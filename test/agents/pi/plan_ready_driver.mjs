// 計画モード (plan 拡張) の isPlanReady に、標準入力の JSON 配列 (応答の文字列) を渡し、結果 (真偽) の配列を JSON で出す。
// 照合は test_pi_plan_ready.py。
//
//   echo '["...", "..."]' | node test/agents/pi/plan_ready_driver.mjs
import { readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "..", "..", "..");
const { isPlanReady } = await import(pathToFileURL(join(ROOT, "home", "dot_pi", "agent", "extensions", "plan", "index.ts")).href);

const cases = JSON.parse(readFileSync(0, "utf-8"));
console.log(JSON.stringify(cases.map((text) => isPlanReady(text))));
