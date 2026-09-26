"""XonForge dashboard (XONFORGE_SPEC.md §10).

    streamlit run xonforge/app/dashboard.py
    python -m xonforge dashboard

Seven pages: Configure, Providers, Run, Review queue, Quality, Corpus, Logs. Keys are shown as present or missing.
Starting the sample sends API calls and waits for an explicit confirmation. The first corpus is not started.
"""
from __future__ import annotations

from pathlib import Path

import streamlit as st

from xonforge import locations, registry
from xonforge.app import views
from xonforge.corpus import terms
from xonforge.render.store import DocumentStore
from xonforge.review.decisions import DecisionLog
from xonforge.review.queue import QueueStore
from xonforge.skeleton.catalog import TRAPS, V1_PLANT_TYPES
from xonforge.skeleton.generators import PLANT_TYPES
from xonforge.skeleton.schema import Base


def _root() -> tuple[Path | None, str | None]:
    try:
        return locations.text_log_dir(), None
    except locations.LocationRefused as exc:
        return None, str(exc)


def _skeleton_for(folder: Path, document):
    if not folder.is_dir():
        return None
    for file in sorted(folder.glob("*.json")):
        base = Base.model_validate_json(file.read_text(encoding="utf-8"))
        if base.base_id != document.base_id:
            continue
        for skeleton in (base.consistent, *base.planted, *base.trap_only):
            if skeleton.variant == document.variant and skeleton.digest() == document.skeleton_digest:
                return skeleton
        for skeleton in (base.consistent, *base.planted, *base.trap_only):
            if skeleton.variant == document.variant:
                return skeleton
    return None


def _bases(folder: Path) -> dict:
    found = {}
    if not folder.is_dir():
        return found
    for file in sorted(folder.glob("*.json")):
        base = Base.model_validate_json(file.read_text(encoding="utf-8"))
        found[base.base_id] = base
    return found


def page_configure(defaults: dict, root: Path | None, location_error: str | None) -> None:
    st.header("Configure")
    st.caption("Target size, mix, constants, review settings and split proportions. A saved draft is not the "
               "configuration a run loads.")
    draft = st.session_state.setdefault("draft", views.default_draft(defaults))
    plants = [*PLANT_TYPES, *V1_PLANT_TYPES]
    draft["target"] = int(st.number_input(
        "Target size (documents; a unit's meaning, document or base, is still open)",
        min_value=1, value=int(draft["target"]), step=1))
    draft["plant_types"] = st.multiselect("Plant types", plants, default=[p for p in draft["plant_types"] if p in plants])
    draft["traps"] = st.multiselect("Traps", list(TRAPS), default=[t for t in draft["traps"] if t in TRAPS])
    draft["levels"] = st.multiselect("Difficulty levels", [1, 2, 3], default=[n for n in draft["levels"] if n in (1, 2, 3)])
    draft["genres"] = [st.text_input("Genre", value=draft["genres"][0] if draft["genres"] else "office memo")]
    names = [e.name for e in registry.load_entries()]
    draft["providers"] = st.multiselect("Renderer mix", names, default=[n for n in draft["providers"] if n in names])
    draft["review_k"] = int(st.number_input("Reviewers per document (K)", min_value=1,
                                            value=int(draft["review_k"]), step=1))
    c1, c2, c3 = st.columns(3)
    draft["development"] = int(c1.number_input("Development %", min_value=0, max_value=100,
                                               value=int(draft["development"])))
    draft["calibration"] = int(c2.number_input("Calibration %", min_value=0, max_value=100,
                                               value=int(draft["calibration"])))
    draft["test"] = int(c3.number_input("Test %", min_value=0, max_value=100, value=int(draft["test"])))
    st.subheader("Constants")
    st.json(views.constants(defaults))
    problems = views.validate_draft(draft)
    if problems:
        for problem in problems:
            st.warning(problem)
        return
    st.subheader("Quota preview")
    st.caption(f"Units per plant type, level and renderer, preview seed {views.PREVIEW_SEED}. "
               "Judged plant types are not part of this mix; they go to the judged split.")
    st.dataframe(views.quota_preview(draft), hide_index=True)
    if st.button("Save draft"):
        if root is None:
            st.error(location_error)
        else:
            path = views.save_draft(root / "dashboard" / "configure.yaml", draft)
            st.success(f"Draft saved outside the repository: {path}")


def page_providers(defaults: dict) -> None:
    st.header("Providers")
    st.caption("A key is present or missing. Its value is never shown. This page does not send a test call; "
               "`python -m xonforge providers --test-call` does, and it spends the budget.")
    rows = views.provider_rows(defaults)
    st.dataframe([{
        "name": r["name"], "provider": r["provider"], "model": r["model"],
        "model id": "verified" if r["model_verified"] else "unverified",
        "key": f"{r['key_env']}: {r['key']}" if r["key_env"] else r["key"],
        "available": "yes" if r["available"] else f"no ({r['unavailable_because']})",
        "structured output": r["structured_output"],
        "USD / MTok in": r["price_in"], "USD / MTok out": r["price_out"],
        "price": "verified" if r["price_verified"] else "unverified",
        "cap tokens": r["cap_tokens"], "cap USD": r["cap_usd"], "test call": r["test_call"],
    } for r in rows], hide_index=True)
    caps = registry.caps_of(defaults, registry.load_entries())
    st.write(f"Top-level caps: tokens {caps.run_tokens if caps.run_tokens is not None else 'not set'}, "
             f"USD {caps.run_usd if caps.run_usd is not None else 'not set'}.")
    for name, config in (defaults.get("runs") or {}).items():
        run_caps = config.get("caps") or {}
        st.write(f"Run {name}: tokens {run_caps.get('run_tokens') if run_caps.get('run_tokens') is not None else 'not set'}, "
                 f"USD {run_caps.get('run_usd') if run_caps.get('run_usd') is not None else 'not set'}.")
    st.subheader("Terms of use, before any export")
    st.dataframe(views.terms_rows(), hide_index=True)
    blockers = terms.problems([r["provider"] for r in rows], terms.load())
    for blocker in blockers:
        st.warning(blocker)


def page_run(defaults: dict, root: Path | None) -> None:
    st.header("Run")
    st.caption("Cost is estimated offline. Duration is not estimated: no duration model is registered. "
               "Pause is the budget cap stopping the run. Resume continues from the cache.")
    names = sorted((defaults.get("runs") or {"sample": {}}).keys())
    name = st.selectbox("Run configuration", names, index=names.index("sample") if "sample" in names else 0)
    status = views.run_status(name, defaults)
    st.write(f"Mode: {status['mode'] or 'unknown'}. Renderers: {', '.join(status['renderers']) or 'none'}. "
             f"Reviewers: {', '.join(status['reviewers']) or 'none'}.")
    if status["problems"]:
        for problem in status["problems"]:
            st.error(problem)
    else:
        st.success("It may start.")
    if name == "sample" and status["renderers"]:
        from xonforge import estimate as estimates
        from xonforge.pipeline import sample_bases
        from xonforge.review import blind

        settings = defaults["estimate"]
        kw = {"renderers": status["renderers"], "reviewers": status["reviewers"],
              "review_prompts": tuple(blind.PROMPTS), "thinking": settings["thinking_per_call"],
              "premise_share": defaults["skeletons"]["negation_premise_share"]}
        first = estimates.plan(sample_bases(), attempts=1, **kw)
        rows = []
        for entry_name, tally in first.tallies.items():
            entry = next(e for e in registry.load_entries() if e.name == entry_name)
            rows.append({"entry": entry_name, "calls": int(tally.calls),
                         "USD, first attempts": estimates.usd(tally, entry, settings)})
        st.subheader("Pre-run cost estimate")
        st.write(f"{first.documents} documents, {first.reviewed_items} reviewed items per reviewer and prompt, "
                 "canaries included. First attempts, with the assumed thinking.")
        st.dataframe(rows, hide_index=True)
        st.write(f"Run cap: USD {status['run_usd'] if status['run_usd'] is not None else 'not set'}.")
    if root is not None:
        from xon_common.calllog import CallLog

        log_path = locations.ROOT / defaults["call_log"]
        spent = CallLog(log_path).spent(name) if log_path.exists() else {}
        st.subheader("Live cost")
        if spent:
            st.dataframe([{"entry": n, "tokens": t, "USD": u} for n, (t, u) in spent.items()], hide_index=True)
        else:
            st.info(f"No answered calls for {name} are in the call log.")
        manifest = root / "runs" / f"{name}.json"
        st.subheader("Progress")
        if manifest.exists():
            import json
            data = json.loads(manifest.read_text(encoding="utf-8"))
            st.write(f"Run record: {data.get('status', 'unknown')}.")
            composition = data.get("composition") or []
            documents = DocumentStore(root / "documents").documents(name)
            rendered = {d.base_id for d in documents if d.status == "rendered"}
            by_seed = {(base.planted[0].plant.type, base.consistent.seed): base.base_id
                       for base in _bases(root / "skeletons" / name).values()}
            st.dataframe([{
                "plant type": row["plant_type"], "level": row["level"], "seed": row["seed"],
                "rendered": "yes" if by_seed.get((row["plant_type"], row["seed"])) in rendered else "no",
            } for row in composition], hide_index=True)
            failed = [d for d in documents if d.status != "rendered"]
            retried = [d for d in documents if len(d.attempts) > 1]
            st.write(f"Failures: {len(failed)}. Documents that took more than one attempt: {len(retried)}.")
            if failed:
                st.dataframe([{"doc_id": d.doc_id, "attempts": len(d.attempts),
                               "failed checks": "; ".join(msg for a in d.attempts for msg in a.failed)}
                              for d in failed], hide_index=True)
        else:
            st.info("No run record yet. Progress by quota cell appears after a run has generated its composition.")
    confirmed = st.checkbox("Start or resume the sample. This sends API calls, within the sample's caps.")
    typed = st.text_input("Type the run name to confirm", value="")
    if st.button("Start or resume"):
        if name != "sample" or not status["allowed"]:
            st.error(status["problems"][0] if status["problems"] else "This run may not start.")
        elif not confirmed or typed != "sample":
            st.warning("Confirm the checkbox and type sample. Nothing was started.")
        else:
            from xonforge.pipeline import execute

            report = execute(registry.Session(name, run_config=name))
            st.write(report.text())


def page_review(root: Path | None, location_error: str | None) -> None:
    st.header("Review queue")
    if root is None:
        st.error(location_error)
        return
    runs = sorted(p.stem for p in (root / "reviews" / "queue").glob("*.json")) if (root / "reviews" / "queue").is_dir() else []
    if not runs:
        st.info("No review queue is stored yet.")
        return
    run = st.selectbox("Run", runs)
    items = QueueStore(root / "reviews" / "queue").load(run)
    log = DecisionLog(root / "reviews" / "decisions.jsonl")
    decisions = log.entries()
    st.json(views.queue_statistics(items, decisions))
    if not items:
        return
    labels = [i.doc_id for i in items]
    doc_id = st.selectbox("Document", labels)
    item = next(i for i in items if i.doc_id == doc_id)
    document = DocumentStore(root / "documents").load(run, doc_id)
    st.subheader("Flags")
    for reason in item.reasons:
        st.write(reason)
    if document is None:
        st.warning("The document is not in the document store.")
        return
    skeleton = _skeleton_for(root / "skeletons" / run, document)
    text_col, map_col = st.columns(2)
    text_col.subheader("Text")
    text_col.write(document.text or "(no text)")
    map_col.subheader("Skeleton and span map")
    if skeleton is None:
        map_col.write("The skeleton is not in the skeleton store.")
        map_col.dataframe([{"fact": fid, "span": span} for fid, span in document.spans.items()], hide_index=True)
    else:
        map_col.dataframe(views.fact_rows(skeleton, document.spans), hide_index=True)
    st.subheader("Decision")
    decision = st.radio("Decision", views.DECISIONS, horizontal=True)
    reason = st.text_input("Reason")
    reviewer = st.text_input("Reviewer (optional)")
    if st.button("Record decision"):
        try:
            entry = views.record_decision(log, run, doc_id, decision, reason, reviewer.strip() or None)
        except ValueError as exc:
            st.error(str(exc))
        else:
            st.session_state["review_notice"] = (
                f"Recorded {entry.decision} for {entry.doc_id}. Head {entry.hash}.")
            st.rerun()
    notice = st.session_state.pop("review_notice", None)
    if notice:
        st.success(notice)


def page_quality(root: Path | None, location_error: str | None) -> None:
    st.header("Quality")
    if root is None:
        st.error(location_error)
        return
    doc_root = root / "documents"
    runs = sorted(p.name for p in doc_root.iterdir() if p.is_dir()) if doc_root.is_dir() else []
    if not runs:
        st.info("No documents are stored yet, so there is no calibration, flag rate or difficulty to show.")
    else:
        run = st.selectbox("Run", runs)
        documents = DocumentStore(doc_root).documents(run)
        st.subheader("Flag rates by renderer")
        st.dataframe(views.flag_rates(documents), hide_index=True)
        st.subheader("Difficulty, set against measured")
        st.dataframe(views.difficulty_rows(documents), hide_index=True)
        packet = root / "runs" / f"{run}-review.md"
        st.subheader("Reviewer calibration")
        if packet.exists():
            lines = views.score_lines(packet.read_text(encoding="utf-8"))
            if lines:
                for line in lines:
                    st.write(line)
            else:
                st.info("The review packet has no calibration line.")
        else:
            st.info("No review packet is stored, so no recall on canaries is available.")
    st.subheader("Solver discards")
    skeleton_root = root / "skeletons" if root is not None else None
    if skeleton_root is None or not skeleton_root.is_dir():
        st.info("No skeleton store is available.")
        return
    run_names = sorted(p.name for p in skeleton_root.iterdir() if p.is_dir())
    if not run_names:
        st.info("The skeleton store is empty.")
        return
    chosen = st.selectbox("Skeleton store", run_names, key="discard-run")
    counts = views.solver_discard_counts(skeleton_root / chosen)
    st.write(f"Kept: {counts['kept']}. Discarded: {counts['discarded']}.")
    for problem in counts["problems"]:
        st.write(problem)


def page_corpus(root: Path | None, location_error: str | None) -> None:
    st.header("Corpus")
    st.caption("Browse what is stored. Export and seal stay closed for a pipeline test, and while terms are unchecked. "
               "The first corpus is not started from here.")
    if root is None:
        st.error(location_error)
        documents = []
        decisions = []
        run = None
    else:
        doc_root = root / "documents"
        runs = sorted(p.name for p in doc_root.iterdir() if p.is_dir()) if doc_root.is_dir() else []
        run = st.selectbox("Run", runs) if runs else None
        documents = DocumentStore(doc_root).documents(run) if run else []
        log_path = root / "reviews" / "decisions.jsonl"
        decisions = DecisionLog(log_path).entries() if log_path.exists() else []
    variants = sorted({d.variant for d in documents})
    statuses = sorted({d.status for d in documents})
    renderers = sorted({d.renderer.entry for d in documents})
    c1, c2, c3 = st.columns(3)
    variant = c1.selectbox("Variant", ["any", *variants])
    status = c2.selectbox("Status", ["any", *statuses])
    renderer = c3.selectbox("Renderer", ["any", *renderers])
    needle = st.text_input("Document id contains")
    shown = views.filter_documents(documents, variant=None if variant == "any" else variant,
                                   status=None if status == "any" else status,
                                   renderer=None if renderer == "any" else renderer, doc_id=needle)
    st.write(f"{len(shown)} documents.")
    if shown:
        doc_id = st.selectbox("Document", [d.doc_id for d in shown])
        document = next(d for d in shown if d.doc_id == doc_id)
        skeleton = _skeleton_for(root / "skeletons" / run, document) if root is not None and run else None
        st.subheader("Provenance")
        st.json(views.provenance(document, skeleton, decisions))
    preview = views.datasheet_preview(documents)
    st.subheader("Datasheet preview")
    st.write(preview["notice"])
    for section in preview["sections"]:
        st.write(f"- {section}")
    st.subheader("Export and seal")
    for reason in preview["refusal"]:
        st.warning(reason)
    if not preview["refusal"]:
        st.success("The documents may be exported. Sealing waits for that export, and the first corpus is a later step.")


def page_logs(defaults: dict, root: Path | None, location_error: str | None) -> None:
    st.header("Logs")
    st.subheader("Run log")
    log_path = locations.ROOT / defaults["call_log"]
    rows = views.call_rows(log_path)
    if rows:
        st.dataframe(rows, hide_index=True)
    else:
        st.info(f"No call log at {log_path}.")
    st.subheader("Changelog")
    changelog = locations.ROOT / "CHANGELOG_EXPERIMENTS.md"
    st.text(views.changelog_latest(changelog.read_text(encoding="utf-8")) if changelog.exists() else "No changelog.")
    st.subheader("Decision log")
    if root is None:
        st.error(location_error)
        return
    verification = views.decision_verification(DecisionLog(root / "reviews" / "decisions.jsonl"))
    if verification["ok"]:
        st.success(verification["detail"])
    else:
        st.error(verification["detail"])


def main() -> None:
    st.set_page_config(page_title="XonForge", layout="wide")
    st.sidebar.title("XonForge")
    page = st.sidebar.radio("Page", views.PAGES)
    defaults = registry.load_defaults()
    root, location_error = _root()
    if page == "Configure":
        page_configure(defaults, root, location_error)
    elif page == "Providers":
        page_providers(defaults)
    elif page == "Run":
        page_run(defaults, root)
    elif page == "Review queue":
        page_review(root, location_error)
    elif page == "Quality":
        page_quality(root, location_error)
    elif page == "Corpus":
        page_corpus(root, location_error)
    else:
        page_logs(defaults, root, location_error)


if __name__ == "__main__":
    main()
