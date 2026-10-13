// 判定器 (TS 版) と正解データ (Python 版の判定結果) の差分試験。
//
//   node test/agents/pi/judge_golden.mjs            # bash 以外 (移植済みの範囲) が全件一致すること
//   node test/agents/pi/judge_golden.mjs --bash     # bash も含めて全件一致すること (移植の完了条件)
//   node test/agents/pi/judge_golden.mjs --verbose  # 食い違いを 10 件ずつ出す
//
// 正解データは scripts/agents/export_decide_golden.py が書き出す (規則や判定器を変えたら書き出し直す)。
// パスは ${ROOT} / ${HOME} の記号で保存してあり、ここで自分の場所に展開する。
// see docs/spec/pi-decide.md
import { readFileSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "..", "..", "..");
const GOLDEN = resolve(ROOT, "test", "agents", "golden");
const HOME = homedir();

const JUDGE = resolve(ROOT, "home", "dot_config", "pi", "harness", "judge");
const { decide, setBashDecider } = await import(pathToFileURL(resolve(JUDGE, "decide.ts")).href);
const { makeBashDecider } = await import(pathToFileURL(resolve(JUDGE, "bash.ts")).href);
setBashDecider(makeBashDecider(JSON.parse(readFileSync(resolve(GOLDEN, "tables.json"), "utf8"))));

const args = new Set(process.argv.slice(2));
const requireBash = args.has("--bash");
const verbose = args.has("--verbose");

const common = JSON.parse(readFileSync(resolve(GOLDEN, "common.json"), "utf8"));
const lines = readFileSync(resolve(GOLDEN, "decide_golden.jsonl"), "utf8").split("\n").filter(Boolean);

const expand = (v) =>
	typeof v === "string"
		? v.replaceAll("${ROOT}", ROOT).replaceAll("${HOME}", HOME)
		: Array.isArray(v)
			? v.map(expand)
			: v && typeof v === "object"
				? Object.fromEntries(Object.entries(v).map(([k, x]) => [k, expand(x)]))
				: v;
const tokenize = (v) =>
	typeof v === "string"
		? v.replaceAll(ROOT, "${ROOT}").replaceAll(HOME, "${HOME}")
		: Array.isArray(v)
			? v.map(tokenize)
			: v && typeof v === "object"
				? Object.fromEntries(Object.entries(v).map(([k, x]) => [k, tokenize(x)]))
				: v;
const stable = (v) =>
	JSON.stringify(v, (_k, x) =>
		x && typeof x === "object" && !Array.isArray(x)
			? Object.fromEntries(Object.entries(x).sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0)))
			: x,
	);

const category = (request) => {
	if (!request || typeof request !== "object" || Array.isArray(request) || typeof request.tool !== "string") return "invalid";
	if (request.tool === "bash") return typeof request.input?.command === "string" ? "bash" : "invalid";
	if (["read", "grep", "find", "ls", "edit", "write"].includes(request.tool)) return "file";
	return "other";
};

const stats = {};
const failures = {};
for (const line of lines) {
	const { request, response: expected } = JSON.parse(line);
	const cat = category(request);
	stats[cat] ??= { pass: 0, fail: 0 };
	const got = tokenize(decide(expand(request), common));
	if (stable(got) === stable(expected)) {
		stats[cat].pass += 1;
	} else {
		stats[cat].fail += 1;
		(failures[cat] ??= []).push({ request, expected, got });
	}
}

let failed = false;
for (const [cat, { pass, fail }] of Object.entries(stats).sort()) {
	const gate = cat !== "bash" || requireBash;
	if (fail > 0 && gate) failed = true;
	const note = cat === "bash" && !requireBash ? "  (未移植。--bash で必須にする)" : "";
	console.log(`${cat.padEnd(8)} 一致 ${String(pass).padStart(5)} / 食い違い ${String(fail).padStart(5)}${note}`);
}
if (verbose || failed) {
	for (const [cat, list] of Object.entries(failures)) {
		if (cat === "bash" && !requireBash && !verbose) continue;
		console.log(`\n--- ${cat} の食い違い (先頭 ${Math.min(10, list.length)} / ${list.length} 件)`);
		for (const f of list.slice(0, 10)) {
			console.log(JSON.stringify({ request: f.request, expected: f.expected, got: f.got }));
		}
	}
}
process.exit(failed ? 1 : 0);
