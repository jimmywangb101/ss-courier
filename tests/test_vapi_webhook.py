"""
test_vapi_webhook.py — tests for every Vapi webhook handler.

Run with:  ./venv/Scripts/python.exe -m pytest tests/ -v

WHAT WE ARE PROTECTING
----------------------
These endpoints run while a customer is on the phone. The two things that must
never break are:
  * the 790 kg capacity rule (a wrong answer sends an overloaded van out), and
  * every response containing a speakable sentence, never raw JSON or an error.
"""

from __future__ import annotations

import pytest

from conftest import legacy_call_payload, tool_call_payload
from api.services import booking_ref

QUOTE_ARGS = {
    "pickup_address": "1 Oxford Street, London, W1D 1BS",
    "dropoff_address": "Canary Wharf, London, E14 5AB",
    "weight_kg": 350,
    "date": "2026-09-15",
    "time": "10:00",
}


# ══════════════════════════════════════════════════════════════════════════════
#  /vapi/quote
# ══════════════════════════════════════════════════════════════════════════════

def test_quote_returns_speech_and_price(client):
    """The happy path: a spoken sentence plus the structured numbers."""
    response = client.post("/vapi/quote", json=tool_call_payload("get_quote", QUOTE_ARGS))
    assert response.status_code == 200

    body = response.json()
    assert body["action"] == "quote"
    # 15 base + (9.43 * 2.50) = 38.575 -> 38.58, no surcharge under 400 kg
    assert body["quote_gbp"] == 38.58
    assert body["distance_miles"] == 9.43

    speech = body["result"]
    assert isinstance(speech, str) and len(speech) > 20
    assert "38 pounds 58" in speech          # spoken, not "38.58"
    assert "book that in" in speech.lower()  # asks for the sale


def test_quote_supports_both_vapi_formats(client):
    """New 'toolCalls' and legacy 'functionCall' payloads both work."""
    modern = client.post("/vapi/quote", json=tool_call_payload("get_quote", QUOTE_ARGS))
    legacy = client.post("/vapi/quote", json=legacy_call_payload("get_quote", QUOTE_ARGS))

    assert modern.json()["quote_gbp"] == legacy.json()["quote_gbp"] == 38.58
    # Only the modern format echoes a toolCallId back.
    assert modern.json()["results"][0]["toolCallId"] == "tool_1"
    assert "results" not in legacy.json()


def test_quote_accepts_field_aliases(client):
    """The AI does not always use our exact parameter names."""
    response = client.post("/vapi/quote", json=tool_call_payload("get_quote", {
        "pickup": "Manchester Piccadilly",
        "dropoff": "Leeds City Centre",
        "weight": "350 kg",       # units stuck to the number
        "date": "tomorrow",       # relative date
        "time": "half past two",  # spoken time
    }))
    assert response.json()["action"] == "quote"


@pytest.mark.parametrize("weight,expected_surcharge", [
    (399, False),
    (400, False),   # rule is "over 400", so exactly 400 is not surcharged
    (401, True),
    (790, True),
])
def test_weight_surcharge_boundary(client, weight, expected_surcharge):
    """The 10% surcharge applies only ABOVE 400 kg."""
    args = {**QUOTE_ARGS, "weight_kg": weight}
    body = client.post("/vapi/quote", json=tool_call_payload("get_quote", args)).json()

    base_price = 38.58  # 15 + 9.43 * 2.50
    if expected_surcharge:
        assert body["quote_gbp"] > base_price
        assert "surcharge" in body["result"].lower()
    else:
        assert body["quote_gbp"] == base_price
        assert "surcharge" not in body["result"].lower()


@pytest.mark.parametrize("weight", [790.01, 791, 900, 2000])
def test_over_capacity_transfers_not_crashes(client, weight):
    """Anything over 790 kg must route to a human, politely."""
    args = {**QUOTE_ARGS, "weight_kg": weight}
    body = client.post("/vapi/quote", json=tool_call_payload("get_quote", args)).json()

    assert body["action"] == "transfer"
    assert body["transfer_reason"] == "over_capacity"
    assert "quote_gbp" not in body            # never price an overloaded job
    assert "790" in body["result"]            # explains the limit to the caller


def test_exactly_at_capacity_is_still_quoted(client):
    """790 kg is the limit, so 790 itself must still get a price."""
    args = {**QUOTE_ARGS, "weight_kg": 790}
    body = client.post("/vapi/quote", json=tool_call_payload("get_quote", args)).json()
    assert body["action"] == "quote"


@pytest.mark.parametrize("args,expected_action", [
    ({**QUOTE_ARGS, "weight_kg": 0}, "need_weight"),
    ({**QUOTE_ARGS, "weight_kg": "dunno"}, "need_weight"),
    ({"weight_kg": 350}, "need_addresses"),
    ({"pickup_address": "London", "weight_kg": 350}, "need_addresses"),
])
def test_missing_fields_ask_a_question(client, args, expected_action):
    """Missing data produces a follow-up question, never an error."""
    body = client.post("/vapi/quote", json=tool_call_payload("get_quote", args)).json()
    assert body["action"] == expected_action
    assert body["result"].strip().endswith("?")


def test_quote_survives_maps_failure(client, monkeypatch):
    """A bad postcode must produce a question, not a 500."""
    from api import main

    async def broken_distance(origin, destination):
        raise main.HTTPException(status_code=422, detail="Route not found")

    monkeypatch.setattr(main, "get_distance_miles", broken_distance)

    response = client.post("/vapi/quote", json=tool_call_payload("get_quote", QUOTE_ARGS))
    assert response.status_code == 200
    assert response.json()["action"] == "need_valid_addresses"
    assert "postcode" in response.json()["result"].lower()


def test_maps_billing_error_transfers_instead_of_blaming_the_caller(client, monkeypatch):
    """If OUR Google account is broken, do not ask the caller for a postcode.

    They would just hit the same wall. Hand them to a human and log it loudly.
    """
    from api import main

    async def account_error(origin, destination):
        raise main.HTTPException(
            status_code=422,
            detail="account: Maps API REQUEST_DENIED - You must enable Billing")

    monkeypatch.setattr(main, "get_distance_miles", account_error)

    body = client.post("/vapi/quote", json=tool_call_payload("get_quote", QUOTE_ARGS)).json()

    assert body["action"] == "transfer"
    assert body["transfer_reason"] == "system_error"
    assert "postcode" not in body["result"].lower()

    import json
    record = json.loads(main.config.TRANSFERS_LOG.read_text(encoding="utf-8").strip())
    assert record["reason"] == "maps_account_error"


def test_empty_body_does_not_crash(client):
    """Malformed input still returns something speakable."""
    response = client.post("/vapi/quote", json={})
    assert response.status_code == 200
    assert isinstance(response.json()["result"], str)


# ══════════════════════════════════════════════════════════════════════════════
#  /vapi/transfer
# ══════════════════════════════════════════════════════════════════════════════

def test_transfer_returns_hold_message_and_destination(client):
    body = client.post("/vapi/transfer", json=tool_call_payload(
        "transfer_to_human", {"reason": "human_requested"})).json()

    assert body["action"] == "transfer"
    assert body["transfer_reason"] == "human_requested"
    assert "hold" in body["result"].lower()
    assert body["destination"]["type"] == "number"


def test_transfer_is_logged(client, tmp_path):
    """Every transfer must leave an audit trail."""
    from api import main

    client.post("/vapi/transfer", json=tool_call_payload(
        "transfer_to_human", {"reason": "human_requested"}))

    lines = main.config.TRANSFERS_LOG.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    import json
    assert json.loads(lines[0])["reason"] == "human_requested"


def test_over_capacity_quote_also_logs_a_transfer(client):
    """An over-capacity quote is a transfer event too."""
    from api import main

    client.post("/vapi/quote", json=tool_call_payload(
        "get_quote", {**QUOTE_ARGS, "weight_kg": 1200}))

    import json
    record = json.loads(main.config.TRANSFERS_LOG.read_text(encoding="utf-8").strip())
    assert record["reason"] == "over_capacity"
    assert record["weight_kg"] == 1200


# ══════════════════════════════════════════════════════════════════════════════
#  /vapi/end-of-call
# ══════════════════════════════════════════════════════════════════════════════

def end_of_call_payload(accepted: bool = True, **overrides) -> dict:
    structured = {
        "caller_name": "Sarah Jones",
        "caller_phone": "07700900123",
        "caller_email": "sarah@example.com",
        "pickup_address": "1 Oxford Street, London",
        "dropoff_address": "Canary Wharf, London",
        "weight_kg": 350,
        "date": "2026-09-15",
        "time": "10:00",
        "quote_gbp": 38.58,
        "booking_accepted": accepted,
    }
    structured.update(overrides)
    return {
        "message": {
            "type": "end-of-call-report",
            "call": {"id": "call_eoc_1", "customer": {"number": "+447700900123"}},
            "endedReason": "customer-ended-call",
            "durationSeconds": 142.5,
            "summary": "Customer accepted the quote.",
            "transcript": "AI: ... User: yes please",
            "analysis": {"structuredData": structured},
        }
    }


def test_end_of_call_extracts_booking_data(client):
    body = client.post("/vapi/end-of-call", json=end_of_call_payload(True)).json()

    assert body["call_status"] == "booking_accepted"
    assert body["duration_seconds"] == 142.5

    booking = body["booking_data"]
    assert booking["caller_name"] == "Sarah Jones"
    assert booking["weight_kg"] == 350.0
    assert booking["date"] == "2026-09-15"
    assert booking["quote_gbp"] == 38.58


def test_end_of_call_marks_declined_calls(client):
    body = client.post("/vapi/end-of-call", json=end_of_call_payload(False)).json()
    assert body["call_status"] == "no_booking"


def test_end_of_call_writes_jsonl_log(client):
    from api import main
    import json

    client.post("/vapi/end-of-call", json=end_of_call_payload(True))

    record = json.loads(main.config.CALLS_LOG.read_text(encoding="utf-8").strip())
    assert record["call_id"] == "call_eoc_1"
    assert record["ended_reason"] == "customer-ended-call"
    assert record["booking_accepted"] is True
    assert record["transcript"]


def test_end_of_call_without_structured_data(client):
    """Assistants with no structured-data schema must not crash the handler."""
    body = client.post("/vapi/end-of-call", json={
        "message": {"type": "end-of-call-report", "call": {"id": "c9"},
                    "endedReason": "customer-did-not-give-microphone-permission"}
    }).json()

    assert body["ok"] is True
    assert body["call_status"] == "no_booking"


def test_duration_computed_from_timestamps(client):
    """When Vapi omits durationSeconds we work it out from the timestamps."""
    body = client.post("/vapi/end-of-call", json={
        "message": {
            "type": "end-of-call-report", "call": {"id": "c10"},
            "startedAt": "2026-09-15T10:00:00.000Z",
            "endedAt": "2026-09-15T10:03:30.000Z",
        }
    }).json()
    assert body["duration_seconds"] == 210.0


# ══════════════════════════════════════════════════════════════════════════════
#  Automatic booking creation at end-of-call
#
#  This is what used to be n8n's job: check the call was accepted, and if so
#  create the booking. It now happens in-process inside /vapi/end-of-call
#  itself (see _auto_create_booking() in api/main.py) - one call ending
#  should produce exactly one booking, with no separate trigger needed.
# ══════════════════════════════════════════════════════════════════════════════

def test_accepted_call_creates_a_real_booking(client, no_external_calls):
    """The single most important behaviour of this whole feature: a call
    that ends accepted, with full data, results in an actual booking -
    calendar, sheet, SMS and both emails - with no separate step required."""
    body = client.post("/vapi/end-of-call", json=end_of_call_payload(True)).json()

    outcome = body["booking_outcome"]
    assert outcome["ok"] is True
    assert outcome["attempted"] is True
    assert booking_ref.is_valid_reference(outcome["reference"])

    # And the integrations were genuinely called, not just reported as ok.
    assert len(no_external_calls["calendar"]) == 1
    assert len(no_external_calls["sheet"]) == 1
    assert len(no_external_calls["sms"]) == 1
    assert len(no_external_calls["email"]) == 2


def test_declined_call_never_attempts_a_booking(client, no_external_calls):
    """The caller saying no must not create anything, ever."""
    body = client.post("/vapi/end-of-call", json=end_of_call_payload(False)).json()

    outcome = body["booking_outcome"]
    assert outcome["attempted"] is False
    assert no_external_calls["calendar"] == []
    assert no_external_calls["sheet"] == []


@pytest.mark.parametrize("missing_field,bad_value", [
    ("pickup_address", ""),
    ("dropoff_address", ""),
    ("weight_kg", 0),
    ("quote_gbp", 0),
])
def test_accepted_but_incomplete_data_alerts_instead_of_booking(
    client, no_external_calls, missing_field, bad_value
):
    """The AI can mark booking_accepted=True on data that isn't actually
    usable - a field it failed to capture, or a quote of zero suggesting
    get_quote never really ran. That must never silently create a broken
    booking; it must alert the client so a human can follow up by hand."""
    payload = end_of_call_payload(True, **{missing_field: bad_value})
    body = client.post("/vapi/end-of-call", json=payload).json()

    outcome = body["booking_outcome"]
    assert outcome["ok"] is False
    assert outcome["attempted"] is True
    assert no_external_calls["calendar"] == []          # nothing was booked

    # The client was told, by email, so nothing goes missing silently.
    alerts = [e for e in no_external_calls["email"] if "ACTION NEEDED" in e["subject"]]
    assert len(alerts) == 1


def test_over_capacity_never_reaches_auto_booking(client, no_external_calls):
    """Belt and braces: even if somehow marked accepted, a >790kg job must
    never be auto-booked. In practice /vapi/quote already blocks this earlier
    in the call, but create_booking() itself also enforces the limit."""
    payload = end_of_call_payload(True, weight_kg=900)
    body = client.post("/vapi/end-of-call", json=payload).json()

    outcome = body["booking_outcome"]
    assert outcome["ok"] is False
    assert "790" in outcome["error"] or "exceeds" in outcome["error"]
    assert no_external_calls["calendar"] == []


# ══════════════════════════════════════════════════════════════════════════════
#  /vapi/webhook — the master router
# ══════════════════════════════════════════════════════════════════════════════

def test_webhook_routes_tool_call_to_quote(client):
    body = client.post("/vapi/webhook", json=tool_call_payload("get_quote", QUOTE_ARGS)).json()
    assert body["action"] == "quote"


def test_webhook_routes_transfer_by_function_name(client):
    body = client.post("/vapi/webhook", json=tool_call_payload(
        "transfer_to_human", {"reason": "human_requested"})).json()
    assert body["action"] == "transfer"


def test_webhook_routes_end_of_call(client):
    body = client.post("/vapi/webhook", json=end_of_call_payload(True)).json()
    assert body["call_status"] == "booking_accepted"


def test_webhook_answers_transfer_destination_request(client):
    body = client.post("/vapi/webhook", json={
        "message": {"type": "transfer-destination-request", "call": {"id": "c11"}}
    }).json()
    assert body["destination"]["type"] == "number"


def test_webhook_acknowledges_status_updates(client):
    body = client.post("/vapi/webhook", json={
        "message": {"type": "status-update", "status": "in-progress", "call": {"id": "c12"}}
    }).json()
    assert body == {"ok": True, "received": "status-update"}


def test_webhook_acknowledges_unknown_event_types(client):
    """Unknown types get a 200 so Vapi does not retry them forever."""
    response = client.post("/vapi/webhook", json={"message": {"type": "speech-update"}})
    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_webhook_rejects_bad_secret(client, monkeypatch):
    """With a secret configured, an unsigned request is refused."""
    from api import main

    monkeypatch.setattr(main.config, "VAPI_SERVER_SECRET", "s3cret")

    unsigned = client.post("/vapi/webhook", json=tool_call_payload("get_quote", QUOTE_ARGS))
    assert unsigned.status_code == 401

    signed = client.post("/vapi/webhook",
                         json=tool_call_payload("get_quote", QUOTE_ARGS),
                         headers={"x-vapi-secret": "s3cret"})
    assert signed.status_code == 200
