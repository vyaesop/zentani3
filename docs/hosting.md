# Hosting Decision (P4 of the Performance & UX Overhaul)

## Recommendation: Railway

One small always-on host removes cold starts, gives the task queue a real worker
process, and gives Redis a home. Railway is recommended because:

- The project already used Railway Postgres before (familiar console/billing).
- One-click Postgres + Redis add-ons; `Procfile` in this repo already defines
  `web`, `worker`, and `release` (migrations) processes.
- Fly.io / Render / a small Hetzner VPS are equally fine — the requirement is
  simply: **1 web process (gunicorn) + 1 worker process
  (`manage.py run_tasks --forever`) + managed Postgres + Redis.**

## If staying on Vercel (works today, no action required)

The rest of the overhaul does not depend on migrating:

- `vercel.json` now defines a cron hitting `GET /internal/run-tasks/` every
  minute; set the `CRON_SECRET` env var and Vercel sends it automatically as a
  bearer token. (You can also call it manually with the `X-Run-Tasks-Secret`
  header.)
- Provision an Upstash Redis (free tier) and set `REDIS_URL` so caching and
  `cached_db` sessions work across lambdas.
- Accept the remaining cold starts.

## Migration checklist (if/when moving)

1. Provision Postgres + Redis on the new host.
2. Copy data: `pg_dump --no-owner $OLD_DATABASE_URL | psql $NEW_DATABASE_URL`.
3. Set env vars: `DATABASE_URL`, `REDIS_URL`, `DJANGO_SECRET_KEY`, `SITE_URL`,
   `ALLOWED_HOSTS`, Cloudinary (`CLOUDINARY_CLOUD_NAME/API_KEY/API_SECRET`),
   Telegram (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_ALERT_CHAT_ID`,
   `TELEGRAM_CUSTOMER_BOT_TOKEN`, `TELEGRAM_CUSTOMER_CHANNEL_CHAT_ID`,
   `TELEGRAM_CUSTOMER_BOT_USERNAME`, webhook secrets), `GEMINI_API_KEY`,
   AI image generator vars.
4. Deploy; the `release` process runs migrations, `web` serves (whitenoise
   handles static files), `worker` drains the task table continuously.
5. Re-register the Telegram webhooks against the new domain
   (`setWebhook` with `secret_token`), verify with a test message.
6. Point DNS, watch logs, then decommission the Vercel project and delete the
   `crons` block from `vercel.json` (the always-on worker replaces it).

## Acceptance

- p50 TTFB on a cold visit drops (no cold starts).
- The `worker` process drains `BackgroundTask` rows continuously (check the
  dashboard → Background Tasks page).
- Deploys are boring.
