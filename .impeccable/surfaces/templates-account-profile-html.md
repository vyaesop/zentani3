---
version: 1
slug: "templates-account-profile-html"
primary_target: "templates/account/profile.html"
related_targets: ["templates/account/login.html","templates/store/faq.html","templates/store/contact.html","templates/404.html"]
---

## Scope

Account and static pages: login, register, profile with saved items, add address, password change and reset flows, referral dashboard (`templates/account/*.html`); about, contact, FAQ, delivery and returns, privacy, terms (`templates/store/about-us.html`, `contact.html`, `faq.html`, `delivery-returns.html`, `privacy.html`, `terms.html`); error pages (`templates/404.html`, `500.html`). Visitor modes: Operate for account forms, Read for the static pages and FAQ.

## Direction contract

THESIS: Forms and policies are written on the same cloth: one ruled column of plain fields, one measure of readable prose, no cards, no panels, so the quiet pages feel like the same store as the loud homepage.

OWN-WORLD: DESIGN.md system. Page headings in Unbounded display without eyebrows; body prose in Archivo 16px at a 65 to 72ch measure; definition-style rows (label, value) on 2px ink rules; forms in 2px ink boxes with uppercase labels, primary actions as the black selvedge bar, secondary as ghost. FAQ as a ruled list of `<details>` with an ink plus that rotates. Error pages carry the thin band, one sentence and two actions.

STORY: The shopper lands on a plain heading, reads or fills one column, and leaves by one clear action.

FIRST VIEWPORT: 390px phone. Shell, heading, first paragraph or first field, primary action within one scroll.

FORM: Extension of direction 0a6966cd "Tibeb Band". No new world.

FINISH: reviewed at 390 and 1440 on login (with a validation error), profile, FAQ and 404; Django form field ids and names unchanged.

## Unresolved

None.
