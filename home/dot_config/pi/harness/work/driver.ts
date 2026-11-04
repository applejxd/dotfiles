// 並列実行基盤のドライバ: スケジューラ (sched.next) の Action を、台帳のイベントと子の起動・停止の効果に変換し、
// 子の完了・失敗・429 を台帳へ戻す。純関数 (pi・fs・時計・乱数なし。時刻と乱数は引数)。入力は変更しない。決定的。
// 子の起動・停止は注入する Spawner の型だけ定義する (実体は配線の feature が spawnChild を包む)。see docs/spec/work/driver.md
import { aimdStep, is429 } from "./aimd.ts";
import type { AimdConfig, ProviderState } from "./aimd.ts";
import { schedStateOf, digestInputOf } from "./adapt.ts";
import type { DigestInput } from "./digest.ts";
import { makeAux, makeEvent, NOTE_MAX } from "./events.ts";
import type { RunEndStatus } from "./events.ts";
import { reduce, rootGoalId } from "./reduce.ts";
import type { LedgerState } from "./reduce.ts";
import { addMoney, canReserve, ZERO } from "./reserve.ts";
import type { Budget } from "./reserve.ts";
import { next as schedNext } from "./sched.ts";
import type { Action, Resources } from "./sched.ts";
import type { Isolation, Method, Stats } from "./strategy.ts";
import type { Money, NewEvent } from "./types.ts";

/** 子に渡す起動の仕様。workTool は常に false (子には work ツールを渡さず、台帳に書かせない) */
export interface SpawnSpec {
	runId: string;
	task: string;
	role: string;
	strategy: Method;
	isolation: Isolation;
	/** isolation が worktree のときの名前 (task の id 由来) */
	worktree?: string;
	prompt: string;
	reserve: Money;
	workTool: false;
	speculative?: { contract: string; rev: number };
	variant?: number;
}

/** ドライバが返す効果。実行は Spawner (配線) が行う */
export type Effect =
	| ({ kind: "spawn" } & SpawnSpec)
	| { kind: "steer"; run: string; text: string }
	| { kind: "abort"; run: string; reason: string }
	| { kind: "pause_provider"; until: number; reason: string }
	| { kind: "resume_provider" }
	| { kind: "wake"; reason: string };

/** 子の起動・停止の注入口 (型だけ。実体は spawnChild と Jobs を包む) */
export interface Spawner {
	spawn(spec: SpawnSpec): { runId: string; pid: number } | Promise<{ runId: string; pid: number }>;
	steer(runId: string, text: string): void | Promise<void>;
	abort(runId: string, reason: string): void | Promise<void>;
}

/** spawner の現況 (読み取りだけ)。live は今走っている run の id */
export interface SpawnerView {
	live: readonly string[];
}

/** 呼び出し側が持ち回る記憶 (台帳には載らない通知の重複防止)。tick が新しい値を返す */
export interface Memo {
	/** wrap-up の steer を出し済みの run */
	steered: string[];
	/** abort を出し済みの run */
	aborting: string[];
	/** pause_provider を通知済み */
	announced: boolean;
	/** 直前に起こした理由 (同じ理由を繰り返し起こさない) */
	lastWake: string;
	/** run ごとの最後の出力時刻 (台帳の attrs に書く経路が無いので記憶で持つ。stall の見張りに使う) */
	outputAt: Record<string, number>;
}

export const emptyMemo = (): Memo => ({ steered: [], aborting: [], announced: false, lastWake: "", outputAt: {} });

export interface TickCtx {
	now: number;
	res: Resources;
	spawner?: SpawnerView;
	/** 省略時は active な goal の予算 */
	budget?: Budget;
	aimd: ProviderState;
	memo?: Memo;
	stats?: Stats;
	/** lease の保持者 (I8)。省略時は付けない */
	holder?: string;
}

export interface TickResult {
	events: NewEvent[];
	effects: Effect[];
	memo: Memo;
	/** 台帳の門が拒否した start (スケジューラと台帳の食い違い。起動しない) */
	rejected: { task: string; reason: string }[];
	actions: Action[];
}

export interface RunResult {
	status: "done" | "failed" | "aborted" | "limit";
	answer?: string;
	/** 子の使用量の累計 (評価役を含む)。台帳に記録済みの分との差だけを加算する */
	usage: Money;
	error?: string;
	/** 完了のとき、検査の結果をすぐ台帳へ入れる (省略時は checking のまま。onChecked で入れる) */
	check?: { name: string; ok: boolean; detail?: string };
}

export interface FinishCtx {
	now: number;
	aimd: ProviderState;
	/** 429 のバックオフ用の乱数 (0 以上 1 未満。省略時 0.5) */
	rand?: number;
	cfg?: AimdConfig;
	holder?: string;
}

export interface FinishResult {
	events: NewEvent[];
	/** events を畳んだ後の台帳 */
	state: LedgerState;
	aimd: ProviderState;
	/** 429 で落ちた (失敗に数えず再キューした) */
	rateLimited: boolean;
	/** 失敗の理由。失敗・中断・上限のときは必ず非 null (failure_never_null) */
	error: string | null;
	digestInput: DigestInput | null;
}

const cmpStr = (a: string, b: string): number => (a < b ? -1 : a > b ? 1 : 0);
const num = (n: number): number => (Number.isFinite(n) ? Math.max(0, n) : 0);
const mk = (type: Parameters<typeof makeEvent>[0], node: string, data: unknown, holder?: string): NewEvent =>
	makeEvent(type, node, data as never, "system", holder !== undefined ? { holder } : {});

/** 台帳へ当てる (入力は変更しない)。seq と ts はここで仮に付ける (本物は store が付ける) */
export function applyEvents(state: LedgerState, events: readonly NewEvent[], now: number): LedgerState {
	let s = state;
	for (const e of events) s = reduce(s, { ...e, seq: s.seq + 1, ts: now });
	return s;
}

/** 未使用の run id (r1, r2, ...)。決定的 */
function freshRunId(state: LedgerState, taken: ReadonlySet<string>): string {
	let n = 1;
	for (const x of state.nodes.values()) if (x.kind === "run") n++;
	for (;;) {
		const id = `r${n}`;
		if (!state.nodes.has(id) && !taken.has(id)) return id;
		n++;
	}
}

function promptOf(state: LedgerState, taskId: string, role: string): string {
	const t = state.nodes.get(taskId);
	const lines = [`# ${t?.title ?? taskId}`, `役割: ${role}`];
	if (t && t.writes.length > 0) lines.push(`書き込み範囲: ${t.writes.join(", ")}`);
	for (const n of t?.notes ?? []) if (n.by === "user" || n.by === "llm") lines.push(`- ${n.text}`);
	lines.push("work ツールは使えない。台帳には書かず、最後に「## 結論」節で結果を報告せよ。");
	return lines.join("\n");
}

/** 1 回の計算: next() の Action を台帳のイベントと効果に変換する。台帳の門 (reduce) を通らない start は出さない */
export function tick(state: LedgerState, ctx: TickCtx): TickResult {
	const memo0 = ctx.memo ?? emptyMemo();
	const live = ctx.spawner ? new Set(ctx.spawner.live) : undefined;
	const steered = new Set(memo0.steered);
	const aborting = new Set(memo0.aborting);
	const ss = schedStateOf(state, { now: ctx.now, resources: ctx.res, provider: ctx.aimd, budget: ctx.budget, stats: ctx.stats });
	// 見積りは adapt が attrs.est から作る。台帳の attrs に無い記憶 (steer 済み・最後の出力) をここで重ねる
	for (const r of ss.runs) {
		if (steered.has(r.id)) r.steered = r.stallSteered = true;
		const out = memo0.outputAt?.[r.id];
		if (out !== undefined && out > (r.lastOutputAt ?? -1)) r.lastOutputAt = out;
	}
	ss.providerAnnounced = memo0.announced;
	const actions = schedNext(ss, ctx.res, ctx.now);

	const events: NewEvent[] = [];
	const effects: Effect[] = [];
	const rejected: { task: string; reason: string }[] = [];
	let work = state;
	let announced = memo0.announced;
	const wakes: string[] = [];
	const taken = new Set<string>();
	const goalOf = (): string | undefined => [...state.nodes.values()].find((n) => n.kind === "goal" && n.state === "active")?.id;
	let reserved: Money = { ...ZERO };
	for (const r of ss.runs) if (r.state === "reserved" || r.state === "started") reserved = addMoney(reserved, r.reserve);

	for (const a of actions) {
		switch (a.kind) {
			case "steer":
				if (!steered.has(a.run)) {
					steered.add(a.run);
					effects.push({ kind: "steer", run: a.run, text: a.text });
				}
				break;
			case "abort":
				if (!aborting.has(a.run)) {
					aborting.add(a.run);
					effects.push({ kind: "abort", run: a.run, reason: a.reason });
				}
				break;
			case "pause_provider":
				announced = true;
				events.push(makeAux("resource.429", { status: 429, until: a.until, reason: a.reason }));
				effects.push({ kind: "pause_provider", until: a.until, reason: a.reason });
				break;
			case "resume_provider":
				announced = false;
				events.push(makeAux("notice", { kind: "resume_provider" }));
				effects.push({ kind: "resume_provider" });
				break;
			case "wake_parent": {
				wakes.push(a.reason);
				if (a.reason === "provider_exhausted") {
					const g = goalOf();
					const gn = g ? work.nodes.get(g) : undefined;
					if (g && gn?.state === "active") {
						const ev = mk("goal.paused", g, { reason: "429 が続いた (利用上限)" }, ctx.holder);
						try {
							work = applyEvents(work, [ev], ctx.now);
							events.push(ev);
						} catch {
							/* 既に止まっている等は無視 */
						}
					}
				}
				break;
			}
			case "start": {
				const t = state.nodes.get(a.task);
				const role = typeof t?.attrs.role === "string" && t.attrs.role ? t.attrs.role : "worker";
				// 予算の二重確認 (スケジューラの予約とは別に、ここでも使用済み + 予約 + 見積りを見る)
				if (!canReserve(ss.budget, ss.used, reserved, a.reserve)) {
					rejected.push({ task: a.task, reason: "予算を超える" });
					break;
				}
				const runId = freshRunId(work, taken);
				const attrs: Record<string, unknown> = { strategy: a.strategy, isolation: a.isolation, why: a.why, est: { ...a.reserve } };
				if (a.speculative) attrs.speculative = a.speculative;
				if (a.variant !== undefined) attrs.variant = a.variant;
				const ev = mk("run.reserved", runId, { task: a.task, est: a.reserve, attrs }, ctx.holder);
				try {
					work = applyEvents(work, [ev], ctx.now);
				} catch (e) {
					rejected.push({ task: a.task, reason: String((e as Error).message) });
					break;
				}
				taken.add(runId);
				reserved = addMoney(reserved, a.reserve);
				events.push(ev);
				const spawn: Effect = {
					kind: "spawn",
					runId,
					task: a.task,
					role,
					strategy: a.strategy,
					isolation: a.isolation,
					prompt: promptOf(state, a.task, role),
					reserve: { ...a.reserve },
					workTool: false,
				};
				if (a.isolation === "worktree") spawn.worktree = a.task;
				if (a.speculative) spawn.speculative = a.speculative;
				if (a.variant !== undefined) spawn.variant = a.variant;
				effects.push(spawn);
				break;
			}
			case "none":
				break;
		}
	}
	// 同じ理由を繰り返し起こさない
	const wakeKey = [...new Set(wakes)].sort(cmpStr).join("|");
	if (wakeKey !== memo0.lastWake && wakeKey !== "") for (const r of [...new Set(wakes)].sort(cmpStr)) effects.push({ kind: "wake", reason: r });
	const memo: Memo = {
		steered: [...steered].filter((id) => !live || live.has(id)).sort(cmpStr),
		aborting: [...aborting].filter((id) => !live || live.has(id)).sort(cmpStr),
		announced,
		lastWake: wakeKey,
		outputAt: Object.fromEntries(Object.entries(memo0.outputAt ?? {}).filter(([id]) => !live || live.has(id))),
	};
	return { events, effects, memo, rejected, actions };
}

/** 子が起動できた: run.started */
export function onSpawned(state: LedgerState, runId: string, pid: number, holder?: string): NewEvent[] {
	const r = state.nodes.get(runId);
	if (!r || r.kind !== "run" || r.state !== "reserved") return [];
	return [mk("run.started", runId, { pid }, holder)];
}

/**
 * 子の出力を受けた: 観測用の aux イベント (台帳の状態には効かない) と、stall の見張り用に記憶した最後の出力時刻を返す。
 * 生きた run 以外は何もしない。台帳の attrs を更新する既存のイベントが無いので、時刻は Memo (outputAt) で持ち回る
 */
export function onOutput(state: LedgerState, runId: string, now: number, memo: Memo = emptyMemo()): { events: NewEvent[]; memo: Memo } {
	const r = state.nodes.get(runId);
	if (!r || r.kind !== "run" || (r.state !== "reserved" && r.state !== "started")) return { events: [], memo };
	return {
		events: [makeAux("notice", { kind: "run.output", run: runId, at: now })],
		memo: { ...memo, outputAt: { ...(memo.outputAt ?? {}), [runId]: now } },
	};
}

/** 子の使用量 (source: child) と評価役の使用量 (eval) を run へ足す。run → task → goal へ合算され、予算に効く */
export function onUsage(state: LedgerState, runId: string, usage: Money, holder?: string): NewEvent[] {
	const r = state.nodes.get(runId);
	if (!r || r.kind !== "run" || r.state !== "started") return [];
	const u = { usd: num(usage.usd), tokens: num(usage.tokens), ms: num(usage.ms) };
	if (u.usd === 0 && u.tokens === 0 && u.ms === 0) return [];
	return [mk("run.usage", runId, { usage: u }, holder)];
}

/** 検査の結果 (task が checking のとき) */
export function onChecked(state: LedgerState, taskId: string, c: { name: string; ok: boolean; detail?: string }, holder?: string): NewEvent[] {
	if (state.nodes.get(taskId)?.state !== "checking") return [];
	return [mk("check.result", taskId, c, holder)];
}

const clip = (s: string, n: number): string => (s.length <= n ? s : `${s.slice(0, n - 1)}…`);

/** 子の終了: run.ended と周辺のイベント。429 は task の失敗に数えず再キューし、AIMD を更新する */
export function onFinished(state: LedgerState, runId: string, result: RunResult, ctx: FinishCtx): FinishResult {
	const run = state.nodes.get(runId);
	if (!run || run.kind !== "run" || (run.state !== "reserved" && run.state !== "started")) {
		return { events: [], state, aimd: ctx.aimd, rateLimited: false, error: null, digestInput: null };
	}
	const h = ctx.holder;
	const task = state.nodes.get(run.parent as string);
	const rateLimited = result.status === "limit" || (result.status === "failed" && is429(result.error ?? ""));
	const status: RunEndStatus = rateLimited ? "limit" : result.status;
	const failed = status !== "done";
	const error = failed ? (result.error && result.error.trim() ? result.error.trim() : `原因不明 (status=${status})`) : null;
	const events: NewEvent[] = [];
	if (run.state === "reserved") events.push(mk("run.started", runId, {}, h));
	const text = failed ? `失敗: ${error}` : (result.answer ?? "").trim();
	if (text) events.push(mk("note.appended", runId, { by: `run:${runId}`, text: clip(text, NOTE_MAX) }, h));
	const delta = {
		usd: num(result.usage.usd - run.spent.usd),
		tokens: num(result.usage.tokens - run.spent.tokens),
		ms: num(result.usage.ms - run.spent.ms),
	};
	events.push(mk("run.ended", runId, { status, usage: delta }, h));
	let s = applyEvents(state, events, ctx.now);
	let aimd = ctx.aimd;
	if (rateLimited) {
		const rand = Math.min(0.999999, Math.max(0, ctx.rand ?? 0.5));
		aimd = aimdStep(aimd, { t: "429", ts: ctx.now, rand }, ctx.cfg);
		const aux = makeAux("resource.429", { status: 429, rand, until: aimd.pausedUntil, run: runId });
		events.push(aux);
		s = applyEvents(s, [aux], ctx.now);
		if (s.nodes.get(task?.id ?? "")?.state === "failed") {
			const v = mk("verdict", task?.id as string, { verdict: "retry", reason: "429 のため再キュー (失敗に数えない)" }, h);
			events.push(v);
			s = applyEvents(s, [v], ctx.now);
		}
	} else if (status === "done") {
		aimd = aimdStep(aimd, { t: "success", ts: ctx.now }, ctx.cfg);
		if (result.check) {
			const c = mk("check.result", task?.id as string, result.check, h);
			events.push(c);
			s = applyEvents(s, [c], ctx.now);
		}
	}
	return { events, state: s, aimd, rateLimited, error, digestInput: digestInputOf(s, runId) };
}

/**
 * 台帳の全 run を調べ、このドライバが知らない生きた run を閉じるイベント。live は spawner の現況。
 * started (プロセスが消えた等) は lost で、起動されないまま残った reserved は aborted で閉じる (予約を解放。task が failed になれば retry で戻す)
 */
export function reconcile(state: LedgerState, view: SpawnerView, holder?: string): NewEvent[] {
	const live = new Set(view.live);
	const out: NewEvent[] = [];
	let s = state;
	for (const n of [...state.nodes.values()].sort((a, b) => cmpStr(a.id, b.id))) {
		if (n.kind !== "run" || (n.state !== "started" && n.state !== "reserved") || live.has(n.id)) continue;
		if (rootGoalId(state.nodes, n.id) === undefined) continue;
		if (n.state === "reserved") {
			const evs = [
				mk("note.appended", n.id, { by: `run:${n.id}`, text: "起動されなかった予約 (回収)" }, holder),
				mk("run.ended", n.id, { status: "aborted" }, holder),
			];
			s = applyEvents(s, evs, 0);
			out.push(...evs);
			if (n.parent && s.nodes.get(n.parent)?.state === "failed") {
				const v = mk("verdict", n.parent, { verdict: "retry", reason: "起動されなかった予約の回収 (失敗に数えない)" }, holder);
				s = applyEvents(s, [v], 0);
				out.push(v);
			}
			continue;
		}
		out.push(mk("note.appended", n.id, { by: `run:${n.id}`, text: "失敗: プロセスが消えた (lost)" }, holder));
		out.push(mk("run.ended", n.id, { status: "lost" }, holder));
	}
	return out;
}
