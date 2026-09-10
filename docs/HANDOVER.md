# Handover — SS Courier AI Booking Line

Everything needed to take ownership of this system: what it is, what runs where,
every account involved, and the exact steps to transfer control.

**Written for:** the client (SS Courier) and whoever maintains this next.
**Status at handover:** built, deployed, live and tested — with one step
outstanding, see below.

---

## 1. What this system does

A customer rings the courier line. An AI voice assistant answers, collects the
job details, quotes a real price based on actual road mileage, and — if the
caller accepts — books the job completely on its own:

```
Customer calls
   → AI assistant ("Riley") answers, collects 5 details
   → prices the job from real Google Maps road mileage
   → caller says yes
        ├── calendar entry created (Cal.com)
        ├── row written to the bookings spreadsheet (Google Sheets)
        ├── confirmation SMS to the customer (Twilio)
        ├── confirmation email to the customer (Resend)
        └── notification email to the office (Resend)
```

No human is involved unless the caller asks for one, or the load is over the
790 kg van limit — in which case the call is handed to a person.

It runs 24 hours a day. That is the point of it: the calls it catches are the
ones that would otherwise ring out at 3am.

### The pricing it uses

| Rule | Value |
|---|---|
| Base fare | £15.00 |
| Up to 10 miles | £2.50 per mile |
| 10–30 miles | £2.00 per mile |
| Over 30 miles | £1.75 per mile |
| Loads over 400 kg | +10% |
| Loads over 790 kg | Not quoted — transferred to a person |

These live in `api/config.py`. Changing them is a one-line edit; ask your
developer.

---

## 2. Status — what is done, and what is not

### Working and verified

| Component | Evidence |
|---|---|
| Pricing engine | Live quote returns £385.11 for SW1A 1AA → M1 1AE (211 miles) — arithmetic checked by hand |
| Google Maps mileage | Real Distance Matrix responses |
| Cal.com calendar | Verified reachable, real availability responses |
| Google Sheets log | Bookings written and read back live |
| Customer SMS | **Carrier-confirmed `delivered`** to a real UK mobile |
| Customer + office email | **Delivered to inbox** (not spam) from `bookings@sscourierbookings.com` |
| Email authentication | SPF, DKIM and DMARC all verified on the sending domain |
| The AI assistant | Full booking taken end to end on a real call |
| Admin dashboard | Password-protected, live |
| Automated tests | 115 passing |

### ⚠️ Outstanding — the line is not yet reachable by phone

**No phone number is attached to the AI assistant.** Every call made so far has
been a browser test call through the Vapi dashboard. Those calls prove the
whole system works, but a customer dialling a number cannot reach it yet.

To finish this, one of:

1. **Buy a number inside Vapi** (simplest) — Vapi dashboard → Phone Numbers →
   buy a UK number → assign the "Riley" assistant to it. Then forward the
   existing business line `01474557719` to it with your phone provider.
2. **Buy a UK number in Twilio and import it into Vapi.** Twilio is already
   upgraded to a full account, but currently owns no numbers. A UK number
   needs Twilio's regulatory bundle (proof of business address) approved
   first, which takes 1–3 working days.

Option 1 is faster and needs no regulatory wait. Option 2 keeps voice and SMS
with one provider.

Until this is done, the system is complete but idle.

### Known limitations, stated plainly

- **The admin dashboard uses one shared password.** No individual logins, no
  record of who viewed what. Fine for one or two people in an office; rotate
  the password if someone with it leaves.
- **Availability checking fails "open".** If Cal.com is unreachable, the agent
  takes the booking rather than telling a paying customer you are full. A
  double booking is recoverable; a lost customer is not. This was deliberate.
- **Ambiguous times are assumed to be daytime.** "Half two" becomes 14:30, not
  02:30. The agent reads the time back to confirm.
- **SMS is one-way.** Texts are sent from the name `SSCourier`, not a number,
  so customers cannot reply to them. They are told to ring back instead.
- **The local booking file is wiped on each deploy.** This is safe because the
  Google Sheet is the real record; the local file is only a fallback for when
  Google is unreachable.

---

## 3. Where everything runs

| What | Where | Notes |
|---|---|---|
| The application | Render — `courier-booking-api` | Frankfurt region, `starter` plan |
| Live address | `https://courier-booking-api.onrender.com` | |
| Admin dashboard | `…/admin` | Username `admin`, password sent separately |
| Website quote widget | `…/widget/quote` | Embed with one `<iframe>` line |
| Health check | `…/health` | Shows which services are connected |
| Source code | `github.com/jimmywangb101/ss-courier` | **Private. Must be transferred — see §5** |
| AI assistant | Vapi — "Riley", `689b2a5d-a6cf-4176-9fa1-1a237a234088` | |
| Calendar | Cal.com — event type `6906108` | |
| Bookings log | Google Sheets, tab `Bookings` | |
| Sending domain | `sscourierbookings.com` — DNS at Cloudflare, email via Resend | |

**Frankfurt was chosen deliberately:** it is the closest Render region to the
UK, so lower latency for callers, and it keeps customer names, addresses and
phone numbers stored inside the EU.

---

## 4. Accounts — the full inventory

Everything below currently sits under the Google account
**`wangbjimmy70@gmail.com`**, created specifically for this project. That
account is the linchpin: it is the login or the password-reset mailbox for
every service in the list.

| Service | What it does | Logs in via | Cost |
|---|---|---|---|
| **Google account** | The hub — login and recovery for everything below | — | Free |
| Google Cloud | Road mileage (Distance Matrix API) | Google sign-in | Free allowance covers normal volume |
| Google Sheets | The bookings spreadsheet | Google sign-in | Free |
| Vapi | The AI voice itself | Google sign-in | Pay as you go, ~£0.05–0.12/min |
| Twilio | Confirmation texts | Email + password | ~4p per text (full account, no numbers owned) |
| Cal.com | The booking calendar | Google sign-in | Free tier |
| Resend | Confirmation emails | Google sign-in | Free up to 3,000/month |
| Cloudflare | DNS for `sscourierbookings.com` | Email + password | Free (domain renewal is separate) |
| Render | Hosting | Google/GitHub sign-in | ~$7/month |
| GitHub | Source code | Separate account `jimmywangb101` | Free |

### Roughly what it costs to run

The only cost that moves with volume is Vapi, billed per minute of call time.

- **Quiet month** (~100 calls, 3 min each): **roughly £45–60**
- **Busier month** (~300 calls, 3 min each): **roughly £110–140**

Hosting is a flat ~£6/month. Texts are ~4p each. Maps and email are almost
certainly free at this volume.

These are estimates for budgeting, not quotes — each provider publishes its own
current pricing.

**Set a spending cap on Vapi.** It is billed by the minute, so a stuck or
looping call is the one realistic way this runs up an unexpected bill. A
monthly limit makes that impossible.

---

## 5. Transferring ownership

Work through this in order. Steps 1–3 are best done together on a call, so the
client can confirm access as it changes hands.

### Step 1 — The Google account (do this first)

Handing over `wangbjimmy70@gmail.com` transfers control of nearly everything
in one move, because it is the sign-in for most services and the
password-reset mailbox for the rest.

**Client does, while the developer is on the call:**

- [ ] Sign in at <https://myaccount.google.com> with the current password
- [ ] **Change the password** to one only the client knows
- [ ] Security → **2-Step Verification** → remove the developer's phone,
      add the client's own (or an authenticator app)
- [ ] Security → **Recovery phone and recovery email** → replace with the
      client's
- [ ] Security → **Your devices** → sign out every session the client does not
      recognise
- [ ] Security → **Third-party apps with account access** → review and remove
      anything unexpected

**Developer confirms in writing:** the password is changed, they no longer hold
it, and they have removed themselves from recovery.

> Do not skip the recovery details. A recovery phone left in place is a way
> back into the account regardless of the new password.

### Step 2 — The source code

The repository is currently under the developer's personal GitHub account, not
the client's. Render deploys from it, so if that account disappears, updates
become impossible.

- [ ] Client creates a GitHub account (or organisation) in the business name
- [ ] Developer: repo → Settings → **Transfer ownership** → to the client's account
- [ ] Client accepts the transfer
- [ ] In Render → the service → Settings → **reconnect** the repository under
      its new owner
- [ ] Push a trivial change and confirm Render still auto-deploys

### Step 3 — Rotate the credentials

The developer has necessarily seen every API key while building this. Rotating
them is quick and is simply good hygiene at a handover — it is not a statement
about anyone's trustworthiness.

For each, generate a new key in the provider's dashboard, paste it into
**Render → Environment**, and delete the old one:

- [ ] `GOOGLE_MAPS_API_KEY` — Google Cloud → Credentials
- [ ] `RESEND_API_KEY` — Resend → API Keys (keep it **sending-access only**)
- [ ] `CAL_API_KEY` — Cal.com → Settings → Developer → API Keys
- [ ] `TWILIO_AUTH_TOKEN` — Twilio Console → Account → API keys & tokens
- [ ] `VAPI_PRIVATE_KEY` — Vapi → API Keys
- [ ] `VAPI_SERVER_SECRET` — invent a new long random string; set the **same**
      value in Vapi (Assistant → Server → Secret) and in Render
- [ ] `ADMIN_PASSWORD` — any long random string; Render → Environment
- [ ] Google service-account key — Google Cloud → Service Accounts → Keys →
      add a new JSON key, upload to Render as the Secret File
      `/etc/secrets/service-account.json`, then delete the old key

After each change Render redeploys automatically. Check `/health` shows every
integration `true` when you are done.

### Step 4 — Billing

- [ ] Replace the card on file for Render, Vapi, Twilio and Google Cloud with
      the company card
- [ ] Set spending caps: Vapi ~£100/month, Google Cloud ~£30/month,
      Twilio ~£40/month
- [ ] Confirm who receives the billing emails

### Step 5 — Finish the phone line

- [ ] Attach a phone number to the assistant (see §2)
- [ ] Forward `01474557719` to it
- [ ] Make a real test call and confirm a booking appears in the calendar,
      the spreadsheet, and both inboxes

---

## 6. Running it day to day

See **`docs/operating-guide.md`** — written in plain English for whoever works
the office, with no technical knowledge assumed.

The short version:

- **Bookings appear** in the Google Sheet, in Cal.com, and as an email to the
  office. You do not have to do anything for a normal booking.
- **The dashboard** at `…/admin` shows recent bookings at a glance.
- **If an email arrives with "ACTION NEEDED" in the subject**, a booking could
  not be completed automatically and needs a person. It contains everything
  needed to sort it by hand.

---

## 7. If something breaks

| Symptom | Likely cause | Where to look |
|---|---|---|
| Callers get a price but no booking arrives | Check the office inbox for an "ACTION NEEDED" email — it names the exact reason | `docs/setup-guide.md` §12 |
| Agent apologises and transfers on every quote | Google Maps billing lapsed | Google Cloud → Billing |
| Texts stop arriving | Twilio balance, or sender ID blocked | Twilio Console |
| Emails stop arriving | Resend monthly limit, or a DNS record removed | Resend → Domains |
| Bookings missing from the calendar | Cal.com key expired or availability changed | Cal.com |
| Nothing works at all | Hosting down or card declined | Render → Logs |

`https://courier-booking-api.onrender.com/health` is the fastest single check —
it reports which services are connected. Anything showing `false` is the fault.

Full troubleshooting is in **`docs/setup-guide.md`** §12.

---

## 8. What is included in this delivery

**Included:**

- The complete working system, deployed and running
- Full source code, commented throughout, with 115 automated tests
- This handover document
- `docs/operating-guide.md` — plain-English daily use
- `docs/setup-guide.md` — full technical setup and troubleshooting
- `docs/render-deploy.md` — how the deployment works and how to redeploy
- The website quote widget, ready to embed

**Not included:**

- Ongoing hosting, call and messaging costs — these are billed by the providers
  directly to the account holder
- A phone number (see §2)
- Individual user logins for the admin dashboard
- Any ongoing support or maintenance beyond what has been separately agreed

---

## 9. Handover sign-off

- [ ] Google account password changed, recovery details replaced
- [ ] Developer confirms no remaining access to the Google account
- [ ] GitHub repository transferred and Render reconnected
- [ ] All API keys rotated; `/health` shows every integration `true`
- [ ] Billing moved to the company card, spending caps set
- [ ] Admin dashboard password changed and tested
- [ ] Phone number attached and a real test call completed
- [ ] Client has read the operating guide

Signed ......................................  Date ....................
