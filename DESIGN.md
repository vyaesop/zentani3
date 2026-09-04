---
name: Zentanee
description: Cotton-white ground, ink type, one woven tibeb band carrying every thread colour. Homepage system (body.zent-home-page).
colors:
  cotton-white: "#fbfbf8"
  ink: "#111111"
  ink-soft: "#3d3a36"
  paper: "#ffffff"
  thread-red: "#c8102e"
  thread-gold: "#f2b705"
  thread-indigo: "#1f3a93"
  thread-green: "#1b7f4c"
typography:
  display:
    fontFamily: "Unbounded, Archivo, Helvetica Neue, Arial, sans-serif"
    fontSize: "clamp(27px, 7.3vw, 82px)"
    fontWeight: 700
    lineHeight: 1.0
    letterSpacing: "-0.02em"
  headline:
    fontFamily: "Unbounded, Archivo, Helvetica Neue, Arial, sans-serif"
    fontSize: "clamp(22px, 4vw, 34px)"
    fontWeight: 700
    lineHeight: 1.05
    letterSpacing: "-0.02em"
  title:
    fontFamily: "Unbounded, Archivo, Helvetica Neue, Arial, sans-serif"
    fontSize: "15px"
    fontWeight: 600
    letterSpacing: "-0.01em"
    fontFeature: "tabular-nums lining-nums"
  body:
    fontFamily: "Archivo, Helvetica Neue, Arial, sans-serif"
    fontSize: "15px"
    fontWeight: 400
    lineHeight: 1.5
  label:
    fontFamily: "Archivo, Helvetica Neue, Arial, sans-serif"
    fontSize: "12px"
    fontWeight: 400
    letterSpacing: "0.02em"
  button:
    fontFamily: "Unbounded, Archivo, Helvetica Neue, Arial, sans-serif"
    fontSize: "12.5px"
    fontWeight: 600
    letterSpacing: "0.02em"
rounded:
  none: "0px"
spacing:
  xs: "4px"
  sm: "10px"
  md: "16px"
  lg: "20px"
  section: "40px"
  section-wide: "56px"
components:
  button-primary:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.paper}"
    typography: "{typography.button}"
    rounded: "{rounded.none}"
    padding: "0 16px"
    height: "50px"
  button-primary-hover:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
  button-ghost:
    backgroundColor: "transparent"
    textColor: "{colors.ink}"
    typography: "{typography.button}"
    rounded: "{rounded.none}"
    padding: "0 16px"
    height: "50px"
  button-ghost-hover:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.paper}"
  size-chip:
    backgroundColor: "transparent"
    textColor: "{colors.ink}"
    rounded: "{rounded.none}"
    padding: "0 8px"
    height: "30px"
  size-chip-hover:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.paper}"
  status-tag:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
    rounded: "{rounded.none}"
    padding: "4px 10px"
  status-tag-inverse:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.paper}"
  price-label:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.paper}"
    rounded: "{rounded.none}"
    padding: "2px 6px"
---

# Design System: Zentanee

## Overview

**Creative North Star: "The Tibeb Band"**

The homepage is a length of white cotton with one dense woven border. The *tibeb* (the patterned band on Ethiopian cotton dress) is the only ornament and the only structure: a full band opens the page and closes it, a thin thread line opens every section, and the products sit on top like cut cloth. Everything else is ink on cotton: black type, 2px black rules, black-bordered photos, black buttons. Depth comes from things overlapping, never from shadows or gradients.

The system is deliberately narrow in scope. It is built by `zentanee/static/asset/css/zent-home.css` and applies only to `body.zent-home-page` (the homepage). Header, footer, product pages, cart and account still run the shared "spring" storefront theme in `zent-core.css` / `zent-shim.css` / `zent-storefront.css`. The one element binding both worlds is the pop-art halftone black-and-white circular logo; the homepage's ink-on-white palette is chosen to sit under it. The direction contract and the build agree on every invariant; nothing in the shipped code diverges from the OWN-WORLD block.

Density is confident-sparse: a small catalogue (20 to 30 pieces) shown as a few large modules on a ruled grid, never padded to fill. Rulers, not cards: lists are separated by 2px ink rules and never boxed. Amharic swaps the type to Noto Sans Ethiopic with more leading; the palette and rules are unchanged.

**Key Characteristics:**
- Cotton-white ground with ink type; the four thread colours never appear as text or as fills outside the woven devices.
- One woven band motif, authored as SVG geometry and tiled as CSS backgrounds; full (120x64) for the page's top and foot, thin (24x12) for every section divider.
- Depth by overlap and 2px ink borders only; no box-shadow anywhere on the page.
- Tabular lining numerals on every fee, price, size, count and time.
- Buttons are black bars; the primary carries a 6px gold bottom edge (the selvedge).
- One motion moment: the hero band clip-paths in left to right once, and only when `prefers-reduced-motion: no-preference`.

## Colors

Two neutrals do almost all the work; four thread colours live inside woven devices and surface nowhere else.

### Primary
- **Ink** (`{colors.ink}`): all type, all rules and borders (2px), button fills, the swatch price label, scrollbar thumb, the diamond separators between brand names. Ink is the brand's voice; it is used at full strength, never tinted.
- **Cotton White** (`{colors.cotton-white}`): the page ground. Slightly warm so the pure-white photo frames and button hover state read as a lift against it.

### Secondary (the threads)
- **Thread Gold** (`{colors.thread-gold}`): the only thread that leaves the band. It appears as the 3px underline under highlighted phrases and section links (`.zh-thread`, `<mark>`, hero `<em>`), as the 6px selvedge under the primary button, as the 2px rule under a sold-out "Notify me" link, and as the text-selection background. Never as text, never as a fill area.
- **Thread Red** (`{colors.thread-red}`): chevrons in the default band and stripes in the default thin band; the under-tile beneath hero swatches.
- **Thread Indigo** (`{colors.thread-indigo}`): dashes and diamond chain in the default band; lead colour of the `--indigo` band tint (Collections, Brands). Also the 3px `:focus-visible` outline, the one place it acts outside a band.
- **Thread Green** (`{colors.thread-green}`): diamond centres in the default band; lead colour of the `--green` band tint (How it works, Channel).

### Neutral
- **Ink Soft** (`{colors.ink-soft}`): secondary text: the truth line, fee labels, brand under a product name, step body copy, counts, captions, struck compare-at prices.
- **Paper** (`{colors.paper}`): photo frame backgrounds, button text on ink, hover fill of the primary button, the status tag ground.

### Named Rules
**The Thread Stays in the Weave Rule.** Red, gold, indigo and green exist as SVG fills inside the band tiles. Outside the tiles, only gold is allowed, and only as a line: the 3px underline, the 6px button selvedge, the selection highlight. No thread colour is ever text, a background area, or a border around a box.

**The Two-Ink Rule.** Text is either Ink or Ink Soft. There is no third grey, no tinted text, no coloured link. Links are distinguished by weight and the gold underline, not by hue.

## Typography

**Display Font:** Unbounded 600/700 (with Archivo, Helvetica Neue, Arial fallback), loaded only by the homepage
**Body Font:** Archivo 400/500/600/700 (with Helvetica Neue, Arial fallback), shared with the rest of the store
**Amharic:** Noto Sans Ethiopic 400/600/700 replaces both stacks under `html[lang="am"]`; the hero headline relaxes to line-height 1.15 and letter-spacing 0

**Character:** Unbounded is wide, heavy and tight-set, so headlines read as a block stamped on cloth; Archivo underneath is plain and quiet. Unbounded also carries every number that matters (prices, fees, step numerals) so the truth of the page is in the loud face.

### Hierarchy
- **Display** (700, `clamp(27px, 7.3vw, 82px)` on phones, `clamp(44px, 5.6vw, 82px)` from 768px, line-height 1.0, -0.02em, `text-wrap: balance`, max 20ch): the hero headline only. Its emphasised phrase (`<em>`) is upright ink with the gold underline.
- **Headline** (700, `clamp(22px, 4vw, 34px)`, line-height 1.05, -0.02em): section titles. Collection names run larger (`clamp(20px, 5vw, 36px)`, line-height 1) because each one is a row, not a heading.
- **Title** (600, 15 to 17px, -0.01em, tabular numerals): fee values in the ruler (17px), product prices (15px; 19px on the lead module), step titles (16px), brand names (15px). Step numerals are the same face at 700, 30px.
- **Body** (400, 15 to 16px, line-height 1.5 to 1.55; truth line 18px from 768px): the truth line (max 34ch), step copy (max 46ch), channel copy (max 52ch). Product titles are Archivo 500, 15px, line-height 1.35.
- **Label** (400, 12 to 13px, +0.02em, Ink Soft): fee labels, brand under a product, counts, captions, delivery times. Uppercase appears once, on the status tag (700, 10.5px, +0.06em).
- **Button** (Unbounded 600, 12.5px, +0.02em): all `.zh-btn` labels.

### Named Rules
**The Tabular Truth Rule.** Every fee, price, size, count and time carries `font-variant-numeric: tabular-nums lining-nums` (`.zh-num`). Numbers that describe money or delivery are set in the display face so they align and read as commitments, not footnotes.

**The Gold Underline Rule.** Emphasis and links use one device: a 3px gold underline, offset 0.14em, `text-decoration-skip-ink: none`. No bold-only emphasis, no coloured text, no italics. On hover the underline turns ink or appears under the linked title.

## Layout

Phone first at 390px; the desktop composition inherits from it. Content sits in the shared `.spring-container`; the woven bands run edge to edge above it (the hero and foot bands are full-bleed, the thin dividers span the container).

- **Hero (phone):** a three-row grid: headline, then the three overlapping swatches, then the body (truth line, actions, fee ruler; the ruler is visually reordered below the actions so the primary button stays in the first viewport). Row gap 18px, 22px above.
- **Hero (768px and up):** two columns, headline spanning both; body left, swatches right. Column gap 48px (72px from 1200px), row gap 28px, 40px above (48px from 1200px).
- **Fee ruler:** 2 columns on phones, 4 from 768px; cells divided by 2px ink rules top, bottom and between; 8px/12px cell padding.
- **The drop / Most wanted:** on phones a horizontal snap rail bled to the viewport edge (`margin: 0 calc(50% - 50vw)`), columns `min(72vw, 300px)`, gap 16px. From 768px a 4-column dense grid, gap 20px, row gap 28px, with the first module spanning 2x2 (the lead piece).
- **Recently viewed:** 2 columns on phones, 4 from 768px, no rail.
- **Collections, steps:** ruled lists, not cards. Steps stack on phones (56px numeral column) and become three ruled columns from 768px.
- **Rhythm:** sections open with a thin band, then a heading row (`margin: 18px 0 20px`), and carry 40px top padding (56px from 1200px). Component-internal gaps step 4 / 10 / 16 / 20px.
- **Band heights:** full band 56px on phones, 72px from 768px, 88px from 1200px; thin band 10px everywhere. Tiles repeat at the band's own height (`background-size: auto 100%`) so the weave is never stretched.

## Elevation & Depth

There are no shadows on the homepage. Depth is physical: the three hero swatches overlap by 22px, step down by 14/26px on phones (28/56px from 768px), and are stacked by z-index so the newest piece sits on top; under each one a thin woven tile is offset 12px down and right, so the photo reads as cloth laid on a strip of cloth. Everywhere else, edges are drawn: 2px ink borders around photos and swatches, 2px ink rules between rows and ruler cells. State is shown by inversion (ink to white, white to ink) or by a border thickening from 2px to 3px, never by a lift.

### Named Rules
**The Overlap Not Shadow Rule.** If two things need to read as layered, one overlaps the other and both keep a 2px ink edge. `box-shadow` does not appear in this system, at rest or on hover.

## Shapes

Square. Every corner on the page is 0px: buttons, photo frames, tags, size chips, swatches, the empty-state dashed box. The single radius in the stylesheet is the 2px on the `:focus-visible` outline. Borders are 2px solid ink (3px on a hovered swatch, 2px dashed for the empty state). The band supplies all the geometry the page needs: chevrons, dashes, a diamond chain and a selvedge line; the same diamond, as an 8px rotated ink square, separates brand names. Photos are 4:5 portraits, cover-fitted, on a white frame.

## Components

### Buttons
Black bars set in the display face; the primary is hemmed with gold.
- **Shape:** square (0px), 2px ink border, min-height 50px, `inline-flex` with a 10px gap for an optional leading icon.
- **Primary:** ink fill, white text, `padding 0 16px` (0 22px from 768px), plus a **6px gold bottom border, the selvedge**. On phones the two hero actions share the row at equal width.
- **Ghost:** transparent fill, ink text, same border and size.
- **Hover / Focus:** inversion. Primary becomes white with ink text (the selvedge stays gold); ghost becomes ink with white text. `:active` translates down 1px. Transitions: transform 220ms on the world ease `cubic-bezier(0.16, 1, 0.3, 1)`, colour 160ms.
- **Focus ring (global):** 3px solid indigo outline, 3px offset, 2px radius.

### Size Chips
Quick-add buttons under a product, one per available size (htmx post).
- **Style:** transparent, 2px ink border, ink text, Archivo 600 11.5px tabular, min-width 34px, height 30px, 4px gaps.
- **State:** hover and focus invert to ink fill / white text (140ms); while the request is in flight the chip drops to 50% opacity and ignores pointer events.

### Status Tag
A small flag pinned to the top-left of a product photo, overlapping its border by 2px.
- **Style:** white ground, 2px ink border with no left edge, uppercase 700 10.5px +0.06em, `padding 4px 10px`.
- **Variants:** "New" and "Most wanted" on white; sale ("-N%") and "Sold out" inverted to ink with white text. Only one tag shows per module, in the priority sold out > sale > most wanted > new.

### Product Module
A photo, a name, a price, a size ruler. No card chrome.
- **Media:** 4:5 cover photo on a white frame with a 2px ink border.
- **Body:** 4px gaps: Archivo 500 title (ink; gold-underlined on module hover), brand in Ink Soft 12px, price in Unbounded 600 15px tabular. A sale price shows the compare-at price struck in Archivo 400 Ink Soft 8px to its right; a sold-out module shows "Sold out" in Ink Soft with a 12px "Notify me" link ruled in gold.
- **Lead module:** in a `.zh-rail--weave` grid the first module spans 2x2 from 768px and its title and price step up to 19px.

### Fee Ruler
Four real numbers (Addis fee, free threshold, outside fee, delivery days) in a list bounded top and bottom by 2px ink rules and divided by 2px ink rules. Label in Ink Soft 12px above, value in Unbounded 600 17px ink. Two columns on phones, four from 768px.

### Hero Swatches (signature)
The three newest pieces, cropped 4:5, overlapping like cut cloth. Each swatch is a link: photo with 2px ink border, a thin woven tile offset 12px beneath it, and the price as a white-on-ink label hanging 24px below the right edge. Hover and focus thicken the border to 3px. When there are no live products the slot becomes a 2px dashed ink box with a one-line message; it never fills with placeholders.

### Woven Band (signature)
`templates/store/_tibeb_band.html` emits one `aria-hidden` div whose background is an authored SVG tile from `zent-home-bands.css`. Variants: `full` (selvedge lines, chevrons, dashes, diamond chain; 120x64 tile) for the top and foot of the page; `thin` (two selvedge lines and alternating stripes; 24x12 tile) for section dividers. Tints: default (red/gold with indigo and green details), `zh-band--indigo` (indigo/red with gold), `zh-band--green` (green/gold with ink and red). The hero band carries `zh-band--weave`: under `prefers-reduced-motion: no-preference` it reveals once from `clip-path: inset(0 100% 0 0)` to `inset(0)` over 1100ms on the world ease. Colours or motifs are changed by regenerating the tiles; see `docs/homepage-tibeb-band.md`.

### Ruled Lists (collections, steps)
Rows separated by 2px ink rules with no boxes. A collection row is name (display 700), count (Ink Soft 13px, tabular) and a 56px (72px from 768px) square photo swatch with a 2px ink border, or an empty ink-outlined square when there is no image. A step is a 30px display numeral, a 16px display title, Ink Soft body copy, and a 12px tabular time line.

### Navigation
Not part of this system. The header, footer and mobile tab bar are the shared spring theme; the homepage only hides the footer's Telegram CTA (`.spring-footer__telegram`) because the page carries its own channel section.

## Do's and Don'ts

### Do:
- **Do** scope new homepage styles under `body.zent-home-page` with the `.zh-` prefix; the shared theme's `.spring-body a` colour rules otherwise win.
- **Do** open every new section with a thin woven band and a 2px-ruled heading row; use the `--indigo` or `--green` tint to vary sections, not new colours.
- **Do** set every number a shopper can act on (fee, price, size, count, days, hours) in `.zh-num` tabular lining figures, and set money in Unbounded 600.
- **Do** emphasise with the 3px gold underline (`.zh-thread` or `<mark>`), and mark the primary action with the 6px gold selvedge.
- **Do** layer by overlap with 2px ink edges; show hover and focus by inverting ink and white or thickening a border.
- **Do** keep the empty state honest: the dashed ink box with one sentence, never placeholder products.

### Don't:
- **Don't** use `box-shadow`, gradients, or blur anywhere on the homepage.
- **Don't** use red, indigo or green as text, backgrounds or borders outside the band tiles (indigo's one exception is the focus outline); don't use gold as text or as a filled area.
- **Don't** round corners; every box is 0px.
- **Don't** box content into cards; separate rows with 2px ink rules.
- **Don't** add a photo hero, stock imagery or `asset/images/banner.webp`; the band and the products carry the viewport.
- **Don't** invent testimonials, review counts or metrics; the page shows only real fees, times, phone number and channel.
- **Don't** apply this system to other storefront pages by default; they run the shared spring theme, and the halftone logo is the only element both worlds share.
