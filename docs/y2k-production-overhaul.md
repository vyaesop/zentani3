# Zentanee Y2K Production Overhaul

## Goal
Build a storefront that feels unmistakably Zentanee: fast, mobile-first, polished enough for production, and visually closer to a sharp Y2K fashion destination than a recycled marketplace template.

## Audit Findings

### 1. Character Drift
- The current storefront is structurally cleaner than before, but the visual system is still beige, safe, and theme-derived.
- Copy explains the flow well, but it often sounds like a UX note instead of a fashion brand with taste and energy.
- The shell still carries Wolmart-era layout habits, so even refreshed pages inherit generic ecommerce body language.

### 2. Mobile Hierarchy Is Better Than Before, But Still Not Leading
- The site works on mobile, but it still reads like a desktop theme that was adapted down rather than designed from the phone upward.
- Header, search, navigation, and collection discovery need a tighter one-thumb hierarchy.
- Product cards and page heroes need stronger scanability and less explanatory clutter.

### 3. Performance + Dead Code Problems
- `templates/base.html` still shipped old quick-view markup and a heavy theme shell that is no longer part of the product.
- Google `Poppins` plus `webfont.js` added extra weight while also making the site feel visually generic.
- Several routes still point at legacy/demo templates, and one live route (`all-products`) had no template at all.
- There are still production-facing pages whose content is theme filler or broken instead of intentional store UX.

### 4. Production Readiness Gaps
- The contact route did not have a real template.
- Legacy `shop`, `checkout`, and `test` surfaces still diluted confidence.
- Footer and support language was generic and sometimes inaccurate for the real business.

## Plan

### Phase 1. Shell Reset + Dead Code Cleanup
Status: Initial pass completed

- Rebuild the global shell around a bolder Y2K visual language.
- Make header, sticky footer, mobile menu, search, and footer feel designed together.
- Remove dead quick-view and theme residue from `base.html`.
- Drop external font loading and move to a lighter, more intentional local font stack.
- Fix broken production surfaces:
  - create a real `products.html`
  - create a real `contact.html`
  - redirect or retire demo-only routes where appropriate

### Phase 2. Homepage + Browse Identity
Status: Initial pass completed

- Rewrite homepage copy and composition around drops, categories, and featured products.
- Give product cards more attitude, tighter copy, and faster mobile scanning.
- Strengthen browse and directory pages so they feel like one branded discovery system.

### Phase 3. PDP + Conversion Surfaces
Status: Initial pass completed

- Rebuild the product page with a stronger visual hierarchy, clearer size behavior, and more confident trust cues.
- Tighten cart, orders, and account flows so they keep the same brand voice instead of falling back to dashboard utility styling.

### Phase 4. Route + Asset Cleanup
Status: Initial pass completed

- Replace remaining legacy pages (`about`, old `shop`, old `checkout`, `test`) with production surfaces or redirects.
- Audit plugin and script usage page by page and remove assets that are no longer needed.
- Do a final pass for accessibility, responsive spacing, and copy consistency.

## Immediate Execution
I am starting with Phase 1 because it changes the whole emotional feel of the site at once and removes the biggest remaining template residue that makes the UI feel generic.
