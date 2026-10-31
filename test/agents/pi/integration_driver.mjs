// 試験用。標準入力の JSON ({ cases: [{ command, protected? }] }) を classifyIntegration に通し、結果の配列を標準出力へ出す。
//   node test/agents/pi/integration_driver.mjs < cases.json
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "..", "..", "..");
const JUDGE = resolve(ROOT, "home", "dot_config", "pi", "harness", "judge");
const { classifyIntegration } = await import(pathToFileURL(resolve(JUDGE, "gitintegration.ts")).href);
const DEFAULT_PROTECTED = ["develop", "main", "master"];
const { cases } = JSON.parse(readFileSync(0, "utf8"));
process.stdout.write(JSON.stringify(cases.map((c) => classifyIntegration(c.command, c.protected ?? DEFAULT_PROTECTED))));
