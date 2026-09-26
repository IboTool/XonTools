"""XonForge step 6 (XONFORGE_SPEC.md §8, §9, §12): acceptance, the sealed split's manifest and seal, encryption at
rest, export and placement, the providers' terms, and the datasheet. Never calls an API."""
import ast
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import date, datetime, timezone
from functools import cache
from pathlib import Path

import pytest

from xon_common import manifest as manifests
from xon_common.providers import ADAPTERS
from xonforge import locations
from xonforge.corpus import datasheet, export, leak, seal, terms
from xonforge.corpus.acceptance import Verdict, accept, accept_base, latest_decisions
from xonforge.render.phrasing import statement
from xonforge.render.prompt import PROMPT_VERSION
from xonforge.render.renderer import derive, doc_id, render
from xonforge.render.schema import Attempt, Document, Renderer, Rendering, RenderRules, SpanEntry
from xonforge.review.calibration import CanaryScore
from xonforge.review.decisions import DecisionLog
from xonforge.skeleton.generators import Knobs, generate
from xonforge.skeleton.schema import Trap
from xonforge.verify import scans
from xonforge.verify.canaries import ScanTrust
from xonforge.verify.checks import check, finalize
from xonforge.waiting import Waiting

from xonforge_fakes import FakeClient, anthropic_response, caller, entry

ROOT = Path(__file__).resolve().parents[2]
RULES = RenderRules(words=300, explicitness="stated", lexical_variety="low", min_spacing=2)
FILLER = "Item {} on the agenda was the printer schedule for the coming week at the main office."
TRUST = {s: ScanTrust(scan=s, trusted=True) for s in scans.SCANS}
RENDERER = Renderer(entry="test-entry", provider="anthropic", model="model-x", prompt_version=PROMPT_VERSION)
CANARIES = {s: f"XONFORGE-CANARY-00000000-0000-4000-8000-00000000000{n}" for n, s in enumerate(export.SPLITS)}
CANARY = CANARIES["development"]
LICENSE = "A license text for the tests, not the corpus's"
CHECKS = {"anthropic": terms.TermsCheck(checked=date(2026, 9, 25), allows=True, sources=("a page for the tests",))}


def sentence(fact, skeleton):
    s = ("Assume that " if fact.kind == "premise" and not fact.states_arity else "") + statement(fact, skeleton) + "."
    return s[0].upper() + s[1:]


def rendering(skeleton):
    """Each fact's sentence in the skeleton's own wording, after three sentences of filler."""
    filler = iter(FILLER.format(i) for i in range(1, 1000))
    parts, entries = [], []
    for f in skeleton.facts:
        s = sentence(f, skeleton)
        parts += [next(filler) for _ in range(3)] + [s]
        entries.append(SpanEntry(fact=f.id, span=s))
    return Rendering(text=" ".join(parts + [next(filler), next(filler)]), spans=entries)


def made(skeleton, *, trust=TRUST, mode="record", **update):
    """The document the renderer records for a rendering in the skeleton's own wording, finalized, its target length
    the text's own. A planted or trap variant's is recorded as derived from its twin's or planted variant's, which the
    same wording makes byte for byte but for the sentences of the facts that differ."""
    r = rendering(skeleton)
    derived = ({"derived_from": f"{skeleton.base_id}-consistent",
                "changed": tuple(skeleton.plant.params["differs_from_twin"])} if skeleton.variant == "planted" else
               {"derived_from": f"{skeleton.base_id}-planted", "changed": (skeleton.arity_fact,)}
               if skeleton.variant == "trap_only" else {})
    doc = Document(doc_id=doc_id(skeleton), base_id=skeleton.base_id, variant=skeleton.variant,
                   skeleton_digest=skeleton.digest(), mode=mode, renderer=RENDERER,
                   rules=RULES.model_copy(update={"words": len(r.text.split())}), status="rendered", text=r.text,
                   spans=r.span_map(), attempts=(Attempt(number=1),), **derived)
    return finalize(skeleton, doc, trust).model_copy(update=update)


def twin_of(skeleton, **kw):
    """The document a planted variant's is derived from: its twin's, made the same way."""
    return made(next(b.consistent for b in (base(), other()) if b.base_id == skeleton.base_id), **kw)


def gaps(skeleton):
    return [a for s in scans.SCANS if scans.applies(s, skeleton) for a in scans.relevant(s, skeleton)
            if not scans.covers(s, a)]


@cache
def base():
    b = generate("order_cycle", seed=0, genre="office memo", knobs=Knobs(entities=5, distractors=1))
    assert gaps(b.planted[0]) == []
    return b


@cache
def other():
    """A second base, for a skeleton a document does not render."""
    return generate("order_cycle", seed=1, genre="office memo", knobs=Knobs(entities=5, distractors=1))


def without_patterns_for(monkeypatch, attribute):
    """Every scan as if it had no pattern for the attribute: v0's scans have patterns for all of its attributes."""
    covers = scans.covers
    monkeypatch.setattr(scans, "covers", lambda scan, a: a != attribute and covers(scan, a))


def reasons(verdict, needle):
    return [r for r in verdict.reasons if needle in r]


# ------------------------------------------------------------------------------------------ acceptance (§8)
def test_a_twin_the_renderer_kept_and_the_variant_derived_from_it_are_accepted_when_they_pass_everything(tmp_path):
    b = base()
    twin, planted = b.consistent, b.planted[0]
    good = rendering(twin)
    reply = anthropic_response(text=json.dumps({"text": good.text, "spans": [s.model_dump() for s in good.spans]}))
    rules = RULES.model_copy(update={"words": len(good.text.split())})
    doc = render(twin, rules, caller(tmp_path, entry("anthropic"), FakeClient(reply)), check=check, max_tokens=4096,
                 mode="record")
    doc = finalize(twin, doc, TRUST)
    assert accept(twin, doc, mode="record", trust=TRUST, queued=False) == Verdict(id=doc.doc_id, accepted=True)
    (fid,) = planted.plant.params["differs_from_twin"]
    new = rendering(planted).span_map()[fid]
    revised = anthropic_response(text=json.dumps({"sentences": [{"fact": fid, "sentence": new}]}))
    derived = derive(planted, twin, doc, caller(tmp_path / "derive", entry("anthropic"), FakeClient(revised)),
                     check=check, max_tokens=4096, mode="record")
    derived = finalize(planted, derived, TRUST)
    assert accept(planted, derived, mode="record", trust=TRUST, queued=False, source=doc) == Verdict(
        id=derived.doc_id, accepted=True)
    assert accept(planted, derived, mode="record", trust=TRUST, queued=False).reasons == (
        f"the derivation: the document it was derived from, {doc.doc_id}, is needed to check it",)
    ids = [doc.doc_id, derived.doc_id]
    assert accept_base(b, {i: Verdict(id=i, accepted=True) for i in ids}).accepted


def test_a_trap_variant_is_accepted_with_the_planted_variant_it_was_derived_from():
    b = next(b for b in (generate("binary_parity", seed=s, genre="office memo", knobs=Knobs(entities=5, distractors=1),
                                  traps=("arity_control",)) for s in range(200))
             if all(gaps(v) == [] for v in (b.consistent, *b.planted, *b.trap_only)))
    docs = {v.variant: made(v) for v in (b.consistent, *b.planted, *b.trap_only)}
    kw = {"mode": "record", "trust": TRUST, "queued": False}
    verdicts = {docs["consistent"].doc_id: accept(b.consistent, docs["consistent"], **kw),
                docs["planted"].doc_id: accept(b.planted[0], docs["planted"], source=docs["consistent"], **kw),
                docs["trap_only"].doc_id: accept(b.trap_only[0], docs["trap_only"], source=docs["planted"], **kw)}
    assert all(v.accepted for v in verdicts.values()), verdicts
    assert accept_base(b, verdicts).accepted
    wrong = accept(b.trap_only[0], docs["trap_only"], source=docs["consistent"], **kw)
    assert wrong.reasons == (f"the derivation: the document it was derived from, {docs['planted'].doc_id}, is needed "
                             "to check it",)


def test_acceptance_runs_the_solver_and_the_checks_again_rather_than_reading_the_record():
    sk = base().planted[0]
    doc = made(sk)
    kw = {"mode": "record", "trust": TRUST, "queued": False, "source": twin_of(sk)}
    planted_span = doc.spans[sk.plant.facts[0]]
    altered = doc.model_copy(update={"text": doc.text.replace(planted_span, "")})
    assert reasons(accept(sk, altered, **kw), "a check fails:")
    assert reasons(accept(sk, altered, **kw), "the derivation: its text differs")
    assert reasons(accept(other().planted[0], doc, **kw), "the document does not render this skeleton")
    loose = sk.model_copy(update={"plant": sk.plant.model_copy(update={"facts": sk.plant.facts[:-1]})})
    assert reasons(accept(loose, doc, **kw), "the solver: the plant's facts can all be true")
    trapped = sk.model_copy(update={"traps": (Trap(type="coreference_trap", facts=(sk.facts[0].id,)),)})
    assert reasons(accept(trapped, doc, **kw), "the solver: traps in consistent or planted variants come with v1")


def test_a_failed_rendering_too_many_attempts_or_a_queued_document_no_human_accepted_is_refused(tmp_path):
    sk = base().planted[0]
    doc = made(sk)
    kw = {"mode": "record", "trust": TRUST, "source": twin_of(sk)}
    failed = doc.model_copy(update={"status": "failed"})
    assert accept(sk, failed, queued=False, **kw).reasons == ("the rendering did not pass its checks",)
    retried = doc.model_copy(update={"attempts": tuple(Attempt(number=i) for i in range(1, 7))})
    assert accept(sk, retried, queued=False, **kw).reasons == (
        "the rendering took 6 attempts, more than the retry cap",)
    assert accept(sk, doc, queued=True, **kw).reasons == ("queued for human review and not accepted by a human",)
    log = DecisionLog(tmp_path / "decisions.jsonl", clock=lambda: datetime(2026, 9, 25, 12, tzinfo=timezone.utc))
    log.decide("run-1", doc.doc_id, "regenerate", "a second superlative on arrival")
    latest = latest_decisions(log.entries(), "run-1")
    assert accept(sk, doc, queued=True, decision=latest.get(doc.doc_id), **kw).reasons == (
        "queued for human review and not accepted by a human (the decision: regenerate)",)
    log.decide("run-1", doc.doc_id, "accept", "reads well after the new rendering", reviewer="MF")
    latest = latest_decisions(log.entries(), "run-1")
    assert latest_decisions(log.entries(), "run-2") == {}
    assert accept(sk, doc, queued=True, decision=latest[doc.doc_id], **kw).accepted


def test_an_untrusted_scan_or_a_scan_gap_is_never_accepted_and_the_reason_says_so(monkeypatch):
    sk = base().planted[0]
    doc = made(sk)
    untrusted = accept(sk, doc, mode="record", trust={}, queued=False, source=twin_of(sk))
    applicable = [s for s in scans.SCANS if scans.applies(s, sk)]
    assert len(reasons(untrusted, "clean result is not trusted")) == len(applicable)
    assert len(untrusted.reasons) == len(applicable)
    attribute = scans.relevant("order_cycles", sk)[0]
    without_patterns_for(monkeypatch, attribute)
    found = reasons(accept(sk, made(sk), mode="record", trust=TRUST, queued=False, source=twin_of(sk)),
                    "waits for a scan pattern: the")
    assert found and gaps(sk) and all(attribute in r for r in found)


def test_a_base_is_accepted_only_when_every_variant_is():
    b = base()
    ids = [doc_id(b.consistent), doc_id(b.planted[0])]
    assert accept_base(b, {i: Verdict(id=i, accepted=True) for i in ids}).accepted
    refused = accept_base(b, {ids[0]: Verdict(id=ids[0], accepted=False, reasons=("x",))})
    assert refused.reasons == (f"{ids[0]} is not accepted", f"{ids[1]} has no verdict")


# ------------------------------------------------------------------------------------------ acceptance never reads
# the engine diagnostics (§7.5)
def imported(module: str) -> set[str]:
    """The xonforge and xon_common modules a module imports, directly or through others, parent packages included."""
    seen, todo = set(), [module]
    while todo:
        name = todo.pop()
        if name in seen:
            continue
        seen.add(name)
        path = ROOT.joinpath(*name.split("."))
        package = (path / "__init__.py").is_file()
        file = path / "__init__.py" if package else path.with_suffix(".py")
        if not file.is_file():
            continue
        here = name.split(".") if package else name.split(".")[:-1]
        for node in ast.walk(ast.parse(file.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                targets = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                base_name = ".".join((here[:len(here) - node.level + 1] if node.level else [])
                                     + (node.module.split(".") if node.module else []))
                targets = [base_name] + [f"{base_name}.{a.name}" for a in node.names]
            else:
                continue
            for t in targets:
                parts = t.split(".")
                if parts[0] in ("xonforge", "xon_common"):
                    todo += [".".join(parts[:i]) for i in range(1, len(parts) + 1)]
    return {m for m in seen if ROOT.joinpath(*m.split(".")).with_suffix(".py").is_file()
            or ROOT.joinpath(*m.split("."), "__init__.py").is_file()}


ISOLATED = r"""
import json
import os
import sys

sys.path.insert(0, sys.argv[1])
opened = []
sys.addaudithook(lambda event, args: opened.append(os.fsdecode(args[0]))
                 if event == "open" and args and isinstance(args[0], (str, bytes, os.PathLike)) else None)
from xonforge.corpus.acceptance import accept
from xonforge.render.schema import Document
from xonforge.skeleton.schema import Skeleton
from xonforge.verify.canaries import ScanTrust

data = json.loads(sys.stdin.read())
verdict = accept(Skeleton.model_validate(data["skeleton"]), Document.model_validate(data["document"]), mode="record",
                 trust={s: ScanTrust.model_validate(t) for s, t in data["trust"].items()}, queued=False)
print(json.dumps({"verdict": verdict.model_dump(mode="json"), "opened": opened,
                  "modules": sorted(m for m in sys.modules if m.split(".")[0] == "xonforge")}))
"""


def test_acceptance_never_imports_or_reads_the_engine_diagnostics(tmp_path):
    reached = imported("xonforge.corpus.acceptance")
    assert {"xonforge.verify.checks", "xonforge.verify.scanners", "xonforge.solver.solver"} <= reached
    assert sorted(m for m in reached if m.split(".")[:2] == ["xonforge", "diagnostics"]) == []
    for module in ("export", "datasheet", "seal"):
        assert not any(m.split(".")[:2] == ["xonforge", "diagnostics"] for m in imported(f"xonforge.corpus.{module}"))
    (tmp_path / "diagnostics").mkdir()
    (tmp_path / "diagnostics" / "engine.jsonl").write_text('{"doc_id": "b0001-planted"}\n', encoding="utf-8")
    sk = base().consistent
    data = {"skeleton": sk.model_dump(mode="json"), "document": made(sk).model_dump(mode="json"),
            "trust": {s: t.model_dump(mode="json") for s, t in TRUST.items()}}
    env = {**os.environ, locations.CACHE_ENV: str(tmp_path / "cache")}
    out = subprocess.run([sys.executable, "-c", ISOLATED, str(ROOT)], input=json.dumps(data), cwd=ROOT, env=env,
                         capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    res = json.loads(out.stdout)
    assert res["verdict"]["accepted"], res["verdict"]
    assert "xonforge.verify.scanners" in res["modules"]
    assert not any(m.split(".")[:2] == ["xonforge", "diagnostics"] for m in res["modules"])
    def under(p, d):
        return Path(p).resolve().is_relative_to(d.resolve())

    assert any(under(p, ROOT / "xonforge" / "verify") for p in res["opened"])
    diagnostics = [ROOT / "xonforge" / "diagnostics", tmp_path / "diagnostics"]
    assert [p for p in res["opened"] if any(under(p, d) for d in diagnostics)] == []


# ------------------------------------------------------------------------------------------ the manifest (§9)
def sealed_folder(tmp_path):
    folder = tmp_path / "sealed" / "v0.1"
    (folder / "sub").mkdir(parents=True)
    (folder / "test.jsonl").write_text('{"doc_id": "b0001-planted", "mode": "record"}\n', encoding="utf-8")
    (folder / "sub" / "test.skeletons.jsonl").write_text('{"base_id": "b0001"}\n', encoding="utf-8")
    return folder


def test_a_sealed_folder_s_manifest_lists_every_file_and_verifies(tmp_path):
    folder = sealed_folder(tmp_path)
    made_manifest = seal.write_manifest(folder, canary=CANARY)
    assert sorted(made_manifest["files"]) == ["sub/test.skeletons.jsonl", "test.jsonl"]
    assert made_manifest["files"]["test.jsonl"] == hashlib.sha256((folder / "test.jsonl").read_bytes()).hexdigest()
    assert made_manifest["canary"] == CANARY and CANARY in (folder / seal.MANIFEST).read_text(encoding="utf-8")
    assert manifests.load(folder / seal.MANIFEST) == made_manifest
    assert seal.verify_sealed(folder) == []
    assert manifests.build(made_manifest["files"])["manifest_hash"] != made_manifest["manifest_hash"]
    with pytest.raises(locations.LocationRefused):
        seal.write_manifest(locations.ROOT / "sealed")


def _alter(folder):
    (folder / "test.jsonl").write_text('{"doc_id": "b0002-planted"}\n', encoding="utf-8")


def _add(folder):
    (folder / "extra.jsonl").write_text("{}\n", encoding="utf-8")


def _remove(folder):
    (folder / "sub" / "test.skeletons.jsonl").unlink()


def _edit_listed_hash(folder):
    m = json.loads((folder / seal.MANIFEST).read_text(encoding="utf-8"))
    m["files"]["test.jsonl"] = "0" * 64
    (folder / seal.MANIFEST).write_text(json.dumps(m), encoding="utf-8")


def _edit_manifest_hash(folder):
    m = json.loads((folder / seal.MANIFEST).read_text(encoding="utf-8"))
    m["manifest_hash"] = "0" * 64
    (folder / seal.MANIFEST).write_text(json.dumps(m), encoding="utf-8")


def _edit_canary(folder):
    m = json.loads((folder / seal.MANIFEST).read_text(encoding="utf-8"))
    m["canary"] = "XONFORGE-CANARY-another"
    (folder / seal.MANIFEST).write_text(json.dumps(m), encoding="utf-8")


@pytest.mark.parametrize("tamper, found", [
    (_alter, ["changed: test.jsonl"]),
    (_add, ["not in the manifest: extra.jsonl"]),
    (_remove, ["missing: sub/test.skeletons.jsonl"]),
    (_edit_listed_hash, ["the manifest hash does not match the files it lists", "changed: test.jsonl"]),
    (_edit_manifest_hash, ["the manifest hash does not match the files it lists"]),
    (_edit_canary, ["the manifest hash does not match the files it lists"]),
])
def test_any_change_to_a_sealed_folder_or_its_manifest_shows(tmp_path, tamper, found):
    folder = sealed_folder(tmp_path)
    seal.write_manifest(folder, canary=CANARY)
    tamper(folder)
    assert seal.verify_sealed(folder) == found


@pytest.mark.parametrize("path", ["../x.jsonl", "a\\b.jsonl", "/abs.jsonl", "C:x.jsonl", "a//b.jsonl", ""])
def test_a_manifest_path_is_relative_with_forward_slashes_and_stays_in_its_folder(path):
    with pytest.raises(ValueError, match="a manifest path is relative"):
        manifests.build({path: "0" * 64})


def test_a_manifest_holds_lower_case_sha_256_digests_and_nothing_else(tmp_path):
    with pytest.raises(ValueError, match="not a SHA-256"):
        manifests.build({"a.jsonl": "A" * 64})
    with pytest.raises(ValueError, match="canary string is a non-empty string"):
        manifests.build({"a.jsonl": "0" * 64}, canary=" ")
    good = manifests.build({"a.jsonl": "0" * 64})
    assert "canary" not in good
    for bad, message in (({**good, "note": "x"}, "and nothing else"), ({**good, "canary": 7}, "is a string")):
        (tmp_path / "m.json").write_text(json.dumps(bad), encoding="utf-8")
        with pytest.raises(ValueError, match=message):
            manifests.load(tmp_path / "m.json")


# ------------------------------------------------------------------------------------------ SEALED.md, the canary
def test_a_seal_records_the_manifest_hash_date_version_and_canary_hash_once_per_version(tmp_path):
    folder = sealed_folder(tmp_path)
    m = seal.write_manifest(folder)
    canary = CANARIES["test"]
    path = seal.append_seal(tmp_path / "SEALED.md", corpus_version="v0.1", date="2026-09-25", manifest=m,
                            canary=canary)
    text = path.read_text(encoding="utf-8")
    assert text.startswith("# Sealed XonForge test splits\n")
    assert seal.seal_section(corpus_version="v0.1", date="2026-09-25", manifest_hash=m["manifest_hash"], files=2,
                             canary=canary) in text
    assert f"- Canary string's SHA-256: `{hashlib.sha256(canary.encode()).hexdigest()}`" in text
    assert canary not in text
    with pytest.raises(ValueError, match="v0.1 is already sealed"):
        seal.append_seal(path, corpus_version="v0.1", date="2026-09-26", manifest=m, canary=canary)
    seal.append_seal(path, corpus_version="v0.2", date="2026-09-26", manifest=m, canary=canary)
    assert path.read_text(encoding="utf-8").startswith(text.rstrip("\n") + "\n\n## v0.2\n")
    assert "b0001" not in path.read_text(encoding="utf-8")


def test_each_split_gets_a_canary_string_of_its_own():
    made = seal.new_canaries(export.SPLITS)
    assert list(made) == list(export.SPLITS) and len(set(made.values())) == len(export.SPLITS)
    assert all(re.fullmatch(r"XONFORGE-CANARY-[0-9a-f-]{36}", c) for c in made.values())
    assert made["test"] in seal.CANARY_NOTICE.format(canary=made["test"])
    assert seal.new_canaries(["test"])["test"] != made["test"]


# ------------------------------------------------------------------------------------------ encryption at rest
def test_encryption_round_trips_and_refuses_a_wrong_passphrase_or_an_altered_file():
    blob = seal.encrypt(b"Ada is older than Ben.", "a passphrase")
    assert blob.startswith(seal.MAGIC) and b"Ada" not in blob
    assert seal.decrypt(blob, "a passphrase") == b"Ada is older than Ben."
    with pytest.raises(ValueError, match="passphrase is wrong"):
        seal.decrypt(blob, "another passphrase")
    with pytest.raises(ValueError, match="passphrase is wrong"):
        seal.decrypt(blob[:-1] + bytes([blob[-1] ^ 1]), "a passphrase")
    with pytest.raises(ValueError, match="not a file XonForge encrypted"):
        seal.decrypt(b"plain text", "a passphrase")
    with pytest.raises(ValueError, match="empty passphrase"):
        seal.encrypt(b"x", "")


def test_a_folder_is_encrypted_beside_the_sealed_one_which_is_left_as_it_is(tmp_path):
    folder = sealed_folder(tmp_path)
    seal.write_manifest(folder)
    written = seal.encrypt_folder(folder, tmp_path / "encrypted", "a passphrase")
    assert sorted(p.relative_to(tmp_path / "encrypted").as_posix() for p in written) == [
        "MANIFEST.json.enc", "sub/test.skeletons.jsonl.enc", "test.jsonl.enc"]
    assert seal.decrypt((tmp_path / "encrypted" / "test.jsonl.enc").read_bytes(), "a passphrase") == \
        (folder / "test.jsonl").read_bytes()
    assert seal.verify_sealed(folder) == []
    with pytest.raises(ValueError, match="outside the sealed split's folder"):
        seal.encrypt_folder(folder, folder / "encrypted", "a passphrase")
    with pytest.raises(locations.LocationRefused):
        seal.encrypt_folder(folder, locations.ROOT / "encrypted", "a passphrase")


# ------------------------------------------------------------------------------------------ export (§9)
def test_the_license_is_cc_by_4_0_and_the_not_for_training_notice_a_request_that_is_not_a_term_of_it(tmp_path):
    assert "Creative Commons Attribution 4.0 International License (CC BY 4.0)" in export.LICENSE
    assert "https://creativecommons.org/licenses/by/4.0/legalcode" in export.LICENSE
    assert export.NOTICE.startswith("Not for training, a request: ")
    assert export.NOTICE.endswith("This request is not a term of the license.")
    sk = base().planted[0]
    rec = export.record(sk, made(sk), canary=CANARY)
    for license in (None, "", "  "):
        with pytest.raises(ValueError, match="carries its license's text"):
            export.write_split(tmp_path / "out", "development", [rec], license=license, canary=CANARY)
        with pytest.raises(ValueError, match="carries its license's text"):
            export.write_readme(tmp_path / "out", corpus_version="v0.1", splits=["development"], mode="record",
                                license=license, canaries=CANARIES)
        with pytest.raises(ValueError, match="carries its license's text"):
            export.write_license(tmp_path / "out", splits=["development"], license=license, canaries=CANARIES)
        with pytest.raises(ValueError, match="carries its license's text"):
            export.place({}, [], {}, mode="record", version="v0.1", license=license, canaries=CANARIES,
                         checks=CHECKS, data_dir=tmp_path / "out")
    assert not (tmp_path / "out").exists()
    text = export.write_license(tmp_path / "out", splits=["development"], canaries=CANARIES).read_text(encoding="utf-8")
    assert text == f"{export.LICENSE}\n\n{export.NOTICE}\n\nCanary string of the development split: {CANARY}\n"


def test_each_split_s_files_carry_its_own_canary_string_and_no_other_split_s(tmp_path):
    for bad, message in (({**CANARIES, "calibration": " "}, "and calibration has none"),
                         ({**CANARIES, "calibration": CANARY}, "two splits share one")):
        with pytest.raises(ValueError, match=message):
            export.write_readme(tmp_path / "out", corpus_version="v0.1", splits=["development", "calibration"],
                                mode="record", canaries=bad)
    readme = export.write_readme(tmp_path / "out", corpus_version="v0.1", splits=["development", "calibration"],
                                 mode="record", canaries=CANARIES).read_text(encoding="utf-8")
    assert readme.endswith(f"Canary string of the development split: {CANARY}\n"
                           f"Canary string of the calibration split: {CANARIES['calibration']}\n")
    assert CANARIES["test"] not in readme and CANARIES["judged"] not in readme


# ------------------------------------------------------------------------------------------ the providers' terms
def test_nothing_is_exported_before_each_renderer_s_terms_are_checked_and_found_to_allow_it(tmp_path, monkeypatch):
    b1, b2, b3 = three_bases()
    entries = placed_entries()
    verdicts = {d.doc_id: Verdict(id=d.doc_id, accepted=True) for _, d in entries}
    assignment = {b.base_id: "development" for b in (b1, b2, b3)}
    kw = {"mode": "record", "version": "v0.1", "canaries": CANARIES, "data_dir": tmp_path / "data"}
    refusing = {"anthropic": terms.TermsCheck(checked=date(2026, 9, 25), allows=False, sources=("a page",))}
    monkeypatch.setattr(terms, "load", lambda path=terms.PATH: {})
    for checks, message in (({}, "anthropic's terms on publishing its outputs as a dataset are not checked and "
                                 "logged yet"),
                            (refusing, "anthropic's terms, checked on 2026-09-25, do not allow publishing"),
                            (None, "anthropic's terms on publishing its outputs as a dataset are not checked")):
        with pytest.raises(Waiting, match="nothing is exported before each renderer's terms are checked .*" + message):
            export.place(assignment, entries, verdicts, checks=checks, **kw)
    assert not (tmp_path / "data").exists()
    assert export.place(assignment, entries, verdicts, checks=CHECKS, **kw) == {"development": tmp_path / "data" /
                                                                                "v0.1"}


def test_the_terms_file_lists_every_provider_and_a_logged_check_has_its_date_result_and_pages():
    checks = terms.load()
    assert set(checks) == set(ADAPTERS)
    assert terms.problems(["openai", "anthropic"], {**checks, **CHECKS}) == [
        "openai's terms on publishing its outputs as a dataset are not checked and logged yet "
        "(xonforge/config/terms.yaml)"]
    for bad in ({"checked": "2026-09-25", "allows": True}, {"checked": "2026-09-25", "sources": ["a page"]},
                {"allows": False, "sources": ["a page"]}):
        with pytest.raises(ValueError, match="a logged check has its date, its result and the pages read"):
            terms.TermsCheck.model_validate(bad)


def test_an_exported_record_holds_what_the_spec_lists_and_every_line_the_canary(tmp_path):
    sk = base().planted[0]
    doc = made(sk, flags=("needed all 5 rendering attempts",))
    log = DecisionLog(tmp_path / "decisions.jsonl", clock=lambda: datetime(2026, 9, 25, 12, tzinfo=timezone.utc))
    log.decide("run-1", doc.doc_id, "accept", "reads well", reviewer="MF")
    log.decide("run-1", "b9999-planted", "discard", "another document")
    rec = export.record(sk, doc, canary=CANARY, reviewers=["openai model-y"], decisions=log.entries())
    assert (rec.doc_id, rec.base_id, rec.variant, rec.genre) == (doc.doc_id, sk.base_id, "planted", "office memo")
    assert (rec.text, rec.spans, rec.plant, rec.traps) == (doc.text, doc.spans, sk.plant.model_dump(mode="json"), [])
    assert (rec.arity_fact, rec.premise_status) == (sk.arity_fact, sk.premise_status)
    assert rec.difficulty["measured"] == doc.measured and rec.difficulty["set"]["words"] == doc.rules.words
    assert (rec.renderer, rec.reviewers, rec.flags) == (RENDERER, ["openai model-y"], list(doc.flags))
    assert rec.scans == list(doc.scans)
    assert [(d.decision, d.reviewer) for d in rec.decisions] == [("accept", "MF")]
    assert rec.hashes == {"skeleton": sk.digest(), "text": hashlib.sha256(doc.text.encode("utf-8")).hexdigest()}
    path = export.write_split(tmp_path / "out", "development", [rec, rec], license=LICENSE, canary=CANARY)
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2 and all(json.loads(line)["canary"] == CANARY for line in lines)
    assert export.ExportRecord.model_validate_json(lines[0]) == rec
    with pytest.raises(FileExistsError):
        export.write_split(tmp_path / "out", "development", [rec], license=LICENSE, canary=CANARY)
    with pytest.raises(ValueError, match="every record carries its split's canary string"):
        export.write_split(tmp_path / "out2", "development", [rec], license=LICENSE, canary="another")
    with pytest.raises(ValueError, match="the splits are"):
        export.write_split(tmp_path / "out2", "train", [rec], license=LICENSE, canary=CANARY)
    with pytest.raises(ValueError, match="only a rendered document of this skeleton"):
        export.record(other().planted[0], doc, canary=CANARY)
    with pytest.raises(ValueError, match="only a rendered document of this skeleton"):
        export.record(sk, doc.model_copy(update={"text": None}), canary=CANARY)


# ------------------------------------------------------------------------------------------ placement
@cache
def three_bases():
    return tuple(generate("order_cycle", seed=s, genre="office memo", knobs=Knobs(entities=5, distractors=1))
                 for s in (1, 2, 3))


def placed_entries():
    return [(sk, made(sk)) for b in three_bases() for sk in (b.consistent, b.planted[0])]


def test_placement_keeps_each_base_whole_and_puts_each_split_where_rules_md_says(tmp_path):
    b1, b2, b3 = three_bases()
    entries = placed_entries()
    verdicts = {d.doc_id: Verdict(id=d.doc_id, accepted=True) for _, d in entries}
    assignment = {b1.base_id: "development", b2.base_id: "calibration", b3.base_id: "test"}
    folders = {"data_dir": tmp_path / "data", "sealed": tmp_path / "sealed", "judged": tmp_path / "judged"}
    written = export.place(assignment, entries, verdicts, mode="record", version="v0.1", license=LICENSE,
                           canaries=CANARIES, checks=CHECKS, **folders)
    data, sealed = tmp_path / "data" / "v0.1", (tmp_path / "sealed").resolve() / "v0.1"
    assert written == {"development": data, "calibration": data, "test": sealed}
    assert sorted(p.name for p in data.iterdir()) == ["LICENSE.txt", "README.md", "calibration.jsonl",
                                                      "calibration.skeletons.jsonl", "development.jsonl",
                                                      "development.skeletons.jsonl"]
    assert sorted(p.name for p in sealed.iterdir()) == ["LICENSE.txt", "README.md", "test.jsonl",
                                                        "test.skeletons.jsonl"]
    assert not (tmp_path / "judged").exists()
    test_lines = [json.loads(line) for line in (sealed / "test.jsonl").read_text(encoding="utf-8").splitlines()]
    assert sorted((r["base_id"], r["variant"]) for r in test_lines) == [(b3.base_id, "consistent"),
                                                                        (b3.base_id, "planted")]
    assert all(r["canary"] == CANARIES["test"] for r in test_lines)
    skeletons = (sealed / "test.skeletons.jsonl").read_text(encoding="utf-8").splitlines()
    assert [json.loads(s)["canary"] for s in skeletons] == [CANARIES["test"]] * 2
    for split in ("development", "calibration"):
        assert {json.loads(line)["canary"] for line in (data / f"{split}.jsonl").read_text(
            encoding="utf-8").splitlines()} == {CANARIES[split]}
    for name in ("README.md", "LICENSE.txt"):
        text = (data / name).read_text(encoding="utf-8")
        assert export.NOTICE in text and LICENSE in text
        assert CANARIES["development"] in text and CANARIES["calibration"] in text
    assert "Splits here: development, calibration." in (data / "README.md").read_text(encoding="utf-8")
    assert not any(CANARIES["test"] in p.read_text(encoding="utf-8") for p in data.iterdir())
    seal.write_manifest(sealed, canary=CANARIES["test"])
    assert seal.verify_sealed(sealed) == []
    assert all(CANARIES["test"] in p.read_text(encoding="utf-8") for p in sealed.iterdir())
    assert not any(c in p.read_text(encoding="utf-8") for p in sealed.iterdir()
                   for c in (CANARIES["development"], CANARIES["calibration"]))


def test_a_sealed_split_s_fingerprints_flag_its_own_files_and_not_the_splits_in_the_repository(tmp_path, monkeypatch):
    b1, b2, b3 = three_bases()
    entries = [(sk, made(sk)) for b in (b1, b2) for sk in (b.consistent, b.planted[0])]
    monkeypatch.setitem(globals(), "FILLER", "Note {} of the sealed memo: lanterns, a harbour, and a violin nobody in "
                                             "the village could tune.")
    entries += [(sk, made(sk)) for sk in (b3.consistent, b3.planted[0])]
    verdicts = {d.doc_id: Verdict(id=d.doc_id, accepted=True) for _, d in entries}
    assignment = {b1.base_id: "development", b2.base_id: "calibration", b3.base_id: "test"}
    written = export.place(assignment, entries, verdicts, mode="record", version="v0.1", canaries=CANARIES,
                           checks=CHECKS, data_dir=tmp_path / "data", sealed=tmp_path / "sealed")
    manifest = leak.fingerprint_split(written["test"], "test", version="v0.1")
    assert manifest["canary_sha256"] == seal.canary_sha256(CANARIES["test"])
    assert [d["doc_id"] for d in manifest["documents"]] == [doc_id(b3.consistent), doc_id(b3.planted[0])]
    leak.write_fingerprint(manifest, tmp_path / "prints")
    assert leak.check_worktrees(roots=[written["development"]], folder=tmp_path / "prints").findings == []
    found = leak.check_worktrees(roots=[written["test"]], folder=tmp_path / "prints").findings
    assert {Path(f.where).name for f in found} == {"test.jsonl", "README.md", "LICENSE.txt", "test.skeletons.jsonl"}
    assert "the canary string of the test split of v0.1" in {f.what for f in found}


def test_placement_refuses_an_unassigned_base_a_split_base_or_a_document_not_accepted(tmp_path):
    b1, b2, b3 = three_bases()
    entries = placed_entries()
    verdicts = {d.doc_id: Verdict(id=d.doc_id, accepted=True) for _, d in entries}
    assignment = {b1.base_id: "development", b2.base_id: "calibration", b3.base_id: "test"}
    folders = {"data_dir": tmp_path / "data", "sealed": tmp_path / "sealed", "judged": tmp_path / "judged"}
    kw = {"mode": "record", "version": "v0.1", "license": LICENSE, "canaries": CANARIES, "checks": CHECKS, **folders}
    with pytest.raises(ValueError, match="every base with documents is assigned a split"):
        export.place({b1.base_id: "development"}, entries, verdicts, **kw)
    with pytest.raises(ValueError, match="a consistent twin and its planted variants are placed together"):
        export.place(assignment, [e for e in entries if e[1].doc_id != doc_id(b2.consistent)], verdicts, **kw)
    refused = {**verdicts, doc_id(b3.planted[0]): Verdict(id=doc_id(b3.planted[0]), accepted=False)}
    with pytest.raises(ValueError, match="only accepted documents are placed"):
        export.place(assignment, entries, refused, **kw)
    with pytest.raises(ValueError, match="each split has a canary string of its own, and test has none"):
        export.place(assignment, entries, verdicts, **{**kw, "canaries": {"development": CANARY,
                                                                         "calibration": CANARIES["calibration"]}})
    assert not any((tmp_path / f).exists() for f in ("data", "sealed", "judged"))


def test_the_sealed_and_judged_splits_go_outside_the_repository_and_the_others_into_it():
    data = locations.ROOT / "data" / "xonforge"
    for split in ("development", "calibration"):
        assert export.destination(split, "v0.1", mode="record") == data / "v0.1"
        assert export.destination(split, "v0.1", mode="pipeline_test") == data / "pipeline_test" / "v0.1"
    for split, kw in (("test", "sealed"), ("judged", "judged")):
        with pytest.raises(locations.LocationRefused):
            export.destination(split, "v0.1", mode="record", **{kw: locations.ROOT / split})
        with pytest.raises(locations.LocationRefused, match="is not set"):
            export.destination(split, "v0.1", mode="record")
        with pytest.raises(ValueError, match=f"never enters a sealed or judged split, and this is the {split} split"):
            export.destination(split, "v0.1", mode="pipeline_test")
    with pytest.raises(ValueError, match="the splits are"):
        export.destination("train", "v0.1", mode="record")
    with pytest.raises(ValueError, match="names its mode"):
        export.destination("development", "v0.1", mode="test")


# ------------------------------------------------------------------------------------------ the datasheet (§12)
SECTIONS = ["## Motivation", "## Composition", "## Generation process", "## Providers used",
            "## Review and calibration results", "## Known issues", "## Splits and sealing",
            "## Recommended and discouraged uses", "## License"]


def test_the_datasheet_has_every_section_counts_the_records_and_holds_no_document_text():
    b1, b2, *_ = three_bases()
    records = {split: [export.record(sk, made(sk), canary=CANARIES[split]) for sk in (b.consistent, b.planted[0])]
               for split, b in (("development", b1), ("test", b2))}
    score = CanaryScore(reviewer="openai model-y", batch_id="batch-1", defects=4, caught=3, clean=2, false_alarms=0)
    sheet = datasheet.datasheet(corpus_version="v0.1", date="2026-09-25", mode="record", records=records,
                                canaries=CANARIES, reviewers=["openai model-y"], scores=[score],
                                known_issues=["a known issue"])
    lines = sheet.splitlines()
    assert [line for line in lines if line.startswith("## ")] == SECTIONS
    assert "- Documents: 4, from 2 base skeletons." in lines
    assert "- By split: development: 2, test: 2." in lines
    assert "- By variant: consistent: 2, planted: 2." in lines
    assert "- By plant type: order_cycle: 2." in lines
    assert "- Renderers: anthropic model-x: 4." in lines
    assert "- openai model-y, batch batch-1: recall 3/4, false alarms 0/2." in lines
    assert "- a known issue" in lines
    assert "- Bases by split: development: 1, test: 1." in lines
    assert "- Test split manifest hash: not sealed yet." in lines
    assert f"- Canary string of the development split, in each of its files and its README: `{CANARY}`." in lines
    assert (f"- Canary string of the test split: its SHA-256 is `{seal.canary_sha256(CANARIES['test'])}`; the string "
            "itself is only in the split's own files.") in lines
    assert CANARIES["test"] not in sheet and CANARIES["calibration"] not in sheet
    assert lines[-1] == export.LICENSE
    texts = [s for rs in records.values() for r in rs for s in r.spans.values()]
    assert texts and not any(s in sheet for s in texts)
    sealed = datasheet.datasheet(corpus_version="v0.1", date="2026-09-25", mode="record", records=records,
                                 canaries=CANARIES, license=LICENSE, manifest_hash="a" * 64)
    assert f"- Test split manifest hash: `{'a' * 64}`." in sealed and sealed.splitlines()[-1] == LICENSE
    assert "- No canary scores are recorded." in sealed and "- Reviewers: none recorded." in sealed
    with pytest.raises(ValueError, match="the splits are"):
        datasheet.datasheet(corpus_version="v0.1", date="2026-09-25", mode="record", records={"train": []},
                            canaries=CANARIES)
    for canaries in ({**CANARIES, "test": CANARY}, {"development": CANARY}):
        with pytest.raises(ValueError, match="each split has a canary string of its own"):
            datasheet.datasheet(corpus_version="v0.1", date="2026-09-25", mode="record", records=records,
                                canaries=canaries)
    with pytest.raises(ValueError, match="every record carries its split's canary string"):
        datasheet.datasheet(corpus_version="v0.1", date="2026-09-25", mode="record",
                            records={"development": records["test"]}, canaries=CANARIES)
    assert "Pipeline test" not in sheet + sealed


def test_the_datasheet_is_written_once_per_corpus(tmp_path):
    path = datasheet.write(tmp_path / "v0.1", "# Datasheet\n")
    assert path.name == "DATASHEET.md" and path.read_text(encoding="utf-8") == "# Datasheet\n"
    with pytest.raises(FileExistsError):
        datasheet.write(tmp_path / "v0.1", "# Datasheet\n")


def test_the_datasheet_lists_scan_gaps_and_untrusted_clean_scans_as_known_issues(monkeypatch):
    sk = base().planted[0]
    without_patterns_for(monkeypatch, scans.relevant("order_cycles", sk)[0])
    rec = export.record(sk, made(sk, trust={}), canary=CANARY)
    sheet = datasheet.datasheet(corpus_version="v0.1", date="2026-09-25", mode="record",
                                records={"development": [rec]}, canaries=CANARIES)
    for s in rec.scans:
        if s.uncovered:
            assert f"- the {s.scan} scan has no pattern for {', '.join(s.uncovered)}, in 1 document" in sheet
        if s.result == "clean":
            assert (f"- the {s.scan} scan's clean results are not trusted (it has not caught every canary registered "
                    "for it), in 1 document") in sheet
    assert any(s.uncovered for s in rec.scans)


# ------------------------------------------------------------------------------------------ the pipeline-test mode
def test_a_pipeline_test_document_is_accepted_only_into_a_pipeline_test():
    sk = base().planted[0]
    test_doc, record_doc = made(sk, mode="pipeline_test"), made(sk)
    kw = {"trust": TRUST, "queued": False}
    assert accept(sk, test_doc, mode="pipeline_test", source=twin_of(sk, mode="pipeline_test"), **kw).accepted
    assert accept(sk, test_doc, mode="record", source=twin_of(sk, mode="pipeline_test"), **kw).reasons == (
        "a pipeline-test document is excluded from any corpus of record",)
    assert accept(sk, record_doc, mode="pipeline_test", source=twin_of(sk), **kw).reasons == (
        "a document made for a corpus of record is not accepted into a pipeline test",)
    for mode in (None, "test"):
        with pytest.raises(ValueError, match="names its mode"):
            accept(sk, record_doc, mode=mode, **kw)


def test_a_pipeline_test_is_placed_apart_from_every_corpus_of_record_and_never_in_a_sealed_or_judged_split(tmp_path):
    b1, b2, b3 = three_bases()
    entries = [(sk, made(sk, mode="pipeline_test")) for b in (b1, b2, b3) for sk in (b.consistent, b.planted[0])]
    verdicts = {d.doc_id: Verdict(id=d.doc_id, accepted=True) for _, d in entries}
    folders = {"data_dir": tmp_path / "data", "sealed": tmp_path / "sealed", "judged": tmp_path / "judged"}
    kw = {"version": "v0.1", "license": LICENSE, "canaries": CANARIES, "checks": CHECKS, **folders}
    for split in ("test", "judged"):
        assignment = {b1.base_id: "development", b2.base_id: "calibration", b3.base_id: split}
        with pytest.raises(ValueError, match=f"never enters a sealed or judged split, and base {b3.base_id} is "
                                             f"assigned the {split} split"):
            export.place(assignment, entries, verdicts, mode="pipeline_test", **kw)
    assignment = {b1.base_id: "development", b2.base_id: "calibration", b3.base_id: "development"}
    with pytest.raises(ValueError, match="a pipeline-test document is excluded from any corpus of record, and "):
        export.place(assignment, entries, verdicts, mode="record", **kw)
    mixed = entries[:-1] + [(entries[-1][0], made(entries[-1][0]))]
    with pytest.raises(ValueError, match="a pipeline test places only its own documents"):
        export.place(assignment, mixed, verdicts, mode="pipeline_test", **kw)
    assert not any((tmp_path / f).exists() for f in ("data", "sealed", "judged"))
    written = export.place(assignment, entries, verdicts, mode="pipeline_test", **kw)
    folder = tmp_path / "data" / "pipeline_test" / "v0.1"
    assert written == {"development": folder, "calibration": folder}
    assert sorted(p.name for p in (tmp_path / "data").iterdir()) == ["pipeline_test"]
    readme = (folder / "README.md").read_text(encoding="utf-8")
    assert export.PIPELINE_TEST_NOTICE in readme and export.NOTICE in readme
    lines = [json.loads(line) for split in ("development", "calibration")
             for line in (folder / f"{split}.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(lines) == 6 and {r["mode"] for r in lines} == {"pipeline_test"}


def test_a_split_holds_records_of_one_mode_and_a_pipeline_test_s_never_the_test_or_judged_split(tmp_path):
    sk = base().planted[0]
    test_rec = export.record(sk, made(sk, mode="pipeline_test"), canary=CANARY)
    record_rec = export.record(sk, made(sk), canary=CANARY)
    assert (test_rec.mode, record_rec.mode) == ("pipeline_test", "record")
    kw = {"license": LICENSE, "canary": CANARY}
    for split in ("test", "judged"):
        with pytest.raises(ValueError, match=f"never enters a sealed or judged split, and this is the {split} split"):
            export.write_split(tmp_path / "out", split, [test_rec], **kw)
        with pytest.raises(ValueError, match="never enters a sealed or judged split"):
            export.write_readme(tmp_path / "out", corpus_version="v0.1", splits=["development", split],
                                mode="pipeline_test", license=LICENSE, canaries=CANARIES)
    with pytest.raises(ValueError, match="a split's records are of one mode"):
        export.write_split(tmp_path / "out", "development", [record_rec, test_rec], **kw)
    assert not (tmp_path / "out").exists()
    export.write_split(tmp_path / "out", "development", [test_rec], **kw)
    export.write_split(tmp_path / "out", "test", [record_rec], **kw)


def test_a_pipeline_test_document_or_an_unlabelled_line_is_never_sealed(tmp_path):
    sk = base().planted[0]
    for name, line in (("pipeline", export.record(sk, made(sk, mode="pipeline_test"), canary=CANARY).model_dump_json()),
                       ("unlabelled", '{"doc_id": "b0001-planted"}'), ("unreadable", "not json")):
        folder = sealed_folder(tmp_path / name)
        (folder / "sub" / "more.jsonl").write_text(line + "\n", encoding="utf-8")
        found = "a pipeline-test document" if name == "pipeline" else "not labelled record"
        with pytest.raises(ValueError, match=f"a sealed split holds only documents of a corpus of record, .*: "
                                             f"sub/more.jsonl, line 1: {found}"):
            seal.write_manifest(folder, canary=CANARY)
        assert not (folder / seal.MANIFEST).exists()
    assert seal.not_of_record(sealed_folder(tmp_path / "clean")) == []


def test_a_pipeline_test_s_datasheet_says_so_and_covers_only_its_own_documents():
    b1, b2, *_ = three_bases()
    records = {split: [export.record(sk, made(sk, mode="pipeline_test"), canary=CANARIES[split])
                       for sk in (b.consistent, b.planted[0])] for split, b in (("development", b1),
                                                                               ("calibration", b2))}
    sheet = datasheet.datasheet(corpus_version="v0.1", date="2026-09-25", mode="pipeline_test", records=records,
                                canaries=CANARIES)
    lines = sheet.splitlines()
    assert [line for line in lines if line.startswith("## ")] == ["## Pipeline test"] + SECTIONS
    assert export.PIPELINE_TEST_NOTICE in lines
    assert "- Test split manifest hash: none: a pipeline test has no sealed or judged split." in lines
    assert "- Recommended: testing XonForge's pipeline; this is not a corpus of record." in lines
    assert "In this pipeline test the reviewers were not required to be of other providers" in sheet
    kw = {"corpus_version": "v0.1", "date": "2026-09-25", "canaries": CANARIES}
    with pytest.raises(ValueError, match="a datasheet covers one corpus, whose records are all of its mode"):
        datasheet.datasheet(mode="record", records=records, **kw)
    with pytest.raises(ValueError, match="never enters a sealed or judged split, and records are given for test"):
        datasheet.datasheet(mode="pipeline_test", records={"test": records["development"]},
                            **{**kw, "canaries": {"test": CANARY}})
    with pytest.raises(ValueError, match="a pipeline test has no sealed split, so no manifest hash"):
        datasheet.datasheet(mode="pipeline_test", records=records, manifest_hash="a" * 64, **kw)
