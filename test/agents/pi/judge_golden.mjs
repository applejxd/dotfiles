// 判定器 (TS 版) と正解データ (Python 版の判定結果) の差分試験。
//
//   node test/agents/pi/judge_golden.mjs            # bash 以外 (移植済みの範囲) が全件一致すること
//   node test/agents/pi/judge_golden.mjs --bash     # bash も含めて全件一致すること (移植の完了条件)
//   node test/agents/pi/judge_golden.mjs --verbose  # 食い違いを 10 件ずつ出す
//
// 正解データは scripts/agents/export_decide_golden.py が書き出す (規則や判定器を変えたら書き出し直す)。
// パスは ${ROOT} / ${HOME} の記号で保存してあり、ここで自分の場所に展開する。
// see docs/spec/guard/pi-decide.md
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

// TS 版だけの後続の規則を、Python 版の正解と照合する (Python 版には確認表 [pi.confirm] と本文の形の deny が無い。標本は除かない)。
//  - mustConfirm の ask: Python は ask、あるいは bypass 要求の allow+bypassed。理由・source・check は確認表だけに載ると Python では default なので比べない
//    既定が deny の役割では、Python が default の deny (確認表にしか無いコマンド。例: chezmoi apply) でもよい (子は UI が無く、どちらも通らない)
//  - 本文を確認できない形の deny: Python はそのコマンドを ask / allow として扱う
//  - 既定が deny の役割 (explorer・reader・committer) で、[bash] ask を deny にしたもの: Python は ask (bypass なら allow)。役割・bash・元の理由・source・check を比べる
//  - 同じ役割で、元に戻せないローカルの git 操作 ([pi.confirm] local_git) を deny にしたもの: 役割と bash だけを比べる
const BLIND_PREFIX = "本文を確認できない形";
const DENY_DEFAULT_ROLES = new Set(["explorer", "reader", "committer"]);
const DENY_DEFAULT_SUFFIX = "\nこの役割は既定が deny なので、承認で通さない (bypass でも通さない)";
const LOCAL_GIT_DENY_SUFFIX = "。この役割は shell で元に戻せない操作をしない";
const askLike = (r) => r?.decision === "ask" || (r?.decision === "allow" && r?.bypassed === true);
const denyDefaultRoleBash = (request) => request?.tool === "bash" && DENY_DEFAULT_ROLES.has(request?.role);
const sameAsExpected = (got, expected, request) => {
	if (stable(got) === stable(expected)) return true;
	if (got?.decision === "ask" && got.mustConfirm === true) {
		if (askLike(expected)) return true;
		return denyDefaultRoleBash(request) && expected?.decision === "deny" && expected?.source === "default";
	}
	if (got?.decision === "deny" && typeof got.reason === "string" && got.reason.startsWith(BLIND_PREFIX)) {
		return expected?.decision === "ask" || expected?.decision === "allow";
	}
	if (got?.decision === "deny" && typeof got.reason === "string" && denyDefaultRoleBash(request)) {
		if (got.reason.endsWith(LOCAL_GIT_DENY_SUFFIX)) return askLike(expected);
		if (got.reason.endsWith(DENY_DEFAULT_SUFFIX)) {
			return (
				askLike(expected) &&
				got.reason === `${expected.reason}${DENY_DEFAULT_SUFFIX}` &&
				got.source === expected.source &&
				got.check === expected.check
			);
		}
	}
	return false;
};

const stats = {};
const failures = {};
for (const line of lines) {
	const { request, response: expected } = JSON.parse(line);
	const cat = category(request);
	stats[cat] ??= { pass: 0, fail: 0 };
	const got = tokenize(decide(expand(request), common));
	if (sameAsExpected(got, expected, request)) {
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
