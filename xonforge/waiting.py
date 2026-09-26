"""Parts that wait for the user's answer refuse with ``Waiting`` rather than guess (CHANGELOG_EXPERIMENTS.md,
XonForge)."""


class Waiting(RuntimeError):
    """A part of XonForge that waits for the user's answer to an open question, which the message names."""
