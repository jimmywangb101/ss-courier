"""
conftest.py — shared pytest setup.

Two jobs:
  1. Put the project root on sys.path so `from api import main` works when you
     run pytest from anywhere.
  2. Block every real external call. Tests must never send a real SMS, create a
     real calendar entry or spend money on the Google Maps API. The
     `no_external_calls` fixture below is autouse, so it applies to every test
     automatically — you cannot forget it.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from api import main  # noqa: E402
from api.services import calcom, email_sender, sheets, twilio_sms  # noqa: E402


# ── Fake distance so tests are deterministic and free ─────────────────────────

FAKE_DISTANCE_MILES = 9.43

# The autouse fixture below replaces the real integration functions with fakes.
# A few tests need to exercise the REAL implementation (e.g. checking the TwiML
# a transfer builds), so we keep references to the originals here before any
# patching happens. Import this dict and call through it to bypass the mocks.
ORIGINALS = {
    "send_sms": twilio_sms.send_sms,
    "transfer_call": twilio_sms.transfer_call,
}


@pytest.fixture(autouse=True)
def no_external_calls(monkeypatch, tmp_path):
    """Replace every outbound integration with an in-memory fake.

    `autouse=True` means pytest applies this to every test without it being
    requested. The `calls` dict it returns lets a test assert what WOULD have
    been sent.
    """
    calls: dict[str, list] = {"sms": [], "email": [], "calendar": [], "sheet": []}

    async def fake_distance(origin: str, destination: str) -> float:
        return FAKE_DISTANCE_MILES

    async def fake_send_sms(to_number: str, body: str) -> dict:
        calls["sms"].append({"to": to_number, "body": body})
        return {"ok": True, "sid": "SMtest123", "to": to_number}

    async def fake_send_email(to, subject, text_body, html_body=None) -> dict:
        calls["email"].append({"to": to, "subject": subject, "text": text_body})
        return {"ok": True, "to": [to] if isinstance(to, str) else to}

    async def fake_create_booking(**kwargs) -> dict:
        calls["calendar"].append(kwargs)
        return {"ok": True, "booking_uid": "cal_test_uid", "start_utc": "2026-09-15T09:00:00.000Z"}

    async def fake_check_availability(date_str: str, time_str: str) -> dict:
        return {"available": True, "assumed": False, "next_available": time_str,
                "free_slots": ["09:00", "10:00", "11:00"]}

    async def fake_append_booking(record: dict) -> dict:
        calls["sheet"].append(record)
        return {"ok": True, "updated_range": "Bookings!A2:P2", "local": True}

    async def fake_list_bookings(limit: int = 50) -> list[dict]:
        return list(reversed(calls["sheet"]))[:limit]

    async def fake_transfer_call(call_sid: str, to_number=None, whisper=None) -> dict:
        calls.setdefault("transfer", []).append({"call_sid": call_sid, "to": to_number})
        return {"ok": True, "call_sid": call_sid, "transferred_to": to_number}

    monkeypatch.setattr(main, "get_distance_miles", fake_distance)
    monkeypatch.setattr(twilio_sms, "send_sms", fake_send_sms)
    monkeypatch.setattr(twilio_sms, "transfer_call", fake_transfer_call)
    monkeypatch.setattr(email_sender, "send_email", fake_send_email)
    monkeypatch.setattr(calcom, "create_booking", fake_create_booking)
    monkeypatch.setattr(calcom, "check_availability", fake_check_availability)
    monkeypatch.setattr(sheets, "append_booking", fake_append_booking)
    monkeypatch.setattr(sheets, "list_bookings", fake_list_bookings)

    # Write log files into a temp folder so tests never pollute logs/.
    monkeypatch.setattr(main.config, "CALLS_LOG", tmp_path / "calls.jsonl")
    monkeypatch.setattr(main.config, "TRANSFERS_LOG", tmp_path / "transfers.jsonl")
    monkeypatch.setattr(main.config, "BOOKINGS_LOG", tmp_path / "bookings.jsonl")

    # Tests must not depend on what happens to be in .env today.
    # Once a real VAPI_SERVER_SECRET was added, /vapi/webhook started (correctly)
    # rejecting the unsigned requests these tests send, and six of them broke
    # even though nothing was wrong with the app. Pinning the secret to empty
    # here keeps the suite hermetic; the one test that cares about the secret
    # sets its own value with monkeypatch.
    monkeypatch.setattr(main.config, "VAPI_SERVER_SECRET", "")

    return calls


@pytest.fixture
def client():
    """A FastAPI test client. Imported lazily so conftest patches land first."""
    from fastapi.testclient import TestClient

    return TestClient(main.app)


# ── Payload builders (keep the tests readable) ────────────────────────────────

def tool_call_payload(name: str, arguments: dict, call_id: str = "call_test_1",
                      tool_call_id: str = "tool_1") -> dict:
    """A modern Vapi 'tool-calls' event."""
    return {
        "message": {
            "type": "tool-calls",
            "call": {"id": call_id, "customer": {"number": "+447700900123"}},
            "toolCalls": [
                {"id": tool_call_id, "type": "function",
                 "function": {"name": name, "arguments": arguments}}
            ],
        }
    }


def legacy_call_payload(name: str, parameters: dict, call_id: str = "call_test_2") -> dict:
    """The older Vapi 'function-call' event, still sent by some assistants."""
    return {
        "message": {
            "type": "function-call",
            "call": {"id": call_id},
            "functionCall": {"name": name, "parameters": parameters},
        }
    }
