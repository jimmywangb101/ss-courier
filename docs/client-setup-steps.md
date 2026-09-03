# Getting Set Up — Step by Step

Everything you need to do, in the order to do it. No technical knowledge needed.

**Total hands-on time: about 60–75 minutes.** You don't have to do it all in one
sitting — each section stands on its own.

Two of these involve a waiting period for approval, so it's worth starting them
early even though the rest can be done any time.

---

## Before you start

Have these to hand:

- **The company card** (for billing)
- **A company email address** — ideally something like `admin@yourcompany.co.uk`
  rather than a personal Gmail, so the accounts stay with the business
- **Proof of business address** — a recent utility bill or bank statement.
  Twilio requires this to issue a UK phone number
- **Your phone** — several sites will text you a verification code

Throughout, whenever you're asked to invite me, use:

**mohammadrabby.dil@gmail.com**

---

## The order to do things in

| # | What | Time | Why this order |
|---|---|---|---|
| 1 | Google Maps billing | 10 min | **Blocking everything.** Instant once done |
| 2 | Twilio | 20 min | **Start early** — the phone number needs approval, which can take 1–3 working days |
| 3 | Vapi | 10 min | The AI voice |
| 4 | Cal.com | 5 min | The calendar |
| 5 | Google Sheets & email | 10 min | Your booking records |
| 6 | Hosting | 10 min | Keeps it running 24/7 |

Steps 1 and 2 are the ones that matter this week. The rest can follow.

---

## STEP 1 — Google Maps (do this first)

This is what works out the mileage between addresses, so it's what makes the
price accurate. Nothing can quote until it's live.

### 1.1 Sign in

Go to <https://console.cloud.google.com> and sign in with the **company** Google
account.

If you've never used Google Cloud, it'll offer you a free trial — accept it.

### 1.2 Create a project

1. At the top of the page there's a project dropdown (it may say
   "Select a project")
2. Click it → **New Project**
3. Name it something like `Courier Booking System`
4. Click **Create**, then make sure that project is selected in the dropdown

### 1.3 Add your card

1. In the search bar at the top, type **Billing** and open it
2. Click **Link a billing account** → **Create billing account**
3. Enter the company details and card

> **You will almost certainly not be charged.** Google gives a free monthly
> allowance that comfortably covers a business of your size. But they refuse
> *all* requests unless a card is on file — that's the bit currently blocking
> us.

### 1.4 Turn on the mapping service

1. In the search bar, type **Distance Matrix API**
2. Open it and click **Enable**

⚠️ It must be **Distance Matrix API** specifically. There are several
similarly-named Google mapping services and the others won't work.

### 1.5 Set a spending cap

1. Search for **Budgets & alerts** → **Create budget**
2. Set the amount to **£30 per month**
3. Tick the alert thresholds (50%, 90%, 100%)

You'll now get an email long before anything unexpected happens.

### 1.6 Invite me

1. Search for **IAM** and open it
2. Click **Grant access**
3. In "New principals" enter **mohammadrabby.dil@gmail.com**
4. Under "Role" choose **Editor**
5. Click **Save**

### ✅ Then tell me

Just message me *"Google is done"* — I can see the rest from my side and I'll
confirm within a few minutes that quoting is live.

---

## STEP 2 — Twilio (start this early)

This provides your phone number and the confirmation texts customers receive.

> **Why to start now:** UK phone numbers are regulated. Twilio has to verify
> your business address before it will issue one, and that check can take
> **1–3 working days**. Everything else here is instant, so get this one in the
> queue.

### 2.1 Create the account

Go to <https://www.twilio.com/try-twilio> and sign up with the company email.
Verify your email and mobile when prompted.

### 2.2 Upgrade off the free trial

This is essential. Trial accounts can only text numbers you've manually
verified one at a time — real customers would never receive a confirmation.

1. In the console, look for **Upgrade** (usually top-right or in the billing
   section)
2. Add the company card
3. You'll be asked for an initial top-up — **£20 is plenty** to start

### 2.3 Submit your address proof

1. In the console search bar, type **Regulatory Compliance**, then open
   **Bundles**
2. Click **Create new Bundle**
3. Choose **United Kingdom**, and that you're a **business**
4. Upload your proof of address (utility bill or bank statement) and company
   details
5. Submit

This is the part that takes a few days. Once it's submitted you can carry on
with the other steps — nothing else depends on it.

### 2.4 Buy a UK number

Once the bundle is approved:

1. **Phone Numbers → Buy a number**
2. Set country to **United Kingdom**
3. Tick both **Voice** and **SMS** in the capabilities filter
4. Pick a number you like and buy it

> A UK number matters. There's currently a US number on the system, and UK
> mobile networks heavily filter texts sent from US numbers — messages appear to
> send but often never arrive.

### 2.5 Set a spending cap

Search for **Usage triggers** (or **Billing alerts**) and set an alert at around
**£40 per month**.

### 2.6 Invite me

**Account → Manage users → Invite user** → **mohammadrabby.dil@gmail.com**,
with the **Administrator** role.

If your plan doesn't offer user invites, don't worry — see
*"Sending me the keys safely"* near the end of this document.

### ✅ Then tell me

Message me the **new UK phone number** once you have it.

---

## STEP 3 — Vapi (the AI voice)

This is the service that actually speaks to and understands your callers.

### 3.1 Create the account

Go to <https://dashboard.vapi.ai> and sign up with the company email.

### 3.2 Add your card

Find **Billing** in the left-hand menu and add the company card.

Vapi is charged **per minute of call time**, so this is the cost that moves with
how busy you are. Budget roughly 8–12p per minute of calls.

### 3.3 Set a spending limit

In the same Billing section, set a monthly limit — **£100** is a sensible
starting point. You can always raise it.

> This is the one I'd genuinely encourage you not to skip. Because it's billed
> by the minute, a fault that left a call connected is the only realistic way
> this could run up an unexpected bill. A cap makes that impossible.

### 3.4 Invite me

**Organisation → Members → Invite**, using
**mohammadrabby.dil@gmail.com**.

### ✅ Then tell me

Message me *"Vapi is ready"* and I'll do all the assistant configuration —
the voice, the script, the booking logic. That part is my job, not yours.

---

## STEP 4 — Cal.com (the calendar)

This is where confirmed jobs appear.

### 4.1 Create the account

Sign up at <https://cal.com> with the company email. The free plan is fine to
start.

### 4.2 Create the booking type

1. Go to **Event Types** → **New**
2. Title: **Courier Collection**
3. Duration: **60 minutes**
4. Save

### 4.3 Set your operating hours

Go to **Availability** and set it to match when you actually run.
If you cover 24/7, set it to all day, every day.

This matters — the AI checks this before promising a slot to a customer.

### 4.4 Send me two things

1. **The event type ID.** Open the Courier Collection event you just made and
   look at the web address in your browser. It ends in a number:
   `https://app.cal.com/event-types/`**`123456`**
   That number is all I need.
2. **An API key.** Go to **Settings → Developer → API keys → Add**.
   This one is a password — please send it using the safe method below, not by
   email.

---

## STEP 5 — Your booking records

### 5.1 The spreadsheet

1. Go to <https://sheets.google.com> and create a new blank spreadsheet
2. Name the file something like **Courier Bookings**
3. At the bottom left, rename the tab from `Sheet1` to exactly **`Bookings`**
   (capital B — the system looks for that exact name)
4. Copy the web address and send it to me

I'll then send you back a long robot-style email address ending in
`.iam.gserviceaccount.com`. Click **Share** on the spreadsheet, paste it in, and
give it **Editor** access.

That's what lets bookings write themselves into the sheet automatically.

### 5.2 Confirmation emails

Customers get an email confirming their booking. For that, the system needs
permission to send from one of your addresses.

**My recommendation:** create a dedicated address such as
`bookings@yourcompany.co.uk` rather than using your main inbox. If anything ever
needs revoking, it's isolated.

Then:

1. Sign in to that account and turn on **2-Step Verification** at
   <https://myaccount.google.com/security>
2. Go to <https://myaccount.google.com/apppasswords>
3. Create an app password named `Courier Booking System`
4. Google shows you 16 characters — send them to me using the safe method below

> An "app password" is a single-purpose password that only lets software send
> mail. It is **not** your account password, it can't be used to sign in and
> read your email, and you can revoke it any time from that same page.

---

## STEP 6 — Hosting

Right now the system runs on my computer, which means it's only online when my
machine is. Hosting puts it on a proper server so your phone line works at 3am.

Pick whichever you prefer:

- **Easiest:** create an account at <https://railway.app> or
  <https://render.com> with the company card (about £5–10/month), then invite me
- **Alternative:** if you already have a web host or IT provider, tell me who
  and I'll work with them

Once the account exists, I'll do the deployment.

---

## Sending me the keys safely

A few of the items above (the Cal.com key, the email app password) are
effectively passwords. **Please don't send those by email, WhatsApp or text** —
those messages sit on servers and in backups indefinitely.

**The easy safe way:** go to <https://send.bitwarden.com>, paste the text, set it
to expire after 1 day and 1 view, and send me the link it generates. It's free
and needs no account.

If that's awkward, just ring me and read it out.

Anything that isn't secret — the phone number, the spreadsheet link, the event
type ID — is fine to send however you like.

---

## Quick checklist

Print this or tick it off as you go.

**This week:**

- [ ] Google Cloud project created, card added
- [ ] Distance Matrix API enabled
- [ ] £30 budget alert set
- [ ] Invited me to Google Cloud
- [ ] Twilio account created and **upgraded**
- [ ] Address proof submitted to Twilio *(the slow one — do it early)*

**Once Twilio approves:**

- [ ] UK number bought, with Voice and SMS
- [ ] Sent me the new number

**Any time:**

- [ ] Vapi account created, card added, spending limit set
- [ ] Invited me to Vapi
- [ ] Cal.com event type created, availability set
- [ ] Sent me the event type ID and API key
- [ ] Spreadsheet created with a tab named `Bookings`
- [ ] Shared the spreadsheet with the robot address I send you
- [ ] App password created for the sending email address
- [ ] Hosting account created

---

## What happens next

Once Step 1 is done I can turn quoting on the same day, and you'll be able to
ring the test line and hear it price a real job.

Everything after that is configuration on my side. The only things I'll come
back to you for are:

- Confirming the **prices** are right before any real customer hears them
- A **test call together**, so you can hear it and tell me what to change about
  the wording or tone
- Your **mobile number**, for the calls the AI hands over to a human

If anything above doesn't look the way I've described it — these companies
redesign their websites regularly — just send me a screenshot and I'll point you
to the right button.
