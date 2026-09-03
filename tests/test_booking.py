"""
test_booking.py — tests for booking creation and the admin endpoints.

Every external service is mocked by the autouse fixture in conftest.py, so
these tests are fast, free and safe to run offline.

Run with:  ./venv/Scripts/python.exe -m pytest tests/ -v
"""

from __future__ import annotations

import pytest

from conftest import ORIGINALS
from api.services import booking_ref

VALID_BOOKING = {
    "caller_name": "Sarah Jones",
    "caller_phone": "07700900123",
    "caller_email": "sarah@example.com",
    "pickup_address": "1 Oxford Street, London, W1D 1BS",
    "dropoff_address": "Canary Wharf, London, E14 5AB",
    "weight_kg": 350,
    "date": "2026-09-15",
    "time": "10:00",
    "quote_gbp": 38.58,
    "distance_miles": 9.43,
    "call_id": "call_test_1",
}


# ══════════════════════════════════════════════════════════════════════════════
#  POST /booking/create
# ══════════════════════════════════════════════════════════════════════════════

def test_create_booking_runs_every_step(client, no_external_calls):
    response = client.post("/booking/create", json=VALID_BOOKING)
    assert response.status_code == 201

    body = response.json()
    assert body["ok"] is True
    assert booking_ref.is_valid_reference(body["reference"])

    # All five steps succeeded.
    for step in ("calendar", "spreadsheet", "sms", "customer_email", "client_email"):
        assert body["steps"][step]["ok"] is True, f"{step} did not succeed"

    # And each integration actually received something.
    assert len(no_external_calls["calendar"]) == 1
    assert len(no_external_calls["sheet"]) == 1
    assert len(no_external_calls["sms"]) == 1
    assert len(no_external_calls["email"]) == 2  # customer + client


def test_booking_reference_format_and_uniqueness(client):
    """References embed the SERVICE date, and never repeat."""
    references = {
        client.post("/booking/create", json=VALID_BOOKING).json()["reference"]
        for _ in range(20)
    }
    assert len(references) == 20
    for reference in references:
        assert reference.startswith("CRR-20260915-")


def test_sms_content_is_useful(client, no_external_calls):
    body = client.post("/booking/create", json=VALID_BOOKING).json()
    sms = no_external_calls["sms"][0]

    assert sms["to"] == "+447700900123"          # normalised to E.164
    assert body["reference"] in sms["body"]
    assert "38.58" in sms["body"]
    assert "2026-09-15" in sms["body"]


def test_both_emails_go_to_the_right_people(client, no_external_calls):
    from api import config

    body = client.post("/booking/create", json=VALID_BOOKING).json()
    recipients = {email["to"] for email in no_external_calls["email"]}

    assert "sarah@example.com" in recipients
    assert config.CLIENT_EMAIL in recipients

    subjects = " ".join(email["subject"] for email in no_external_calls["email"])
    assert body["reference"] in subjects
    assert "NEW BOOKING" in subjects  # the client's copy is clearly flagged


def test_spreadsheet_row_has_every_column(client, no_external_calls):
    from api.services import sheets

    client.post("/booking/create", json=VALID_BOOKING)
    row = no_external_calls["sheet"][0]

    for column in sheets.HEADERS:
        assert column in row, f"missing column {column}"
    assert row["status"] == "confirmed"
    assert row["calcom_uid"] == "cal_test_uid"


def test_spoken_reference_is_read_out_clearly(client):
    """The message read to the caller spaces out the reference characters."""
    body = client.post("/booking/create", json=VALID_BOOKING).json()
    assert "C R R" in body["message"]


@pytest.mark.parametrize("weight", [790.01, 900, 1500])
def test_over_capacity_booking_is_refused(client, weight, no_external_calls):
    """The capacity rule is enforced here too, not just in the voice flow."""
    response = client.post("/booking/create", json={**VALID_BOOKING, "weight_kg": weight})

    assert response.status_code == 400
    assert "exceeds" in response.json()["detail"]
    assert no_external_calls["calendar"] == []  # nothing was booked


@pytest.mark.parametrize("weight", [0, -5])
def test_invalid_weight_is_rejected_by_validation(client, weight):
    """Pydantic enforces weight_kg > 0 before our code even runs."""
    response = client.post("/booking/create", json={**VALID_BOOKING, "weight_kg": weight})
    assert response.status_code == 422


def test_messy_date_and_time_are_normalised(client, no_external_calls):
    client.post("/booking/create", json={
        **VALID_BOOKING, "date": "15/09/2026", "time": "half past two"})

    row = no_external_calls["sheet"][0]
    assert row["service_date"] == "2026-09-15"
    assert row["service_time"] == "14:30"


def test_one_failing_step_does_not_lose_the_booking(client, monkeypatch):
    """If Twilio is down the booking still completes; the response says so.

    This is the single most important behaviour in the file. A failed text
    message must never cost the client a confirmed job.
    """
    from api.services import twilio_sms

    async def failing_sms(to_number, body):
        return {"ok": False, "error": "twilio is down"}

    monkeypatch.setattr(twilio_sms, "send_sms", failing_sms)

    body = client.post("/booking/create", json=VALID_BOOKING).json()

    assert body["ok"] is True
    assert body["steps"]["sms"]["ok"] is False
    assert body["steps"]["sms"]["error"] == "twilio is down"
    assert body["steps"]["calendar"]["ok"] is True   # the rest still ran


def test_an_exception_in_one_step_is_contained(client, monkeypatch):
    """Even an unexpected crash inside a step cannot 500 the whole booking."""
    from api.services import sheets

    async def exploding_append(record):
        raise RuntimeError("disk on fire")

    monkeypatch.setattr(sheets, "append_booking", exploding_append)

    response = client.post("/booking/create", json=VALID_BOOKING)
    assert response.status_code == 201
    assert response.json()["steps"]["spreadsheet"]["ok"] is False
    assert "disk on fire" in response.json()["steps"]["spreadsheet"]["error"]


# ══════════════════════════════════════════════════════════════════════════════
#  POST /booking/check-availability
# ══════════════════════════════════════════════════════════════════════════════

def test_check_availability_free_slot(client):
    body = client.post("/booking/check-availability",
                       json={"date": "2026-09-15", "time": "10:00"}).json()
    assert body["available"] is True
    assert body["assumed"] is False
    assert body["date"] == "2026-09-15"


def test_check_availability_busy_slot(client, monkeypatch):
    from api.services import calcom

    async def busy(date_str, time_str):
        return {"available": False, "assumed": False, "next_available": "13:00",
                "free_slots": ["13:00", "14:00"]}

    monkeypatch.setattr(calcom, "check_availability", busy)

    body = client.post("/booking/check-availability",
                       json={"date": "2026-09-15", "time": "10:00"}).json()
    assert body["available"] is False
    assert body["next_available"] == "13:00"


def test_availability_fails_open_when_calcom_is_down(client, monkeypatch):
    """A Cal.com outage must not tell real customers we are fully booked."""
    from api.services import calcom

    async def down(date_str, time_str):
        return {"available": True, "assumed": True, "next_available": None,
                "error": "network_error"}

    monkeypatch.setattr(calcom, "check_availability", down)

    body = client.post("/booking/check-availability",
                       json={"date": "2026-09-15", "time": "10:00"}).json()
    assert body["available"] is True
    assert body["assumed"] is True  # flagged as unverified


# ══════════════════════════════════════════════════════════════════════════════
#  GET /booking/{reference}
# ══════════════════════════════════════════════════════════════════════════════

def test_lookup_existing_booking(client):
    reference = client.post("/booking/create", json=VALID_BOOKING).json()["reference"]

    body = client.get(f"/booking/{reference}").json()
    assert body["ok"] is True
    assert body["booking"]["caller_name"] == "Sarah Jones"


def test_lookup_is_case_and_space_insensitive(client):
    """Callers read references back untidily; we should still find them."""
    reference = client.post("/booking/create", json=VALID_BOOKING).json()["reference"]
    messy = reference.lower().replace("-", " ")

    assert client.get(f"/booking/{messy}").status_code == 200


@pytest.mark.parametrize("bad", ["NOTAREF", "12345", "ABC-20260915-XXXX"])
def test_malformed_reference_gives_400(client, bad):
    assert client.get(f"/booking/{bad}").status_code == 400


def test_unknown_reference_gives_404(client):
    assert client.get("/booking/CRR-20260915-QQQQ").status_code == 404


# ══════════════════════════════════════════════════════════════════════════════
#  POST /booking/alert-failure
# ══════════════════════════════════════════════════════════════════════════════

def test_failure_alert_emails_the_client(client, no_external_calls):
    from api import config

    body = client.post("/booking/alert-failure", json={
        "reason": "Cal.com returned 500",
        "details": {"caller_name": "Sarah", "caller_phone": "07700900123"},
    }).json()

    assert body["ok"] is True and body["alert_sent"] is True
    alert = no_external_calls["email"][0]
    assert alert["to"] == config.CLIENT_EMAIL
    assert "ACTION NEEDED" in alert["subject"]
    assert "Cal.com returned 500" in alert["text"]


# ══════════════════════════════════════════════════════════════════════════════
#  Admin
# ══════════════════════════════════════════════════════════════════════════════

def test_admin_bookings_lists_newest_first(client):
    first = client.post("/booking/create", json=VALID_BOOKING).json()["reference"]
    second = client.post("/booking/create",
                         json={**VALID_BOOKING, "caller_name": "Tom"}).json()["reference"]

    body = client.get("/admin/bookings").json()
    assert body["count"] == 2
    assert body["bookings"][0]["reference"] == second  # newest first
    assert body["bookings"][1]["reference"] == first


def test_admin_bookings_respects_limit(client):
    for _ in range(5):
        client.post("/booking/create", json=VALID_BOOKING)

    assert client.get("/admin/bookings?limit=3").json()["count"] == 3


def test_admin_bookings_source_reflects_what_actually_happened(client, monkeypatch):
    """"source" must describe the path THIS call took, not just whether
    Sheets is configured.

    Caught in production: Sheets was fully configured, but a call landed
    while the sheet had fewer than 2 rows in it (recently cleared of test
    data), so list_bookings() correctly fell back to the local file - and the
    endpoint still reported "google_sheets", because it was reading a static
    config flag instead of what list_bookings() actually returned.
    """
    from api import config
    from api.services import sheets

    async def fell_back_to_local(limit: int = 50):
        return [{"reference": "CRR-LOCAL-ONLY"}], "local_log"

    monkeypatch.setattr(config, "SHEETS_ENABLED", True)   # configured...
    monkeypatch.setattr(sheets, "list_bookings", fell_back_to_local)  # ...but this call fell back

    body = client.get("/admin/bookings").json()
    assert body["source"] == "local_log"


def test_admin_dashboard_renders(client):
    response = client.get("/admin")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Courier bookings" in response.text
    # The page must escape call data before rendering it.
    assert "function esc(" in response.text


# ══════════════════════════════════════════════════════════════════════════════
#  booking_ref unit tests
# ══════════════════════════════════════════════════════════════════════════════

def test_reference_uses_unambiguous_characters():
    """No 0/O/1/I/5/S — those get misheard when read down the phone."""
    suffixes = [booking_ref.generate_reference("2026-09-15")[-4:] for _ in range(300)]
    assert not set("".join(suffixes)) & set("O0I1L5S2Z")


def test_reference_validation():
    assert booking_ref.is_valid_reference("CRR-20260915-K7Q4")
    assert not booking_ref.is_valid_reference("CRR-20260915-K7Q")   # too short
    assert not booking_ref.is_valid_reference("XXX-20260915-K7Q4")  # wrong prefix
    assert not booking_ref.is_valid_reference("")


def test_reference_normalisation():
    assert booking_ref.normalise_reference("crr 20260915 k7q4") == "CRR-20260915-K7Q4"
    assert booking_ref.normalise_reference("CRR20260915K7Q4") == "CRR-20260915-K7Q4"


@pytest.mark.parametrize("given,expected", [
    ("+4407367312558", "+447367312558"),   # trunk zero kept after +44
    ("07367 312558",   "+447367312558"),   # national format
    ("+447367312558",  "+447367312558"),   # already correct
    ("00447367312558", "+447367312558"),   # international access code
    ("7367312558",     "+447367312558"),   # bare mobile
    ("(07367) 312-558", "+447367312558"),  # punctuation
    ("",               ""),
])
def test_uk_number_normalisation(given, expected):
    """UK numbers must reach Twilio as E.164.

    The trunk-zero case is the one that bit us in practice: the client supplied
    +4407367312558, keeping the national leading 0 after the country code. That
    is one digit too long and Twilio rejects it outright, but it looks correct
    at a glance, so it must be normalised rather than passed through.
    """
    from api.services.twilio_sms import normalise_uk_number

    assert normalise_uk_number(given) == expected


# ══════════════════════════════════════════════════════════════════════════════
#  Alphanumeric sender ID ("SSCourier")
# ══════════════════════════════════════════════════════════════════════════════

def test_sender_id_validation():
    from api.services.twilio_sms import is_phone_number, sender_id_problem

    assert is_phone_number("+447367312558")
    assert not is_phone_number("SSCourier")

    assert sender_id_problem("SSCourier") is None
    assert sender_id_problem("+447367312558") is None
    assert "11" in sender_id_problem("WayTooLongName")       # over length
    assert "letters" in sender_id_problem("SS-Courier")      # bad character
    assert "letter" in sender_id_problem("12345")            # digits only


def test_transfer_omits_callerid_for_alphanumeric_sender(monkeypatch):
    """A sender ID is legal for SMS but ILLEGAL as a TwiML callerId.

    Leaving "SSCourier" in callerId makes Twilio reject the whole TwiML and the
    transfer fails silently mid-call, so the attribute must be dropped.
    """
    import asyncio

    from api import config
    from api.services import twilio_sms

    captured = {}

    class FakeResponse:
        status_code = 200
        @staticmethod
        def json():
            return {"sid": "CA123"}

    class FakeClient:
        def __init__(self, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, data=None, auth=None):
            captured["twiml"] = data["Twiml"]
            return FakeResponse()

    monkeypatch.setattr(twilio_sms.httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr(config, "TWILIO_ENABLED", True)
    monkeypatch.setattr(config, "TWILIO_ACCOUNT_SID", "AC123")
    monkeypatch.setattr(config, "TWILIO_AUTH_TOKEN", "tok")

    monkeypatch.setattr(config, "TWILIO_FROM_NUMBER", "SSCourier")
    asyncio.run(ORIGINALS["transfer_call"]("CA_test", "+447367312558"))
    assert "callerId" not in captured["twiml"]
    assert "+447367312558" in captured["twiml"]

    monkeypatch.setattr(config, "TWILIO_FROM_NUMBER", "+441474557719")
    asyncio.run(ORIGINALS["transfer_call"]("CA_test", "+447367312558"))
    assert 'callerId="+441474557719"' in captured["twiml"]


def test_sms_rejects_malformed_sender(monkeypatch):
    """A bad sender ID fails fast with a clear reason, not a Twilio error code."""
    import asyncio

    from api import config
    from api.services import twilio_sms

    monkeypatch.setattr(config, "TWILIO_ENABLED", True)
    monkeypatch.setattr(config, "TWILIO_FROM_NUMBER", "SS-Courier!")

    result = asyncio.run(ORIGINALS["send_sms"]("07367312558", "test"))
    assert result["ok"] is False
    assert "invalid_sender" in result["error"]


# ══════════════════════════════════════════════════════════════════════════════
#  Website widget (/widget/quote) and the /quote rate limiter it needed
# ══════════════════════════════════════════════════════════════════════════════

def test_widget_page_serves_html(client):
    response = client.get("/widget/quote")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Get instant quote" in response.text
    # The server-side placeholder must always be replaced, never leak as-is.
    assert "__CALL_NUMBER__" not in response.text


def test_widget_injects_configured_call_number(client, monkeypatch):
    from api import config

    monkeypatch.setattr(config, "CLIENT_PUBLIC_NUMBER", "01474557719")
    assert "01474557719" in client.get("/widget/quote").text


def test_widget_omits_call_button_when_number_not_set(client, monkeypatch):
    """No configured number must not render a broken tel: link.

    _env() returns "" (not None) for an unset value, so the injected line is
    always `var CALL_NUMBER = "";` - the widget's JS treats that falsy string
    as "no number configured" and hides the call button accordingly.
    """
    from api import config

    monkeypatch.setattr(config, "CLIENT_PUBLIC_NUMBER", "")
    response = client.get("/widget/quote").text
    assert 'var CALL_NUMBER = "";' in response


def test_quote_endpoint_is_rate_limited(client, monkeypatch):
    """The widget makes /quote reachable by anyone on the internet, and each
    call spends real money on the Google Maps API. A flood from one address
    must eventually be refused rather than run up the client's bill.

    The rate-limiter state is a module-level dict shared across the whole
    test process, so it is reset here to isolate this test from whatever
    other tests happened to call /quote before it.
    """
    from api import main

    monkeypatch.setattr(main, "_quote_rate_state", {})

    payload = {"pickup_address": "A", "dropoff_address": "B", "weight_kg": 10}
    statuses = [client.post("/quote", json=payload).status_code for _ in range(35)]

    assert 429 in statuses
    # Everything up to the limit succeeds; the very next call is refused.
    assert statuses.index(429) == main._QUOTE_RATE_LIMIT
    assert all(code == 200 for code in statuses[: main._QUOTE_RATE_LIMIT])


def test_quote_rate_limit_is_per_ip(client, monkeypatch):
    """A flood from one address must not lock out a different caller."""
    from api import main

    monkeypatch.setattr(main, "_quote_rate_state", {})
    payload = {"pickup_address": "A", "dropoff_address": "B", "weight_kg": 10}

    for _ in range(main._QUOTE_RATE_LIMIT):
        client.post("/quote", json=payload, headers={"x-forwarded-for": "1.1.1.1"})

    blocked = client.post("/quote", json=payload, headers={"x-forwarded-for": "1.1.1.1"})
    assert blocked.status_code == 429

    fresh = client.post("/quote", json=payload, headers={"x-forwarded-for": "2.2.2.2"})
    assert fresh.status_code == 200


def test_reference_falls_back_to_today_on_bad_date():
    """A malformed date must not stop a booking being created."""
    assert booking_ref.is_valid_reference(booking_ref.generate_reference("not-a-date"))
