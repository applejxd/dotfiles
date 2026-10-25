// 判定器の部品 (shlex・分割・正規化・照合) の TS 版と、Python 版の出力 (正解データ) の差分試験。
//
//   node test/agents/pi/policy_golden.mjs            # 全件一致を必須にする
//   node test/agents/pi/policy_golden.mjs --verbose  # 食い違いを 10 件ずつ出す
//
// 正解データは scripts/agents/export_policy_golden.py が書き出す。
// 判定の入口の試験 (judge_golden.mjs) と違い、食い違ったときにどの部品が原因かが分かる。
// see docs/spec/guard/pi-decide.md#ts-版への移植
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "..", "..", "..");
const GOLDEN = resolve(ROOT, "test", "agents", "golden");
const JUDGE = resolve(ROOT, "home", "dot_config", "pi", "harness", "judge");

const load = (name) => import(pathToFileURL(resolve(JUDGE, name)).href);
const { shlexSplit, ShlexError } = await load("pystr.ts");
const { normalize, splitCommandSegments, extractCommandSubstitutions, extractFunctionBodies, findMatch } =
	await load("normalize.ts");

const verbose = process.argv.includes("--verbose");
const common = JSON.parse(readFileSync(resolve(GOLDEN, "common.json"), "utf8"));
const lists = {
	deny: common.bash?.deny ?? [],
	ask: common.bash?.ask ?? [],
	allow: common.pi?.shell?.allow ?? [],
};

const run = {
	shlex: (e) => {
		try {
			return { tokens: shlexSplit(e.arg) };
		} catch (err) {
			if (err instanceof ShlexError) return { error: err.message };
			throw err;
		}
	},
	split: (e) => splitCommandSegments(e.arg),
	normalize: (e) => normalize(e.arg),
	subst: (e) => extractCommandSubstitutions(e.arg),
	funcs: (e) => extractFunctionBodies(e.arg),
	find_match: (e) => findMatch(e.arg, lists[e.list]),
};

const lines = readFileSync(resolve(GOLDEN, "policy_golden.jsonl"), "utf8").split("\n").filter(Boolean);
const stats = {};
const failures = {};
for (const line of lines) {
	const entry = JSON.parse(line);
	const key = entry.fn === "find_match" ? `find_match(${entry.list})` : entry.fn;
	stats[key] ??= { pass: 0, fail: 0 };
	let got;
	try {
		got = run[entry.fn](entry);
	} catch (err) {
		got = { exception: String(err) };
	}
	if (JSON.stringify(got) === JSON.stringify(entry.out)) {
		stats[key].pass += 1;
	} else {
		stats[key].fail += 1;
		(failures[key] ??= []).push({ arg: entry.arg, expected: entry.out, got });
	}
}

let failed = false;
for (const [key, { pass, fail }] of Object.entries(stats).sort()) {
	if (fail > 0) failed = true;
	console.log(`${key.padEnd(18)} 一致 ${String(pass).padStart(5)} / 食い違い ${String(fail).padStart(5)}`);
}
if (verbose || failed) {
	for (const [key, list] of Object.entries(failures)) {
		console.log(`\n--- ${key} の食い違い (先頭 ${Math.min(10, list.length)} / ${list.length} 件)`);
		for (const f of list.slice(0, 10)) console.log(JSON.stringify(f));
	}
}
process.exit(failed ? 1 : 0);
