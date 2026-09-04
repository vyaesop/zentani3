---
version: 1
slug: "templates-store-cart-html"
primary_target: "templates/store/cart.html"
related_targets: ["templates/store/_cart_contents.html","templates/store/order_confirmation.html","templates/store/orders.html"]
---

## Scope

Cart and checkout (`templates/store/cart.html`, `_cart_contents.html`), order confirmation (`order_confirmation.html`), order history and tracking (`orders.html`), review invitation (`review_invite.html`), Telegram opt-in partial and flow status partial. Visitor mode: Operate (the shopper completes an order or checks on one).

## Direction contract

THESIS: The cart is an order slip: every line, fee and total in tabular figures on ink rules, the checkout form in the same ruled discipline, so the shopper can read the whole commitment before the driver ever knocks.

OWN-WORLD: DESIGN.md system. Cart lines as ruled rows with a 2px ink-framed thumbnail, title, size, quantity stepper made of ink chips, line total in Unbounded 600 tabular. Summary as a fee ruler (subtotal, delivery, total). Form fields are 2px ink boxes with uppercase Archivo labels; errors are ink 600 with the indigo thread under them. Place Order is the black selvedge bar. Order timeline is a ruled list with ink numerals; the current step carries the indigo thread.

STORY: Review the lines, adjust a quantity, read the fee ruler, fill name, phone and landmark, place the order, land on a confirmation whose order number is in Unbounded and whose next step is stated plainly.

FIRST VIEWPORT: 390px phone. Shell, heading "Your cart" with the line count, the first cart line in full, the fee ruler visible or one scroll away; on the confirmation page the order number and the "we call to confirm" sentence lead.

FORM: Extension of direction 0a6966cd "Tibeb Band". No new world.

FINISH: reviewed at 390 and 1440 with a two-line cart, an empty cart, a validation error, and a confirmation; quantity, coupon, checkout and claim forms keep their ids and htmx behaviour.

## Unresolved

None.
