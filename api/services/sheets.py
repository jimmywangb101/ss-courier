"""
sheets.py — reads and writes the booking log in Google Sheets.

WHY NOT google-api-python-client?
---------------------------------
That library is synchronous: every call would block the event loop while we
wait on Google, freezing other live calls. Instead we do this:

  1. Use `google-auth` to turn the service-account JSON into a short-lived
     OAuth access token. That step is blocking, so it runs in a worker thread
     via asyncio.to_thread() — and the token is cached and reused for ~an hour.
  2. Call the Sheets REST API with httpx, fully async.

A LOCAL SAFETY NET
------------------
Every booking is ALSO appended to logs/bookings.jsonl before we try Google.
If Sheets is down, misconfigured, or the client has not shared the sheet yet,
no booking is ever lost — you can replay the file later. This is why the admin
dashboard still shows data before Google is set up.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any

import httpx

from api import config

log = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(20.0)
_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
_API_ROOT = "https://sheets.googleapis.com/v4/spreadsheets"

# Column order of the sheet. Changing this means changing the header row too.
HEADERS = [
    "reference", "created_at", "status", "caller_name", "caller_phone",
    "caller_email", "pickup_address", "dropoff_address", "weight_kg",
    "distance_miles", "quote_gbp", "service_date", "service_time",
    "calcom_uid", "call_id", "notes",
]

# Cached access token: (token_string, unix_expiry)
_token_cache: tuple[str, float] | None = None


# ── Auth ──────────────────────────────────────────────────────────────────────

def _mint_token_blocking() -> tuple[str, float]:
    """Exchange the service-account key for an OAuth access token.

    Blocking on purpose — always call this through asyncio.to_thread().
    """
    from google.auth.transport.requests import Request
    from google.oauth2 import service_account

    key_path = Path(config.GOOGLE_SERVICE_ACCOUNT_JSON)
    if not key_path.is_absolute():
        key_path = config.BASE_DIR / key_path

    credentials = service_account.Credentials.from_service_account_file(
        str(key_path), scopes=_SCOPES
    )
    credentials.refresh(Request())
    # Refresh a minute early so we never send a token that expires mid-flight.
    expiry = credentials.expiry.timestamp() - 60 if credentials.expiry else time.time() + 3000
    return credentials.token, expiry


async def _get_token() -> str | None:
    """Return a valid access token, minting a new one only when needed."""
    global _token_cache

    if _token_cache and _token_cache[1] > time.time():
        return _token_cache[0]

    try:
        token, expiry = await asyncio.to_thread(_mint_token_blocking)
        _token_cache = (token, expiry)
        return token
    except Exception as exc:
        log.error("Google Sheets auth failed: %s", exc)
        return None


# ── Local mirror (always runs, even when Sheets is off) ───────────────────────

def _append_local(record: dict[str, Any]) -> None:
    """Append the booking to logs/bookings.jsonl. Runs in a worker thread."""
    try:
        with open(config.BOOKINGS_LOG, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    except OSError as exc:
        log.error("Could not write local booking log: %s", exc)


def _read_local(limit: int = 50) -> list[dict[str, Any]]:
    """Read the most recent bookings from the local mirror."""
    if not config.BOOKINGS_LOG.exists():
        return []
    try:
        with open(config.BOOKINGS_LOG, "r", encoding="utf-8") as handle:
            lines = handle.readlines()
    except OSError:
        return []

    records = []
    for line in lines[-limit:]:
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    records.reverse()  # newest first
    return records


# ── Write ─────────────────────────────────────────────────────────────────────

async def append_booking(record: dict[str, Any]) -> dict:
    """Append one booking row. Writes locally first, then to Google Sheets."""
    await asyncio.to_thread(_append_local, record)

    if not config.SHEETS_ENABLED:
        log.warning("Google Sheets not configured - booking %s saved locally only",
                    record.get("reference"))
        return {"ok": False, "skipped": True, "error": "sheets_not_configured",
                "local": True}

    token = await _get_token()
    if not token:
        return {"ok": False, "error": "auth_failed", "local": True}

    # Sheets wants a list of rows, each a list of cell values in column order.
    row = [_cell(record.get(column)) for column in HEADERS]
    url = f"{_API_ROOT}/{config.GOOGLE_SHEETS_ID}/values/{config.GOOGLE_SHEETS_TAB}!A:P:append"

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(
                url,
                params={
                    "valueInputOption": "USER_ENTERED",
                    "insertDataOption": "INSERT_ROWS",
                },
                headers={"Authorization": f"Bearer {token}"},
                json={"values": [row]},
            )
        if resp.status_code >= 400:
            detail = _error_detail(resp)
            log.error("Sheets append failed (%s): %s", resp.status_code, detail)
            return {"ok": False, "error": detail, "local": True}

        updates = resp.json().get("updates", {})
        log.info("Booking %s written to Sheets (%s)",
                 record.get("reference"), updates.get("updatedRange"))
        return {"ok": True, "updated_range": updates.get("updatedRange"), "local": True}

    except httpx.HTTPError as exc:
        log.exception("Sheets network error")
        return {"ok": False, "error": f"network_error: {exc}", "local": True}


# ── Read ──────────────────────────────────────────────────────────────────────

async def list_bookings(limit: int = 50) -> tuple[list[dict[str, Any]], str]:
    """Return the most recent bookings, newest first, and where they came from.

    Falls back to the local JSONL mirror whenever Sheets is unavailable, so the
    admin dashboard always shows something useful. The source string is the
    ACTUAL path this call took ("google_sheets" or "local_log") - not simply
    whether Sheets is configured. Those can differ: Sheets can be fully
    configured and still be the wrong answer for one particular call, e.g. the
    sheet momentarily has no data rows in it. A caller that reports
    "google_sheets" just because config.SHEETS_ENABLED is true, while actually
    showing locally-cached data, is telling the person reading the admin
    dashboard something false about where the numbers came from.
    """
    if not config.SHEETS_ENABLED:
        return await asyncio.to_thread(_read_local, limit), "local_log"

    token = await _get_token()
    if not token:
        return await asyncio.to_thread(_read_local, limit), "local_log"

    url = f"{_API_ROOT}/{config.GOOGLE_SHEETS_ID}/values/{config.GOOGLE_SHEETS_TAB}!A:P"
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(url, headers={"Authorization": f"Bearer {token}"})
        if resp.status_code >= 400:
            log.error("Sheets read failed (%s): %s", resp.status_code, _error_detail(resp))
            return await asyncio.to_thread(_read_local, limit), "local_log"

        values = resp.json().get("values", [])
        if len(values) < 2:  # header row only, or empty sheet
            return await asyncio.to_thread(_read_local, limit), "local_log"

        header = [str(cell).strip() for cell in values[0]]
        rows = []
        for raw_row in values[1:]:
            padded = list(raw_row) + [""] * (len(header) - len(raw_row))
            rows.append(dict(zip(header, padded)))

        rows.reverse()  # newest first
        return rows[:limit], "google_sheets"

    except httpx.HTTPError as exc:
        log.error("Sheets read network error: %s", exc)
        return await asyncio.to_thread(_read_local, limit), "local_log"


async def find_booking(reference: str) -> dict[str, Any] | None:
    """Look up one booking by its reference. Returns None if not found."""
    target = (reference or "").strip().upper()
    if not target:
        return None

    # Search a generous window so older references are still findable.
    records, _source = await list_bookings(limit=500)
    for record in records:
        if str(record.get("reference", "")).strip().upper() == target:
            return record
    return None


# ── Sheet setup helper ────────────────────────────────────────────────────────

async def ensure_header_row() -> dict:
    """Write the header row if the sheet is empty. Safe to call repeatedly.

    Called once at startup so you do not have to type the column names by hand.
    """
    if not config.SHEETS_ENABLED:
        return {"ok": False, "skipped": True}

    token = await _get_token()
    if not token:
        return {"ok": False, "error": "auth_failed"}

    url = f"{_API_ROOT}/{config.GOOGLE_SHEETS_ID}/values/{config.GOOGLE_SHEETS_TAB}!A1:P1"
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            existing = await client.get(url, headers={"Authorization": f"Bearer {token}"})
            if existing.status_code < 400 and existing.json().get("values"):
                return {"ok": True, "already_present": True}

            resp = await client.put(
                url,
                params={"valueInputOption": "RAW"},
                headers={"Authorization": f"Bearer {token}"},
                json={"values": [HEADERS]},
            )
        if resp.status_code >= 400:
            return {"ok": False, "error": _error_detail(resp)}
        log.info("Sheets header row created")
        return {"ok": True, "created": True}
    except httpx.HTTPError as exc:
        return {"ok": False, "error": f"network_error: {exc}"}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _cell(value: Any) -> str:
    """Sheets cells must be scalars - flatten anything else to text."""
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, default=str)
    return str(value)


def _error_detail(resp: httpx.Response) -> str:
    try:
        body = resp.json()
        return str(body.get("error", {}).get("message", body))[:300]
    except Exception:
        return resp.text[:300]
