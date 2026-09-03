"""
utils.py — shared helpers for dates, times and speech formatting.

WHY THIS EXISTS
---------------
A voice agent does NOT hand you clean data. The caller says "tomorrow at half
two" and the speech-to-text gives us "tomorrow", "2:30pm", "14.30" or "half
two" depending on the day. If we passed that straight into Cal.com we would get
constant 400 errors mid-call.

So everything from Vapi goes through normalise_date()/normalise_time() first,
which turn messy human input into strict "YYYY-MM-DD" and "HH:MM".

The speak_* helpers do the reverse: they turn our clean data back into words a
British TTS voice reads naturally ("the fifteenth of September", "forty-two
pounds seventy-five" rather than "2026-09-15" and "42.75").
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime, time, timedelta, timezone

log = logging.getLogger(__name__)

# ── Timezone ──────────────────────────────────────────────────────────────────
# Windows does not ship the IANA timezone database, so ZoneInfo("Europe/London")
# only works if the `tzdata` package is installed (it is in requirements.txt).
# If it is missing we fall back to UTC rather than crashing — the app still runs,
# it just will not adjust for British Summer Time.
try:
    from zoneinfo import ZoneInfo

    LONDON = ZoneInfo("Europe/London")
except Exception:  # pragma: no cover - depends on the host machine
    log.warning("tzdata not installed - falling back to UTC. Run: pip install tzdata")
    LONDON = timezone.utc


def london_now() -> datetime:
    """Current time in the client's timezone (handles GMT/BST automatically)."""
    return datetime.now(LONDON)


# ── Date parsing ──────────────────────────────────────────────────────────────

_MONTHS = {
    "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3,
    "april": 4, "apr": 4, "may": 5, "june": 6, "jun": 6, "july": 7, "jul": 7,
    "august": 8, "aug": 8, "september": 9, "sept": 9, "sep": 9, "october": 10,
    "oct": 10, "november": 11, "nov": 11, "december": 12, "dec": 12,
}

_WEEKDAYS = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
}


def normalise_date(value: str | None, *, today: date | None = None) -> str:
    """Turn spoken/typed dates into strict YYYY-MM-DD.

    Understands: "2026-09-15", "15/09/2026" (UK day-first), "today",
    "tomorrow", "next tuesday", "15 September", "September 15th".

    Falls back to today's date if it cannot understand the input — a booking on
    the wrong day is recoverable, a crashed phone call is not. The agent is
    prompted to read the date back to the caller for confirmation.
    """
    today = today or london_now().date()
    if not value:
        return today.isoformat()

    text = str(value).strip().lower()

    # 1. Already ISO — the happy path.
    iso = re.match(r"^(\d{4})-(\d{2})-(\d{2})", text)
    if iso:
        try:
            return date(int(iso.group(1)), int(iso.group(2)), int(iso.group(3))).isoformat()
        except ValueError:
            return today.isoformat()

    # 2. Relative words.
    if "today" in text or "this afternoon" in text or "this morning" in text:
        return today.isoformat()
    if "tomorrow" in text:
        return (today + timedelta(days=1)).isoformat()
    if "day after tomorrow" in text:
        return (today + timedelta(days=2)).isoformat()

    # 3. "next tuesday" / "on friday" — the next occurrence of that weekday.
    for name, index in _WEEKDAYS.items():
        if name in text:
            days_ahead = (index - today.weekday()) % 7
            if days_ahead == 0 or "next" in text:
                days_ahead = days_ahead or 7
            return (today + timedelta(days=days_ahead)).isoformat()

    # 4. UK numeric format, day first: 15/09/2026 or 15-9-26.
    numeric = re.match(r"^(\d{1,2})[/.\-](\d{1,2})(?:[/.\-](\d{2,4}))?$", text)
    if numeric:
        day, month = int(numeric.group(1)), int(numeric.group(2))
        year = int(numeric.group(3)) if numeric.group(3) else today.year
        if year < 100:
            year += 2000
        parsed = _safe_date(year, month, day, today)
        if parsed:
            return parsed

    # 5. "15 september 2026" or "september 15th".
    for name, month in _MONTHS.items():
        if name in text:
            day_match = re.search(r"(\d{1,2})(?:st|nd|rd|th)?", text)
            year_match = re.search(r"(20\d{2})", text)
            day = int(day_match.group(1)) if day_match else 1
            year = int(year_match.group(1)) if year_match else today.year
            parsed = _safe_date(year, month, day, today)
            if parsed:
                return parsed

    log.warning("Could not parse date %r - defaulting to today", value)
    return today.isoformat()


def _safe_date(year: int, month: int, day: int, today: date) -> str | None:
    """Build a date, rolling into next year if the date has already passed.

    If a caller says "the 3rd of January" in December they mean next January,
    not one that is already gone.
    """
    try:
        candidate = date(year, month, day)
    except ValueError:
        return None
    if candidate < today and candidate.year == today.year:
        try:
            candidate = date(year + 1, month, day)
        except ValueError:
            return None
    return candidate.isoformat()


# ── Time parsing ──────────────────────────────────────────────────────────────

def normalise_time(value: str | None) -> str:
    """Turn spoken/typed times into strict 24-hour HH:MM.

    Understands: "14:30", "2:30pm", "2pm", "1430", "14.30", "half past two",
    "quarter past nine", "noon", "midday", "midnight".
    Defaults to 09:00 when unreadable.
    """
    if not value:
        return "09:00"

    text = str(value).strip().lower().replace(".", ":")

    if "noon" in text or "midday" in text:
        return "12:00"
    if "midnight" in text:
        return "00:00"

    is_pm = "pm" in text or "evening" in text or "afternoon" in text
    is_am = "am" in text or "morning" in text

    # "half past two", "quarter past nine", "quarter to five"
    worded = re.search(r"(half|quarter)\s+(past|to)\s+(\w+)", text)
    if worded:
        hour = _word_to_number(worded.group(3))
        if hour is not None:
            minutes = 30 if worded.group(1) == "half" else 15
            if worded.group(2) == "to":
                hour, minutes = hour - 1, 60 - minutes
            return _apply_meridiem(hour, minutes, is_pm, is_am)

    # "1430" — four bare digits. A leading zero ("0230") means the caller/system
    # gave us an explicit 24-hour time, so we must NOT nudge it to the afternoon.
    bare = re.match(r"^(\d{4})$", text.replace(":", "").strip())
    if bare:
        digits = bare.group(1)
        return _apply_meridiem(int(digits[:2]), int(digits[2:]), False, False,
                               explicit_24h=True)

    # "14:30" / "2:30pm" — again, "02:30" is explicit 24-hour, "2:30" is not.
    hhmm = re.search(r"(\d{1,2}):(\d{2})", text)
    if hhmm:
        return _apply_meridiem(int(hhmm.group(1)), int(hhmm.group(2)), is_pm, is_am,
                               explicit_24h=hhmm.group(1).startswith("0"))

    # "2pm" / "9 in the morning"
    hour_only = re.search(r"(\d{1,2})", text)
    if hour_only:
        return _apply_meridiem(int(hour_only.group(1)), 0, is_pm, is_am,
                               explicit_24h=hour_only.group(1).startswith("0"))

    # "two o'clock"
    spelled = _word_to_number(text)
    if spelled is not None:
        return _apply_meridiem(spelled, 0, is_pm, is_am)

    log.warning("Could not parse time %r - defaulting to 09:00", value)
    return "09:00"


_NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
}


def _word_to_number(text: str) -> int | None:
    for word, number in _NUMBER_WORDS.items():
        if word in text:
            return number
    return None


def _apply_meridiem(hour: int, minute: int, is_pm: bool, is_am: bool,
                    *, explicit_24h: bool = False) -> str:
    """Convert a 12-hour reading into 24-hour, then clamp to a valid time.

    THE AMBIGUITY PROBLEM: a caller who says "half past two" means 14:30, not
    02:30 — courier collections at half two in the morning are vanishingly rare.
    So when no am/pm was given and the hour is 1-6, we assume afternoon.

    We skip that assumption when the input was explicitly 24-hour ("0230",
    "02:30"), because a leading zero means someone deliberately wrote 24-hour
    time. The agent also reads the time back to the caller for confirmation, so
    a wrong guess gets caught on the call.
    """
    if is_pm and hour < 12:
        hour += 12
    elif is_am and hour == 12:
        hour = 0
    elif not is_pm and not is_am and not explicit_24h and 1 <= hour <= 6:
        hour += 12  # "half two" -> 14:30

    hour = max(0, min(23, hour))
    minute = max(0, min(59, minute))
    return f"{hour:02d}:{minute:02d}"


# ── Conversion for calendar APIs ──────────────────────────────────────────────

def to_utc_iso(date_str: str, time_str: str) -> str:
    """Combine a local London date + time into a UTC ISO-8601 timestamp.

    Cal.com expects UTC. In summer London is UTC+1, so a 10:00 BST collection
    must be sent as 09:00Z — getting this wrong books every summer job an hour
    out, which is exactly the sort of bug that only shows up in June.
    """
    day = datetime.strptime(normalise_date(date_str), "%Y-%m-%d").date()
    parts = normalise_time(time_str).split(":")
    local = datetime.combine(day, time(int(parts[0]), int(parts[1])), tzinfo=LONDON)
    return local.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def local_datetime(date_str: str, time_str: str) -> datetime:
    """The booking moment as a timezone-aware London datetime."""
    day = datetime.strptime(normalise_date(date_str), "%Y-%m-%d").date()
    parts = normalise_time(time_str).split(":")
    return datetime.combine(day, time(int(parts[0]), int(parts[1])), tzinfo=LONDON)


# ── Speech formatting (British English) ───────────────────────────────────────

_ORDINALS = {1: "first", 2: "second", 3: "third", 5: "fifth", 8: "eighth",
             9: "ninth", 12: "twelfth", 20: "twentieth", 21: "twenty-first",
             22: "twenty-second", 23: "twenty-third", 30: "thirtieth",
             31: "thirty-first"}


def speak_date(date_str: str) -> str:
    """'2026-09-15' -> 'Tuesday the fifteenth of September'.

    Reading the raw ISO string aloud sounds robotic ("two thousand and twenty
    six dash zero nine"), so we spell it the way a British person would say it.
    """
    try:
        day = datetime.strptime(normalise_date(date_str), "%Y-%m-%d").date()
    except ValueError:
        return date_str

    ordinal = _ORDINALS.get(day.day)
    if not ordinal:
        tens = {4: "fourth", 6: "sixth", 7: "seventh", 10: "tenth",
                11: "eleventh", 13: "thirteenth", 14: "fourteenth",
                15: "fifteenth", 16: "sixteenth", 17: "seventeenth",
                18: "eighteenth", 19: "nineteenth", 24: "twenty-fourth",
                25: "twenty-fifth", 26: "twenty-sixth", 27: "twenty-seventh",
                28: "twenty-eighth", 29: "twenty-ninth"}
        ordinal = tens.get(day.day, str(day.day))

    return f"{day:%A} the {ordinal} of {day:%B}"


def speak_time(time_str: str) -> str:
    """'14:30' -> 'half past two in the afternoon'; '09:00' -> 'nine in the morning'."""
    normalised = normalise_time(time_str)
    hour, minute = (int(part) for part in normalised.split(":"))

    if hour < 12:
        period = "in the morning"
    elif hour < 17:
        period = "in the afternoon"
    else:
        period = "in the evening"

    display_hour = hour % 12 or 12
    words = {v: k for k, v in _NUMBER_WORDS.items()}
    spoken_hour = words.get(display_hour, str(display_hour))

    if minute == 0:
        return f"{spoken_hour} o'clock {period}"
    if minute == 30:
        return f"half past {spoken_hour} {period}"
    if minute == 15:
        return f"quarter past {spoken_hour} {period}"
    if minute == 45:
        next_hour = words.get((display_hour % 12) + 1, str(display_hour + 1))
        return f"quarter to {next_hour} {period}"
    return f"{spoken_hour} {minute:02d} {period}"


def speak_money(amount: float) -> str:
    """42.75 -> 'forty-two pounds seventy-five'... spoken as digits.

    We keep the numerals (TTS engines read '42 pounds 75' correctly) but drop
    the decimal point, because '42.75 pounds' gets read as 'forty two point
    seven five pounds', which sounds wrong on a price.
    """
    pounds = int(amount)
    pence = int(round((amount - pounds) * 100))
    if pence == 0:
        return f"{pounds} pounds"
    return f"{pounds} pounds {pence:02d}"


def speak_miles(miles: float) -> str:
    """Round distance for speech — nobody says '9.43 miles' on the phone."""
    if miles < 1:
        return "under a mile"
    return f"about {round(miles)} miles"
