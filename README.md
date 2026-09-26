# XonTools: evidence-clamped consistency checking for AI oversight

XonTools asks whether the claims in a text, such as an LLM's answer, a report, or eventually an agent's account of what it did, can all be true together, given evidence you trust. A language model reads the text into claims and relations; everything after that is exact mathematics, so every verdict comes with the specific claims and relations that cause it.

The repository is a research project in progress. One component is built and has a pre-registered result (the consistency engine, A1). The safety tool it is meant to support (an agent transcript monitor, A2) is fully specified but not yet built. Results so far, including where the engine loses to a strong LLM judge, are reported below.

---

## The problem

Oversight of AI systems increasingly means reading what they say about themselves: plans, progress reports, summaries of tool output, claims that tests pass. Three difficulties make this hard to automate:

- **Contradictions spread across many sentences are invisible to pairwise checks.** "Ana is older than Ben," "Ben is older than Cara," … "Hana is older than Ana": no two of these eight sentences conflict, but all eight cannot be true. A checker that compares statements two at a time never sees it.
- **An LLM judge is opaque, and can become a training target.** A strong judge may notice the conflict, but it gives no structural account of why, and if its verdicts ever feed back into training, the monitored model learns to satisfy the judge rather than to be consistent.
- **Not all statements deserve equal trust.** A test log is evidence; an agent's summary of the test log is a claim. A useful checker has to hold trusted evidence fixed and ask what it implies for everything else.

## What the engine does (A1, built)

Given a text, the engine:

1. **Extracts claims** with an LLM, each marked as asserted, a premise ("Assume that…"), or quoted.
2. **Scores how pairs of claims relate** (supports, contradicts, unrelated, with a confidence and a rationale), building a signed claim graph.
3. **Extracts relations between entities** (same, different, greater, on each attribute, with the attribute's number of values when the text states it), building an entity graph.
4. **Checks both graphs exactly**, with no further model calls:
   - **Balance** of the signed claim graph (Harary, 1953) and its shortest frustrated cycle, the smallest set of claims that cannot all hold.
   - **Conflict:** the smallest eigenvalue of the signed Laplacian (Kunegis et al., 2010), computed as a cellular-sheaf Laplacian.
   - **Harmony under clamped evidence:** the minimum energy of a real-valued truth assignment with trusted claims fixed at true and a prior that asserted claims are true, solved exactly. Invariant tests guarantee the score cannot be improved by dropping evidence, cutting relations, or rewriting observations.
   - **Localization:** per-claim residuals and counterfactual culprits (how much the conflict would change without each claim).
   - **Entity contradictions:** cycles in a strict order (A > B > … > A), equality chains broken by a "different," and odd cycles of "different" on two-valued attributes. All are found at any length.
5. **Returns a verdict** with the claims, relations and source spans behind it.

The eight-sentence age loop above is the simplest illustration. The claim graph has no edges at all, because no pair of sentences relates. The entity graph has one directed cycle through all eight people, which the engine reports as a contradiction and lists all eight sentences as its support.

The app (Streamlit) shows both graphs, the verdict, the residuals, and a JSON export of the full analysis.

## Results so far

**L1, the run of record (September 24, 2026).** A corpus of 180 short documents built from 60 base scenarios, each in a consistent version, a version with a direct (two-claim) contradiction, and a version with a contradiction that exists only jointly across three or four claims. Pass criteria were fixed before the run.

| Method | Direct F1 | Cycle F1 | False-positive rate (consistent docs) | Localization |
|---|---|---|---|---|
| Engine | 0.916 | 0.916 | 0.183 | 1.000 |
| Minimal engine (ablation) | 0.923 | 0.923 | 0.167 | 1.000 |
| Pairwise only | 0.916 | 0.329 | 0.183 | — |
| LLM judge, with thinking | 0.930 | 0.930 | 0.150 | 1.000 |
| LLM judge, no thinking | 0.805 | 0.805 | 0.483 | 1.000 |

L1b (does harmony track inconsistency, and does localization find the contradicted premise?): AUC 0.926 for 1 − harmony, against 0.528 for the raw eigenvalue; the contradicted premise was among the top three residuals in 0.933 of cases. Both pre-registered criteria passed.

**What this does and does not show:**

- The engine finds joint contradictions that pairwise checking structurally cannot (cycle F1 0.916 against 0.329).
- A strong LLM judge with extended thinking did slightly better on this corpus, at about one-twentieth of the engine's cost per document ($0.006 against $0.138). The engine's case therefore rests on structure (auditable verdicts, exact localization, evidence clamping) and on a hypothesis still to be tested: that its advantage grows with contradiction length and distance, where a judge must hold every sentence at once (see Open questions).
- The false-positive rate is too high. A post-hoc analysis attributed 10 of the engine's 11 false positives to the relation-scoring model (including judging improbability as contradiction and reasoning through claims outside the pair) and 1 to an entity extraction error. None was an unplanted contradiction.
- The corpus is small, synthetic, and was written and evaluated with models of one family (Claude). These are known weaknesses, addressed below.

The full results, the post-hoc analysis, a variance study (L1-var) and every decision behind them are in `results/` and `CHANGELOG_EXPERIMENTS.md`.

**Revision 2.2 (in development).** Fixes the causes found in the post-hoc analysis: "contradicts" now means the two claims cannot both be true, with a separate `tension` label that creates no edge; each pair is judged in isolation, so the model cannot see a third claim; entity extraction transcribes comparatives verbatim and derives their direction in code; and the confidence threshold is chosen by a rule fixed in advance. It is being developed on the L1 corpus, now treated as a development set. Its result of record will be a single run on a fresh, sealed corpus. The development pass is under way.

## Status and roadmap

| Component | What it is | Status |
|---|---|---|
| **A1** consistency engine | Claims and relations in, exact consistency analysis out | Built; L1 and L1b passed on the run of record |
| **A1 rev 2.2** | Precision fixes from the post-hoc analysis | Implemented; development pass under way |
| **XonForge** | Corpus generator: solver-verified plants, blind cross-model review with calibrated reviewers, sealed test splits, multiple model providers | Being built |
| **A2** agent transcript monitor | Checks whether what an agent intended, planned, did, observed and reported can all be true, with trusted tool output clamped as evidence; hash-chained evidence; a coding family with real executions; evaluation on public reward-hacking and misreporting data | Specified; built after rev 2.2 freezes |
| **S1** safeguards | Fail-closed three-way status (flagged, not flagged, could not assess); prompt-injection fencing; canary checks; multi-model ensembles | Specified; built with A2 |
| **C2** drift detector | Change detection on monitor traces over long agent runs | Specified |
| **Strain head** (X1) | A read-only probe on a frozen open-weight transformer, trained with the engine as teacher, to test whether a model's internal states carry a readable signal of inconsistency | Planned experiment, with stop rules |
| **A3–A5, H1–H2, C1** | A learned relation scorer, a coherence-driven agent, and research on field dynamics | Specified or deferred |

Specifications live in `SPECS/`. Each one ends with what its results would and would not mean.

## Research practice

- **Pre-registration.** Pass criteria, thresholds and analyses are fixed before each run of record. Any change is logged in `CHANGELOG_EXPERIMENTS.md` with its reason, and re-specification questions are decided before outcomes are shown.
- **Seen data becomes development data.** Once a corpus has been analyzed, fixes may be developed on it, but results of record come only from a fresh, sealed corpus, run once after a freeze. Sealed splits are stored outside the repository.
- **The system under test never screens its own test data.** Ground truth comes from structure (solvers, scripted harnesses), and reviewer models are checked against planted known defects before their clean results count.
- **Reproducibility.** Every model call is cached under a hash of the full request; runs of record replay byte for byte from the cache; freezes and runs of record are tagged in git.
- **Deliberately not built:** scores exposed to monitored agents, an interface letting agents query their own flags, "honesty" leaderboards, and any use of monitor output as reward, loss or fine-tuning data. A monitor that becomes a training signal teaches models to evade it.
- **How it was built.** Specifications were developed in collaboration with Claude (Anthropic) and implemented with Cursor. Every design decision, deviation and correction is logged.

## Open questions

Each of these is a self-contained project, and a natural place to collaborate:

- **Length crossover.** Does the engine overtake strong LLM judges as contradictions span more claims and more distance? Every link must be extracted for a cycle to close (at 0.90 per link, an eight-link cycle is extracted intact about 43% of the time), so the answer depends on extraction accuracy as much as on the judge.
- **Complementarity on real agent data.** Does the monitor add detections to a strong LLM judge on public reward-hacking and misreporting trajectories (A2's experiment MC2)?
- **Reading strain from inside a model.** Can a read-only head on a frozen transformer predict where its text strains against itself and its sources, and does using the engine as teacher generalize better than training on planted labels (the strain head, X1)?
- **Correlated failure.** How much do extraction and relation scoring improve, and how much do their errors decorrelate, with models from several families?
- **Beyond order and identity.** Numeric, temporal, modal and quantifier contradictions (future extension X2), including the hard negatives that resolve on inspection: time zones, unit conversions, overnight spans.

## Quickstart

Python 3.11 or newer.

```bash
pip install -e ".[dev]"
streamlit run app.py          # or: python -m streamlit run app.py
pytest                        # the offline test suite
```

Without an API key, the app runs in **dry-run** mode: the consistency engine answers only from the response cache and recorded fixtures and makes no network calls. For live analysis, set the key in the terminal that starts the app; it is read only from the environment and never written to disk or logs.

```powershell
$env:ANTHROPIC_API_KEY = "sk-ant-..."    # PowerShell
```

```bash
export ANTHROPIC_API_KEY=sk-ant-...      # bash
```

A 150–300-word text with 12–25 claims costs a few tens of cents to analyze. Each session has a token budget, set in the sidebar.

## Repository map

```
app.py                      Streamlit app (Consistency mode, plus the simulator's modes)
xon/llm/                    A1: client (the only module that talks to the API), prompts, schemas,
                            claim and relation extraction, the exact analysis, entity consistency,
                            the minimal engine, baselines, corpus tools, evaluation
xonforge/                   XonForge corpus generator (in development)
xon/                        the simulator and the spectral and sheaf mathematics it shares with A1
scripts/                    corpus generation and experiment runners
data/consistency/           the L1 corpus (180 documents)
results/                    runs of record, variance studies, post-hoc analyses
tests/                      pytest suite; tests/fixtures/llm/ holds recorded model responses
SPECS/                      specifications, implemented and to do
CHANGELOG_EXPERIMENTS.md    pre-registration and decision log
docs/xon_sim.md             documentation of the simulator and its experiments (E1–E9c)
```

## Origins

The project began as simulations of a mathematical model of consciousness, exploring spectral dynamics on self-similar graphs, together with ideas from cymatics and holographic theories. The simulator is still in this repository (its documentation is in `docs/xon_sim.md`), and its pre-registered experiments tested whether the model's own claims hold together; several did not. What carried over into the safety work is the mathematics of consistency: signed graphs, sheaf Laplacians, frustration, and harmony under clamped evidence. None of the results above depends on the consciousness model.

## Limitations

- The engine is only as good as its extraction. A contradiction that is not extracted as a claim or relation is invisible to the mathematics.
- All results so far come from one synthetic corpus of short texts, written and evaluated with models of one family.
- The engine currently costs far more per document than a strong LLM judge, and rev 2.2's isolated pair judgments cost several times more again.
- Harmony does not include entity-level contradictions; the verdict reports them separately.
- The monitor (A2), which is the actual oversight tool, is not yet built.

## Contact

Ian MacKenna, [gratefulrising@proton.me](mailto:gratefulrising@proton.me)

## License

Licensed under the [Apache License 2.0](LICENSE).
