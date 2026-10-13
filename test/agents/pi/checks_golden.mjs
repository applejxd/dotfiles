// bashrules (bash 検査の各関数) の TS 版と、Python 版の出力 (正解データ) の差分試験。
//
//   node test/agents/pi/checks_golden.mjs            # 移植済みの関数が全件一致を必須にする
//   node test/agents/pi/checks_golden.mjs --verbose  # 食い違いを 10 件ずつ出す
//   node test/agents/pi/checks_golden.mjs --all      # 未移植の検査関数も食い違いに数える
//
// 正解データは scripts/agents/export_checks_golden.py が書き出す (checks_golden.jsonl / tables.json)。
// 検査関数は judge/checks.ts の CHECKS (名前 → 関数) に載せたものだけを試す。
// 1 コマンドごとに、判定と同じく文脈 (Ctx) を作り直す。
// see docs/spec/pi-decide.md#ts-版への移植
import { existsSync, readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "..", "..", "..");
const GOLDEN = resolve(ROOT, "test", "agents", "golden");
const JUDGE = resolve(ROOT, "home", "dot_config", "pi", "harness", "judge");

const load = (name) => import(pathToFileURL(resolve(JUDGE, name)).href);
const { newCtx } = await load("context.ts");
const shared = await load("shared.ts");
const { parse } = await load("shellparse.ts");
const checksModule = existsSync(resolve(JUDGE, "checks.ts")) ? await load("checks.ts") : { CHECKS: new Map() };
const CHECKS = checksModule.CHECKS;

const verbose = process.argv.includes("--verbose");
const all = process.argv.includes("--all");
const tables = JSON.parse(readFileSync(resolve(GOLDEN, "tables.json"), "utf8"));
const common = JSON.parse(readFileSync(resolve(GOLDEN, "common.json"), "utf8"));
const PLACEHOLDER = "${ROOT}";

const mask = (v) => {
	if (typeof v === "string") return v.replaceAll(ROOT, PLACEHOLDER);
	if (Array.isArray(v)) return v.map(mask);
	if (v && typeof v === "object") return Object.fromEntries(Object.entries(v).map(([k, x]) => [k, mask(x)]));
	return v;
};

/** キーを整列して JSON にする (Python 側は sort_keys で書いている)。 */
const canon = (v) =>
	JSON.stringify(v, (_k, x) =>
		x && typeof x === "object" && !Array.isArray(x)
			? Object.fromEntries(Object.entries(x).sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0)))
			: x,
	);

const commandJson = (c) => ({
	words: c.words.map((w) => [w.raw, w.value]),
	redirects: c.redirects.map((r) => [r.fd, r.op, r.target === null ? null : [r.target.raw, r.target.value]]),
});

/** 例外は型名まで揃えられない (Python と JS で違う) ので、「例外になった」ことだけを比べる。 */
const attempt = (fn) => {
	try {
		return { ok: fn() };
	} catch {
		return { error: "*" };
	}
};

const stats = {};
const failures = {};
const unported = new Set();
let ctx = null;

const lines = readFileSync(resolve(GOLDEN, "checks_golden.jsonl"), "utf8").split("\n").filter(Boolean);
for (const line of lines) {
	const e = JSON.parse(line);
	let key = e.fn;
	let got;
	if (e.fn === "heredoc") {
		ctx = newCtx(tables, common, ROOT);
		got = { out: shared.splitHeredocBody(ctx, e.arg), literal: [...ctx.literalHeredocBodies] };
		got = mask(got);
		var want = { out: e.out, literal: e.literal };
	} else if (e.fn === "expand_cd") {
		got = { out: shared.expandCdTargets(e.arg) };
		var want = { out: e.out };
	} else if (e.fn === "commands") {
		got = attempt(() => shared.commands(ctx, e.arg).map(commandJson));
		var want = e.error ? { error: "*" } : { ok: e.ok };
	} else if (e.fn === "write_targets") {
		got = attempt(() => shared.writeTargets(ctx, e.arg));
		var want = e.error ? { error: "*" } : { ok: e.ok };
	} else if (e.fn === "check") {
		key = `check:${e.name.split("@")[0]}`;
		const check = CHECKS.get(e.name.split("@")[0]);
		if (!check) {
			unported.add(e.name.split("@")[0]);
			if (!all) continue;
			got = { ok: null };
		} else {
			got = attempt(() => check(ctx, e.arg));
		}
		var want = e.error ? { error: "*" } : { ok: e.ok };
	} else {
		throw new Error(`未知の fn: ${e.fn}`);
	}
	stats[key] ??= { pass: 0, fail: 0 };
	if (canon(mask(got)) === canon(want)) {
		stats[key].pass++;
	} else {
		stats[key].fail++;
		(failures[key] ??= []).push({ arg: e.arg, want, got });
	}
}

let bad = 0;
for (const [key, s] of Object.entries(stats)) {
	console.log(`${key.padEnd(34)} 一致 ${String(s.pass).padStart(5)} / 食い違い ${String(s.fail).padStart(5)}`);
	bad += s.fail;
	if (verbose && failures[key]) {
		for (const f of failures[key].slice(0, 10)) {
			console.log("  ·", JSON.stringify(f.arg).slice(0, 160));
			console.log("    正解", JSON.stringify(f.want).slice(0, 200));
			console.log("    TS  ", JSON.stringify(f.got).slice(0, 200));
		}
	}
}
if (unported.size && !all) console.log(`未移植の検査関数 (${unported.size}): ${[...unported].sort().join(", ")}`);
console.log(bad === 0 ? "全件一致" : `食い違い ${bad} 件`);
process.exit(bad === 0 ? 0 : 1);
