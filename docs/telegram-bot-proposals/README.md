# Telegram Bot Integration Proposals for Zentanee

This folder contains practical options to integrate the current Django e-commerce website with Telegram.

## Which proposal should you pick?

- Pick `proposal-1-companion-bot.md` if you want the fastest launch with low engineering risk.
- Pick `proposal-2-headless-commerce-bot.md` if you want full in-chat shopping and checkout automation.
- Pick `proposal-3-growth-and-ops-bot-suite.md` if your priority is growth, affiliate sales, and operations workflows.

## Snapshot Comparison

| Proposal | Time to Market | Engineering Complexity | Customer Experience | Revenue Impact Speed |
|---|---|---|---|---|
| 1. Companion Bot | Fast (1-3 weeks) | Low | Medium | Fast |
| 2. Headless Commerce Bot | Medium (4-8 weeks) | High | High | Medium-High |
| 3. Growth + Ops Bot Suite | Medium (3-6 weeks) | Medium | Medium-High | High |

## Shared principles for all options

- Keep Django as the source of truth for products, prices, coupons, cart, orders, and affiliate commissions.
- Use Telegram webhook mode in production for reliability and lower latency.
- Use deep links and signed payloads where needed to prevent tampering.
- Add rate-limits, retry policies, and event logging for bot actions.
- Start with feature flags so bot functionality can be rolled out incrementally.

## Existing site capabilities reused by all proposals

Based on your current codebase (`store/models.py`, `store/views.py`, `store/urls.py`):

- Product catalog by category and brand
- Product sizes and sold-out state checks
- Cart and checkout flow with coupon application
- Order creation and order status lifecycle
- User accounts and addresses
- Affiliate links, click tracking, and commission records

