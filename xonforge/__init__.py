"""XonForge: a multi-model consistency corpus generator (XONFORGE_SPEC.md).

Ground truth comes from structured skeletons checked by a deterministic solver; models only render skeletons as prose.

Nothing here imports the consistency engine (xon.llm.consistency, entity_consistency, minimal, engine), directly or
transitively, except diagnostics/engine_plugin.py (§7.5; tests/xonforge/test_xonforge_boundary.py). Provider keys come
only from XonForge's own environment variables. The response cache, the sealed and judged splits and the logs that
hold text live outside the repository (locations.py); the text-free spend and call log is cache/xonforge/log.jsonl,
and XonForge never writes to cache/llm/.
"""
