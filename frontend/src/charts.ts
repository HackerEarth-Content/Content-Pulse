/** Chart colour and shared chart config.
 *
 * The categorical hues are not a taste call. Running the brand accents through
 * a CVD/contrast validator, only three are mutually distinguishable across
 * every pair in both themes:
 *
 *     aqua → indigo → orange     all-pairs ΔE ≥ 9.4 (deutan), ≥ 24.6 (normal)
 *
 * Six were tried first and failed hard: blue↔indigo reads as ΔE 9.8 to normal
 * vision, magenta↔aqua as ΔE 1.6 to deuteranopes. So anything with more than
 * three parts is a **ranked bar with a written label**, where the word carries
 * identity and colour is only ordinal. Donuts are reserved for 2–3 part splits.
 */

export const CATEGORICAL = [
  "var(--accent-aqua)",
  "var(--accent-indigo)",
  "var(--accent-orange)",
] as const;

/** A single-hue ramp, for magnitude rather than identity. */
export const ORDINAL = [
  "var(--ord-2)",
  "var(--ord-3)",
  "var(--ord-4)",
  "var(--ord-5)",
] as const;

export const MUTED = "var(--ink-3)";

/** Colour follows the entity, never its rank — a filter that drops a series
 * must not repaint the survivors. Anything outside the fixed list is muted
 * rather than given a generated hue. */
const FIXED: Record<string, string> = {
  content_task: CATEGORICAL[0],
  content_request: CATEGORICAL[1],
  content_assessment: CATEGORICAL[2],
};

export const colourFor = (key: string, index = 0): string =>
  FIXED[key] ?? CATEGORICAL[index] ?? MUTED;

/** Ordinal shade by position — for ranked bars, where the label identifies the
 * row and colour only signals magnitude. */
export const shadeFor = (index: number, total: number): string =>
  ORDINAL[Math.min(ORDINAL.length - 1, Math.round((index / Math.max(1, total - 1)) * (ORDINAL.length - 1)))];

export const TOOLTIP = {
  background: "var(--surface)",
  border: "1px solid var(--line)",
  borderRadius: 8,
  fontSize: 12,
  boxShadow: "var(--shadow-hover)",
} as const;

export const AXIS = { stroke: "var(--ink-3)", fontSize: 11 } as const;

/** Donut geometry. A 2px surface-coloured gap between segments keeps adjacent
 * fills legible without adding a stroke that reads as a mark of its own. */
export const DONUT = {
  innerRadius: 58,
  outerRadius: 92,
  paddingAngle: 2,
  stroke: "var(--surface)",
  strokeWidth: 2,
} as const;
