// `/goal` の台帳への接着 (home/dot_config/pi/harness/work/goal.ts) の試験用 driver。標準入力の JSON を実行し、結果を JSON で標準出力へ出す。照合は test_work_goal.py。
//
//   {"run":{"cmds":["/goal の引数", ...],"now0":1000,"step":1000}}   コマンド列を 1 本ずつ変換 → 台帳へ追記 (reduce) → 導出する
//   {"diff":{"seed":1,"runs":220,"steps":14}}                        乱数のコマンド列を goal-core 直接と台帳経由で適用し、導出した GoalState を比べる
//   {"model":true}                                                   モデル・system の出所で利用者専用のイベントを作る・畳むと拒否されること
//   {"pure":{"cmds":[...]}}                                          入力 (凍結した state) を変更せず、決定的であること
//   {"facts":{...}}                                                  settleFactsOfGoal
//   {"raw":{"events":[...]}}                                          生のイベント列を畳み (拒否は飛ばす)、導出した GoalState と goal ノードを返す
// see docs/spec/work/goal.md
import { dirname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "..", "..", "..");
const H = resolve(ROOT, "home", "dot_config", "pi", "harness");
const load = (f) => import(pathToFileURL(resolve(H, f)).href);
const [gl, ev, rd, core] = await Promise.all(["work/goal.ts", "work/events.ts", "work/reduce.ts", "goal-core.ts"].map(load));

const deepFreeze = (x) => {
	if (x && typeof x === "object" && !Object.isFrozen(x)) {
		Object.freeze(x);
		for (const v of x instanceof Map ? [...x.values()] : Object.values(x)) deepFreeze(v);
	}
	return x;
};

const rng = (seed) => () => {
	seed = (seed + 0x6d2b79f5) | 0;
	let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
	t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
	return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
};

/** 変換したイベントを台帳へ畳む (seq・ts は driver が付ける) */
const append = (state, events, ts) => {
	let s = state;
	for (const e of events) s = rd.reduce(s, { ...e, ts, seq: s.seq + 1 });
	return s;
};

const short = (r) => ({
	ok: r.ok,
	...(r.error !== undefined ? { error: r.error } : {}),
	...(r.text !== undefined ? { text: r.text } : {}),
	...(r.draft !== undefined ? { draft: r.draft } : {}),
	...(r.approval !== undefined ? { approval: r.approval } : {}),
	events: r.events.map((e) => ({ type: e.type, node: e.node, source: e.source, data: e.data })),
});

const runCmds = ({ cmds, now0 = 1000, step = 1000 }) => {
	let s = rd.emptyState();
	const steps = [];
	cmds.forEach((c, i) => {
		const now = now0 + i * step;
		// 文字列は /goal の引数。{task: タイトル, state?} は承認後に足す task (モデル出所)。{kind} は解析済みのコマンド (approve など)
		if (typeof c === "object" && c.task !== undefined) {
			const node = { kind: "task", parent: s.goals[s.goals.length - 1], title: c.task, writes: [], after: [] };
			s = append(s, [ev.makeEvent("node.added", c.id ?? `t${i}`, { node }, "model")], now);
			steps.push({ task: c.task, seq: s.seq });
			return;
		}
		const cmd = typeof c === "object" ? c : core.parseGoalArgs(c);
		const r = gl.goalCommandToEvents(cmd, s, now);
		if (r.ok) s = append(s, r.events, now);
		steps.push({ cmd, ...short(r), goal: gl.goalStateOf(s), seq: s.seq });
	});
	return { steps };
};

// ── 差分試験 ──
const WORDS = ["調査", "実装", "検査", "docs", "status", "pause", "resume", "clear", "draft", "budget", "ok", "x"];
const FLAGS = ["--rounds", "--minutes", "--tokens"];
const VALUES = ["1", "5", "20", "200", "201", "0", "abc", "3k", "2m", "1440", "1441", "1000000000", "1000000001", ""];
const randArgs = (R) => {
	const pick = (a) => a[Math.floor(R() * a.length)];
	const r = R();
	if (r < 0.1) return "";
	if (r < 0.2) return "status";
	if (r < 0.32) return "pause";
	if (r < 0.44) return "resume";
	if (r < 0.52) return "clear";
	if (r < 0.58) return `draft ${pick(WORDS)}`;
	const flags = [];
	for (const f of FLAGS) if (R() < 0.35) flags.push(R() < 0.5 ? `${f} ${pick(VALUES)}` : `${f}=${pick(VALUES)}`);
	if (r < 0.72) return `budget ${flags.join(" ")}`.trim();
	if (R() < 0.15) flags.push("--bogus");
	if (R() < 0.3) flags.push("--audit");
	const text = R() < 0.05 ? "" : `${pick(WORDS)} ${pick(WORDS)}`;
	return `${flags.join(" ")} ${text}`.trim();
};

const COMPARE = (g, c) => {
	if (g === null || c === null) return g === c ? null : { g, c };
	const strip = (x) => {
		const { updatedAt, ...rest } = x;
		return rest;
	};
	const a = JSON.stringify(strip(g));
	const b = JSON.stringify(strip(c));
	return a === b ? null : { g: strip(g), c: strip(c) };
};

const diffRuns = ({ seed, runs, steps }) => {
	const R = rng(seed);
	const mismatches = [];
	let compared = 0;
	let applied = { set: 0, pause: 0, resume: 0, budget: 0, clear: 0, noop: 0, rejected: 0 };
	for (let run = 0; run < runs; run++) {
		let s = rd.emptyState();
		let cs = null; // goal-core 直接の GoalState (破棄は null)
		for (let i = 0; i < steps; i++) {
			const now = 1000 + (run * 1000 + i) * 10;
			const args = randArgs(R);
			const cmd = core.parseGoalArgs(args);
			const r = gl.goalCommandToEvents(cmd, s, now);
			const fail = (why) => mismatches.push({ run, i, args, why });
			// goal-core 側の期待
			let expectOk = true;
			let next = cs;
			let kind = "noop";
			const live = cs !== null && cs.status !== "done";
			switch (cmd.kind) {
				case "error":
					expectOk = false;
					break;
				case "set": {
					if (live) { expectOk = false; break; }
					const g = core.newGoal(cmd.text, cmd.budget, now, { audit: cmd.audit });
					if ("error" in g) { expectOk = false; break; }
					next = g; kind = "set";
					break;
				}
				case "pause":
					if (!live) expectOk = false;
					else if (cs.status === "active") { next = core.pauseGoal(cs, "user", now); kind = "pause"; }
					break;
				case "resume":
					if (!live) expectOk = false;
					else if (cs.status === "paused") { next = core.resumeGoal(cs, now); kind = "resume"; }
					break;
				case "budget": {
					if (!live) { expectOk = false; break; }
					const b = core.setBudget(cs, cmd.budget, now);
					if ("error" in b) { expectOk = false; break; }
					next = b; kind = "budget";
					break;
				}
				case "clear":
					if (live) { next = null; kind = "clear"; }
					break;
				default:
					break; // status・draft
			}
			if (r.ok !== expectOk) { fail(`ok が食い違う: 台帳 ${r.ok} (${r.error ?? ""}) ≠ core ${expectOk}`); continue; }
			if (!r.ok) { applied.rejected++; if (typeof r.error !== "string" || r.error === "") fail("error の文言が無い"); continue; }
			if ((r.events.length > 0) !== (kind !== "noop")) fail(`events の有無が食い違う: ${r.events.length} 件 / ${kind}`);
			if (r.events.some((e) => e.source !== "user")) fail("出所が user でないイベントがある");
			try {
				s = append(s, r.events, now);
			} catch (err) {
				fail(`台帳が拒否した: ${err.message}`);
				break;
			}
			applied[kind]++;
			cs = next;
			compared++;
			const g = gl.goalStateOf(s);
			const d = COMPARE(g, cs);
			if (d) fail(`GoalState が食い違う: ${JSON.stringify(d)}`);
		}
	}
	return { mismatches: mismatches.slice(0, 20), nMismatch: mismatches.length, compared, applied };
};

const modelChecks = () => {
	const out = {};
	const tryMake = (type, node, data, source) => {
		try {
			ev.makeEvent(type, node, data, source);
			return "ok";
		} catch (e) {
			return `${e.name}: ${e.message}`;
		}
	};
	const bud = { usd: 1, tokens: 1, ms: 1, rounds: 1 };
	for (const src of ["model", "system"]) {
		out[src] = {
			"plan.approved": tryMake("plan.approved", "g", { hash: "h" }, src),
			"budget.adjusted": tryMake("budget.adjusted", "g", { budget: bud }, src),
			"goal.resumed": tryMake("goal.resumed", "g", {}, src),
		};
	}
	// モデルが goal.created・plan.proposed まで出しても、承認 (利用者専用) が無いので active にならず、導出は null
	let s = rd.emptyState();
	s = append(s, [ev.makeEvent("goal.created", "g1", { title: "x", budget: { usd: 1, tokens: 1, ms: 1 } }, "model"), ev.makeEvent("plan.proposed", "g1", { hash: "h" }, "model")], 1);
	out.modelPlanned = { state: s.nodes.get("g1").state, derived: gl.goalStateOf(s) };
	// source なしの plan.approved を台帳へ直接畳もうとする → 拒否
	try {
		rd.reduce(s, { ts: 2, seq: s.seq + 1, type: "plan.approved", node: "g1", data: { hash: "h" }, source: "model" });
		out.reduceModelApproved = "ok";
	} catch (e) {
		out.reduceModelApproved = `${e.name}: ${e.message}`;
	}
	// 利用者が承認した goal を、モデルの goal.resumed が再開させられない (paused のまま)
	const r = runCmds({ cmds: ["作業", "pause"] });
	let t = rd.emptyState();
	for (const [i, c] of ["作業", "pause"].entries()) {
		const rr = gl.goalCommandToEvents(core.parseGoalArgs(c), t, 1000 + i);
		t = append(t, rr.events, 1000 + i);
	}
	try {
		rd.reduce(t, { ts: 9, seq: t.seq + 1, type: "goal.resumed", node: t.goals[0], data: {}, source: "model" });
		out.reduceModelResume = "ok";
	} catch (e) {
		out.reduceModelResume = `${e.name}: ${e.message}`;
	}
	out.pausedAfter = gl.goalStateOf(t)?.status;
	out.runLen = r.steps.length;
	return out;
};

const pureChecks = ({ cmds }) => {
	let s = rd.emptyState();
	const res = [];
	cmds.forEach((c, i) => {
		const now = 1000 + i;
		const cmd = deepFreeze(core.parseGoalArgs(c));
		const frozen = deepFreeze(structuredClone(s));
		const before = JSON.stringify(rd.serialize(frozen));
		const a = gl.goalCommandToEvents(cmd, frozen, now);
		const b = gl.goalCommandToEvents(cmd, frozen, now);
		const gs1 = gl.goalStateOf(frozen);
		const gs2 = gl.goalStateOf(frozen);
		res.push({
			same: JSON.stringify(a) === JSON.stringify(b),
			unchanged: JSON.stringify(rd.serialize(frozen)) === before,
			gsSame: JSON.stringify(gs1) === JSON.stringify(gs2),
		});
		if (a.ok) s = append(s, a.events, now);
	});
	return { res };
};

const factsChecks = (p) => {
	let s = rd.emptyState();
	for (const [i, c] of p.cmds.entries()) {
		const rr = gl.goalCommandToEvents(core.parseGoalArgs(c), s, 1000 + i);
		s = append(s, rr.events, 1000 + i);
	}
	return gl.settleFactsOfGoal(s, p.facts);
};

const rawChecks = ({ events }) => {
	let s = rd.emptyState();
	const steps = [];
	for (const e of events) {
		try {
			s = rd.reduce(s, { ts: s.seq + 1, seq: s.seq + 1, ...e });
			steps.push({ ok: true });
		} catch (err) {
			steps.push({ ok: false, error: `${err.name}: ${err.message}` });
		}
	}
	const id = s.goals[s.goals.length - 1];
	return { steps, goal: gl.goalStateOf(s), node: id ? s.nodes.get(id) : null };
};

const input = JSON.parse(await new Promise((res) => {
	let b = "";
	process.stdin.setEncoding("utf8");
	process.stdin.on("data", (d) => (b += d));
	process.stdin.on("end", () => res(b));
}));

let out;
if (input.run) out = runCmds(input.run);
else if (input.diff) out = diffRuns(input.diff);
else if (input.model) out = modelChecks();
else if (input.pure) out = pureChecks(input.pure);
else if (input.facts) out = factsChecks(input.facts);
else if (input.raw) out = rawChecks(input.raw);
else throw new Error("未知の入力");
process.stdout.write(JSON.stringify(out));
