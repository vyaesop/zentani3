# Zentanee Ecommerce Assessment

**Date:** 3 September 2026
**Scope:** Live storefront at zentanee.vercel.app, the Telegram channel and order bot, the production database (read-only), and the codebase at commit `6311192`.
**Method:** Every page type was fetched live (home, shop, sale, search, category, PDP, cart, policy, contact, 404, robots, sitemap). Static asset weights, response headers and timings were measured with curl. Production catalog, order, customer and event tables were queried read-only. All views, services, models, templates, settings and CI were read in full.

---

## 1. Executive summary

Zentanee is a well-engineered storefront wrapped around a store that is, today, closed. The codebase is materially better than most Django shops of this size: guest checkout, htmx cart, size-level inventory with row locks, a durable task queue, Cloudinary responsive images, structured data, a staff dashboard, an AI intake pipeline and a 130-test CI suite. None of that is reaching a customer, because **zero of the 23 products in production are active**. The homepage shows two empty sections, the shop page says "0 items", search returns nothing, and the sale page is empty. The only live sales surface is a Telegram channel with 5 subscribers whose last product post was 1 August.

The commercial record confirms the picture. Seven web orders and four bot orders have been placed since March. None in the last 30 days. Lifetime delivered revenue is 19,400 ETB.

The biggest wins are not new features. They are: put a vetted catalog live, close three correctness leaks that will hurt trust and SEO the moment traffic arrives, fix the inconsistent delivery promise, and start measuring the funnel. After that, the platform is ready to carry real growth work.

### Scorecard

| Dimension | Score /10 | One-line verdict |
|---|---|---|
| Catalog readiness | 1 | 23 products, 0 active. Store is functionally closed. |
| Merchandising & data quality | 4 | Rich fields exist; test rows, a 0 ETB item, placeholder SEO titles and phantom stock are live in the DB. |
| Discovery (home, PLP, search) | 6 | Solid filters, sort, load-more, suggestions. All rendering empty states. |
| Product detail page | 6 | Strong trust layer and size UX; hidden products leak with a dead add-to-cart. |
| Cart & checkout | 6 | One-page guest checkout is right for the market; no confirmation page or order number for guests. |
| Payments | 4 | Cash on delivery only, no digital option, no COD-refusal mitigation. |
| Post-purchase & notifications | 4 | Good status timeline; email is a no-op in production; 0 of 12 Telegram opt-ins completed. |
| Trust, policy & legal | 4 | Clear COD and returns copy; no privacy, terms, size guide, business identity; sourcing and replica risk. |
| SEO | 3 | No robots.txt, no sitemap, hidden PDPs indexable as "InStock", placeholder titles, no custom domain. |
| Performance | 5 | Cloudinary images done right; 460 KB legacy theme CSS, jQuery, 246 KB logo, blurry 355 px hero, no static caching. |
| Analytics & measurement | 2 | GA4 tag installed with zero ecommerce events; first-party events exist but no funnel view. |
| Growth & CRM | 2 | 5 channel subscribers, no email capture, coupons unused, affiliate idle. |
| Operations & admin tooling | 7 | Dashboard, bulk status, staff notes, AI queue, task retry. Genuinely good. |
| Engineering health | 7 | Clean service layer, real tests in CI, documented plans. Neon free-tier compute is a standing risk. |
| Security | 6 | HSTS, CSRF, secret-guarded internals. No CSP, cookies lack Secure flag, no login rate limiting. |

---

## 2. Business model and positioning

**What the store actually is.** The catalog is sourced by scraping gojoshop.et (a multi-vendor Ethiopian marketplace) into an AI enrichment queue, where Gemini rewrites copy and assigns collections and brands. The store then resells at its own prices with cash on delivery in Addis Ababa. The scraper's own README flags the legal exposure of republishing vendors' names, descriptions and photos verbatim.

**Positioning drift.** The brand says four different things about itself:

- Homepage title: "Shop clothes & fashion in Addis Ababa"
- Homepage meta: "curated clothing and modest fashion"
- PWA manifest: "Modest fashion and everyday wear"
- About page: "clothing, handbags, perfumes, and accessories"

The live catalog is watches, sneakers, tracksuits, a compact mirror, a beanie and a fitted cap. There is a "Cosmetics" collection with zero products and a "Dresses" story band on the homepage pointing at a collection with zero active items. Pick one positioning and make the catalog, copy and featured flags agree with it.

**Replica risk.** "Cartier Santos Automatic Stainless Steel Watch" at 6,000 ETB and "Omega Seamaster Aqua Terra Worldtimer" at 5,000 ETB are, at roughly 40 USD, not the genuine articles. Nothing on the PDP, in the schema.org brand field or in the Telegram post says so. This is a consumer-trust problem (a shopper who expects authenticity refuses on delivery) and a platform problem (Google Merchant Center, Meta and Instagram Shopping all reject undisclosed replicas of protected brands). Either disclose clearly, rebrand these as unbranded, or remove them.

**Price architecture.** Average catalog price is about 5,000 ETB and the free-delivery threshold is 3,500 ETB, so almost every single-item order qualifies for free delivery. The announcement bar therefore says "Free delivery in Addis Ababa" unconditionally, while the policy page and cart say "free on orders over 3,500 ETB". Both cannot be true; the mobile menu also advertises "Under 1,000 ETB" which currently contains nothing.

---

## 3. Live-site state: the critical findings

These four items each independently block or damage a purchase and should be treated as incidents.

### 3.1 The storefront has no products

| Surface | Observed |
|---|---|
| Homepage "Latest Drops" | "New arrivals will appear here as soon as products go live." |
| Homepage "Featured Products" | "Featured products will appear here once they are marked in admin." |
| /products/ | "All Products — 0 items — No products match this view yet" |
| /sale/ | 0 items |
| /search/?q=nike | 0 items (there are two Nike products in the DB) |
| Production DB | 23 products, `is_active = False` on all 23 |

The publish path in the dashboard does set `is_active = True` (both the one-click AI-draft publish and the "Save & post" button), and 14 products were posted to the channel, so products were active at some point and have since been switched off. Whether that was deliberate (catalog review) or accidental, the site is receiving traffic (224 product views logged since 23 July) that lands on nothing.

### 3.2 Hidden products are publicly reachable with a dead buy button

The product detail view in [store/views/catalog.py](../store/views/catalog.py) fetches by slug with no `is_active` filter. The add-to-cart view does filter on `is_active`. Result, verified live on the Nike Air Force 1 page:

- Page returns 200 with full content, price, "12 in stock", seven size buttons and an enabled "Add to cart" button.
- schema.org markup says `"availability": "https://schema.org/InStock"`.
- Posting add-to-cart returns HTTP 404. The shopper sees nothing happen.

This is exactly the state Google will index (no robots.txt blocks it, and the pages are linked from old Telegram posts and any shared URLs). It also means the 224 "view" events are people or bots hitting pages that cannot convert.

### 3.3 Placeholder text is live in production SEO titles

Three products carry Gemini's template output as their page title. The Nike Air Force 1 page title is currently `Nike Air Force 1 Low '07 Triple Black Sneakers | [Store Name]`. The two abaya/kaftan products carry `[Your Store Name]`. These are the first thing Google shows.

### 3.4 The delivery promise contradicts itself

Announcement bar (every page): "Free delivery in Addis Ababa." Hero eyebrow: "Free delivery in Addis Ababa · Pay on delivery". Policy page and cart: 80 ETB, free over 3,500 ETB. A shopper who adds a 1,100 ETB beanie sees "Free delivery" at the top of the page and 80 ETB in the cart. Given the price architecture, either make delivery unconditionally free in Addis and simplify the code, or change the banner to "Free delivery in Addis over 3,500 ETB".

---

## 4. Catalog and merchandising data quality

Production catalog snapshot, 3 September 2026:

| Metric | Value |
|---|---|
| Products total / active | 23 / 0 |
| Products with no gallery images (cover only) | 18 |
| Products with size inventory rows | 12 |
| Products on sale (compare-at set) | 1 |
| Products with SEO title, description, alt text | 20 |
| Products with material, color, fit and care notes | 22 |
| Products with placeholder `[Store Name]` SEO titles | 3 |
| Products priced 0.00 ETB | 1 (Fuchsia Floral Comfort Pajama Set) |
| Obvious test rows | 4 (`Itaque`, `Debitis`, `ai-queue-verification-…`, "Product Not Identifiable from Image") |
| Products assigned to "No brand" | 13 of 23 |
| Price range / mean | 0 to 7,200 ETB / about 5,030 ETB |

**Phantom inventory.** `Product.DEFAULT_STOCK_PER_SIZE = 10` in [store/models.py](../store/models.py) creates 10 units per size whenever sizes are set. That is why a reseller with no warehouse shows "60 in stock", "70 in stock" and "152 in stock". The PDP then displays "12 in stock" as a fact and the filters offer "In stock only". For a drop-ship or order-on-demand model, stock messaging should say "Made to order, 1-3 days" or "Available", not invent quantities. If stock is real, the default should be 0 and staff should enter counts.

**Featured flags point at empty pages.** Cosmetics (featured, 0 products), Adidas and New Balance (featured, 0 products). The homepage "Brand spotlight" band currently sends shoppers to New Balance, which is empty. The homepage story band sends shoppers to Dresses, which has 0 active items.

**Copy quality is high where Gemini ran.** Titles are specific, descriptions are complete, material/color/care are filled for 22 of 23. The enrichment pipeline is an asset; the failure is the review gate before publish, not the generation.

**Imagery.** All 23 have a cover image; only 5 have a second image. Fashion converts on multiple angles and on-body shots. The card hover-swap feature exists but has nothing to swap to for 18 products.

---

## 5. Discovery: homepage, navigation, listing pages, search

**What is good.** The collection system is one shared layout across shop-all, sale, category, brand and search, with sort (newest, price both ways, name), filters (price, availability, collections, brands, sizes), active-filter chips, reset, htmx partial updates that push clean URLs, infinite "load more" with a crawlable `rel="next"` fallback, and a debounced search suggestion dropdown that returns products, collections and brands. Cards carry quick-add size chips, sale/bestseller/new badges, wishlist, and lazy Cloudinary images with explicit dimensions. This is above the bar for a store this size.

**What is missing or wrong.**

- Homepage hero is a 355 by 327 pixel JPEG stretched to full width with `background-size: cover`. On any desktop or 2x phone it is visibly blurry. The one image that sets the brand's quality signal is the lowest-resolution image on the site.
- Empty states are honest but administrative ("once they are marked in admin"). A shopper should never read admin vocabulary.
- Navigation has eight top-level items plus a bottom mobile bar; "New In" and "Shop All" both go to the same listing with different sort. Fine, but "Collections" and "Brands" as separate directories is thin at 7 collections and 10 brands. Consider collapsing to Shop (with collections as filters) and Sale.
- Search is `icontains` across title, description, category, brand, SKU, material and color with a hand-written rank expression. Adequate for 23 products. No typo tolerance, no Amharic, no synonyms ("sneaker" vs "shoes", "hoodie" vs "tracksuit").
- Category URLs live at the site root (`/dresses/`), so every unknown root path resolves through a category lookup. Harmless today, but it reserves the entire root namespace and makes `/robots.txt`-style paths ambiguous.
- "Recently viewed" and "Most Wanted" rails never render without data; the code handles it, the merchandising does not.

---

## 6. Product detail page

**Strong.** Clear brand/title/price hierarchy, size radio buttons with per-size stock messages, disabled unavailable sizes, per-size restock capture, cash-on-delivery, delivery and returns cards on the page, material/color/collection/SKU spec block, fit and care sections, reviews with fit feedback and customer photos, "customers also bought" backed by real co-purchase data with same-category fill, recently viewed, canonical URL, Open Graph, Product and BreadcrumbList JSON-LD, gallery with correct srcset switching and a lightbox, eager LCP image with `fetchpriority="high"`.

**Gaps that cost conversions.**

- No size guide or garment measurements. For clothing sold without try-on, this is the single most common pre-purchase question and the leading cause of on-the-spot returns, which under this store's policy means the driver went for nothing.
- Prices render as raw decimals: "6000.00 ETB". An `etb` formatting filter exists in [store/templatetags/image_optim.py](../store/templatetags/image_optim.py) and is not used on the PDP or cards. "6,000 ETB" reads as a price; "6000.00 ETB" reads as a database value.
- No sticky add-to-cart on mobile. The buy button scrolls away behind six sections. The bottom navigation is fixed; the CTA is not.
- Reviews require an account, and accounts require a phone-number username plus address at registration. That is a heavy gate for social proof. Consider allowing reviews from delivered orders via a tokenised link.
- No "ask on Telegram" or "call" action on the PDP for the shopper who has a question. Contact is two clicks away.
- Schema.org offer lacks `priceValidUntil`, `shippingDetails`, `hasMerchantReturnPolicy` and `aggregateRating`. These are what earn rich results and Merchant listings.
- The one-line support copy says "Orders are tracked in your account after checkout", which is false for guests (see 7.3).

---

## 7. Cart, checkout and payments

### 7.1 Cart
The htmx cart is well executed: server-authoritative line totals, out-of-band badge updates, stock-aware plus/minus, coupon application with clear error copy, delivery estimation from the saved city, a shortfall nudge toward free delivery, and a flow-status panel that tells the shopper what happens next. Guest carts are session-scoped with no placeholder users. Ownership checks prevent cross-user cart mutation.

### 7.2 Checkout
Single-page guest checkout (name, phone, city, address on the cart page) is the correct design for Addis Ababa, where most shoppers do not want an account and COD removes the payment step. Order placement locks product and size rows, validates stock, snapshots price, records affiliate commission and coupon usage, and clears the cart atomically. Telegram notifications to staff and to opted-in customers fire after commit.

### 7.3 Post-order gaps
- **No confirmation page.** A guest is redirected to the homepage with a green flash message that disappears on the next navigation. They receive no order number, no summary, no way to check status, and no email or SMS because the email backend is the console. If they refresh, the evidence that they ordered is gone.
- **No order entity.** Each cart line becomes a separate `Order` row. A three-item basket produces three order IDs, three status timelines and three lines in the staff dashboard. There is no order number to quote on the phone, no header total, and no persisted delivery fee: the shipping amount is computed for the flash message and never stored. Revenue reporting therefore excludes delivery income and cannot reconcile against cash collected.
- **Address is not snapshotted** for registered users. The dashboard and order pages look up `user.address_set.last()` at render time, so a customer who adds a new address after ordering changes the delivery address on their historical orders as displayed to staff.
- **Cancellation does not restore stock.** Both customer cancellation and staff status changes set `status = "Cancelled"` and nothing else. With real inventory this leaks units; with phantom inventory it does not matter yet.
- **No phone validation** beyond "at least 7 digits". Ethiopian numbers are 09XXXXXXXX or +2519XXXXXXXX; normalise and validate, because the phone number is the delivery contract.

### 7.4 Payments
Cash on delivery only, stated clearly and consistently. That is defensible for this market and this stage. Two things are missing:

- **COD refusal mitigation.** There is no order confirmation call step, no deposit option and no "confirm via Telegram" step before dispatch. The "Pending → Accepted" status exists but nothing prompts the customer to confirm. As volume grows, unconfirmed COD orders are the largest cost line for Ethiopian delivery businesses.
- **Optional digital payment.** Telebirr and CBE Birr are now mainstream in Addis; Chapa and ArifPay aggregate them with a hosted checkout. Offering "pay now for priority dispatch" or "pay a deposit" reduces refusals and expands to customers outside Addis, where 180 ETB COD on a 5,000 ETB item is a thin margin for the courier.

---

## 8. Post-purchase, notifications and CRM

| Signal | Value |
|---|---|
| Web orders lifetime / last 90 days / last 30 days | 7 / 4 / 0 |
| Telegram bot orders lifetime | 4 (3 delivered, 1 pending) |
| Delivered revenue (web) | 19,400 ETB |
| Registered users / staff | 13 / 3 |
| Telegram opt-in links created / completed | 12 / 0 |
| Wishlist entries / reviews / restock requests | 1 / 1 / 0 |
| Active coupons | 0 |

**Order tracking** for registered users is good: status summary tiles, a five-step timeline with plain-language copy per status, staff notes surfaced to the customer, and cancellation while Pending or Accepted.

**Notifications** are Telegram-only. The opt-in banner appears on cart and orders pages; 12 shoppers clicked far enough to mint a link token and none completed the bot handshake. The deep link opens Telegram, requires the customer to tap Start, and only then links. That is two app switches for a benefit ("get updates") the shopper has not yet valued. Move the opt-in to the post-order confirmation page where the value is concrete ("we will message you when the driver leaves") and consider SMS as the default channel: it needs no opt-in and every COD customer has already given a phone number.

**Email is dead in production.** `EMAIL_BACKEND` is the console backend. Password reset silently succeeds and sends nothing. Restock requests collect an email address that is never used; restock alerts only go to Telegram-linked accounts (currently none). Either wire a real provider (Resend, Postmark, SES) or remove the email fields so the UI stops making promises.

**Abandoned cart** nudges exist in the task queue but only fire to Telegram-linked customers. With zero linked, the feature is inert.

---

## 9. Trust, policy and legal surfaces

**Present and good:** cash-on-delivery explanation with "inspect first, then pay", on-the-spot returns policy in plain language, delivery fees and timing, a phone number, Instagram and Telegram contact, order status vocabulary.

**Missing:**

- Business identity: legal name, physical location or pickup point, trade licence or TIN. Ethiopian shoppers paying cash to a driver want to know who they are dealing with; the footer says only "© 2026 Zentanee".
- Privacy policy and terms of service. The site sets analytics cookies, stores phone numbers and addresses, and messages customers on Telegram. Nothing tells them how that data is used.
- FAQ: how confirmation works, what happens if nobody is home, whether sizes can be exchanged, delivery windows, areas served outside Addis.
- Size guide (see PDP).
- Authenticity statement for branded goods (see section 2).
- A branded 404 page. The current one is Django's bare default with no navigation, no search and no logo.

**Sourcing.** The catalog is republished from gojoshop.et vendors, photos included. The scraper README already recommends importing factual data only and regenerating copy and images. Do that before scaling the catalog, and prioritise own photography for the top 20 sellers.

**Returns policy realism.** "Returns accepted only on the spot, before the driver leaves" is clear and operationally honest for COD. It shifts the cost of a bad fit onto the courier trip. That makes the size guide, measurements and fit reviews revenue items, not content nice-to-haves.

---

## 10. SEO and structured data

| Check | Result |
|---|---|
| robots.txt | 404 |
| sitemap.xml | 404 |
| Canonical tag | PDP only; none on home, listings, policy pages |
| Default meta description | "Zentanee fashion storefront." on every page without an override |
| Product JSON-LD | Present; missing rating, shipping, return policy, price validity |
| Organization / WebSite / LocalBusiness JSON-LD | Absent |
| Hidden products | Indexable, marked InStock |
| Placeholder titles | 3 products with `[Store Name]` |
| Language | `lang="en"` only; no Amharic, no hreflang |
| Domain | vercel.app subdomain; README links to www.zentanee.com.et, which does not resolve |
| 404 page | Bare, unbranded |
| HTTP to HTTPS | 308 redirect, HSTS with preload (good) |

The technical SEO base on the PDP is solid. The site-wide layer does not exist yet: without a sitemap and robots file Google discovers pages only by crawling internal links, and today the internal links lead to empty listings. A custom domain matters for trust and for consolidating any future ranking; every share, Telegram post and Instagram bio link currently strengthens `vercel.app`.

Category and brand pages have no description copy and share the default meta description. For a small catalog these pages are the best ranking candidates ("Nike Addis Ababa", "tracksuit set Ethiopia"); give each a paragraph and a unique description.

---

## 11. Performance and front-end

Measured from a European vantage point; Addis latency will be higher.

| Metric | Value |
|---|---|
| Homepage time to first byte | about 0.7 s (three samples, warm) |
| Homepage HTML | 25.7 KB |
| CSS transferred (gzip) | about 110 KB, of which `style.min.css` is 73 KB (460 KB raw legacy Wolmart theme) |
| JS transferred (gzip) | about 110 KB: Swiper 40 KB, jQuery 33 KB, htmx 17 KB, main 17 KB, sticky 3 KB |
| Logo PNG | 246 KB, 512 by 512, displayed at 40 by 40 on every page |
| Hero image | 69 KB, 355 by 327, stretched to full viewport width |
| Static `Cache-Control` | `public, max-age=0, must-revalidate` |
| Product images | Cloudinary `f_auto,q_auto,c_limit,w_N` with 1x/2x srcset, lazy below fold, explicit dimensions |

**Good.** Image delivery is done the right way and is the biggest performance lever in a fashion store. Fonts are preconnected, Font Awesome woff2 is preloaded, scripts are deferred, the LCP image is eager with high priority, and a service worker gives repeat visits a cache-first shell.

**To fix.**

- The legacy theme stylesheet is almost certainly under 10 percent used. Purge it or replace with the two `zent-*` files that already carry the design system.
- jQuery is loaded for `main.min.js` (theme helpers) and sticky.js. After the htmx migration the remaining jQuery dependency should be audited and removed; Swiper does not need it.
- Serve the logo as a 40/80 px WebP or inline SVG; 246 KB for a 40 px mark is the single heaviest byte cost on the page after CSS.
- Replace the hero with a real 1600 px asset via Cloudinary, or drop the photo for a typographic hero. A blurry hero reads as untrustworthy.
- `max-age=0` on static files means every new visitor revalidates every asset. WhiteNoise's manifest storage gives hashed filenames and year-long caching; it was avoided because the theme CSS has broken relative references, which is another reason to purge that file.
- TTFB of 0.7 s is a Python-on-Vercel cold-path number. The hosting doc already recommends an always-on host; that recommendation stands, and it also solves the Neon compute exhaustion issue documented in the task-drain workflow.
- Confirm `REDIS_URL` is set in the Vercel environment. Without it the cache is per-lambda memory and the fragment/menu/collection caches do almost nothing; the local `.env` does not set it.

---

## 12. Analytics and measurement

GA4 (`G-PMSGT50Q4W`) is installed on every page with `config` only. No `view_item`, `add_to_cart`, `begin_checkout` or `purchase` events are sent, so GA4 knows page views and nothing about the funnel. There is no Meta pixel, no TikTok pixel and no Google Ads tag, which means paid acquisition cannot be optimised or attributed.

The first-party `ProductEvent` table is a real asset: 224 views, 1 add-to-cart and 1 purchase since 23 July, and it powers the "customers also bought" rail. It is not surfaced anywhere. The staff dashboard shows order counts and revenue but no conversion, no traffic, no top-viewed products, no search terms with zero results.

Minimum viable measurement: GA4 ecommerce events from the existing htmx endpoints (server-side `dataLayer` pushes in the partial responses), UTM capture on session start stored against the order, and a dashboard tile for views to add-to-cart to order over 7 and 30 days.

---

## 13. Growth channels

**Telegram** is the real storefront today. The channel has 5 subscribers and 13 visible posts, all with photos, price, sizes and a "Choose Size" button into the bot. The bot flow collects size, quantity, name, phone, city and address, confirms with YES, and alerts staff. Four orders came through it and three were delivered, which is a better conversion record than the website. But the posts never link to the website, the website never links to the channel's product posts, and the bot never asks the buyer to subscribe. Each surface is an island.

**Instagram** is linked in the footer and offered as the primary support channel. No feed, no shop tagging, no UTM.

**Affiliate program** exists with dashboards, commission tracking and payout marking: 2 profiles, 2 clicks, 1 commission. It is invisible on the storefront; a customer would find it only by knowing the URL.

**Coupons** are fully built (codes, percentage, date range, usage caps) and there are zero coupons.

**Email/SMS list:** none. The restock form is the only email capture and it feeds nothing.

Growth priority for this market: get the channel and the site to feed each other (every post carries the PDP link and every PDP carries "Order on Telegram"), seed the channel through the courier hand-off (a card with a QR to the channel and a first-order code), and use SMS for order confirmation because it is the one channel every buyer already gave you.

---

## 14. Operations, admin and engineering health

**Staff tooling is strong for the stage.** The dashboard covers orders (search, status filter, single and bulk status changes, staff notes, customer Telegram notifications on change), Telegram bot orders, the AI intake queue with one-click publish, product list with live/hidden/low-stock filters, a broadcast tool to linked subscribers, and a background task page with retry. Django admin covers the rest, including a "post selected to Telegram" action.

**Engineering.** The July overhaul (P0 through P6 in [docs/performance-ux-overhaul-plan.md](performance-ux-overhaul-plan.md)) was executed: views split into a package, a checkout service with row locks, size inventory as single source of truth, guest checkout without placeholder users, an outbox task queue with inline fast-path and stale-task recovery, query-count guard tests, and CI that now runs the real suite after previously passing on zero tests. The task queue shows 0 failed tasks in production.

**Standing operational risks.**

- Neon free tier compute was exhausted once by polling; the drain now runs sparsely. Any new periodic job must respect that.
- Vercel Hobby cron is once daily; the GitHub Actions drain is the real scheduler and depends on a repository secret matching a Vercel env var.
- The local `.env` points at the production database. One `manage.py` command run locally against the wrong settings mutates production. Consider a separate development database.
- `hf_image_worker/` is an empty leftover directory. `db.sqlite3` in the repo root is a stale jewellery-era snapshot.

---

## 15. Security

| Control | State |
|---|---|
| HTTPS, HSTS with preload | Yes (Vercel) |
| X-Frame-Options DENY, nosniff, Referrer-Policy | Yes |
| Content-Security-Policy | No |
| `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE` | Not set; csrftoken cookie observed without Secure flag |
| CSRF on htmx | Yes, via `hx-headers` |
| Object-level ownership on cart/order/address | Yes |
| Internal drain endpoint | Shared-secret, non-echoing errors |
| Telegram webhooks | Secret-token checked |
| Login and registration rate limiting | None |
| Password reset | Non-functional (console email) |
| `DEBUG` in production | Off; settings refuse to boot without a secret key |
| Secrets in repo | `.env` is gitignored; historical credential leak was addressed in P0 |

Set the two Secure cookie flags and `SECURE_SSL_REDIRECT` (harmless behind Vercel), add a basic CSP that allows self, Cloudinary, Google Fonts and GA, and rate-limit login and registration by IP and by phone number.

---

## 16. Prioritised action plan

### P0: this week (unblock selling)

1. **Publish a vetted catalog.** Delete the four test rows, fix the 0.00 ETB price, decide on the Cartier/Omega items, then activate. Un-feature Cosmetics, Adidas and New Balance or give them products.
2. **Fix the three `[Store Name]` SEO titles** and add a validation rule in the AI intake that rejects any bracketed placeholder in title, description or alt text.
3. **Stop hidden products leaking.** Filter `is_active` in the detail view (return 404 or a "no longer available" page with `noindex`), or at minimum emit `OutOfStock` schema and disable the button.
4. **Make the delivery promise consistent** across banner, hero, cart and policy.
5. **Add robots.txt and a sitemap** (`django.contrib.sitemaps` covers products, categories, brands and static pages in an hour), plus canonical tags site-wide.
6. **Wire a real email provider** or remove the password reset link and the restock email field.
7. **Fix stock semantics.** Set `DEFAULT_STOCK_PER_SIZE` to 0 and enter real counts, or switch stock messaging to availability language for made-to-order items.

### P1: next 30 days (convert the traffic you get)

- Order confirmation page with an order number, summary, delivery fee, and the Telegram opt-in placed there. Introduce an order header model (number, totals, delivery fee, address snapshot, contact) with the existing rows as lines.
- SMS order confirmation and dispatch notice via a local gateway; keep Telegram as the rich channel.
- Restore stock on cancellation; validate Ethiopian phone formats.
- Format prices with thousands separators everywhere; sticky mobile add-to-cart; size guide and measurements per collection.
- GA4 ecommerce events and a conversion tile in the dashboard.
- Branded 404; privacy policy; terms; FAQ; business identity in the footer.
- Custom domain; Secure cookie flags; CSP; login rate limiting.
- Purge the legacy theme CSS, drop jQuery if possible, replace logo and hero assets, enable hashed static files with long cache.
- Cross-link Telegram and web: PDP link in every channel post, "Order on Telegram" on every PDP, channel invite in the bot's order confirmation.

### P2: next 90 days (grow)

- Optional Telebirr/CBE Birr prepayment through an aggregator, with priority dispatch as the incentive.
- Own product photography for top sellers; second angle for every product.
- Merchant Center feed and Instagram Shopping once authenticity and policy pages exist.
- Category page copy and Amharic variants of key pages.
- Review collection from delivered orders via tokenised links; seed the first 20 reviews.
- Referral incentive on top of the affiliate system; a launch coupon.
- Move to an always-on host per the hosting doc; retire the drain workflow.

---

## Appendix A: key production numbers

| Item | Value |
|---|---|
| Products total / active / with gallery | 23 / 0 / 5 |
| Categories / brands | 7 / 10 |
| Users / staff | 13 / 3 |
| Web orders lifetime / last 30 days | 7 / 0 |
| Bot orders lifetime | 4 |
| Delivered revenue (web lines) | 19,400 ETB |
| Telegram channel subscribers | 5 |
| Products ever posted to channel / last post | 14 / 1 Aug 2026 |
| Telegram opt-ins minted / linked | 12 / 0 |
| Product views / adds / purchases since 23 Jul | 224 / 1 / 1 |
| Background tasks failed | 0 |
| AI drafts ready / turned into products | 29 / 20 |

## Appendix B: files referenced

- Storefront views: [store/views/catalog.py](../store/views/catalog.py), [store/views/collections.py](../store/views/collections.py), [store/views/cart.py](../store/views/cart.py), [store/views/checkout.py](../store/views/checkout.py)
- Order placement: [store/services/checkout.py](../store/services/checkout.py)
- Inventory defaults: [store/models.py](../store/models.py), [store/services/inventory.py](../store/services/inventory.py)
- Settings (email, cache, security): [zentanee/settings.py](../zentanee/settings.py)
- Base layout and announcement bar: [templates/base.html](../templates/base.html)
- Policy page: [templates/store/delivery-returns.html](../templates/store/delivery-returns.html)
- Task queue and drain: [store/tasks.py](../store/tasks.py), [.github/workflows/run-tasks.yml](../.github/workflows/run-tasks.yml)
- Sourcing: [docs/gojoshop-scrape-README.md](gojoshop-scrape-README.md)
