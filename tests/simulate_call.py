"""
simulate_call.py — walk through a complete phone call against a RUNNING server.

WHAT IT DOES
------------
Plays out a whole booking exactly as Vapi would drive it:

    1. /health                     is the API up, and what is configured?
    2. /vapi/quote                 the AI has the 5 details -> speak a price
    3. /vapi/quote (1200 kg)       over capacity -> hand to a human
    4. /booking/check-availability is that slot free?
    5. /vapi/end-of-call           the call ends AND, since the caller
                                    accepted, the booking is created right
                                    here - calendar, sheet, SMS, both emails.
                                    This is the same in-process step a real
                                    call triggers; there is no separate
                                    "create the booking" call to make.
    6. /booking/{reference}        read the booking back

Unlike the pytest files, this talks to a REAL server, so it is the closest
thing to a live call without picking up the phone. Use it as the demo for the
client too — the printed lines are what the caller actually hears.

USAGE
-----
    # terminal 1
    ./venv/Scripts/python.exe -m uvicorn api.main:app --reload

    # terminal 2
    ./venv/Scripts/python.exe tests/simulate_call.py
    ./venv/Scripts/python.exe tests/simulate_call.py --url https://your.ngrok.dev
    ./venv/Scripts/python.exe tests/simulate_call.py --no-booking   # see below

WARNING: step 5 is real. If Twilio, Cal.com and SMTP are configured it WILL
send a text, create a calendar entry and email people, the moment the
end-of-call event is sent — booking creation is no longer a step you can
separately opt out of, since it happens automatically. --no-booking instead
sends the end-of-call event with booking_accepted set to false, so the
server behaves exactly as it would for a caller who never said yes, and
step 5 stops after showing that outcome.
"""

from __future__ import annotations

import argparse
import sys

import httpx

DEFAULT_URL = "http://localhost:8000"

CALLER = {
    "name": "Sarah Jones",
    "phone": "07700900123",
    "email": "sarah@example.com",
}

JOB = {
    "pickup_address": "1 Oxford Street, London, W1D 1BS",
    "dropoff_address": "Canary Wharf, London, E14 5AB",
    "weight_kg": 350,
    "date": "2026-09-15",
    "time": "10:00",
}


# ── Pretty printing ───────────────────────────────────────────────────────────

def step(number: int, title: str) -> None:
    print(f"\n{'=' * 74}\n  STEP {number}  {title}\n{'=' * 74}")


def caller_says(text: str) -> None:
    print(f"  CALLER : {text}")


def agent_says(text: str) -> None:
    """Wrap the agent's speech so long sentences stay readable."""
    import textwrap

    wrapped = textwrap.fill(text, width=68, initial_indent="", subsequent_indent="           ")
    print(f"  AGENT  : {wrapped}")


def detail(label: str, value: object) -> None:
    print(f"           {label}: {value}")


def fail(message: str) -> None:
    print(f"\n  FAILED: {message}")
    sys.exit(1)


# ── Vapi payload builders ─────────────────────────────────────────────────────

def tool_call(name: str, arguments: dict, call_id: str = "sim_call_001") -> dict:
    """The exact shape Vapi POSTs when the assistant invokes a tool."""
    return {
        "message": {
            "type": "tool-calls",
            "call": {"id": call_id, "customer": {"number": "+447700900123"}},
            "toolCalls": [{
                "id": "sim_tool_1",
                "type": "function",
                "function": {"name": name, "arguments": arguments},
            }],
        }
    }


def end_of_call(quote: float, distance: float, call_id: str = "sim_call_001",
                accepted: bool = True) -> dict:
    """The end-of-call-report Vapi sends once the caller hangs up.

    accepted=False reproduces a call where the caller never said yes - the
    server will not attempt to create a booking, matching --no-booking.
    """
    return {
        "message": {
            "type": "end-of-call-report",
            "call": {"id": call_id, "customer": {"number": "+447700900123"}},
            "endedReason": "customer-ended-call",
            "durationSeconds": 138.4,
            "summary": ("Caller booked a same-day delivery and accepted the quote."
                       if accepted else "Caller enquired about pricing only."),
            "transcript": (
                "AI: Good afternoon, how can I help?\n"
                "User: I need a delivery from Oxford Street to Canary Wharf.\n"
                "AI: ... the price would be ...\n"
                + ("User: Yes, that's fine, please book it in." if accepted
                   else "User: Thanks, I'll think about it and call back.")
            ),
            "analysis": {
                "structuredData": {
                    "caller_name": CALLER["name"],
                    "caller_phone": CALLER["phone"],
                    "caller_email": CALLER["email"],
                    "pickup_address": JOB["pickup_address"],
                    "dropoff_address": JOB["dropoff_address"],
                    "weight_kg": JOB["weight_kg"],
                    "date": JOB["date"],
                    "time": JOB["time"],
                    "quote_gbp": quote,
                    "distance_miles": distance,
                    "booking_accepted": accepted,
                }
            },
        }
    }


# ── The simulation ────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Simulate a full courier booking call")
    parser.add_argument("--url", default=DEFAULT_URL, help="Base URL of the running API")
    parser.add_argument("--no-booking", action="store_true",
                        help="Simulate the caller declining, so no real SMS/email/"
                             "calendar entry is ever created")
    args = parser.parse_args()

    base = args.url.rstrip("/")
    client = httpx.Client(base_url=base, timeout=45.0)

    print(f"\n  Simulating a call against {base}")

    # ── 1. Health ─────────────────────────────────────────────────────────────
    step(1, "Is the API up?")
    try:
        health = client.get("/health").json()
    except httpx.HTTPError as exc:
        fail(f"Could not reach {base} - is uvicorn running?  ({exc})")

    detail("status", health.get("status"))
    for name, ready in health.get("integrations", {}).items():
        detail(name, "configured" if ready else "NOT configured")

    # ── 2. Quote ──────────────────────────────────────────────────────────────
    step(2, "The AI has all five details and asks for a price")
    caller_says("I need a van from Oxford Street to Canary Wharf, "
                "about 350 kilos, the 15th of September at 10am.")

    quote = client.post("/vapi/quote", json=tool_call("get_quote", JOB)).json()
    agent_says(quote.get("result", "(no speech returned)"))

    if quote.get("action") != "quote":
        fail(f"Expected a quote, got action={quote.get('action')}")

    price = quote["quote_gbp"]
    distance = quote["distance_miles"]
    detail("action", quote["action"])
    detail("quote_gbp", price)
    detail("distance_miles", distance)

    # ── 3. Over capacity ──────────────────────────────────────────────────────
    step(3, "A different caller has a load that is too heavy")
    caller_says("Actually it's more like 1200 kilos.")

    heavy = client.post("/vapi/quote",
                        json=tool_call("get_quote", {**JOB, "weight_kg": 1200})).json()
    agent_says(heavy.get("result", ""))
    detail("action", heavy.get("action"))
    detail("transfer_reason", heavy.get("transfer_reason"))

    if heavy.get("action") != "transfer":
        fail("A 1200 kg load must trigger a human transfer")
    if "quote_gbp" in heavy:
        fail("An over-capacity load must never be priced")

    # ── 4. Availability ───────────────────────────────────────────────────────
    step(4, "Check the slot is free")
    availability = client.post("/booking/check-availability",
                               json={"date": JOB["date"], "time": JOB["time"]}).json()
    detail("available", availability.get("available"))
    detail("assumed (unverified)", availability.get("assumed"))
    detail("next_available", availability.get("next_available"))

    # ── 5. End of call — this is also where the booking gets created ─────────
    step(5, "The caller accepts and hangs up")
    if args.no_booking:
        caller_says("Thanks, I'll think about it and call back.")
    else:
        caller_says("Yes, that's fine, please book it in.")

    report = client.post(
        "/vapi/end-of-call",
        json=end_of_call(price, distance, accepted=not args.no_booking),
    ).json()
    detail("call_status", report.get("call_status"))
    detail("duration_seconds", report.get("duration_seconds"))

    if args.no_booking:
        if report.get("call_status") != "no_booking":
            fail(f"Expected no_booking, got {report.get('call_status')}")
        outcome = report.get("booking_outcome", {})
        detail("booking attempted", outcome.get("attempted", False))
        print("\n  --no-booking set: the caller declined, so nothing real was created.")
        return

    if report.get("call_status") != "booking_accepted":
        fail(f"Expected booking_accepted, got {report.get('call_status')}")

    booking_data = report["booking_data"]
    detail("extracted name", booking_data["caller_name"])
    detail("extracted phone", booking_data["caller_phone"])
    detail("extracted date", f"{booking_data['date']} {booking_data['time']}")

    # The booking was created automatically inside /vapi/end-of-call itself -
    # see api/main.py's _auto_create_booking(). Its outcome is right here in
    # the same response; there is no separate call left to make.
    outcome = report.get("booking_outcome", {})
    if not outcome.get("ok"):
        fail(f"Booking was not created: {outcome.get('error', 'unknown reason')}")

    reference = outcome.get("reference")
    if not reference:
        fail("Booking reported ok but no reference was returned")

    print()
    detail("REFERENCE", reference)
    detail("booking outcome", outcome)

    # ── 6. Read it back ────────────────────────────────────────────────────────
    step(6, "Look the booking up by its reference")
    lookup = client.get(f"/booking/{reference}")

    if lookup.status_code != 200:
        fail(f"Could not read booking {reference} back: {lookup.status_code}")

    record = lookup.json()["booking"]
    detail("reference", record.get("reference"))
    detail("customer", record.get("caller_name"))
    detail("service", f"{record.get('service_date')} at {record.get('service_time')}")
    detail("price", f"GBP {record.get('quote_gbp')}")

    print(f"\n{'=' * 74}")
    print(f"  CALL SIMULATION COMPLETE — booking {reference} created and verified.")
    print(f"  See it in the dashboard: {base}/admin")
    print(f"{'=' * 74}\n")


if __name__ == "__main__":
    main()
