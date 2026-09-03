"""
main.py — the FastAPI application behind the AI voice courier agent.

WHAT LIVES HERE
---------------
  Phase 1  /health, /quote                      pricing engine (unchanged)
  Phase 2  /vapi/*                              webhooks Vapi calls during a call
  Phase 3  /booking/*                           what n8n calls to complete a booking
  Phase 4  /admin, /admin/bookings              simple operations dashboard

THE GOLDEN RULE OF THIS FILE
----------------------------
A customer is on the phone. Nothing in here may raise an unhandled exception,
because a 500 response makes the AI agent go silent mid-sentence. Every external
call goes through a service module that returns {"ok": false, ...} instead of
throwing, and every Vapi endpoint has a fallback sentence to say.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from api import config, utils
from api.services import booking_ref, calcom, email_sender, sheets, twilio_sms

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)

# SECURITY: httpx logs every request line at INFO, including the full URL.
# The Google Maps API key travels as a ?key= query parameter, so leaving this on
# writes the key into the log on every single quote. On a hosted server those
# logs are retained and readable by anyone with dashboard access, which is an
# effective key leak. Quietening httpx to WARNING keeps real errors visible
# while keeping credentials out of the log.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

log = logging.getLogger("courier")


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Runs once on startup (before the yield) and once on shutdown (after).

    This is the modern replacement for @app.on_event("startup"). We use it to
    print which integrations have credentials, so the first thing you see in the
    terminal tells you what still needs configuring.
    """
    status = config.integration_status()
    log.info("Courier agent starting - integrations: %s", status)

    missing = [name for name, ready in status.items() if not ready]
    if missing:
        log.warning("Not yet configured: %s (see docs/setup-guide.md)", ", ".join(missing))

    if config.SHEETS_ENABLED:
        await sheets.ensure_header_row()

    yield  # ---- the application runs here ----

    log.info("Courier agent shutting down")


app = FastAPI(
    title="Courier AI Voice Agent",
    version="2.0",
    description="Quote engine, Vapi webhooks and booking orchestration.",
    lifespan=lifespan,
)

MAX_WEIGHT_KG = config.MAX_WEIGHT_KG  # kept as a module constant for Phase 1 tests


# ══════════════════════════════════════════════════════════════════════════════
#  PHASE 1 — Pricing engine (unchanged behaviour, constants moved to config)
# ══════════════════════════════════════════════════════════════════════════════

class QuoteRequest(BaseModel):
    pickup_address: str
    dropoff_address: str
    weight_kg: float
    date: str = ""   # ISO format: 2026-09-15
    time: str = ""   # 24h format: 14:30


class QuoteResponse(BaseModel):
    action: str                             # "quote" | "redirect" | "error"
    distance_miles: float | None = None
    quote_gbp: float | None = None
    message: str | None = None              # spoken by Vapi back to the caller


def calculate_price(distance_miles: float, weight_kg: float) -> float:
    """Tiered mileage pricing plus the heavy-load surcharge.

    base GBP 15 + per-mile rate, where the rate steps DOWN as the job gets
    longer (long runs are more efficient per mile):
        <= 10 miles  GBP 2.50/mile
        <= 30 miles  GBP 2.00/mile
        >  30 miles  GBP 1.75/mile
    Loads over 400 kg add 10% for the extra handling.
    """
    if distance_miles <= 10:
        per_mile = config.RATE_UNDER_10_MI
    elif distance_miles <= 30:
        per_mile = config.RATE_UNDER_30_MI
    else:
        per_mile = config.RATE_OVER_30_MI

    price = config.BASE_FARE_GBP + (distance_miles * per_mile)

    if weight_kg > config.SURCHARGE_WEIGHT_KG:
        price *= config.SURCHARGE_MULTIPLIER

    return round(price, 2)


# Google Maps statuses that mean OUR account is misconfigured, as opposed to
# the caller giving us a duff address. Worth separating: one needs you to fix
# billing, the other needs the caller to repeat their postcode.
_MAPS_ACCOUNT_ERRORS = {
    "REQUEST_DENIED",        # key rejected - usually billing is not enabled
    "OVER_QUERY_LIMIT",      # quota exhausted
    "OVER_DAILY_LIMIT",      # billing/quota problem
    "INVALID_REQUEST",       # we sent something malformed
}


async def get_distance_miles(origin: str, destination: str) -> float:
    """Road distance in miles via the Google Maps Distance Matrix API.

    Raises HTTPException(422) when the distance cannot be worked out. The
    detail string starts with "account:" when the fault is ours (billing, quota,
    bad key) rather than the caller's, so the logs tell you which one to fix.
    """
    url = "https://maps.googleapis.com/maps/api/distancematrix/json"
    params = {
        "origins": origin,
        "destinations": destination,
        "units": "imperial",
        "key": config.GOOGLE_MAPS_API_KEY,
    }
    async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as client:
        response = await client.get(url, params=params)
        response.raise_for_status()
        data = response.json()

    # Google returns HTTP 200 even when it refuses the request, so the real
    # outcome is in the body's "status" field, not the status code.
    top_status = data.get("status", "UNKNOWN")
    if top_status != "OK":
        note = data.get("error_message", "")
        if top_status in _MAPS_ACCOUNT_ERRORS:
            log.error("GOOGLE MAPS ACCOUNT PROBLEM - %s: %s. "
                      "Fix this in Google Cloud; addresses are not the issue.",
                      top_status, note)
            raise HTTPException(status_code=422,
                                detail=f"account: Maps API {top_status} - {note}")
        raise HTTPException(status_code=422, detail=f"Maps API {top_status} - {note}")

    try:
        element = data["rows"][0]["elements"][0]
    except (KeyError, IndexError) as exc:
        raise HTTPException(status_code=422, detail=f"Unexpected Maps response: {exc}")

    if element.get("status") != "OK":
        # ZERO_RESULTS / NOT_FOUND = one of the addresses could not be matched.
        raise HTTPException(status_code=422,
                            detail=f"Route not found ({element.get('status')})")

    metres = element["distance"]["value"]
    return round(metres / 1609.34, 2)


@app.get("/health")
def health() -> dict:
    """Liveness check. Also reports which integrations have credentials, which
    is the fastest way to see what still needs configuring."""
    return {
        "status": "ok",
        "service": "courier-ai-voice-agent",
        "version": app.version,
        "integrations": config.integration_status(),
    }


@app.post("/quote", response_model=QuoteResponse)
async def get_quote(req: QuoteRequest) -> QuoteResponse:
    """Price a job. Used directly by n8n and internally by /vapi/quote."""
    if req.weight_kg <= 0:
        return QuoteResponse(
            action="error",
            message=("I'm sorry, I didn't quite catch the weight. "
                     "Could you confirm the load weight in kilograms?"),
        )

    # Over capacity -> hand to a human, never a flat rejection.
    if req.weight_kg > MAX_WEIGHT_KG:
        return QuoteResponse(
            action="redirect",
            message=(
                f"Your load of {req.weight_kg:.0f} kilograms is larger than our "
                "standard vehicle capacity. Not to worry — let me transfer you to "
                "a specialist who can arrange the right vehicle for you."
            ),
        )

    distance = await get_distance_miles(req.pickup_address, req.dropoff_address)
    price = calculate_price(distance, req.weight_kg)

    return QuoteResponse(
        action="quote",
        distance_miles=distance,
        quote_gbp=price,
        message=(
            f"Great news — I can arrange that collection for you. "
            f"The distance is approximately {distance} miles and your quote is "
            f"£{price:.2f}. Shall I go ahead and book that in?"
        ),
    )


# ══════════════════════════════════════════════════════════════════════════════
#  PHASE 2 — Vapi webhooks
# ══════════════════════════════════════════════════════════════════════════════
#
#  HOW VAPI TALKS TO US
#  --------------------
#  Every event arrives as POST {"message": {"type": "...", ...}}. The types we
#  care about:
#     tool-calls / function-call   the AI wants to run one of our functions
#     end-of-call-report           the call finished; transcript + summary
#     status-update                call state changed (ringing, in-progress...)
#     transfer-destination-request Vapi asks WHERE to transfer the call
#
#  Vapi has changed its tool-call shape over time, so _extract_tool_call below
#  understands both the old ("functionCall") and new ("toolCalls") formats, and
#  our replies include both response shapes. That way a Vapi upgrade will not
#  silently break the agent.

def _write_jsonl(path, record: dict[str, Any]) -> None:
    """Append one JSON object to a .jsonl file. Blocking - use to_thread."""
    try:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    except OSError as exc:
        log.error("Could not write log %s: %s", path, exc)


async def log_event(path, record: dict[str, Any]) -> None:
    """Append to a log file without blocking the event loop."""
    record.setdefault("logged_at", utils.london_now().isoformat())
    await asyncio.to_thread(_write_jsonl, path, record)


def _verify_vapi_secret(request: Request) -> bool:
    """Check the shared secret Vapi sends as the x-vapi-secret header.

    If VAPI_SERVER_SECRET is blank we skip the check, which keeps local
    development easy. Set it before going live — otherwise anyone who finds
    your ngrok URL can post fake bookings.
    """
    if not config.VAPI_SERVER_SECRET:
        return True
    return request.headers.get("x-vapi-secret") == config.VAPI_SERVER_SECRET


def _extract_tool_call(body: dict) -> tuple[str | None, str | None, dict]:
    """Pull (tool_call_id, function_name, arguments) out of a Vapi payload.

    Handles three shapes:
      new     message.toolCalls[0].function.{name, arguments}
      legacy  message.functionCall.{name, parameters}
      plain   the raw body itself (what our own test scripts send)
    """
    message = body.get("message", body) or {}

    tool_calls = message.get("toolCalls") or message.get("toolCallList") or []
    if tool_calls:
        first = tool_calls[0] or {}
        function = first.get("function", {}) or {}
        arguments = function.get("arguments", {})
        # Vapi sometimes sends arguments as a JSON *string* rather than an object.
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError:
                arguments = {}
        return first.get("id"), function.get("name"), arguments or {}

    function_call = message.get("functionCall") or {}
    if function_call:
        parameters = function_call.get("parameters", {})
        if isinstance(parameters, str):
            try:
                parameters = json.loads(parameters)
            except json.JSONDecodeError:
                parameters = {}
        return None, function_call.get("name"), parameters or {}

    # Not a Vapi envelope at all - treat the body as the arguments directly.
    return None, None, body if isinstance(body, dict) else {}


def _first_of(data: dict, *names: str, default: Any = "") -> Any:
    """Return the first present, non-empty key from `names`.

    The AI does not always use the exact parameter names we defined, and Vapi
    tool schemas drift, so we accept sensible aliases for every field.
    """
    for name in names:
        value = data.get(name)
        if value not in (None, "", []):
            return value
    return default


def _call_id(body: dict) -> str:
    message = body.get("message", body) or {}
    call = message.get("call") or body.get("call") or {}
    return call.get("id") or body.get("call_id") or ""


def _call_sid(body: dict) -> str:
    """The underlying Twilio CallSid, needed to redirect a live call."""
    message = body.get("message", body) or {}
    call = message.get("call") or body.get("call") or {}
    for candidate in (
        call.get("phoneCallProviderId"),
        (call.get("phoneCallProviderDetails") or {}).get("sid"),
        body.get("call_sid"),
    ):
        if candidate:
            return str(candidate)
    return ""


def _caller_number(body: dict) -> str:
    """The customer's phone number, as reported by the telephony provider."""
    message = body.get("message", body) or {}
    call = message.get("call") or body.get("call") or {}
    customer = call.get("customer") or message.get("customer") or {}
    return customer.get("number") or body.get("caller_phone") or ""


def vapi_reply(text: str, tool_call_id: str | None = None, **extra: Any) -> dict:
    """Build a response Vapi will speak.

    We return BOTH response shapes ("result" for the legacy function-call format
    and "results" for the newer tool-calls format). Vapi reads whichever one it
    expects and ignores the other, so this works across versions.
    """
    payload: dict[str, Any] = {"result": text}
    if tool_call_id:
        payload["results"] = [{"toolCallId": tool_call_id, "result": text}]
    payload.update(extra)
    return payload


# ── /vapi/quote ───────────────────────────────────────────────────────────────

@app.post("/vapi/quote")
async def vapi_quote(request: Request) -> dict:
    """Called by the AI once it has collected all five booking details.

    Returns a natural British sentence for the agent to read aloud — never raw
    JSON, because whatever we return here goes straight into the caller's ear.
    """
    body = await _safe_json(request)
    tool_call_id, _, params = _extract_tool_call(body)

    pickup = str(_first_of(params, "pickup_address", "pickup", "collection_address", "from"))
    dropoff = str(_first_of(params, "dropoff_address", "dropoff", "delivery_address", "to"))
    raw_weight = _first_of(params, "weight_kg", "weight", "load_weight", default=0)
    date_str = utils.normalise_date(str(_first_of(params, "date", "collection_date", "pickup_date")))
    time_str = utils.normalise_time(str(_first_of(params, "time", "collection_time", "pickup_time")))

    weight = _to_float(raw_weight)

    # ── Validate what the AI gave us ──────────────────────────────────────────
    if not pickup or not dropoff:
        return vapi_reply(
            "Sorry, I just need to check — could you give me the full collection "
            "address and the delivery address again?",
            tool_call_id, action="need_addresses",
        )

    if weight <= 0:
        return vapi_reply(
            "I didn't quite catch the weight there. Roughly how many kilograms "
            "is the load?",
            tool_call_id, action="need_weight",
        )

    # ── Hard capacity rule: over 790 kg goes to a human ───────────────────────
    if weight > MAX_WEIGHT_KG:
        speech = (
            f"Right, {weight:.0f} kilograms is above the {MAX_WEIGHT_KG:.0f} kilogram "
            "limit for our short wheelbase van, so I can't price that one myself. "
            "Not to worry though — let me put you through to one of the team who "
            "can sort a larger vehicle for you. Bear with me one moment."
        )
        await log_event(config.TRANSFERS_LOG, {
            "reason": "over_capacity",
            "weight_kg": weight,
            "call_id": _call_id(body),
            "pickup": pickup,
            "dropoff": dropoff,
        })
        return vapi_reply(speech, tool_call_id, action="transfer",
                          transfer_reason="over_capacity", weight_kg=weight)

    # ── Price it ──────────────────────────────────────────────────────────────
    try:
        distance = await get_distance_miles(pickup, dropoff)
    except (HTTPException, httpx.HTTPError) as exc:
        # A bad postcode or a Maps outage must not kill the call.
        detail = str(getattr(exc, "detail", exc))
        log.error("Distance lookup failed: %s", detail)

        # If the fault is our Google account, asking the caller to repeat their
        # postcode is useless — they would just hit the same wall. Hand them to
        # a human instead, and shout about it in the logs.
        if detail.startswith("account:"):
            await log_event(config.TRANSFERS_LOG, {
                "reason": "maps_account_error",
                "call_id": _call_id(body),
                "detail": detail,
            })
            return vapi_reply(
                "I'm terribly sorry, our pricing system isn't responding at the "
                "moment. Let me put you straight through to a colleague who can "
                "quote that for you.",
                tool_call_id, action="transfer", transfer_reason="system_error",
            )

        return vapi_reply(
            "I'm having a bit of trouble finding one of those addresses. Could "
            "you give me the postcode for the collection and the delivery?",
            tool_call_id, action="need_valid_addresses",
        )

    price = calculate_price(distance, weight)
    surcharge = weight > config.SURCHARGE_WEIGHT_KG

    speech = (
        f"Lovely, I can get that collected for you. It's {utils.speak_miles(distance)} "
        f"from the pickup to the drop-off, and the price for that job would be "
        f"{utils.speak_money(price)}"
        + (", which includes a small surcharge for the heavier load. " if surcharge else ". ")
        + f"That's for {utils.speak_date(date_str)} at {utils.speak_time(time_str)}. "
        "Would you like me to book that in for you?"
    )

    return vapi_reply(
        speech, tool_call_id,
        action="quote",
        quote_gbp=price,
        distance_miles=distance,
        weight_kg=weight,
        date=date_str,
        time=time_str,
        pickup_address=pickup,
        dropoff_address=dropoff,
    )


# ── /vapi/transfer ────────────────────────────────────────────────────────────

@app.post("/vapi/transfer")
async def vapi_transfer(request: Request) -> dict:
    """Hand the call to a human.

    Triggered when the caller asks for a person, or the load is over capacity.

    TWO TRANSFER PATHS (we support both):
      1. If we know the Twilio CallSid and Twilio is configured, we redirect the
         live call ourselves via the Twilio REST API. (Phase 4)
      2. Otherwise we return a `destination` block, which is what Vapi's own
         transfer tool expects, and let Vapi do the transfer.
    Either way the event is logged to logs/transfers.jsonl.
    """
    body = await _safe_json(request)
    tool_call_id, _, params = _extract_tool_call(body)

    reason = str(_first_of(params, "reason", "transfer_reason", default="human_requested"))
    if reason not in ("human_requested", "over_capacity"):
        reason = "over_capacity" if "capacity" in reason.lower() else "human_requested"

    call_sid = _call_sid(body)
    record = {
        "reason": reason,
        "call_id": _call_id(body),
        "call_sid": call_sid,
        "caller_phone": _caller_number(body),
        "notes": str(_first_of(params, "notes", "summary", default="")),
        "destination": config.CLIENT_PHONE_NUMBER,
    }

    # Path 1 — redirect the live Twilio call ourselves.
    transfer_result: dict[str, Any] = {"ok": False, "skipped": True}
    if call_sid and config.TWILIO_ENABLED and config.CLIENT_PHONE_NUMBER:
        transfer_result = await twilio_sms.transfer_call(
            call_sid,
            config.CLIENT_PHONE_NUMBER,
            whisper="Connecting you to a member of our team now. Please hold.",
        )
    record["twilio_transfer"] = transfer_result
    await log_event(config.TRANSFERS_LOG, record)

    speech = (
        "Of course — let me put you through to one of the team now. "
        "Please hold the line, it'll just be a moment."
    )

    # Path 2 — tell Vapi where to send the call, if it is doing the transfer.
    extra: dict[str, Any] = {"action": "transfer", "transfer_reason": reason}
    if config.CLIENT_PHONE_NUMBER:
        extra["destination"] = {
            "type": "number",
            "number": config.CLIENT_PHONE_NUMBER,
            "message": speech,
        }

    return vapi_reply(speech, tool_call_id, **extra)


# ── /vapi/end-of-call ─────────────────────────────────────────────────────────

@app.post("/vapi/end-of-call")
async def vapi_end_of_call(request: Request) -> dict:
    """Record the finished call and extract any booking data it captured.

    Vapi posts the full transcript, the summary and (if you configured a
    structured-data schema on the assistant) a parsed object of the fields the
    AI collected. We write all of it to logs/calls.jsonl, then hand the tidy
    booking payload back — that is what n8n forwards to /booking/create.
    """
    body = await _safe_json(request)
    message = body.get("message", body) or {}
    call = message.get("call") or {}

    summary = message.get("summary") or ""
    transcript = message.get("transcript") or ""
    analysis = message.get("analysis") or {}
    structured = analysis.get("structuredData") or message.get("structuredData") or {}

    booking = _booking_from_structured(structured, body)
    accepted = _looks_accepted(structured, summary, transcript)

    record = {
        "call_id": call.get("id") or _call_id(body),
        "ended_reason": message.get("endedReason") or "",
        "started_at": message.get("startedAt") or call.get("startedAt") or "",
        "ended_at": message.get("endedAt") or call.get("endedAt") or "",
        "duration_seconds": _duration_seconds(message, call),
        "caller_phone": _caller_number(body),
        "cost_usd": message.get("cost"),
        "summary": summary,
        "transcript": transcript,
        "structured_data": structured,
        "booking_accepted": accepted,
        "booking_data": booking,
        "recording_url": message.get("recordingUrl") or message.get("stereoRecordingUrl") or "",
    }
    await log_event(config.CALLS_LOG, record)
    log.info("Call %s ended (%s) - accepted=%s",
             record["call_id"], record["ended_reason"], accepted)

    # n8n reads call_status to decide whether to create the booking.
    return {
        "ok": True,
        "call_id": record["call_id"],
        "call_status": "booking_accepted" if accepted else "no_booking",
        "duration_seconds": record["duration_seconds"],
        "booking_data": booking,
    }


def _booking_from_structured(structured: dict, body: dict) -> dict:
    """Normalise whatever the AI collected into our booking field names."""
    data = structured if isinstance(structured, dict) else {}
    return {
        "caller_name": str(_first_of(data, "caller_name", "name", "customer_name")),
        "caller_phone": str(_first_of(data, "caller_phone", "phone", "phone_number")
                            or _caller_number(body)),
        "caller_email": str(_first_of(data, "caller_email", "email")),
        "pickup_address": str(_first_of(data, "pickup_address", "pickup", "from")),
        "dropoff_address": str(_first_of(data, "dropoff_address", "dropoff", "to")),
        "weight_kg": _to_float(_first_of(data, "weight_kg", "weight", default=0)),
        "date": utils.normalise_date(str(_first_of(data, "date", "collection_date"))),
        "time": utils.normalise_time(str(_first_of(data, "time", "collection_time"))),
        "quote_gbp": _to_float(_first_of(data, "quote_gbp", "quote", "price", default=0)),
        "distance_miles": _to_float(_first_of(data, "distance_miles", "distance", default=0)),
    }


def _looks_accepted(structured: dict, summary: str, transcript: str) -> bool:
    """Did the caller actually accept the quote?

    We trust an explicit structured field first. Falling back to reading the
    transcript is deliberately conservative: we would rather miss a booking (a
    human sees it in the log) than invent one the caller never agreed to.
    """
    if isinstance(structured, dict):
        for key in ("booking_accepted", "accepted", "booking_confirmed", "confirmed"):
            value = structured.get(key)
            if isinstance(value, bool):
                return value
            if isinstance(value, str) and value.strip().lower() in ("true", "yes", "y"):
                return True

        status = str(structured.get("call_status") or structured.get("outcome") or "").lower()
        if "accept" in status or "booked" in status or "confirm" in status:
            return True

    haystack = f"{summary} {transcript}".lower()
    positive = ("booking confirmed", "booked in", "that's booked", "quote accepted",
                "customer accepted", "happy to book")
    return any(phrase in haystack for phrase in positive)


def _duration_seconds(message: dict, call: dict) -> float:
    """Prefer the duration Vapi reports; otherwise compute it from timestamps."""
    for key in ("durationSeconds", "duration"):
        value = message.get(key)
        if isinstance(value, (int, float)) and value > 0:
            return round(float(value), 1)

    started = message.get("startedAt") or call.get("startedAt")
    ended = message.get("endedAt") or call.get("endedAt")
    if started and ended:
        try:
            begin = datetime.fromisoformat(str(started).replace("Z", "+00:00"))
            finish = datetime.fromisoformat(str(ended).replace("Z", "+00:00"))
            return round((finish - begin).total_seconds(), 1)
        except ValueError:
            pass
    return 0.0


# ── /vapi/webhook — the master router ─────────────────────────────────────────

@app.post("/vapi/webhook")
async def vapi_webhook(request: Request) -> Any:
    """Single URL you can paste into the Vapi dashboard.

    Vapi sends every event type here; we look at message.type and route it to
    the same handlers as the dedicated endpoints above. Configuring one server
    URL is simpler than four, and the specific endpoints stay available for
    testing and for tools that point at them directly.
    """
    if not _verify_vapi_secret(request):
        log.warning("Rejected Vapi webhook: bad or missing x-vapi-secret header")
        return JSONResponse({"error": "unauthorised"}, status_code=401)

    body = await _safe_json(request)
    message = body.get("message", body) or {}
    message_type = str(message.get("type") or "").lower()

    log.info("Vapi webhook: type=%s call=%s", message_type or "unknown", _call_id(body))

    # 1. The AI is invoking one of our functions.
    if message_type in ("tool-calls", "function-call", "tool_calls", "function_call"):
        _, function_name, _ = _extract_tool_call(body)
        name = (function_name or "").lower()

        if "transfer" in name or "human" in name or "agent" in name:
            return await vapi_transfer(_replay(request, body))
        if "availab" in name or "slot" in name:
            return await _vapi_availability(body)
        # Default: anything else is a quote request.
        return await vapi_quote(_replay(request, body))

    # 2. The call finished.
    if message_type in ("end-of-call-report", "end_of_call_report"):
        return await vapi_end_of_call(_replay(request, body))

    # 3. Vapi is asking where to transfer the call to.
    if message_type in ("transfer-destination-request", "transfer_destination_request"):
        await log_event(config.TRANSFERS_LOG, {
            "reason": "vapi_destination_request",
            "call_id": _call_id(body),
            "destination": config.CLIENT_PHONE_NUMBER,
        })
        return {
            "destination": {
                "type": "number",
                "number": config.CLIENT_PHONE_NUMBER,
                "message": "Connecting you to the team now, please hold.",
            }
        }

    # 4. Status pings and everything else — acknowledge so Vapi does not retry.
    if message_type in ("status-update", "status_update"):
        log.info("Call %s status: %s", _call_id(body), message.get("status"))

    return {"ok": True, "received": message_type or "unknown"}


async def _vapi_availability(body: dict) -> dict:
    """Answer 'is that slot free?' during a call, in spoken English."""
    tool_call_id, _, params = _extract_tool_call(body)
    date_str = utils.normalise_date(str(_first_of(params, "date", "collection_date")))
    time_str = utils.normalise_time(str(_first_of(params, "time", "collection_time")))

    result = await calcom.check_availability(date_str, time_str)

    if result.get("available"):
        speech = (f"Yes, we have availability on {utils.speak_date(date_str)} "
                  f"at {utils.speak_time(time_str)}.")
    else:
        alternative = result.get("next_available")
        speech = (
            f"I'm afraid {utils.speak_time(time_str)} is already taken on "
            f"{utils.speak_date(date_str)}. "
            + (f"The next free slot is {utils.speak_time(alternative)}. Would that suit?"
               if alternative else "Could you suggest another time?")
        )

    return vapi_reply(speech, tool_call_id, action="availability", **{
        "available": result.get("available"),
        "next_available": result.get("next_available"),
    })


class _ReplayRequest:
    """Lets one handler call another with an already-parsed body.

    FastAPI's Request body can only be read once. When /vapi/webhook has already
    consumed it, we wrap the parsed dict in this tiny stand-in so the specific
    handler can read it again without a second await.
    """

    def __init__(self, request: Request, body: dict):
        self.headers = request.headers
        self._body = body

    async def json(self) -> dict:
        return self._body


def _replay(request: Request, body: dict) -> Any:
    return _ReplayRequest(request, body)


# ══════════════════════════════════════════════════════════════════════════════
#  PHASE 3 — Booking endpoints (called by n8n)
# ══════════════════════════════════════════════════════════════════════════════

class BookingRequest(BaseModel):
    caller_name: str = ""
    caller_phone: str = ""
    caller_email: str = ""
    pickup_address: str
    dropoff_address: str
    weight_kg: float = Field(gt=0, description="Load weight in kilograms")
    date: str
    time: str
    quote_gbp: float = Field(ge=0)
    distance_miles: float | None = None
    call_id: str = ""
    notes: str = ""


class BookingResponse(BaseModel):
    ok: bool
    reference: str
    message: str
    steps: dict[str, Any] = {}


class AvailabilityRequest(BaseModel):
    date: str
    time: str


@app.post("/booking/create", response_model=BookingResponse, status_code=201)
async def create_booking(req: BookingRequest) -> BookingResponse:
    """Complete a booking: calendar, spreadsheet, SMS and both emails.

    ORDER MATTERS. Cal.com runs first because its booking id gets written into
    the spreadsheet row. The remaining four steps are independent, so they run
    CONCURRENTLY with asyncio.gather — the customer's SMS does not wait for the
    client's email to send.

    PARTIAL FAILURE IS OK. If SMS fails but the calendar and sheet succeeded,
    the booking still stands and the response tells you exactly which step
    failed. The booking is always written to logs/bookings.jsonl first, so a
    record survives even a total outage of every external service.
    """
    if req.weight_kg > MAX_WEIGHT_KG:
        raise HTTPException(
            status_code=400,
            detail=f"Load of {req.weight_kg} kg exceeds the {MAX_WEIGHT_KG} kg vehicle limit",
        )

    date_str = utils.normalise_date(req.date)
    time_str = utils.normalise_time(req.time)
    # Normalise the phone number ONCE, here at the edge, so the calendar, the
    # spreadsheet and the SMS all record the identical E.164 value.
    caller_phone = twilio_sms.normalise_uk_number(req.caller_phone)
    reference = booking_ref.generate_reference(date_str)
    steps: dict[str, Any] = {}

    log.info("Creating booking %s for %s on %s %s",
             reference, req.caller_name or "unnamed caller", date_str, time_str)

    # ── 1. Calendar ───────────────────────────────────────────────────────────
    calendar_result = await calcom.create_booking(
        caller_name=req.caller_name,
        caller_email=req.caller_email,
        caller_phone=caller_phone,
        date_str=date_str,
        time_str=time_str,
        pickup=req.pickup_address,
        dropoff=req.dropoff_address,
        weight_kg=req.weight_kg,
        quote_gbp=req.quote_gbp,
        reference=reference,
        distance_miles=req.distance_miles,
    )
    steps["calendar"] = calendar_result

    # ── 2. Everything else, in parallel ───────────────────────────────────────
    record = {
        "reference": reference,
        "created_at": utils.london_now().isoformat(timespec="seconds"),
        "status": "confirmed",
        "caller_name": req.caller_name,
        "caller_phone": caller_phone,
        "caller_email": req.caller_email,
        "pickup_address": req.pickup_address,
        "dropoff_address": req.dropoff_address,
        "weight_kg": req.weight_kg,
        "distance_miles": req.distance_miles or "",
        "quote_gbp": f"{req.quote_gbp:.2f}",
        "service_date": date_str,
        "service_time": time_str,
        "calcom_uid": calendar_result.get("booking_uid", ""),
        "call_id": req.call_id,
        "notes": req.notes,
    }

    sms_text = twilio_sms.build_booking_sms(
        reference=reference, pickup=req.pickup_address, dropoff=req.dropoff_address,
        date_str=date_str, time_str=time_str, quote_gbp=req.quote_gbp,
    )

    customer_subject, customer_text, customer_html = email_sender.build_customer_confirmation(
        reference=reference, caller_name=req.caller_name, pickup=req.pickup_address,
        dropoff=req.dropoff_address, date_str=date_str, time_str=time_str,
        weight_kg=req.weight_kg, quote_gbp=req.quote_gbp, distance_miles=req.distance_miles,
    )

    client_subject, client_text, client_html = email_sender.build_client_notification(
        reference=reference, caller_name=req.caller_name, caller_phone=caller_phone,
        caller_email=req.caller_email, pickup=req.pickup_address,
        dropoff=req.dropoff_address, date_str=date_str, time_str=time_str,
        weight_kg=req.weight_kg, quote_gbp=req.quote_gbp, distance_miles=req.distance_miles,
    )

    sheet_result, sms_result, customer_email, client_email = await asyncio.gather(
        sheets.append_booking(record),
        twilio_sms.send_sms(caller_phone, sms_text),
        email_sender.send_email(req.caller_email, customer_subject, customer_text, customer_html),
        email_sender.send_email(config.CLIENT_EMAIL, client_subject, client_text, client_html),
        return_exceptions=True,  # one failure must not cancel the others
    )

    steps["spreadsheet"] = _settle(sheet_result)
    steps["sms"] = _settle(sms_result)
    steps["customer_email"] = _settle(customer_email)
    steps["client_email"] = _settle(client_email)

    spoken_reference = booking_ref.spell_out_reference(reference)
    return BookingResponse(
        ok=True,
        reference=reference,
        message=(
            f"That's all booked in for you. Your reference is {spoken_reference}. "
            "You'll get a text and an email confirming everything shortly."
        ),
        steps=steps,
    )


def _settle(result: Any) -> dict:
    """Turn a gather() slot into a dict, even when it captured an exception."""
    if isinstance(result, BaseException):
        log.error("Booking sub-task failed: %s", result)
        return {"ok": False, "error": f"{type(result).__name__}: {result}"}
    return result if isinstance(result, dict) else {"ok": bool(result)}


@app.post("/booking/check-availability")
async def check_availability(req: AvailabilityRequest) -> dict:
    """Is a given date/time free on the client's calendar?"""
    date_str = utils.normalise_date(req.date)
    time_str = utils.normalise_time(req.time)
    result = await calcom.check_availability(date_str, time_str)
    return {
        "available": bool(result.get("available")),
        "next_available": result.get("next_available"),
        "date": date_str,
        "time": time_str,
        # True when Cal.com could not be reached and we defaulted to "available".
        "assumed": bool(result.get("assumed")),
        "free_slots": result.get("free_slots", []),
    }


class AlertRequest(BaseModel):
    reason: str = "unknown_error"
    details: dict[str, Any] = {}


@app.post("/booking/alert-failure")
async def alert_failure(req: AlertRequest) -> dict:
    """Email the client when a booking could not be completed automatically.

    n8n calls this on its failure branch. Putting the email here — rather than
    configuring an SMTP node inside n8n — means your mail password lives in ONE
    place (.env) instead of two, and n8n needs no credentials at all.
    """
    subject, text, html = email_sender.build_failure_alert(
        reason=req.reason, payload=req.details
    )
    result = await email_sender.send_email(config.CLIENT_EMAIL, subject, text, html)

    # Always keep a local record, even if the alert email itself fails to send.
    await log_event(config.CALLS_LOG, {
        "event": "booking_failure_alert",
        "reason": req.reason,
        "details": req.details,
        "email": result,
    })
    log.error("Booking failure alert: %s", req.reason)
    return {"ok": True, "alert_sent": bool(result.get("ok")), "email": result}


@app.get("/booking/{reference}")
async def get_booking(reference: str) -> dict:
    """Look up a booking by its reference (e.g. CRR-20260915-K7Q4)."""
    tidy = booking_ref.normalise_reference(reference)
    if not booking_ref.is_valid_reference(tidy):
        raise HTTPException(
            status_code=400,
            detail=f"'{reference}' is not a valid booking reference (expected CRR-YYYYMMDD-XXXX)",
        )

    record = await sheets.find_booking(tidy)
    if not record:
        raise HTTPException(status_code=404, detail=f"No booking found for {tidy}")

    return {"ok": True, "reference": tidy, "booking": record}


# ══════════════════════════════════════════════════════════════════════════════
#  PHASE 4 — Admin dashboard
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/admin/bookings")
async def admin_bookings(limit: int = 50) -> dict:
    """The last N bookings as JSON. Backs the dashboard and is handy for n8n."""
    limit = max(1, min(limit, 500))
    records = await sheets.list_bookings(limit=limit)
    today = utils.london_now().date().isoformat()
    return {
        "ok": True,
        "count": len(records),
        "today": today,
        "today_count": sum(1 for r in records if str(r.get("service_date", "")) == today),
        "source": "google_sheets" if config.SHEETS_ENABLED else "local_log",
        "bookings": records,
    }


@app.get("/admin", response_class=HTMLResponse)
async def admin_dashboard() -> HTMLResponse:
    """A single-page operations view.

    NO AUTHENTICATION YET — anyone with the URL can read customer details. Keep
    it on localhost, or put a password in front of it before sharing the ngrok
    link. Phase 5 adds proper auth.
    """
    return HTMLResponse(_ADMIN_HTML)


# The page fetches /admin/bookings itself, so this stays a plain string with no
# server-side templating to go wrong.
_ADMIN_HTML = """<!doctype html>
<html lang="en-GB">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Courier Bookings</title>
<style>
  :root { --ink:#16233a; --body:#3a4658; --line:#e3e9f2; --bg:#f6f9fd; --blue:#3871c2; }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--bg); color:var(--body);
         font:15px/1.5 -apple-system,"Segoe UI",Roboto,Arial,sans-serif; }
  header { background:#fff; border-bottom:1px solid var(--line); padding:18px 24px;
           display:flex; align-items:center; gap:16px; flex-wrap:wrap; }
  h1 { margin:0; font-size:19px; color:var(--ink); }
  .pill { background:var(--blue); color:#fff; border-radius:999px;
          padding:3px 11px; font-size:13px; font-weight:600; }
  .muted { color:#7c8798; font-size:13px; }
  main { padding:24px; }
  .wrap { overflow-x:auto; background:#fff; border:1px solid var(--line); border-radius:10px; }
  table { border-collapse:collapse; width:100%; min-width:940px; font-size:14px; }
  th { text-align:left; padding:11px 14px; background:#fbfcfe; color:var(--ink);
       border-bottom:1px solid var(--line); font-size:12px; text-transform:uppercase;
       letter-spacing:.04em; white-space:nowrap; }
  td { padding:11px 14px; border-bottom:1px solid #f1f4f9; vertical-align:top; }
  tr:last-child td { border-bottom:0; }
  .ref { font-family:ui-monospace,Consolas,monospace; font-weight:600; color:var(--ink); }
  .today { background:#eef5ff; }
  .price { font-weight:600; color:var(--ink); white-space:nowrap; }
  .addr { max-width:230px; }
  .empty { padding:44px; text-align:center; color:#7c8798; }
  footer { padding:14px 24px; color:#7c8798; font-size:12px; }
</style>
</head>
<body>
<header>
  <h1>Courier bookings</h1>
  <span class="pill" id="todayCount">-</span>
  <span class="muted" id="meta">Loading...</span>
</header>
<main>
  <div class="wrap">
    <table>
      <thead>
        <tr>
          <th>Reference</th><th>Date</th><th>Time</th><th>Customer</th>
          <th>Phone</th><th>Pickup</th><th>Dropoff</th><th>Weight</th><th>Price</th>
        </tr>
      </thead>

            <tbody id="rows"></tbody>
    </table>
    <div class="empty" id="empty" hidden>No bookings recorded yet.</div>
  </div>
</main>
<footer>Refreshes automatically every 60 seconds. No authentication - keep this page private.</footer>

<script>
// Escape anything that came from a phone call before putting it in the DOM.
// Customer-supplied text must never be trusted as HTML.
function esc(value) {
  return String(value === undefined || value === null ? "" : value)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

async function load() {
  try {
    const response = await fetch("/admin/bookings?limit=50", { cache: "no-store" });
    const data = await response.json();
    const today = data.today;
    const rows = data.bookings || [];

    document.getElementById("todayCount").textContent = data.today_count + " today";
    document.getElementById("meta").textContent =
      rows.length + " recent - source: " + data.source +
      " - updated " + new Date().toLocaleTimeString("en-GB");

    document.getElementById("empty").hidden = rows.length > 0;
    document.getElementById("rows").innerHTML = rows.map(function (b) {
      const isToday = String(b.service_date || "") === today;
      const price = b.quote_gbp ? "GBP " + esc(b.quote_gbp) : "";
      const weight = b.weight_kg ? esc(b.weight_kg) + " kg" : "";
      return "<tr class='" + (isToday ? "today" : "") + "'>" +
        "<td class='ref'>" + esc(b.reference) + "</td>" +
        "<td>" + esc(b.service_date) + "</td>" +
        "<td>" + esc(b.service_time) + "</td>" +
        "<td>" + esc(b.caller_name) + "</td>" +
        "<td>" + esc(b.caller_phone) + "</td>" +
        "<td class='addr'>" + esc(b.pickup_address) + "</td>" +
        "<td class='addr'>" + esc(b.dropoff_address) + "</td>" +
        "<td>" + weight + "</td>" +
        "<td class='price'>" + price + "</td>" +
      "</tr>";
    }).join("");
  } catch (error) {
    document.getElementById("meta").textContent = "Could not load bookings: " + error;
  }
}

load();
setInterval(load, 60000);
</script>
</body>
</html>"""


# ══════════════════════════════════════════════════════════════════════════════
#  Shared helpers and startup
# ══════════════════════════════════════════════════════════════════════════════

async def _safe_json(request: Any) -> dict:
    """Read a JSON body without ever raising on malformed input."""
    try:
        body = await request.json()
        return body if isinstance(body, dict) else {"value": body}
    except Exception:
        return {}


def _to_float(value: Any) -> float:
    """Convert whatever the AI sent into a number.

    Speech-to-text gives us '450', '450 kg', '450kg' or 'about 450', so we strip
    everything that is not part of a number rather than trusting float().
    """
    if isinstance(value, (int, float)):
        return float(value)
    try:
        match = re.search(r"-?\d+(?:\.\d+)?", str(value).replace(",", ""))
        return float(match.group()) if match else 0.0
    except (TypeError, ValueError):
        return 0.0
