# GOJO Shop catalog scraper

Imports products from the public **gojoshop.et** storefront into this store's
`Product` / `Category` / `Brand` / `ProductImages` models.

Command: `store/management/commands/scrape_gojoshop.py`

## Why you run it locally (not from Cowork)

gojoshop.et blocks datacenter/proxy traffic, so the scrape has to run from a
machine with normal internet access — your laptop or the production server. It
cannot be run from the sandboxed assistant environment.

## Install the two extra dependencies

```bash
pip install requests beautifulsoup4
```

(They aren't in `requirements.txt`; add them there if you want this permanent.)

## Recommended first run — inspect before importing

Parse a sample, write it to JSON, download nothing, touch no database:

```bash
python manage.py scrape_gojoshop --limit 20 --output-json gojo_sample.json --skip-images --dry-run
```

Open `gojo_sample.json` and confirm titles, prices, categories and image URLs
look right. `docs/gojo_sample_output.json` is a real one-record example of
that format.

## Full import

```bash
python manage.py scrape_gojoshop
```

This crawls the sitemap **and** paginates the "latest" feed (so it catches
products the sitemap omits), then for each product downloads the images and
upserts the row. It is idempotent — keyed on `sku` (the trailing id in each
product URL, e.g. `QS64nR`), so re-running updates instead of duplicating.

## Flags

| Flag | Effect |
|------|--------|
| `--limit N` | Stop after N products (0 = all). |
| `--dry-run` | Parse only, never write to the DB. |
| `--output-json PATH` | Dump every parsed product to a JSON array. |
| `--skip-images` | Don't download images (faster; new rows need an image, so they're skipped). |
| `--refresh-images` | Re-download images even if the product already has one. |
| `--url URL` | Scrape specific product URL(s); repeat the flag for several. |
| `--debug` | Print the parsed dict per product. |
| `--sleep SECONDS` | Delay between fetches (default 0.5). Be polite. |
| `--max-price N` | Skip DB import of items priced above N (model cap is 999999.99). |
| `--to-ai-queue` | Queue AI drafts for Gemini enrichment instead of importing directly (see below). |

## Recommended import path: `--to-ai-queue`

Direct import copies the source copy verbatim (often Amharic-only, sometimes
uncategorized) and publishes immediately. With `--to-ai-queue` the scraper
instead creates a `ProductAIDraft` per item (scraped image + sku + price +
sizes) and enqueues it on the existing Gemini enrichment pipeline — the same
one the dashboard AI intake uses. Gemini writes the title, descriptions, SEO
fields and picks/creates the collection and brand, then creates the product.

```bash
python manage.py scrape_gojoshop --limit 5 --to-ai-queue
python manage.py run_tasks            # drain the queue (or --forever for a worker)
```

Drafts are owned by the first superuser. Items already present (by product or
draft `sku`), sold out at source, or missing an image/price are skipped.

## How fields map

| Source (gojoshop.et) | Target field |
|----------------------|--------------|
| Product name (English + Amharic) | `title`, `seo_title` |
| `og:description` / meta description | `short_description`, `seo_description` |
| Overview tab HTML | `detail_description` |
| Displayed price | `price` |
| Struck-through price (if on sale) | `compare_at_price` |
| Breadcrumb / JSON-LD category | `category` (get-or-created) |
| Brand row if present | `brand` (get-or-created, else null) |
| `/storage/product/*` images | `product_image` (first) + `ProductImages` (rest) |
| "Out of stock" flag | `is_sold_out`, `stock_quantity` |
| Size variations if present | `set_product_sizes(...)` |

## Selectors may need a nudge

Parsing prefers JSON-LD structured data, then falls back to meta tags and
regex. If a field comes out empty on a real run, use
`--url <a product> --debug --dry-run` to see the parsed dict, then adjust the
`_visible_title`, `_overview_html`, `_prices`, `_category` or `_sizes` helpers.

## Legal note

This copies vendors' names, descriptions and photos verbatim from a
third-party multi-vendor marketplace. Make sure you have the right to
republish that content before making the imported products public. A lower-risk
alternative is to import the factual data only and regenerate copy/images with
this project's own AI enrichment pipeline.
