# Homepage: the Tibeb Band world

The homepage (`templates/store/index.html` + `templates/store/_home_sections.html`) was
redesigned on 2026-09-03 with the impeccable skill (`/impeccable`, installed at
`.claude/skills/impeccable`). Product truth lives in `PRODUCT.md`; the direction contract
lives in `.impeccable/surfaces/templates-store-index-html.md`; the visual system is
recorded in `DESIGN.md`.

## The idea in one line

White cotton ground, ink type, and one dense woven band (the *tibeb* border of Ethiopian
cotton dress) as the page's only structure. Products overlap like cut cloth on flat colour.
Fees, sizes and times are tabular numerals. Depth by overlap, never shadow.

## Files

| File | Role |
|---|---|
| `zentanee/static/asset/css/zent-home.css` | The world's stylesheet, loaded only by the homepage (`body.zent-home-page`). |
| `zentanee/static/asset/css/zent-home-bands.css` | Generated. The woven tiles as SVG data URIs, one rule per tint. |
| `templates/store/_tibeb_band.html` | Emits the band div. `band_variant="thin"` for dividers; tint with `zh-band--indigo` / `zh-band--green` on the wrapper. |
| `templates/store/_home_product_module.html` | Homepage product module (photo, name, price, size ruler with htmx quick-add). |

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
const red = '#c8102e', gold = '#f2b705', indigo = '#1f3a93', green = '#1b7f4c';
fs.writeFileSync('zentanee/static/asset/css/zent-home-bands.css', `/* Generated woven tiles (authored SVG geometry, 1 tile = 120x64 or 24x12 units). Regenerate with docs/homepage-tibeb-band.md if colours change. */
.zh-band__tile--full { background-image: ${uri(full({a: red, b: gold, c: indigo, d: green}))}; }
.zh-band--indigo .zh-band__tile--full { background-image: ${uri(full({a: indigo, b: red, c: gold, d: green}))}; }
.zh-band--green .zh-band__tile--full { background-image: ${uri(full({a: green, b: gold, c: ink, d: red}))}; }
.zh-band__tile--thin { background-image: ${uri(thin({a: red, b: gold}))}; }
.zh-band--indigo .zh-band__tile--thin { background-image: ${uri(thin({a: indigo, b: red}))}; }
.zh-band--green .zh-band__tile--thin { background-image: ${uri(thin({a: green, b: gold}))}; }
.zh-swatch::before { background-image: ${uri(thin({a: red, b: gold}))}; }
`);
// EOF
```

## Reviewing the page locally

```bash
python manage.py migrate --settings=zentanee.settings_local
python manage.py runserver 127.0.0.1:8765 --settings=zentanee.settings_local
```

Screenshots for review were taken with Chrome's DevTools Protocol under device emulation
(390 px mobile, 1440 px desktop); Chrome's bare `--screenshot` flag lays the page out wider
than the requested width and produces misleading phone captures.

The anonymous homepage caches its sections fragment for ten minutes (`{% cache 600
home_sections ... %}`); restart the dev server (or bump the catalog version) after editing
`_home_sections.html` to see changes as an anonymous visitor.
