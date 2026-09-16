# Design

<!-- impeccable:design-schema 1 -->

## World

"Elevated Quiet Enterprise" — the existing HackerEarth-branded tonal system
(brand accents, fixed status/ordinal/rating hues, Geist Variable, the
plane→surface→surface-2→surface-3 tonal ladder) kept exactly as brand
truth, with a real depth and motion layer added on top: cards and stat
tiles now cast soft directional shadows and lift on hover instead of only
shifting tone; the topbar is sticky and glassed because content genuinely
scrolls beneath it; every stat/card grid, the rank-bar charts, and the
donut charts animate in on mount; the sidebar's active link carries a
brand-hued rail. Restrained color strategy, unchanged — depth and motion
carry the "elevated" feeling, not new hue.

## Tokens (additions to `frontend/src/theme.css`)

- `--ease-out: cubic-bezier(0.16, 1, 0.3, 1)` — the one easing curve for
  every authored transition/animation in the app (exponential-out, no
  bounce).
- `--dur-fast: 140ms` / `--dur-base: 320ms` / `--dur-slow: 560ms`.
- `--shadow-rest` / `--shadow-lift` — the resting→hover shadow delta for
  cards and stat tiles, defined per theme (light, dark, and both explicit
  `data-theme` overrides) alongside the pre-existing `--shadow` /
  `--shadow-hover` (still reserved for genuinely floating chrome: dialogs,
  the active nav pill).

All existing brand, status, ordinal, and rating tokens are untouched.
Contrast re-verified with `npm run check:contrast` — unaffected (no ink/
surface pair was touched).

## Motion grammar

- **Entrance:** `.reveal-stagger > *`, `.stat-row > *`, and `.grid > *`
  fade/rise in with a capped 12-step stagger (`row-in` keyframe,
  `theme.css`/`App.css`). This is a shared primitive extension — every
  route that lays its content out with `.stat-row`/`.grid` (all of them)
  gets the entrance for free, no per-route change needed.
- **Charts:** `Donut` now animates its arcs in (`isAnimationActive`,
  700ms ease-out) and each slice carries a subtle top-to-bottom gradient
  instead of a flat fill. `RankedBars`' `.rank-fill` grows in from
  `scaleX(0)` (`rank-grow` keyframe) — used by Requests, Analytics,
  Leaderboard, Skill Graph, Effort Drilldown, Stream Split.
- **Interaction:** `.card`/`.stat` lift on hover (`translateY(-2px)` +
  `--shadow-lift`); table rows, nav pills, and sidebar links transition
  smoothly instead of snapping.
- **First screen:** the login card arrives (`login-in`, translateY+scale)
  over a soft two-tone brand-hued radial glow instead of a flat plane.
- Every addition sits inside (or alongside an existing)
  `@media (prefers-reduced-motion: no-preference)` guard; nothing new
  animates when the visitor has asked for less motion, matching the
  existing app convention (`.spin`, `.skeleton` shimmer).

## Depth

- `.card`, `.stat`, `.table-scroll` carry `--shadow-rest` at rest.
- `.sidebar` casts a soft rightward shadow instead of only a hairline
  border, so it reads as a raised plane beside the content rather than a
  bordered column of the same material.
- `.topbar` is now `position: sticky; top: 0` with a translucent,
  backdrop-blurred background — a functional glass (content passes behind
  it while scrolling long tables), not decorative.

## What was deliberately not touched

- Status pill colors/contrast, the ordinal/rating ramps, and the brand
  accent palette — pinned per `PRODUCT.md`'s Brand Commitments.
- Per-route bespoke markup: the redesign works through the shared
  primitives (`StatTile`, `.card`, `.grid`, `RankedBars`, `Donut`) that
  every one of the 19 routes already builds on, rather than editing each
  route file individually.
- `useCountUp` (already existed, used only in Content Health) was not
  propagated to other routes' `StatTile` call sites — real value, but a
  40+ call-site mechanical change; flagged as a fast-follow rather than
  bundled into this pass.
- A pre-existing `border-top` accent on `.qt-tile` / `.stat-accent` (a
  hard-edged accent border on a rounded card) and a pre-existing bounce
  easing on `.field-callout`'s pop-in were flagged by the mechanical
  detector; the callout easing was swapped to `var(--ease-out)` since it
  was one line, the qt-tile border was left as-is since it's a
  widely-reused pre-existing convention, not part of this pass's diff.

## Unverified

No screenshot pass was run against the signed-in app: this is an
internal tool with no signed-out view, and stack it locally requires
Supabase Postgres + Google OAuth credentials this session did not have
running. Verified instead via `npm run build`, `npm run check`
(contrast + date logic), and the bundled Impeccable slop detector over
every changed file. **A real in-browser check (light + dark, desktop +
narrow) is the recommended next step before calling this shipped.**
