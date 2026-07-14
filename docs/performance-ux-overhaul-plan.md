# Zentanee Performance & UX Overhaul Plan

## Goal
Make the storefront and dashboard feel instant without rewriting the app. The Django monolith with server-rendered templates is the right architecture for an SEO-dependent single-store brand — every problem below is fixable in place. No framework migration, no API layer, no big-bang restyle.

## Principles
- Fix in place; never rewrite what already works.
- Nothing user-facing waits on a third-party API (Telegram, Gemini, image generator).
- The database is queried once per thing per request; repeated scans are consolidated or cached.
- Images are served at the size and format the device needs, computed by Cloudinary, not by our server.
- One interaction pattern (htmx partial re-render) replaces the ad-hoc fetch/JSON endpoints.
- Each phase ships independently and leaves the app deployable.

## Effort & Impact Summary

| Phase | Theme | Effort | User-visible gain |
|-------|-------|--------|-------------------|
| P0 | Security & housekeeping | 0.5 day | None (risk removal) |
| P1 | Background jobs / unblock requests | 1–2 days | Checkout & dashboard saves become instant |
| P2 | Cloudinary image delivery | 1 day | Biggest storefront speed win (LCP) |
| P3 | Real caching + query fixes | 1–2 days | Faster browse/search/orders pages |
| P4 | Hosting decision | 0.5–1 day | Kills cold starts; enables P1/P3 fully |
| P5 | Frontend unification (htmx + CSS) | 3–5 days, incremental | SPA-feel cart/filters/wishlist |
| P6 | Code structure & model cleanup | 2–3 days, incremental | Developer velocity, fewer bugs |

Phases P0–P3 are the core: roughly 4–5 days of work for the large majority of the perceptible improvement.

---

## P0 — Security & Housekeeping
Status: Not started
Depends on: nothing. Do this first; it is half a day.

### 0.1 Rotate leaked database credentials
Real passwords sit in commented-out blocks in `jewelryshop/settings.py` (Supabase block around line 131, Railway block around line 146). They are in git history permanently.
- [ ] Rotate the Supabase database password (or delete the project if unused).
- [ ] Rotate the Railway database password (or delete the service if unused).
- [ ] Delete both commented-out `DATABASES` blocks from `settings.py`.
- [ ] Verify no other secrets are committed: grep the repo for `PASSWORD`, `API_KEY`, `SECRET`, `token` outside `.env`.
- [ ] Remove the hard-coded fallback `SECRET_KEY` default (line 24) in production paths — raise `ImproperlyConfigured` instead when `DEBUG=False` and no key is set.

### 0.2 Remove dead weight
- [ ] Delete `djangorestframework` from `requirements.txt` — it is never imported anywhere.
- [ ] Delete one of the two byte-identical FastAPI image workers: keep `zentanee/` (it is the deployed HF Space with its own git) and remove `hf_image_worker/` from this repo, or vice versa. Document the survivor in `docs/hf-image-worker.md`.
- [ ] Deduplicate the Telegram webhook routes registered twice with/without trailing slash in `store/urls.py` (~lines 74–79) — `APPEND_SLASH` or a single canonical form.
- [ ] Delete `jewelryshop/v.html` if it is scratch.

**Acceptance:** old DB credentials no longer work; `pip install -r requirements.txt` is smaller; one image-worker copy remains; deploy still succeeds.

---

## P1 — Get Blocking Work Out of the Request Path
Status: Not started
Depends on: P0. Works on current hosting via cron endpoint; becomes nicer after P4.

This is the single biggest UX fix in the plan. Today every one of these runs synchronously inside a user-facing request:

| Call site | What blocks | Who waits |
|-----------|-------------|-----------|
| `store/signals.py:14,26` | Telegram post on Product/ProductImages save | Admin & dashboard staff |
| `store/views.py:2099` | `notify_new_order` (Telegram) after checkout | **The buyer**, on the order-placed screen |
| `store/views.py:1548` | `notify_new_signup` (Telegram) | New registrants |
| `store/dashboard_views.py:640,786` | Gemini enrichment, `timeout=90` | Dashboard staff, up to 90 s |
| `store/models.py:254–264` | Pillow webp conversion in `save()` | Anyone uploading images (fixed properly in P2) |

### 1.1 Build a minimal outbox queue
No Celery, no Redis broker — a plain database table drained by a worker. This survives serverless.
- [ ] Add a `BackgroundTask` model: `task_type` (choices: `telegram_product_post`, `telegram_order_notify`, `telegram_signup_notify`, `ai_enrich_draft`), `payload` (JSONField), `status` (`pending`/`running`/`done`/`failed`), `attempts`, `last_error`, `run_after`, timestamps. Index on `(status, run_after)`.
- [ ] Add `store/tasks.py` with `enqueue(task_type, payload)` and `run_pending(limit=10)` that claims rows with `select_for_update(skip_locked=True)`, dispatches to a handler per `task_type`, retries with backoff (max 5 attempts), and records `last_error`.
- [ ] Add a management command `python manage.py run_tasks` that calls `run_pending()` (loop mode with `--forever` for always-on hosting; single-pass default for cron).
- [ ] Add an HTTP trigger `POST /internal/run-tasks/` guarded by a shared-secret header, for Vercel Cron (every minute) while still on serverless.

### 1.2 Migrate the call sites
- [ ] `signals.py`: replace direct `post_product_to_channel(...)` calls with `enqueue('telegram_product_post', {...})`. Keep the existing `suspend_telegram_autopublish()` semantics — suspension should skip the enqueue, not the send.
- [ ] `views.py` checkout: replace `notify_new_order(...)` with an enqueue **after** the order transaction commits (`transaction.on_commit`).
- [ ] `views.py` registration: same for `notify_new_signup`.
- [ ] Dashboard AI enrichment: enqueue `ai_enrich_draft`; the queue page (`dashboard/ai_queue.html`) polls draft status (it is already AJAX-driven) instead of holding the request open. Show `pending → processing → ready/failed` states on the draft row.
- [ ] Keep a `TASKS_EAGER = True` setting for tests/local dev that executes handlers inline, so the existing test suite in `store/tests.py` keeps passing with minimal churn.

### 1.3 Observability
- [ ] Dashboard page (staff-only) listing failed tasks with a retry button.
- [ ] Log task duration and outcome; alert path is simply "failed tasks visible in dashboard".

**Acceptance:** checkout response returns in <500 ms with Telegram unreachable (verify by pointing the bot token at a black-hole host in staging); product save in dashboard no longer waits on Telegram; Gemini enrichment never holds an HTTP request open; failed sends are visible and retryable.

---

## P2 — Cloudinary-Native Image Delivery
Status: Not started
Depends on: nothing (independent of P1).

We already pay for Cloudinary but convert images to webp ourselves with Pillow inside `Product.save()` (`store/models.py:254–264`, also Category/Brand/ProductImages), then serve one fixed file to every device. Cloudinary does format, quality, and resize on the fly via URL parameters — better output, zero server CPU.

### 2.1 Template-side responsive images
- [ ] Add a template tag `{% cld_img product.image width=600 %}` in `store/templatetags/` that emits the Cloudinary delivery URL with `f_auto,q_auto,w_<n>,c_limit` and a `srcset` at 1x/2x (fall back to the raw `.url` when Cloudinary is not configured, so local dev still works).
- [ ] Replace `<img src="{{ x.image.url }}">` across storefront templates: collection card partials, `store/detail.html` gallery, cart, wishlist, home. Set explicit `width`/`height` (or `aspect-ratio` CSS) to stop layout shift.
- [ ] Add `loading="lazy"` to all below-the-fold images; keep the LCP hero/first-card eager with `fetchpriority="high"`.

### 2.2 Remove server-side conversion
- [ ] Delete `_convert_uploaded_image_to_webp` calls from all `save()` methods; keep original uploads as-is (Cloudinary transforms at delivery time).
- [ ] Update/remove the webp conversion test in `store/tests.py`; add a test that the template tag renders the expected transform URL.
- [ ] Confirm dashboard image previews (`dashboard/product_form.html` gallery JS) still work with original URLs.

**Acceptance:** Lighthouse mobile on the home page and one collection page shows LCP improvement and zero CLS from images; product uploads no longer spend CPU on Pillow; images arrive as AVIF/WebP sized to the viewport (check response headers/content-type in devtools).

---

## P3 — Real Caching + Query Fixes
Status: Not started
Depends on: P0. Cache backend choice interacts with P4.

The cache backend is `LocMemCache` (`jewelryshop/settings.py:240`) — per-process, so on serverless it caches essentially nothing. Only the nav menu uses it.

### 3.1 Shared cache backend
- [ ] Provision a managed Redis (Upstash free tier works with Vercel; any Redis after P4).
- [ ] Switch `CACHES` to `django.core.cache.backends.redis.RedisCache` via a `REDIS_URL` env var, keeping LocMem as the no-env-var local fallback.
- [ ] Move sessions to `cached_db` once Redis is in place.

### 3.2 Cache the read-heavy paths
- [ ] `{% cache %}` fragment around the product-card grid in the `_collection_*` partials, keyed on (filters hash, page, sort). TTL 5–10 min.
- [ ] `cache_page` (or fragment cache) for anonymous home page and static-ish pages. Skip for authenticated users (cart badge varies) or cache per-fragment around the varying bits.
- [ ] Keep the existing menu cache in `store/context_preprocessors.py`; add explicit invalidation on Category/Brand save instead of TTL-only.
- [ ] Add cache invalidation on Product save for affected collection fragments (simplest: bump a site-wide "catalog version" key included in fragment keys).

### 3.3 Query fixes
- [ ] `orders()` (`store/views.py:2118–2138`): paginate the queryset first, then attach `timeline`/`status_copy` decoration to only the page's rows. Currently the entire order history is materialized per request.
- [ ] Collection pages: `_build_collection_state` runs a price-bounds aggregate (`views.py:1081`), a separate full scan for size options (`views.py:1184` → `1034–1047`), a count, and the page query — consolidate into one aggregate pass where possible and cache the price-bounds/size-options per (category/brand) for 10 min.
- [ ] Add `django-debug-toolbar` (dev-only) to catch regressions; spot-check detail, collection, cart, and dashboard list pages for duplicate queries.

**Acceptance:** repeat anonymous visits to home/collection pages hit cache (verify with debug-toolbar cache panel / Redis MONITOR); a user with 500 orders loads `/orders/` without materializing 500 rows; collection page query count drops measurably.

---

## P4 — Hosting Decision
Status: Not started
Depends on: none technically, but do it before or alongside P1/P3 to simplify them.

Django on Vercel serverless fights the platform: cold starts, no background processes, no shared memory, media workarounds. One small always-on host removes an entire class of problems.

### 4.1 Decide
- [ ] Pick one: Railway / Fly.io / Render / small Hetzner VPS. Requirement: one web process (gunicorn) + one worker process (`manage.py run_tasks --forever`) + managed Postgres + Redis.
- [ ] If staying on Vercel is non-negotiable: keep the P1 cron-endpoint trigger and Upstash Redis, and accept cold starts. The rest of the plan still works — this phase is an amplifier, not a prerequisite.

### 4.2 Migrate (if moving)
- [ ] Provision Postgres, migrate data from the current managed DB (`pg_dump`/`pg_restore`).
- [ ] Set env vars (`DATABASE_URL`, `REDIS_URL`, Cloudinary, Telegram, Gemini, `SITE_URL`).
- [ ] Deploy web + worker processes; keep whitenoise for static files (already configured).
- [ ] Point DNS, verify Telegram webhooks against the new host, then decommission the Vercel project.
- [ ] Replace the P1 cron HTTP trigger with the always-on worker loop.

**Acceptance:** p50 TTFB on a cold visit drops (no cold starts); worker process drains the task table continuously; deploys are boring.

---

## P5 — Frontend Unification (htmx + one design system)
Status: Not started
Depends on: none. Ship page-by-page; each step is independently deployable.

Two problems: (a) ~10 hand-rolled fetch/JSON endpoints each with bespoke JS for cart, wishlist, and filters; (b) two unrelated design systems — `spring-*` (storefront, off `templates/base.html`) and `zd-*` (dashboard, off `templates/dashboard/base.html`) — plus heavy inline styling in the dashboard (`dashboard/product_form.html` alone has 18 inline `style=` attributes and an inline `<script>`).

### 5.1 Adopt htmx for interactions (no build step — it fits the current stack)
- [ ] Vendor `htmx.min.js` into static assets; load in both base templates.
- [ ] **Cart:** convert add-to-cart, plus/minus, and remove to htmx forms returning rendered partials (`_cart_lines.html`, `_cart_badge.html` with `hx-swap-oob` for the nav badge). Delete the corresponding JSON endpoints and their page JS.
- [ ] **Wishlist toggle:** htmx post returning the button partial.
- [ ] **Collection filters/sort/pagination:** `hx-get` on the filter form and pager targeting the product-grid partial, with `hx-push-url="true"` so URLs stay shareable/SEO-clean. The partial structure (`_collection_*`) already supports this — it is the easy case.
- [ ] **Search suggestions:** replace the hand-rolled typeahead in `base.html:194–256` with `hx-trigger="keyup changed delay:300ms"` returning a suggestions partial.
- [ ] Keep plain-form fallbacks working (htmx enhances the same endpoints); JS-disabled users still get full-page flows.

### 5.2 Consolidate the design system (incremental, not a restyle)
- [ ] Choose the storefront system as canonical. Extract shared tokens (colors, spacing, type scale, buttons, form controls) into one `zent-core.css` loaded by both bases.
- [ ] Migrate dashboard pages to the shared tokens one page at a time, starting with the pages staff touch daily: `product_form.html`, `ai_queue.html`, order list. Move all inline `style=` attributes and inline `<script>`/`<style>` blocks into the CSS/static JS as each page is touched.
- [ ] Delete `zd-*` rules as their last usages disappear.

### 5.3 Perceived-performance polish
- [ ] htmx indicators (spinner class) on cart/filter actions; disable buttons while in flight.
- [ ] `<link rel="preconnect">` to the Cloudinary domain in `base.html`.
- [ ] Audit vendored JS: drop sticky.js if CSS `position: sticky` covers it; confirm jQuery is still needed after the htmx migration (goal: remove it).

**Acceptance:** cart and filter interactions update without full page loads and without bespoke JS per endpoint; the JSON-only endpoints for cart/wishlist are deleted; dashboard product form has zero inline styles; total JS payload shrinks (measure before/after).

---

## P6 — Code Structure & Model Cleanup
Status: Not started
Depends on: best done after P1 (services layer hosts the task handlers).

### 6.1 Split the god files (pure moves, no behavior change)
- [ ] Convert `store/views.py` (2,184 lines) into a `store/views/` package: `catalog.py`, `cart.py`, `checkout.py`, `account.py`, `affiliate.py`, `telegram.py`. Re-export names in `__init__.py` so `store/urls.py` is untouched, or update imports in one pass.
- [ ] Extract a `store/services/` layer: `telegram.py` (wraps `telegram_notify`), `enrichment.py` (wraps `ai_enrichment`), `checkout.py` (order creation + commission logic pulled from the view). Views orchestrate; services do the work; P1 task handlers call services.

### 6.2 Model cleanup
- [ ] **Single source of truth for sizes:** drop the CSV `Product.available_sizes` field in favor of `ProductSizeStock` rows (currently both exist, synced by `_sync_size_inventory`, `models.py:190–235`). Provide a data migration; keep a read-only property for template compatibility during transition.
- [ ] **Thin out `Product.save()`:** after P2 removes webp conversion, move size-sync and sold-out reconciliation into explicit service calls from the places that mutate stock, so `save()` has no surprising side effects.
- [ ] **Guest checkout:** stop creating `guest-<session_key>` rows in `auth_user` (`views.py:1247–1253`). Make `Order.user` nullable with `guest_email`/`session_key` fields, or introduce a dedicated `Customer` model. Migrate existing guest users.
- [ ] Fix `Coupon` fields declared with `default=None` on effectively-required columns (`models.py:499–504`).

### 6.3 Test reinforcement
- [ ] Add `assertNumQueries` guards on detail, collection, and cart views to lock in P3's query wins.
- [ ] Add task-queue tests: enqueue on checkout, retry on handler failure, suspension semantics.
- [ ] Keep the existing 28-method `StoreFlowTests` green through every phase — it already covers cart guards, checkout, affiliate commissions, and dashboard gating well.

**Acceptance:** no file in `store/` exceeds ~500 lines; `Product.save()` only saves; a guest checkout creates no `auth_user` row; test suite passes with query-count assertions in place.

---

## Explicitly Rejected (and why)
- **Rewrite as SPA (Next.js/React) + DRF API** — doubles the codebase surface, adds a build pipeline and API versioning for a single-store brand, and sacrifices free server-rendered SEO. None of the current pain comes from the rendering model.
- **Celery + RabbitMQ/Redis broker** — overkill for this volume; the outbox table gives durability, retries, and visibility with one model and one command.
- **Tailwind migration** — a full-repo restyle for aesthetic parity we can reach by consolidating the existing CSS tokens. Revisit only if a redesign is planned anyway.
- **Microservices split** — the image worker is already the one justified external service (GPU workload); everything else belongs in the monolith.

## Sequencing
Recommended order: **P0 → P1 → P2 → P3 → P4 → P5 → P6**, with two notes:
- P4 (hosting) can be pulled forward to before P1 if the migration is approved early — it simplifies the worker story from "cron endpoint" to "just a process".
- P5 and P6 are incremental and can interleave with normal feature work; each checkbox is a shippable unit.
