"""A run's mode (the user's decisions of 2026-09-25, xonforge/docs/decisions.md, which re-specify XONFORGE_SPEC.md §0
and §7.3 for the pipeline-test mode only). Every run names its mode: there is no default, and the pipeline-test mode is
never a fallback for missing providers.

- ``record``: a corpus of record. Reviewers are never from the renderer's provider, and a run needs at least three
  configured providers.
- ``pipeline_test``: the renderer and the reviewers may be models of one provider, and must be different models. Every
  document made in this mode is labelled ``pipeline_test``, never enters a sealed or judged split, and is excluded from
  any corpus of record; the datasheet says so.
"""
from __future__ import annotations

RECORD, PIPELINE_TEST = "record", "pipeline_test"
MODES = (RECORD, PIPELINE_TEST)
MIN_PROVIDERS = 3        # configured providers a corpus-of-record run needs


def check(mode) -> str:
    if mode not in MODES:
        raise ValueError(f"a run names its mode, record or pipeline_test, and not {mode!r}")
    return mode
