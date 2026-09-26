"""A scripted stand-in for the Anthropic SDK client, shared by the A1 pipeline and app tests: messages.create answers
from canned data chosen by the call's system prompt. Never calls the API."""
import json
import re
from types import SimpleNamespace

from xon.llm import prompts
from xon.llm.client import SCHEMA_TOO_COMPLEX

PAIR = re.compile(r"^\((\d+), (\d+)\)$", re.M)
SINGLE_PAIR = re.compile(r"^A \(claim (\d+)\): .*\nB \(claim (\d+)\): ", re.S)
LISTED = re.compile(r"^(\d+)\. ", re.M)
ENTITY_STEPS = {prompts.ENTITY_INVENTORY_SYSTEM_V2_2: "entities-inventory",
                prompts.ENTITY_RELATIONS_SYSTEM_V2_2: "entities-relations",
                prompts.ENTITY_COVERAGE_SYSTEM_V2_2: "entities-coverage"}

ANA_TEXT = "Ana is older than Ben. Ben is older than Cy. Cy is older than Ana."
ANA_CLAIMS = [("Ana is older than Ben.", "asserted"), ("Ben is older than Cy.", "asserted"),
              ("Cy is older than Ana.", "asserted")]
ANA_ENTITIES = {"entities": [{"id": e, "mentions": [e.title()]} for e in ("ana", "ben", "cy")],
                "attributes": [{"key": "age", "arity": "unknown", "arity_span": None}],
                "relations": [{"claim_id": i, "attribute": "age", "kind": "greater", "a": a, "b": b,
                               "confidence": 0.95} for i, (a, b) in enumerate((("ana", "ben"), ("ben", "cy"),
                                                                               ("cy", "ana")))]}
# Rev. 2.2's statements of the same text, in development iteration 0's single answer (ScriptedClient splits it into
# the entity steps' answers): each claim's own subject and object, the comparative verbatim
ANA_ENTITIES_V22 = {"entities": ANA_ENTITIES["entities"],
                    "attributes": [{"key": "age", "arity": "unknown", "arity_span": None, "order_kind": "magnitude",
                                    "other_greater_means": None}],
                    "same_different": [],
                    "orders": [{"claim_id": i, "attribute": "age", "subject": s, "comparative": "older than",
                                "object": o, "confidence": 0.95}
                               for i, (s, o) in enumerate((("ana", "ben"), ("ben", "cy"), ("cy", "ana")))],
                    "extremes": [], "senses": [{"attribute": "age", "comparative": "older than",
                                                "greater_side": "subject"}],
                    "unsupported_order_claims": []}
EMPTY_V22 = {"entities": [], "attributes": [], "same_different": [], "orders": [], "extremes": [], "senses": [],
             "unsupported_order_claims": []}
NO_STATEMENTS = {"same_different": [], "orders": [], "extremes": [], "senses": [], "unsupported_order_claims": []}
# The rationale of pair (1, 7) in the user's Test 1 (labeled contradicts, 0.85), verbatim
MALFORMED_RATIONALE = (
    "If Priya arrived before Tomas, and given typical transitive ordering context, Lena arriving before Priya combined "
    "with Priya before Tomas creates a chain, but this pair alone: Priya before Tomas doesn't itself contradict Lena "
    "before Priya, but if Lena arrived before Priya info is separate, they're compatible; reconsidering, no direct "
    "contradiction exists between just these two statements alone.', 'confidence': 0.3}")


def system_text(system) -> str:
    """The system prompt as text: rev. 2.2 sends it as one block with a cache breakpoint."""
    return system if isinstance(system, str) else "".join(block["text"] for block in system)


def call_kind(system) -> str:
    system = system_text(system)
    if system == prompts.EXTRACT_SYSTEM:
        return "extract"
    if system == prompts.ENTITY_SYSTEM:
        return "entities"
    if system in ENTITY_STEPS:
        return ENTITY_STEPS[system]
    if system == prompts.DIRECT_SYSTEM:
        return "direct"
    for wk in (False, True):
        if system == prompts.relate_system(wk):
            return "relate-wk" if wk else "relate"
        if system == prompts.relate_system_v2_2(wk):
            return "relate-v22-wk" if wk else "relate-v22"
        if system == prompts.pairs_system(wk):
            return "pairs-wk" if wk else "pairs"
    raise AssertionError("unexpected system prompt")


def single_pair(user: str) -> tuple[int, int]:
    """The pair of a rev. 2.2 relation request."""
    m = SINGLE_PAIR.match(user)
    assert m, "not a single-pair relation request"
    return int(m.group(1)), int(m.group(2))


class SchemaRejected(Exception):
    """The API's answer to an output schema it will not compile."""
    status_code = 400


def listed_claims(user: str) -> list[int]:
    """The claim numbers an entity step's message lists."""
    return [int(i) for i in LISTED.findall(user.split("\n\nEntities")[0])]


def constrained(body) -> bool:
    """Whether an entity step's schema is the per-document one (entity ids as an enum), not its fallback."""
    entity = body["output_config"]["format"]["schema"]["$defs"]["SameDifferent"]["properties"]["a"]
    return "enum" in entity or "const" in entity


def step_answers(spec: dict) -> tuple[dict, dict, dict | None]:
    """The inventory's, the relations call's and the coverage call's answers (None: answer none for every listed
    claim) of what the entity steps return, or of iteration 0's single answer (no coverage answer; an extreme
    statement has no restriction)."""
    if "inventory" in spec:
        return spec["inventory"], spec["relations"], spec.get("coverage")
    relations = {k: spec[k] for k in NO_STATEMENTS}
    relations["extremes"] = [{"restriction": None, **x} for x in relations["extremes"]]
    return {"entities": spec["entities"], "attributes": spec["attributes"]}, relations, None


class ScriptedClient:
    """relations / wk_relations: {(a, b): (label, confidence)}, other asked pairs are "unrelated" (0.9); omit: pairs
    left out of relation answers; extra: relation dicts appended to every relation answer; answers: {(a, b): [...]},
    one entry used per relation call that asks for the pair, (label, confidence, rationale) or None to leave the pair
    out, then the tables again. asked: the pairs each relation call asked for. Rev. 2.2 calls are answered one pair
    per call from relations_v22 (default: the same tables; leaving a pair out answers for pair (-1, -1)), and the
    entity steps from entities_v22 (step_answers); the per-document schema of the steps in reject_v22 ("relations",
    "coverage") is refused as too complex."""

    def __init__(self, claims, relations=None, entities=None, *, wk_relations=None, proposed=(), contradictions=(),
                 omit=(), extra=(), answers=None, entities_v22=None, relations_v22=None, reject_v22=()):
        self.claims = list(claims)
        self.relations = dict(relations or {})
        self.wk_relations = self.relations if wk_relations is None else dict(wk_relations)
        self.relations_v22 = None if relations_v22 is None else dict(relations_v22)
        self.entities = entities or {"entities": [], "attributes": [], "relations": []}
        self.entities_v22 = entities_v22 or EMPTY_V22
        self.reject_v22 = set(reject_v22)
        self.proposed = list(proposed)
        self.contradictions = list(contradictions)
        self.omit, self.extra = set(omit), list(extra)
        self.answers = {p: list(v) for p, v in (answers or {}).items()}
        self.calls, self.bodies, self.asked = [], [], []
        self.messages = self

    def _answer(self, table, a, b):
        script = self.answers.get((a, b))
        if script:
            entry = script.pop(0)
            return None if entry is None else dict(zip(("relation", "confidence", "rationale"), entry))
        label, confidence = table.get((a, b), ("unrelated", 0.9))
        return {"relation": label, "confidence": confidence, "rationale": "scripted"}

    def create(self, **body):
        kind = call_kind(body["system"])
        self.calls.append(kind)
        self.bodies.append(body)
        user = body["messages"][0]["content"]
        if kind == "extract":
            out = {"claims": [{"id": i, "text": t, "span": t, "kind": k} for i, (t, k) in enumerate(self.claims)]}
        elif kind in ("relate", "relate-wk"):
            table = self.wk_relations if kind == "relate-wk" else self.relations
            asked = [(int(a), int(b)) for a, b in PAIR.findall(user.split("Pairs (A, B):")[1])]
            self.asked.append(asked)
            found = [(a, b, self._answer(table, a, b)) for a, b in asked if (a, b) not in self.omit]
            out = {"relations": [{"a": a, "b": b, **x} for a, b, x in found if x is not None] + self.extra}
        elif kind in ("relate-v22", "relate-v22-wk"):
            table = (self.relations_v22 if self.relations_v22 is not None else
                     self.wk_relations if kind == "relate-v22-wk" else self.relations)
            a, b = single_pair(user)
            self.asked.append([(a, b)])
            x = None if (a, b) in self.omit else self._answer(table, a, b)
            out = {"a": a, "b": b, **x} if x is not None else {"a": -1, "b": -1, "relation": "unrelated",
                                                                "confidence": 0.9, "rationale": "scripted"}
        elif kind.startswith("pairs"):
            out = {"pairs": [{"a": a, "b": b} for a, b in self.proposed]}
        elif kind == "entities":
            out = self.entities
        elif kind in ENTITY_STEPS.values():
            step = kind.removeprefix("entities-")
            if step in self.reject_v22 and constrained(body):
                raise SchemaRejected(f"{SCHEMA_TOO_COMPLEX} (scripted)")
            inventory, relations, coverage = step_answers(self.entities_v22)
            out = {"inventory": inventory, "relations": relations}.get(step) or coverage or {
                **NO_STATEMENTS, "none": [{"claim_id": c, "reason": "Scripted."} for c in listed_claims(user)]}
        else:
            out = {"contradictions": [{"sentences": list(s), "explanation": "scripted"} for s in self.contradictions]}
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=json.dumps(out))], stop_reason="end_turn",
                               usage=SimpleNamespace(input_tokens=100, output_tokens=40, output_tokens_details=None))
