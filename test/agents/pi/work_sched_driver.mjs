// work/sched 系 (overlap・aimd・reserve・strategy・sched) の純関数の試験用 driver。標準入力の JSON を実行し、結果を JSON で標準出力へ出す。
// 照合は test/agents/test_work_sched.py (表の総当たり・glob の偽陰性・予約・429 など)。性質試験 (props) は乱数 (seed 固定) をここで回す。
//
//   {"calls":[{"mod":"sched","fn":"next","args":[...]}, ...]}      関数を順に呼ぶ (引数は deep freeze。入力を変更したら失敗する)
//   {"map":{"mod":"strategy","fn":"select","argsList":[[...], ...]}}  同じ関数を多数の引数で呼ぶ (総当たり用)
//   {"props":{"seed":1,"runs":200}}                                   性質試験。{violations:[{prop,detail}], counts:{prop:n}} を返す
// see docs/spec/work/scheduler.md
import { dirname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { readFileSync } from "node:fs";

const HERE = dirname(fileURLToPath(import.meta.url));
const WORK = resolve(HERE, "..", "..", "..", "home", "dot_config", "pi", "harness", "work");
const load = (n) => import(pathToFileURL(resolve(WORK, `${n}.ts`)).href);
const M = { overlap: await load("overlap"), aimd: await load("aimd"), reserve: await load("reserve"), strategy: await load("strategy"), sched: await load("sched") };

const deepFreeze = (x) => {
	if (x && typeof x === "object" && !Object.isFrozen(x)) {
		Object.freeze(x);
		for (const v of Object.values(x)) deepFreeze(v);
	}
	return x;
};
const clone = (x) => JSON.parse(JSON.stringify(x));
const call = (c) => M[c.mod][c.fn](...c.args.map((a) => deepFreeze(clone(a))));

// ── 乱数 (mulberry32。seed 固定) ──
const prng = (seed) => {
	let a = seed >>> 0;
	return () => {
		a = (a + 0x6d2b79f5) >>> 0;
		let t = a;
		t = Math.imul(t ^ (t >>> 15), t | 1);
		t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
		return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
	};
};
const pick = (r, xs) => xs[Math.floor(r() * xs.length)];
const int = (r, lo, hi) => lo + Math.floor(r() * (hi - lo + 1));

const WRITE_POOL = ["src/a/**", "src/b/**", "src/a/x.ts", "docs/guide/index.md", "scripts/verify.py", "src/c/index.ts", "test/**", "src/*/z.ts", "lib/q.ts"];
const HOT = ["**/index.ts", "scripts/verify.py", "docs/**/index.md"];
const money = (r, k) => ({ usd: +(r() * k).toFixed(3), tokens: Math.floor(r() * k * 100000), ms: Math.floor(r() * k * 600000) });

function genState(r) {
	const n = int(r, 0, 9);
	const tasks = [];
	const runs = [];
	for (let i = 0; i < n; i++) {
		const kind = pick(r, ["ro", "edit", "edit", "check"]);
		const role = kind === "ro" ? pick(r, ["explore", "review"]) : kind === "check" ? "check" : "worker";
		const after = [];
		for (let j = 0; j < i; j++) if (r() < 0.25) after.push(`t${j}`);
		const state = pick(r, ["ready", "ready", "ready", "running", "done", "waiting", "proposed", "failed"]);
		const t = {
			id: `t${i}`,
			state,
			kind,
			role,
			size: pick(r, ["S", "M", "L"]),
			writes: kind === "edit" ? [pick(r, WRITE_POOL), ...(r() < 0.3 ? [pick(r, WRITE_POOL)] : [])] : [],
			after,
		};
		if (r() < 0.2) t.risk = "boundary";
		if (r() < 0.3) t.group = pick(r, ["g1", "g2"]);
		if (r() < 0.2) t.uncertain = true;
		if (r() < 0.2) t.accept = true;
		if (r() < 0.2) t.pipeline = true;
		if (r() < 0.2 && i > 0) t.contract = `t${int(r, 0, i - 1)}`;
		if (r() < 0.1) t.failures = 2;
		tasks.push(t);
		if (state === "running" && r() < 0.8) {
			runs.push({
				id: `r${i}`,
				task: t.id,
				state: pick(r, ["reserved", "started"]),
				reserve: money(r, 2),
				spent: money(r, 4),
				strategy: pick(r, ["worktree", "serial", "shared", "fanout"]),
				...(r() < 0.3 ? { lastOutputAt: int(r, 0, 1_000_000) } : {}),
			});
		}
	}
	const stats = { byMethod: {}, pairs: [] };
	if (r() < 0.3) stats.byMethod.speculative = { recent: Array.from({ length: 10 }, () => r() < 0.4), total: 10, disabledAt: r() < 0.5 ? 1 : undefined };
	if (r() < 0.2 && n >= 2) stats.pairs.push(["t0", "t1"]);
	const lim = int(r, 1, 10);
	const paused = r() < 0.2;
	const state = {
		tasks,
		runs,
		used: money(r, 3),
		history: {},
		stats,
		provider: { limit: lim, streak: 0, strikes: paused ? 1 : 0, pausedUntil: paused ? 2_000_000 : 0, exhausted: r() < 0.05 },
		...(r() < 0.5 ? { budget: { usd: +(r() * 30).toFixed(2), tokens: int(r, 100_000, 9_000_000) } } : {}),
		...(r() < 0.3 ? { providerAnnounced: true } : {}),
	};
	const res = { slots: int(r, 1, 8), hot: HOT, verifyBusy: r() < 0.2 };
	return { state, res, now: int(r, 0, 3_000_000) };
}

const isStart = (a) => a.kind === "start";
const moneyKeys = ["usd", "tokens", "ms"];

function checkOne(r, V, C, i) {
	const { state, res, now } = genState(r);
	const frozen = deepFreeze(clone({ state, res, now }));
	let a1;
	let a2;
	try {
		a1 = M.sched.next(frozen.state, frozen.res, frozen.now);
		a2 = M.sched.next(frozen.state, frozen.res, frozen.now);
	} catch (e) {
		V.push({ prop: "no_throw_no_mutation", detail: `${i}: ${e.message}` });
		return;
	}
	C.determinism = (C.determinism ?? 0) + 1;
	if (JSON.stringify(a1) !== JSON.stringify(a2)) V.push({ prop: "determinism", detail: `${i}` });
	if (!Array.isArray(a1) || a1.length === 0) V.push({ prop: "nonempty", detail: `${i}` });
	const starts = a1.filter(isStart);
	C.starts = (C.starts ?? 0) + starts.length;
	C.spec_starts = (C.spec_starts ?? 0) + starts.filter((s) => s.strategy === "speculative").length;
	C.race_starts = (C.race_starts ?? 0) + starts.filter((s) => s.strategy === "race").length;
	const activeRuns = state.runs.filter((x) => x.state === "reserved" || x.state === "started");
	const cap = Math.max(0, Math.min(res.slots, state.provider.limit));
	C.backpressure = (C.backpressure ?? 0) + 1;
	if (starts.length > Math.max(0, cap - activeRuns.length)) V.push({ prop: "backpressure", detail: `${i}: ${starts.length} > ${cap}-${activeRuns.length}` });
	// 429 の間・使い切りの後は start しない
	C.no_start_when_paused = (C.no_start_when_paused ?? 0) + 1;
	if ((now < state.provider.pausedUntil || state.provider.exhausted) && starts.length > 0) V.push({ prop: "no_start_when_paused", detail: `${i}` });
	// 予算
	C.budget = (C.budget ?? 0) + 1;
	if (state.budget && starts.length > 0) {
		const reserved = activeRuns.reduce((m, x) => ({ usd: m.usd + x.reserve.usd, tokens: m.tokens + x.reserve.tokens, ms: m.ms + x.reserve.ms }), { usd: 0, tokens: 0, ms: 0 });
		for (const k of moneyKeys) {
			if (state.budget[k] === undefined) continue;
			const add = starts.reduce((s, x) => s + x.reserve[k], 0);
			if (state.used[k] + reserved[k] + add > state.budget[k] + 1e-9) V.push({ prop: "budget", detail: `${i}: ${k}` });
		}
	}
	// writes の重なる task が同時に start されない (実行中の task とも)
	C.no_overlap = (C.no_overlap ?? 0) + 1;
	const byId = new Map(state.tasks.map((t) => [t.id, t]));
	const startedIds = [...new Set(starts.map((s) => s.task))];
	const activeIds = new Set(activeRuns.map((x) => x.task));
	for (const t of state.tasks) if (t.state === "running" || t.state === "checking") activeIds.add(t.id);
	const others = [...activeIds];
	for (let x = 0; x < startedIds.length; x++) {
		const A = byId.get(startedIds[x]);
		for (const id of [...others.filter((o) => o !== A.id), ...startedIds.slice(x + 1)]) {
			const B = byId.get(id);
			if (!B) continue;
			if (A.writes.length && B.writes.length && M.overlap.writesMayOverlap(A.writes, B.writes)) V.push({ prop: "no_overlap", detail: `${i}: ${A.id} ${B.id}` });
			const ha = M.overlap.hotHits(A.writes, res.hot);
			const hb = M.overlap.hotHits(B.writes, res.hot);
			if (ha.some((h) => hb.includes(h))) V.push({ prop: "hot_exclusive", detail: `${i}: ${A.id} ${B.id}` });
		}
	}
	// 依存が done でない task を (見込み以外で) start しない。無効化された見込みは start しない
	C.deps = (C.deps ?? 0) + 1;
	for (const s of starts) {
		const t = byId.get(s.task);
		const pending = t.after.filter((d) => byId.get(d)?.state !== "done");
		if (pending.length > 0 && s.strategy !== "speculative") V.push({ prop: "deps", detail: `${i}: ${s.task}` });
		if (s.strategy === "speculative" && M.strategy.isDisabled(state.stats, "speculative", now)) V.push({ prop: "speculative_disabled", detail: `${i}` });
	}
}

// ── 逐次の模擬 (壁なし・work-conserving・並行数・重なり) ──
function simulate(r, V, C, i) {
	const n = int(r, 2, 12);
	const cap = int(r, 1, 6);
	const tasks = [];
	const dur = new Map();
	for (let k = 0; k < n; k++) {
		const after = [];
		for (let j = 0; j < k; j++) if (r() < 0.2) after.push(`t${j}`);
		const kind = r() < 0.4 ? "ro" : "edit";
		const share = r() < 0.25 ? "shared/**" : `f${k}/**`;
		tasks.push({ id: `t${k}`, state: after.length ? "proposed" : "ready", kind, role: kind === "ro" ? "explore" : "worker", size: pick(r, ["S", "M"]), writes: kind === "edit" ? [share] : [], after });
		dur.set(`t${k}`, int(r, 1, 10) * 1000);
	}
	let now = 0;
	let runs = [];
	let seq = 0;
	const res = { slots: cap, hot: [] };
	const provider = { limit: cap, streak: 0, strikes: 0, pausedUntil: 0, exhausted: false };
	const finish = new Map();
	let guard = 0;
	while (tasks.some((t) => t.state !== "done")) {
		if (++guard > 400) {
			V.push({ prop: "sim_terminates", detail: `${i}` });
			return;
		}
		const state = deepFreeze(clone({ tasks, runs, used: { usd: 0, tokens: 0, ms: 0 }, history: {}, stats: { byMethod: {}, pairs: [] }, provider }));
		const acts = M.sched.next(state, res, now);
		const started = acts.filter(isStart);
		for (const s of started) {
			const t = tasks.find((x) => x.id === s.task);
			t.state = "running";
			const id = `r${seq++}`;
			runs.push({ id, task: t.id, state: "started", reserve: { ...s.reserve }, spent: { usd: 0, tokens: 0, ms: 0 }, strategy: s.strategy });
			finish.set(id, now + dur.get(t.id));
		}
		const act = tasks.filter((t) => t.state === "running");
		C.sim_cap = (C.sim_cap ?? 0) + 1;
		if (act.length > cap) V.push({ prop: "sim_cap", detail: `${i}: ${act.length} > ${cap}` });
		for (let x = 0; x < act.length; x++)
			for (let y = x + 1; y < act.length; y++)
				if (act[x].writes.length && act[y].writes.length && M.overlap.writesMayOverlap(act[x].writes, act[y].writes)) V.push({ prop: "sim_overlap", detail: `${i}: ${act[x].id} ${act[y].id}` });
		// work-conserving (壁を作らない): 空き枠があるのに、起動できる ready の task が残っていてはならない
		C.pipeline = (C.pipeline ?? 0) + 1;
		if (act.length < cap) {
			for (const t of tasks) {
				if (t.state !== "ready") continue;
				const clash = act.some((a) => a.writes.length && t.writes.length && M.overlap.writesMayOverlap(a.writes, t.writes));
				if (!clash) V.push({ prop: "pipeline", detail: `${i}: ${t.id} が空き枠で待っている (t=${now})` });
			}
		}
		if (runs.length === 0) {
			V.push({ prop: "sim_deadlock", detail: `${i}` });
			return;
		}
		// 最初に終わる run を完了させる (同時刻は id 順)
		const [rid, at] = [...finish.entries()].sort((p, q) => p[1] - q[1] || (p[0] < q[0] ? -1 : 1))[0];
		now = at;
		finish.delete(rid);
		const run = runs.find((x) => x.id === rid);
		tasks.find((x) => x.id === run.task).state = "done";
		runs = runs.filter((x) => x.id !== rid);
		for (const t of tasks) if (t.state === "proposed" && t.after.every((d) => tasks.find((x) => x.id === d).state === "done")) t.state = "ready";
	}
}

function aimdProps(r, V, C, i) {
	const A = M.aimd;
	const cfg = { ...A.DEFAULT_AIMD, initial: int(r, 1, 10), k: int(r, 1, 6) };
	let s = A.aimdInit(cfg);
	const evs = [];
	let t = 0;
	for (let k = 0; k < 60; k++) {
		t += int(r, 1, 100000);
		const ev = r() < 0.3 ? { t: "429", ts: t, rand: r() } : { t: "success", ts: t };
		const prev = s;
		s = A.aimdStep(deepFreeze(clone(s)), deepFreeze(clone(ev)), cfg);
		evs.push(ev);
		C.aimd_bounds = (C.aimd_bounds ?? 0) + 1;
		if (s.limit < 1 || s.limit > cfg.max) V.push({ prop: "aimd_bounds", detail: `${i}: ${s.limit}` });
		if (ev.t === "429" && s.limit !== Math.max(1, Math.floor(prev.limit / 2))) V.push({ prop: "aimd_halve", detail: `${i}` });
		if (ev.t === "429") {
			const d = s.pausedUntil - ev.ts;
			const raw = Math.min(cfg.capMs, cfg.baseMs * 2 ** (s.strikes - 1));
			if (d > cfg.capMs || d < raw * 0.8 - 1 && raw < cfg.capMs) V.push({ prop: "backoff_range", detail: `${i}: ${d}` });
		}
		if (ev.t === "success" && prev.limit > s.limit) V.push({ prop: "aimd_decrease_on_success", detail: `${i}` });
	}
	if (JSON.stringify(A.foldAimd(deepFreeze(clone(evs)), cfg)) !== JSON.stringify(s)) V.push({ prop: "aimd_fold", detail: `${i}` });
}

function statsProps(r, V, C, i) {
	const S = M.strategy;
	let s = S.emptyStats();
	const oks = [];
	let ever = false;
	for (let k = 0; k < 40; k++) {
		const ok = r() < 0.6;
		oks.push(ok);
		s = S.foldStats(deepFreeze(clone(s)), { type: "outcome", ts: k, method: "speculative", ok });
		const w = oks.slice(-10);
		if (w.length >= 5 && w.filter((x) => !x).length / w.length > 0.4) ever = true;
		C.stats = (C.stats ?? 0) + 1;
		const m = s.byMethod.speculative;
		if (m.recent.length > 10) V.push({ prop: "stats_bounded", detail: `${i}` });
		if ((m.disabledAt !== undefined) !== ever) V.push({ prop: "stats_disable_rule", detail: `${i}: step ${k}` });
		if (S.isDisabled(s, "speculative", k) !== ever) V.push({ prop: "stats_is_disabled", detail: `${i}: step ${k}` });
	}
	for (let k = 0; k < 120; k++) s = S.foldStats(s, { type: "conflict", ts: k, a: `a${k}`, b: `b${k}` });
	if (s.pairs.length > S.PAIRS_MAX) V.push({ prop: "pairs_bounded", detail: `${i}` });
}

if (process.argv[2] === "--selftest") {
	console.log("ok");
	process.exit(0);
}
const input = JSON.parse(readFileSync(0, "utf8"));
if (input.calls) {
	console.log(JSON.stringify({ results: input.calls.map((c) => call(c)) }));
} else if (input.map) {
	const { mod, fn, argsList } = input.map;
	console.log(JSON.stringify({ results: argsList.map((args) => call({ mod, fn, args })) }));
} else if (input.props) {
	const { seed, runs } = input.props;
	const V = [];
	const C = {};
	const r = prng(seed);
	for (let i = 0; i < runs; i++) checkOne(r, V, C, i);
	for (let i = 0; i < Math.max(1, Math.floor(runs / 4)); i++) simulate(r, V, C, i);
	for (let i = 0; i < Math.max(1, Math.floor(runs / 10)); i++) aimdProps(r, V, C, i);
	for (let i = 0; i < Math.max(1, Math.floor(runs / 10)); i++) statsProps(r, V, C, i);
	console.log(JSON.stringify({ violations: V.slice(0, 20), counts: C, nViolations: V.length }));
} else throw new Error("unknown input");
