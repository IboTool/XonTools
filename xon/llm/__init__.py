"""A1 consistency engine (XON_A1_CONSISTENCY.md): claims, relations and entity relations extracted by Claude,
checked with signed-graph balance, algebraic conflict, clamped harmony and entity-relation cycles.

Every LLM call goes through ``xon.llm.client``; no other module imports the ``anthropic`` package.
"""
