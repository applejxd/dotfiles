// 調停の接着層 (home/dot_config/pi/harness/work/settle.ts) の試験用 driver。標準入力の JSON を実行し、結果を JSON で標準出力へ出す。照合は test_work_settle.py。
//
//   {"cases":[{"opts":{enabled,child},"twice":bool,"snapshot":{..},"event":{..},"ctx":{mode,pending,compacting},"fail":{"snapshot":bool,"journal":bool,"wake":bool}}]}
//       偽の pi に登録してハンドラを呼ぶ。{registered, handlers, result, calls, pi, direct} を返す。direct は arbiter.ts の直接呼び出し (別に組んだ事実)
//   {"effects":[Effect..]}   runEffects だけを呼び、exec の呼び出しを返す
// see docs/spec/work/settle.md
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "..", "..", "..");
const W = resolve(ROOT, "home", "dot_config", "pi", "harness", "work");
const st = await import(pathToFileURL(resolve(W, "settle.ts")).href);
const arb = await import(pathToFileURL(resolve(W, "arbiter.ts")).href);

const clone = (x) => JSON.parse(JSON.stringify(x));

const makeDeps = (c, calls) => ({
	snapshot: () => {
		if (c.fail?.snapshot) throw new Error("snapshot 失敗");
		return clone(c.snapshot);
	},
	exec: {
		wake: (p, o) => {
			calls.wake.push([p, o]);
			if (c.fail?.wake) throw new Error("wake 失敗");
		},
		notify: (k, t) => calls.notify.push([k, t]),
		checkpoint: (a) => calls.checkpoint.push(a),
	},
	runtime: c.noRuntime ? undefined : { submit: async (ev) => (calls.submit.push(ev), { ok: true, applied: [] }) },
	journal: c.noJournal
		? undefined
		: {
				emit: (t, d) => {
					calls.journal.push([t, d]);
					if (c.fail?.journal) throw new Error("journal 失敗");
				},
			},
});
const newCalls = () => ({ wake: [], notify: [], checkpoint: [], submit: [], journal: [] });

async function runCase(c) {
	const calls = newCalls();
	const piCalls = { send: 0, trigger: 0 };
	const handlers = [];
	const pi = {
		on: (n, h) => handlers.push([n, h]),
		sendUserMessage: () => piCalls.send++,
		triggerTurn: () => piCalls.trigger++,
	};
	const deps = makeDeps(c, calls);
	const r1 = st.registerSettle(pi, deps, c.opts);
	const r2 = c.twice ? st.registerSettle(pi, deps, c.opts) : null;
	let result = null;
	if (handlers.length > 0) {
		const ctx = {
			mode: c.ctx?.mode,
			hasPendingMessages: () => c.ctx?.pending === true,
			isCompacting: () => c.ctx?.compacting === true,
		};
		result = await handlers[0][1](clone(c.event ?? {}), ctx);
	}
	// 独立に組んだ事実で arbiter を直接呼ぶ
	const s = c.snapshot;
	const e = c.event ?? {};
	const direct = arb.settle({
		trigger: "settle",
		mode: c.ctx?.mode === "print" || c.ctx?.mode === "json" ? c.ctx.mode : "interactive",
		child: false,
		outcome: e.outcome ?? "completed",
		phase: s.phase,
		compacting: s.compacting === true || c.ctx?.compacting === true,
		userInput: c.ctx?.pending === true,
		streak: s.streak,
		maxStreak: s.maxStreak,
		budgetExhausted: s.budgetExhausted,
		checkpoint: s.checkpoint,
		todo: s.todo,
		goal: s.goal,
		children: s.children,
	});
	return {
		registered: [r1.registered, r2?.registered ?? null],
		handlers: handlers.map((h) => h[0]),
		result,
		calls,
		pi: piCalls,
		direct,
	};
}

const req = JSON.parse(readFileSync(0, "utf8"));
let out;
if (req.cases) {
	out = { results: [] };
	for (const c of req.cases) out.results.push(await runCase(c));
} else if (req.effects) {
	const calls = newCalls();
	st.runEffects(req.effects, makeDeps({ snapshot: {} }, calls));
	out = { calls };
} else throw new Error("未知の要求");
process.stdout.write(JSON.stringify(out));
