"""
twilio_sms.py — sends SMS confirmations and redirects live calls to the client.

WHY NOT THE OFFICIAL TWILIO SDK?
--------------------------------
The `twilio` Python package is synchronous. Calling it from an async FastAPI
endpoint blocks the whole event loop — while we wait on Twilio, no other caller
can get a quote. Twilio's REST API is just HTTP basic auth + a form body, so we
use httpx and stay fully async. One less dependency, and it's non-blocking.
"""

from __future__ import annotations

import logging
import re

import httpx

from api import config

log = logging.getLogger(__name__)

_API_ROOT = "https://api.twilio.com/2010-04-01"
_TIMEOUT = httpx.Timeout(10.0)


# ── Phone number tidy-up ──────────────────────────────────────────────────────

def normalise_uk_number(raw: str) -> str:
    """Convert a spoken/typed UK number into E.164 (+44...) form.

    Speech-to-text hands us things like "oh seven seven double oh nine hundred"
    which Vapi renders as "07700 900123". Twilio only accepts E.164, so:
        07700 900123    -> +447700900123
        44 7700900123   -> +447700900123
        00447700900123  -> +447700900123
        7700900123      -> +447700900123
        +447700900123   -> unchanged

    THE TRUNK-ZERO TRAP
    -------------------
    UK numbers are written nationally with a leading 0 (07367 312558), but that
    0 is a "trunk prefix" that must be DROPPED after the country code. People
    routinely keep it and write +4407367312558, which is one digit too long and
    is rejected outright by Twilio. We strip it rather than passing the broken
    number through, because the failure otherwise shows up much later as an
    undeliverable text.
    """
    if not raw:
        return ""

    text = re.sub(r"[^\d+]", "", str(raw))
    if not text:
        return ""

    # Reduce whatever we were given to a plain international number.
    if text.startswith("+"):
        national = text[1:]
    elif text.startswith("00"):       # international access code
        national = text[2:]
    elif text.startswith("0"):        # national format, e.g. 07367 312558
        national = "44" + text[1:]
    else:
        national = text

    # "+44 07367..." - country code followed by the trunk zero.
    if national.startswith("440"):
        national = "44" + national[3:]

    # A bare UK mobile with no country code at all, e.g. 7367312558.
    if not national.startswith("44") and len(national) == 10 and national.startswith("7"):
        national = "44" + national

    return "+" + national


def is_phone_number(sender: str) -> bool:
    """True if this is a real number rather than an alphanumeric sender ID."""
    return bool(sender) and re.fullmatch(r"\+?\d{6,15}", sender.strip()) is not None


def sender_id_problem(sender: str) -> str | None:
    """Check an alphanumeric sender ID against the rules, or None if fine.

    Alphanumeric sender IDs let texts arrive from a business name ("SSCourier")
    instead of a number, which is what the client chose. The constraints:
      * 1-11 characters, letters/digits/spaces only
      * must contain at least one letter
      * the account must be upgraded off trial
      * they are ONE-WAY - the customer cannot reply
    """
    sender = (sender or "").strip()
    if not sender or is_phone_number(sender):
        return None
    if len(sender) > 11:
        return f"sender ID {sender!r} is {len(sender)} characters; the limit is 11"
    if not re.fullmatch(r"[A-Za-z0-9 ]+", sender):
        return f"sender ID {sender!r} may only contain letters, digits and spaces"
    if not re.search(r"[A-Za-z]", sender):
        return f"sender ID {sender!r} must contain at least one letter"
    return None


# ── SMS ───────────────────────────────────────────────────────────────────────

async def send_sms(to_number: str, body: str) -> dict:
    """Send one SMS. Returns a result dict; never raises.

    Returns {"ok": True, "sid": "SM..."} or {"ok": False, "error": "..."}.
    """
    to_e164 = normalise_uk_number(to_number)

    if not config.TWILIO_ENABLED:
        log.warning("Twilio not configured — SMS to %s skipped", to_e164)
        return {"ok": False, "skipped": True, "error": "twilio_not_configured"}
    if not to_e164:
        return {"ok": False, "error": "no_destination_number"}

    # Catch a malformed sender ID here rather than reading Twilio's error later.
    problem = sender_id_problem(config.TWILIO_FROM_NUMBER)
    if problem:
        log.error("TWILIO_FROM_NUMBER invalid - %s", problem)
        return {"ok": False, "error": f"invalid_sender: {problem}"}

    url = f"{_API_ROOT}/Accounts/{config.TWILIO_ACCOUNT_SID}/Messages.json"
    payload = {"To": to_e164, "From": config.TWILIO_FROM_NUMBER, "Body": body[:1500]}

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(
                url,
                data=payload,
                auth=(config.TWILIO_ACCOUNT_SID, config.TWILIO_AUTH_TOKEN),
            )
        if resp.status_code >= 400:
            detail = _twilio_error(resp)
            log.error("Twilio SMS failed (%s): %s", resp.status_code, detail)
            return {"ok": False, "error": detail, "status_code": resp.status_code}

        sid = resp.json().get("sid")
        log.info("SMS sent to %s (sid=%s)", to_e164, sid)
        return {"ok": True, "sid": sid, "to": to_e164}

    except httpx.HTTPError as exc:
        # Network blip, DNS failure, timeout — log it, keep the call alive.
        log.exception("Twilio SMS network error")
        return {"ok": False, "error": f"network_error: {exc}"}


def build_booking_sms(*, reference: str, pickup: str, dropoff: str,
                      date_str: str, time_str: str, quote_gbp: float) -> str:
    """The confirmation SMS text. Kept short — long messages bill as multiple
    segments and get truncated by some handsets."""
    return (
        f"Booking confirmed: {reference}\n"
        f"{date_str} at {time_str}\n"
        f"From: {_short(pickup)}\n"
        f"To: {_short(dropoff)}\n"
        f"Price: GBP {quote_gbp:.2f}\n"
        f"Questions? Call us back and quote your reference."
    )


def _short(address: str, limit: int = 48) -> str:
    address = (address or "").strip()
    return address if len(address) <= limit else address[: limit - 1] + "\u2026"


# ── Live call transfer (Phase 4) ──────────────────────────────────────────────

async def transfer_call(call_sid: str, to_number: str | None = None,
                        whisper: str | None = None) -> dict:
    """Redirect an in-progress Twilio call to the client's mobile.

    HOW THIS WORKS
    --------------
    Twilio calls are state machines you can update mid-flight. POSTing new TwiML
    to /Calls/{CallSid}.json tears down whatever the call was doing (talking to
    our AI agent) and immediately runs the new instructions instead — here, a
    <Dial> to the client's mobile.

    IMPORTANT: this only works when the call is running on YOUR Twilio account
    and you have the CallSid. If Vapi is using its own telephony, use Vapi's
    native transfer instead (see docs/setup-guide.md) — the /vapi/transfer
    endpoint returns that shape too, so both paths are covered.
    """
    destination = normalise_uk_number(to_number or config.CLIENT_PHONE_NUMBER)

    if not config.TWILIO_ENABLED:
        return {"ok": False, "skipped": True, "error": "twilio_not_configured"}
    if not call_sid:
        return {"ok": False, "error": "no_call_sid"}
    if not destination:
        return {"ok": False, "error": "no_client_phone_number"}

    say = whisper or "Connecting you to a member of our team now. Please hold."

    # callerId must be a REAL phone number. When TWILIO_FROM_NUMBER holds an
    # alphanumeric sender ID (e.g. "SSCourier") it is valid for SMS but illegal
    # here, and Twilio rejects the whole TwiML. In that case we omit the
    # attribute and let Twilio fall back to the original caller's number.
    caller_id = (
        f' callerId="{config.TWILIO_FROM_NUMBER}"'
        if is_phone_number(config.TWILIO_FROM_NUMBER) else ""
    )

    twiml = (
        "<Response>"
        f"<Say voice=\"Polly.Amy\" language=\"en-GB\">{_xml_escape(say)}</Say>"
        f"<Dial timeout=\"30\"{caller_id}>"
        f"{destination}</Dial>"
        "<Say voice=\"Polly.Amy\" language=\"en-GB\">Sorry, we could not reach "
        "the team. Please call back shortly.</Say>"
        "</Response>"
    )

    url = f"{_API_ROOT}/Accounts/{config.TWILIO_ACCOUNT_SID}/Calls/{call_sid}.json"
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(
                url,
                data={"Twiml": twiml},
                auth=(config.TWILIO_ACCOUNT_SID, config.TWILIO_AUTH_TOKEN),
            )
        if resp.status_code >= 400:
            detail = _twilio_error(resp)
            log.error("Twilio transfer failed (%s): %s", resp.status_code, detail)
            return {"ok": False, "error": detail, "status_code": resp.status_code}

        log.info("Call %s transferred to %s", call_sid, destination)
        return {"ok": True, "call_sid": call_sid, "transferred_to": destination}

    except httpx.HTTPError as exc:
        log.exception("Twilio transfer network error")
        return {"ok": False, "error": f"network_error: {exc}"}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _twilio_error(resp: httpx.Response) -> str:
    """Twilio returns {"message": "...", "code": 21211} on failure."""
    try:
        body = resp.json()
        return f"{body.get('message', 'unknown')} (code {body.get('code')})"
    except Exception:
        return resp.text[:200]


def _xml_escape(text: str) -> str:
    """TwiML is XML — an unescaped & or < would break the whole document."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
