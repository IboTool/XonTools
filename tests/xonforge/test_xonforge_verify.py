"""XonForge's structural checks and deterministic scans (XONFORGE_SPEC.md §7.1, §7.2; §13; §14, step 4; the user's
items 1, 2, 4, 5 and 6 of 2026-09-25), and the renderer's check they make together. Offline: renderings are built
from the skeletons' own wording."""
import inspect
import json
import re
from pathlib import Path

import pytest

from xonforge.render.phrasing import statement
from xonforge.render.renderer import render
from xonforge.render.schema import Rendering, RenderRules, SpanEntry
from xonforge.skeleton.catalog import CATEGORICAL, ORDINAL
from xonforge.skeleton.generators import PLANT_TYPES, Knobs, generate
from xonforge.verify import canaries, scanners, scans, sentences
from xonforge.verify.checks import check, finalize
from xonforge.verify.structural import length_range, measure, spread_problems
from xonforge.verify.structural import structural as structural_checks

from xonforge_fakes import FakeClient, anthropic_response, caller, entry

RULES = RenderRules(words=300, explicitness="stated", lexical_variety="low", min_spacing=2)
FILLER = "Item {} on the agenda was the printer schedule for the coming week at the main office."
XONFORGE = Path(__file__).resolve().parents[2] / "xonforge"


def fit(r, **update):
    """RULES, with the target length the rendering's own, so that only what a test looks at can fail."""
    return RULES.model_copy(update={"words": min(3000, max(150, len(r.text.split()))), **update})


def structural(skeleton, r, rules=None):
    return structural_checks(skeleton, r, rules or fit(r))


def made(plant_type="order_cycle", seed=1, knobs=Knobs(entities=5, distractors=1), **kw):
    kw = {"premise": True, **kw} if plant_type == "direct_negation" else kw
    return generate(plant_type, seed=seed, genre="office memo", knobs=knobs, **kw)


def planted(plant_type="order_cycle", seed=1, knobs=Knobs(entities=5, distractors=1)):
    return made(plant_type, seed, knobs).planted[0]


def sentence(fact, skeleton):
    s = ("Assume that " if fact.kind == "premise" and not fact.states_arity else "") + statement(fact, skeleton) + "."
    return s[0].upper() + s[1:]


def rendering(skeleton, *, gap=3, replace=None, extra=(), spans=None):
    """Each fact's sentence after ``gap`` filler sentences, then ``extra`` sentences and two more of filler.
    ``replace``: a fact id's sentence to write instead of its own, reported as its span."""
    replace = replace or {}
    filler = iter(FILLER.format(i) for i in range(1, 1000))
    parts, entries = [], []
    for f in skeleton.facts:
        s = replace.get(f.id, sentence(f, skeleton))
        parts += [next(filler) for _ in range(gap)] + [s]
        entries.append(SpanEntry(fact=f.id, span=s))
    text = " ".join(parts + list(extra) + [next(filler), next(filler)])
    return Rendering(text=text, spans=entries if spans is None else spans)


def name(skeleton, entity_id):
    return next(e.name for e in skeleton.entities if e.id == entity_id)


def fact(skeleton, fid):
    return next(f for f in skeleton.facts if f.id == fid)


def one(problems, needle):
    found = [p for p in problems if needle in p]
    assert len(found) == 1, problems
    return found[0]


# ------------------------------------------------------------------------------------------ what passes
SWEEP = [Knobs(entities=5, distractors=1), Knobs(cycle_length=5, entities=8, attributes=3, distractors=2),
         Knobs(cycle_length=4, entities=6, attributes=3, distractors=3, same_attribute_distractors=True)]


@pytest.mark.parametrize("plant_type", PLANT_TYPES)
def test_a_rendering_in_the_skeleton_s_own_wording_passes_every_check_and_scan(plant_type):
    for knobs in SWEEP:
        if plant_type == "direct_negation":
            knobs = Knobs(entities=knobs.entities, attributes=knobs.attributes, distractors=knobs.distractors,
                          same_attribute_distractors=knobs.same_attribute_distractors)
        for seed in range(12):
            b = made(plant_type, seed, knobs, **({"traps": ("arity_control",)} if plant_type == "binary_parity"
                                                  else {}))
            for sk in (b.consistent, *b.planted, *b.trap_only):
                r = rendering(sk)
                assert check(sk, r, fit(r)) == [], (plant_type, knobs, seed, sk.variant)


# ------------------------------------------------------------------------------------------ spans (§13)
def test_a_missing_unknown_doubled_or_unfound_span_is_reported():
    sk = planted()
    r = rendering(sk)
    first, second = r.spans[0], r.spans[1]
    missing = Rendering(text=r.text, spans=r.spans[1:])
    assert one(structural(sk, missing), f"no span was given for fact {first.fact}")
    unknown = Rendering(text=r.text, spans=r.spans + [SpanEntry(fact="f99", span=first.span)])
    assert one(structural(sk, unknown), "spans were given for f99, which is not a listed fact")
    doubled = Rendering(text=r.text, spans=r.spans + [first])
    assert one(structural(sk, doubled), f"fact {first.fact} was given 2 spans")
    unfound = Rendering(text=r.text, spans=[SpanEntry(fact=first.fact, span=first.span.lower())] + r.spans[1:])
    assert one(structural(sk, unfound), f"the span for fact {first.fact} is not in the text character")


def test_a_span_must_be_one_whole_sentence_of_its_own_stated_once():
    sk = planted()
    r = rendering(sk)
    first, second = r.spans[0], r.spans[1]
    part = Rendering(text=r.text, spans=[SpanEntry(fact=first.fact, span=first.span[:-1])] + r.spans[1:])
    assert one(structural(sk, part), f"the span for fact {first.fact} is not one whole sentence")
    twice = rendering(sk, extra=[first.span])
    assert one(structural(sk, twice), f"the sentence for fact {first.fact} appears 2 times")
    both = first.span[:-1] + ", and " + second.span[0].lower() + second.span[1:]
    shared = rendering(sk, replace={first.fact: both, second.fact: both})
    assert one(structural(sk, shared), f"facts {first.fact} and {second.fact} share one sentence")


# ------------------------------------------------------------------------------------------ what a span states
def test_a_wrong_or_extra_number_in_a_stated_number_of_values_is_caught():
    sk = planted("binary_parity")
    arity = sk.arity_fact
    good = sentence(fact(sk, arity), sk)
    assert "two" in good
    wrong = structural(sk, rendering(sk, replace={arity: good.replace("two", "three")}))
    assert one(wrong, f"the sentence for fact {arity} must state the number two:")
    extra = structural(sk, rendering(sk, replace={arity: good[:-1] + ", not three."}))
    assert one(extra, f"the sentence for fact {arity} must state the number two and no other (three)")
    assert structural(sk, rendering(sk, replace={arity: good.replace("two", "2")})) == []


def test_a_value_must_be_named_and_a_negation_kept_exactly_where_the_fact_has_one():
    sk = planted("direct_negation")
    claim, negation = sk.plant.params["negated_claim"], sk.plant.params["negation"]
    value = fact(sk, negation).value
    other = next(v for v in ("red", "blue", "chess", "drama", "sales", "design", "one", "two", "north", "south")
                 if v != value and v not in sentence(fact(sk, negation), sk))
    changed = sentence(fact(sk, negation), sk).replace(f" {value}", f" {other}")
    assert one(structural(sk, rendering(sk, replace={negation: changed})), f"must name the value {value}")
    dropped = sentence(fact(sk, negation), sk).replace(" not ", " ")
    assert one(structural(sk, rendering(sk, replace={negation: dropped})), "must say that it does not hold")
    added = sentence(fact(sk, claim), sk).replace(" is ", " is not ")
    assert one(structural(sk, rendering(sk, replace={claim: added})), "must state it without a negation")
    contracted = sentence(fact(sk, negation), sk).replace(" is not ", " isn\u2019t ")
    assert structural(sk, rendering(sk, replace={negation: contracted})) == []


def test_a_fact_s_people_must_be_named_in_its_sentence():
    sk = planted()
    f = fact(sk, sk.plant.facts[0])
    pronoun = sentence(f, sk).replace(name(sk, f.subject), "She", 1)
    assert one(structural(sk, rendering(sk, replace={f.id: pronoun})),
               f"the sentence for fact {f.id} must name {name(sk, f.subject)}")


INVERSE = {"is older than": ("is younger than", "is not older than"),
           "is taller than": ("is shorter than", "is not taller than"),
           "arrived later than": ("arrived earlier than", "did not arrive later than"),
           "scored higher than": ("scored lower than", "did not score higher than"),
           "is faster than": ("is slower than", "is not faster than")}


@pytest.mark.parametrize("seed", range(5))
def test_a_comparison_must_run_the_right_way_without_a_negation(seed):
    sk = planted("order_cycle", seed)
    f = fact(sk, sk.plant.facts[0])
    s, o = name(sk, f.subject), name(sk, f.object)
    phrase = next(p for p in INVERSE if p in sentence(f, sk))
    inverse, negated = INVERSE[phrase]
    assert one(structural(sk, rendering(sk, replace={f.id: f"{o} {phrase} {s}."})), "the wrong way round")
    assert structural(sk, rendering(sk, replace={f.id: f"{o} {inverse} {s}."})) == []
    assert one(structural(sk, rendering(sk, replace={f.id: f"{s} {negated} {o}."})), "without a negation")


def test_a_shared_group_and_a_difference_keep_their_sense():
    sk = planted("equality_break")
    facts = [fact(sk, i) for i in sk.plant.facts]
    same = next(f for f in facts if f.relation == "same")
    different = next(f for f in facts if f.relation == "different")
    s1, o1 = name(sk, same.subject), name(sk, same.object)
    s2, o2 = name(sk, different.subject), name(sk, different.object)
    noun = same.attribute
    broken = {same.id: f"{s1} is not in the same {noun} as {o1}.", different.id: f"{s2} shares a {noun} with {o2}."}
    problems = structural(sk, rendering(sk, replace=broken))
    assert one(problems, f"the sentence for fact {same.id} must say that the two share their {noun}")
    assert one(problems, f"the sentence for fact {different.id} must say that the two differ in their {noun}")
    fine = {same.id: f"{s1} and {o1} share a {noun}.", different.id: f"{s2} is not in the same {noun} as {o2}."}
    assert structural(sk, rendering(sk, replace=fine)) == []


# ------------------------------------------------------------------------------------------ the constants (§13)
def test_a_planted_entity_named_with_the_planted_attribute_outside_the_planted_sentences_is_forbidden():
    sk = planted("order_cycle", seed=2)
    attribute = sk.plant.params["attribute"]
    who = name(sk, sk.plant.params["entities"][0])
    outsider = next(e.name for e in sk.entities if e.id not in sk.plant.params["entities"])
    word = {"age": "was the oldest in the room", "height": "was the tallest in the room",
            "arrival": "arrived with the coffee", "score": "scored well", "speed": "was the fastest"}[attribute]
    leak = structural(sk, rendering(sk, extra=[f"{who} {word}."]))
    assert one(leak, f"no sentence may mention {who} together with their")
    assert structural(sk, rendering(sk, extra=[f"{outsider} {word}."])) == []


def test_the_arity_sentence_is_exempt_from_forbidden_content():
    sk = planted("binary_parity")
    arity = sk.arity_fact
    who = name(sk, sk.plant.params["entities"][0])
    noun = sk.plant.params["attribute"]
    named = f"There are exactly two {noun}s, and {who} knows it."
    assert structural(sk, rendering(sk, replace={arity: named})) == []


def test_a_twin_s_and_a_trap_variant_s_planted_sentences_are_checked_like_a_plant_s():
    b = made("binary_parity", seed=3, traps=("arity_control",))
    who = name(b.consistent, b.planted[0].plant.params["entities"][0])
    noun = b.planted[0].plant.params["attribute"]
    for sk, planted_ids in ((b.consistent, b.consistent.twin_facts), (b.trap_only[0], b.planted[0].plant.facts)):
        assert sk.planted_facts() == planted_ids and sk.arity_fact not in planted_ids
        leak = structural(sk, rendering(sk, extra=[f"{who} changed {noun}s last spring."]))
        assert one(leak, f"no sentence may mention {who} together with their {noun}")
        tight = rendering(sk, gap=0)
        spacing = [p for p in structural(sk, tight, fit(tight, min_spacing=10))
                   if p.endswith("put at least 10 between them")]
        assert spacing and {f for p in spacing for f in re.findall(r"f\d+", p)} <= set(planted_ids)
        named = f"There are exactly {'two' if sk is b.consistent else 'three'} {noun}s, and {who} knows it."
        assert structural(sk, rendering(sk, replace={sk.arity_fact: named})) == []


def test_quotation_marks_a_length_out_of_its_tolerance_and_adjacent_planted_sentences_are_caught():
    sk = planted()
    quoted = rendering(sk, extra=["The memo was titled \u201cSpring plans\u201d this year."])
    assert one(structural(sk, quoted), "the text uses quotation marks")
    short = rendering(sk, gap=0)
    problems = structural(sk, short, RULES)
    assert one(problems, f"the text has {len(short.text.split())} words, and must have 255 to 345; write about 300")
    spacing = [p for p in problems if p.endswith("put at least 2 between them")]
    assert spacing and all(re.match(r"only [01] other sentences? separates? the sentences for facts f\d+ and f\d+;", p)
                           for p in spacing)


@pytest.mark.parametrize("target, low, high", [(150, 125, 175), (170, 145, 195), (300, 255, 345), (800, 680, 920),
                                               (3000, 2550, 3450)])
def test_the_length_is_within_15_percent_of_the_target_and_at_least_25_words(target, low, high):
    assert length_range(target) == (low, high)


def test_a_text_outside_its_length_tolerance_fails_the_length_check():
    sk = planted()
    r = rendering(sk)
    words = len(r.text.split())

    def failed(target):
        return any("words, and must have" in p for p in structural(sk, r, RULES.model_copy(update={"words": target})))

    assert not failed(words) and not failed(words + 25) and failed(2 * words)


def laid_out(skeleton, at, total=20):
    """The skeleton's facts' sentences at the sentence indices ``at``, in the facts' order, and filler elsewhere."""
    filler = iter(FILLER.format(i) for i in range(1, 1000))
    placed = dict(zip(at, skeleton.facts))
    parts, entries = [], []
    for i in range(total):
        if i in placed:
            parts.append(sentence(placed[i], skeleton))
            entries.append(SpanEntry(fact=placed[i].id, span=parts[-1]))
        else:
            parts.append(next(filler))
    return Rendering(text=" ".join(parts), spans=entries)


def test_the_level_s_spread_of_the_planted_sentences_is_checked():
    sk = generate("order_cycle", seed=1, genre="g").planted[0]
    assert len(sk.facts) == len(sk.plant.facts) == 3
    half, quarters = (RULES.model_copy(update={"spread": s}) for s in ("half", "quarters"))
    assert spread_problems(sk, laid_out(sk, (0, 2, 4)), RULES) == []
    assert one(spread_problems(sk, laid_out(sk, (0, 2, 4)), half), "over at least half of the document")
    assert spread_problems(sk, laid_out(sk, (2, 8, 14)), half) == []
    assert spread_problems(sk, laid_out(sk, (0, 10, 19)), quarters) == []
    late = spread_problems(sk, laid_out(sk, (6, 10, 19)), quarters)
    assert late == [f"the first of the sentences for facts {', '.join(sk.plant.facts[:-1])} and {sk.plant.facts[-1]}, "
                    f"fact {sk.facts[0].id}'s, begins after the first quarter of the document; put it within the first "
                    "quarter"]
    early = spread_problems(sk, laid_out(sk, (0, 10, 13)), quarters)
    assert len(early) == 1 and "begins before the last quarter" in early[0]
    m = measure(sk, laid_out(sk, (0, 10, 19)))
    assert m["words_before_first_planted"] == 0 and m["planted_words"] == m["words"]
    assert 4 * m["words_before_last_planted"] >= 3 * m["words"]


@pytest.mark.parametrize("seed", range(4))
def test_what_is_measured_after_rendering(seed):
    sk = planted("direct_negation", seed)
    r = rendering(sk, gap=3)
    m = measure(sk, r)
    assert m["words"] == len(r.text.split()) and m["sentences"] == 4 * len(sk.facts) + 2
    ids = [f.id for f in sk.facts]
    i, j = sorted(ids.index(p) for p in sk.plant.facts)
    between = ids[i + 1:j]
    assert m["min_spacing"] == 3 * (j - i) + len(between)
    assert m["plant_distance"] == (sum(len(sentence(fact(sk, b), sk).split()) for b in between)
                                   + 3 * (j - i) * len(FILLER.format(1).split()))


# ------------------------------------------------------------------------------------------ the scans
def team_plant():
    """An equality break on teams: the one categorical attribute A1's same-attribute cues cover."""
    return next(sk for sk in (planted("equality_break", seed) for seed in range(60))
                if sk.plant.params["attribute"] == "team")


def test_the_scans_catch_a_superlative_clash_an_unplanted_cycle_and_a_same_attribute_leak():
    sk = team_plant()
    a, b, c = [name(sk, e) for e in sk.plant.params["entities"]][:3]
    clash = rendering(sk, extra=[f"Later, {a} arrived first.", f"By all accounts {b} was the first to arrive."])
    assert one(check(sk, clash, RULES), "are each given the same superlative on arrival (earliest)")
    attribute, phrase = next((k, p) for k, p in (("age", "is older than"), ("height", "is taller than"))
                             if k not in {x.key for x in sk.attributes})
    cycle = rendering(sk, extra=[f"{a} {phrase} {b}.", f"{b} {phrase} {c}.", f"{c} {phrase} {a}."])
    found = one(check(sk, cycle, RULES), f"in a circle on {attribute}")
    assert found.startswith("sentences other than the sentences for facts")
    leak = rendering(sk, extra=[f"{a} and {b} were on the same team last year."])
    assert one(check(sk, leak, RULES), f"no sentence may relate {' and '.join(sorted([a, b]))} on their team")


def test_the_scans_wait_for_whole_planted_sentences():
    sk = team_plant()
    a, b = [name(sk, e) for e in sk.plant.params["entities"][:2]]
    r = rendering(sk, extra=[f"Later, {a} arrived first.", f"By all accounts {b} was the first to arrive."])
    first = r.spans[0]
    broken = Rendering(text=r.text, spans=[SpanEntry(fact=first.fact, span=first.span[:-1])] + r.spans[1:])
    problems = check(sk, broken, RULES)
    assert any("not one whole sentence" in p for p in problems)
    assert not any("superlative" in p for p in problems)


def test_every_scan_has_patterns_for_every_attribute_of_xonforge_s_it_reads():
    ordinal, categorical = sorted(ORDINAL), sorted(CATEGORICAL)
    assert ordinal == ["age", "arrival", "height", "score", "speed"]
    assert categorical == ["cabin", "club", "department", "table", "team"]
    covered = {s: sorted(a for a in ordinal + categorical if scans.covers(s, a)) for s in scans.SCANS}
    assert covered == {"superlative_collisions": ordinal, "order_cycles": ordinal,
                       "same_attribute": sorted(ordinal + categorical)}
    assert set(scans.NOT_REUSED) == {"activity_synonyms"}


def test_the_order_cycle_scan_reads_a1_s_wording_and_the_skeletons_each_way_round():
    def cycles(text):
        return [c["attribute"] for c in scans.run("order_cycles", text, ["Ada", "Ben", "Cleo"])]
    assert cycles("Ada arrived before Ben. Ben arrived before Cleo. Cleo arrived before Ada.") == ["arrival"]
    assert cycles("Ada arrived later than Ben. Ben arrived later than Cleo. Cleo arrived later than Ada.") == [
        "arrival"]
    assert cycles("Ada arrived before Ben. Ben arrived earlier than Cleo. Cleo arrived earlier than Ada.") == [
        "arrival"]
    assert cycles("Ada arrived before Ben. Ben arrived earlier than Cleo. Cleo arrived later than Ada.") == []
    assert cycles("Ada outscored Ben. Ben scored higher than Cleo. Cleo scored higher than Ada.") == ["score"]
    assert cycles("Ada outscored Ben. Ben scored higher than Cleo. Cleo scored lower than Ada.") == []
    assert cycles("Ada was faster than Ben. Ben is quicker than Cleo. Cleo was faster than Ada.") == ["speed"]
    assert cycles("Ada was faster than Ben. Ben is quicker than Cleo. Cleo was slower than Ada.") == []


def test_the_copied_scans_and_sentences_are_a1_s_as_they_stand():
    from xon.llm import corpus, corpus_qa
    assert scanners.A1_SUPERLATIVE_CUES == corpus._SUPERLATIVE_CUES
    assert scanners.A1_ORDER_PATTERNS == corpus_qa._ORDER_PATTERNS
    assert scanners.A1_ATTRIBUTE_CUES == corpus_qa._ATTRIBUTE_CUES
    assert (sentences.QUOTE_CHARS, sentences.TITLES) == (corpus.QUOTE_CHARS, corpus.TITLES)
    copied = [(scanners, corpus, n) for n in ("_owners_of_cue", "superlative_collisions")]
    copied += [(scanners, corpus_qa, n) for n in ("_nonplanted_sentences", "extract_order_edges", "_find_cycles",
                                                 "order_cycle_scan")]
    copied += [(sentences, corpus, n) for n in ("normalize_ws", "_boundaries", "_sentence_spans", "occurrences")]
    for ours, theirs, n in copied:
        assert inspect.getsource(getattr(ours, n)) == inspect.getsource(getattr(theirs, n)), n
    assert (inspect.getsource(scanners.same_attribute_hits)
            == inspect.getsource(corpus_qa.same_attribute_hits).replace("p: Plan,", "p,"))
    assert (inspect.getsource(sentences.sentences)
            == inspect.getsource(corpus._sentence_texts).replace("def _sentence_texts(", "def sentences("))


# ------------------------------------------------------------------------------------------ canaries (§13)
def write_canary(folder, **fields):
    folder.mkdir(parents=True, exist_ok=True)
    body = {"people": ["Ada", "Ben", "Cleo"], "defect": "a test defect", **fields}
    (folder / f"{fields['id']}.json").write_text(json.dumps(body), encoding="utf-8")


def test_no_scan_is_trusted_until_it_catches_every_canary_registered_for_it(tmp_path):
    assert canaries.load(tmp_path / "none") == []
    assert not any(t.trusted for t in canaries.trust([]).values())
    folder = tmp_path / "scans"
    write_canary(folder, id="s1", scan="superlative_collisions",
                 text="Ada arrived first. Later, Ben was the first to arrive.")
    write_canary(folder, id="o1", scan="order_cycles",
                 text="Ada is older than Ben. Ben is older than Cleo. Cleo is older than Ada.")
    write_canary(folder, id="o2", scan="order_cycles",
                 text="Ada outranks Ben. Ben outranks Cleo. Cleo outranks Ada.")
    trust = canaries.trust(canaries.load(folder))
    assert trust["superlative_collisions"].trusted and trust["superlative_collisions"].caught == ("s1",)
    assert not trust["order_cycles"].trusted and trust["order_cycles"].missed == ("o2",)
    assert not trust["same_attribute"].trusted and trust["same_attribute"].caught == ()
    write_canary(folder, id="s2", scan="superlative_collisions", text="Ada arrived first.")
    (folder / "s2.json").rename(folder / "s2-copy.json")
    write_canary(folder, id="s2", scan="order_cycles", text="x")
    with pytest.raises(ValueError, match="an id of its own"):
        canaries.load(folder)


def test_every_pattern_has_a_synthetic_canary_the_scan_catches_on_that_pattern_alone():
    registered = canaries.load()
    assert canaries.FOLDER == XONFORGE / "canaries" / "scans"
    for s in scans.SCANS:
        synthetic = [c.pattern for c in registered if c.scan == s and c.source == "synthetic"]
        assert sorted(synthetic) == sorted(scans.patterns(s))
    assert all(t.trusted and not t.missed for t in canaries.trust(registered).values())
    for c in registered:
        hits = scans.run(c.scan, c.text, c.people, attribute=c.attribute, plant_people=c.plant_people,
                         planted=c.planted)
        if c.scan == "superlative_collisions":
            found = [f"{h['attribute']}:{h['pole']}" for h in hits]
            assert found == [c.pattern] if c.source == "synthetic" else c.pattern in found
        elif c.scan == "order_cycles":
            spans = [e["span"] for e in scanners.extract_order_edges(c.text, c.people)]
            assert len(hits) == 1 and spans and all(re.fullmatch(rf"\w+\s+{c.pattern}\s+\w+", s) for s in spans)
        else:
            assert [h["attribute"] for h in hits] == [c.pattern]
            assert scans.run(c.scan, c.text, c.people, attribute=c.attribute, plant_people=c.plant_people,
                             planted=(*c.planted, hits[0]["sentence"])) == []


def test_the_l1_canary_is_base_32_s_superlative_clash_as_the_l1_review_pack_holds_it():
    l1 = [c for c in canaries.load() if c.source != "synthetic"]
    assert [(c.id, c.scan, c.pattern) for c in l1] == [
        ("l1-base32-arrival-earliest", "superlative_collisions", "arrival:earliest")]
    pack = json.loads((XONFORGE.parent / "data" / "consistency" / "corpus_review_pack.json").read_text(
        encoding="utf-8"))
    assert l1[0].text == pack["attempt_flagged"]["32"]["text"]
    assert "1b1749b4afcea1106c439306bcc8600b44095263" in l1[0].source
    hit = next(h for h in scans.run(l1[0].scan, l1[0].text, l1[0].people) if h["pole"] == "earliest")
    assert hit["people"] == ["Milo", "Quinn"]


def test_a_rendered_document_records_its_measurements_and_what_each_scan_found_and_was_trusted_for(tmp_path):
    sk = made("direct_negation").consistent
    good = rendering(sk)
    reply = anthropic_response(text=json.dumps({"text": good.text, "spans": [s.model_dump() for s in good.spans]}))
    doc = render(sk, fit(good), caller(tmp_path, entry("anthropic"), FakeClient(reply)), check=check,
                 max_tokens=4096, mode="record")
    assert doc.status == "rendered" and doc.measured == {}
    trust = {"superlative_collisions": canaries.ScanTrust(scan="superlative_collisions", trusted=True)}
    done = finalize(sk, doc, trust)
    assert done.measured == measure(sk, good)
    records = {r.scan: r for r in done.scans}
    assert records["superlative_collisions"].result == "clean" and records["superlative_collisions"].trusted
    assert records["order_cycles"].result == "clean" and not records["order_cycles"].trusted
    assert records["same_attribute"].result == "not_applicable"
    assert all(r.uncovered == () for r in done.scans)
    empty = doc.model_copy(update={"text": None, "spans": {}})
    assert finalize(sk, empty, trust) == empty


def test_the_renderer_quotes_the_failed_checks_back_until_the_rendering_passes(tmp_path):
    sk = made().consistent
    good = rendering(sk)
    bad = rendering(sk, extra=["The memo was titled \u201cSpring plans\u201d this year."])
    replies = [anthropic_response(text=json.dumps({"text": r.text, "spans": [s.model_dump() for s in r.spans]}))
               for r in (bad, good)]
    fake = FakeClient(*replies)
    doc = render(sk, fit(good), caller(tmp_path, entry("anthropic"), fake), check=check, max_tokens=4096,
                 mode="record")
    assert doc.status == "rendered" and [len(a.failed) for a in doc.attempts] == [1, 0]
    assert "the text uses quotation marks" in json.dumps(fake.bodies[1]["messages"])


def test_nothing_in_xonforge_imports_xon_now_that_a1_s_scans_are_copied():
    importers = sorted(p.relative_to(XONFORGE).as_posix() for p in XONFORGE.rglob("*.py")
                       if re.search(r"^\s*(?:from|import)\s+xon(?:\.|\s)", p.read_text(encoding="utf-8"), re.M))
    assert importers == []
