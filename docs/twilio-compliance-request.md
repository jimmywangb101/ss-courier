# Twilio compliance — request to lift the long-code provisioning restriction

> **Before sending:** replace `<ACCOUNT SID>` in both places with the real
> Account SID, which is on the front page of the Twilio Console (it starts
> `AC…`). It is deliberately not written into this file — GitHub's secret
> scanning blocks Twilio identifiers from being committed, and an account
> identifier does not belong in a source repository even though it is useless
> on its own without the auth token.

**Send to:** `verifymyaccount@twilio.com`
**From:** the email on the Twilio account (`jimmywangb101@gmail.com`)

## Why this is needed

Buying any UK number currently fails with:

```
22300 — Account is restricted from provisioning new long code Phone Numbers
```

This is **not** an address or compliance-bundle problem. The UK regulatory
bundle is already `twilio-approved`, the account is a full (non-trial) account,
and it holds a £34 balance. The restriction is an account-level hold applied by
Twilio Compliance, common on recently-created accounts, and only Twilio can
lift it.

Verified while diagnosing: the block applies to every long code — a Gravesend
landline and a UK mobile were both refused with the identical error.

---

## The message to send

> **Subject: Request to lift long code provisioning restriction — <ACCOUNT SID>**
>
> Hello,
>
> Our account is currently restricted from provisioning long code phone
> numbers (error 22300), and we would be grateful if the compliance team could
> review it.
>
> **Account details**
>
> - **Account SID:** `<paste from the Twilio Console dashboard>`
> - **Business name:** Salus Securities & Couriers Limited
> - **Company registration number (UK CRN):** 15750459
> - **Website:** https://sscourier.co.uk
> - **Registered address:** 7 St John's Road, Gillingham, Kent, ME7 5NB,
>   United Kingdom
> - **Authorised representative:** Jimmy Wangboje — Info@sscourier.co.uk
> - **Approved UK regulatory bundle:** BUbb9fe3176530f8b642ec1013eb286238
>   ("United Kingdom: Local — Business", status: **approved**)
>
> **What we are building**
>
> We are a same-day courier company in Kent. We have built an automated
> telephone booking line so that customer calls are answered 24 hours a day,
> including overnight and at weekends when no one is in the office.
>
> We would like to purchase one UK local number on the **01634 (Medway)**
> dialling code — the area matching the registered address on our approved
> bundle. It will not be advertised anywhere. Our existing published business
> number, 01474557719, will simply be forwarded to it, so customers continue to
> dial the number they already know and never see this one.
>
> **How we intend to use it**
>
> - **Voice (inbound only).** Customers ring our own advertised number, which
>   forwards to this one. We do not make outbound marketing calls of any kind.
> - **SMS (outbound, transactional only).** After a customer has booked a
>   collection on the phone, they receive a single confirmation text containing
>   their booking reference, the collection date and time, and the agreed
>   price. Nothing else is ever sent.
>
> Every message goes only to a customer who has just given us their number on a
> phone call in order to receive that confirmation. We send no marketing, no
> bulk messaging, and no messages to purchased or third-party lists. There is
> no way for a number to enter our system other than a customer providing it
> during a booking call.
>
> **Expected volume**
>
> Modest and steady: in the region of 100–300 calls per month, with roughly one
> confirmation SMS per completed booking.
>
> We would be happy to provide any further documentation you need — company
> registration, proof of address, or a description of the booking flow.
>
> Thank you for your help.
>
> Kind regards,
> [Your name]
> Salus Securities & Couriers Limited

---

## After they reply

Once the restriction is lifted, everything else is quick:

1. **Buy the number** — Twilio → Phone Numbers → Buy a number → United Kingdom
   → search `1634` → pick any free Medway number (`+441634980582`,
   `+441634949983`, `+441634980994` and `+441634980195` were free at the time
   of writing) → select the **Gillingham ME7 5NB** address and the approved
   bundle.

   It must be an **01634** number: that is the dialling area of the address on
   the approved bundle. It does not need to match the published line (01474),
   because customers never dial it — `01474557719` forwards to it.
2. **Import it into Vapi** — Phone Numbers → Create Phone Number →
   **Import Twilio** → enter the number, the Account SID and the Auth Token.
3. **Assign the assistant** — select **Riley**.
4. **Forward the business line** — ask the phone provider to forward
   `01474557719` to the new number.
5. **Test** — ring `01474557719`, book a job, and confirm it appears in the
   calendar, the spreadsheet and both inboxes.

## If Twilio declines or is slow

Two fallbacks, both usable the same day:

- **A free Vapi US number.** Vapi issues these instantly, no compliance needed.
  Useless for real customers (forwarding a UK landline to a US number bills
  international rates), but it proves the whole inbound telephony path works
  while the UK side is sorted.
- **Another UK provider.** Telnyx or Plivo numbers can also be imported into
  Vapi, and their onboarding is a separate process from Twilio's. Worth trying
  only if Twilio's review drags on — it means a second account to maintain.

Note that SMS is unaffected by any of this. Confirmation texts already send and
deliver through the `SSCourier` alphanumeric sender ID, which needs no number.
