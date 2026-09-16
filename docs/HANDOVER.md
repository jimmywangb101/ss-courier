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
| Starting charge | None — the price is the mileage |
| Up to 45 miles | £3.00 per mile |
| Over 45, under 100 miles | £2.00 per mile |
| 100 miles and over | £1.80 per mile |
| Loads over 400 kg | +10% |
| Loads over 790 kg | Not quoted — transferred to a person |

The rate applies to the **whole journey**, so a 20-mile job is 20 × £3 = £60.
Confirmed by Jimmy Wangboje on 16 September 2026.

One consequence worth knowing: because the lower rate covers the whole
journey, a 45-mile job (£135) costs more than a 46-mile one (£92).

These live in `api/config.py`. Changing them is a one-line edit; ask your
developer.

---

## 2. Status — what is done, and what is not

### Working and verified

| Component | Evidence |
|---|---|
| Pricing engine | Live quote returns £380.68 for SW1A 1AA → M1 1AE (211.49 miles × £1.80) — arithmetic checked by hand |
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

**Vapi cannot sell you a UK number.** Numbers created directly inside Vapi
are free but **US only**. A `+44` number has to be bought elsewhere and
imported. So the route is:

**Step 1 — UK regulatory bundle — ALREADY DONE ✅**

Bundle `BUbb9fe3176530f8b642ec1013eb286238` ("United Kingdom: Local —
Business") is **approved**, for Salus Securities & Couriers Limited (UK CRN
15750459), authorised representative Jimmy Wangboje.

**The address on that approved bundle is 7 St John's Road, Gillingham, Kent,
ME7 5NB.** This matters more than it looks. A UK number marked
`address_requirements: local` can only be bought by a business with a proven
address **in that same dialling area**, and the bundle carries the Gillingham
address — so the number must be on the **01634 (Medway)** code.

The account also holds a second validated address in Northfleet (DA11 8HN,
which is the 01474 Gravesend area), but it is **not** the one attached to the
approved bundle, so it does not help here.

This is what the "Provisioning failed" error meant: a **London 020** number was
selected, and London is neither Gillingham nor Northfleet. UK mobile numbers
(`07…`) carry no address requirement at all and would sidestep the issue
entirely.

**Step 2 — ⚠️ BLOCKED: lift the account restriction (Twilio Compliance)**

Buying any long-code number currently fails with:

```
22300 — Account is restricted from provisioning new long code Phone Numbers
```

This is an account-level hold applied by Twilio Compliance — routine on
recently created accounts. It is **not** an address, bundle or funding problem:
the bundle is approved, the account is full (non-trial) and holds a £34
balance. Verified during diagnosis: a Gravesend landline and a UK mobile were
both refused identically, so it blocks every long code.

Only Twilio can lift it. **See `docs/twilio-compliance-request.md` for the
ready-to-send request** to `verifymyaccount@twilio.com`.

**Step 3 — Buy the number (Twilio), once the hold is lifted**

Phone Numbers → Buy a number → United Kingdom → search `1634` → tick **Voice**
→ select the **Gillingham ME7 5NB** address and the approved bundle → buy.
Free at the time of writing: `+441634980582`, `+441634949983`,
`+441634980994`, `+441634980195`.

The number's area code does not need to match the published business line
(01474), because customers never dial it — `01474557719` forwards to it. It
only has to match the address on the approved bundle.

**Step 4 — Import it into Vapi**

Vapi dashboard → Phone Numbers → **Create Phone Number** → **Import Twilio**.
It asks for three things:

- the phone number, with country code
- the **Twilio Account SID**
- the **Twilio Auth Token**

Then assign the **Riley** assistant to it.

**Step 5 — Point the business line at it**

Ask the existing phone provider to forward `01474557719` to the new Twilio
number. Customers keep dialling the number they already know.

> **Do not port `01474557719` into Twilio** to save the forwarding step, at
> least not yet. Porting takes weeks and puts the live business line at risk
> if anything goes wrong. Forwarding is reversible in minutes.

**Want to test telephony before the bundle clears?** Create one of Vapi's free
US numbers and ring it. It proves the whole inbound path works end to end
while the UK paperwork is in the queue. It is not suitable for production —
forwarding a UK landline to a US number bills international rates per minute.

**A useful side effect.** Once calls arrive through the client's own Twilio
account, the code can redirect a live call to a human directly via Twilio
rather than relying on Vapi to do it. Both paths are already implemented in
`api/main.py`; the Twilio one simply becomes available.

Until a number is attached, the system is complete but idle.

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
| Source code | `github.com/jimmywangb101/ss-courier` | Private, already under the client's own GitHub account |
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

**Nothing to transfer.** `github.com/jimmywangb101/ss-courier` is already the
client's own GitHub account, so the code sits where it should. Render deploys
from it, and that link is unaffected by the handover.

The only thing to tidy is the developer's access to it:

- [ ] Repo → Settings → **Collaborators** → remove the developer, if listed
- [ ] GitHub → Settings → **Developer settings → Personal access tokens** →
      revoke any token the developer used to push
- [ ] Confirm Render still deploys: push a trivial change (or use
      **Manual Deploy** in the Render dashboard) and watch it go green

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
- [ ] Developer's GitHub access removed; Render still deploys
- [ ] All API keys rotated; `/health` shows every integration `true`
- [ ] Billing moved to the company card, spending caps set
- [ ] Admin dashboard password changed and tested
- [ ] Phone number attached and a real test call completed
- [ ] Client has read the operating guide

Signed ......................................  Date ....................
