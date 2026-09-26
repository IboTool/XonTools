"""XonForge's dashboard (XONFORGE_SPEC.md §10).

Seven pages, all usable with no model call: Configure, Providers, Run, Review queue, Quality, Corpus and Logs.
Keys are shown as present or missing, never as their values. Start, pause and resume do not send a call; a live run
waits until the cost estimate is approved. This module does not import the consistency engine.
"""
from __future__ import annotations

import streamlit as st

from xonforge import locations, registry, runs
from xonforge.cli import composition, format_estimate
from xonforge.corpus import datasheet
from xonforge.corpus.export import destination
from xonforge.review.decisions import DecisionLog
from xonforge.review.queue import QueueStore
from xonforge.verify.canaries import load as load_canaries
from xonforge.verify.canaries import trust as scan_trust

PAGES = ("Configure", "Providers", "Run", "Review queue", "Quality", "Corpus", "Logs")
SAMPLE = ("order_cycle:1:4", "equality_break:1:3", "binary_parity:1:2", "direct_negation:1:1")


def _config() -> dict:
    if "config" not in st.session_state:
        st.session_state["config"] = registry.load_defaults()
    return st.session_state["config"]


def _location(what):
    try:
        return what(), None
    except locations.LocationRefused as exc:
        return None, str(exc)


def page_configure() -> None:
    cfg = _config()
    st.header("Configure")
    st.caption("Edits stay in this session. Writing defaults.yaml, including its caps, waits for you.")
    cfg["render"]["min_spacing"] = st.number_input("Minimum spacing (sentences)", min_value=1, max_value=5,
                                                   value=int(cfg["render"]["min_spacing"]), key="min_spacing")
    cfg["render"]["retry_cap"] = st.number_input("Retry cap", min_value=1, max_value=5,
                                                 value=int(cfg["render"]["retry_cap"]), key="retry_cap")
    cfg["review"]["k"] = st.number_input("Reviewers per document", min_value=1, max_value=5,
                                         value=int(cfg["review"]["k"]), key="review_k")
    st.session_state["target"] = st.number_input("Target documents", min_value=2, max_value=300, value=20,
                                                 step=2, key="target_size")
    st.text_input("Mix (TYPE:LEVEL:COUNT, comma-separated)", value=", ".join(SAMPLE), key="mix")
    dev = st.number_input("Development %", min_value=0, max_value=100, value=50, key="split_dev")
    cal = st.number_input("Calibration %", min_value=0, max_value=100, value=15, key="split_cal")
    test = st.number_input("Test %", min_value=0, max_value=100, value=35, key="split_test")
    st.session_state["splits"] = {"development": dev, "calibration": cal, "test": test}
    if dev + cal + test != 100:
        st.warning("The three proportions add up to something other than 100.")


def page_providers() -> None:
    st.header("Providers")
    defaults = _config()
    entries = registry.load_entries()
    rows = registry.startup_check(entries, registry.adapters(entries, defaults), defaults, test_call=False)
    st.dataframe([{"name": r["name"], "model": r["model"], "key": r["key"], "available": "yes" if r["available"] else "no",
                   "USD in / out": f"{r['price_in']} / {r['price_out']}",
                   "caps tokens / USD": f"{r['cap_tokens']} / {r['cap_usd']}"} for r in rows], hide_index=True)
    terms = registry.load_yaml("terms.yaml") or {}
    st.subheader("Terms checklist")
    for name, item in (terms.get("providers") or {}).items():
        checked = "logged" if item.get("checked") else "not logged"
        allows = {True: "allows publishing", False: "does not allow publishing", None: "not decided"}[item.get("allows")]
        st.write(f"{name}: {checked}; {allows}")


def _problems(name: str, dry: bool) -> tuple[runs.RunConfig | None, list[str]]:
    defaults = _config()
    entries = {e.name: e for e in registry.load_entries()}
    try:
        config = runs.load(name, defaults, entries)
    except ValueError as exc:
        return None, [str(exc)]
    return config, runs.problems(config, entries, registry.adapters(list(entries.values()), defaults),
                                 k=int(defaults["review"]["k"]), dry_run=dry)


def page_run() -> None:
    st.header("Run")
    names = sorted(_config().get("runs") or {"sample": {}})
    name = st.selectbox("Run configuration", names, index=names.index("sample") if "sample" in names else 0,
                        key="run_name")
    st.session_state["paused"] = st.session_state.get("paused", True)
    config, problems = _problems(name, dry=True)
    if problems:
        st.error("It may not start: " + "; ".join(problems))
    elif config is not None:
        st.success(f"{config.name} may start as a dry run. A live run is not started from here.")
    mix = st.session_state.get("mix", ", ".join(SAMPLE))
    if st.button("Estimate", key="estimate"):
        try:
            if config is None:
                raise ValueError("the run configuration did not load")
            specs = composition([p.strip() for p in mix.split(",") if p.strip()], seed=1, trap=False)
            defaults = _config()
            entries = {e.name: e for e in registry.load_entries()}
            from xonforge import estimate as estimates
            prompts = ("contradiction_only", "relational_inventory")
            settings = defaults["estimate"]
            arguments = {"renderers": config.renderers, "reviewers": config.reviewers, "review_prompts": prompts,
                         "thinking": settings["thinking_per_call"], "genre": "office memo",
                         "premise_share": defaults["skeletons"]["negation_premise_share"]}
            first = estimates.plan(specs, attempts=1, **arguments)
            every = estimates.plan(specs, attempts=int(defaults["render"]["retry_cap"]), **arguments)
            st.text(format_estimate(config, entries, settings, first, every, list(prompts)))
        except (ValueError, TypeError) as exc:
            st.error(str(exc))
    cols = st.columns(3)
    if cols[0].button("Start", key="start"):
        st.session_state["paused"] = False
        st.info("Start does not send a call. Approve the estimate, then run it from the command line.")
    if cols[1].button("Pause", key="pause"):
        st.session_state["paused"] = True
        st.info("Paused. No call was sent.")
    if cols[2].button("Resume", key="resume"):
        st.session_state["paused"] = False
        st.info("Resume replays the cache only in this phase. No call was sent.")
    st.write("Paused." if st.session_state["paused"] else "Not paused. Still no call has been sent.")


def page_queue() -> None:
    st.header("Review queue")
    _, problem = _location(locations.cache_dir)
    if problem:
        st.info(problem)
        return
    run = st.text_input("Run", value="sample", key="queue_run")
    items = QueueStore().load(run)
    if not items:
        st.write("The queue is empty.")
    for item in items:
        st.write(f"{item.doc_id}: {'; '.join(item.reasons)}")
    doc = st.text_input("Document", value=items[0].doc_id if items else "", key="queue_doc")
    reason = st.text_input("Reason", value="", key="queue_reason")
    choice = st.radio("Decision", ("accept", "regenerate", "discard"), key="queue_decision", horizontal=True)
    if st.button("Record decision", key="queue_record"):
        if not doc or not reason.strip():
            st.error("A decision names the document and a reason.")
        else:
            entry = DecisionLog().decide(run, doc, choice, reason.strip(), reviewer="dashboard")
            st.success(f"Recorded {entry.decision} for {entry.doc_id}.")


def page_quality() -> None:
    st.header("Quality")
    trusted = scan_trust(load_canaries())
    st.dataframe([{"scan": t.scan, "trusted": t.trusted, "caught": len(t.caught), "missed": len(t.missed)}
                  for t in trusted.values()], hide_index=True)
    _, problem = _location(locations.cache_dir)
    if problem:
        st.info("No queue to count flag rates from: " + problem)
        return
    items = QueueStore().load(st.session_state.get("queue_run", "sample"))
    st.write(f"Queue items for this session's run: {len(items)}.")


def page_corpus() -> None:
    st.header("Corpus")
    st.write("A pipeline-test run is not split or sealed. These actions call the corpus code and do not write a split.")
    if st.button("Preview datasheet", key="datasheet"):
        text = datasheet.datasheet(corpus_version="sample", date="2026-09-26", mode="pipeline_test",
                                   records={}, canaries={})
        st.text(text[:1500])
    if st.button("Try to place a sealed split", key="seal"):
        try:
            destination("test", "sample", mode="pipeline_test")
        except (ValueError, locations.LocationRefused) as exc:
            st.error(str(exc))


def page_logs() -> None:
    st.header("Logs")
    _, problem = _location(locations.cache_dir)
    if problem:
        st.info(problem)
        return
    try:
        count, head = DecisionLog().verify()
    except Exception as exc:
        st.error(f"{type(exc).__name__}: {exc}")
        return
    st.write(f"Decision log: {count} entries. Head {head}.")


def main() -> None:
    st.set_page_config(page_title="XonForge", layout="wide")
    st.sidebar.title("XonForge")
    page = st.sidebar.radio("Page", PAGES, key="page")
    {"Configure": page_configure, "Providers": page_providers, "Run": page_run, "Review queue": page_queue,
     "Quality": page_quality, "Corpus": page_corpus, "Logs": page_logs}[page]()


main()
