// 作業台帳の遷移の唯一の表。goal・task・run の各状態 × イベント (× 変種) → 次の状態と副作用の種類。
// reducer (reduce.ts)・試験・docs が同じ表を使う。未定義の遷移は TransitionError (黙って無視しない)。仕様: docs/spec/work/ledger.md
import type { EventType, GoalState, Kind, RunState, TaskState } from "./types.ts";

export type TKind = "goal" | "task" | "run";

export const GOAL_STATES: readonly GoalState[] = ["draft", "planned", "active", "paused", "done", "cancelled"];
export const TASK_STATES: readonly TaskState[] = [
	"proposed",
	"ready",
	"running",
	"waiting",
	"checking",
	"done",
	"failed",
	"blocked",
	"cancelled",
	"skipped",
];
export const RUN_STATES: readonly RunState[] = ["reserved", "started", "done", "blocked", "failed", "limit", "aborted", "lost"];
export const STATES: Record<TKind, readonly string[]> = { goal: GOAL_STATES, task: TASK_STATES, run: RUN_STATES };

/** 副作用の種類 (reduce.ts が実装する)。none は状態の変更だけ */
export type Effect =
	| "none"
	| "plan"
	| "approve"
	| "promote"
	| "start"
	| "usage"
	| "end"
	| "evidence"
	| "wait"
	| "resolve"
	| "retry"
	| "verdict"
	| "finish"
	| "edge"
	| "note"
	| "budget"
	| "lease";

export interface Rule {
	kind: TKind;
	from: string;
	on: EventType;
	/** 変種。"*" は変種なし */
	variant: string;
	to: string;
	effect: Effect;
}

export class TransitionError extends Error {
	constructor(message: string) {
		super(message);
		this.name = "TransitionError";
	}
}

/** 表で区別するイベントごとの変種。run.ended は status、verdict は種類、check.result は pass|fail、wait.resolved は残りの待ちと走行中の run */
export const VARIANTS: Partial<Record<EventType, readonly string[]>> = {
	"run.ended": ["done", "blocked", "failed", "limit", "aborted", "lost"],
	"verdict": ["done", "continue", "retry", "block", "cancel", "skip"],
	"check.result": ["pass", "fail"],
	"wait.resolved": ["remain", "live", "idle"],
};

/** 変種を決めるために reducer が状態から集める事実 */
export interface Facts {
	/** 他に開いた待ちが残る */
	waitsRemain: boolean;
	/** reserved|started の run が子にある */
	liveRun: boolean;
}

export const variantOf = (type: EventType, data: Record<string, unknown>, facts: Facts): string => {
	switch (type) {
		case "run.ended":
			return String(data.status);
		case "verdict":
			return String(data.verdict);
		case "check.result":
			return data.ok ? "pass" : "fail";
		case "wait.resolved":
			return facts.waitsRemain ? "remain" : facts.liveRun ? "live" : "idle";
		default:
			return "*";
	}
};

/** check・integrate は task と同じ表に従う。wait は独立のノードにならない (待ちは node.waits) */
export const tkindOf = (kind: Kind): TKind => {
	if (kind === "goal") return "goal";
	if (kind === "run") return "run";
	if (kind === "wait") throw new TransitionError("wait はノードにならない");
	return "task";
};

/** 作成時の task の状態。goal が draft|planned なら proposed (承認で ready へ)、active|paused なら ready。終わった goal へは足せない */
export const initialTaskState = (goal: GoalState): TaskState => {
	if (goal === "draft" || goal === "planned") return "proposed";
	if (goal === "active" || goal === "paused") return "ready";
	throw new TransitionError(`終わった goal (${goal}) へは足せない`);
};

// ── 表 (手書き。from は配列で展開する。"=" は元の状態のまま) ──
export const RULES: Rule[] = [];
const add = (
	kind: TKind,
	from: string | readonly string[],
	on: EventType | readonly EventType[],
	variant: string | readonly string[],
	to: string,
	effect: Effect = "none",
) => {
	for (const f of typeof from === "string" ? [from] : from) {
		for (const o of typeof on === "string" ? [on] : on) {
			for (const v of typeof variant === "string" ? [variant] : variant) {
				RULES.push({ kind, from: f, on: o, variant: v, to: to === "=" ? f : to, effect });
			}
		}
	}
};
const LIVE_GOAL = ["draft", "planned", "active", "paused"];
const OPEN_TASK = ["proposed", "ready", "running", "waiting", "checking", "failed", "blocked"];
const ALL_TASK = TASK_STATES;

// goal: draft → planned → active ⇄ paused → done | cancelled
add("goal", ["draft", "planned"], "plan.proposed", "*", "planned", "plan");
add("goal", "planned", "plan.approved", "*", "active", "approve"); // 利用者専用。proposed の task を ready にする
add("goal", ["active", "paused"], "plan.approved", "*", "=", "approve"); // 再承認 (利用者専用・状態は変えない。未承認の task が無ければ reduce が拒否)
add("goal", "active", "goal.paused", "*", "paused");
add("goal", "paused", "goal.resumed", "*", "active"); // 利用者専用
add("goal", "active", "goal.done", "*", "done", "finish"); // verdict done と全 task の決着が要る (I6)
add("goal", LIVE_GOAL, "verdict", "cancel", "cancelled");
add("goal", "active", "verdict", ["done", "continue"], "=", "verdict");
add("goal", GOAL_STATES, "note.appended", "*", "=", "note");
add("goal", LIVE_GOAL, "budget.adjusted", "*", "=", "budget"); // 利用者専用
add("goal", LIVE_GOAL, ["lease.acquired"], "*", "=", "lease");
add("goal", GOAL_STATES, ["lease.released", "lease.expired"], "*", "=", "lease");
add("goal", LIVE_GOAL, "wait.opened", "*", "=", "wait");
add("goal", LIVE_GOAL, "wait.resolved", ["remain", "live", "idle"], "=", "resolve");

// task (check・integrate も同じ): proposed → ready → running ⇄ waiting → checking → done。failed → ready | blocked。cancelled・skipped
add("task", "proposed", "plan.approved", "*", "ready", "promote"); // goal の承認からの連鎖
add("task", "ready", "run.reserved", "*", "running", "start"); // 依存・writes・予算の門を通ったときだけ
add("task", "running", "run.ended", "done", "checking", "end");
add("task", "running", "run.ended", "blocked", "blocked", "end");
add("task", "running", "run.ended", ["failed", "limit", "aborted", "lost"], "failed", "end");
add("task", "waiting", "run.ended", RUN_ENDED(), "=", "end");
add("task", ["cancelled", "skipped"], "run.ended", RUN_ENDED(), "=", "end"); // 取り消し後に届く run の終了
add("task", "checking", "check.result", "pass", "done", "evidence");
add("task", "checking", "check.result", "fail", "failed", "evidence");
add("task", "running", "wait.opened", "*", "waiting", "wait");
add("task", ["waiting", "failed", "blocked"], "wait.opened", "*", "=", "wait");
add("task", "waiting", "wait.resolved", "remain", "waiting", "resolve");
add("task", "waiting", "wait.resolved", "live", "running", "resolve");
add("task", "waiting", "wait.resolved", "idle", "ready", "resolve"); // 走る run が無ければ再実行へ
add("task", ["failed", "blocked"], "wait.resolved", ["remain", "live", "idle"], "=", "resolve");
add("task", ["failed", "blocked"], "verdict", "retry", "ready", "retry");
add("task", "failed", "verdict", "block", "blocked", "verdict");
add("task", ["proposed", "ready", "running", "waiting", "checking", "failed", "blocked"], "verdict", "cancel", "cancelled");
add("task", ["proposed", "ready"], "verdict", "skip", "skipped");
add("task", ["proposed", "ready"], "edge.added", "*", "=", "edge");
add("task", ALL_TASK, "edge.rejected", "*", "=", "edge");
add("task", ALL_TASK, "note.appended", "*", "=", "note");
add("task", OPEN_TASK, "budget.adjusted", "*", "=", "budget"); // 利用者専用

// run: reserved → started → ended (done | blocked | failed | limit | aborted | lost)
add("run", "reserved", "run.started", "*", "started");
add("run", "started", "run.usage", "*", "started", "usage");
add("run", "started", "run.ended", RUN_ENDED(), "=", "end"); // to は run.ended の変種そのもの (下で上書き)
add("run", "reserved", "run.ended", ["failed", "limit", "aborted", "lost"], "=", "end"); // 開始前の終了は done・blocked にならない
add("run", RUN_STATES, "note.appended", "*", "=", "note");
// run.ended の to は status そのもの
for (const r of RULES) if (r.kind === "run" && r.on === "run.ended") r.to = r.variant;

function RUN_ENDED(): string[] {
	return ["done", "blocked", "failed", "limit", "aborted", "lost"];
}

const INDEX = new Map<string, Rule>();
for (const r of RULES) {
	const key = `${r.kind}|${r.from}|${r.on}|${r.variant}`;
	if (INDEX.has(key)) throw new Error(`遷移表の重複: ${key}`);
	INDEX.set(key, r);
}

export const lookup = (kind: TKind, from: string, on: EventType, variant = "*"): Rule | undefined =>
	INDEX.get(`${kind}|${from}|${on}|${variant}`);

/** 遷移を引く。未定義なら例外 */
export const next = (kind: TKind, from: string, on: EventType, variant = "*"): Rule => {
	const r = lookup(kind, from, on, variant);
	if (!r) throw new TransitionError(`未定義の遷移: ${kind} ${from} --${on}${variant === "*" ? "" : `:${variant}`}-->`);
	return r;
};

/** 表が対象にするイベント (aux と、表を持たない作成系の goal.created・node.added を除く) */
export const TABLE_EVENTS: readonly EventType[] = [...new Set(RULES.map((r) => r.on))];

/** 状態 × イベント × 変種の全セル (総当たりの試験用) */
export const allCells = (): { kind: TKind; from: string; on: EventType; variant: string }[] => {
	const out: { kind: TKind; from: string; on: EventType; variant: string }[] = [];
	for (const kind of ["goal", "task", "run"] as const) {
		for (const from of STATES[kind]) {
			for (const on of TABLE_EVENTS) for (const variant of VARIANTS[on] ?? ["*"]) out.push({ kind, from, on, variant });
		}
	}
	return out;
};
