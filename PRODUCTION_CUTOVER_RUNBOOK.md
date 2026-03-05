# EasyMentor Production Cutover Runbook (Cloudflare + Render + Supabase + Upstash)

This runbook is designed for **zero-risk migration** from expiring Render DB to persistent Supabase Postgres.

## 1) Create managed services (manual dashboard steps)

1. Create Supabase project (Postgres).
2. Copy Supabase `DATABASE_URL` (transaction/pool URL preferred for app usage).
3. Create Upstash Redis database.
4. Copy Upstash `REDIS_URL`.

## 2) Render environment variables (manual)

Set these on your Render web service:

- `DATABASE_URL=<supabase_postgres_url>`
- `REDIS_URL=<upstash_redis_url>`
- `DEBUG=False`
- `ALLOWED_HOSTS=.onrender.com,yourdomain.com`
- `CSRF_TRUSTED_ORIGINS=https://*.onrender.com,https://yourdomain.com`
- `SECURE_SSL_REDIRECT=True`
- `DB_SSL_REQUIRE=True`
- `SECRET_KEY=<strong-random>`

Optional:
- `USE_CACHE_SESSIONS=False` (keep False unless needed)
- `SECURE_HSTS_SECONDS=31536000`
- `SECURE_HSTS_INCLUDE_SUBDOMAINS=True`
- `SECURE_HSTS_PRELOAD=True`

## 3) Cloudflare (manual)

1. Add your domain DNS record pointing to Render service hostname.
2. Enable proxy (orange cloud).
3. SSL/TLS mode: `Full (strict)`.
4. Keep cache bypass for dynamic pages if needed.

## 4) Zero-risk migration flow

### A. Pre-cutover validation (no downtime)

1. Deploy current app code.
2. Ensure `/healthz/` returns JSON `ok:true`.
3. Take backup from app: `Live Followup Sheet -> Download DB Backup (JSON)`.

### B. Final data export (freeze writes for 5-10 min)

1. Announce short maintenance window.
2. Take **fresh** JSON backup from production app.

### C. Import to Supabase-connected app

Run on app with `DATABASE_URL` set to Supabase:

```bash
python manage.py migrate
python manage.py loaddata latest_backup.json
python manage.py check
```

### D. Go live

1. Restart Render service.
2. Verify:
   - Login
   - Module switch
   - Attendance upload
   - Result upload
   - Call save flows
   - PDF/Excel export

## 5) Rollback plan

If any issue:

1. Switch Render `DATABASE_URL` back to previous DB.
2. Restart service.
3. App returns to previous state.

## 6) Ongoing backup discipline

1. Download JSON backup daily/weekly from Live Followup page (SuperAdmin).
2. Also keep Supabase automated backups enabled.

