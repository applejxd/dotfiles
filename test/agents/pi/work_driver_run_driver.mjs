// 並列実行基盤の接着層 (work/driver-run.ts) の試験用 driver。照合は test_work_driver_run.py。
//
//   node test/agents/pi/work_driver_run_driver.mjs <ケース名>   ケースの結果を JSON 1 行で出す
//   node test/agents/pi/work_driver_run_driver.mjs prop <seed> <n>   seed から n 本の乱数列を回し、違反の一覧を JSON 1 行で出す
// 偽の spawnChild・偽の Jobs・実物の runtime (tmp ディレクトリ) を使う。see docs/spec/work/driver-run.md
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "..", "..", "..");
const WORK = join(ROOT, "home", "dot_config", "pi", "harness", "work");
const load = (f) => import(pathToFileURL(join(WORK, f)).href);
const [dr, rt, ev, inv] = await Promise.all(["driver-run.ts", "runtime.ts", "events.ts", "invariants.ts"].map(load));

const H = "holder-A";
const BIG = { usd: 100, tokens: 10_000_000, ms: 10_000_000_000 };
const T = (id, writes = [], after = [], role = "worker", size = "S", kind) => ({ id, writes, after, role, size, kind });
const sleep0 = () => new Promise((r) => setTimeout(r, 0));
const flush = async () => {
	for (let i = 0; i < 20; i++) await sleep0();
};

/** 偽の子。run() の約束は finish() / close() で解く */
function fakeJob(id) {
	let resolve_;
	const p = new Promise((r) => (resolve_ = r));
	const j = {
		id,
		pid: 4000,
		calls: 0,
		tokens: 0,
		cost: 0,
		steers: [],
		closed: [],
		prompt: null,
		run(message, opts) {
			j.prompt = message;
			j.timeoutMs = opts.timeoutMs;
			return p;
		},
		steer(m) {
			j.steers.push(m);
			return "queued";
		},
		close(force) {
			j.closed.push(!!force);
			resolve_({ status: "closed", answer: "", errors: [], note: "closed while running", blocked: [] });
		},
		finish(r = {}) {
			resolve_({ status: "done", answer: "## 結論\n完了", errors: [], blocked: [], ...r });
		},
	};
	return j;
}

async function mk({ env = { PI_WORK_SCHEDULER: "1" }, child = false, tasks = [], approve = true, budget = BIG, jobsMax = 6, others = 0, mode, check = true, spawnError } = {}) {
	const dir = mkdtempSync(join(tmpdir(), "driver-run-"));
	let clock = 1_700_000_000_000;
	const now = () => (clock += 1);
	const runtime = rt.createRuntime({ cwd: dir, sessionId: "s", holder: H, pid: process.pid, root: join(dir, ".tmp", "work"), now, timers: { setInterval: () => 0, clearInterval: () => {} }, env: {} });
	await runtime.start();
	const E = ev.makeEvent;
	const h = (type, node, data, source = "system") => E(type, node, data, source, { holder: H });
	const evs = [E("goal.created", "G", { title: "run の試験", budget }, "system"), E("plan.proposed", "G", { hash: "h1" }, "model")];
	for (const t of tasks) {
		const attrs = { role: t.role, size: t.size, ...(t.kind ? { kind: t.kind } : {}) };
		evs.push(h("node.added", t.id, { node: { kind: "task", parent: "G", title: `task ${t.id}`, writes: t.writes, after: t.after, attrs } }, "model"));
	}
	// 承認の時点の task だけが起動候補になるので、task を足してから承認する
	if (approve) evs.push(h("plan.approved", "G", { hash: "h1" }, "user"));
	const first = await runtime.submit(evs);
	const handlers = new Map();
	const tools = [];
	const pi = { on: (n, f) => handlers.set(n, f), registerTool: (t) => tools.push(t.name), registerCommand: () => {} };
	const jobs = [];
	const calls = [];
	const live = new Set();
	const jobsLike = {
		max: jobsMax,
		get size() {
			return others + [...live].filter((j) => !j.done).length;
		},
	};
	const spawnChild = (...args) => {
		const [agent, ctx, owner, model, isolation, effort, cwd] = args;
		calls.push({ agent, cwd: ctx?.cwd, owner, model: model ?? null, isolation: isolation ?? null, effort: effort ?? null, cwdArg: cwd ?? null, extra: args.length });
		if (spawnError) return { error: spawnError };
		const j = fakeJob(`job-${jobs.length + 1}`);
		jobs.push(j);
		live.add(j);
		return { job: j, model: "m" };
	};
	const timers = { fns: [], cleared: 0, setInterval: (fn) => (timers.fns.push(fn), timers.fns.length), clearInterval: () => timers.cleared++ };
	const source = () => (mode ? { runtime: { mode, state: () => runtime.state(), submit: async (e) => (calls.push({ submit: e.length }), { ok: false, applied: [] }) }, holder: H } : { runtime, holder: H });
	const run = dr.registerDriverRun(pi, {
		child,
		env,
		runtime: source,
		spawnChild,
		jobs: jobsLike,
		now,
		timers,
		ownerRole: "worker",
		rand: () => 0.5,
		...(check ? { check: () => ({ name: "pytest", ok: true }) } : {}),
	});
	const ctx = { cwd: dir };
	return {
		dir,
		runtime,
		pi,
		handlers,
		tools,
		run,
		jobs,
		calls,
		live,
		timers,
		first,
		ctx,
		now,
		start: async () => handlers.get("session_start")?.({}, ctx),
		stop: async () => handlers.get("session_shutdown")?.({}),
		st: (id) => runtime.state().nodes.get(id)?.state,
		runsOf: (t) => [...runtime.state().nodes.values()].filter((n) => n.kind === "run" && n.parent === t),
		done: (j, r) => {
			j.done = true;
			j.finish(r);
		},
		cleanup: async () => {
			await runtime.close().catch(() => {});
			rmSync(dir, { recursive: true, force: true });
		},
	};
}

const spawnedTasks = (s) => s.runsOf ? [...s.runtime.state().nodes.values()].filter((n) => n.kind === "run").map((n) => n.parent).sort() : [];

const cases = {
	// 旗なし・PI_WORK=0・子では登録しない (何も起動しない)
	async gating() {
		const out = {};
		for (const [name, o] of Object.entries({
			noflag: { env: {} },
			flag0: { env: { PI_WORK_SCHEDULER: "0" } },
			off: { env: { PI_WORK_SCHEDULER: "1", PI_WORK: "0" } },
			child: { child: true },
			childEnv: { env: { PI_WORK_SCHEDULER: "1", PI_HARNESS_CHILD: "1" } },
			on: {},
		})) {
			const s = await mk({ ...o, tasks: [T("T1")] });
			await s.start();
			if (s.run) await s.run.kick();
			await flush();
			out[name] = { registered: s.run !== null, handlers: [...s.handlers.keys()], spawns: s.calls.length, timers: s.timers.fns.length };
			await s.cleanup();
		}
		return out;
	},
	// 承認済みの goal の ready な task だけが起動する。依存のある task は待つ
	async approved() {
		const s = await mk({ tasks: [T("T1", ["a/**"]), T("T2", ["b/**"], ["T1"])] });
		await s.start();
		await s.run.kick();
		await flush();
		const r = { calls: s.calls.map((c) => ({ agent: c.agent, owner: c.owner, isolation: c.isolation, model: c.model, effort: c.effort, cwdArg: c.cwdArg, extra: c.extra })), states: { T1: s.st("T1"), T2: s.st("T2") }, runs: spawnedTasks(s), live: s.run.live(), first: s.first.ok, prompt: s.jobs[0]?.prompt, timeoutMs: s.jobs[0]?.timeoutMs, ctxCwdOk: s.calls[0]?.cwd === s.dir, started: s.runsOf("T1").map((n) => n.state) };
		await s.cleanup();
		return r;
	},
	// 未承認の計画では何も起動しない
	async unapproved() {
		const s = await mk({ tasks: [T("T1"), T("T2")], approve: false });
		await s.start();
		await s.run.kick();
		await s.run.kick();
		await flush();
		const r = { calls: s.calls.length, runs: spawnedTasks(s), goal: s.runtime.state().nodes.get("G")?.state, T1: s.st("T1") };
		await s.cleanup();
		return r;
	},
	// work ツールは子に渡さない: pi に registerTool せず、子への依頼文は work を使えないと明記する
	async notool() {
		const s = await mk({ tasks: [T("T1", ["a/**"])] });
		await s.start();
		await s.run.kick();
		await flush();
		const r = { tools: s.tools, prompt: s.jobs[0].prompt, argc: s.calls[0].extra };
		await s.cleanup();
		return r;
	},
	// 書き込み集合が重なる task は同時に起動しない
	async overlap() {
		const s = await mk({ tasks: [T("T1", ["a/**"]), T("T2", ["a/x.ts"]), T("T3", ["b/**"])] });
		await s.start();
		await s.run.kick();
		await flush();
		const first = spawnedTasks(s);
		const j1 = s.jobs[0];
		s.done(j1);
		await flush();
		const after = spawnedTasks(s);
		const r = { first, after, violations: inv.check(s.runtime.state()).map((v) => v.inv) };
		await s.cleanup();
		return r;
	},
	// 同時数: index.ts の上限 (jobs.max - 他の子) と aimd の上限の小さい方
	async slots() {
		const out = {};
		for (const [name, o] of Object.entries({ two: { jobsMax: 2 }, others: { jobsMax: 3, others: 2 }, full: { jobsMax: 2, others: 2 }, six: { jobsMax: 6 } })) {
			const tasks = Array.from({ length: 12 }, (_, i) => T(`T${i + 1}`, [], [], "worker", "S", "ro"));
			const s = await mk({ ...o, tasks });
			await s.start();
			await s.run.kick();
			await s.run.kick();
			await flush();
			out[name] = { spawned: s.calls.length, live: s.run.live().length };
			await s.cleanup();
		}
		return out;
	},
	// 子の完了で次段がすぐ (タイマーを待たず) 起動する
	async pipeline() {
		const s = await mk({ tasks: [T("T1", ["a/**"]), T("T2", ["b/**"], ["T1"]), T("T3", ["c/**"], ["T2"])] });
		await s.start();
		await s.run.kick();
		await flush();
		const steps = [spawnedTasks(s)];
		s.done(s.jobs[0]);
		await flush();
		steps.push(spawnedTasks(s));
		s.done(s.jobs[1]);
		await flush();
		steps.push(spawnedTasks(s));
		s.done(s.jobs[2]);
		await flush();
		const r = { steps, states: ["T1", "T2", "T3"].map((id) => s.st(id)), goal: s.runtime.state().nodes.get("G")?.state, violations: inv.check(s.runtime.state()).map((v) => v.inv), timerFires: 0 };
		await s.cleanup();
		return r;
	},
	// 検査の経路が無いと checking のまま (次段は起動しない)
	async nocheck() {
		const s = await mk({ tasks: [T("T1", ["a/**"]), T("T2", ["b/**"], ["T1"])], check: false });
		await s.start();
		await s.run.kick();
		await flush();
		s.done(s.jobs[0]);
		await flush();
		const r = { T1: s.st("T1"), runs: spawnedTasks(s) };
		await s.cleanup();
		return r;
	},
	// 429 で止まり、失敗に数えず再キューされる。止まっている間は起動しない
	async ratelimit() {
		const s = await mk({ tasks: [T("T1", ["a/**"]), T("T2", ["b/**"])] });
		await s.start();
		await s.run.kick();
		await flush();
		const before = s.calls.length;
		s.done(s.jobs[0], { status: "failed", errors: ["429 Too Many Requests"], answer: "" });
		await flush();
		const types = s.runsOf("T1").map((n) => n.state);
		const r = { before, afterCalls: s.calls.length, T1: s.st("T1"), runs: types, failures: s.runtime.state().nodes.get("T1")?.attrs?.failures ?? null };
		await s.cleanup();
		return r;
	},
	// 予算超過: 1.5 倍で steer、2 倍で abort (使用量の増分を台帳へ)
	async budget() {
		const s = await mk({ tasks: [T("T1", ["a/**"], [], "worker", "M")], budget: { usd: 50, tokens: 1e9, ms: 1e12 } });
		await s.start();
		await s.run.kick();
		await flush();
		const j = s.jobs[0];
		const est = s.runsOf("T1")[0].attrs.est;
		const at = (x, c) => {
			j.cost = est.usd * x;
			j.tokens = Math.round(est.tokens * x);
			j.calls = c;
		};
		at(0.2, 1);
		await s.run.kick();
		const mid = { steers: j.steers.length, closed: j.closed.length };
		at(1.6, 2);
		await s.run.kick();
		await flush();
		const steered = { steers: j.steers.length, closed: j.closed.length };
		at(2.5, 3);
		await s.run.kick();
		await flush();
		const run = s.runsOf("T1")[0];
		const r = { mid, steered, aborted: { steers: j.steers.length, closed: j.closed, closedFlag: j.closed.length }, spent: run?.spent, runState: run?.state, goalSpent: s.runtime.state().nodes.get("G")?.spent };
		await s.cleanup();
		return r;
	},
	// session_shutdown で全ての子に abort。タイマーも止める
	async shutdown() {
		const s = await mk({ tasks: [T("T1", ["a/**"]), T("T2", ["b/**"]), T("T3", ["c/**"])] });
		await s.start();
		await s.run.kick();
		await flush();
		const before = s.run.live().length;
		await s.stop();
		await flush();
		const r = { before, closed: s.jobs.map((j) => j.closed), timers: s.timers.cleared, after: s.run.live().length };
		await s.run.kick();
		await flush();
		r.noMore = s.calls.length === s.jobs.length;
		r.armed = s.timers.fns.length;
		await s.cleanup();
		return r;
	},
	// 読み取り専用 (driver でない runtime) では起動も書き込みもしない
	async readonly() {
		const out = {};
		for (const mode of ["readonly", "off", "degraded"]) {
			const s = await mk({ tasks: [T("T1")], mode });
			await s.start();
			await s.run.kick();
			await flush();
			out[mode] = { calls: s.calls.length };
			await s.cleanup();
		}
		return out;
	},
	// runtime がまだ取れない (登録簿が空) 間は何もしない
	async noruntime() {
		const pi = { on: () => {}, registerTool: () => {} };
		let spawned = 0;
		const run = dr.registerDriverRun(pi, { child: false, env: { PI_WORK_SCHEDULER: "1" }, runtime: () => null, spawnChild: () => (spawned++, { error: "x" }), jobs: { max: 6, size: 0 } });
		await run.kick();
		globalThis.__piWork = undefined;
		return { spawned, registry: dr.registryRuntime() };
	},
	// 台帳が予約を拒否 (submit 失敗) したら子は起動しない
	async rejectsubmit() {
		const s = await mk({ tasks: [T("T1")], mode: "driver" });
		await s.start();
		await s.run.kick();
		await flush();
		const r = { spawns: s.calls.filter((c) => c.agent).length, submits: s.calls.filter((c) => c.submit !== undefined).length };
		await s.cleanup();
		return r;
	},
	// spawnChild が error を返したら run を失敗で閉じる (台帳に生きた run を残さない)
	async spawnerror() {
		const s = await mk({ tasks: [T("T1", ["a/**"])], spawnError: "too many live child jobs" });
		await s.start();
		await s.run.kick();
		await flush();
		const r = { runs: s.runsOf("T1").map((n) => n.state), live: s.run.live().length };
		await s.cleanup();
		return r;
	},
	// 子の blocked / closed の結果の写像
	async mapping() {
		const out = {};
		for (const [name, res] of Object.entries({ blocked: { status: "blocked", blocked: ["ask: not approved"], answer: "" }, failed: { status: "failed", errors: ["boom"], answer: "" }, limit: { status: "limit", note: "time limit", answer: "" }, closed: { status: "closed", answer: "" } })) {
			const s = await mk({ tasks: [T("T1", ["a/**"])] });
			await s.start();
			await s.run.kick();
			await flush();
			s.done(s.jobs[0], res);
			await flush();
			const run = s.runsOf("T1")[0];
			out[name] = { run: run?.state, task: s.st("T1") };
			await s.cleanup();
		}
		return out;
	},
	// 起動時の reconcile: 台帳に started のまま残った run (前のプロセスの子) を lost で閉じる
	async reconcile() {
		const s = await mk({ tasks: [T("T1", ["a/**"])] });
		const E = ev.makeEvent;
		const h = (type, node, data, source = "system") => E(type, node, data, source, { holder: H });
		const sub = await s.runtime.submit([h("run.reserved", "rX", { task: "T1", est: { usd: 0.1, tokens: 1, ms: 1 }, attrs: {} }), h("run.started", "rX", { pid: 1 })]);
		await s.start();
		await s.run.kick();
		await flush();
		const r = { sub: sub.ok, rX: s.runtime.state().nodes.get("rX")?.state };
		await s.cleanup();
		return r;
	},
	// 経路は spawnChild の 1 本だけ: 起動の呼び出しは spawnChild の (agent, ctx, owner, undefined, isolation) だけ
	async singlepath() {
		const s = await mk({ tasks: [T("T1", ["a/**"]), T("T2", ["b/**"])] });
		await s.start();
		await s.run.kick();
		await flush();
		const r = { calls: s.calls.map((c) => [c.agent, c.model, c.effort, c.cwdArg, c.isolation]), jobsMade: s.jobs.length };
		await s.cleanup();
		return r;
	},
};

// 性質試験: seed 固定の乱数列で台帳と子を回し、不変条件・同時数・書き込みの排他・予算を検査する
function lcg(seed) {
	let x = (seed * 2654435761 + 12345) >>> 0;
	return () => ((x = (Math.imul(x, 1664525) + 1013904223) >>> 0) / 4294967296);
}
async function prop(seed0, n) {
	const bad = [];
	let started = 0;
	for (let k = 0; k < n; k++) {
		const rnd = lcg(seed0 + k);
		const pool = ["a/**", "b/**", "a/x.ts", "c/**", "d/**"];
		const nt = 3 + Math.floor(rnd() * 6);
		const tasks = [];
		for (let i = 0; i < nt; i++) {
			const w = rnd() < 0.2 ? [] : [pool[Math.floor(rnd() * pool.length)]];
			const after = i > 0 && rnd() < 0.4 ? [`T${1 + Math.floor(rnd() * i)}`] : [];
			tasks.push(T(`T${i + 1}`, w, after, "worker", "S", w.length === 0 ? "ro" : undefined));
		}
		const jobsMax = 1 + Math.floor(rnd() * 4);
		const budget = rnd() < 0.3 ? { usd: 2, tokens: 1e9, ms: 1e12 } : BIG;
		const s = await mk({ tasks, jobsMax, budget });
		await s.start();
		for (let step = 0; step < 40; step++) {
			await s.run.kick();
			await flush();
			const liveJobs = s.jobs.filter((j) => !j.done);
			const tag = `seed ${seed0 + k} step ${step}`;
			if (liveJobs.length > jobsMax) bad.push(`${tag}: 同時数 ${liveJobs.length} > ${jobsMax}`);
			const st = s.runtime.state();
			for (const v of inv.check(st)) bad.push(`${tag}: ${v.inv} ${v.message ?? ""}`);
			const goal = st.nodes.get("G");
			if (goal && budget.usd < 100 && goal.spent.usd > budget.usd * 2.5) bad.push(`${tag}: 予算 ${goal.spent.usd} が 2 倍を大きく超えた`);
			if (liveJobs.length === 0 && step > 0 && [...st.nodes.values()].filter((x) => x.kind === "task").every((t) => ["done", "failed", "cancelled", "blocked", "skipped"].includes(t.state))) break;
			const r = rnd();
			for (const j of liveJobs) {
				if (rnd() < 0.5) {
					j.calls++;
					j.cost += rnd() * 0.8;
					j.tokens += 10;
				}
				if (rnd() < 0.4) {
					const q = rnd();
					s.done(j, q < 0.7 ? {} : q < 0.85 ? { status: "failed", errors: ["boom"], answer: "" } : { status: "failed", errors: ["429 rate limit"], answer: "" });
				}
			}
			void r;
		}
		started += s.jobs.length;
		await s.stop();
		await flush();
		await s.cleanup();
	}
	return { bad: bad.slice(0, 20), seeds: n, started };
}

const [name, a, b] = process.argv.slice(2);
const result = name === "prop" ? await prop(Number(a), Number(b)) : await cases[name]();
process.stdout.write(`${JSON.stringify(result)}\n`);
process.exit(0);
