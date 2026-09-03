"""
config.py — one place that loads .env and holds every setting + business rule.

WHY THIS FILE EXISTS
--------------------
Without it, every service module would call os.getenv() itself and you'd end up
with typo'd key names scattered across the codebase. Here the environment is
read exactly once, at import time, and everything else imports from here.

Every integration also gets an `is_configured()` style flag. That is what lets
the app degrade gracefully: if Twilio isn't set up yet, the SMS step logs a
warning and the booking still succeeds, instead of a 500 error killing a live
customer call.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# ── Paths ─────────────────────────────────────────────────────────────────────
# BASE_DIR is the project root (hey101231/), i.e. one level above api/.
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

LOGS_DIR = BASE_DIR / "logs"
LOGS_DIR.mkdir(exist_ok=True)

CALLS_LOG = LOGS_DIR / "calls.jsonl"          # one JSON object per completed call
TRANSFERS_LOG = LOGS_DIR / "transfers.jsonl"  # every human-transfer event
BOOKINGS_LOG = LOGS_DIR / "bookings.jsonl"    # local mirror of every booking


def _env(name: str, default: str = "") -> str:
    """Read an env var, trimming whitespace and treating placeholders as empty.

    The .env ships with values like `your_twilio_sid`. Treating those as "not
    configured" means the app behaves correctly before you've filled them in.
    """
    raw = (os.getenv(name) or default).strip()
    if raw.lower().startswith("your_") or raw.lower() == "changeme":
        return ""
    return raw


def _env_int(name: str, default: int) -> int:
    try:
        return int(_env(name) or default)
    except ValueError:
        return default


# ── Business rules (from the client's spec — change nothing here casually) ────
MAX_WEIGHT_KG = 790.0        # SWB van hard capacity
SURCHARGE_WEIGHT_KG = 400.0  # loads above this add 10%
SURCHARGE_MULTIPLIER = 1.10
BASE_FARE_GBP = 15.00
RATE_UNDER_10_MI = 2.50
RATE_UNDER_30_MI = 2.00
RATE_OVER_30_MI = 1.75

TIMEZONE = "Europe/London"
BOOKING_DURATION_MINUTES = 60  # how long each job blocks the calendar for

# ── Google Maps ───────────────────────────────────────────────────────────────
GOOGLE_MAPS_API_KEY = _env("GOOGLE_MAPS_API_KEY")

# ── Google Sheets ─────────────────────────────────────────────────────────────
GOOGLE_SHEETS_ID = _env("GOOGLE_SHEETS_ID")
GOOGLE_SHEETS_TAB = _env("GOOGLE_SHEETS_TAB", "Bookings")
GOOGLE_SERVICE_ACCOUNT_JSON = _env(
    "GOOGLE_SERVICE_ACCOUNT_JSON", "./api/service-account.json"
)


def _service_account_is_real() -> bool:
    """True only if the service-account file holds a genuine Google key.

    The repo ships a placeholder service-account.json so you can see the shape
    of the file. Checking only that the file EXISTS would switch Sheets on and
    then fail on every request. So we also confirm the private key looks real
    rather than being the placeholder text.
    """
    import json

    path = BASE_DIR / GOOGLE_SERVICE_ACCOUNT_JSON
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    key = str(data.get("private_key", ""))
    return "BEGIN PRIVATE KEY" in key and "REPLACE" not in key.upper()


SHEETS_ENABLED = bool(GOOGLE_SHEETS_ID) and _service_account_is_real()

# ── Twilio ────────────────────────────────────────────────────────────────────
TWILIO_ACCOUNT_SID = _env("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = _env("TWILIO_AUTH_TOKEN")
TWILIO_FROM_NUMBER = _env("TWILIO_FROM_NUMBER")
TWILIO_ENABLED = bool(TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN and TWILIO_FROM_NUMBER)

# ── Cal.com ───────────────────────────────────────────────────────────────────
CAL_API_KEY = _env("CAL_API_KEY")
CAL_EVENT_TYPE_ID = _env("CAL_EVENT_TYPE_ID")
CAL_API_BASE = "https://api.cal.com/v2"
CAL_API_VERSION = "2024-08-13"  # Cal.com pins its v2 API behind a date header
CALCOM_ENABLED = bool(CAL_API_KEY and CAL_EVENT_TYPE_ID)

# ── Vapi ──────────────────────────────────────────────────────────────────────
VAPI_PRIVATE_KEY = _env("VAPI_PRIVATE_KEY")
VAPI_SERVER_SECRET = _env("VAPI_SERVER_SECRET")  # blank = signature check skipped

# ── Email (SMTP) ──────────────────────────────────────────────────────────────
SMTP_HOST = _env("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = _env_int("SMTP_PORT", 587)
SMTP_USER = _env("SMTP_USER")
SMTP_PASSWORD = _env("SMTP_PASSWORD")
SMTP_FROM_NAME = _env("SMTP_FROM_NAME", "Courier Bookings")
EMAIL_ENABLED = bool(SMTP_HOST and SMTP_USER and SMTP_PASSWORD)

# ── The client (business owner) ───────────────────────────────────────────────
CLIENT_EMAIL = _env("CLIENT_EMAIL")
CLIENT_PHONE_NUMBER = _env("CLIENT_PHONE_NUMBER")
CLIENT_NAME = _env("CLIENT_NAME", "Courier Operations")

# ── Public URL ────────────────────────────────────────────────────────────────
NGROK_URL = _env("NGROK_URL").rstrip("/")


def integration_status() -> dict[str, bool]:
    """Snapshot of which integrations are live. Surfaced on /health so you can
    see at a glance what still needs credentials."""
    return {
        "google_maps": bool(GOOGLE_MAPS_API_KEY),
        "google_sheets": SHEETS_ENABLED,
        "twilio": TWILIO_ENABLED,
        "calcom": CALCOM_ENABLED,
        "email": EMAIL_ENABLED,
        "vapi_secret_check": bool(VAPI_SERVER_SECRET),
    }
