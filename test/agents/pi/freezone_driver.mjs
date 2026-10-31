// freezone.ts / gitrun.ts の試験用の実行器。標準入力の JSON を読み、結果を JSON で出す。
//
//   {"cwd": "...", "protected": [...]?, "env": {...}?, "timeoutMs": 1?}                    → classifyFreeZone
//   {"fn": "git", "args": [...], "cwd": "...", "env": {...}?, "timeoutMs": 1?}             → gitSync
//
// env を渡すと process.env を置き換える (PATH を空にする試験用)。
// see docs/change/0053-worktree-integration-gate.md
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "..", "..", "..");
const harness = (name) => pathToFileURL(resolve(ROOT, "home", "dot_config", "pi", "harness", name)).href;

const req = JSON.parse(readFileSync(0, "utf8"));
const opts = { env: req.env, timeoutMs: req.timeoutMs };
let result;
if (req.fn === "git") {
	const { gitSync } = await import(harness("gitrun.ts"));
	result = gitSync(req.args, req.cwd, opts);
} else {
	const { classifyFreeZone } = await import(harness("freezone.ts"));
	result = req.protected ? classifyFreeZone(req.cwd, req.protected, opts) : classifyFreeZone(req.cwd, undefined, opts);
}
process.stdout.write(JSON.stringify(result));
