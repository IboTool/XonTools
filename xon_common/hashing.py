"""Request hashing: A1's own functions, imported from xon/llm/client.py rather than rewritten, so that a request's key
here is computed exactly as A1 computes it (CHANGELOG_EXPERIMENTS.md, 2026-09-25, XonForge step 1). They are the only
names this package imports from client.py.
"""
from xon.llm.client import request_hash, request_key

__all__ = ["request_hash", "request_key"]
