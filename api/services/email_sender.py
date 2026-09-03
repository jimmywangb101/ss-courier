"""
email_sender.py — sends confirmation emails to the customer and the client.

WHY STDLIB smtplib AND NOT AN ASYNC LIBRARY?
--------------------------------------------
`smtplib` is part of Python, so it is one fewer dependency to install and break.
It IS blocking though, so every send runs inside `asyncio.to_thread(...)`, which
hands the blocking work to a background thread and lets the event loop carry on
serving other callers. That gives us the safety of stdlib with async behaviour.

GMAIL NOTE: SMTP_PASSWORD must be a 16-character **App Password**, not your
normal Google password. See docs/setup-guide.md.
"""

from __future__ import annotations

import asyncio
import logging
import smtplib
from email.message import EmailMessage

from api import config

log = logging.getLogger(__name__)

_TIMEOUT_SECONDS = 15


# ── Core sender ───────────────────────────────────────────────────────────────

async def send_email(to: list[str] | str, subject: str, text_body: str,
                     html_body: str | None = None) -> dict:
    """Send one email to one or more recipients. Never raises.

    Returns {"ok": True, "to": [...]} or {"ok": False, "error": "..."}.
    """
    addresses = [to] if isinstance(to, str) else to
    recipients = [a.strip() for a in addresses if a and a.strip()]

    if not config.EMAIL_ENABLED:
        log.warning("SMTP not configured - email '%s' skipped", subject)
        return {"ok": False, "skipped": True, "error": "smtp_not_configured"}
    if not recipients:
        return {"ok": False, "error": "no_recipients"}

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = f"{config.SMTP_FROM_NAME} <{config.SMTP_USER}>"
    message["To"] = ", ".join(recipients)
    message.set_content(text_body)
    if html_body:
        # Adding HTML as an alternative means plain-text clients still work.
        message.add_alternative(html_body, subtype="html")

    try:
        # to_thread moves the blocking SMTP conversation off the event loop.
        await asyncio.to_thread(_send_blocking, message, recipients)
        log.info("Email '%s' sent to %s", subject, recipients)
        return {"ok": True, "to": recipients}
    except Exception as exc:
        # Bad password, greylisting, DNS - log and continue. A failed email must
        # never lose us a confirmed booking.
        log.exception("Email send failed")
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def _send_blocking(message: EmailMessage, recipients: list[str]) -> None:
    """The actual SMTP conversation. Runs in a worker thread."""
    if config.SMTP_PORT == 465:
        # Port 465 = implicit TLS: encrypted from the very first byte.
        with smtplib.SMTP_SSL(config.SMTP_HOST, config.SMTP_PORT,
                              timeout=_TIMEOUT_SECONDS) as server:
            server.login(config.SMTP_USER, config.SMTP_PASSWORD)
            server.send_message(message, to_addrs=recipients)
    else:
        # Port 587 = STARTTLS: connect in the clear, then upgrade to TLS.
        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT,
                          timeout=_TIMEOUT_SECONDS) as server:
            server.starttls()
            server.login(config.SMTP_USER, config.SMTP_PASSWORD)
            server.send_message(message, to_addrs=recipients)


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
