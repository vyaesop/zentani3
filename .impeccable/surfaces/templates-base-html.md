---
version: 1
slug: "templates-base-html"
primary_target: "templates/base.html"
related_targets: []
---

## Scope

Site shell (`templates/base.html`): announcement bar, header, primary nav, mobile drawer, phone tab bar, footer, toast and flash messages. Wraps every storefront page. Visitor mode: Operate (finding, searching and getting back are tasks). Extends the Tibeb Band world recorded in DESIGN.md from the homepage to the whole store; the homepage keeps its own hero and hides the shell's channel row.

## Direction contract

THESIS: The header is the top selvedge of the cloth and the footer its hem; one thin woven line under the header and one full band above the footer frame every page, so a shopper always knows which store they are in without a single decorative element elsewhere.

OWN-WORLD: Cotton-white ground, ink type; Unbounded 600 uppercase for nav labels, Archivo for everything else; 2px ink rules instead of borders and shadows; thread colours (indigo, green) only in the woven tiles; indigo alone leaves the weave, as the 3px underline (current page, hover), the primary button selvedge and the focus ring; no red, no yellow anywhere. Halftone logo mark plus Unbounded wordmark centred in the header.

STORY: Menu, search, logo, account, cart in one ruled row; a thin band closes the header; the page begins. At the bottom the full band closes the cloth, then a ruled footer: channel row, four link columns, legal line.

FIRST VIEWPORT: 390px phone. Ink announcement bar, one header row (square menu button, logo, cart with tabular count), thin woven line, then the page's own first viewport. The tab bar (Home, Shop, Sale, Cart, Me) sits on a 2px ink rule with a indigo 3px selvedge on the active tab.

FORM: Extension of direction 0a6966cd "Tibeb Band" (assigned, built on the homepage). No new world.

FINISH: reviewed at 390 and 1440 with the drawer open and closed, with and without a cart count; documented in DESIGN.md as the site system.

## Unresolved

None. Font Awesome glyph icons remain the icon set (one stroke, one weight) until an authored SVG set exists.
