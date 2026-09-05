# Setup Guide — Courier AI Voice Agent

Everything you have to do **by hand** to take this from code to a working phone
line. Work top to bottom: later steps depend on earlier ones.

Each section ends with a **Test it** command so you never move on with something
quietly broken.

---

## 0. Before anything else

```powershell
# from C:\Users\Betopia\Downloads\Rabby_Project\hey101231
.\venv\Scripts\python.exe -m pip install -r requirements.txt
.\venv\Scripts\python.exe -m uvicorn api.main:app --reload
```

Then in a second terminal:

```powershell
.\venv\Scripts\python.exe -m pytest tests\ -q          # should be 65 passed
```

**Test it:** open <http://localhost:8000/health>. The `integrations` block tells
you what is still unconfigured — that block is your to-do list for this guide.

```json
{"google_maps": true, "google_sheets": false, "twilio": true,
 "calcom": false, "email": false, "vapi_secret_check": false}
```

> **Security note.** Your `.env` holds live secrets. `.gitignore` already excludes
> it, along with `api/service-account.json`. Never paste either into a chat,
> screenshot or commit. If a key ever leaks, rotate it in the provider's console
> immediately — rotating is cheap, a leaked Twilio token is not.

---

## 1. Google Maps — REQUIRED, and currently broken

The mileage in every quote comes from the Distance Matrix API.

**Right now your key returns `REQUEST_DENIED`:**

> "You must enable Billing on the Google Cloud Project"

Until you fix this, **no caller can get a price.** The agent handles it
gracefully (it apologises and transfers to a human instead of blaming the
caller's postcode), but it cannot quote.

### Fix it

1. Go to <https://console.cloud.google.com/billing> and attach a billing account
   to the project that owns the key.
2. Go to **APIs & Services → Library** and enable **Distance Matrix API**.
   (Enabling "Maps JavaScript API" is *not* enough — it must be Distance Matrix.)
3. **APIs & Services → Credentials → your key → Restrict key**:
   - *API restrictions* → restrict to **Distance Matrix API**
   - *Application restrictions* → **IP addresses**, and add your server's IP

Google gives a recurring free monthly credit that comfortably covers a small
courier operation, but the card must still be on file.

**Test it:**

```powershell
.\venv\Scripts\python.exe -c "import sys;sys.path.insert(0,'.');import httpx;from api import config;print(httpx.get('https://maps.googleapis.com/maps/api/distancematrix/json',params={'origins':'London','destinations':'Manchester','units':'imperial','key':config.GOOGLE_MAPS_API_KEY}).json()['status'])"
```

You want `OK`. Anything else, re-read the steps above.

---

## 2. Twilio — SMS and call transfer

### What is wrong today

Two problems showed up in testing:

1. **You are on a trial account.** Trial accounts can only text numbers you have
   verified. The exact error was:
   > *"No Twilio trial phone number is assigned for messaging to this destination
   > number. Please add the 'to' number as a verified recipient."*
2. **`TWILIO_FROM_NUMBER` is a US number** (`+1 737…`). Sending SMS to UK mobiles
   from a US long code is unreliable and often silently filtered by UK carriers.

### Fix it

1. **Upgrade the account** — Twilio Console → Billing → Upgrade. Trial mode
   cannot text arbitrary UK customers, so this is not optional for go-live.
2. **Buy a UK number** — Console → Phone Numbers → Buy a number → United Kingdom,
   with **SMS** capability. Put it in `.env` as `TWILIO_FROM_NUMBER=+44…`.
3. **Register for UK A2P** — the UK requires an Alphanumeric Sender ID or a
   registered number for business messaging. Twilio's console walks you through
   it. Skipping this is the usual reason texts "send" but never arrive.

While still on trial you can test by adding your own mobile under
**Phone Numbers → Verified Caller IDs**.

### For call transfer (Phase 4)

Set the destination the AI hands callers to:

```
CLIENT_PHONE_NUMBER=+447700123456    # the owner's PRIVATE mobile - only rung
                                      # mid-call for a human transfer
CLIENT_PUBLIC_NUMBER=01474557719     # the number CUSTOMERS see and dial -
                                      # shown on the website widget's call
                                      # button. Do not confuse the two: the
                                      # public number is what gets forwarded
                                      # to the Vapi line by the phone
                                      # provider; the private one is only
                                      # reached via an in-call transfer.
```

**Test it** (sends a real text, so use your own mobile):

```powershell
.\venv\Scripts\python.exe -c "import sys,asyncio;sys.path.insert(0,'.');from api.services import twilio_sms;print(asyncio.run(twilio_sms.send_sms('+44YOURMOBILE','Courier agent test')))"
```

Expect `{'ok': True, 'sid': 'SM…'}`.

---

## 3. Google Sheets — the booking log

### Create the sheet

1. New Google Sheet. Name the first tab exactly **`Bookings`**.
2. Copy the ID out of the URL:
   `https://docs.google.com/spreadsheets/d/`**`THIS_LONG_ID`**`/edit`
3. Put it in `.env` as `GOOGLE_SHEETS_ID=`.

### Create the service account

A service account is a robot Google user. Our app signs in as it, so no human
has to click an OAuth consent screen at 3am.

1. <https://console.cloud.google.com> → **IAM & Admin → Service Accounts → Create**
2. Name it `courier-agent`, click through the optional steps, **Done**.
3. Open it → **Keys → Add key → Create new key → JSON**. A file downloads.
4. Save that file over `api/service-account.json`, replacing the placeholder.
5. **APIs & Services → Library → enable "Google Sheets API"**.
6. **Share the sheet with the robot.** Open the JSON, copy the `client_email`
   (`courier-agent@….iam.gserviceaccount.com`), then in the Sheet click
   **Share** and give that address **Editor**.

Step 6 is the one everyone forgets. Without it you get `403 The caller does not
have permission`.

The app writes the header row for you on first start. Column order lives in
`api/services/sheets.py` (`HEADERS`).

> The placeholder `service-account.json` is deliberately ignored: `config.py`
> checks the private key is real before switching Sheets on, so a half-finished
> setup fails safe instead of erroring on every booking.

**Test it:** restart uvicorn. `/health` should show `"google_sheets": true`, and
the header row appears in your sheet.

---

## 4. Cal.com — the calendar

1. <https://cal.com> → **Settings → Developer → API Keys → Add**. You already
   have a `cal_live_…` key in `.env`.
2. Create an **Event Type** for collections (e.g. "Courier Collection",
   60 minutes). Set its availability to your real operating hours.
3. Find the **event type ID** — open the event type and read it out of the URL:
   `https://app.cal.com/event-types/`**`123456`**
4. Put it in `.env` as `CAL_EVENT_TYPE_ID=123456`.

Both values are required; `/health` shows `calcom: false` until they are set.

**Test it:**

```powershell
curl.exe -X POST http://localhost:8000/booking/check-availability -H "Content-Type: application/json" -d "{\"date\":\"2026-09-15\",\"time\":\"10:00\"}"
```

If `"assumed": true` comes back, Cal.com was **not** actually reached — the app
deliberately fails *open* (better to double-book than to tell a paying customer
you are full). `"assumed": false` means the answer is real.

---

## 5. Email (Resend)

This used to be Gmail SMTP with an app password. It was switched to Resend's
HTTP API after Gmail SMTP broke in production: the Google account behind it
got disabled and, once reinstated, Google held it in an extended trust-review
window where SMTP-via-app-password stays blocked ("534 Please log in with
your web browser") no matter how correctly everything is configured - 2-Step
Verification on, a fresh app password, a full interactive login, none of it
helped, because the block isn't a setting. A production system emailing real
customers cannot depend on that kind of opaque per-account timer.

### Get an API key

1. Sign up at <https://resend.com> (free tier: 3,000 emails/month)
2. **API Keys → Create API Key**
3. Add it to `.env`:

```
RESEND_API_KEY=re_xxxxxxxxxxxxxxxxxxxxxxxx
RESEND_FROM_EMAIL=onboarding@resend.dev
EMAIL_FROM_NAME=SS Courier Bookings
```

**Test it:**

```powershell
.\venv\Scripts\python.exe -c "import sys,asyncio;sys.path.insert(0,'.');from api.services import email_sender as e;print(asyncio.run(e.send_email('the-address-you-signed-up-to-resend-with@example.com','Test','It works')))"
```

### The sandbox limitation — this blocks real customer email until fixed

Confirmed directly: without a verified domain, Resend's `onboarding@resend.dev`
address can **only deliver to the email address the Resend account itself was
signed up with**. Every other recipient — including the client's own business
inbox — gets rejected with a 403. This is fine for proving the integration
works, but it means **no real customer or client email goes out until a
domain is verified.**

### Verify a domain (required before this handles real bookings)

1. Resend dashboard → **Domains → Add Domain** → enter `sscourier.co.uk` (or
   whichever domain the client controls)
2. Resend shows a handful of DNS records (typically an MX record plus a
   couple of TXT records for SPF/DKIM) — add these at wherever the domain's
   DNS is managed (the client's domain registrar, or whoever hosts their
   website). **This step needs someone with access to that DNS panel** — it
   is not something either of us can do without it.
3. Wait for Resend to show the domain as **Verified** (usually minutes once
   the records propagate, occasionally longer)
4. Update `.env`:

```
RESEND_FROM_EMAIL=bookings@sscourier.co.uk
```

5. Retest — it should now deliver to the client's real email and any real
   customer address, not just the Resend account owner's inbox.

---

## 6. ngrok — exposing your PC to Vapi

Vapi lives on the internet; your API lives on your laptop. ngrok bridges them.

```powershell
ngrok http 8000
```

Copy the `https://` URL into `.env` as `NGROK_URL`.

> **The free-tier trap:** the URL changes every time you restart ngrok, and you
> must update it in the Vapi dashboard each time. A paid static domain (or
> deploying to a real host) removes this daily annoyance. Your current reserved
> domain is `childless-stride-clunky.ngrok-free.dev`.

**Test it:** open `https://<your-ngrok-url>/health` in a browser.

---

## 6.5. The website quote widget

A small "get an instant quote" box the client can drop into their own site.
It's a page this server itself serves — the client's site doesn't need to run
any code, just embed one line:

```html
<iframe src="https://<this-server>/widget/quote"
        width="100%" height="480" style="border:0"></iframe>
```

An `<iframe>` is used deliberately rather than a `<script>` snippet — most
site builders (Squarespace, some Wix plans) restrict custom JavaScript to
paid tiers, but accept a plain iframe embed on any plan. It also means the
widget's calls back to `/quote` are same-origin (the iframe loads from this
server, not the parent site's domain), so there is no CORS configuration to
maintain across whatever platform the client's site happens to run on.

The widget asks for pickup, dropoff and weight only — `/quote`'s pricing does
not use date or time at all, so there's nothing to gain from asking a website
visitor for them. It shows the price and a **Call to book** button using
`CLIENT_PUBLIC_NUMBER` (set that in `.env` or the visitor gets a price with no
way to act on it).

**Because this makes `/quote` reachable by anyone on the internet** — not just
Vapi as before — it's rate-limited to 30 requests/minute per visitor.
That's generous for a real customer adjusting their weight a few times, tight
enough to stop a bot loop running up the Google Maps bill.

**Test it:** open `https://<your-server>/widget/quote` directly in a browser
and get a real quote.

---

## 7. Vapi — the voice agent itself

This is where the phone call actually happens.

### 7.1 Server URL and secret

Dashboard → your Assistant → **Advanced / Server**:

- **Server URL:** `https://<your-ngrok-url>/vapi/webhook`
- **Server URL Secret:** invent a long random string, and put the *same* value
  in `.env` as `VAPI_SERVER_SECRET`.

That one URL handles every event — quotes, transfers, end-of-call — because
`/vapi/webhook` routes on `message.type`.

Until you set the secret, anyone who discovers your ngrok URL can post fake
bookings. Set it before go-live.

### 7.2 Voice and model

- **Transcriber:** Deepgram Nova-2, language **en-GB**
- **Voice:** any warm British voice (ElevenLabs, or PlayHT "Ruby")
- **Model:** GPT-4o or Claude — either is fine at this complexity

### 7.3 System prompt

Paste this into the assistant's system prompt:

```
You are the booking assistant for a UK same-day courier company. You speak
natural, warm British English. Keep replies short — one or two sentences —
because the caller is on the phone.

YOUR JOB
Collect these five things, one or two at a time, never all at once:
  1. Collection address (ask for the postcode)
  2. Delivery address (ask for the postcode)
  3. Load weight in kilograms
  4. Collection date
  5. Collection time

Once you have all five, call the get_quote function. Read out the price it
gives you, exactly as worded. Then ask if they would like to book it.

RULES
- Never invent a price. Only ever say the price get_quote returns.
- If the load is over 790 kg, do not quote. Call transfer_to_human with
  reason "over_capacity".
- If the caller asks for a person at any point, call transfer_to_human with
  reason "human_requested".
- Only treat a booking as accepted after the caller clearly says yes.
- After they accept, collect their name, mobile number and email address.
- Read the date and time back to confirm before finishing.
- We operate 24 hours a day, seven days a week.

TONE
Friendly and efficient, like a good dispatcher. Use "lovely", "no problem",
"bear with me" naturally. Never sound robotic or read out JSON.
```

### 7.4 Tools

Add two tools of type **Function**, both with **Server URL**
`https://<your-ngrok-url>/vapi/webhook`.

**Tool 1 — `get_quote`**

```json
{
  "name": "get_quote",
  "description": "Calculate the price for a courier job once all five details are known.",
  "parameters": {
    "type": "object",
    "properties": {
      "pickup_address": { "type": "string", "description": "Full collection address including postcode" },
      "dropoff_address": { "type": "string", "description": "Full delivery address including postcode" },
      "weight_kg":       { "type": "number", "description": "Load weight in kilograms" },
      "date":            { "type": "string", "description": "Collection date, e.g. 2026-09-15 or 'tomorrow'" },
      "time":            { "type": "string", "description": "Collection time, e.g. 14:30 or '2pm'" }
    },
    "required": ["pickup_address", "dropoff_address", "weight_kg", "date", "time"]
  }
}
```

**Tool 2 — `transfer_to_human`**

```json
{
  "name": "transfer_to_human",
  "description": "Hand the call to a human when the caller asks for a person or the load exceeds 790 kg.",
  "parameters": {
    "type": "object",
    "properties": {
      "reason": {
        "type": "string",
        "enum": ["human_requested", "over_capacity"],
        "description": "Why the transfer is needed"
      }
    },
    "required": ["reason"]
  }
}
```

You do not need to hand-write date parsing in the prompt — the API accepts
"tomorrow" and "half past two" and normalises them.

### 7.5 Structured data (important)

Analysis → **Structured Data** → enable, with this schema. This is how booking
details survive the end of the call:

```json
{
  "type": "object",
  "properties": {
    "caller_name":      { "type": "string" },
    "caller_phone":     { "type": "string" },
    "caller_email":     { "type": "string" },
    "pickup_address":   { "type": "string" },
    "dropoff_address":  { "type": "string" },
    "weight_kg":        { "type": "number" },
    "date":             { "type": "string" },
    "time":             { "type": "string" },
    "quote_gbp":        { "type": "number" },
    "distance_miles":   { "type": "number" },
    "booking_accepted": { "type": "boolean", "description": "true only if the caller clearly agreed to book" }
  }
}
```

Without `booking_accepted`, the system falls back to reading the transcript,
which is deliberately cautious and will miss some bookings.

### 7.6 Attach a phone number

Phone Numbers → buy one or import your Twilio number → assign this assistant.

**Test it:** ring the number. Watch your uvicorn terminal — you should see
`Vapi webhook: type=tool-calls`.

---

## 8. Nothing to do here — booking creation is automatic

Earlier drafts of this project used n8n as a separate automation layer
sitting between Vapi and the booking logic: Vapi's end-of-call event would
reach n8n, which checked whether the caller had accepted, then called
`/booking/create`.

That extra hop has been removed. `/vapi/end-of-call` now does that check and
creates the booking itself, in the same process, the moment the call ends —
see `_auto_create_booking()` in `api/main.py`. One fewer service to run, one
fewer thing that can silently stop working, and nothing left to configure or
activate here.

Every endpoint that logic uses (`/booking/create`, `/booking/check-availability`,
`/booking/alert-failure`, and so on) is still there and still callable
directly — by `curl`, an admin tool, or n8n again later if you ever want it —
it just is not required for a call to complete.

---

## 9. Testing the whole thing

```powershell
# Automated — mocked, free, offline, ~0.4s
.\venv\Scripts\python.exe -m pytest tests\ -v

# A full simulated call against the running server
.\venv\Scripts\python.exe tests\simulate_call.py

# ...without creating a real booking
.\venv\Scripts\python.exe tests\simulate_call.py --no-booking
```

`tests/test_quote.http` covers every endpoint by hand (VS Code REST Client
extension).

The dashboard is at <http://localhost:8000/admin>.

---

## 10. Where things are written down

| What | Where |
|---|---|
| Every completed call, with transcript | `logs/calls.jsonl` |
| Every human transfer | `logs/transfers.jsonl` |
| Every booking (local safety copy) | `logs/bookings.jsonl` |
| Every booking (shared, live) | Google Sheet |

The local JSONL files mean **no booking is ever lost**, even if Google, Cal.com
and Twilio are all down at once. The dashboard falls back to reading them when
Sheets is unavailable — that is what `"source": "local_log"` means.

To clear the demo bookings created during setup:

```powershell
Remove-Item logs\bookings.jsonl
```

---

## 11. Go-live checklist

- [ ] Google Cloud **billing enabled**, Distance Matrix returns `OK` — *blocking*
- [ ] Twilio account **upgraded** off trial
- [ ] Twilio **UK** sending number, A2P registered
- [ ] `CLIENT_PHONE_NUMBER` is the owner's real mobile — test a transfer end to end
- [ ] `CLIENT_EMAIL` is the owner's real address
- [ ] Google Sheet shared with the service account
- [ ] `CAL_EVENT_TYPE_ID` set, availability matches real operating hours
- [ ] `VAPI_SERVER_SECRET` set in **both** `.env` and the Vapi dashboard
- [ ] `/health` shows every integration `true`
- [ ] A real test call books a real job end to end
- [ ] Quote prices spot-checked against the client's own pricing
- [ ] `/admin` protected, or not exposed through ngrok (it has **no auth**)

### Known limitations to raise with the client

- **ngrok free URLs change on restart.** For production, deploy the API to a
  host (Railway, Fly.io, a VPS) so the URL is stable.
- **`/admin` has no authentication.** Anyone with the link sees customer names,
  numbers and addresses. Add auth before sharing it.
- **Availability fails open.** If Cal.com is unreachable the agent will still
  take the booking rather than turn a customer away. Double bookings are
  possible during a Cal.com outage — that trade-off was deliberate.
- **Ambiguous times are assumed to be daytime.** "Half two" becomes 14:30, not
  02:30. The agent reads the time back to confirm.

---

## 12. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Agent apologises and transfers on every quote | Maps billing disabled | Section 1 |
| `REQUEST_DENIED` from Maps | Billing, or API not enabled | Section 1 |
| SMS returns error `572002` | Twilio trial restriction | Section 2 |
| Texts "send" but never arrive | US sender number / no A2P | Section 2 |
| Sheets `403 caller does not have permission` | Sheet not shared with the robot | Section 3, step 6 |
| `/health` shows `google_sheets: false` | Placeholder key file, or no sheet ID | Section 3 |
| `check-availability` always `"assumed": true` | Cal.com not configured or unreachable | Section 4 |
| Vapi webhook returns 401 | Secret mismatch | Section 7.1 |
| Vapi calls do nothing | ngrok URL changed after restart | Section 6 |
| A call ends but no booking appears | Check the `booking_outcome` field in the `/vapi/end-of-call` response, or the latest line of `logs/calls.jsonl` — it names the exact reason | Section 8 |
| `ZoneInfoNotFoundError` | `tzdata` missing on Windows | `pip install tzdata` |

To see exactly what Vapi sent you, read the newest line of the call log:

```powershell
Get-Content logs\calls.jsonl -Tail 1
```
