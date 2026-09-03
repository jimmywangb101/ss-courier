"""
booking_ref.py — generates unique, human-readable booking references.

Format: CRR-YYYYMMDD-XXXX   e.g. CRR-20260915-K7Q4

WHY THIS FORMAT
---------------
The reference gets read aloud down the phone and typed into an SMS. So:
  * CRR       - fixed prefix, tells you instantly it's one of our bookings
  * YYYYMMDD  - the SERVICE date, so ops can sort/search the sheet by day
  * XXXX      - random suffix from an alphabet with no 0/O/1/I/5/S, because
                those are the characters people mishear and mistype.

4 characters from a 28-symbol alphabet = 614,656 combinations per day, which is
far more than enough to avoid collisions for a single-van operation.
"""

from __future__ import annotations

import re
import secrets
from datetime import date, datetime

# Deliberately excludes 0/O, 1/I/L, 5/S, 2/Z — the classic mis-hearings.
_ALPHABET = "ABCDEFGHJKMNPQRTUVWXY346789"
_SUFFIX_LENGTH = 4
_PREFIX = "CRR"

# Matches CRR-20260915-K7Q4 (used to validate lookups before hitting Sheets)
REFERENCE_PATTERN = re.compile(rf"^{_PREFIX}-\d{{8}}-[{_ALPHABET}]{{{_SUFFIX_LENGTH}}}$")


def generate_reference(service_date: str | date | None = None) -> str:
    """Build a booking reference for the given service date.

    Args:
        service_date: "2026-09-15", a date object, or None for today.

    `secrets` (not `random`) is used so references aren't predictable — someone
    who has one reference shouldn't be able to guess another customer's.
    """
    day = _coerce_date(service_date)
    suffix = "".join(secrets.choice(_ALPHABET) for _ in range(_SUFFIX_LENGTH))
    return f"{_PREFIX}-{day:%Y%m%d}-{suffix}"


def is_valid_reference(reference: str) -> bool:
    """True if the string is shaped like one of our references."""
    return bool(REFERENCE_PATTERN.match((reference or "").strip().upper()))


def normalise_reference(reference: str) -> str:
    """Tidy up a reference typed or spoken by a human.

    Callers say "C R R 2 0 2 6..." and people type 'crr 20260915 k7q4', so we
    uppercase, strip spaces, and re-insert the dashes if they're missing.
    """
    cleaned = re.sub(r"[^A-Za-z0-9]", "", (reference or "")).upper()
    if cleaned.startswith(_PREFIX) and len(cleaned) == len(_PREFIX) + 8 + _SUFFIX_LENGTH:
        return f"{cleaned[:3]}-{cleaned[3:11]}-{cleaned[11:]}"
    return (reference or "").strip().upper()


def spell_out_reference(reference: str) -> str:
    """Turn a reference into something the voice agent reads clearly.

    'CRR-20260915-K7Q4' -> 'C R R, 2 0 2 6 0 9 1 5, K 7 Q 4'
    Spacing the characters stops the TTS engine reading 'K7Q4' as a word and
    makes the date digits land one at a time.
    """
    parts = normalise_reference(reference).split("-")
    return ", ".join(" ".join(part) for part in parts)


def _coerce_date(value: str | date | None) -> date:
    if value is None:
        return date.today()
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except ValueError:
        # Never let a malformed date block a booking — fall back to today.
        return date.today()
