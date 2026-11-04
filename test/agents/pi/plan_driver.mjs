// judge/plan.ts (解析結果 Plan) の試験用の入口。ケースの JSON (配列) を読み、各ケースの結果を JSON の配列で標準出力へ出す。
//
//   node --experimental-strip-types test/agents/pi/plan_driver.mjs <cases.json>
//
// ケース: { cmd: string | null, ssh?: string[], vendor?: string, tables?: boolean, ast?: boolean, breakEval?: boolean }
//   - 既定: analyze(cmd, { sshTargets: ssh ?? [], vendorDir: vendor }) の結果 (Set は配列にして返す)
//   - ast: true: mvdan-sh の構文木の型名とフィールドの要約 (fixture 用)。構文エラーは { error }
//   - tables: true: golden/tables.json を legacy の heredoc 書換えに渡す
//
// see docs/spec/guard/pi-decide.md#解析結果-plan-と-literal-の定義表
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "..", "..", "..");
const JUDGE = resolve(ROOT, "home", "dot_config", "pi", "harness", "judge");
const plan = await import(pathToFileURL(resolve(JUDGE, "plan.ts")).href);
const syn = await import(pathToFileURL(resolve(JUDGE, "syntax.ts")).href);

/** 構文木のノードを { _t: 型名, フィールド… } に要約する (位置・関数は除く) */
function dump(n) {
	if (n === null || n === undefined) return null;
	if (typeof n !== "object") return n;
	if (Array.isArray(n) || typeof n.$length === "number") return syn.arr(n).map((x) => dump(x));
	if (typeof n.Pos !== "function") return null;
	const o = { _t: syn.typeOf(n) };
	for (const k of Reflect.ownKeys(n)) {
		if (typeof k !== "string" || k === "__internal_object__" || k === "$type" || k === "Pos" || k === "End") continue;
		const v = n[k];
		if (typeof v === "function" || v === null || v === undefined) continue;
		if (typeof v === "object") {
			const dv = dump(v);
			if (dv !== null && !(Array.isArray(dv) && dv.length === 0)) o[k] = dv;
		} else if (v !== "" && v !== false && v !== 0) o[k] = v;
		else if (v === 0 && k === "Op") o[k] = 0;
	}
	return o;
}

let tables;
try {
	tables = JSON.parse(readFileSync(resolve(ROOT, "test", "agents", "golden", "tables.json"), "utf8"));
} catch {
	tables = undefined;
}

const cases = JSON.parse(readFileSync(process.argv[2], "utf8"));
const out = cases.map((c) => {
	if (c.ast) {
		const p = syn.parseSource(c.cmd);
		return p.ok ? { tree: dump(p.src.file.Stmts) } : { error: p.why };
	}
	const opts = { sshTargets: c.ssh ?? [] };
	if (c.vendor) opts.vendorDir = c.vendor;
	if (c.tables) opts.tables = tables;
	// breakEval: new Function を壊して、mvdan-sh の評価の失敗 (sha256 は一致している) を再現する
	const F = globalThis.Function;
	if (c.breakEval) {
		globalThis.Function = function () {
			throw new Error("boom");
		};
	}
	try {
		const r = plan.analyze(c.cmd, opts);
		return r.ok ? { ...r, varsVisible: [...r.varsVisible].sort() } : r;
	} finally {
		globalThis.Function = F;
	}
});
console.log(JSON.stringify(out));
