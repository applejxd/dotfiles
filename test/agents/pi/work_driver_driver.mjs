// 並列実行基盤のドライバ (work/driver.ts) の統合試験用 driver。照合は test_work_driver.py。
//
//   node test/agents/pi/work_driver_driver.mjs <ケース名>     ケースの結果を JSON 1 行で出す
//   node test/agents/pi/work_driver_driver.mjs prop <seed> <n> seed から n 本の乱数列を回し、違反の一覧を JSON 1 行で出す
// see docs/spec/work/driver.md
import { writeSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "..", "..", "..");
const WORK = join(ROOT, "home", "dot_config", "pi", "harness", "work");
const load = (f) => import(pathToFileURL(join(WORK, f)).href);
const [ev, rd, inv, dr, ad, aimd] = await Promise.all(["events.ts", "reduce.ts", "invariants.ts", "driver.ts", "adapt.ts", "aimd.ts"].map(load));

const out = (s) => writeSync(1, `${s}\n`);
const H = "holder-A";
const BIG = { usd: 100, tokens: 10_000_000, ms: 10_000_000_000 };
const canon = (x) => JSON.stringify(x, (_k, v) => (v && typeof v === "object" && !Array.isArray(v) ? Object.fromEntries(Object.entries(v).sort(([a], [b]) => (a < b ? -1 : 1))) : v));
const ser = (s) => canon(rd.serialize(s));

/** シナリオ: goal を作って承認し、task を足す。tasks は [id, writes, after, role, size, kind?] */
export function scenario(tasks, budget = BIG) {
	const E = ev.makeEvent;
	const h = (type, node, data, source = "system") => E(type, node, data, source, { holder: H });
	const evs = [
		E("goal.created", "G", { title: "driver の試験", budget }, "system"),
		E("plan.proposed", "G", { hash: "h1" }, "model"),
		E("lease.acquired", "G", { holder: H, pid: process.pid }, "system"),
	];
	for (const [id, writes, after, role, size, kind, tbudget] of tasks) {
		const attrs = { role: role ?? "worker", size: size ?? "S", ...(kind ? { kind } : {}) };
		evs.push(h("node.added", id, { node: { kind: "task", parent: "G", title: `task ${id}`, writes, after: after ?? [], attrs, ...(tbudget ? { budget: tbudget } : {}) } }, "model"));
	}
	// 承認の時点の task だけが起動候補になるので、task を足してから承認する
	evs.push(h("plan.approved", "G", { hash: "h1" }, "user"));
	return evs;
}

/** 偽の spawner と台帳を持つ模擬。log はこれまでの全イベント (永続の代わり) */
export class Sim {
	constructor(tasks, { budget = BIG, slots = 4, hot = [] } = {}) {
		this.now = 1_000_000;
		this.res = { slots, hot };
		this.log = scenario(tasks, budget);
		this.state = dr.applyEvents(rd.emptyState(), this.log, this.now);
		this.aimd = aimd.aimdInit({ ...aimd.DEFAULT_AIMD, initial: Math.min(slots, aimd.DEFAULT_AIMD.max) });
		this.memo = dr.emptyMemo();
		this.stamps = this.log.map(() => this.now);
		this.live = new Set();
		this.spawned = [];
		this.effects = [];
		this.rejected = [];
		this.wakes = [];
	}
	push(events) {
		this.log.push(...events);
		this.stamps.push(...events.map(() => this.now));
		this.state = dr.applyEvents(this.state, events, this.now);
	}
	/** tick して、イベントを台帳へ入れ、spawn を偽の spawner で実行する */
	tick() {
		const r = dr.tick(this.state, { now: this.now, res: this.res, aimd: this.aimd, memo: this.memo, spawner: { live: [...this.live] }, holder: H });
		this.push(r.events);
		this.memo = r.memo;
		this.rejected.push(...r.rejected);
		for (const e of r.effects) {
			this.effects.push(e);
			if (e.kind === "spawn") {
				this.spawned.push(e);
				this.live.add(e.runId);
				this.push(dr.onSpawned(this.state, e.runId, 1000 + this.spawned.length, H));
			} else if (e.kind === "wake") this.wakes.push(e.reason);
		}
		return r;
	}
	usage(runId, u) {
		this.push(dr.onUsage(this.state, runId, u, H));
	}
	finish(runId, result, rand = 0.5) {
		const f = dr.onFinished(this.state, runId, result, { now: this.now, aimd: this.aimd, rand, holder: H });
		this.log.push(...f.events);
		this.stamps.push(...f.events.map(() => this.now));
		this.state = f.state;
		this.aimd = f.aimd;
		this.live.delete(runId);
		return f;
	}
	runOf(task) {
		return [...this.state.nodes.values()].filter((n) => n.kind === "run" && n.parent === task);
	}
	st(id) {
		return this.state.nodes.get(id)?.state;
	}
	violations(prev) {
		return inv.check(this.state, prev).map((v) => `${v.inv}:${v.node ?? ""}:${v.message}`);
	}
	replayEqual() {
		const evs = JSON.parse(JSON.stringify(this.log)).map((e, i) => ({ ...e, seq: i + 1, ts: this.stamps[i] }));
		return ser(rd.fold(evs)) === ser(this.state);
	}
}

const T = (id, writes, after = [], size = "S", kind, tbudget) => [id, writes, after, "worker", size, kind, tbudget];
const DONE = (runUsage = { usd: 0.1, tokens: 100, ms: 100 }) => ({ status: "done", usage: runUsage, answer: "## 結論\n完了", check: { name: "pytest", ok: true } });

const cases = {
	// start → 予約 → spawn → started → finished → ended → 次の ready の start (完了した子から次段がすぐ start)
	flow() {
		const s = new Sim([T("T1", ["a/**"]), T("T2", ["b/**"]), T("T3", ["c/**"], ["T1"]), T("T4", ["d/**"], ["T2", "T3"])], { slots: 2 });
		const first = s.tick();
		const t1 = {
			events: first.events.map((e) => e.type),
			effects: first.effects.map((e) => e.kind),
			spawn: first.effects.filter((e) => e.kind === "spawn").map((e) => e.task),
			states: Object.fromEntries(["T1", "T2", "T3", "T4"].map((id) => [id, s.st(id)])),
			runStates: s.spawned.map((e) => s.st(e.runId)),
		};
		const r1 = s.runOf("T1")[0].id;
		const fin = s.finish(r1, DONE());
		const afterFin = { T1: s.st("T1"), run: s.st(r1), types: fin.events.map((e) => e.type), digest: fin.digestInput };
		const second = s.tick();
		const t2 = { spawn: second.effects.filter((e) => e.kind === "spawn").map((e) => e.task), T2: s.st("T2"), T3: s.st("T3"), liveRuns: [...s.live].length };
		const r2 = s.runOf("T2")[0].id;
		s.finish(r2, DONE());
		const r3 = s.runOf("T3")[0].id;
		s.finish(r3, DONE());
		const third = s.tick();
		const t3 = { spawn: third.effects.filter((e) => e.kind === "spawn").map((e) => e.task) };
		s.finish(s.runOf("T4")[0].id, DONE());
		const fourth = s.tick();
		return {
			t1,
			afterFin,
			t2,
			t3,
			wakes: fourth.effects.filter((e) => e.kind === "wake").map((e) => e.reason),
			final: Object.fromEntries(["T1", "T2", "T3", "T4"].map((id) => [id, s.st(id)])),
			rejected: s.rejected,
			violations: s.violations(),
			replayEqual: s.replayEqual(),
		};
	},
	// 429: 失敗に数えず再キュー、AIMD が半減、バックオフ中は起動しない、連続成功で戻る
	ratelimit() {
		const tasks = Array.from({ length: 14 }, (_, i) => T(`T${i + 1}`, [], [], "S", "ro"));
		const s = new Sim(tasks, { slots: 4 });
		s.tick();
		const limit0 = s.aimd.limit;
		const live0 = [...s.live].length;
		const r1 = s.spawned[0].runId;
		const task1 = s.spawned[0].task;
		const f = s.finish(r1, { status: "failed", error: "429 Too Many Requests", usage: { usd: 0.01, tokens: 10, ms: 10 } });
		const failures = ad.schedStateOf(s.state, { now: s.now, resources: s.res }).tasks.find((t) => t.id === task1).failures;
		const afterLimit = s.aimd.limit;
		const pausedUntil = s.aimd.pausedUntil;
		const t1 = s.tick();
		const t2 = s.tick();
		const kinds1 = t1.effects.map((e) => e.kind);
		const kinds2 = t2.effects.map((e) => e.kind);
		const taskState = s.st(task1);
		const runState = s.st(r1);
		const typesAfter = f.events.map((e) => e.type);
		// 止まっている間は起動しない
		const spawnedWhilePaused = s.spawned.length;
		// バックオフが明けたら再開し、連続成功で上限が戻る
		s.now = pausedUntil + 1;
		const t3 = s.tick();
		const kinds3 = t3.effects.map((e) => e.kind);
		const limits = [];
		for (let i = 0; i < 40 && [...s.live].length + s.spawned.length < 60; i++) {
			for (const id of [...s.live]) s.finish(id, DONE());
			limits.push(s.aimd.limit);
			s.now += 1000;
			s.tick();
		}
		return {
			limit0,
			live0,
			afterLimit,
			pausedUntil,
			now: s.now,
			failures,
			taskState,
			runState,
			typesAfter,
			rateLimited: f.rateLimited,
			error: f.error,
			kinds1,
			kinds2,
			spawnedWhilePaused,
			kinds3,
			maxLimit: Math.max(...limits),
			finalLimit: s.aimd.limit,
			requeuedStarted: s.runOf(task1).length,
			violations: s.violations(),
			replayEqual: s.replayEqual(),
		};
	},
	// 予算: 超過で start が出ない / 1.5 倍で steer (1 回) / 2 倍で abort (1 回)
	budget() {
		const tiny = new Sim([T("T1", ["a/**"])], { budget: { usd: 0.0001, tokens: 1, ms: 1 } });
		const tinyTick = tiny.tick();
		const one = new Sim([T("T1", ["a/**"]), T("T2", ["b/**"])], { budget: { usd: 100, tokens: 200_000, ms: 10_000_000_000 } });
		const oneTick = one.tick();
		const s = new Sim([T("T1", ["a/**"])]);
		s.tick();
		const r = s.spawned[0];
		const res = r.reserve;
		s.usage(r.runId, { usd: res.usd * 0.5, tokens: res.tokens * 0.5, ms: res.ms * 0.5 });
		const k0 = s.tick().effects.map((e) => e.kind);
		s.usage(r.runId, { usd: res.usd * 1.0, tokens: res.tokens * 1.0, ms: res.ms * 0.5 });
		const k15 = s.tick();
		const k15b = s.tick();
		s.usage(r.runId, { usd: res.usd * 0.6, tokens: res.tokens * 0.6, ms: res.ms * 0.1 });
		const k2 = s.tick();
		const k2b = s.tick();
		return {
			tinySpawn: tinyTick.effects.filter((e) => e.kind === "spawn").length,
			tinyEvents: tinyTick.events.map((e) => e.type),
			oneSpawn: oneTick.effects.filter((e) => e.kind === "spawn").length,
			k0,
			k15: k15.effects.map((e) => e.kind),
			k15b: k15b.effects.map((e) => e.kind),
			k2: k2.effects.map((e) => `${e.kind}:${e.reason ?? ""}`),
			k2b: k2b.effects.map((e) => e.kind),
			steerRun: k15.effects.find((e) => e.kind === "steer")?.run ?? null,
			abortRun: k2.effects.find((e) => e.kind === "abort")?.run ?? null,
			runId: r.runId,
			spent: s.state.nodes.get(r.runId).spent,
		};
	},
	// 見積り: adapt は attrs.est (起動時の見積り) を reserve にする。超過後も 1.5 倍の steer・2 倍の abort が出る。attrs.est が無ければ従来どおり
	estimate() {
		const s = new Sim([T("T1", ["a/**"])]);
		s.tick();
		const r = s.spawned[0];
		const est = r.reserve;
		const reserveOf = () => ad.schedStateOf(s.state, { now: s.now, resources: s.res }).runs.find((x) => x.id === r.runId).reserve;
		s.usage(r.runId, { usd: est.usd * 1.6, tokens: est.tokens * 1.6, ms: est.ms * 0.1 });
		const ledgerReserved = s.state.nodes.get(r.runId).reserved;
		const k15 = s.tick();
		const k15b = s.tick();
		s.usage(r.runId, { usd: est.usd * 0.5, tokens: est.tokens * 0.5, ms: est.ms * 0.1 });
		const k2 = s.tick();
		// attrs.est が無い run は台帳の reserved のまま
		const bare = new Sim([T("T1", ["a/**"])]);
		bare.push([ev.makeEvent("run.reserved", "r9", { task: "T1", est: { usd: 2, tokens: 3, ms: 4 } }, "system", { holder: H })]);
		const bareReserve = ad.schedStateOf(bare.state, { now: bare.now, resources: bare.res }).runs[0].reserve;
		// 不正な est (数でない) は無視
		const bad = new Sim([T("T1", ["a/**"])]);
		bad.push([ev.makeEvent("run.reserved", "r9", { task: "T1", est: { usd: 2, tokens: 3, ms: 4 }, attrs: { est: { usd: "x" } } }, "system", { holder: H })]);
		const badReserve = ad.schedStateOf(bad.state, { now: bad.now, resources: bad.res }).runs[0].reserve;
		return {
			est,
			reserve: reserveOf(),
			ledgerReserved: { usd: ledgerReserved.usd, tokens: ledgerReserved.tokens },
			k15: k15.effects.map((e) => e.kind),
			k15b: k15b.effects.map((e) => e.kind),
			k2: k2.effects.map((e) => `${e.kind}:${e.reason ?? ""}`),
			bareReserve,
			badReserve,
		};
	},
	// 無出力の見張り: onOutput で最後の出力を覚え、5 分で steer (1 回)・10 分で abort。attrs の steeredAt・lastOutputAt も読む
	stall() {
		const s = new Sim([T("T1", [], [], "S", "ro")]);
		s.tick();
		const id = s.spawned[0].runId;
		const o = dr.onOutput(s.state, id, s.now, s.memo);
		s.memo = o.memo;
		s.push(o.events);
		const kinds = () => s.tick().effects.map((e) => `${e.kind}:${e.reason ?? ""}`);
		s.now += 4 * 60_000;
		const at4 = kinds();
		s.now += 60_000;
		const at5 = kinds();
		const at5b = kinds();
		s.now += 5 * 60_000;
		const at10 = kinds();
		// 出力があれば idle が戻る (別の run で確かめる)
		const t = new Sim([T("T1", [], [], "S", "ro")]);
		t.tick();
		const tid = t.spawned[0].runId;
		t.now += 4 * 60_000;
		t.memo = dr.onOutput(t.state, tid, t.now, t.memo).memo;
		t.now += 4 * 60_000;
		const quiet = t.tick().effects.map((e) => e.kind);
		// 終わった run には記録しない
		t.finish(tid, DONE());
		const dead = dr.onOutput(t.state, tid, t.now, t.memo);
		// attrs の lastOutputAt・steeredAt を adapt が読む
		const a = new Sim([T("T1", [], [], "S", "ro")]);
		a.push([ev.makeEvent("run.reserved", "r9", { task: "T1", est: { usd: 1, tokens: 1, ms: 1 }, attrs: { lastOutputAt: 123, steeredAt: 456 } }, "system", { holder: H })]);
		const ar = ad.schedStateOf(a.state, { now: a.now, resources: a.res }).runs[0];
		return {
			at4,
			at5,
			at5b,
			at10,
			quiet,
			deadEvents: dead.events.length,
			deadMemoSame: JSON.stringify(dead.memo) === JSON.stringify(t.memo),
			memoAt: s.memo.outputAt,
			auxTypes: o.events.map((e) => e.type),
			attr: { lastOutputAt: ar.lastOutputAt, steered: ar.steered, stallSteered: ar.stallSteered },
		};
	},
	// writes の重なり: 同時に start しない。台帳の門 (run.reserved) に拒否されない
	overlap() {
		const named = new Sim([T("T1", ["scripts/verify.py"]), T("T2", ["*.py"]), T("T3", ["src/**/*.ts"]), T("T4", ["src/a.ts"])]);
		named.tick();
		const disjoint = new Sim([T("T1", ["a/**"]), T("T2", ["b/**"]), T("T3", ["c/**"])]);
		disjoint.tick();
		const same = new Sim([T("T1", ["a/**"]), T("T2", ["a/x.ts"])]);
		same.tick();
		const sameFirst = same.spawned.map((e) => e.task);
		same.finish(same.spawned[0].runId, DONE());
		same.tick();
		return {
			namedSpawn: named.spawned.map((e) => e.task),
			namedRejected: named.rejected,
			namedViolations: named.violations(),
			disjointSpawn: disjoint.spawned.map((e) => e.task),
			disjointRejected: disjoint.rejected,
			sameFirst,
			sameAll: same.spawned.map((e) => e.task),
			sameViolations: same.violations(),
		};
	},
	// 子には work ツールを渡さない
	worktool() {
		const s = new Sim([T("T1", ["a/**"]), T("T2", [], [], "S", "ro"), T("T3", ["c/**"])]);
		s.tick();
		return {
			spawns: s.spawned.map((e) => ({ task: e.task, workTool: e.workTool, hasKey: "workTool" in e, role: e.role, worktree: e.worktree ?? null, prompt: e.prompt })),
		};
	},
	// 入力の不変と決定性
	purity() {
		const s = new Sim([T("T1", ["a/**"]), T("T2", ["b/**"]), T("T3", [], [], "S", "ro")]);
		const before = ser(s.state);
		const ctx = { now: s.now, res: s.res, aimd: s.aimd, memo: s.memo, holder: H };
		const ctxBefore = canon(ctx);
		const a = dr.tick(s.state, ctx);
		const b = dr.tick(s.state, ctx);
		const unchangedTick = ser(s.state) === before && canon(ctx) === ctxBefore;
		const same = canon(a) === canon(b);
		s.push(a.events);
		for (const e of a.effects) if (e.kind === "spawn") s.push(dr.onSpawned(s.state, e.runId, 7, H));
		const before2 = ser(s.state);
		const res = { status: "done", usage: { usd: 0.1, tokens: 100, ms: 100 }, answer: "## 結論\nok" };
		const resBefore = canon(res);
		const aimdBefore = canon(s.aimd);
		const runId = a.effects.find((e) => e.kind === "spawn").runId;
		const f1 = dr.onFinished(s.state, runId, res, { now: s.now, aimd: s.aimd, holder: H });
		const f2 = dr.onFinished(s.state, runId, res, { now: s.now, aimd: s.aimd, holder: H });
		return {
			unchangedTick,
			same,
			unchangedFinish: ser(s.state) === before2 && canon(res) === resBefore && canon(s.aimd) === aimdBefore,
			sameFinish: canon({ ...f1, state: ser(f1.state) }) === canon({ ...f2, state: ser(f2.state) }),
		};
	},
	// 子の失敗の理由は null にならない
	failure() {
		const s = new Sim([T("T1", ["a/**"]), T("T2", ["b/**"]), T("T3", ["c/**"]), T("T4", ["d/**"])]);
		s.tick();
		const u = { usd: 0.1, tokens: 10, ms: 10 };
		const cases = [
			["failed", undefined],
			["failed", "   "],
			["failed", "テストが落ちた"],
			["aborted", undefined],
		];
		const res = [];
		s.spawned.forEach((e, i) => {
			const [status, error] = cases[i];
			const f = s.finish(e.runId, { status, error, usage: u });
			const run = s.state.nodes.get(e.runId);
			res.push({ status, error: f.error, runState: run.state, note: run.notes.map((n) => n.text), taskState: s.st(e.task), digest: f.digestInput?.status ?? null });
		});
		const ok = new Sim([T("T1", ["a/**"])]);
		ok.tick();
		const fo = ok.finish(ok.spawned[0].runId, DONE());
		const lim = new Sim([T("T1", ["a/**"])]);
		lim.tick();
		const fl = lim.finish(lim.spawned[0].runId, { status: "limit", usage: u });
		return { res, okError: fo.error, limitError: fl.error, limitRate: fl.rateLimited, violations: s.violations() };
	},
	// 失敗した task は失敗に数える (429 ではない)
	failcount() {
		const s = new Sim([T("T1", ["a/**"])]);
		s.tick();
		s.finish(s.spawned[0].runId, { status: "failed", error: "コンパイルエラー", usage: { usd: 0.1, tokens: 10, ms: 10 } });
		const ss = ad.schedStateOf(s.state, { now: s.now, resources: s.res });
		const t = s.tick();
		return { failures: ss.tasks[0].failures, taskState: s.st("T1"), aimdLimit: s.aimd.limit, strikes: s.aimd.strikes, wakes: t.effects.filter((e) => e.kind === "wake").map((e) => e.reason) };
	},
	// 使用量: 子と評価役の合算が run → task → goal に載る
	usage() {
		const s = new Sim([T("T1", ["a/**"])]);
		s.tick();
		const id = s.spawned[0].runId;
		s.usage(id, { usd: 0.2, tokens: 200, ms: 20 });
		s.usage(id, { usd: 0.1, tokens: 100, ms: 10 });
		const mid = { ...s.state.nodes.get(id).spent };
		s.finish(id, { status: "done", usage: { usd: 0.5, tokens: 500, ms: 50 }, answer: "## 結論\nok" });
		return {
			mid,
			run: s.state.nodes.get(id).spent,
			task: s.state.nodes.get("T1").spent,
			goal: s.state.nodes.get("G").spent,
			goalReserved: s.state.nodes.get("G").reserved,
			usedSched: ad.schedStateOf(s.state, { now: s.now, resources: s.res }).used,
			noop: dr.onUsage(s.state, id, { usd: 1, tokens: 1, ms: 1 }, H).length,
			zero: dr.onUsage(s.state, "none", { usd: 1, tokens: 1, ms: 1 }, H).length,
		};
	},
	// 429 が続いたら goal を pause して親を起こす (重複して起こさない)
	exhausted() {
		const tasks = Array.from({ length: 8 }, (_, i) => T(`T${i + 1}`, [], [], "S", "ro"));
		const s = new Sim(tasks, { slots: 6 });
		s.tick();
		const wakes = [];
		const ids = [...s.live];
		for (const id of ids.slice(0, 5)) s.finish(id, { status: "limit", error: "usage limit", usage: { usd: 0.01, tokens: 1, ms: 1 } }, 0.5);
		const exhausted = s.aimd.exhausted;
		const t1 = s.tick();
		const t2 = s.tick();
		return {
			exhausted,
			goal: s.st("G"),
			wake1: t1.effects.filter((e) => e.kind === "wake").map((e) => e.reason),
			wake2: t2.effects.filter((e) => e.kind === "wake").map((e) => e.reason),
			events1: t1.events.map((e) => e.type),
			violations: s.violations(),
		};
	},
	// スケジューラが知らない台帳の門 (task ごとの予算) に拒否された start は起動せず、拒否として返す
	gate() {
		const s = new Sim([T("T1", ["a/**"], [], "S", undefined, { usd: 0.01, tokens: 1, ms: 1 }), T("T2", ["b/**"])]);
		const r = dr.tick(s.state, { now: s.now, res: s.res, aimd: s.aimd, holder: H });
		const after = dr.applyEvents(s.state, r.events, s.now);
		return {
			events: r.events.map((e) => e.type),
			rejected: r.rejected,
			spawns: r.effects.filter((e) => e.kind === "spawn").map((e) => e.task),
			T1: after.nodes.get("T1").state,
			T2: after.nodes.get("T2").state,
			violations: inv.check(after).map((v) => v.inv),
		};
	},
	// 台帳に残った started の run を spawner が知らないとき lost で閉じる
	reconcile() {
		const s = new Sim([T("T1", ["a/**"]), T("T2", ["b/**"])]);
		s.tick();
		const [a, b] = s.spawned.map((e) => e.runId);
		const evs = dr.reconcile(s.state, { live: [a] }, H);
		s.push(evs);
		return { types: evs.map((e) => e.type), nodes: evs.map((e) => e.node), runB: s.st(b), runA: s.st(a), taskB: s.st("T2"), violations: s.violations() };
	},
};

// ── 性質試験 ──
function rng(seed) {
	let a = seed >>> 0;
	return () => {
		a = (a + 0x6d2b79f5) >>> 0;
		let t = a;
		t = Math.imul(t ^ (t >>> 15), t | 1);
		t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
		return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
	};
}

function oneSeed(seed) {
	const r = rng(seed);
	const pick = (xs) => xs[Math.floor(r() * xs.length)];
	const n = 3 + Math.floor(r() * 6);
	const pool = [[], ["a/**"], ["b/**"], ["c/x.ts"], ["*.py"], ["docs/**"], ["a/x.ts"], ["scripts/verify.py"]];
	const tasks = [];
	for (let i = 0; i < n; i++) {
		const after = [];
		for (let j = 0; j < i; j++) if (r() < 0.25) after.push(`T${j + 1}`);
		const writes = pick(pool);
		tasks.push(T(`T${i + 1}`, writes, after, pick(["S", "S", "M"]), writes.length === 0 ? "ro" : undefined));
	}
	const budgetKind = pick(["big", "mid", "tight"]);
	const budget = budgetKind === "big" ? BIG : budgetKind === "mid" ? { usd: 6, tokens: 2_000_000, ms: 10_000_000_000 } : { usd: 1.2, tokens: 400_000, ms: 10_000_000_000 };
	const slots = 1 + Math.floor(r() * 4);
	const s = new Sim(tasks, { budget, slots });
	const bad = [];
	const note = (m) => bad.length < 8 && bad.push(`seed ${seed}: ${m}`);
	let prev = s.state;
	let peak = 0;
	let usedPeak = 0;
	const activeRuns = () => [...s.state.nodes.values()].filter((x) => x.kind === "run" && (x.state === "reserved" || x.state === "started")).length;
	for (let step = 0; step < 90; step++) {
		s.now += Math.floor(r() * 120_000);
		const cap = Math.min(s.res.slots, s.aimd.limit);
		const before = activeRuns();
		let t;
		try {
			t = s.tick();
		} catch (e) {
			note(`tick が例外: ${e.message}`);
			break;
		}
		const started = t.effects.filter((e) => e.kind === "spawn").length;
		const after = activeRuns();
		peak = Math.max(peak, after);
		if (started > 0 && after > cap) note(`同時数が上限を超えた: ${after} > ${cap}`);
		if (after > s.res.slots) note(`同時数が slots を超えた: ${after} > ${s.res.slots}`);
		for (const e of t.effects) if (e.kind === "spawn" && e.workTool !== false) note("workTool が false でない");
		const g = s.state.nodes.get("G");
		if (g.budget) for (const k of ["usd", "tokens", "ms"]) if (g.reserved[k] > g.budget[k] + 1e-9 || g.spent[k] > g.budget[k] + 1e-9) note(`予算を超えた: ${k}`);
		usedPeak = Math.max(usedPeak, g.reserved.usd);
		for (const v of s.violations(prev)) note(`不変条件 ${v}`);
		prev = s.state;
		// 走っている子を気まぐれに進める
		for (const id of [...s.live].sort()) {
			const run = s.state.nodes.get(id);
			const res = run.reserved;
			const x = r();
			if (x < 0.25) s.usage(id, { usd: res.usd * 0.2 * r(), tokens: res.tokens * 0.2 * r(), ms: res.ms * 0.2 * r() });
			else if (x < 0.55) {
				const f = Math.min(1, 0.2 + 0.8 * r());
				const u = { usd: res.usd * f, tokens: res.tokens * f, ms: res.ms * f };
				s.finish(id, { status: "done", usage: { usd: Math.max(u.usd, run.spent.usd), tokens: Math.max(u.tokens, run.spent.tokens), ms: Math.max(u.ms, run.spent.ms) }, answer: "## 結論\nok", check: { name: "t", ok: r() < 0.85 } }, r());
			} else if (x < 0.65) s.finish(id, { status: "failed", error: r() < 0.5 ? "エラー" : undefined, usage: run.spent }, r());
			else if (x < 0.75) s.finish(id, { status: r() < 0.5 ? "limit" : "failed", error: "429 Too Many Requests", usage: run.spent }, r());
			else if (x < 0.8) s.finish(id, { status: "aborted", usage: run.spent }, r());
			for (const v of s.violations(prev)) note(`不変条件 (終了後) ${v}`);
			prev = s.state;
		}
		if (s.rejected.length > 0) {
			note(`台帳の門が拒否: ${canon(s.rejected[0])}`);
			s.rejected.length = 0;
		}
	}
	if (!s.replayEqual()) note("永続→再生が一致しない");
	return { bad, peak, usedPeak };
}

const [, , cmd, ...args] = process.argv;
if (cmd === "prop") {
	const seed0 = Number(args[0] ?? 1);
	const n = Number(args[1] ?? 200);
	const bad = [];
	let peak = 0;
	for (let i = 0; i < n; i++) {
		const r = oneSeed(seed0 + i);
		bad.push(...r.bad);
		peak = Math.max(peak, r.peak);
	}
	out(JSON.stringify({ n, bad: bad.slice(0, 20), badCount: bad.length, peak }));
} else if (cases[cmd]) {
	out(JSON.stringify(cases[cmd]()));
} else {
	process.stderr.write(`unknown command: ${cmd}\n`);
	process.exit(2);
}
