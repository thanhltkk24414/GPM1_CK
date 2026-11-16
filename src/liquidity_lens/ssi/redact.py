"""Redaction of credentials before anything is printed, logged or written to disk."""
from __future__ import annotations

from typing import Any, Iterable

MASK = "***"

SENSITIVE_KEYS = frozenset(
    k.lower() for k in ("apiKey", "apiSecret", "accessToken", "refreshToken", "otp", "transactionId", "authorization")
)


def mask(obj: Any, secrets: Iterable[str | None] = ()) -> Any:
    """Return a copy of `obj` with credentials hidden.

    Values under sensitive keys (case-insensitive) become MASK, and any literal occurrence of the
    given `secrets` inside strings is replaced by MASK. The input is never modified.
    """
    literals = [s for s in secrets if s]
    return _mask(obj, literals)


def _mask(obj: Any, literals: list[str]) -> Any:
    if isinstance(obj, dict):
        return {
            k: MASK if isinstance(k, str) and k.lower() in SENSITIVE_KEYS else _mask(v, literals)
            for k, v in obj.items()
        }
    if isinstance(obj, (list, tuple)):
        return [_mask(v, literals) for v in obj]
    if isinstance(obj, str):
        for s in literals:
            obj = obj.replace(s, MASK)
        return obj
    return obj
