# Launch checklist (after the September 2026 hardening pass)

Everything in the ecommerce assessment that could be done in code is now in the
repo. What remains is configuration, content and a handful of business
decisions. Work through this top to bottom.

## 1. Environment variables to set on Vercel

Copy from `.env.example`; the ones that change behaviour the most:

| Variable | Why |
|---|---|
| `SITE_URL` | Canonical host for sitemap, feeds, canonical tags, SMS/Telegram links. Set to the custom domain. |
| `REDIS_URL` | Shared cache (Upstash free tier). Without it fragment caches and login rate limits are per-lambda. |
| `EMAIL_HOST`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `DEFAULT_FROM_EMAIL` | Password reset, order receipts, restock alerts. Any SMTP provider (Resend, Postmark, Brevo, SES). |
| `SMS_BACKEND=afromessage` + `AFROMESSAGE_TOKEN` (or `SMS_BACKEND=http` + `SMS_HTTP_*`) | Order confirmation and dispatch SMS. Every COD buyer already gave a phone number. |
| `STORE_LEGAL_NAME`, `STORE_ADDRESS`, `STORE_EMAIL`, `STORE_TRADE_LICENSE`, `STORE_TIN` | Rendered in the footer, contact page, terms and privacy policy, and schema.org. |
| `STORE_SHOW_STOCK_COUNTS` | `false` (default) says "In stock / Sold out"; set `true` only once counts are real. |
| `DEFAULT_STOCK_PER_SIZE` | `0` forces staff to enter real counts per size; `10` (default) keeps the old behaviour. |
| `CHAPA_SECRET_KEY`, `CHAPA_WEBHOOK_SECRET` | Optional Telebirr / CBE Birr / card prepay through Chapa. Leave empty to stay COD-only. |
| `GA_MEASUREMENT_ID` | GA4 property. Ecommerce events (`view_item`, `add_to_cart`, `begin_checkout`, `purchase`) now fire. |
| `REFERRAL_WELCOME_COUPON_CODE` | Create the coupon in admin first, then set its code here to auto-apply for referred shoppers. |

`python manage.py check --deploy` now warns when email or SMS are still off in
production and when `SITE_URL` is empty.

## 2. Catalog (you said you would do this)

1. In Control Room → Products, delete the four test rows (`Itaque`, `Debitis`,
   `ai-queue-verification-…`, "Product Not Identifiable from Image") and fix
   the 0 ETB pajama set. The dashboard form now refuses a 0 price and any copy
   containing `[Store Name]`-style placeholders.
2. Run `python manage.py scrub_seo_placeholders` (then `--apply`) once against
   production to clean the three leaked SEO titles. Until then the storefront
   already strips placeholders at render time, so nothing bad is shown.
3. Decide on the Cartier / Omega watches: disclose, rebrand as unbranded, or
   remove. The terms and FAQ now promise that non-original items are labelled.
4. Set real size counts (or `DEFAULT_STOCK_PER_SIZE=0`) and enter
   measurements per product or a size guide per collection (Category → "Size
   guide"). Products without either show no size guide.
5. Add `meta_description` on collections and brands (admin → SEO fieldset).
6. Publish. Featured collections/brands with no live products are hidden
   automatically now, so "Cosmetics", "Adidas" and "New Balance" stop
   appearing until they have stock.

## 3. External registrations

- **Chapa**: create the merchant account, set the two env vars, and register
  `https://<domain>/payments/chapa/webhook/` as the webhook URL with the same
  secret.
- **Google Merchant Center / Meta Commerce**: submit
  `https://<domain>/feeds/google-merchant.xml` (RSS 2.0 with `g:` fields, one
  item per size). Requires the authenticity decision above and the policy
  pages, which now exist at `/terms/`, `/privacy/`, `/faq/`, `/delivery-returns/`.
- **Google Search Console**: verify the domain and submit
  `https://<domain>/sitemap.xml` (`robots.txt` already points to it).
- **Telegram**: no change needed. Channel posts now carry a "View on site"
  button and the bot's replies link back to the channel and the shop when
  `SITE_URL` is set.

## 4. What changed in code (for the deploy note)

- Hidden products return a real 404 with alternatives and `noindex`; staff see a
  preview banner. Structured data marks them `OutOfStock`.
- `OrderGroup` header: order number `ZT-YYMMDD-XXXX`, contact snapshot,
  delivery fee, totals, payment state, claim token. Existing orders were
  back-filled by migration 0060.
- Confirmation page at `/orders/confirmation/<token>/` with receipt, next
  steps, Telegram opt-in and a one-time GA4 `purchase` event. Guests can also
  see their orders at `/orders/` for the life of their session.
- Cancellation (customer, dashboard single/bulk, admin action) returns units to
  stock exactly once and un-sold-outs the product.
- Delivered lines queue a review invite (Telegram → SMS → email) with a
  tokenised `/review/<token>/` form; reviews carry a "Verified purchase" badge.
- Phone numbers are validated and normalised to `09XXXXXXXX` everywhere; login
  accepts `+251…` spellings.
- Prices render as `6,000 ETB`; stock copy uses availability language unless
  `STORE_SHOW_STOCK_COUNTS=true`.
- Sticky mobile add-to-cart bar, "Order on Telegram" button, size guide,
  contact chips and a fixed support note on the product page.
- `robots.txt`, `sitemap.xml`, canonical tags site-wide, `noindex` on
  cart/account/search/confirmation, unique meta descriptions for collections
  and brands, Organization + WebSite JSON-LD, richer Product offers
  (`priceValidUntil`, shipping, return policy, `aggregateRating`).
- Branded 404 and standalone 500 pages; privacy, terms and FAQ pages; business
  identity in the footer and contact page; language switcher (English /
  Amharic) with a compiled Amharic catalogue for the storefront chrome.
- Legacy Wolmart theme CSS (460 KB), jQuery, sticky.js and unused vendor
  libraries removed; a 40/80 px logo replaces the 246 KB PNG; the blurry hero
  photo is replaced by a typographic hero; static files get content-hash query
  strings and a one-year immutable `Cache-Control` from Vercel.
- CSP header, Secure cookie flags, SSL redirect, login/registration rate
  limiting (10 attempts / 15 min per IP and per phone).
- SMS layer (`store/sms.py`), email receipts, restock emails for shoppers
  without Telegram, Chapa payment module, Merchant Center feed, zero-result
  search logging and a conversion funnel tile in the Control Room.

## 5. Verify after deploy

```bash
curl -sI https://<domain>/static/asset/css/zent-core.css | grep -i cache-control   # immutable
curl -s https://<domain>/robots.txt
curl -s https://<domain>/sitemap.xml | head
curl -s -o /dev/null -w "%{http_code}\n" https://<domain>/product/<hidden-slug>/   # 404
```

Then place one guest test order end to end: confirmation page renders, SMS
arrives, Telegram staff alert shows the `ZT-` number and delivery fee, and
marking it Delivered in the Control Room sends the review invite.
