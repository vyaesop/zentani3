# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Confirmed: mixed men and women in Addis Ababa, streetwear-leaning — sneakers, tracksuits, caps and watches alongside dresses and sets. They discover products on Telegram and Instagram, shop on a phone, and pay cash to the driver after inspecting the item.

Inferred (from catalog, orders and channel data; confirm when convenient): roughly 18–35, comfortable with Telegram bots, wary of online prepayment, sensitive to delivery cost and to whether a branded item is real.

## Product Purpose

Zentanee is a curated fashion store for Addis Ababa. A shopper browses on the site or the Telegram channel, orders in a few taps (web cart or bot chat), gets a confirmation call, receives the item within 1–3 days in Addis, inspects it with the driver present and only then pays. Success is a confirmed order that is accepted at the door; the store's cost centre is a refused or wrong-size delivery.

## Positioning

Confirmed: branded items are genuine originals and can be described as such.

The mechanism a neighbouring shop cannot truthfully copy: inspect-before-you-pay with on-the-spot returns, a Telegram channel that posts every drop with a one-tap order button, and delivery in Addis that is free over 3,500 ETB. Inferred summary line: fast discovery, honest product pages, zero payment risk.

## Operating Context

- Telegram channel `@zentanee_channel` posts each product with a "Choose Size" button that starts an order in the bot; the site's product pages carry an "Order on Telegram" button back into the same bot.
- Staff confirm every order by phone before dispatch; drivers deliver; customers inspect and pay cash (optional Chapa prepay exists but is off until configured).
- Sizes are tracked per product; wishlist, restock alerts, verified-purchase reviews with fit feedback, and an order confirmation page with an order number exist.
- Staff run a Control Room (dashboard) and an AI intake that drafts product copy from supplier photos.

## Capabilities and Constraints

- Django server-rendered templates with htmx; no JavaScript build step. Storefront CSS lives in `zentanee/static/asset/css/zent-core.css`, `zent-shim.css`, `zent-storefront.css`; behaviour in `asset/js/zent.js`.
- Images are Cloudinary-delivered through the `cld_img` / `cld_url` template tags (responsive, `f_auto,q_auto`). Product photos are supplier photos, usually one per product on a plain background; there is no lifestyle or campaign photography yet.
- Content-Security-Policy allows external scripts only from Google Analytics, stylesheets and fonts from Google Fonts, images from any https origin. Static files are served by Vercel with content-hash query strings.
- Currency is ETB (prices formatted through the `etb` filter). Delivery: 80 ETB in Addis, free over 3,500 ETB, 180 ETB outside Addis. UI strings are translatable (English, Amharic).
- The live catalog is small (roughly 20–30 products) and grows in drops; the homepage must look complete with few products and must never pad with placeholders.
- Undecided: hero imagery. No brand-owned campaign photography exists; the legacy stock photo in `asset/images/banner.webp` is not Zentanee's and must not be used as if it were.

## Brand Commitments

- Binding: the pop-art halftone black-and-white circular logo (`asset/images/logo-circle.png`, `logo-mark-80/160.png`) is the identity anchor.
- Open: palette, typography, layout, imagery treatment. Telegram does not have to lead the page.
- Name: Zentanee. Voice (inferred from existing copy; confirm): direct, plain, warm, no hype — "inspect before you pay".

## Evidence on Hand

- Real product catalog with Cloudinary photos, sizes and prices.
- Real policy numbers (fees, threshold, 1–3 day delivery, on-the-spot returns) and a real support phone number.
- Real Telegram channel and order bot.
- Small real order history (11 orders lifetime across web and bot). No testimonials, press, or customer photos exist yet — none may be invented.
- Logo assets and an OG image (`asset/images/og-zentanee.jpg`).

## Product Principles

1. Trust before taste: every price, fee, delivery time and authenticity statement on the page is true and visible.
2. Inspect-before-you-pay is the product; the design dramatizes it rather than burying it in a trust bar.
3. The channel and the site are one store: each surface points at the other.
4. Thumb first: the phone composition is the design; desktop inherits.
5. A small catalog is presented with confidence — fewer, larger, better-described pieces beat a padded grid.

## Accessibility & Inclusion

WCAG AA contrast on all text; English and Amharic UI; Addis mobile networks are slow and metered, so pages stay light (lazy images, no hero video, no heavy fonts).
