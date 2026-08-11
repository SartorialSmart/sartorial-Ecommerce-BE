# Deploying the API to Vercel

This is the serverless deploy path. The VM path (gunicorn + Celery + nginx)
still works and is documented in `deploy/README.md`; both run from the same
`config.settings.prod` module, which detects the platform at import time.

---

## 1. What changes on serverless

Vercel runs the app as a single function with no always-on process, no Redis,
and a read-only filesystem. Three subsystems adapt automatically:

| Subsystem | On a VM | On Vercel | How it's decided |
|---|---|---|---|
| Cache | Redis | Local memory, 30s TTL on store settings | `REDIS_URL` empty |
| Background tasks | Celery workers | Run inline in the request | No broker configured |
| Recurring jobs | Celery Beat | Vercel Cron → `/api/v1/cron/run/` | `vercel.json` `crons` |

Nothing here requires a separate settings module — leaving `REDIS_URL` unset is
what flips the first two.

### The one behavioural consequence worth knowing

With no worker, work that Celery would have done in the background now happens
**inside the request that triggered it**. Concretely, `POST` of a payment
webhook that marks an order paid also routes the order to its supplier and
sends the confirmation email before it returns. That is why `vercel.json` sets
`maxDuration: 60`. If supplier routing gets slower, raise it (Pro allows up to
300s) or move to the VM deploy.

Task failures are contained: `CELERY_TASK_EAGER_PROPAGATES=False` means a failed
notification or Cloudinary cleanup is logged, not raised into the caller, so a
checkout can't 500 because an email bounced.

---

## 2. One-time setup

### a. Apply migrations

Vercel's build **does not** run migrations — it has no reliable DB access and a
build should not mutate production data. Run them from your machine against the
target database, before the first deploy and after any deploy adding migrations.

`DJANGO_SECRET_KEY` and `DATABASE_URL` are read from your local `.env`, so the
command needs neither:

```bash
DJANGO_SETTINGS_MODULE=config.settings.prod uv run python manage.py migrate
```

Create the first admin user the same way, with `createsuperuser`.

> Avoid passing secrets inline as `VAR="$SOME_VAR"`. If the shell variable is
> unset that expands to an **empty string**, which is present in the environment
> and therefore overrides the setting's default rather than falling back to it.
> Production settings now reject an empty, placeholder, or under-50-character
> `DJANGO_SECRET_KEY` with an explicit message instead of failing later inside
> an unrelated third-party import.

To target a database other than the one in `.env`, set `DATABASE_URL` inline —
but type the value, don't expand an unset variable.

### b. Set environment variables

In the Vercel dashboard (Settings → Environment Variables), for **Production**
*and* **Preview**. `DJANGO_SECRET_KEY` must also be present at **build** time:
`collectstatic` imports production settings, which raise if the key is missing.

**Required**

| Variable | Value |
|---|---|
| `DJANGO_SETTINGS_MODULE` | `config.settings.prod` |
| `DJANGO_SECRET_KEY` | 50+ random chars — `python -c "import secrets;print(secrets.token_urlsafe(64))"` |
| `DATABASE_URL` | The Neon **pooled** URL, query string included |
| `CRON_SECRET` | `python -c "import secrets;print(secrets.token_urlsafe(32))"` |

**Strongly recommended**

| Variable | Why |
|---|---|
| `CORS_ALLOWED_ORIGINS` | Storefront origin(s). Without it, only `localhost:3000` may call the API. |
| `FRONTEND_BASE_URL` | Builds password-reset and email links. |
| `API_PUBLIC_BASE_URL` | The webhook URL shown to admins to paste into the payment dashboard. |
| `DJANGO_ALLOW_VERCEL_PREVIEWS=1` | Preview deploys 400 without it (their hostnames rotate). |

**Leave unset** — `REDIS_URL`, `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND`.
Setting them points the app at a broker that does not exist. In particular do
**not** copy `CELERY_TASK_ALWAYS_EAGER=false` across from `.env.example`.

Then the usual per-integration secrets as you enable them: `CLOUDINARY_*`,
`PAYSTACK_*` / `FLUTTERWAVE_*`, `PAYMENT_WEBHOOK_SECRET`, `ZEPTOMAIL_TOKEN`,
`TELEGRAM_BOT_TOKEN`, `OPENROUTER_API_KEY`.

### c. Deploy

```bash
npx vercel@latest --prod     # or connect the Git repo in the dashboard
```

Vercel detects Django from `manage.py`, installs from `pyproject.toml` +
`uv.lock`, runs `collectstatic` itself, and serves `STATIC_ROOT` from its CDN.

---

## 3. Why the config files look the way they do

- **`pyproject.toml` → `[tool.vercel] entrypoint`** — the project defines both
  `WSGI_APPLICATION` and `ASGI_APPLICATION`, and Vercel prefers ASGI when both
  are present. The app is entirely synchronous, so WSGI is pinned explicitly.
- **`.python-version` → `3.12`** — `requires-python = ">=3.12"` would also
  accept 3.14, which Vercel is moving to as its default. Pinning keeps the
  deployed interpreter identical to the tested one.
- **`vercel.json` → `regions: ["cle1"]`** — Cleveland, co-located with the Neon
  database in AWS `us-east-2`. Every request makes several round trips to
  Postgres, so region mismatch shows up directly as latency. **Change this if
  your database moves.**
- **`DISABLE_SERVER_SIDE_CURSORS`** — Neon's `-pooler` host is PgBouncer in
  transaction-pooling mode, which cannot hold a server-side cursor across
  statements.
- **`DB_CONN_MAX_AGE=0`** — a pooled connection kept across an idle period gets
  reaped server-side and returns as "connection already closed" on the next
  request.

---

## 4. Scheduled jobs

`vercel.json` declares two cron schedules against `/api/v1/cron/run/`, which
calls the same functions Celery Beat would have. Vercel authenticates itself
with `Authorization: Bearer $CRON_SECRET`; the endpoint returns 503 when
`CRON_SECRET` is unset rather than exposing the jobs publicly.

Verify manually:

```bash
curl -H "Authorization: Bearer $CRON_SECRET" \
  "https://<your-app>/api/v1/cron/run/?jobs=refresh-exchange-rates"
```

Jobs: `release-expired-reservations`, `poll-supplier-orders`,
`refresh-exchange-rates`, `sync-suppliers`. Omit `?jobs=` to run all four. A 207
means at least one job failed — the body reports which, and the traceback is in
the function log.

> **Hobby plan:** cron is limited to two jobs running at most once per day, so
> the `*/5 * * * *` schedule in `vercel.json` will not be honoured. Either move
> to Pro, or drive the endpoint from an external scheduler (GitHub Actions,
> cron-job.org) using the same bearer token.

---

## 5. Post-deploy checks

```bash
curl https://<your-app>/api/v1/health/     # {"status":"ok", database ok}
curl https://<your-app>/api/schema/        # OpenAPI document
curl -I https://<your-app>/static/admin/css/base.css   # 200 from the CDN
```

Then load `/django-admin/` and confirm the stylesheet applies — that exercises
static serving, sessions, and CSRF together.

---

## 6. Known gaps

- **Tests run on SQLite, production is Postgres.** SQLite silently ignores
  `select_for_update`, so locking bugs pass CI and fail in production — exactly
  how the `FOR UPDATE`/`DISTINCT` bug in `inventory.release_expired` reached
  this branch. Consider running the suite against Postgres in CI.
- **`CATALOG_IMAGE_BACKEND`** defaults to `static` when no Cloudinary cloud name
  is set, which serves image paths the storefront must host. Set the
  `CLOUDINARY_*` variables to serve real uploads.
- **`generate_product_images`** writes to the filesystem and cannot run on
  Vercel (read-only outside `/tmp`). Run it locally and commit the output.
- **In-memory cache is per-instance.** An admin settings change takes up to
  `CACHE_SETTINGS_TIMEOUT` (30s) to appear on every warm instance. Attach a
  managed Redis and set `REDIS_URL` to make invalidation immediate — that also
  restores real background workers if you add a worker host.
