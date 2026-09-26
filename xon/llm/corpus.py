"""The A1 corpus (XON_A1_CONSISTENCY.md §5, rev. 2.1): 60 base documents x 3 variants.

Each base document has a plan fixed in advance: a topic, five named people, a premise, an asserted claim, the
relational sentences of the matched control and of the cycle and, for binary documents, the arity sentences.
Claude writes only the consistent variant (i), which must contain the plan's sentences verbatim. The other two
variants are derived from it by string edits, so the three differ only in their planted sentences:
- (ii) direct contradiction: (i) plus the negation of the premise (half the documents) or of the asserted claim,
  inserted at a sentence boundary;
- (iii) cycle contradiction: (i) with the control's differing relational sentence replaced by the cycle's (order and
  equality types), or with the "three values" arity sentence replaced by the "two values" one (binary type).
Plant verification is a string check after whitespace normalization and makes no LLM call (§5).
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

import numpy as np

from .client import LLM, LLMError, LLMTruncated
from .schemas import LeakScan, _Frozen

CYCLE_TYPES = ("order_cycle", "equality_break", "binary_parity")
VARIANTS = ("consistent", "direct", "cycle")
N_BASE = 60
SAMPLE_BASES = (0, 1, 2, 3)     # §8 step 6 and L1-var: 12 documents, 4 per variant type, all three cycle types
MAX_ATTEMPTS = 5
MAX_TOKENS = 4096               # 2048 truncated a draft mid-JSON once (base 10); room for a 300-word document
QUOTE_CHARS = "\"\u201c\u201d"   # straight and curly double quotes; these documents never need quoted speech
MIN_GAP = 2                     # sentences between any two required sentences (no two adjacent)
MIN_SPREAD = 0.5                # required sentences must span at least this fraction of the document's sentences

TOPICS = ("a community garden", "a school chess club", "a village bakery", "a regional cycling race",
          "a choir rehearsal", "a science fair", "a weekend hiking trip", "a pub quiz night", "a pottery class",
          "a rowing regatta", "a library book club", "a robotics workshop", "a farmers' market",
          "a model railway club", "a debate tournament", "a bird-watching walk", "a theatre rehearsal",
          "a charity fun run", "a photography contest", "a beach clean-up")
NAMES = ("Ana", "Ben", "Cy", "Dara", "Eli", "Fay", "Gus", "Hana", "Ivo", "Jun", "Kira", "Leo", "Mina", "Noor",
         "Otto", "Pia", "Quinn", "Rosa", "Sami", "Tess", "Uma", "Vik", "Wren", "Xavi", "Yara", "Zeno", "Alma",
         "Bo", "Cleo", "Dev", "Esme", "Finn", "Gia", "Hugo", "Isla", "Jude", "Kai", "Lena", "Milo", "Nell")
# The greater entity under the extraction prompt's direction rule: the subject, the object, or either (the rule does not
# cover "finished ahead of").
ORDER = (("age", "is older than", "subject"), ("arrival_time", "arrived before", "object"),
         ("height", "is taller than", "subject"), ("rank", "finished ahead of", "either"))
EQUALITY = (("team", "is on the same team as", "is not on the same team as"),
            ("class", "is in the same class as", "is not in the same class as"),
            ("study_group", "is in the same study group as", "is not in the same study group as"))
BINARY = (("team", "{} and {} were on different teams.", "There were two teams.", "There were three teams."),
          ("house", "{} and {} were in different houses.", "The school had two houses.", "The school had three houses."),
          ("shift", "{} and {} worked different shifts.", "The shop ran two shifts.", "The shop ran three shifts."))
ROLES = ("the treasurer", "the team captain", "the event organizer", "the club secretary", "the head judge",
         "the lead volunteer")
ROLE_KEYWORDS = ("treasurer", "captain", "organizer", "secretary", "judge", "volunteer")   # parallel to ROLES
FACTS = (("brought the first-aid kit", "did not bring the first-aid kit"), ("booked the hall", "did not book the hall"),
         ("won the raffle", "did not win the raffle"), ("drove the minibus", "did not drive the minibus"),
         ("took the photographs", "did not take the photographs"))
FACT_KEYWORDS = ("first-aid", "hall", "raffle", "minibus", "photograph")   # parallel to FACTS
# Base 2's default fact ("won the raffle") kept leaking through narrative tone (Vik's excitement, luck) rather than
# restatement, surviving one regeneration under the leak-scan pass (rev. 2.1 §5 tighten re-specification); the user
# swapped it for a neutral logistical fact with no emotional valence to leak through. The pattern recurred in the
# 60-base run (prize and reaction sentences), and the user swapped those bases the same way (re-specification 20).
FACT_OVERRIDES = {2: 0, 7: 0, 12: 0, 17: 0, 22: 0, 37: 0, 47: 0, 57: 0}
TITLES = ("Mr.", "Mrs.", "Ms.", "Dr.", "St.", "Prof.")

# Superlative / universal-extremal cues: two different people assigned the same (attribute, pole) is an accidental
# contradiction in filler (base 32: "Milo arrived first" vs "Quinn … before anyone else"). Report-only until wired
# into verify; patterns cover paraphrases of first/last, not only those words.
_SUPERLATIVE_CUES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("arrival", "earliest", (
        r"arrived first", r"came first", r"showed up first", r"was the first to arrive", r"first to arrive",
        r"before anyone else", r"before everyone else", r"before anyone", r"before everyone",
        r"ahead of everyone", r"ahead of anyone", r"earlier than anyone", r"earliest to arrive",
        r"the first (?:one )?to (?:arrive|show up|come in)",
    )),
    ("arrival", "latest", (
        r"arrived last", r"came last", r"showed up last", r"was the last to arrive", r"last to arrive",
        r"after everyone else", r"after everyone", r"after anyone else", r"later than anyone",
        r"the last (?:one )?to (?:arrive|show up|come in)",
    )),
    ("height", "tallest", (
        r"the tallest", r"tallest of", r"taller than (?:everyone|anyone)(?:\s+else)?",
        r"tallest among", r"tallest in",
    )),
    ("height", "shortest", (
        r"the shortest", r"shortest of", r"shorter than (?:everyone|anyone)(?:\s+else)?",
        r"shortest among", r"shortest in",
    )),
    ("age", "oldest", (
        r"the oldest", r"oldest of", r"older than (?:everyone|anyone)(?:\s+else)?",
        r"oldest among", r"oldest in",
    )),
    ("age", "youngest", (
        r"the youngest", r"youngest of", r"younger than (?:everyone|anyone)(?:\s+else)?",
        r"youngest among", r"youngest in",
    )),
    ("rank", "highest", (
        r"ranked highest", r"the highest rank", r"finished first", r"finished ahead of everyone",
        r"placed first", r"came first in",
    )),
    ("rank", "lowest", (
        r"ranked lowest", r"the lowest rank", r"finished last", r"placed last",
    )),
)

CORPUS_SYSTEM = """You write short, plain documents for a test of contradiction detection.

Write one document of 150 to 300 words about the given topic, in plain prose paragraphs. It must:
- contain every required sentence exactly as written, character for character, each as a sentence of its own, \
each exactly once;
- mention every listed person;
- add several further statements that relate the listed people to each other on attributes such as age, arrival \
time, team, height or ranking, all consistent with the required sentences and with each other;
- spread the required sentences through the document: put at least one further statement between any two of \
them, and do not group them into one part of the document (for example, do not put them all right after the \
opening sentence) — where they appear must not give away which sentences are required;
- follow every restriction listed.
Required sentence 1 is the only assumption in the document: no other sentence may begin with "Assume" or \
"Suppose". Do not hedge, do not cast doubt on any required sentence and do not add contradictions. Do not use \
quotation marks anywhere in the document. Do not give two different people the same superlative or universal \
extremal on the same attribute (for example two people who "arrived first" / "before anyone else", or two who \
are each "the tallest").

Return only the JSON object required by the output schema."""


class DocumentText(_Frozen):
    text: str


@dataclass(frozen=True)
class PlantedRelation:
    """A relational sentence as the extraction prompt should read it; "greater" means a > b on the attribute."""
    sentence: str
    kind: str                       # same | different | greater
    a: str
    b: str
    direction: str = "none"         # greater: "fixed" by the prompt's rule, or "either"; none: same and different


@dataclass(frozen=True)
class Plan:
    base: int
    topic: str
    cycle_type: str
    premise_contradicted: bool      # (ii) negates the premise; otherwise it negates the asserted claim
    people: tuple[str, ...]         # A, B, C (the relational sentences), D (the premise), E (the claim)
    attribute: str
    premise: str
    claim: str
    negation: str                   # the planted negation of the premise or of the claim
    role_keyword: str                # the premise's role, for the no-leak check (e.g. "treasurer")
    claim_keyword: str                # the claim's event, for the no-leak check (e.g. "hall")
    control_relations: tuple[PlantedRelation, ...]   # the relational sentences of (i) and (ii)
    cycle_relations: tuple[PlantedRelation, ...]     # the relational sentences of (iii)
    arity_control: str | None = None   # binary type: the "three values" sentence of (i) and (ii)
    arity_cycle: str | None = None     # binary type: the "two values" sentence of (iii)

    @property
    def control(self) -> tuple[str, ...]:
        return tuple(r.sentence for r in self.control_relations)

    @property
    def cycle(self) -> tuple[str, ...]:
        return tuple(r.sentence for r in self.cycle_relations)

    @property
    def required(self) -> tuple[str, ...]:
        """The sentences Claude must write verbatim into (i)."""
        return (self.premise, self.claim) + self.control + ((self.arity_control,) if self.arity_control else ())


@dataclass
class CorpusRecord:
    doc_id: str
    base: int
    variant: str                    # one of VARIANTS
    cycle_type: str                 # of the base document (the cycle variant's type; the controls match it)
    premise_contradicted: bool
    topic: str
    text: str
    planted: list[str]              # ground truth: the sentences forming the planted contradiction ([] if consistent)
    premises: list[str]
    arity_sentence: str | None      # binary documents: the sentence establishing the number of values
    relations: list[PlantedRelation] = field(default_factory=list)   # the relational sentences (control or cycle)


def plan(base: int) -> Plan:
    """The fixed plan of one base document: each cycle type on every third document (20 each), the premise negated on
    every other one (10 per cycle type), each topic once per cycle type."""
    if not 0 <= base < N_BASE:
        raise ValueError(f"base document {base} outside 0..{N_BASE - 1}")
    cycle_type, topic = CYCLE_TYPES[base % 3], TOPICS[base // 3]
    a, b, c, d, e = np.random.default_rng([20260923, base]).choice(NAMES, size=5, replace=False).tolist()
    role = ROLES[(base // 2) % len(ROLES)]
    fact_index = FACT_OVERRIDES.get(base, base % len(FACTS))
    fact, not_fact = FACTS[fact_index]
    role_keyword, claim_keyword = ROLE_KEYWORDS[(base // 2) % len(ROLES)], FACT_KEYWORDS[fact_index]
    premise, claim = f"Assume that {d} is {role}.", f"{e} {fact}."
    negation = f"{d} is not {role}." if base % 2 == 0 else f"{e} {not_fact}."
    arity_control = arity_cycle = None
    if cycle_type == "order_cycle":
        attribute, phrase, greater = ORDER[(base // 3) % len(ORDER)]

        def rel(x, y):
            return PlantedRelation(f"{x} {phrase} {y}.", "greater", *((y, x) if greater == "object" else (x, y)),
                                   "either" if greater == "either" else "fixed")
        control = (rel(a, b), rel(b, c), rel(a, c))
        cycle = control[:2] + (rel(c, a),)
    elif cycle_type == "equality_break":
        attribute, same, different = EQUALITY[(base // 3) % len(EQUALITY)]

        def rel(x, y, kind):
            return PlantedRelation(f"{x} {same if kind == 'same' else different} {y}.", kind, x, y)
        cycle = (rel(a, b, "same"), rel(b, c, "same"), rel(a, c, "different"))
        control = (cycle[0], rel(b, c, "different"), cycle[2])     # both relation types, arranged consistently
    else:
        attribute, template, arity_cycle, arity_control = BINARY[(base // 3) % len(BINARY)]
        control = cycle = tuple(PlantedRelation(template.format(x, y), "different", x, y)
                                for x, y in ((a, b), (b, c), (a, c)))
    return Plan(base, topic, cycle_type, base % 2 == 0, (a, b, c, d, e), attribute, premise, claim, negation,
                role_keyword, claim_keyword, control, cycle, arity_control, arity_cycle)


def corpus_user(p: Plan, attempt: int = 1, problems: list[str] | None = None) -> str:
    a, b, c, d, e = p.people
    lines = [f"Topic: {p.topic}", f"People: {', '.join(p.people)}", "", "Required sentences:"]
    lines += [f"{k}. {s}" for k, s in enumerate(p.required, start=1)]
    lines += ["", "Restrictions:",
              f"- No further statement may compare {a}, {b} and {c} with each other on {p.attribute.replace('_', ' ')}.",
              f"- No further statement may say who is or is not {p.premise.split(' is ', 1)[1].rstrip('.')}, or "
              f"refer to that role, directly or indirectly, other than in sentence 1.",
              f"- No further statement may repeat, deny, or refer back to sentence 2's claim, directly or "
              f"indirectly, other than sentence 2 itself.",
              "- More generally: no sentence but the required ones may describe, hint at, or make guessable any "
              "person's planted role or relationship, or any planted fact's subject matter — literally or "
              "indirectly, including by describing what it implies."]
    if p.cycle_type != "order_cycle":
        noun = {"team": "teams", "class": "classes", "study_group": "study groups", "house": "houses",
                "shift": "shifts"}[p.attribute]
        lines.append(f"- Do not say how many {noun} there are" + (" except in the required sentence that does."
                                                                  if p.arity_control else "."))
    if attempt > 1:
        lines += ["", f"Attempt {attempt}: an earlier draft had these problems: "
                  + "; ".join(problems or ["left out or changed a required sentence"])
                  + ". Fix them without changing anything else."]
    return "\n".join(lines)


LEAK_QA_SYSTEM = """You are checking a test document for information leaks, not writing it.

The document plants some sentences as the only place certain facts should appear. Every other sentence must not \
reveal, hint at, or make guessable any of these facts — not by name, and not indirectly, for example by \
describing someone doing the kind of thing their planted role would do, or by restating the outcome or subject \
matter of a planted event in different words.

You will be given the planted sentences, the planted attribute (if any) and the full document. List every other \
sentence that leaks one of the planted facts: quote it verbatim and say, in one sentence, which planted fact it \
leaks and why. If none do, return an empty list.

Do not flag:
- a sentence that only repeats a person's name, or an unrelated detail;
- a sentence that restates a planted sentence in close to the same wording (that is already checked separately);
- a comparison on a different attribute than the planted one (height, ranking, team, arrival time, age, or any \
other), even between people who also appear in a planted relation — that is expected filler. Flag such a \
comparison only if it specifically implies the planted attribute's value or order (for example, calling someone \
\"the oldest\" when the plant is age order, or saying two people \"work separately\" when the plant is that \
they are not on the same team).

Return only the JSON object required by the output schema."""


def leak_qa_user(p: Plan, text: str) -> str:
    lines = ["Planted sentences (the only place these facts should appear):"]
    lines += [f"- {s}" for s in p.required]
    lines += ["", f"Planted attribute: {p.attribute.replace('_', ' ')} "
              f"(comparisons on other attributes are expected filler; see the instructions).",
              "", "Document:", text]
    return "\n".join(lines)


def scan_leaks(llm: LLM, p: Plan, text: str, *, tag: str) -> list[dict]:
    """A second, independent QA pass (§5 rev. 2.1 tighten re-specification): a separate call, with its own
    prompt, outside the scored extraction/relation pipeline, reads the accepted draft for paraphrased leaks the
    keyword check in `verify` cannot see. It only reports flags; it does not regenerate — the user makes the
    final call per flagged document."""
    out = llm.parse(system=LEAK_QA_SYSTEM, user=leak_qa_user(p, text), schema=LeakScan, max_tokens=1024,
                    thinking=False, tag=tag)
    return [f.model_dump() for f in out.flags]


# ------------------------------------------------------------------------------------------ variants and verification
def normalize_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _boundaries(text: str) -> list[int]:
    """Offsets where a sentence may be inserted: after a sentence end followed by whitespace and a capital letter
    (not after a title such as "Dr."), and the end of the text."""
    out = [m.start() for m in re.finditer(r"(?<=[.!?])\s+(?=[A-Z])", text)
           if not text[:m.start()].split()[-1] in TITLES]
    return out + [len(text.rstrip())]


def build_variants(p: Plan, text: str) -> list[CorpusRecord]:
    """(i), (ii), (iii) from Claude's text for (i); a missing sentence makes an edit a no-op, which verification
    reports."""
    text = text.strip()
    spots = _boundaries(text)
    at = spots[int(np.random.default_rng([20260923, p.base, 1]).integers(len(spots)))]
    direct = text[:at] + " " + p.negation + text[at:]
    if p.cycle_type == "binary_parity":
        cycle_text = text.replace(p.arity_control, p.arity_cycle)
    else:
        [(old, new)] = [(o, n) for o, n in zip(p.control, p.cycle) if o != n]
        cycle_text = text.replace(old, new)
    negated = p.premise if p.premise_contradicted else p.claim
    common = dict(base=p.base, cycle_type=p.cycle_type, premise_contradicted=p.premise_contradicted, topic=p.topic,
                  premises=[p.premise])
    return [CorpusRecord(f"b{p.base:02d}-consistent", variant="consistent", text=text, planted=[],
                         arity_sentence=p.arity_control, relations=list(p.control_relations), **common),
            CorpusRecord(f"b{p.base:02d}-direct", variant="direct", text=direct, planted=[negated, p.negation],
                         arity_sentence=p.arity_control, relations=list(p.control_relations), **common),
            CorpusRecord(f"b{p.base:02d}-cycle", variant="cycle", text=cycle_text,
                         planted=list(p.cycle) + ([p.arity_cycle] if p.arity_cycle else []),
                         arity_sentence=p.arity_cycle, relations=list(p.cycle_relations), **common)]


def _sentence_spans(text: str) -> list[tuple[int, int]]:
    """The (start, end) offset of each sentence, split at the same boundaries used to insert the negation."""
    bounds = _boundaries(text)
    return list(zip([0] + bounds[:-1], bounds))


def _sentence_index(spans: list[tuple[int, int]], text: str, sentence: str) -> int | None:
    """Which sentence span a sentence's first occurrence falls in, or None if it is not found (already reported
    by the missing-sentence check)."""
    m = re.search(r"(?<![A-Za-z])" + re.escape(sentence), text)
    if not m:
        return None
    return next((i for i, (s, e) in enumerate(spans) if s <= m.start() < e), len(spans) - 1)


def _spread_problems(text: str, sentences: tuple[str, ...]) -> list[str]:
    """The required sentences must not sit in adjacent sentences or all bunch within one stretch of the document:
    position must not be a tell (§5 rev. 2.1, spread re-specification). A string check on the same boundaries as
    the rest of plant verification; no extraction, relation or entity call."""
    spans = _sentence_spans(text)
    positions = sorted(i for s in sentences if (i := _sentence_index(spans, text, s)) is not None)
    if len(positions) < 2:
        return []
    problems = []
    if any(b - a < MIN_GAP for a, b in zip(positions, positions[1:])):
        problems.append("adjacent required sentences")
    if (positions[-1] - positions[0]) / max(len(spans) - 1, 1) < MIN_SPREAD:
        problems.append("required sentences clustered in one stretch of the document")
    return problems


def _leak_problems(text: str, must: list[str], keywords: tuple[str, ...]) -> list[str]:
    """No sentence but the required ones may refer to the premise's role or the claim's event (§5 rev. 2.1,
    tighten re-specification). A keyword check on ROLES/FACTS's fixed, closed vocabulary (e.g. "hall" for
    "booked the hall"): a fully semantic check of indirect reference would need the pipeline this verification
    must not use, so paraphrases that avoid the keyword are left to review, not caught here."""
    residual = text
    for s in must:
        residual = residual.replace(s, "", 1)
    residual = residual.lower()
    return [f"refers to '{kw}' outside the required sentences" for kw in keywords if kw.lower() in residual]


def _sentence_texts(text: str) -> list[str]:
    """Sentence strings using the same boundaries as plant verification."""
    return [text[s:e].strip() for s, e in _sentence_spans(text) if text[s:e].strip()]


def _owners_of_cue(sentence: str, people: tuple[str, ...] | list[str], cue: str) -> list[str]:
    """People the cue is attributed to: the nearest listed name before the cue in the sentence (so
    'Esme mentioned that Leo was the tallest' credits Leo, not Esme)."""
    match = re.search(rf"(?i)(?:{cue})", sentence)
    if not match:
        return []
    prefix = sentence[:match.start()]
    found: list[tuple[int, str]] = []
    for person in people:
        for m in re.finditer(rf"(?<![A-Za-z]){re.escape(person)}(?![A-Za-z])", prefix):
            found.append((m.end(), person))
    if not found:
        return []
    found.sort()
    return [found[-1][1]]


def superlative_collisions(text: str, people: tuple[str, ...] | list[str]) -> list[dict]:
    """Two different people given the same superlative / universal extremal on the same attribute.

    Catches 'arrived first' vs 'before anyone else' / 'ahead of everyone', not only the words first and last.
    A string check only; used as a corpus QA report and in plant verification."""
    sentences = _sentence_texts(text)
    owned: dict[tuple[str, str], dict[str, list[str]]] = {}
    for attribute, pole, cues in _SUPERLATIVE_CUES:
        for sent in sentences:
            for cue in cues:
                for person in _owners_of_cue(sent, people, cue):
                    owned.setdefault((attribute, pole), {}).setdefault(person, [])
                    if sent not in owned[(attribute, pole)][person]:
                        owned[(attribute, pole)][person].append(sent)
    hits = []
    for (attribute, pole), by_person in owned.items():
        if len(by_person) < 2:
            continue
        names = sorted(by_person)
        sents: list[str] = []
        seen: set[str] = set()
        for n in names:
            for s in by_person[n]:
                if s not in seen:
                    seen.add(s)
                    sents.append(s)
        hits.append({"attribute": attribute, "pole": pole, "people": names, "sentences": sents})
    return hits


def _superlative_problems(text: str, people: tuple[str, ...]) -> list[str]:
    return [f"superlative collision on {h['attribute']}/{h['pole']}: {', '.join(h['people'])}"
            for h in superlative_collisions(text, people)]


def occurrences(text: str, sentence: str) -> int:
    """How often a sentence occurs in a text, after whitespace normalization, starting at a word boundary (so that
    "Ana is older than Ben." does not match inside "Hana is older than Ben.")."""
    return len(re.findall(r"(?<![A-Za-z])" + re.escape(normalize_ws(sentence)), normalize_ws(text)))


def verify(p: Plan, r: CorpusRecord) -> list[str]:
    """Problems with one variant: a required or planted sentence missing or repeated, a sentence of another
    variant present, a stray quotation mark, or (on the consistent variant, where Claude chooses positions) the
    required sentences bunched together. A string check only: no extraction, relation or entity call (§5)."""
    arity_control, arity_cycle = (p.arity_control,) if p.arity_control else (), (p.arity_cycle,) if p.arity_cycle else ()
    must = [p.premise, p.claim] + list(p.cycle + arity_cycle if r.variant == "cycle" else p.control + arity_control)
    must += [p.negation] if r.variant == "direct" else []
    if r.variant == "cycle":
        banned = [s for s in p.control + arity_control if s not in p.cycle + arity_cycle] + [p.negation]
    else:
        banned = [s for s in p.cycle + arity_cycle if s not in p.control + arity_control]
        banned += [] if r.variant == "direct" else [p.negation]
    problems = [f"missing: {s}" for s in must if occurrences(r.text, s) == 0]
    problems += [f"repeated: {s}" for s in must if occurrences(r.text, s) > 1]
    problems += [f"present: {s}" for s in banned if occurrences(r.text, s) > 0]
    problems += ["stray quotation mark"] if any(ch in r.text for ch in QUOTE_CHARS) else []
    problems += _leak_problems(r.text, must, (p.role_keyword, p.claim_keyword))
    from .corpus_qa import activity_synonym_hits, same_attribute_hits, order_cycle_scan
    problems += [f"activity synonym '{h['keyword']}' outside planted sentences"
                 for h in activity_synonym_hits(r.text, p, exclude=must)]
    if r.variant == "consistent":
        problems += [f"same-attribute filler on {h['attribute']}: {', '.join(h['people'])}"
                     for h in same_attribute_hits(r.text, p, exclude=must)]
        problems += _spread_problems(r.text, p.required)
    problems += _superlative_problems(r.text, p.people)
    unplanted = order_cycle_scan(r.text, p.people, exclude_sentences=must)["cycles_unplanted"]
    problems += [f"unplanted order cycle on {c['attribute']}: {' > '.join(c['entities'])}"
                 for c in unplanted]
    return problems


def generate(llm: LLM, plans: list[Plan], *, max_attempts: int = MAX_ATTEMPTS, log=print,
            qa_scan: bool = False, review_problems: dict[int, list[str]] | None = None) -> tuple[list, dict]:
    """Claude writes (i) for each plan; the variants are derived and verified, and a plan whose variants fail
    verification is regenerated (with the failing problems fed back, so the cache does not return the same
    draft). A plan that only passes on the final attempt is flagged: the retries exist only to satisfy the
    structural constraints (verified the same pipeline-independent way as the plant check itself), never to
    search for a draft that scores better downstream, so a document that needed every attempt is not silently
    accepted. With `qa_scan`, an accepted document's consistent variant is also read by the independent leak-scan
    pass (`scan_leaks`); any flags are reported in `stats["leak_flags"]`, not acted on automatically.
    `review_problems` regenerates a base against problems a review found in its previous draft: the first request is
    attempt 2 and states them in the retry message, since an unchanged request would replay that draft from the
    cache."""
    records, stats = [], {"plans": len(plans), "regenerated": 0, "failed": {}, "attempts": {}, "flagged": [],
                         "leak_flags": {}}
    for p in plans:
        problems: list[str] = list((review_problems or {}).get(p.base, []))
        for attempt in range(2 if problems else 1, max_attempts + 1):
            try:
                out = llm.parse(system=CORPUS_SYSTEM, user=corpus_user(p, attempt, problems), schema=DocumentText,
                                max_tokens=MAX_TOKENS, thinking=False, tag=f"corpus-b{p.base:02d}-a{attempt}")
            except LLMTruncated:
                # Truncation is not cached; treat it as a failed draft and retry with a changed request, same as
                # plant-verification failures. Raising would abort the whole corpus for one overlong draft.
                problems = ["response truncated (hit max_tokens)"]
                stats["attempts"][p.base] = attempt
                stats["regenerated"] += attempt < max_attempts
                log(f"base {p.base}, attempt {attempt}: {problems[0]}")
                continue
            except LLMError as exc:
                stats["failed"][p.base] = [f"{type(exc).__name__}: {exc}"]
                log(f"base {p.base}: {type(exc).__name__}: {exc}")
                break
            variants = build_variants(p, out.text)
            problems = [f"{r.variant}: {x}" for r in variants for x in verify(p, r)]
            stats["attempts"][p.base] = attempt
            if not problems:
                if attempt == max_attempts:
                    stats["flagged"].append(p.base)
                    log(f"base {p.base}: passed only on the final attempt ({max_attempts}); flagged for review")
                if qa_scan:
                    flags = scan_leaks(llm, p, variants[0].text, tag=f"corpus-b{p.base:02d}-qa")
                    if flags:
                        stats["leak_flags"][p.base] = flags
                        log(f"base {p.base}: the leak-scan pass flagged {len(flags)} sentence(s) for review")
                from .corpus_qa import qa_record
                stats.setdefault("deterministic_qa", {})[p.base] = [qa_record(p, r) for r in variants]
                records += variants
                break
            stats["regenerated"] += attempt < max_attempts
            log(f"base {p.base}, attempt {attempt}: {'; '.join(problems)}")
        else:
            stats["failed"][p.base] = problems
    return records, stats


def record_to_dict(r: CorpusRecord) -> dict:
    return asdict(r)
