# Handover — SS Courier AI Booking Line

Everything needed to take ownership of this system: what it is, what runs where,
every account involved, and the exact steps to transfer control.

**Written for:** the client (SS Courier) and whoever maintains this next.
**Status at handover:** built, deployed and live on **01634 980038**, tested
end to end with real phone calls.

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
| Call-out fee | £10.00 on every job |
| Every mile | £1.75, whatever the distance |
| Loads over 400 kg | +10% |
| VAT | 20%, added last |
| Loads over 790 kg | Not quoted — transferred to a person |

So a 20-mile job is (20 × £1.75) + £10 = £45, plus VAT = **£54.00**. Set by
Jimmy Wangboje on 21 September 2026.

**Quoted prices include VAT.** The figure the assistant reads out, texts and
emails is what the customer pays. The distance bands used until this date were
dropped at the same time, which removed a price step where a 46-mile job cost
less than a 45-mile one.

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
| Phone line | Real inbound calls to **01634 980038** answered, booked and confirmed (16 Sep 2026) |
| Customer SMS | **Carrier-confirmed `delivered`** to a real UK mobile, from a real phone booking |
| Customer + office email | **Delivered to inbox** (not spam) from `bookings@sscourierbookings.com` |
| Email authentication | SPF, DKIM and DMARC all verified on the sending domain |
| The AI assistant | Full booking taken end to end on a real call |
| Admin dashboard | Password-protected, live |
| Automated tests | 129 passing |

### The phone line

**Customers ring `01634 980038`.** It is a UK local number (Medway) bought
through Twilio and connected to the AI assistant in Vapi. Twilio passes every
incoming call straight to the assistant.

It is the business's **public number**, for the Google profile, the website,
the van and paperwork. The website quote widget shows it automatically once
`CLIENT_PUBLIC_NUMBER` is set to `01634980038` in Render.

**The old number, `01474557719`,** is an internet phone line (VoIP) from a
separate provider, which the client intends to cancel. Recommended: forward it
to `01634 980038` for a few weeks first, so anyone who still has the old
number gets through, then cancel it. Forwarding is set in that provider's
online account, or by asking their support team.

**How the number was obtained, for the record.** Vapi only issues US numbers,
so a UK number has to be bought elsewhere and imported. Twilio requires an
approved UK regulatory bundle, and a *local* number must match the dialling
area of the address on that bundle. That is why it is an 01634 number: the
approved bundle (`BUbb9fe3176530f8b642ec1013eb286238`) carries the Gillingham
ME7 5NB address. New Twilio accounts are also blocked from buying numbers
until Twilio's fraud team reviews them (error `22300`). That review completed
on 15 Sep 2026, after the verification questions on ticket #29336617 were
answered.

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
- **The assistant does not check the calendar before agreeing a time.** It
  books whatever time the caller asks for. If that slot is already taken
  (there is one van), Cal.com refuses the calendar entry and the office
  receives an "ACTION NEEDED" email saying the booking is not on the calendar,
  so it can be rearranged with the customer. Checking availability during the
  call is a possible future improvement.
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
| Phone number | **01634 980038**, Twilio, connected to Vapi | The public number customers ring |
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
| Google Cloud | Road mileage (Distance Matrix API) | wangbjimmy70@gmail.com | Free allowance covers normal volume |
| Google Sheets | The bookings spreadsheet | wangbjimmy70@gmail.com | Free |
| Vapi | The AI voice itself | wangbjimmy70@gmail.com | Pay as you go, ~£0.05–0.12/min |
| Twilio | The phone number and confirmation texts | wangbjimmy70@gmail.com | ~£1/month for the number, ~4p per text |
| Cal.com | The booking calendar | wangbjimmy70@gmail.com | Free tier |
| Resend | Confirmation emails | wangbjimmy70@gmail.com | Free up to 3,000/month |
| Cloudflare | DNS for `sscourierbookings.com` | wangbjimmy70@gmail.com | Free (domain renewal is separate) |
| Render | Hosting | wangbjimmy70@gmail.com | ~$7/month |
| GitHub | Source code | Separate account `jimmywangb101` | Free |

Where a site offers "Continue with Google", use it with the Google account
above; otherwise the site has its own password, sent separately.

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
- [ ] `TWILIO_AUTH_TOKEN` — Twilio Console → Account → API keys & tokens.
      **Two other places use this token and must be updated at the same time,
      or they stop working:** (1) Vapi → Phone Numbers → 01634 980038, which
      stores it to receive calls; (2) any other system sending texts from this
      Twilio account. On 13 Sep 2026, texts beginning "SALUS: Booking SS-"
      were sent from this account by a different system, most likely the
      website's own booking system. Confirm with the client who runs it before
      rotating.
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

### Step 5 — Switch customers to the new number

- [x] Phone number `01634 980038` attached to the assistant
- [x] Real test calls made; the booking reached the calendar, the spreadsheet,
      the customer's phone and both inboxes
- [x] Test bookings removed from the calendar and spreadsheet
- [ ] Render → Environment → `CLIENT_PUBLIC_NUMBER` = `01634980038`
- [ ] Google business profile and website updated to `01634 980038`
- [ ] `01474557719` forwarded to `01634 980038` for a few weeks, then cancelled

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
| Calls to 01634 980038 do not connect | Vapi credit ran out, or the number was unassigned from the assistant | Vapi → Billing, Vapi → Phone Numbers |
| Nothing works at all | Hosting down or card declined | Render → Logs |

`https://courier-booking-api.onrender.com/health` is the fastest single check —
it reports which services are connected. Anything showing `false` is the fault.

Full troubleshooting is in **`docs/setup-guide.md`** §12.

---

## 8. What is included in this delivery

**Included:**

- The complete working system, deployed and running
- Full source code, commented throughout, with 129 automated tests
- This handover document
- `docs/operating-guide.md` — plain-English daily use
- `docs/setup-guide.md` — full technical setup and troubleshooting
- `docs/render-deploy.md` — how the deployment works and how to redeploy
- The website quote widget, ready to embed

**Not included:**

- Ongoing hosting, call and messaging costs — these are billed by the providers
  directly to the account holder
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
- [x] Phone number attached and real test calls completed
- [ ] Customers switched to 01634 980038 (profile, website, forwarding)
- [ ] Client has read the operating guide

Signed ......................................  Date ....................
