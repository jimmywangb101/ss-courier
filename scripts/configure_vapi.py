"""
configure_vapi.py — push the courier assistant configuration into Vapi.

WHY THIS SCRIPT EXISTS
----------------------
The Vapi dashboard keeps a draft copy of the assistant in your browser. If you
change the assistant through the API and then press Publish on a browser tab
that was opened BEFORE that change, the stale tab overwrites everything. That
happened once already and wiped the server URL, greeting and system prompt.

So the configuration lives here, in version control, as the single source of
truth. If the dashboard ever clobbers it again, re-run this script rather than
retyping anything.

USAGE
    ./venv/Scripts/python.exe scripts/configure_vapi.py            # apply
    ./venv/Scripts/python.exe scripts/configure_vapi.py --check    # read only

AFTER RUNNING IT
    1. RELOAD the Vapi dashboard page (Ctrl+R) so the browser picks up the new
       version. Do not press Publish on a tab you opened earlier.
    2. Press Publish if the button is active.
"""

from __future__ import annotations

import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from api import config  # noqa: E402

ASSISTANT_ID = "689b2a5d-a6cf-4176-9fa1-1a237a234088"
API = "https://api.vapi.ai"

FIRST_MESSAGE = "Good afternoon, same-day couriers. How can I help you today?"

SYSTEM_PROMPT = """You are the booking assistant for a UK same-day courier company. You speak natural, warm British English. Keep every reply to one or two sentences - the caller is on the phone and long answers are hard to follow.

YOUR JOB
Collect these five things, asking for one or two at a time, never all at once:
  1. Collection address (ask for the postcode)
  2. Delivery address (ask for the postcode)
  3. Load weight in kilograms
  4. Collection date
  5. Collection time

Once you have all five, call the get_quote function. Read out the price exactly as it comes back, then ask if they would like to book it.

RULES
- Never invent or estimate a price. Only ever say the figure get_quote returns.
- If the load is over 790 kg, do not quote. Call transfer_to_human with reason "over_capacity".
- If the caller asks for a person at any point, call transfer_to_human with reason "human_requested".
- Only treat the booking as accepted once the caller clearly says yes.
- After they accept, take their full name, mobile number and email address.
- Read the date and time back to confirm before you finish.
- We operate 24 hours a day, seven days a week, so never tell a caller we are closed.

TONE
Friendly and efficient, like a good dispatcher who knows the roads. Use "lovely", "no problem", "bear with me" naturally. Never read out JSON, numbers with decimals, or technical detail."""

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_quote",
            "description": "Calculate the price for a courier job once all five details are known.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pickup_address": {"type": "string",
                                       "description": "Full collection address including postcode"},
                    "dropoff_address": {"type": "string",
                                        "description": "Full delivery address including postcode"},
                    "weight_kg": {"type": "number", "description": "Load weight in kilograms"},
                    "date": {"type": "string",
                             "description": "Collection date, e.g. 2026-09-15 or 'tomorrow'"},
                    "time": {"type": "string", "description": "Collection time, e.g. 14:30 or '2pm'"},
                },
                "required": ["pickup_address", "dropoff_address", "weight_kg", "date", "time"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "transfer_to_human",
            "description": "Hand the call to a human when the caller asks for a person or the load exceeds 790 kg.",
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {
                        "type": "string",
                        "enum": ["human_requested", "over_capacity"],
                        "description": "Why the transfer is needed",
                    }
                },
                "required": ["reason"],
            },
        },
    },
]

# Without this, booking details do not survive the end of the call and nothing
# reaches the spreadsheet.
STRUCTURED_SCHEMA = {
    "type": "object",
    "properties": {
        "caller_name": {"type": "string"},
        "caller_phone": {"type": "string"},
        "caller_email": {"type": "string"},
        "pickup_address": {"type": "string"},
        "dropoff_address": {"type": "string"},
        "weight_kg": {"type": "number"},
        "date": {"type": "string", "description": "Collection date as YYYY-MM-DD"},
        "time": {"type": "string", "description": "Collection time as HH:MM 24-hour"},
        "quote_gbp": {"type": "number"},
        "distance_miles": {"type": "number"},
        "booking_accepted": {"type": "boolean",
                             "description": "true only if the caller clearly agreed to book"},
    },
}


def desired_config() -> dict:
    return {
        "firstMessage": FIRST_MESSAGE,
        "model": {
            "provider": "openai",
            "model": "gpt-4.1",
            "messages": [{"role": "system", "content": SYSTEM_PROMPT}],
            "tools": TOOLS,
        },
        "server": {
            "url": f"{config.NGROK_URL}/vapi/webhook",
            "timeoutSeconds": 30,
            "headers": {"x-vapi-secret": config.VAPI_SERVER_SECRET},
        },
        "analysisPlan": {
            "structuredDataPlan": {"enabled": True, "schema": STRUCTURED_SCHEMA}
        },
    }


def headers() -> dict:
    return {"Authorization": f"Bearer {config.VAPI_PRIVATE_KEY}",
            "Content-Type": "application/json"}


def fetch() -> dict:
    resp = httpx.get(f"{API}/assistant/{ASSISTANT_ID}", headers=headers(), timeout=20)
    resp.raise_for_status()
    return resp.json()


def report(a: dict) -> bool:
    """Print the live config. Returns True if it matches what we want."""
    server = a.get("server") or {}
    model = a.get("model") or {}
    prompt = (model.get("messages") or [{}])[0].get("content", "")
    structured = (a.get("analysisPlan") or {}).get("structuredDataPlan") or {}
    tools = [t.get("function", {}).get("name") for t in (model.get("tools") or [])]

    want_url = f"{config.NGROK_URL}/vapi/webhook"
    checks = {
        "server url": (server.get("url") == want_url, server.get("url") or "(empty)"),
        "secret hdr": ((server.get("headers") or {}).get("x-vapi-secret")
                       == config.VAPI_SERVER_SECRET, "matches .env"),
        "greeting  ": (a.get("firstMessage") == FIRST_MESSAGE,
                       (a.get("firstMessage") or "")[:45]),
        "prompt    ": (prompt.startswith("You are the booking assistant"),
                       prompt[:45].replace("\n", " ")),
        "tools     ": (sorted(tools) == ["get_quote", "transfer_to_human"], tools),
        "structured": (bool(structured.get("enabled")), "enabled"),
    }

    all_ok = True
    for label, (ok, detail) in checks.items():
        all_ok &= ok
        print(f"  [{'OK ' if ok else 'BAD'}] {label}  {detail}")
    return all_ok


def main() -> None:
    if not config.VAPI_PRIVATE_KEY:
        sys.exit("VAPI_PRIVATE_KEY missing from .env (Vapi dashboard > API keys > private).")
    if not config.NGROK_URL:
        sys.exit("NGROK_URL missing from .env.")

    check_only = "--check" in sys.argv

    print("Current configuration on Vapi:")
    ok = report(fetch())

    if check_only:
        print("\nMatches expected." if ok else "\nDoes NOT match - re-run without --check to fix.")
        return

    if ok:
        print("\nAlready correct - nothing to push.")
        return

    print("\nPushing configuration...")
    resp = httpx.patch(f"{API}/assistant/{ASSISTANT_ID}", headers=headers(),
                       json=desired_config(), timeout=30)
    if resp.status_code >= 400:
        sys.exit(f"FAILED {resp.status_code}: {resp.text[:400]}")

    print("\nConfiguration after push:")
    report(fetch())

    print("\nNEXT: reload the Vapi dashboard (Ctrl+R) BEFORE pressing Publish.")
    print("Publishing from a tab opened earlier will overwrite this again.")


if __name__ == "__main__":
    main()
