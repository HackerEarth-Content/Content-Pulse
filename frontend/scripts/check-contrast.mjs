#!/usr/bin/env node
/**
 * Contrast check for the theme tokens.
 *
 *     node scripts/check-contrast.mjs
 *
 * Reads the real values out of src/theme.css and checks every text/background
 * pair the UI actually renders, in both themes. Exits non-zero on a failure, so
 * it works as a pre-commit or CI step.
 *
 * This exists because eyeballing a palette does not catch the tight pairs. The
 * status chips shipped for months setting their label in the raw status hue on
 * a 12% tint of that same hue — amber came out at 1.70:1 against a 4.5
 * requirement, and nobody noticed because it looked fine at a glance.
 */

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const css = readFileSync(join(root, "src/theme.css"), "utf8");

const AA = 4.5; // normal-size text; every label we check is under 18px

const hex = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16) / 255);
const lin = (c) => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
const lum = (h) => {
  const [r, g, b] = hex(h).map(lin);
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
};
const ratio = (a, b) => {
  const [hi, lo] = [lum(a), lum(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
};
const byte = (v) => Math.round(Math.max(0, Math.min(255, v * 255))).toString(16).padStart(2, "0");
/** `color-mix(in srgb, c pct%, bg)` — how the chips build their backgrounds. */
const mix = (c, bg, pct) => {
  const a = hex(c);
  const b = hex(bg);
  return "#" + [0, 1, 2].map((i) => byte(a[i] * pct + b[i] * (1 - pct))).join("");
};

/** Pull a token block out of theme.css by its selector. */
function block(selector) {
  const start = css.indexOf(selector);
  if (start < 0) throw new Error(`no such selector in theme.css: ${selector}`);
  const open = css.indexOf("{", start);
  const end = css.indexOf("}", open);
  const out = {};
  for (const [, k, v] of css.slice(open, end).matchAll(/(--[\w-]+):\s*(#[0-9a-fA-F]{6})/g)) {
    out[k] = v;
  }
  return out;
}

// `:root` is the light theme; the explicit dark block carries the dark values
// and falls back to :root for anything it doesn't override.
const light = block(":root {");
const dark = { ...light, ...block(':root[data-theme="dark"]') };

let failures = 0;
const check = (theme, what, fg, bg, need = AA) => {
  const r = ratio(fg, bg);
  const pass = r >= need;
  if (!pass) failures++;
  console.log(
    `  ${pass ? "ok  " : "FAIL"} ${theme.padEnd(5)} ${what.padEnd(34)} ` +
      `${fg} on ${bg}  ${r.toFixed(2)}:1`
  );
};

for (const [name, t] of [["light", light], ["dark", dark]]) {
  console.log(`\n${name}`);
  // Body and secondary text on every surface it can land on.
  for (const surface of ["--plane", "--surface", "--surface-2", "--surface-3"]) {
    check(name, `ink on ${surface.slice(2)}`, t["--ink"], t[surface]);
    check(name, `ink-2 on ${surface.slice(2)}`, t["--ink-2"], t[surface]);
    check(name, `ink-3 on ${surface.slice(2)}`, t["--ink-3"], t[surface]);
  }
  // Status chips: label in `-ink`, background a 12% tint of the raw hue.
  for (const status of ["good", "warning", "serious", "critical", "neutral"]) {
    const hue = t[`--status-${status}`];
    const ink = t[`--status-${status}-ink`];
    if (!hue || !ink) {
      console.log(`  FAIL ${name.padEnd(5)} status ${status}: missing token`);
      failures++;
      continue;
    }
    check(name, `status ${status} chip`, ink, mix(hue, t["--surface"], 0.12));
  }
}

console.log(
  failures === 0
    ? "\nAll pairs clear WCAG AA (4.5:1).\n"
    : `\n${failures} pair(s) below 4.5:1 — fix the token, do not lower the bar.\n`
);
process.exit(failures === 0 ? 0 : 1);
