// スケジューラ: 台帳の射影 (SchedState) と資源から、次にやること (Action) を決める純関数。
// 外部依存・fs・pi の API・乱数・時計なし (now は引数)。入力は変更しない。決定的 (同じ入力 → 同じ出力)。
// 台帳 (work-core) の関数は import しない。アダプタが台帳から SchedState を作る (配線時)。see docs/spec/work/scheduler.md
import type { ProviderState } from "./aimd.ts";
import { hotHits, serialize, validateWrites, writesMayOverlap } from "./overlap.ts";
import { addMoney, canReserve, durationP50, estimate, watch, ZERO } from "./reserve.ts";
import type { Budget, Size } from "./reserve.ts";
import { disabledMethods, failLevel, learnedOverlap, select } from "./strategy.ts";
import type { Isolation, Method, Stats, StrategyInput } from "./strategy.ts";
import type { Money, TaskState } from "./types.ts";

export interface SchedTask {
	id: string;
	/** ready = 取り出し可。waiting = 実行中の上流を待つ (見込みの候補)。台帳の状態をそのまま渡す */
	state: TaskState;
	kind: "ro" | "edit" | "check";
	role: string;
	size: Size;
	writes: string[];
	after: string[];
	risk?: "none" | "boundary";
	/** 同じ group (共有 worktree の候補) */
	group?: string;
	uncertain?: boolean;
	/** 受け入れが機械判定できる */
	accept?: boolean;
	/** 契約 (I/F) の task の id。done のときだけ見込みの条件を満たす */
	contract?: string;
	/** foreach × 段の task */
	pipeline?: boolean;
	/** これまでの失敗回数 (429 の再キューは数えない) */
	failures?: number;
	/** 見積りの所要 (ms)。省略時は履歴の p50 */
	estMs?: number;
	/** 費用の見積り (usd)。省略時は見積り表 */
	costUsd?: number;
}

export interface SchedRun {
	id: string;
	task: string;
	state: "reserved" | "started" | "done" | "blocked" | "failed" | "limit" | "aborted" | "lost";
	reserve: Money;
	spent: Money;
	/** 評価役の使用量 (子と合算して見積りと比べる) */
	evalSpent?: Money;
	steered?: boolean;
	/** 最後に出力があった時刻 (stall の見張り) */
	lastOutputAt?: number;
	stallSteered?: boolean;
	strategy?: Method;
	/** 見込みの run: 起動時の契約の版 */
	speculative?: { contract: string; rev: number };
}

export interface SchedState {
	tasks: SchedTask[];
	runs: SchedRun[];
	budget?: Budget;
	/** 完了した run を含む使用済み (予約は含まない) */
	used: Money;
	/** 履歴 (役割:大きさ → 完了した run の使用量) */
	history: Record<string, Money[]>;
	stats: Stats;
	provider: ProviderState;
	/** pause_provider を通知済み (解除まで繰り返さない) */
	providerAnnounced?: boolean;
	/** 満たすと bundle が揃う task の id (優先する) */
	bundleNeed?: string[];
	/** 契約 task の現在の版 (見込みの run の版と違えば cancel) */
	contractRevs?: Record<string, number>;
}

export interface Resources {
	/** 子の総数の上限 (設定) */
	slots: number;
	/** hot file の glob (排他予約) */
	hot: string[];
	/** 全件検査が走っている */
	verifyBusy?: boolean;
	/** 見込みに使える予算の比率 (既定 0.25) */
	specFraction?: number;
	/** 無出力で steer / abort する時間 (ms。既定 5 分 / 10 分) */
	stallSteerMs?: number;
	stallAbortMs?: number;
}

export type Action =
	| {
			kind: "start";
			task: string;
			strategy: Method;
			isolation: Isolation;
			reserve: Money;
			degree: number;
			verify: string;
			why: string;
			/** 競争 (race) の候補の番号 */
			variant?: number;
			speculative?: { contract: string; rev: number };
	  }
	| { kind: "steer"; run: string; text: string }
	| { kind: "abort"; run: string; reason: string }
	| { kind: "pause_provider"; until: number; reason: string }
	| { kind: "resume_provider" }
	| { kind: "wake_parent"; reason: string }
	| { kind: "none" };

const TERMINAL: readonly string[] = ["done", "failed", "cancelled", "skipped"];
const ACTIVE_RUN: readonly string[] = ["reserved", "started"];
const cmpStr = (a: string, b: string): number => (a < b ? -1 : a > b ? 1 : 0);

const scale = (m: Money, n: number): Money => ({ usd: m.usd * n, tokens: m.tokens * n, ms: m.ms * n });

interface ActiveTask {
	id: string;
	kind: SchedTask["kind"];
	writes: string[];
	hot: string[];
	group?: string;
	method?: Method;
}

/** 臨界路の長さ (その task から下流への見積り所要の最長の和)。循環は辺を無視して有限にする */
function criticalPaths(tasks: readonly SchedTask[], state: SchedState): Map<string, number> {
	const byId = new Map(tasks.map((t) => [t.id, t]));
	const dependents = new Map<string, string[]>();
	for (const t of tasks) {
		for (const a of t.after) {
			const list = dependents.get(a) ?? [];
			list.push(t.id);
			dependents.set(a, list);
		}
	}
	const memo = new Map<string, number>();
	const visiting = new Set<string>();
	const cp = (id: string): number => {
		const hit = memo.get(id);
		if (hit !== undefined) return hit;
		const t = byId.get(id);
		if (!t || visiting.has(id)) return 0;
		visiting.add(id);
		let best = 0;
		for (const d of dependents.get(id) ?? []) best = Math.max(best, cp(d));
		visiting.delete(id);
		const v = (t.estMs ?? durationP50(t.role, t.size, state.history)) + best;
		memo.set(id, v);
		return v;
	};
	for (const t of tasks) cp(t.id);
	return memo;
}

/** 次の Action を返す。必ず 1 件以上 (何も無ければ none)。starts は空き枠を超えない (背圧) */
export function next(state: SchedState, res: Resources, now: number): Action[] {
	const out: Action[] = [];
	const prov = state.provider;
	const paused = now < prov.pausedUntil;
	// ── provider (429) ──
	if (paused && !state.providerAnnounced) out.push({ kind: "pause_provider", until: prov.pausedUntil, reason: "429" });
	if (!paused && prov.pausedUntil > 0 && state.providerAnnounced) out.push({ kind: "resume_provider" });
	if (prov.exhausted) out.push({ kind: "wake_parent", reason: "provider_exhausted" });
	const blocked = paused || prov.exhausted;

	// ── 実行中の run の監視 ──
	const activeRuns = state.runs.filter((r) => ACTIVE_RUN.includes(r.state)).sort((a, b) => cmpStr(a.id, b.id));
	const stallSteer = res.stallSteerMs ?? 5 * 60_000;
	const stallAbort = res.stallAbortMs ?? 10 * 60_000;
	for (const r of activeRuns) {
		if (r.speculative && (state.contractRevs?.[r.speculative.contract] ?? r.speculative.rev) !== r.speculative.rev) {
			out.push({ kind: "abort", run: r.id, reason: "contract-changed" });
			continue;
		}
		const w = watch(r);
		if (w === "abort") {
			out.push({ kind: "abort", run: r.id, reason: "usage-2x" });
			continue;
		}
		const idle = r.lastOutputAt === undefined ? 0 : now - r.lastOutputAt;
		if (r.lastOutputAt !== undefined && idle >= stallAbort) {
			out.push({ kind: "abort", run: r.id, reason: "stall" });
			continue;
		}
		if (w === "steer") out.push({ kind: "steer", run: r.id, text: "使用量が見積りの 1.5 倍に達した。残りを絞って wrap-up し、結論と未完を報告せよ" });
		else if (r.lastOutputAt !== undefined && idle >= stallSteer && !r.stallSteered) {
			out.push({ kind: "steer", run: r.id, text: "5 分以上出力が無い。現状を 1 行で報告し、詰まっていれば部分結果を保って終えよ" });
		}
	}

	// ── 起動 ──
	const tasks = state.tasks;
	const byId = new Map(tasks.map((t) => [t.id, t]));
	const done = (id: string): boolean => byId.get(id)?.state === "done";
	const cap = Math.max(0, Math.min(res.slots, prov.limit));
	const runTask = new Map<string, SchedRun>();
	for (const r of activeRuns) runTask.set(r.task, r);
	let free = cap - activeRuns.length;
	const startedHere: string[] = [];
	let budgetBlocked = false;

	// 実行中の task (run を持つもの + 台帳が running・checking とするもの)
	const hot = res.hot;
	const active: ActiveTask[] = [];
	for (const t of tasks) {
		if (!runTask.has(t.id) && t.state !== "running" && t.state !== "checking") continue;
		active.push({ id: t.id, kind: t.kind, writes: t.writes, hot: hotHits(t.writes, hot), group: t.group, method: runTask.get(t.id)?.strategy });
	}
	let reserved: Money = activeRuns.reduce((m, r) => addMoney(m, r.reserve), ZERO);
	let specReserved: Money = activeRuns.filter((r) => r.speculative).reduce((m, r) => addMoney(m, r.reserve), ZERO);
	let specCount = activeRuns.filter((r) => r.speculative).length;

	if (!blocked && free > 0) {
		const live = tasks.filter((t) => !TERMINAL.includes(t.state));
		const cps = criticalPaths(tasks, state);
		const activeIds = new Set(active.map((a) => a.id));
		// 自動の直列化: 重なる task に (実行中 → 今すぐ着手できるもの → 臨界路の長い順 → id) の順で依存を足す
		// 依存待ちの task を先頭にすると、着手できる task が無駄に待たされる (head-of-line)。着手可能なものを先にする
		const tier = (t: SchedTask): number => (activeIds.has(t.id) ? 0 : t.after.every(done) ? 1 : 2);
		const ser = serialize(
			live.map((t) => ({ id: t.id, writes: t.writes, after: t.after, rank: tier(t) * 1e15 - (cps.get(t.id) ?? 0) })),
		);
		const auto = ser.auto;
		const needSet = new Set(state.bundleNeed ?? []);
		const costOf = (t: SchedTask): number => t.costUsd ?? estimate(t.role, t.size, state.history).usd;
		const cmp = (a: SchedTask, b: SchedTask): number =>
			(cps.get(b.id) ?? 0) - (cps.get(a.id) ?? 0) ||
			(needSet.has(a.id) ? 0 : 1) - (needSet.has(b.id) ? 0 : 1) ||
			costOf(a) - costOf(b) ||
			cmpStr(a.id, b.id);

		type Cand = { t: SchedTask; spec: boolean };
		const cands: Cand[] = [];
		for (const t of live) {
			if (runTask.has(t.id) || t.state === "running" || t.state === "checking") continue;
			if (t.state !== "ready" && t.state !== "waiting") continue;
			const autoOk = (auto[t.id] ?? []).every(done);
			if (!autoOk) continue;
			const pending = t.after.filter((a) => !done(a));
			if (pending.length === 0) {
				if (t.state === "ready") cands.push({ t, spec: false });
			} else if (pending.every((a) => byId.get(a)?.state === "running")) {
				cands.push({ t, spec: true });
			}
		}
		cands.sort((a, b) => cmp(a.t, b.t));
		const readyRo = cands.filter((c) => !c.spec && c.t.kind === "ro").length;
		const dis = disabledMethods(state.stats, now);
		const fail = failLevel(state.stats, "worktree");
		const specFraction = res.specFraction ?? 0.25;
		const budget = state.budget;

		for (const { t, spec } of cands) {
			if (free <= 0) break;
			const w = validateWrites(t.writes);
			if (!w.ok) {
				out.push({ kind: "wake_parent", reason: `invalid_writes:${t.id}` });
				continue;
			}
			const myHot = hotHits(t.writes, hot);
			const conflicts = active.some(
				(a) =>
					a.id !== t.id &&
					((a.writes.length > 0 && t.writes.length > 0 && writesMayOverlap(a.writes, t.writes)) ||
						a.hot.some((h) => myHot.includes(h)) ||
						learnedOverlap(state.stats, a.id, t.id)),
			);
			if (conflicts) continue;
			if (t.kind === "check" && (res.verifyBusy || active.some((a) => a.kind === "check"))) continue;
			const est = estimate(t.role, t.size, state.history);
			// 予算の余裕: 使用済み + 予約 + 見積りが各項目の上限の 60% 以内
			let ample = true;
			if (budget) {
				for (const k of ["usd", "tokens", "ms"] as const) {
					const c = budget[k];
					if (c !== undefined && state.used[k] + reserved[k] + est[k] > 0.6 * c) ample = false;
				}
			}
			// 競争の候補は 1 つの見積りが予算の 15% 以下
			let cheap = true;
			if (budget) for (const k of ["usd", "tokens", "ms"] as const) if (budget[k] !== undefined && est[k] > 0.15 * (budget[k] as number)) cheap = false;
			const group = t.group !== undefined && !tasks.some((o) => o.id !== t.id && o.group === t.group && !TERMINAL.includes(o.state) && writesMayOverlap(o.writes, t.writes));
			const contractTask = t.contract === undefined ? undefined : byId.get(t.contract);
			const input: StrategyInput = {
				kind: t.kind,
				overlap: false,
				size: t.size,
				upstream: spec ? "running" : "none",
				risk: t.risk ?? "none",
				hot: myHot.length > 0,
				free,
				ready: Math.max(1, readyRo),
				budget: ample ? "ample" : "tight",
				fail,
				group,
				contract: contractTask?.state === "done",
				uncertain: (!!t.uncertain || (t.failures ?? 0) >= 2) && cheap,
				accept: !!t.accept,
				pipeline: !!t.pipeline,
				disabled: dis,
			};
			const ch = select(input);
			if (ch.degree <= 0) continue;
			// 実行中の上流を待つ候補は、見込みの方式のときだけ起動する (それ以外は上流の完了を待つ)
			if (spec && ch.method !== "speculative") continue;
			// 直列: 他の編集と同時に走らせない (writes・hot の競合は上で除外済み。R4 の境界・R8・R9)
			const alone = ch.method === "serial" && ch.rule !== "R1" && !(ch.rule === "R4" && input.risk !== "boundary");
			if (alone && active.some((a) => a.kind === "edit")) continue;
			// 方式ごとの並列度
			const sameMethod = active.filter((a) => a.method === ch.method);
			if (ch.method === "shared" && sameMethod.filter((a) => a.group === t.group).length >= ch.degree) continue;
			if ((ch.method === "worktree" || ch.method === "shared") && fail === "mid" && sameMethod.length >= Math.max(1, Math.ceil(cap / 2))) continue;
			// 見込みの投機予算 (予算が無いときは同時 1 つ)
			if (ch.method === "speculative") {
				let okSpec = budget ? true : specCount < 1;
				if (budget) {
					for (const k of ["usd", "tokens", "ms"] as const) {
						const c = budget[k];
						if (c !== undefined && specReserved[k] + est[k] > specFraction * c) okSpec = false;
					}
				}
				if (!okSpec) continue;
			}
			const n = ch.method === "race" ? Math.min(ch.degree, free) : 1;
			if (!canReserve(budget, state.used, reserved, scale(est, n))) {
				budgetBlocked = true;
				continue;
			}
			const specTag = ch.method === "speculative" && t.contract !== undefined ? { contract: t.contract, rev: state.contractRevs?.[t.contract] ?? 0 } : undefined;
			for (let v = 0; v < n; v++) {
				const a: Action = {
					kind: "start",
					task: t.id,
					strategy: ch.method,
					isolation: ch.isolation,
					reserve: { ...est },
					degree: ch.degree,
					verify: ch.verify,
					why: `${ch.rule}: ${ch.why}`,
				};
				if (n > 1) a.variant = v;
				if (specTag) a.speculative = specTag;
				out.push(a);
			}
			free -= n;
			reserved = addMoney(reserved, scale(est, n));
			if (specTag) {
				specReserved = addMoney(specReserved, est);
				specCount += 1;
			}
			active.push({ id: t.id, kind: t.kind, writes: t.writes, hot: myHot, group: t.group, method: ch.method });
			startedHere.push(t.id);
		}
	}

	// ── 起こす ──
	if (startedHere.length === 0 && activeRuns.length === 0) {
		const unfinished = state.tasks.filter((t) => !TERMINAL.includes(t.state));
		// 全部が終端のとき: 失敗した task があれば failed (all_done は done / skipped / cancelled だけのとき)
		if (state.tasks.length > 0 && unfinished.length === 0) {
			out.push({ kind: "wake_parent", reason: state.tasks.some((t) => t.state === "failed") ? "failed" : "all_done" });
		}
		else if (budgetBlocked) out.push({ kind: "wake_parent", reason: "budget" });
		else if (
			!blocked &&
			unfinished.length > 0 &&
			!unfinished.some((t) => t.state === "waiting" || t.state === "checking" || t.state === "running") &&
			!out.some((a) => a.kind === "wake_parent")
		) {
			// 未承認の task (台帳が proposed に落としたもの) が残っているなら、利用者の承認待ち。無ければ行き詰まり
			out.push({ kind: "wake_parent", reason: unfinished.some((t) => t.state === "proposed") ? "awaiting_approval" : "stuck" });
		}
	}
	if (out.length === 0) out.push({ kind: "none" });
	return out;
}
