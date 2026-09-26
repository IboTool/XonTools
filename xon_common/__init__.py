"""Code shared by xon/ and xonforge/ (the spec's xon-common, XONFORGE_SPEC.md §4): the provider modules, the response
cache, budgets, the spend and call log, transport retries and request hashing.

It imports neither xonforge nor the consistency engine (tests/xonforge/test_xonforge_boundary.py), and from
xon/llm/client.py only the two hashing functions (hashing.py).
"""
