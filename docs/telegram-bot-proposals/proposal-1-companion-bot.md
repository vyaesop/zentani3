# Proposal 1: Companion Bot (Website-First)

## Summary

Build a Telegram bot that helps users discover products, track orders, get support, and jump into the website for cart and checkout. This is the lowest-risk option because it reuses your current web flows directly.

## Architecture

- Telegram Bot API webhook endpoint in Django (for example: `/telegram/webhook/`).
- Bot service layer in Django app (or separate `bot` app) to process commands/callbacks.
- Deep links from bot to existing pages:
  - Product detail page
  - Cart page
  - Checkout page
  - Affiliate tracking URL (`/ref/<code>/`)
- Optional Redis cache for conversation state and throttling.

## Complete Feature Set

### Customer features

- `/start` onboarding with language and quick menu.
- Browse featured products with image, price, brand, category.
- Search products by keyword.
- Filter shortcuts by category and brand.
- Product detail card with:
  - title, short description, price
  - sold-out warning
  - available sizes
  - "Open on website" CTA
- "Continue where I left off" links to website cart/checkout.
- Order lookup:
  - latest orders summary
  - status updates (Pending, Accepted, Packed, On The Way, Delivered, Cancelled)
- Coupon info helper:
  - check if coupon looks valid
  - explain active/expired/inactive states
- Customer support menu:
  - FAQ
  - contact/store location links
  - escalation to human support via Telegram handle or web form

### Marketing and growth features

- Broadcast campaigns (new arrivals, offers) to opted-in subscribers.
- Product drop alerts by category/brand subscriptions.
- Coupon campaign broadcasting with redemption CTA.
- Affiliate share helper:
  - affiliate can fetch and copy referral links
  - one-tap share templates for Telegram chats/channels

### Operations features

- Admin command set for basic campaign send and announcement previews.
- Delivery team quick order status push (manual) from admin panel action.
- Bot health and command usage metrics.

## Integration with your current code

- Read products from `Product`, `Category`, `Brand`.
- Respect `available_sizes` and `is_sold_out` before showing CTAs.
- Read order states from `Order.status`.
- Validate coupon logic using current `_coupon_issue` rules.
- Reuse affiliate links from `track_affiliate_link` route.

## Implementation plan

1. Add bot webhook endpoint and command router.
2. Implement product browse/search cards with inline keyboards.
3. Add deep links to website product/cart/checkout.
4. Add order tracking command and notification events.
5. Add broadcast module with opt-in and opt-out.
6. Add analytics dashboard section in Django admin.

## Pros

- Fastest launch and easiest maintenance.
- Minimal risk to current checkout flow.
- Immediate user engagement channel.

## Cons

- Checkout still happens on website, not inside Telegram.
- Conversational commerce depth is limited.

## Best fit

Choose this if you want to go live quickly and improve conversion through reminders, discovery, and re-engagement without major backend refactoring.
