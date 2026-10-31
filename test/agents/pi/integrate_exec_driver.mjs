// integrate-exec.ts の試験用の実行器。標準入力の JSON ({plan, cleanup, approverCwd, abortAfterMs?, commitTimeoutMs?}) を読み、結果を JSON で出す。
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "..", "..", "..");
const href = pathToFileURL(resolve(ROOT, "home", "dot_config", "pi", "harness", "integrate-exec.ts")).href;
const { executeIntegration } = await import(href);
const req = JSON.parse(readFileSync(0, "utf8"));
const ac = new AbortController();
if (req.abortAfterMs) setTimeout(() => ac.abort(), req.abortAfterMs);
const input = { plan: req.plan, cleanup: req.cleanup ?? "none", approverCwd: req.approverCwd, signal: ac.signal };
if (req.commitTimeoutMs) input.commitTimeoutMs = req.commitTimeoutMs;
process.stdout.write(JSON.stringify(await executeIntegration(input)));
