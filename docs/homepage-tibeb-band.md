# The Tibeb Band design system (storefront)

The storefront was redesigned with the impeccable skill (`/impeccable`, installed at
`.claude/skills/impeccable`): the homepage on 2026-09-03, the rest of the store on
2026-09-04. Product truth lives in `PRODUCT.md`; the direction contracts live in
`.impeccable/surfaces/*.md` (one per surface group); the visual system is recorded in
`DESIGN.md` and its sidecar `.impeccable/design.json`.

## The idea in one line

White cotton ground, ink type, and one dense woven band in ink, indigo and green (the *tibeb* border of Ethiopian
cotton dress) as the only ornament and the only structure: a thin woven line closes the
header, a full band opens the footer, and every section opens with a thread line. Depth by
overlap and 2px ink rules, never shadow. Every corner is square. Fees, prices, sizes and
times are tabular numerals; money is set in Unbounded.

## Files

| File | Role |
|---|---|
| `zentanee/static/asset/css/zent-tibeb.css` | The system: tokens, type, bands, buttons, chips, forms, rulers, rows, lists, tables, steps, product module, rails, prose, FAQ, alerts, toast, htmx states, and the shell (announcement, header, nav, drawer, tab bar, footer). Loaded by `templates/base.html`. |
| `zentanee/static/asset/css/zent-tibeb-bands.css` | Generated. The woven tiles as SVG data URIs, one rule per tint (default, `zh-band--indigo`, `zh-band--green`). |
| `zentanee/static/asset/css/zent-tibeb-pages.css` | Page layouts: catalog, cart/checkout/orders, account and static pages, product detail, in that order. |
| `zentanee/static/asset/css/zent-home.css` | Homepage only (hero, swatches, collections list, brands, channel row). |
| `templates/base.html` | The shell. `{% block header_band %}` lets a page suppress the thin header band (the homepage does, its hero band follows). |
| `templates/store/_tibeb_band.html` | Emits a band tile. `band_variant="thin"` for dividers; tint with `zh-band--indigo` / `zh-band--green` on the wrapping `.zh-band`. |
| `templates/store/_product_card_content.html` | The product module used everywhere (homepage, collections, rails, saved items). |
| `zentanee/static/asset/js/zent.js` | Behaviour: drawer, search suggestions, toast, sticky add-to-cart bar, filter column sync, copy buttons, GA4. |

Class prefix is `.zh-`. The Control Room dashboard is out of scope and keeps
`zent-core.css` + `zent-dashboard.css`.

## Adding a page

```django
{% extends 'base.html' %}
{% block content %}
<main class="zh-main"><div class="zh-wrap">
  <div class="zh-page__head">
    <h1>{% trans "Page title" %}</h1>
    <p class="zh-lede">{% trans "One sentence." %}</p>
  </div>
  <section class="zh-section">
    <div class="zh-band zh-band--indigo">{% include 'store/_tibeb_band.html' with band_variant="thin" %}</div>
    <div class="zh-section__head"><h2>…</h2><a href="…">…</a></div>
    …
  </section>
</div></main>
{% endblock %}
```

No eyebrow above a heading, no cards, no shadows, no radius, no thread colour outside the
bands (indigo alone leaves the weave: the 3px underline, the primary button's 6px selvedge, the focus ring). Numbers get `.zh-num`.

## Regenerating the band tiles

The tiles are authored geometry, not pictures. Change colours or motifs by editing and
re-running this snippet from the project root (Node 22):

```js
// node - <<'EOF'   (paste, then Ctrl-D)
const fs = require('fs');
const ink = '#111111';
function full({a, b, c, d}) {
  let s = `<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 120 64' width='120' height='64'>`;
  s += `<rect x='0' y='1' width='120' height='2' fill='${ink}'/>`;
  for (let i = 0; i < 5; i++) { const x = i * 24;
    s += `<polygon points='${x},26 ${x+12},8 ${x+24},26' fill='${a}'/>`;
    s += `<polygon points='${x+12},8 ${x+24},26 ${x+36},8' fill='${b}'/>`; }
  s += `<polygon points='-12,8 0,26 12,8' fill='${b}'/>`;
  for (let i = 0; i < 10; i++) s += `<rect x='${2 + i*12}' y='30' width='8' height='4' fill='${c}'/>`;
  for (let i = 0; i < 4; i++) { const cx = 15 + i * 30;
    s += `<polygon points='${cx},38 ${cx+12},48 ${cx},58 ${cx-12},48' fill='${c}'/>`;
    s += `<polygon points='${cx},43 ${cx+5},48 ${cx},53 ${cx-5},48' fill='${d}'/>`;
    s += `<rect x='${cx+14}' y='47' width='6' height='2' fill='${ink}'/><rect x='${cx+16}' y='45' width='2' height='6' fill='${ink}'/>`; }
  s += `<rect x='0' y='61' width='120' height='2' fill='${ink}'/></svg>`;
  return s;
}
function thin({a, b}) {
  return `<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 12' width='24' height='12'><rect x='0' y='0' width='24' height='1.5' fill='${ink}'/><rect x='1' y='4' width='10' height='4' fill='${a}'/><rect x='13' y='4' width='10' height='4' fill='${b}'/><rect x='0' y='10.5' width='24' height='1.5' fill='${ink}'/></svg>`;
}
const uri = (svg) => `url("data:image/svg+xml,${encodeURIComponent(svg).replace(/'/g, '%27').replace(/\(/g, '%28').replace(/\)/g, '%29')}")`;
const indigo = '#1f3a93', green = '#1b7f4c', paper = '#ffffff';
fs.writeFileSync('zentanee/static/asset/css/zent-tibeb-bands.css', `/* Generated woven tiles (authored SVG geometry, 1 tile = 120x64 or 24x12 units): ink, indigo and green only. Regenerate with docs/homepage-tibeb-band.md if colours change. Loaded site-wide by templates/base.html. */
.zh-band__tile--full { background-image: ${uri(full({a: indigo, b: ink, c: green, d: paper}))}; }
.zh-band--indigo .zh-band__tile--full { background-image: ${uri(full({a: ink, b: indigo, c: indigo, d: green}))}; }
.zh-band--green .zh-band__tile--full { background-image: ${uri(full({a: green, b: ink, c: indigo, d: paper}))}; }
.zh-band__tile--thin { background-image: ${uri(thin({a: indigo, b: ink}))}; }
.zh-band--indigo .zh-band__tile--thin { background-image: ${uri(thin({a: indigo, b: green}))}; }
.zh-band--green .zh-band__tile--thin { background-image: ${uri(thin({a: green, b: ink}))}; }
.zh-swatch::before { background-image: ${uri(thin({a: indigo, b: ink}))}; }
`);
// EOF
```

## Reviewing pages locally

```bash
python manage.py migrate --settings=zentanee.settings_local
ZENT_NOCACHE=1 python manage.py runserver 127.0.0.1:8765 --settings=zentanee.settings_local
```

`ZENT_NOCACHE=1` turns the fragment cache into a no-op so edits to cached partials
(`_home_sections.html`, the collection grid) show without a restart.

Screenshots for review were taken with Chrome's DevTools Protocol under device emulation
(390 px mobile, 1440 px desktop); Chrome's bare `--screenshot` flag lays the page out wider
than the requested width and produces misleading phone captures. Pages that need a session
(cart lines, checkout errors, account pages, confirmations) were rendered with Django's
test client to a standalone HTML file pointing at the dev server, then screenshotted.
