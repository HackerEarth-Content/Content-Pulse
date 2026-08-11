#!/usr/bin/env node
/**
 * Checks the dd/mm/yyyy parsing and formatting in src/format.ts.
 *
 *     node scripts/check-dates.mjs
 *
 * There is no test runner in this project and these two functions did not
 * justify adding one, so the check transpiles the real module with the
 * TypeScript that is already installed and asserts against it. Importing the
 * actual source matters: a copy of the logic here would drift from the copy
 * the app runs, which is the failure mode this is meant to prevent.
 */

import { execFileSync } from "node:child_process";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const out = mkdtempSync(join(tmpdir(), "contentops-dates-"));

try {
  execFileSync(
    "npx",
    ["tsc", join(root, "src/format.ts"), "--outDir", out,
     "--module", "esnext", "--target", "es2022", "--skipLibCheck"],
    { stdio: "pipe", cwd: root }
  );
} catch (e) {
  console.error("could not transpile src/format.ts:\n" + (e.stdout ?? e.message));
  process.exit(1);
}

// tsc emits `.js`, which Node reads as CommonJS unless the containing package
// says otherwise — and the emitted file uses ESM `export`.
writeFileSync(join(out, "package.json"), '{"type":"module"}');

const { dmy, fromDmy, commitDate } = await import(pathToFileURL(join(out, "format.js")).href);

let failures = 0;
const eq = (what, got, want) => {
  const ok = got === want;
  if (!ok) failures++;
  console.log(`  ${ok ? "ok  " : "FAIL"} ${what.padEnd(46)} ${JSON.stringify(got)}`
    + (ok ? "" : ` (expected ${JSON.stringify(want)})`));
};

console.log("\nformatting — ISO in, dd/mm/yyyy out");
eq("a plain date", dmy("2026-08-10"), "10/08/2026");
eq("single-digit day keeps its zero", dmy("2026-08-01"), "01/08/2026");
eq("a datetime is truncated to its date", dmy("2026-08-10T14:30:00"), "10/08/2026");
// The whole reason this is string surgery rather than `new Date(iso)`: that
// parses bare ISO as UTC midnight, which renders as the previous day for
// anyone west of Greenwich.
eq("no timezone shift on the 1st", dmy("2026-01-01"), "01/01/2026");
eq("null renders as a dash", dmy(null), "—");
eq("empty renders as a dash", dmy(""), "—");

console.log("\nparsing — dd/mm/yyyy in, ISO out");
eq("a plain date", fromDmy("10/08/2026"), "2026-08-10");
eq("single digits are padded", fromDmy("1/8/2026"), "2026-08-01");
eq("dots accepted", fromDmy("10.08.2026"), "2026-08-10");
eq("dashes accepted", fromDmy("10-08-2026"), "2026-08-10");
eq("surrounding space ignored", fromDmy("  10/08/2026 "), "2026-08-10");
eq("leap day in a leap year", fromDmy("29/02/2028"), "2028-02-29");

console.log("\nparsing — rejects rather than guessing");
// Date would roll 31/02 over to 3 March. A typo must not become a silent
// wrong answer four weeks out.
eq("31st of February", fromDmy("31/02/2026"), null);
eq("29th of February in a common year", fromDmy("29/02/2026"), null);
eq("month 13", fromDmy("10/13/2026"), null);
eq("day 0", fromDmy("00/08/2026"), null);
eq("two-digit year", fromDmy("10/08/26"), null);
eq("ISO handed in by mistake", fromDmy("2026-08-10"), null);
eq("not a date at all", fromDmy("hello"), null);
eq("empty", fromDmy(""), null);

// `commit` runs on blur, so it runs on every click away from the field — the
// calendar button, a tab, anywhere on the page. Emitting when nothing changed
// made the period picker rewrite the URL and drop its selected preset on a
// click that changed nothing. `changed` is the flag that stops that.
console.log("\ncommit — only reports a change when there is one");
const commit = (raw, current, min, max) => commitDate(raw, current, min, max);
eq("same date retyped is not a change",
  commit("10/08/2026", "2026-08-10").changed, false);
eq("same date, sloppier spelling, still not a change",
  commit("1/8/2026", "2026-08-01").changed, false);
eq("a different date is a change",
  commit("11/08/2026", "2026-08-10").changed, true);
eq("...and carries the new value",
  commit("11/08/2026", "2026-08-10").iso, "2026-08-11");
eq("clearing an empty field is not a change",
  commit("", "").changed, false);
eq("clearing a filled field is a change",
  commit("", "2026-08-10").changed, true);
eq("blurring on a typo reports no change",
  commit("31/02/2026", "2026-08-10").changed, false);
eq("...and flags it invalid",
  commit("31/02/2026", "2026-08-10").invalid, true);
eq("...and keeps the existing value",
  commit("31/02/2026", "2026-08-10").iso, "2026-08-10");
eq("a date before min is refused",
  commit("01/01/2026", "2026-08-10", "2026-05-04").invalid, true);
eq("a date after max is refused",
  commit("01/01/2030", "2026-08-10", undefined, "2026-08-10").invalid, true);
eq("a date exactly on max is fine",
  commit("10/08/2026", "2026-01-01", undefined, "2026-08-10").changed, true);

console.log("\nround trip");
for (const iso of ["2026-01-01", "2026-08-10", "2028-02-29", "2025-12-31"]) {
  eq(`${iso} survives a round trip`, fromDmy(dmy(iso)), iso);
}

rmSync(out, { recursive: true, force: true });
console.log(failures === 0 ? "\nAll date checks passed.\n" : `\n${failures} failed.\n`);
process.exit(failures === 0 ? 0 : 1);
