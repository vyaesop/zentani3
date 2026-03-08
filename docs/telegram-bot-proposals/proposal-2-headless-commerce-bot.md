# Proposal 2: Headless Commerce Bot (Telegram-First)

## Summary

Create a full conversational shopping flow inside Telegram: browse, select size, add to cart, apply coupon, enter address, and place order. The website remains available, but Telegram becomes a complete sales channel.

## Architecture

- Introduce internal API endpoints in Django (REST/JSON) for bot operations.
- Bot engine (Django app or separate Python worker) with finite-state conversation flows.
- Shared business logic layer so bot and website use the same validation rules.
- Persistent conversation/session state store (Redis or DB table).
- Event queue (optional) for notifications and retries.

## Complete Feature Set

### Customer shopping features

- Guided onboarding:
  - account link or quick registration flow
  - saved address capture
- Catalog browsing in chat:
  - categories, brands, featured
  - pagination and quick filters
- Product details with image gallery and size picker.
- Add-to-cart with size validation.
- Cart management in chat:
  - list items
  - increase/decrease quantity
  - remove line
- Coupon flow:
  - apply code
  - explain invalid/expired code
- Checkout in chat:
  - choose saved address or add new
  - order summary with line totals
  - place order
- Post-purchase updates:
  - status notifications as order progresses
  - quick reorder from past order

### Payments and fulfillment

- Option A: Cash on Delivery order creation through existing checkout logic.
- Option B: Telegram payments (if supported in your region/provider).
- Delivery note and preferred contact capture.
- Automatic sold-out guardrails during checkout.

### Account and loyalty features

- My orders history in chat.
- My addresses management.
- Affiliate center in chat:
  - get referral link
  - clicks/conversions summary
  - pending/paid commission snapshot
- Personalized recommendations from browsing/order history.

### Growth automation

- Abandoned cart reminders triggered by inactivity windows.
- Restock notifications for sold-out products.
- Segment-based campaigns:
  - by category interest
  - by order recency
  - by affiliate status

### Admin and operations features

- Admin bot panel commands:
  - campaign creation and scheduling
  - order queue snapshot
  - low stock/sold-out alerts
- Moderation controls:
  - block user
  - quiet hours
  - global announcement pause

## Integration with your current code

- Use `Product`, `Cart`, `Coupon`, `Order`, `Address` directly through service methods.
- Reuse `_coupon_issue`, `_effective_unit_price`, and checkout validations.
- Preserve affiliate behavior with `AffiliateProfile`, `AffiliateClick`, `AffiliateCommission`.
- Keep website and bot order status in the same `Order.status` field.

## Implementation plan

1. Extract reusable commerce service layer from current views.
2. Create authenticated internal APIs for bot operations.
3. Build conversational state machine (browse -> cart -> checkout).
4. Implement address and coupon flows.
5. Connect order placement and status notification pipeline.
6. Add growth automation jobs and admin controls.
7. Load test webhook throughput and retry behavior.

## Pros

- Best Telegram-native user experience.
- Strongest potential conversion lift for Telegram-heavy users.
- Unified commerce data remains in Django.

## Cons

- Highest engineering effort and QA surface.
- Requires careful conversation-state handling and error recovery.

## Best fit

Choose this if Telegram is a primary channel and you want end-to-end purchases without sending users back to the website.
