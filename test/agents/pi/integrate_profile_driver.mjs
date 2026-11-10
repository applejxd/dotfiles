// integrateprofile.ts / integrate-profile-load.ts の試験用の実行器。標準入力の JSON を読み、結果を JSON で出す。
//
//   {"fn": "effective", "defaults": {...}, "text": "..." | null}                            → effectiveProfile
//   {"fn": "load", "cwd": "...", "defaults": {...}}                                        → loadProfile
//   {"fn": "fake", "cwd": "...", "defaults": {...}, "outputs": {"ls-tree": {"ok": true, "stdout": "..."}, ...}} → git を注入した loadProfile
//   {"fn": "seq", "cwd": "...", "defaults": {...}, "steps": [{"load": true}, {"git": [...]}, ...]}
//       → 順に実行 (load は loadProfile。git は cwd で git を実行して設定を変える)。各 load の結果と、
//         注入した git の呼び出し一覧 (サブコマンドごとの回数) を返す。
//
// see docs/change/closed/0057-per-project-integrate.md
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "..", "..", "..");
const harness = (name) => pathToFileURL(resolve(ROOT, "home", "dot_config", "pi", "harness", name)).href;

const req = JSON.parse(readFileSync(0, "utf8"));
// ローダーは git のグローバルオプション (--no-replace-objects) をサブコマンドの前に付ける。先頭の "--" 始まりを飛ばしてサブコマンドを数える
const sub = (args) => args.find((a) => !a.startsWith("--"));
let result;
if (req.fn === "effective") {
	const { effectiveProfile } = await import(harness("judge/integrateprofile.ts"));
	result = effectiveProfile(req.defaults, req.text);
} else if (req.fn === "load") {
	const { loadProfile } = await import(harness("integrate-profile-load.ts"));
	result = loadProfile(req.cwd, req.defaults);
} else if (req.fn === "seq") {
	const { loadProfile } = await import(harness("integrate-profile-load.ts"));
	const { gitSync } = await import(harness("gitrun.ts"));
	const calls = [];
	const git = (args, cwd) => {
		calls.push(sub(args));
		return gitSync(args, cwd, { timeoutMs: 5000 });
	};
	const loads = [];
	for (const step of req.steps) {
		if (step.load) {
			loads.push(loadProfile(req.cwd, step.defaults ?? req.defaults, { git }));
		} else if (step.git) {
			execFileSync("git", ["-c", "user.name=t", "-c", "user.email=t@example.com", "-c", "commit.gpgsign=false", ...step.git], {
				cwd: req.cwd,
				stdio: "ignore",
			});
		}
	}
	result = { loads, calls };
} else if (req.fn === "fake") {
	// git を注入して、ls-tree / cat-file の出力を固定する (サブコマンドごと)
	const { loadProfile } = await import(harness("integrate-profile-load.ts"));
	const seen = [];
	const git = (args) => (seen.push(args), req.outputs[sub(args)] ?? { ok: false, reason: "no output" });
	const loaded = loadProfile(req.cwd, req.defaults, { git });
	// 渡された git 引数を見たいときは record
	result = req.record ? { loaded, seen } : loaded;
}
process.stdout.write(JSON.stringify(result));
