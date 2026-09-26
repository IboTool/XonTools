"""The solver (XONFORGE_SPEC.md §5.5): the source of ground truth. Deterministic; it calls no model and imports nothing
from the consistency engine."""
from .solver import Unsupported, check_base, check_skeleton, minimal_contradiction, naive_contradiction, satisfiable

__all__ = ["Unsupported", "check_base", "check_skeleton", "minimal_contradiction", "naive_contradiction",
           "satisfiable"]
