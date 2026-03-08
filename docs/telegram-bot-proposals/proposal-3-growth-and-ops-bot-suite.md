# Proposal 3: Growth and Ops Bot Suite (Multi-Bot Strategy)

## Summary

Build two coordinated bots: a customer engagement bot and an internal operations bot. This focuses on retention, affiliate growth, and order operations efficiency, while keeping checkout mostly web-based.

## Architecture

- `@ZentShopBot` for customer-facing flows.
- `@ZentOpsBot` restricted to staff/admin Telegram IDs.
- Shared Django integration layer and event hooks.
- Role-based access control for internal bot commands.
- Scheduled jobs for campaigns, reports, and alerts.

## Complete Feature Set

### Customer bot (`@ZentShopBot`)

- Personalized product feed from browsing and purchase history.
- New arrivals digest by chosen category/brand.
- Smart reminders:
  - abandoned cart reminder with deep link
  - coupon expiration reminder
  - seasonal campaign reminders
- Affiliate toolkit:
  - one-click referral link generation
  - deep link to product-specific referral pages
  - performance summary (clicks, conversions, pending commissions)
- Order and support:
  - order status lookup
  - delivery update notifications
  - return/exchange request intake form

### Operations bot (`@ZentOpsBot`)

- Real-time sales digest:
  - orders today
  - pending vs delivered counts
  - top products by order quantity
- Exception alerts:
  - sudden order failure spikes
  - unusual coupon usage patterns
  - high cancellation ratio alerts
- Workflow actions:
  - update order status quickly
  - trigger campaign broadcasts
  - send urgent customer notices
- Affiliate operations:
  - pending payouts report
  - mark payout references and notes
  - fraud review queue (self-referral/suspicious patterns)

### Analytics and BI features

- Weekly bot funnel report:
  - reached users
  - click-through rate
  - website conversion from bot traffic
- Campaign attribution:
  - campaign -> click -> order mapping
- Affiliate leaderboard and cohort reports.

## Integration with your current code

- Reuse affiliate and commission models already present.
- Reuse order status and cart logic for alerts and reminders.
- Build minimal extra endpoints for reporting and secure status updates.
- Add `telegram_chat_id` mapping table linked to user accounts.

## Implementation plan

1. Implement user-chat linking and consent flows.
2. Launch customer bot reminder and tracking features.
3. Launch ops bot dashboards and command permissions.
4. Add campaign scheduler and attribution tracking.
5. Add affiliate payout tooling and fraud checks.

## Pros

- Excellent for growth and operational efficiency.
- Lower risk than full in-chat checkout.
- Better team visibility and faster issue response.

## Cons

- Two-bot governance and permissions add complexity.
- Shopping experience is not fully in-chat.

## Best fit

Choose this if your priority is scaling traffic, improving repeat purchases, and giving staff faster operational control from Telegram.
