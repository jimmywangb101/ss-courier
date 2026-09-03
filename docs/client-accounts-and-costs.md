# Client Accounts & Running Costs

Two things in here:

1. **The message to send the client** — copy/paste, plain English, no jargon.
2. **Your own reference table** — what each account is, and why it must be in
   their name.

Replace `[Client name]`, `[Your name]` and `[your email]` before sending.

---

## 1. The message to send

> **Subject: Accounts needed before your AI phone line can go live**
>
> Hi [Client name],
>
> The AI booking assistant is built and working. Before it can take real
> customer calls, a few external services need to be set up and connected to a
> payment method.
>
> **These accounts need to be opened in your company's name, on your company's
> card.** I'll then be added as a user so I can do the technical configuration.
>
> I've set it up this way deliberately, for three reasons:
>
> - **You own the system.** The phone number, the customer records and the
>   booking history stay yours. If you ever change developer, nothing has to be
>   rebuilt or handed over.
> - **No interruption.** If the accounts sat on my card, the service would stop
>   the moment a payment failed or our arrangement ended. Your phone line should
>   never depend on that.
> - **Data protection.** Your customers' names, numbers and addresses are your
>   business records. Under GDPR they should sit under your company's control,
>   not a contractor's personal account.
>
> ### What needs setting up
>
> | Service | What it does for you | Cost |
> |---|---|---|
> | **Google Maps** | Works out the mileage between the pickup and delivery address, so the price is accurate | Small free monthly allowance; beyond that roughly £4 per 1,000 quotes |
> | **Twilio** | The phone number, and the confirmation texts customers receive | Around £1–2/month for a UK number, plus roughly 4p per text. Needs an initial top-up of about £20 |
> | **Vapi** | The AI voice itself — the part that speaks to and understands callers | Charged per minute of call time. Expect roughly 8–12p per minute |
> | **Cal.com** | The booking calendar | Free plan is likely enough to start |
> | **Hosting** | Keeps the system online 24/7 | Roughly £5–10/month |
> | **Google Sheets / Gmail** | Your booking spreadsheet and confirmation emails | Free with your existing Google account |
>
> ### Roughly what to expect
>
> The only cost that really moves is Vapi, because it's charged by the minute.
>
> - **Quiet month** — around 100 calls, 3 minutes each: **roughly £45–60**
> - **Busier month** — around 300 calls, 3 minutes each: **roughly £110–140**
>
> These are estimates to help you budget, not quotes. Every provider publishes
> its own current pricing, and I'd suggest checking it as you sign up. I'll set
> spending caps and alerts on each account so there are no surprises.
>
> For comparison, that's a fraction of the cost of someone answering the phone
> overnight — and the line is covered 24/7.
>
> ### One thing is blocking us right now
>
> The Google Maps account currently has **no billing enabled**, so it can't
> calculate mileage. Until that's switched on, the assistant can answer calls
> and take details, but it can't quote a price — it hands the caller to a human
> instead.
>
> It's a five-minute fix: add a card at
> <https://console.cloud.google.com/billing> and enable the "Distance Matrix
> API". Google's free monthly allowance will likely cover your volume, but a
> card has to be on file before they'll allow any requests at all.
>
> ### What I need from you
>
> 1. Open the accounts above in the company name, with the company card
> 2. Invite me as a user on each: **[your email]**
> 3. Enable billing on Google Maps first — that's the one holding everything up
>
> Happy to sit on a call and do the sign-ups together if that's easier — it
> usually takes about half an hour for the lot.
>
> Best regards,
> [Your name]

---

## 2. Your reference — the detail behind each line

| Service | Account holder | Payment | Notes |
|---|---|---|---|
| Google Cloud (Maps) | Client | Client card | **Currently blocking.** Needs billing + Distance Matrix API enabled |
| Twilio | Client | Client card | Currently a **trial** account with a **US** number — both must change |
| Vapi | Client | Client card | Dominant cost; scales directly with call minutes |
| Cal.com | Client | Free tier likely | Only needs the event type ID to work |
| Google Sheets | Client | Free | Share with the service-account email |
| Gmail SMTP | Client | Free | Needs an App Password, not the normal password |
| Hosting / ngrok | Client | Client card | Replaces the ngrok URL that changes on every restart |

### Points worth raising on the call

- **Twilio must be upgraded off trial.** Trial accounts can only text numbers
  that have been manually verified, so real customers would never receive a
  confirmation. There's also a US sending number in place at the moment; UK
  carriers filter US long-code messages heavily, so a UK number is needed.
- **UK A2P registration.** Business SMS to UK mobiles needs registering through
  Twilio. Skipping it is the usual reason texts appear to send but never arrive.
- **Set billing alerts on every account** as you create them. Vapi in particular
  is per-minute, so a stuck or looping call is the one thing that could run up a
  bill unnoticed.
- **Don't send credentials over WhatsApp or email.** Ask the client to add you
  as a *user* on each account instead of sharing passwords or API keys. If a key
  ever does get sent that way, rotate it straight after use.

### If the client pushes back on owning the accounts

The usual objection is "can't you just handle it and bill me?" Worth explaining
that it isn't about the money — it's that their phone number, their customer
list and their booking history would sit inside a contractor's personal account.
Most business owners change their mind the moment it's framed as *whose records
these are*, rather than *whose card is on file*.
