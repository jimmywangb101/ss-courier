"""
calcom.py — thin async wrapper around the Cal.com v2 API.

WHAT WE USE IT FOR
------------------
  * create_booking()      - puts the job on the client's calendar
  * check_availability()  - tells the agent whether a slot is free BEFORE it
                            promises it to the caller
  * cancel_booking()      - tidy-up path if a booking has to be undone

API NOTES (these bite people)
-----------------------------
  * Cal.com v2 pins behaviour behind a date header, `cal-api-version`. Without
    it you get confusing validation errors. Bookings use 2024-08-13; the slots
    endpoint uses a later version, 2024-09-04.
  * All times must be sent as UTC ISO-8601. utils.to_utc_iso() handles the
    London -> UTC conversion including British Summer Time.
  * The API key goes in as `Authorization: Bearer <key>`.

Nothing here raises. Every function returns a dict with an "ok" flag so a
Cal.com outage degrades the booking to "recorded but not on the calendar"
rather than dropping the customer's call.
"""

from __future__ import annotations

import logging

import httpx

from api import config, utils

log = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(15.0)
_SLOTS_API_VERSION = "2024-09-04"


def _headers(api_version: str = config.CAL_API_VERSION) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {config.CAL_API_KEY}",
        "cal-api-version": api_version,
        "Content-Type": "application/json",
    }


# ── Create a booking ──────────────────────────────────────────────────────────

async def create_booking(*, caller_name: str, caller_email: str, caller_phone: str,
                         date_str: str, time_str: str, pickup: str, dropoff: str,
                         weight_kg: float, quote_gbp: float, reference: str,
                         distance_miles: float | None = None) -> dict:
    """Create a calendar booking. Returns {"ok": bool, ...}, never raises."""
    if not config.CALCOM_ENABLED:
        log.warning("Cal.com not configured - booking %s not added to calendar", reference)
        return {"ok": False, "skipped": True, "error": "calcom_not_configured"}

    start_utc = utils.to_utc_iso(date_str, time_str)

    payload = {
        "start": start_utc,
        "eventTypeId": _event_type_id(),
        "attendee": {
            "name": caller_name or "Telephone booking",
            # Cal.com requires an email. If the caller would not give one we
            # send a placeholder so the calendar entry still gets created.
            "email": caller_email or "no-reply@example.com",
            "timeZone": config.TIMEZONE,
            "language": "en",
            "phoneNumber": caller_phone or None,
        },
        # metadata is free-form and shows on the calendar entry - this is what
        # the driver actually reads before setting off.
        "metadata": {
            "reference": reference,
            "pickup": pickup[:490],
            "dropoff": dropoff[:490],
            "weight_kg": str(weight_kg),
            "quote_gbp": f"{quote_gbp:.2f}",
            "distance_miles": str(distance_miles or ""),
            "source": "ai_voice_agent",
        },
    }

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(
                f"{config.CAL_API_BASE}/bookings", json=payload, headers=_headers()
            )
        if resp.status_code >= 400:
            detail = _error_detail(resp)
            log.error("Cal.com create_booking failed (%s): %s", resp.status_code, detail)
            return {"ok": False, "error": detail, "status_code": resp.status_code}

        data = resp.json().get("data", {})
        booking_uid = data.get("uid") or data.get("id")
        log.info("Cal.com booking created: uid=%s ref=%s", booking_uid, reference)
        return {"ok": True, "booking_uid": booking_uid, "start_utc": start_utc, "raw": data}

    except httpx.HTTPError as exc:
        log.exception("Cal.com network error")
        return {"ok": False, "error": f"network_error: {exc}"}


# ── Availability ──────────────────────────────────────────────────────────────

async def check_availability(date_str: str, time_str: str) -> dict:
    """Is the requested slot free?

    Returns {"available": bool, "next_available": "HH:MM" | None, ...}.

    IMPORTANT DESIGN CHOICE: if Cal.com is unreachable or unconfigured we
    return available=True. Telling a real customer "we are fully booked"
    because of our own outage loses the client money; double-booking is
    recoverable by a human. We flag it with "assumed": True so the caller of
    this function knows the answer was not verified.
    """
    if not config.CALCOM_ENABLED:
        return {"available": True, "assumed": True, "next_available": None,
                "error": "calcom_not_configured"}

    day = utils.normalise_date(date_str)
    wanted = utils.normalise_time(time_str)

    params = {
        "eventTypeId": _event_type_id(),
        "start": day,
        "end": day,
        "timeZone": config.TIMEZONE,
    }

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(
                f"{config.CAL_API_BASE}/slots",
                params=params,
                headers=_headers(_SLOTS_API_VERSION),
            )
        if resp.status_code >= 400:
            detail = _error_detail(resp)
            log.error("Cal.com slots failed (%s): %s", resp.status_code, detail)
            return {"available": True, "assumed": True, "next_available": None,
                    "error": detail}

        free_times = _extract_slot_times(resp.json(), day)

        # No slot data at all usually means the event type has no availability
        # rules set up yet. Do not block the booking on that.
        if not free_times:
            return {"available": True, "assumed": True, "next_available": None,
                    "error": "no_slot_data"}

        if wanted in free_times:
            return {"available": True, "assumed": False, "next_available": wanted,
                    "free_slots": free_times[:12]}

        later = [t for t in free_times if t > wanted]
        return {
            "available": False,
            "assumed": False,
            "next_available": (later or free_times)[0],
            "free_slots": free_times[:12],
        }

    except httpx.HTTPError as exc:
        log.exception("Cal.com availability network error")
        return {"available": True, "assumed": True, "next_available": None,
                "error": f"network_error: {exc}"}


def _extract_slot_times(body: dict, day: str) -> list[str]:
    """Pull local HH:MM strings out of the slots response.

    Cal.com has shipped a couple of shapes for this over the versions:
        {"data": {"2026-09-15": [{"start": "2026-09-15T09:00:00Z"}, ...]}}
        {"data": {"slots": {"2026-09-15": [...]}}}
    We handle both rather than pinning to one and breaking on an upgrade.
    """
    data = body.get("data", body) or {}
    if isinstance(data, dict) and "slots" in data:
        data = data["slots"]

    raw_slots = []
    if isinstance(data, dict):
        raw_slots = data.get(day) or next((v for v in data.values() if isinstance(v, list)), [])
    elif isinstance(data, list):
        raw_slots = data

    times: list[str] = []
    for slot in raw_slots:
        start = slot.get("start") if isinstance(slot, dict) else slot
        if not isinstance(start, str):
            continue
        local = _utc_iso_to_local_hhmm(start)
        if local:
            times.append(local)
    return sorted(set(times))


def _utc_iso_to_local_hhmm(iso_string: str) -> str | None:
    """'2026-09-15T09:00:00Z' -> '10:00' (London, BST-aware)."""
    from datetime import datetime, timezone

    try:
        cleaned = iso_string.replace("Z", "+00:00")
        moment = datetime.fromisoformat(cleaned)
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        return moment.astimezone(utils.LONDON).strftime("%H:%M")
    except ValueError:
        return None


# ── Cancel ────────────────────────────────────────────────────────────────────

async def cancel_booking(booking_uid: str, reason: str = "Cancelled by operator") -> dict:
    """Cancel a Cal.com booking by its uid."""
    if not config.CALCOM_ENABLED or not booking_uid:
        return {"ok": False, "skipped": True, "error": "calcom_not_configured_or_no_uid"}

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(
                f"{config.CAL_API_BASE}/bookings/{booking_uid}/cancel",
                json={"cancellationReason": reason},
                headers=_headers(),
            )
        if resp.status_code >= 400:
            return {"ok": False, "error": _error_detail(resp)}
        return {"ok": True, "booking_uid": booking_uid}
    except httpx.HTTPError as exc:
        return {"ok": False, "error": f"network_error: {exc}"}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _event_type_id() -> int | str:
    """Cal.com wants eventTypeId as a number. The .env stores it as text."""
    try:
        return int(config.CAL_EVENT_TYPE_ID)
    except (TypeError, ValueError):
        return config.CAL_EVENT_TYPE_ID


def _error_detail(resp: httpx.Response) -> str:
    """Cal.com errors arrive as {"error": {"message": "..."}} or plain text."""
    try:
        body = resp.json()
        error = body.get("error")
        if isinstance(error, dict):
            return str(error.get("message") or error)
        return str(error or body.get("message") or body)[:300]
    except Exception:
        return resp.text[:300]
