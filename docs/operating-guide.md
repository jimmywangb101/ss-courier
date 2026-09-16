# Operating Guide — Your AI Booking Line

For whoever runs the office. No technical knowledge needed. Nothing in here
requires you to touch the code.

---

## What happens when a customer rings

Customers ring **01634 980038**. You do not have to do anything. The
assistant handles the whole call:

1. It answers with *"Hello, you're through to SS Courier. How can I help you
   today?"*
2. It asks for the collection postcode, the delivery postcode, the weight, and
   the date and time.
3. It works out the real road mileage and quotes a price.
4. If the customer says yes, it takes their name, mobile and email.
5. It books the job.

Within seconds of the call ending, all of this happens on its own:

- The job appears in **your calendar**
- A row is added to the **bookings spreadsheet**
- The **customer gets a text** with their reference and the price
- The **customer gets an email** with the full details
- **You get an email** headed `NEW BOOKING`

---

## When it hands the call to a person

The assistant passes the caller to a human in two situations:

- **The load is over 790 kg** — bigger than the van, so it does not quote. It
  says it is putting them through to someone who can arrange a larger vehicle.
- **The caller asks for a person** — at any point, for any reason.

It never simply rejects a caller. Both cases become a transfer, not a dead end.

---

## Your three places to look

### 1. The dashboard — the quick glance

**`https://courier-booking-api.onrender.com/admin`**

Sign in with the username and password sent to you separately. It shows recent
bookings, newest first, with today's highlighted and a count of today's jobs at
the top. It refreshes itself every minute.

Use this when you want to see what has come in without opening anything else.

> This page shows customers' names, phone numbers and addresses. Treat the
> password like a key to the filing cabinet — do not share it outside the
> office, and ask for it to be changed if someone with it leaves.

### 2. The spreadsheet — the full record

Every booking, every column: reference, customer, phone, email, both
addresses, weight, mileage, price, date and time.

This is the system's permanent record. You can sort it, filter it, and use it
for invoicing.

### 3. The calendar — what the driver works from

Each confirmed job appears as a one-hour slot, with the pickup, dropoff, weight
and price in the entry.

**Set your availability here to match when you actually run.** The assistant
checks this before promising a slot. If you cover 24/7, set it to all day,
every day.

---

## The emails you will receive

### `NEW BOOKING CRR-… — …` — normal

A job has been booked. Everything is already in the calendar and spreadsheet.
Nothing to do.

### `ACTION NEEDED — booking could not be completed automatically` — read this one

Something stopped a booking completing. The email says exactly what went wrong
and includes every detail captured on the call, so you can ring the customer
back and sort it by hand.

**This is the only email that needs you to act.** It is deliberately rare — if
these start arriving often, something is wrong and your developer should look.

You may also get one saying a booking **is not on the calendar**. The customer
has been confirmed and texted, but the calendar entry failed — add it manually,
or the driver will not see the job.

---

## Cancelling a booking

Bookings are not connected to your website. They live in your calendar and
your spreadsheet. To cancel one:

1. **Calendar (Cal.com):** open the booking and press **Cancel**. This frees
   the time slot.
2. **Spreadsheet:** delete the row, or type **CANCELLED** next to it.
3. **Let the customer know.** Nothing tells them automatically.

The bookings dashboard only shows bookings; it cannot cancel them.

---

## Understanding a booking reference

Every booking gets one, like:

```
CRR-20261015-K7Q4
 │      │       └── random, to keep them unique
 │      └────────── the collection date: 15 October 2026
 └───────────────── always CRR
```

Customers are asked to quote it when they ring back. The random part
deliberately avoids the letters and numbers people mishear on the phone —
there is no O, I, S or Z in it, so a `0` is always a zero.

---

## The quote box for your website

There is a small "get an instant quote" box you can put on your website. A
visitor types two postcodes and a weight and sees a real price, with a button
to ring you and book.

Give your web person this one line:

```html
<iframe src="https://courier-booking-api.onrender.com/widget/quote"
        width="100%" height="480" style="border:0"></iframe>
```

It works on any website platform — no plugins, no custom code, nothing to
install.

---

## Things worth knowing

**Customers cannot reply to the text messages.** They are sent from the name
`SSCourier` rather than a phone number, so replies go nowhere. The text tells
customers to ring back and quote their reference.

**Times are assumed to be daytime.** If a caller says "half two", the assistant
books 14:30, not 02:30. It reads the time back before finishing so a mistake
gets caught on the call.

**If the calendar service is ever unreachable, it still takes the booking.**
This is deliberate: it is better to risk a double booking you can sort out than
to tell a paying customer you are full when you are not.

**It does not check the calendar before agreeing a time.** If two customers
ask for the same slot, the second customer still gets a confirmation, but the
booking cannot go into the calendar. You will get an email saying it is **not
on the calendar**, so you can rearrange it with them.

**It never invents a price.** It only ever says the figure the pricing system
returns. If it cannot work out the mileage, it apologises and hands the caller
to a person rather than guessing.

---

## Changing things

These all need your developer — none is a big job:

| You want to | What it involves |
|---|---|
| Change the prices | One line in a settings file |
| Change what the assistant says | Editing the greeting or its instructions |
| Change the voice | A different voice can be selected |
| Change the weight limit | One line |
| Change who gets the booking emails | One setting |
| Add a second phone number | Configuration in the AI dashboard |

---

## If something looks wrong

Open **`https://courier-booking-api.onrender.com/health`** in any browser.

You will see a short block of text listing each connected service as `true` or
`false`. If everything says `true`, the system is healthy. Anything saying
`false` is the problem — send a screenshot to your developer and it will tell
them exactly where to look.

If bookings have stopped arriving entirely, check that first before anything
else.
