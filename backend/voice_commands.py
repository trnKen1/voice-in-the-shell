"""Interpreting short spoken/typed responses as yes/no.

Used to resolve a pending tool-permission confirmation from whatever the
active-listening pipeline (or the shell's manual "T" test path) next
recognizes, instead of treating it as a new agent query.
"""

import re

ALLOW_PHRASES = [
    "yes", "yeah", "yep", "yup", "sure", "allow", "approve",
    "go ahead", "do it", "confirm", "okay", "ok",
]
DENY_PHRASES = [
    "no", "nope", "nah", "deny", "don't", "do not", "stop", "cancel", "negative",
]


def _matches_any(text: str, phrases: list[str]) -> bool:
    return any(re.search(rf"\b{re.escape(phrase)}\b", text) for phrase in phrases)


def interpret_yes_no(text: str) -> bool | None:
    """Returns True (allow), False (deny), or None if ambiguous/no match —
    an ambiguous utterance should never be guessed at, only ignored."""
    normalized = text.lower().strip()
    allowed = _matches_any(normalized, ALLOW_PHRASES)
    denied = _matches_any(normalized, DENY_PHRASES)
    if allowed and not denied:
        return True
    if denied and not allowed:
        return False
    return None
