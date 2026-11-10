// `work` ツール (home/dot_config/pi/harness/work/tool.ts) の純関数の試験用 driver。標準入力の JSON を実行し、結果を JSON で標準出力へ出す。照合は test_work_tool.py。
//
//   {"cases":[{"setup":[{"type":..,"node":..,"data":{..},"source":..}, ...], "now":1000, "holder":"h", "steps":[<work の引数>, ...]}, ...]}
//        setup のイベントを畳んだ状態から、steps を順に handleWork へ渡す。各 step で返ったイベントを畳み、
//        入力 state が変わっていないか (before/after の直列化)・同じ入力で 2 回呼んで同じ結果か・不変条件の違反を返す
//   {"schema":true}   WORK_TOOL_SCHEMA を返す
// see docs/spec/work/tool.md
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "..", "..", "..");
const W = resolve(ROOT, "home", "dot_config", "pi", "harness", "work");
const load = (f) => import(pathToFileURL(resolve(W, f)).href);
const [tool, rd, inv] = await Promise.all(["tool.ts", "reduce.ts", "invariants.ts"].map(load));

const USER_ONLY = new Set(["plan.approved", "budget.adjusted", "goal.resumed"]);
const mkEvent = (e, seq) => {
	const source = e.source ?? (USER_ONLY.has(e.type) ? "user" : "system");
	return { ts: seq * 1000, seq, type: e.type, ...(e.node !== undefined ? { node: e.node } : {}), data: { ...(e.data ?? {}) }, source, ...(e.holder !== undefined ? { holder: e.holder } : {}) };
};
const ser = (s) => JSON.stringify(rd.serialize(s));

const input = JSON.parse(readFileSync(0, "utf8"));
const out = {};

if (input.schema) out.schema = tool.WORK_TOOL_SCHEMA;

if (input.cases) {
	out.cases = input.cases.map((c) => {
		let st = rd.emptyState();
		for (const e of c.setup ?? []) st = rd.reduce(st, mkEvent(e, st.seq + 1));
		const ctx = { now: c.now ?? 5000, holder: c.holder ?? "h1" };
		const steps = [];
		for (const args of c.steps) {
			const before = ser(st);
			const r1 = tool.handleWork(st, args, ctx);
			const r2 = tool.handleWork(st, args, ctx);
			const unchanged = ser(st) === before;
			const deterministic = JSON.stringify(r1) === JSON.stringify(r2);
			let applyError = null;
			const prev = st;
			if (r1.ok) {
				try {
					for (const e of r1.events) st = rd.reduce(st, { ...e, ts: ctx.now, seq: st.seq + 1 });
				} catch (e) {
					applyError = String(e.message);
				}
			}
			const violations = inv.check(st, prev).map((v) => `${v.inv}:${v.message}`);
			steps.push({
				result: r1,
				unchanged,
				deterministic,
				applyError,
				violations,
				nodes: Object.fromEntries([...st.nodes].map(([id, n]) => [id, { state: n.state, after: n.after, kind: n.kind, parent: n.parent, notes: n.notes.length, title: n.title }])),
				eventTypes: r1.events.map((e) => e.type),
			});
		}
		return { steps };
	});
}

process.stdout.write(JSON.stringify(out));
