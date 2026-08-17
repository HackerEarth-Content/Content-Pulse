# Design Reference: Quiet Enterprise Data Dashboard

Dense, data-heavy, but restrained — the opposite of flashy. Every technique below is what makes it feel "sleek" rather than "spreadsheet." Source: `frontend/src/theme.css` + `frontend/src/App.css`.

## Core tokens (swap colors, keep structure)

| Token | Role |
|---|---|
| `--plane` | page background (slightly tinted, not pure white/black) |
| `--surface` / `--surface-2` | card bg / recessed bg (inputs, table stripes, pills) |
| `--ink` / `--ink-2` / `--ink-3` | text hierarchy: primary, secondary, tertiary — 3 levels, no more |
| `--line` | all borders, one shade, never black |
| `--ring` / `--shadow` / `--shadow-hover` | focus ring + two-tier elevation |
| `--accent-*` (7 hues) | brand accents, themed separately per light/dark |
| `--status-*` (good/warning/serious/critical/neutral) | **fixed across themes, never recolored** — semantic meaning must stay stable |
| `--ord-1..5` | single-hue monotone ramp for ordinal/severity scales (not categorical) |
| `--radius` (12px) / `--radius-sm` (8px) | two radii total, used everywhere |

## The subtle techniques that make it sleek

1. **Dual dark-mode wiring** — both `@media (prefers-color-scheme: dark)` and an explicit `[data-theme="dark"]` override, so it respects OS setting but lets a UI toggle win. Copy this pattern exactly for any theme-aware rebuild.
2. **Status colors never shift with theme** — good/warning/critical stay semantically fixed while everything else re-themes. Prevents "wait, is orange bad now?" confusion.
3. **`color-mix(in srgb, var(--accent) X%, var(--surface))`** everywhere instead of hardcoded tint colors — one accent variable drives borders, backgrounds, hover states, chip fills, all derived by mix percentage. This is the single biggest "how did they make this so cohesive" trick.
4. **Two-tier shadow system** — resting `--shadow` (barely there, 2 layered blurs) vs `--shadow-hover` (slightly more) + `transform: translateY(-1px)` on hover. Motion is ~1px, never bouncy.
5. **Typography restraint** — one sans (Inter) for everything, one mono (JetBrains Mono) reserved *only* for numbers (`.value`, `.num`, table numeric cells) with `font-variant-numeric: tabular-nums`. This is why the numbers feel "engineered" rather than typed.
6. **Font sizes stay in a tight 10.5–22px band** — no heading ever gets big. Hierarchy is carried by weight (600–650) and letter-spacing (slightly negative on headings, slightly positive/uppercase on labels), not size jumps.
7. **Uppercase micro-labels** (`.section-title`, `th`, `.eyebrow`) at 10.5–11px with `letter-spacing: 0.05–0.09em` — the "quiet enterprise" signature. Labels whisper, values speak.
8. **Pill-shaped everything interactive** — segmented control (`.period-group`), filter chips (`.chip`), status dots — high border-radius (999px) reserved for things you click/toggle; cards/tiles stay at the boring 12px radius.
9. **`prefers-reduced-motion` gating** on every transition/animation block — sleekness never comes at the cost of accessibility.
10. **Skeleton shimmer** via a single gradient + `background-position` animation, not a spinner — loading states feel like "the content is already there, just fading in."
11. **Section rules, not boxes** — `.section-heading` uses a colored dot + label + a thin `flex:1` line rather than a full divider block, so sections feel grouped without adding visual weight.
12. **Sticky-column tables** with matching `left` offsets and an opaque (not transparent) `color-mix` background at the seam — prevents the classic "content bleeds through sticky column" bug when scrolling wide tables.
13. **Live/status dots get a soft halo** — `box-shadow: 0 0 0 3px color-mix(accent 20%, transparent)` — a glow ring instead of a hard outline, reads as "alive" without being loud.

## To reuse with different colors

Only touch the `--accent-*`, `--ord-*`, and the two `--plane`/`--surface` pairs (light+dark blocks) — everything else (spacing scale, radii, shadow depth, type scale, the `color-mix` calls) is structural and should stay as-is. That's what preserves the "sleek" feel across a palette swap.
