# Deploying to Render

This replaces the current setup — your laptop + ngrok — with a server that's
always on. Do this once the client has admin access set up on the Render
workspace and a card is on file (see the earlier accounts message).

Everything below is one-time setup. After this, `git push` deploys automatically.

---

## 1. Push the code to GitHub

Render deploys from a GitHub (or GitLab) repo — it can't pull from your laptop
directly. The local repo already exists and is committed; it just needs a
remote.

1. Go to [github.com/new](https://github.com/new), create a repo (e.g.
   `courier-booking-api`). **Private**, not public — this is a client's live
   business system. Don't tick "Add a README" (the repo already has files).
2. Push:

   ```powershell
   git remote add origin https://github.com/<your-username>/courier-booking-api.git
   git branch -M main
   git push -u origin main
   ```

**Check before you push:** `.env`, `api/service-account.json` and `logs/*.jsonl`
must NOT appear in `git status`. They're excluded by `.gitignore` — this was
already verified when the repo was created, but it's cheap to check again:

```powershell
git status
```

---

## 2. Create the service on Render

1. In the Render dashboard: **New +** → **Blueprint**
2. Connect the GitHub repo you just pushed
3. Render reads `render.yaml` from the repo root automatically and proposes
   the service — name, plan (`starter`), region (`frankfurt`), build and start
   commands are all already set. Click **Apply**.

It will build and try to start, then most likely **crash on first boot** — the
secret env vars aren't filled in yet. That's expected; continue to step 3.

---

## 3. Upload the Google service-account key as a Secret File

`api/service-account.json` is deliberately not in git — it's a credential.
Render has a separate mechanism for files like this that never touches the
git history.

1. On the service page: **Environment** tab → **Secret Files** → **Add Secret File**
2. **Filename**: `/etc/secrets/service-account.json` (must match exactly —
   `render.yaml` already points `GOOGLE_SERVICE_ACCOUNT_JSON` at this path)
3. **Contents**: open your local `api/service-account.json`, paste the whole
   JSON in
4. Save

---

## 4. Fill in the secret environment variables

Still on the **Environment** tab, under **Environment Variables**. `render.yaml`
already declared which keys exist (`sync: false` ones need a value from you);
this is where you paste the values.

Open your local `.env` side by side and copy each of these across:

| Render variable | Copy from `.env` |
|---|---|
| `GOOGLE_MAPS_API_KEY` | same |
| `GOOGLE_SHEETS_ID` | same |
| `TWILIO_ACCOUNT_SID` | same |
| `TWILIO_AUTH_TOKEN` | same |
| `TWILIO_FROM_NUMBER` | same (`SSCourier`) |
| `CAL_API_KEY` | same |
| `CAL_EVENT_TYPE_ID` | same |
| `VAPI_PRIVATE_KEY` | same |
| `VAPI_SERVER_SECRET` | same |
| `CLIENT_EMAIL` | same |
| `CLIENT_PHONE_NUMBER` | same |
| `SMTP_USER` | same |
| `SMTP_PASSWORD` | same |

Leave `NGROK_URL` blank for now — you don't know Render's assigned URL until
after the first successful deploy (step 5).

Save. This triggers a redeploy.

---

## 5. Get the assigned URL and point everything at it

Once the deploy goes green, the service page shows a URL like:

```
https://courier-booking-api.onrender.com
```

1. Add it as the `NGROK_URL` env var (yes, despite the name — nothing in the
   code was renamed after moving off the tunnel) and save
2. **Verify it's actually serving:**

   ```powershell
   curl https://courier-booking-api.onrender.com/health
   ```

   You want to see every integration `true` except Twilio (still pending
   Trust Hub) — the same output `/health` gives locally.

3. **Repoint Vapi at the new URL.** Update `NGROK_URL` in your *local* `.env`
   too (so the script below picks it up), then:

   ```powershell
   .\venv\Scripts\python.exe scripts\configure_vapi.py
   ```

   This rewrites the assistant's webhook server URL from the ngrok tunnel to
   the Render address. Reload the Vapi dashboard tab afterward before touching
   Publish, same rule as always.

4. **Test with a real call** — click Talk in Vapi, or ring the number if it's
   attached to one. Watch Render's **Logs** tab (not your terminal — the app
   is running there now) for `Vapi webhook: type=tool-calls`.

---

## 6. You can now stop running things locally

Once step 5's test call works, your laptop and ngrok are no longer part of the
live system. You can close them. The API runs on Render continuously.

**For future development:** keep working locally (`uvicorn --reload`) against
your `.env` as before — that's still the right way to build and test changes.
Only `main` pushed to GitHub reaches production.

---

## Updating the live service later

```powershell
git add -A
git commit -m "describe the change"
git push
```

Render redeploys automatically. If you only changed an env var (not code), do
that directly in the Render dashboard — no push needed, it redeploys on save.

---

## If something goes wrong

| Symptom | Likely cause |
|---|---|
| Build succeeds, health check fails | Missing/wrong Secret File path — must be exactly `/etc/secrets/service-account.json` |
| `/health` shows `google_sheets: false` | Secret File missing, or the sheet was never shared with the robot email |
| 502 / service unavailable right after deploy | Normal for a few seconds while it boots — retry |
| Vapi calls don't reach the server | `NGROK_URL` env var wasn't updated, or `configure_vapi.py` wasn't re-run after updating it |
| Logs show nothing when you call | You're watching your local terminal, not Render's **Logs** tab |
