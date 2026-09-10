# Delivery Note — the message to send the client

Copy the text below into an email. Replace `[Client name]` and `[Your name]`
before sending.

**Attach or link:** `HANDOVER.md` and `operating-guide.md`.

**Send separately, via <https://send.bitwarden.com> (set to expire after 1 day
and 1 view) — never in this email:**

- The Google account password for `wangbjimmy70@gmail.com`
- The admin dashboard password

---

> **Subject: Your AI booking line — built, tested and ready to hand over**
>
> Hi [Client name],
>
> The AI booking line is finished. It has been built, deployed, and tested end
> to end with real calls, real texts and real emails. This message explains
> what you have, what is left to do, and how we hand ownership over to you.
>
> ---
>
> ### What it does
>
> A customer rings. An AI assistant answers in a natural British voice, asks
> for the collection and delivery postcodes, the weight, and the date and time.
> It works out the real road mileage, quotes a price from your pricing
> structure, and if the customer says yes, it books the whole job on its own:
>
> - The job goes into your calendar
> - A row is added to your bookings spreadsheet
> - The customer gets a text with their reference and price
> - The customer gets a confirmation email
> - You get a notification email
>
> No one has to be there. It runs 24 hours a day — the calls it catches are the
> ones that would otherwise ring out overnight.
>
> If a load is over 790 kg, or the caller asks for a person, it hands the call
> straight over rather than turning anyone away.
>
> ---
>
> ### What has been tested
>
> I did not want to hand this over on the basis that it *should* work, so every
> part has been verified against the live system:
>
> - **A full booking taken on a real call**, start to finish
> - **A text message delivered** to a real UK mobile, confirmed by the network
> - **Confirmation emails delivered to the inbox**, not the spam folder — the
>   sending domain is properly authenticated
> - **Pricing checked by hand** — a London to Manchester job (211 miles) quotes
>   £385.11, which is correct for your rates
> - **115 automated tests** that run before any future change goes live
>
> That testing was worth doing. It found three faults that would otherwise have
> reached your customers — including one where a booking could end up in the
> spreadsheet and the customer's inbox but not on the driver's calendar, with
> nobody being told. All three are fixed, and the system now emails you if a
> booking ever fails to reach the calendar.
>
> ---
>
> ### One thing still to do
>
> **The line does not yet have a phone number attached.** Everything works —
> the test bookings were made through the system's own test line — but a
> customer dialling a number cannot reach it until a number is connected.
>
> UK phone numbers are regulated, so there is one piece of paperwork in the
> way — and it is the only thing between you and going live:
>
> **What I need from you:** proof of your business address — a utility bill or
> bank statement, less than a year old, showing an address in the Gravesend
> area (it has to match the 01474 dialling code). Not a PO box or a virtual
> office address; those get rejected.
>
> **What happens then:** I submit it to the phone provider, who verify it —
> usually within a few hours, occasionally up to three working days. Once
> approved I buy the number, connect it to the AI, and ask your phone provider
> to forward 01474557719 to it. **Your customers carry on dialling the number
> they already know** — nothing changes for them.
>
> I would not recommend moving 01474557719 itself over to the new provider,
> even though it would save the forwarding step. That takes weeks and puts
> your live business line at risk if anything goes wrong. Forwarding can be
> undone in minutes.
>
> If you would like to hear it on a real phone before the paperwork clears, I
> can set up a temporary test number today at no cost. It would not be
> suitable for customers, but it lets you ring in and hear exactly how it
> handles a call.
>
> ---
>
> ### Handing over ownership
>
> The source code is already in your own GitHub account, so that side needs
> nothing doing. Everything else for this project sits under a Google account
> I created specifically for it: **wangbjimmy70@gmail.com**. That account is the sign-in
> for the AI platform, the calendar, the maps service, the email service and
> the spreadsheet.
>
> I set it up that way on purpose. It means I can hand you the entire system in
> one move, rather than you inheriting a scattered set of logins — and it keeps
> everything separate from any personal account of mine or yours.
>
> **To transfer it, we should spend about half an hour on a call together.** In
> that time you will:
>
> 1. Sign in and **change the password** to one only you know
> 2. Replace the recovery phone and email with yours
> 3. Set up your own two-factor authentication
> 4. Sign out any other devices
>
> After that I have no way back into the account, and I will confirm that to
> you in writing.
>
> We should also, in the same session:
>
> - **Replace all the security keys** — I have necessarily seen them while
>   building this, and replacing them at handover is simply good practice
> - **Move the billing** to your company card and set spending limits
>
> The full step-by-step list is in the handover document attached, so nothing
> depends on either of us remembering it on the day.
>
> ---
>
> ### What it costs to run
>
> The only cost that moves is the AI call time, billed by the minute.
>
> | | Roughly |
> |---|---|
> | Quiet month (~100 calls) | £45–60 |
> | Busier month (~300 calls) | £110–140 |
> | Hosting | ~£6/month, flat |
> | Text messages | ~4p each |
>
> These are estimates for budgeting, not quotes — every provider publishes its
> own current pricing.
>
> **I would strongly suggest setting a spending cap on the AI platform.**
> Because it is billed per minute, a stuck call is the only realistic way this
> could run up a bill unnoticed. A monthly limit removes that possibility
> entirely. I will set these up with you on the call.
>
> For comparison: this is a fraction of the cost of someone answering the phone
> overnight, and the line is covered around the clock.
>
> ---
>
> ### What is attached
>
> - **Handover document** — every account, the transfer checklist, costs, and
>   what to do if something breaks
> - **Operating guide** — plain English, for whoever runs the office. How
>   bookings arrive, which emails need action, and where to look
>
> The passwords are **not** in this email. I will send those separately through
> a secure one-time link.
>
> ---
>
> ### What I need from you
>
> 1. **Proof of your business address** — a utility bill or bank statement,
>    less than a year old, for the Gravesend address. This is the one thing
>    holding up the phone number, so it is worth sending first
> 2. **Half an hour on a call** to transfer the account — let me know when suits
> 3. **Confirm the prices are right** before real customers hear them — worth a
>    two-minute look at the table in the handover document
>
> Once the number is connected, I would suggest we ring the line together so
> you can hear it, and tell me anything you would like changed about the
> wording or the tone. That part is easy to adjust.
>
> Thanks — it has been a genuinely interesting one to build.
>
> Best regards,
> [Your name]
