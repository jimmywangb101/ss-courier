"""
test_admin_actions.py — cancelling a booking from the dashboard.

This is the only endpoint in the system that changes a booking after the
customer has been confirmed, so what matters is less the happy path and more
what must never happen: no second cancellation text when someone double-clicks,
no failure to free the calendar slot, and nothing reachable without the admin
password.

Every external service is mocked. Run with:
    ./venv/Scripts/python.exe -m pytest tests/ -q
"""

from __future__ import annotations

import pytest

from conftest import FUTURE_ISO, admin_headers
from api import config

BOOKING = {
    "reference": "CRR-20261015-K7Q4",
    "status": "confirmed",
    "caller_name": "Sarah Jones",
    "caller_phone": "+447700900123",
    "caller_email": "sarah@example.com",
    "pickup_address": "1 Oxford Street, London, W1D 1BS",
    "dropoff_address": "Canary Wharf, London, E14 5AB",
    "weight_kg": "350",
    "distance_miles": "9.43",
    "quote_gbp": "28.29",
    "service_date": FUTURE_ISO,
    "service_time": "10:00",
    "calcom_uid": "cal_uid_123",
    "call_id": "call_test_1",
    "notes": "",
}


@pytest.fixture
def sheet(monkeypatch):
    """A fake one-row sheet that records every update applied to it."""
    from api.services import sheets

    state = {"booking": dict(BOOKING), "updates": []}

    async def fake_find(reference):
        return dict(state["booking"]) if reference == state["booking"]["reference"] else None

    async def fake_update(reference, updates):
        state["updates"].append(dict(updates))
        state["booking"].update(updates)
        return {"ok": True, "row": 2, "booking": dict(state["booking"])}

    monkeypatch.setattr(sheets, "find_booking", fake_find)
    monkeypatch.setattr(sheets, "update_booking", fake_update)
    return state


@pytest.fixture
def calendar(monkeypatch):
    """Records what the calendar was asked to do."""
    from api.services import calcom

    state = {"cancelled": []}

    async def fake_cancel(uid, reason="Cancelled by operator"):
        state["cancelled"].append(uid)
        return {"ok": True, "booking_uid": uid}

    monkeypatch.setattr(calcom, "cancel_booking", fake_cancel)
    return state


# ══════════════════════════════════════════════════════════════════════════════
#  Authentication
# ══════════════════════════════════════════════════════════════════════════════

def test_cancel_requires_the_admin_password(client):
    """This cancels a live customer booking. It must never be open."""
    assert client.post("/admin/bookings/CRR-20261015-K7Q4/cancel").status_code == 401


# ══════════════════════════════════════════════════════════════════════════════
#  Cancelling
# ══════════════════════════════════════════════════════════════════════════════

def test_cancel_frees_the_calendar_marks_the_sheet_and_texts_the_customer(
        client, sheet, calendar, no_external_calls):
    r = client.post(f"/admin/bookings/{BOOKING['reference']}/cancel", headers=admin_headers())
    assert r.status_code == 200

    body = r.json()
    assert body["ok"] is True
    assert calendar["cancelled"] == ["cal_uid_123"]
    assert sheet["updates"] == [{"status": "cancelled"}]

    text = no_external_calls["sms"][0]
    assert text["to"] == BOOKING["caller_phone"]
    assert BOOKING["reference"] in text["body"]
    assert "cancelled" in text["body"].lower()


def test_cancelling_twice_is_harmless(client, sheet, calendar, no_external_calls):
    """A double click on the dashboard must not send two cancellation texts."""
    client.post(f"/admin/bookings/{BOOKING['reference']}/cancel", headers=admin_headers())
    second = client.post(f"/admin/bookings/{BOOKING['reference']}/cancel", headers=admin_headers())

    assert second.status_code == 200
    assert second.json()["already_cancelled"] is True
    assert len(no_external_calls["sms"]) == 1
    assert len(calendar["cancelled"]) == 1


def test_cancel_can_skip_telling_the_customer(client, sheet, calendar, no_external_calls):
    r = client.post(f"/admin/bookings/{BOOKING['reference']}/cancel?notify=false",
                    headers=admin_headers())
    assert r.status_code == 200
    assert r.json()["steps"]["sms"]["skipped"] is True
    assert no_external_calls["sms"] == []


def test_cancel_still_marks_the_sheet_when_there_is_no_calendar_entry(
        client, sheet, calendar, no_external_calls):
    sheet["booking"]["calcom_uid"] = ""
    r = client.post(f"/admin/bookings/{BOOKING['reference']}/cancel", headers=admin_headers())

    assert r.status_code == 200
    assert calendar["cancelled"] == []
    assert sheet["booking"]["status"] == "cancelled"


def test_cancel_unknown_reference_is_404(client, sheet):
    r = client.post("/admin/bookings/CRR-20261015-AAAA/cancel", headers=admin_headers())
    assert r.status_code == 404


def test_cancel_malformed_reference_is_400(client, sheet):
    r = client.post("/admin/bookings/not-a-reference/cancel", headers=admin_headers())
    assert r.status_code == 400
