# SecureGate — Deployment Guide (Vercel + Render + Supabase PostgreSQL)

This app has 3 pieces:

| Piece | What it is | Where it lives |
|---|---|---|
| Frontend | React + TypeScript app | **Vercel** (free) |
| Backend | Django + DRF API | **Render** (free) |
| Database | PostgreSQL | **Supabase** (free) |

No Docker, no Kubernetes, no terminal servers — just clicking through 4 websites.
Everything is connected with environment variables (values you paste into each site).

---

## Before you start

- Make sure the latest code is committed and pushed to GitHub
  (`git push origin main`). Render and Vercel deploy straight from GitHub.
- You need accounts on: GitHub, Supabase, Render, Vercel (all free).

---

## 1. Create the database on Supabase  (REQUIRED)

1. Go to <https://supabase.com> → **Start your project** → sign in with GitHub.
2. Click **New project**.
   - **Project name**: `SecureGate`
   - **Database password**: create one using **only letters and numbers**
     (avoids URL problems — no `@`, `/`, `:`, `+`). Save it somewhere safe.
   - **Region**: pick the closest one to you.
   - **Create new project**. Wait 2–3 minutes for it to finish starting.
3. Open **Project Settings** (gear icon, bottom-left) → **Database** tab.
4. Under **Connection string**, pick **Session pooler** (port `5432`).
   Copy the whole string. It looks like:

   ```
   postgresql://postgres.abcdefghijklmnop:YOUR-PASSWORD@aws-0-us-east-1.pooler.supabase.com:5432/postgres
   ```

   This is your **`DATABASE_URL`**. Keep it; you need it in Section 2 and 3.

   > Optional — if the copied string ends with `?pgbouncer=true&connection_limit=1`,
   > delete that part. The app also tolerates it, so don't stress about it.

Expected result: a Supabase project with nothing in the database yet (you migrate it in Section 3).

---

## 2. Deploy the backend on Render  (REQUIRED)

1. Go to <https://render.com> → **Get Started** → sign in with GitHub → **Authorize**.
   (In GitHub settings, make sure the `Secure_Gate` repo is visible to Render.)
2. Click **New +** (top-right) → **Web Service** → connect the `Secure_Gate` repository.
3. Fill in:
   - **Branch**: `main`
   - **Name**: `securegate-api` → this becomes your URL:
     `https://securegate-api.onrender.com`
   - **Root Directory**: `backend`
   - **Environment**: `Python 3`
   - **Build Command**:
     ```
     pip install -r requirements.txt && python manage.py collectstatic --noinput
     ```
   - **Start Command**:
     ```
     gunicorn config.wsgi:application --bind 0.0.0.0:$PORT --workers 2 --timeout 60
     ```
4. **Instance Type**: `Free` (or Starter if you want it to stay awake longer).
5. Click **Create Web Service**. The first build may fail — that's expected; you
   still need to add the secrets below.
6. While it builds, open the service page → **Environment** tab → **Add Environment
   Variable** for each of these:

   | Variable | Value | Where it comes from |
   |---|---|---|
   | `DJANGO_ENV` | `production` | Required for the safety checks |
   | `DJANGO_DEBUG` | `False` | Must be False in production |
   | `SECRET_KEY` | a random 50-character string | Generate at <https://djecrety.ir> (or any random string) |
   | `ALLOWED_HOSTS` | `securegate-api.onrender.com` | Your Render service name + `.onrender.com` |
   | `DATABASE_URL` | the Supabase string from Section 1 step 4 | Supabase settings page |
   | `CORS_ALLOWED_ORIGINS` | `https://your-app.vercel.app` (placeholder for now) | Update after Section 4 |
   | `CSRF_TRUSTED_ORIGINS` | same as above | Update after Section 4 |

   Click **Save Changes**, then **Manual Deploy** → **Deploy Latest Commit**.

7. When the deploy finishes, open:
   ```
   https://securegate-api.onrender.com/api/health/
   ```
   You should see JSON like `{"status":"ok"}`.

   > Free Render “sleeps” after ~15 minutes of no traffic. The first request after
   > sleeping takes ~30–60 seconds to wake up. This is normal and free-tier behavior.

Expected result: a live backend that answers `/api/health/`.

---

## 3. Create the database tables (run migrations)  (REQUIRED)

Your new database is empty. Django must create the tables. The simplest safe way is
from your own computer:

Open a terminal in the `backend/` folder and run:

**Windows (PowerShell):**
```powershell
$env:DATABASE_URL="postgresql://postgres.abcdefghijklmnop:YOUR-PASSWORD@aws-0-us-east-1.pooler.supabase.com:5432/postgres"
.venv\Scripts\python.exe manage.py migrate
```

**macOS / Linux:**
```bash
export DATABASE_URL="postgresql://postgres.abcdefghijklmnop:YOUR-PASSWORD@aws-0-us-east-1.pooler.supabase.com:5432/postgres"
source .venv/bin/activate
python manage.py migrate
```

Expected result: a list that ends with `Applying ... OK` for all migrations.
The Supabase database now has all tables.

> If you instead used Render's `render.yaml` Blueprint, Render runs `python manage.py
> migrate` automatically before each deploy, so you can skip this section.

---

## 4. Deploy the frontend on Vercel  (REQUIRED)

1. Go to <https://vercel.com> → sign in with GitHub → **Add New…** → **Project**.
2. Import the `Secure_Gate` repository.
3. Leave the defaults (Vercel auto-detects **Vite**):
   - Build Command: `npm run build`
   - Output Directory: `dist`
4. Click **Environment Variables** and add:

   | Variable | Value | Where it comes from |
   |---|---|---|
   | `VITE_API_BASE_URL` | `https://securegate-api.onrender.com` | Your Render backend URL from Section 2 |

5. Click **Deploy**. After ~1 minute it gives you a frontend URL:
   ```
   https://securegate-xxxx.vercel.app
   ```
   Copy it exactly (no trailing slash).

Expected result: the landing page loads at your Vercel URL.

---

## 5. Link them together — final wiring  (REQUIRED)

1. Go back to Render → `securegate-api` → **Environment** tab.
2. Update the two placeholder values:
   - `CORS_ALLOWED_ORIGINS` = your exact Vercel URL, e.g. `https://securegate-xxxx.vercel.app`
   - `CSRF_TRUSTED_ORIGINS` = same value
3. **Save Changes** → **Manual Deploy** → **Deploy Latest Commit**. Wait 1–2 minutes.

Now the browser app (Vercel) is allowed to talk to the API (Render).

---

## 6. Test everything  (REQUIRED)

1. Open the **Vercel URL** → landing page loads.
2. **Get Started → Register** → create your account.
3. **Create workspace** (onboarding) → you become the Administrator.
4. **Register a visitor** (name, phone, company, document, host, building) → status shows `PENDING`.
5. **Approvals** page → **Approve** → status becomes `APPROVED` and a QR pass is generated.
6. **Visitors** → open the visitor → check in → `CHECKED_IN`. Check out → `CHECKED_OUT`.
7. **Reports** → export CSV and switch daily/weekly/monthly.
8. Check the **audit log** — you'll see registration, approval, check-in entries.

If the QR email doesn't arrive, that's OK — email sending is optional (Section 7) and
passes are printable/scanable from the visitor's profile.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `/api/health/` fails | Check `DATABASE_URL` and `ALLOWED_HOSTS` in Render env vars |
| Frontend shows CORS / network errors | `VITE_API_BASE_URL` on Vercel must be the Render URL; `CORS_ALLOWED_ORIGINS` on Render must be the exact Vercel URL (no trailing slash) |
| Backend very slow on first request | Free Render slept — just wait, it wakes up |
| Migrations error about `pgbouncer` | Remove `?pgbouncer=true&connection_limit=1` from the end of `DATABASE_URL` |
| “Host does not exist” when registering | No **Employee** exists yet — create one in the workspace/Admin first |

---

## REQUIRED NOW

1. Create a **Supabase** project and copy the *Session pooler* connection string.
2. Create a **Render** web service from the repo (root `backend`) and add the 7
   environment variables from Section 2.
3. Run `python manage.py migrate` against the Supabase URL (Section 3).
4. Create a **Vercel** project from the repo, add `VITE_API_BASE_URL`, and deploy.
5. Set `CORS_ALLOWED_ORIGINS` / `CSRF_TRUSTED_ORIGINS` on Render to your Vercel URL
   and redeploy.
6. Test the 10 actions in Section 6.

## OPTIONAL LATER

- **Real emails**: set `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD` (a Gmail *App
  Password*), `DEFAULT_FROM_EMAIL` on Render so QR passes are emailed on approval.
- **Custom domain** for the frontend/backend (Vercel/Render settings).
- **Paid plans** so the server never sleeps (Render Starter) and unlimited builds.
- **Auto-archive old visits**: schedule Django's archiving task daily (Render Cron Jobs
  or any scheduler) — completed visits older than 30 days get archived.
- **Docker + dedicated Postgres tuning**: only if the project grows.