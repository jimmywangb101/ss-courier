"""
test_regressions.py — cover for faults that actually reached production.

Every test in here exists because something broke on a real call or a real
deploy, not because a code path looked risky. Each one names the failure it
prevents, so a future change that reintroduces it fails loudly rather than
quietly shipping the same bug twice.

Run with:  ./venv/Scripts/python.exe -m pytest tests/ -v
"""

from __future__ import annotations

import asyncio
from datetime import date

import pytest

from conftest import ORIGINALS
from api import config, utils
from test_booking import VALID_BOOKING


# ══════════════════════════════════════════════════════════════════════════════
#  Date normalisation
# ══════════════════════════════════════════════════════════════════════════════
#
#  THE FAILURE (live call, 10 September 2026)
#  The caller said "next Tuesday". The agent correctly read back "Tuesday the
#  15th of September". Vapi's structured-data extraction then handed us
#  "2023-09-15" — three years in the past.
#
#  normalise_date() returned already-ISO input untouched, and the roll-forward
#  in _safe_date() only triggered when the date's year already matched the
#  current year, so a wrong YEAR passed straight through in every format. The
#  booking was written to the spreadsheet dated 2023, the customer was texted
#  that date, and Cal.com silently refused to create the calendar entry at all,
#  because you cannot book a slot in the past.

@pytest.mark.parametrize("given", [
    "2023-09-15",   # ISO with a wrong year — the exact production failure
    "15/09/2023",   # the same mistake in UK numeric form
    "15-9-23",      # ...and in shorthand
])
def test_past_date_rolls_forward_to_the_next_occurrence(given):
    """Whatever format it arrives in, a date that has already gone must not
    survive contact with normalise_date()."""
    assert utils.normalise_date(given, today=date(2026, 9, 10)) == "2026-09-15"


def test_iso_dates_are_not_waved_through():
    """The specific hole, worth a test of its own.

    ISO input used to be returned verbatim on the assumption that anything
    already well-formed was already correct. Well-formed and correct are not
    the same thing when an LLM produced the string.
    """
    today = date(2026, 9, 10)
    assert utils.normalise_date("2020-01-01", today=today) != "2020-01-01"
    assert utils.normalise_date("2020-01-01", today=today) == "2027-01-01"


@pytest.mark.parametrize("given", ["2026-09-15", "2026-12-25", "2027-01-05", "2030-06-01"])
def test_genuine_future_dates_are_left_exactly_as_given(given):
    """The fix must not "correct" dates that were already right."""
    assert utils.normalise_date(given, today=date(2026, 9, 10)) == given


def test_today_is_still_bookable():
    """This is a SAME-DAY courier. Today must not roll forward a year."""
    assert utils.normalise_date("2026-09-10", today=date(2026, 9, 10)) == "2026-09-10"


def test_year_end_wrap_still_works():
    """The behaviour the old code did get right, kept: "the 3rd of January",
    said in December, means next January."""
    assert utils.normalise_date("3 January", today=date(2026, 12, 20)) == "2027-01-03"


def test_impossible_leap_day_degrades_safely():
    """29 February in a non-leap year must not crash, and must not produce a
    date in the past.

    It deliberately does NOT hunt forward for the next real leap day: from
    March 2026 that would be 2028, and a same-day courier booking two years
    out is a worse answer than the documented fallback. So this lands on
    today, exactly like any other input that cannot be read - and the agent
    reads the date back to the caller, which is where a mis-heard date is
    meant to be caught.
    """
    today = date(2026, 3, 1)  # neither 2026 nor 2027 has a 29 February
    result = utils.normalise_date("2024-02-29", today=today)

    assert result == today.isoformat()
    assert date.fromisoformat(result) >= today, "must never resolve into the past"


def test_a_real_leap_day_is_kept():
    """A 29 February that genuinely exists and is still ahead of us is left
    alone."""
    assert utils.normalise_date("2028-02-29", today=date(2026, 3, 1)) == "2028-02-29"


def test_a_rolled_date_still_produces_a_bookable_reference(client):
    """End to end: a past date from the AI must yield a booking on a real,
    future service date — which is what Cal.com rejected last time."""
    response = client.post("/booking/create",
                           json={**VALID_BOOKING, "date": "2023-09-15"})
    assert response.status_code == 201

    reference = response.json()["reference"]
    booked_year = int(reference.split("-")[1][:4])
    assert booked_year >= date.today().year
    assert "2023" not in reference


# ══════════════════════════════════════════════════════════════════════════════
#  A booking that is not on the calendar must not be silent
# ══════════════════════════════════════════════════════════════════════════════
#
#  Same incident. Cal.com refused the booking, /booking/create still returned
#  ok: True, and nothing anywhere said the calendar entry was missing. The job
#  existed in the spreadsheet, in the customer's inbox and in their texts — but
#  not in the calendar the driver actually works from.

def test_failed_calendar_alerts_the_client(client, no_external_calls, monkeypatch):
    from api.services import calcom

    async def calendar_rejects(**kwargs):
        return {"ok": False, "error": "no_available_users_found_error"}

    monkeypatch.setattr(calcom, "create_booking", calendar_rejects)

    response = client.post("/booking/create", json=VALID_BOOKING)
    assert response.status_code == 201

    # The booking itself still stands — the customer keeps their confirmation.
    body = response.json()
    assert body["ok"] is True
    assert body["steps"]["calendar"]["ok"] is False
    assert body["steps"]["calendar_alert"]["client_notified"] is True

    alerts = [e for e in no_external_calls["email"] if "ACTION NEEDED" in e["subject"]]
    assert len(alerts) == 1
    assert alerts[0]["to"] == config.CLIENT_EMAIL
    assert "NOT on the calendar" in alerts[0]["text"]
    # The alert has to carry enough detail to rescue the job by hand.
    assert body["reference"] in alerts[0]["text"]
    assert "no_available_users_found_error" in alerts[0]["text"]


def test_unconfigured_calendar_does_not_email_on_every_booking(
        client, no_external_calls, monkeypatch):
    """Cal.com not being set up is a known state, not an incident. Alerting on
    it would train the client to ignore these emails — which is how a real one
    gets missed."""
    from api.services import calcom

    async def calendar_skipped(**kwargs):
        return {"ok": False, "skipped": True, "error": "calcom_not_configured"}

    monkeypatch.setattr(calcom, "create_booking", calendar_skipped)
    client.post("/booking/create", json=VALID_BOOKING)

    assert not [e for e in no_external_calls["email"] if "ACTION NEEDED" in e["subject"]]


def test_successful_calendar_raises_no_alert(client, no_external_calls):
    client.post("/booking/create", json=VALID_BOOKING)
    assert not [e for e in no_external_calls["email"] if "ACTION NEEDED" in e["subject"]]


# ══════════════════════════════════════════════════════════════════════════════
#  Spreadsheet write format
# ══════════════════════════════════════════════════════════════════════════════

def test_sheet_write_preserves_the_leading_plus_on_phone_numbers(monkeypatch):
    """Phone numbers must reach the sheet as +447367312558, not 447367312558.

    Sheets' USER_ENTERED mode parses every cell as though a person had typed
    it, and a leading "+" starts a formula — so it was silently dropping the
    country code from the one field an operator rings back on.
    """
    from api.services import sheets

    captured: dict = {}

    class _Response:
        status_code = 200

        @staticmethod
        def json():
            return {"updates": {"updatedRange": "Bookings!A2:P2"}}

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, params=None, headers=None, json=None):
            captured["params"] = params
            captured["row"] = json["values"][0]
            return _Response()

    monkeypatch.setattr(config, "SHEETS_ENABLED", True)
    monkeypatch.setattr(sheets.httpx, "AsyncClient", _Client)

    async def token():
        return "fake-token"

    monkeypatch.setattr(sheets, "_get_token", token)

    result = asyncio.run(ORIGINALS["append_booking"]({
        "reference": "CRR-20260915-AAAA",
        "caller_phone": "+447367312558",
    }))

    assert result["ok"] is True
    assert captured["params"]["valueInputOption"] == "RAW"

    phone = captured["row"][sheets.HEADERS.index("caller_phone")]
    assert phone == "+447367312558"
    assert phone.startswith("+"), "the country code was stripped again"
