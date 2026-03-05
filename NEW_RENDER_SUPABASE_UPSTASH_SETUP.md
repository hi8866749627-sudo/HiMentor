# New Render Setup (No Change to Current Render)

This guide creates a separate deployment using:

Cloudflare -> Render (Django + Uvicorn) -> Supabase Postgres -> Upstash Redis

## 1) Create new code/deploy boundary

1. Create a new GitHub repo.
2. Push this project code to that new repo.
3. In new Render account, create a new Web Service from that new repo.
4. Use `render.new-account.yaml` as blueprint (or copy the same values manually).

## 2) Render environment variables

Set these in the new Render service:

- `DATABASE_URL=<SUPABASE_TRANSACTION_POOLER_URL>`
- `REDIS_URL=<UPSTASH_REDIS_URL>`
- `FIXTURE_PATH=core/data_fixture_latest.json` (optional: one-time JSON import during build)
- `DEBUG=False`
- `ALLOWED_HOSTS=.onrender.com,<your-domain>`
- `CSRF_TRUSTED_ORIGINS=https://*.onrender.com,https://<your-domain>`
- `SECURE_SSL_REDIRECT=True`
- `DB_SSL_REQUIRE=True`
- `USE_CACHE_SESSIONS=False`
- `SECRET_KEY=<random-strong-secret>`

Notes:
- Use Supabase transaction pooler URL for app runtime.
- Keep SSL required for Supabase in production.

## 3) Data migration from current app (JSON based)

1. From current production app UI:
   - Go to Live Followup page.
   - Download latest DB backup JSON.
2. Free Render plan does not provide shell. Use one of these:
   - Put backup JSON in repo as `core/data_fixture_latest.json` and set `FIXTURE_PATH=core/data_fixture_latest.json`.
   - Deploy once, then remove `FIXTURE_PATH` (or unset it) to avoid re-import on every deploy.
3. Verify `/healthz/` returns `{"ok": true, ...}`.

## 4) Cloudflare routing

1. Add/Update DNS record to point domain/subdomain to the new Render hostname.
2. Enable Cloudflare proxy (orange cloud).
3. Set SSL/TLS mode to `Full (strict)`.
4. Add final domain to:
   - `ALLOWED_HOSTS`
   - `CSRF_TRUSTED_ORIGINS`

## 5) Go-live checks

1. Login works for superadmin/mentor.
2. Attendance upload works.
3. Results upload works.
4. Call save/update flows work.
5. PDF/Excel export works.
6. Mobile API login and module data work.

## 6) Security actions (important)

Credentials shared in plain text should be treated as exposed.

Rotate all of these before final go-live:
- Supabase database password / connection string
- Supabase publishable key (if not intentionally public for your client use-case)
- Upstash Redis password/URL

After rotation, update only the new Render env vars with rotated values.
