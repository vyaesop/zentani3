# Storefront UI Production Roadmap

## Goal
Make the storefront feel intentional, modern, and consistent across browsing, product discovery, and checkout instead of looking like a mix of theme-demo leftovers and one-off patches.

## Current Problems
- Browse pages solve the same problem in different ways, so category, brand, and search pages feel unrelated.
- Theme-demo filler is still visible in several places, especially fake filters, old banners, and placeholder content.
- Visual styling is fragmented between legacy theme classes and custom inline styles, which creates a janky look.
- The homepage, product page, and account pages do not yet share a strong storefront system.

## Action Plan

### 1. Normalize Browse Surfaces
Status: Completed

What I’m doing:
- Create one shared collection layout for category, brand, and search pages.
- Remove fake filter widgets and demo-only sections.
- Standardize browse headers, sidebar navigation, product grids, and pagination.
- Bring category and brand directory pages into the same visual system.

Success criteria:
- Browse and search pages look like part of one product-discovery experience.
- There are no obviously fake filters or placeholder brand names.
- Category, brand, and search pages use the same layout rhythm and visual language.

### 2. Rebuild the Homepage Around Merchandising
Status: Completed

What I’ll do:
- Replace leftover theme sections with a focused home structure.
- Create a stronger hero, featured collections, trending categories, and trust messaging.
- Remove ad hoc cards and mismatched promotional blocks.

Success criteria:
- The homepage quickly explains what Zentanee sells and where to start.
- The top half of the page supports scrolling into products instead of distracting from them.

### 3. Rebuild Product Detail for Conversion
Status: Completed

What I’ll do:
- Simplify the detail page structure.
- Remove remaining demo tabs, fake review/vendor content, and duplicated components.
- Build a stronger mobile-first buy section with clear size selection and delivery guidance.

Success criteria:
- A shopper can understand the product and next step within a few seconds.
- The page feels purpose-built rather than inherited from a generic theme.

### 4. Unify Cart, Account, and Auth UI
Status: Completed

What I’ll do:
- Bring cart, profile, login, register, and address flows into the same design language.
- Standardize spacing, hierarchy, action buttons, and empty states.
- Tighten mobile layout and reduce visual noise.

Success criteria:
- The transactional side of the store feels as polished as the shopping side.
- The step-by-step order flow feels calm and predictable.

### 5. Extract a Proper Storefront Design System
Status: Completed

What I’ll do:
- Move repeated UI styles into a cleaner shared layer.
- Standardize tokens for color, spacing, borders, buttons, cards, and section headers.
- Reduce inline styles and fragile page-specific overrides.

Success criteria:
- New UI work becomes faster and more consistent.
- The storefront no longer depends on scattered one-off styling to look acceptable.

## Current Focus
The core storefront roadmap items are complete. Remaining cleanup is now about older secondary pages that still use legacy theme markup.
