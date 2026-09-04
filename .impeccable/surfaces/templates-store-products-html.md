---
version: 1
slug: "templates-store-products-html"
primary_target: "templates/store/products.html"
related_targets: ["templates/store/_collection_header.html","templates/store/_collection_sidebar.html","templates/store/_collection_grid_items.html","templates/store/_product_card_content.html","templates/store/search.html","templates/store/categories.html","templates/store/brands.html"]
---

## Scope

Collection pages: all products, sale, search results, category and brand pages, plus the collections and brands directories (`templates/store/products.html`, `sale_products.html`, `search.html`, `category_products.html`, `brand_products.html`, `categories.html`, `brands.html`, `_collection_*.html`, `_product_card_content.html`, `_directory_card.html`, `_search_empty.html`, `product_unavailable.html`). Visitor mode: Persuade (the shopper decides which piece to open). Small catalogue: 20 to 30 pieces, never padded.

## Direction contract

THESIS: A collection is a bolt of cloth unrolled: the heading is the label, the fee ruler's discipline carries into the filters, and the pieces hang on one ruled grid, fewer and larger than a category default.

OWN-WORLD: DESIGN.md system. Heading in Unbounded display with the live count in tabular figures; no eyebrow. Filters are ruled groups of ink chips (size, price, category, brand), not a boxed sidebar; the sort control is a 2px ink select. Product modules are the homepage module: 4:5 photo with 2px ink frame, single status tag, Archivo title, Unbounded price, size chips that quick-add, a square ink save button.

STORY: The shopper reads the heading and count, narrows with a chip or two, scans two columns of large photos on the phone, taps a size to add or a photo to open.

FIRST VIEWPORT: 390px phone. Shell, heading with count, one row of active filter chips and the sort select, then the first two modules in full. Filters open as a ruled drawer below the toolbar on phones and sit as a ruled left column from 1024px.

FORM: Extension of direction 0a6966cd "Tibeb Band". No new world.

FINISH: reviewed at 390 and 1440 with a full grid, an empty result, and a load-more page; the htmx swap targets and ids keep working.

## Unresolved

None.
