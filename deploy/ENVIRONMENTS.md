# Environment checklists — SartorialEcommerce API

Settings module: `config.settings.dev` locally, `config.settings.prod` on
servers/serverless. All secrets come from the environment (`.env` locally,
platform env vars in prod). Branding defaults live in `config/branding.py`.

## Local (laptop, no services)

- `DJANGO_SETTINGS_MODULE=config.settings.dev`
- `DJANGO_SECRET_KEY` — any dev value (never reuse in staging/prod)
- `USE_SQLITE=1` for a service-free run, or `POSTGRES_*` pointing at local Postgres
- Leave `REDIS_URL` empty → locmem cache + inline Celery (correct for dev)
- `PAYMENT_PROVIDER=mock`, `RATES_PROVIDER=mock`, `CATALOG_IMAGE_BACKEND=mock`
- `TENANT_SLUG=` empty (multi-tenant resolution via `X-Tenant-Slug` header)
- Run: `uv sync && uv run python manage.py migrate && make seed && make run`

## Staging (mirror of prod, test data only)

- `DJANGO_SETTINGS_MODULE=config.settings.prod`
- `DJANGO_SECRET_KEY` — generated, ≥50 chars, unique to staging
- `DATABASE_URL` (managed Postgres, e.g. Neon) with `?sslmode=require` intact
- `REDIS_URL` set (real worker + beat) or empty (inline tasks — document which)
- `API_PUBLIC_BASE_URL=https://<staging-api-host>` (drives webhook URLs + CSRF)
- `CORS_ALLOWED_ORIGINS=https://<staging-storefront-host>`
- `DJANGO_CSRF_TRUSTED_ORIGINS=https://<staging-api-host>`
- Live-test keys only: Paystack/Flutterwave **test** keys, `RATES_PROVIDER` real or mock
- `NOTIFICATIONS_EMAIL_BACKEND=console`, `NOTIFICATIONS_TELEGRAM_BACKEND=console`
- `CRON_SECRET` set (else `/api/v1/cron/run/` returns 503)
- Verify: `manage.py check`, migrations applied, `seed_currencies`, admin login,
  register → basket → checkout → mock payment → paid order

## Production (real money, real tenants)

- [ ] `DJANGO_SECRET_KEY` real, ≥50 chars (prod boots refuse placeholders)
- [ ] `DATABASE_URL` production Postgres + backups + restore rehearsed
- [ ] `REDIS_URL` production Redis (workers + beat running as services)
- [ ] `API_PUBLIC_BASE_URL=https://<api-domain>` (webhook URL in gateway dashboards)
- [ ] `PAYMENT_PROVIDER=paystack|flutterwave` + live `*_SECRET_KEY` (+ Flutterwave secret hash)
- [ ] `RATES_PROVIDER` live source + `CURRENCY_API_NET_KEY` if needed; base currency `NGN`
- [ ] Cloudinary live account (`CLOUDINARY_URL` or trio) + `CLOUDINARY_UPLOAD_FOLDER`
- [ ] `NOTIFICATIONS_EMAIL_BACKEND=zeptomail` + `ZEPTOMAIL_TOKEN`; `EMAIL_FROM_*`, `SUPPORT_EMAIL`
- [ ] `TELEGRAM_BOT_TOKEN` + `TELEGRAM_DEFAULT_CHAT_ID` (ops alerts)
- [ ] `CRON_SECRET` set + GitHub `API_BASE_URL`/`CRON_SECRET` secrets for `cron.yml`
- [ ] `CORS_ALLOWED_ORIGINS` = real storefront origin(s) only
- [ ] `FRONTEND_BASE_URL` = real storefront URL (password-reset + payment return URLs)
- [ ] Per-tenant: `Tenant` rows (`erp_subscriber` with `erp_business_id` vs `independent`),
      owner memberships, `TenantApiKey` issued to the ERP per subscriber store
- [ ] Launch checklist (report §13 Phase 6): security review, backup rehearsal,
      monitoring/alerting + runbook, staging rehearsal, signed checklist, rollback tested

## Type-checking position

Strict mypy reports pre-existing findings and gates nothing. CI runs it as
non-blocking informational. Do not add it as a required check until the
codebase adopts the lighter (non-strict) settings per technical report §7.
