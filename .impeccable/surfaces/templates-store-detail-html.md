---
version: 1
slug: "templates-store-detail-html"
primary_target: "templates/store/detail.html"
related_targets: ["templates/store/_wishlist_button.html"]
---

## Scope

Product detail page (`templates/store/detail.html`) and its partials (wishlist button, sticky add-to-cart bar, restock form, size guide, reviews, related rails). Visitor mode: Persuade (the shopper picks a size and adds, or orders on Telegram).

## Direction contract

THESIS: One piece laid on the cloth: the photo is the page, the size ruler is the only control, and the inspect-before-you-pay mechanism sits next to the price as fact, not as a trust badge.

OWN-WORLD: DESIGN.md system. Gallery photos with 2px ink frames and a thin woven under-tile beneath the main image (the homepage swatch device); thumbnails as ink-framed squares. Title in Unbounded display, price in Unbounded 600 tabular, compare-at struck in Archivo Ink Soft. Sizes are 2px ink chips that invert when selected; the add button is the black selvedge bar; Order on Telegram is the ghost bar. Fee facts in a ruler. Reviews and description are ruled lists.

STORY: Photo, name, price, sizes, add; below it the fees and the three-step mechanism; then description, fit feedback and reviews; then more pieces from the same drop.

FIRST VIEWPORT: 390px phone. Shell, main photo full width with its under-tile, title, brand, price, size chips, black add-to-cart bar. The sticky bar appears once the main button scrolls away and repeats price plus add.

FORM: Extension of direction 0a6966cd "Tibeb Band". No new world.

FINISH: reviewed at 390 and 1440 with a multi-size product, a sold-out product with the restock form, and a sale price; the add-to-cart, wishlist, restock and review forms keep their ids and htmx behaviour.

## Unresolved

None.
