"""Test hooks shared by the test modules."""
import sys

import pytest

from xon.llm import consistency, minimal

# XON_A1_MINIMAL_ENGINE.md §5 (equivalence): while a test of these modules runs, every full-engine analysis is checked
# against the minimal engine on the same claims, relations and entity graph.
A1_MODULES = {"test_consistency", "test_entity_consistency", "test_llm_engine", "test_consistency_eval",
              "test_consistency_app", "test_minimal_engine", "test_rev22"}
FULL_ANALYZE = consistency.analyze
cross_checked = {"analyses": 0}


def analyze_cross_checked(sg, entities=None, *args, **kwargs):
    """The full engine's ``analyze``, failing when the minimal engine's direct and entity contradictions on the same
    inputs, at the same threshold, are not the report's clause (a) and clause (c) outputs."""
    report = FULL_ANALYZE(sg, entities, *args, **kwargs)
    direct = minimal.direct_contradictions(sg.claims, sg.relations, report.threshold)
    entity = minimal.entity_contradictions(entities, sg.kinds, report.threshold)
    assert direct == report.direct_contradictions, (
        f"clause (a): minimal engine {direct}, full engine {report.direct_contradictions}")
    assert entity == report.verdict_entity_contradictions, (
        f"clause (c): minimal engine {entity}, full engine {report.verdict_entity_contradictions}")
    cross_checked["analyses"] += 1
    return report


@pytest.fixture(autouse=True)
def _minimal_engine_cross_check(request, monkeypatch):
    if request.module.__name__.rpartition(".")[2] in A1_MODULES:
        for module in list(sys.modules.values()):
            if getattr(module, "__dict__", {}).get("analyze") is FULL_ANALYZE:
                monkeypatch.setattr(module, "analyze", analyze_cross_checked)


def pytest_terminal_summary(terminalreporter):
    if cross_checked["analyses"]:
        terminalreporter.write_line(f"Minimal-engine cross-check: {cross_checked['analyses']} full-engine analyses in "
                                    "the A1 tests matched on clauses (a) and (c).")
