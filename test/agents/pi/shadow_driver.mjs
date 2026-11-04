// judge/shadow.ts (観測) の試験用の入口。
//
//   node --experimental-strip-types test/agents/pi/shadow_driver.mjs <cases.json>
//
// ケース (JSON の配列。結果も同じ順の JSON 配列):
//   { op: "record", input }                               shadowRecord(input) をそのまま
//   { op: "record", cmd, response?, mode?, role?, tool? } analyze(cmd) の結果で shadowRecord を作る
//   { op: "append", file, record?, maxBytes?, n? }        appendShadow を n 回 (結果: 書けた回数, 最終サイズ)
//   { op: "observe", dir, cmds, env?, tool?, analyze?, session?, response?, budgetMs? }
//                                                         createShadow で observe を cmds の順に呼ぶ。analyze: real | throw | slow | slow-first
//   { op: "invariance", dir }                             baseline と同じ入力集合で、観測の有効/無効の応答が一致すること
//
// see docs/spec/guard/pi-decide.md#shadow観測
import { existsSync, readFileSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "..", "..", "..");
const JUDGE = resolve(ROOT, "home", "dot_config", "pi", "harness", "judge");
const load = (n) => import(pathToFileURL(resolve(JUDGE, n)).href);
const shadow = await load("shadow.ts");
const plan = await load("plan.ts");

const real = (cmd) => plan.analyze(cmd, { sshTargets: [] });
const jsonable = (p) => JSON.parse(JSON.stringify(p, (_k, v) => (v instanceof Set ? [...v] : v)));

const readLines = (path) =>
	readFileSync(path, "utf8")
		.split("\n")
		.filter(Boolean)
		.map((l) => JSON.parse(l));

const analyzers = (kind) => {
	let n = 0;
	if (kind === "throw") {
		return () => {
			throw new TypeError("boom");
		};
	}
	if (kind === "slow" || kind === "slow-first") {
		// 実時間で待つ (同期)。slow は毎回遅い。slow-first は 1 回目だけ速く、2 回目から遅い
		return (cmd) => {
			n++;
			if (kind === "slow" || n >= 2) {
				const end = Date.now() + 260;
				while (Date.now() < end);
			}
			return real(cmd);
		};
	}
	return real;
};

const run = async (c) => {
	if (c.op === "record") {
		if (c.input) return shadow.shadowRecord(c.input);
		return shadow.shadowRecord({
			role: c.role ?? "worker",
			mode: c.mode ?? "ask",
			tool: c.tool ?? "bash",
			cmd: c.cmd,
			response: c.response ?? { decision: "allow", source: "rule" },
			plan: real(c.cmd),
			ms: 1,
		});
	}
	if (c.op === "append") {
		let ok = 0;
		const rec =
			c.record ?? shadow.shadowRecord({ role: "r", mode: "ask", tool: "bash", cmd: "git log", response: { decision: "allow" }, ms: 1 });
		for (let i = 0; i < (c.n ?? 1); i++) if (shadow.appendShadow(c.file, rec, c.maxBytes)) ok++;
		return { ok, size: existsSync(c.file) ? readFileSync(c.file).length : 0 };
	}
	if (c.op === "observe") {
		const s = shadow.createShadow({
			env: c.env ?? {},
			role: () => "worker",
			mode: () => "ask",
			analyze: analyzers(c.analyze ?? "real"),
			budgetMs: c.budgetMs,
		});
		const resp = Object.freeze(c.response ?? { decision: "allow", source: "rule" });
		let threw = false;
		for (const cmd of c.cmds) {
			try {
				s.observe(c.tool ?? "bash", cmd, resp, c.dir, c.session ?? "s1");
			} catch {
				threw = true;
			}
		}
		const file = shadow.shadowPath(c.dir, c.session ?? "s1");
		return { lines: existsSync(file) ? readLines(file) : [], tripped: s.tripped, threw, resp };
	}
	if (c.op === "invariance") return invariance(c.dir);
	throw new Error(`op 不明: ${c.op}`);
};

async function invariance(dir) {
	const base = await import(pathToFileURL(resolve(HERE, "judge_baseline.mjs")).href);
	const { decide } = await load("decide.ts");
	const HOME = homedir();
	const expand = (v) =>
		typeof v === "string"
			? v.replaceAll("${ROOT}", ROOT).replaceAll("${HOME}", HOME)
			: Array.isArray(v)
				? v.map(expand)
				: v && typeof v === "object"
					? Object.fromEntries(Object.entries(v).map(([k, x]) => [k, expand(x)]))
					: v;
	const reqs = [...readLines(resolve(base.GOLDEN, "decide_golden.jsonl")).map((e) => e.request), ...base.truthRequests()];
	const stable = (r) => JSON.stringify(r, Object.keys(r).sort());
	const off = shadow.createShadow({ env: { PI_SHADOW: "0" }, role: () => "r", mode: () => "ask" });
	const on = shadow.createShadow({ env: {}, role: () => "r", mode: () => "ask", budgetMs: 1e9 });
	let diffs = 0;
	let bash = 0;
	const cmds = [];
	for (const req of reqs) {
		const r = expand(req);
		const a = decide(r, base.common);
		const sa = stable(a);
		// 観測へ渡す応答は凍結する (観測が書き換えれば例外か不一致になる)
		off.observe(r?.tool, r?.input?.command, Object.freeze({ ...a }), dir, "off");
		const b = decide(r, base.common);
		const resp = Object.freeze({ ...b });
		on.observe(r?.tool, r?.input?.command, resp, dir, "on");
		if (sa !== stable(resp) || sa !== stable(b)) diffs++;
		if (r?.tool === "bash" && typeof r.input?.command === "string") {
			bash++;
			cmds.push(r.input.command);
		}
	}
	const onFile = shadow.shadowPath(dir, "on");
	const text = existsSync(onFile) ? readFileSync(onFile, "utf8") : "";
	const leaks = cmds.filter((c) => c.length > 12 && text.includes(JSON.stringify(c).slice(1, -1))).length;
	return {
		total: reqs.length,
		bash,
		diffs,
		onLines: text.split("\n").filter(Boolean).length,
		offExists: existsSync(shadow.shadowPath(dir, "off")),
		leaks,
	};
}

const cases = JSON.parse(readFileSync(process.argv[2], "utf8"));
const out = [];
for (const c of cases) out.push(jsonable(await run(c)));
console.log(JSON.stringify(out));
