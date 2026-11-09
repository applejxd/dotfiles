// freezone.ts / gitrun.ts の試験用の実行器。標準入力の JSON を読み、結果を JSON で出す。
//
//   {"cwd": "...", "protected": [...]?, "env": {...}?, "timeoutMs": 1?}                    → classifyFreeZone
//   {"fn": "git", "args": [...], "cwd": "...", "env": {...}?, "timeoutMs": 1?}             → gitSync
//   {"fn": "preview", "cwd": "...", "protected": [...], "target": "develop"}               → {blocked: 理由 | null} (raw finish のプレビューを止めるか)
//   {"fn": "seq", "cwd": "...", "steps": [{"classify": true}, {"write": [パス, 本文]}, {"git": [...]}]}
//       → 順に実行して、classify の結果の配列を返す (git は cwd を変えずに実行。同じプロセスでの判定の変化を見る)
//
// env を渡すと process.env を置き換える (PATH を空にする試験用)。
// see docs/change/closed/0053-worktree-integration-gate.md
import { execFileSync } from "node:child_process";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
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
} else if (req.fn === "preview") {
	const { previewBlocked } = await import(harness("freezone.ts"));
	result = { blocked: previewBlocked(req.cwd, req.protected, req.target) };
} else if (req.fn === "seq") {
	const { classifyFreeZone } = await import(harness("freezone.ts"));
	result = [];
	for (const s of req.steps) {
		if (s.classify) result.push(classifyFreeZone(req.cwd, undefined, opts));
		else if (s.write) {
			mkdirSync(dirname(s.write[0]), { recursive: true });
			writeFileSync(s.write[0], s.write[1]);
		} else if (s.git) {
			execFileSync("git", ["-c", "user.name=t", "-c", "user.email=t@example.com", "-c", "commit.gpgsign=false", ...s.git], { stdio: "ignore" });
		}
	}
} else {
	const { classifyFreeZone } = await import(harness("freezone.ts"));
	result = req.protected ? classifyFreeZone(req.cwd, req.protected, opts) : classifyFreeZone(req.cwd, undefined, opts);
}
process.stdout.write(JSON.stringify(result));
