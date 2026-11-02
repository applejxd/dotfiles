// integrate-exec.ts の試験用の実行器。標準入力の JSON ({plan, cleanup, approverCwd, abortAfterMs?, commitTimeoutMs?, ...}) を読み、結果を JSON で出す。
// 故障注入: stopUnconfirmed (停止確認が常に false)、unconfirmedFrom (n 回目の停止確認から false)、
// noSignal (シグナルを送らない)、graceMs / killMs (待ち時間の短縮)。
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "..", "..", "..");
const href = pathToFileURL(resolve(ROOT, "home", "dot_config", "pi", "harness", "integrate-exec.ts")).href;
const { executeIntegration, executeIntegrationOutcome } = await import(href);
const { validateResultBody } = await import(pathToFileURL(resolve(ROOT, "home", "dot_config", "pi", "harness", "pending-ops.ts")).href);
const req = JSON.parse(readFileSync(0, "utf8"));
const ac = new AbortController();
if (req.abortAfterMs) setTimeout(() => ac.abort(), req.abortAfterMs);
const input = { plan: req.plan, cleanup: req.cleanup ?? "none", approverCwd: req.approverCwd, signal: ac.signal };
if (req.protectedRefs) input.protectedRefs = req.protectedRefs;
if (req.commitTimeoutMs) input.commitTimeoutMs = req.commitTimeoutMs;
if (req.stopUnconfirmed) input.stopVerifier = () => false;
if (req.unconfirmedFrom) {
	let n = 0;
	input.stopVerifier = () => ++n < req.unconfirmedFrom;
}
if (req.noSignal) input.killSignal = () => {};
if (req.graceMs) input.graceMs = req.graceMs;
if (req.killMs) input.killMs = req.killMs;
// outcome: true なら { body, termination, valid } を出す (valid = validateResultBody の結果)
const res = req.outcome ? await executeIntegrationOutcome(input) : await executeIntegration(input);
if (req.outcome) res.valid = validateResultBody(res.body);
// 停止できなかった子が残っていても、ここで終わる
process.stdout.write(JSON.stringify(res), () => process.exit(0));
