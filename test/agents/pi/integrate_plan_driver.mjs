// integrate-plan.ts の試験用の実行器。標準入力の JSON (IntegrateInput) を読み、結果を JSON で出す。
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "..", "..", "..");
const href = pathToFileURL(resolve(ROOT, "home", "dot_config", "pi", "harness", "integrate-plan.ts")).href;
const { computeIntegrationPlan } = await import(href);
const req = JSON.parse(readFileSync(0, "utf8"));
process.stdout.write(JSON.stringify(computeIntegrationPlan(req)));
