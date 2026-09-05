"""
email_sender.py — sends confirmation emails to the customer and the client.

WHY RESEND'S HTTP API AND NOT SMTP
-----------------------------------
This used to be Gmail SMTP with an app password. That broke in production
after the Google account behind it was disabled and later reinstated: Google
puts reinstated accounts into an extended, opaque trust-rebuilding window
where SMTP-via-app-password stays blocked ("534 Please log in with your web
browser") regardless of correct settings - 2-Step Verification on, a brand
new app password, a full interactive browser login, all confirmed, none of
it helped, because the restriction isn't a setting at all. A production
system sending real customer confirmations cannot depend on an unpredictable
timer inside somebody's personal Google account.

Resend is a plain authenticated HTTPS POST, so this is now simpler than the
SMTP version too: no smtplib, no asyncio.to_thread to keep a blocking socket
off the event loop - httpx already does this natively.

SANDBOX NOTE: without a verified domain, Resend can only deliver to the email
address the Resend account itself was signed up with - not arbitrary
customers. Verify a domain (e.g. sscourier.co.uk) and change
RESEND_FROM_EMAIL before this can email real customers. See
docs/setup-guide.md.
"""

from __future__ import annotations

import logging

import httpx

from api import config

log = logging.getLogger(__name__)

_TIMEOUT_SECONDS = 15
_API_URL = "https://api.resend.com/emails"


# ── Core sender ───────────────────────────────────────────────────────────────

async def send_email(to: list[str] | str, subject: str, text_body: str,
                     html_body: str | None = None) -> dict:
    """Send one email to one or more recipients. Never raises.

    Returns {"ok": True, "to": [...]} or {"ok": False, "error": "..."}.
    """
    addresses = [to] if isinstance(to, str) else to
    recipients = [a.strip() for a in addresses if a and a.strip()]

    if not config.EMAIL_ENABLED:
        log.warning("Resend not configured - email '%s' skipped", subject)
        return {"ok": False, "skipped": True, "error": "resend_not_configured"}
    if not recipients:
        return {"ok": False, "error": "no_recipients"}

    payload = {
        "from": f"{config.EMAIL_FROM_NAME} <{config.RESEND_FROM_EMAIL}>",
        "to": recipients,
        "subject": subject,
        "text": text_body,
    }
    if html_body:
        payload["html"] = html_body

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
            resp = await client.post(
                _API_URL,
                headers={"Authorization": f"Bearer {config.RESEND_API_KEY}"},
                json=payload,
            )
        if resp.status_code >= 400:
            detail = _error_detail(resp)
            log.error("Resend send failed (%s): %s", resp.status_code, detail)
            return {"ok": False, "error": detail, "status_code": resp.status_code}

        log.info("Email '%s' sent to %s", subject, recipients)
        return {"ok": True, "to": recipients}

    except httpx.HTTPError as exc:
        # Network blip, timeout - log and continue. A failed email must never
        # cost us a confirmed booking.
        log.exception("Resend network error")
        return {"ok": False, "error": f"network_error: {exc}"}


def _error_detail(resp: httpx.Response) -> str:
    """Resend errors arrive as {"message": "...", "name": "..."}."""
    try:
        body = resp.json()
        return f"{body.get('message', 'unknown')} ({body.get('name', 'error')})"
    except Exception:
        return resp.text[:300]


# ── Message templates ─────────────────────────────────────────────────────────

def _row(label: str, value: str) -> str:
    """One table row used by the HTML emails."""
    return (
        '<tr style="border-bottom:1px solid #e5e7eb">'
        f'<td style="color:#6b7280;width:150px">{label}</td>'
        f"<td>{value}</td></tr>"
    )


def build_customer_confirmation(*, reference: str, caller_name: str, pickup: str,
                                dropoff: str, date_str: str, time_str: str,
                                weight_kg: float, quote_gbp: float,
                                distance_miles: float | None) -> tuple[str, str, str]:
    """Returns (subject, text_body, html_body) for the customer's copy."""
    subject = f"Your delivery is booked - {reference}"
    miles = f"{distance_miles:.1f} miles" if distance_miles else "to be confirmed"
    greeting = caller_name or "there"

    text = f"""Hello {greeting},

Your collection is confirmed. Here are the details:

Booking reference : {reference}
Date and time     : {date_str} at {time_str}
Collection from   : {pickup}
Delivery to       : {dropoff}
Load weight       : {weight_kg:g} kg
Distance          : {miles}
Total price       : GBP {quote_gbp:.2f}

Our driver will call you shortly before arrival. If anything changes, call us
and quote your reference number.

Thank you for your booking.
{config.CLIENT_NAME}
"""

    rows = "".join([
        _row("Date and time", f"{date_str} at {time_str}"),
        _row("Collection from", pickup),
        _row("Delivery to", dropoff),
        _row("Load weight", f"{weight_kg:g} kg"),
        _row("Distance", miles),
        _row("Total price", f"<strong>GBP {quote_gbp:.2f}</strong>"),
    ])

    html = f"""<div style="font-family:-apple-system,Segoe UI,Arial,sans-serif;max-width:560px;color:#1f2937">
  <h2 style="color:#16233a;margin:0 0 4px">Your delivery is booked</h2>
  <p style="margin:0 0 16px;color:#6b7280">Reference
    <strong style="color:#16233a;font-size:16px">{reference}</strong></p>
  <table cellpadding="8" cellspacing="0" style="border-collapse:collapse;width:100%;font-size:14px">
    {rows}
  </table>
  <p style="font-size:14px;margin-top:20px">Our driver will call you shortly before
     arrival. If anything changes, call us and quote your reference number.</p>
  <p style="font-size:13px;color:#6b7280">Thank you for your booking.<br>{config.CLIENT_NAME}</p>
</div>"""

    return subject, text, html


def build_client_notification(*, reference: str, caller_name: str, caller_phone: str,
                              caller_email: str, pickup: str, dropoff: str,
                              date_str: str, time_str: str, weight_kg: float,
                              quote_gbp: float,
                              distance_miles: float | None) -> tuple[str, str, str]:
    """Returns (subject, text_body, html_body) for the business owner's copy."""
    subject = f"NEW BOOKING {reference} - {date_str} {time_str} - GBP {quote_gbp:.2f}"
    miles = f"{distance_miles:.1f}" if distance_miles else "n/a"
    name = caller_name or "not given"
    phone = caller_phone or "not given"
    mail = caller_email or "not given"

    text = f"""New booking taken by the AI agent.

Reference   : {reference}
Customer    : {name}
Phone       : {phone}
Email       : {mail}

Date / time : {date_str} at {time_str}
Pickup      : {pickup}
Dropoff     : {dropoff}
Weight      : {weight_kg:g} kg
Distance    : {miles} miles
Price       : GBP {quote_gbp:.2f}
"""

    rows = "".join([
        _row("Customer", name),
        _row("Phone", phone),
        _row("Email", mail),
        _row("Date and time", f"{date_str} at {time_str}"),
        _row("Pickup", pickup),
        _row("Dropoff", dropoff),
        _row("Weight", f"{weight_kg:g} kg"),
        _row("Distance", f"{miles} miles"),
        _row("Price", f"<strong>GBP {quote_gbp:.2f}</strong>"),
    ])

    html = f"""<div style="font-family:-apple-system,Segoe UI,Arial,sans-serif;max-width:560px;color:#1f2937">
  <h2 style="color:#16233a;margin:0 0 4px">New booking - {reference}</h2>
  <p style="margin:0 0 16px;color:#6b7280">Taken automatically by the voice agent.</p>
  <table cellpadding="8" cellspacing="0" style="border-collapse:collapse;width:100%;font-size:14px">
    {rows}
  </table>
</div>"""

    return subject, text, html


def build_failure_alert(*, reason: str, payload: dict) -> tuple[str, str, str]:
    """Alert sent to the client when a booking could NOT be completed, so a
    human can rescue it. Called from api/main.py's _auto_create_booking()
    when a call ends with the quote accepted but the booking cannot actually
    be created."""
    subject = "ACTION NEEDED - booking could not be completed automatically"
    lines = "\n".join(f"{key:<16}: {value}" for key, value in payload.items())

    text = f"""A caller accepted a quote but the booking did not complete.

Reason: {reason}

Details captured on the call:
{lines}

Please contact the customer manually.
"""

    html = f"""<div style="font-family:-apple-system,Segoe UI,Arial,sans-serif;max-width:560px">
  <h2 style="color:#b91c1c;margin:0 0 8px">Booking failed - manual action needed</h2>
  <p style="font-size:14px"><strong>Reason:</strong> {reason}</p>
  <pre style="background:#f6f9fd;padding:12px;border-radius:6px;font-size:13px;white-space:pre-wrap">{lines}</pre>
  <p style="font-size:14px">Please contact the customer manually.</p>
</div>"""

    return subject, text, html
