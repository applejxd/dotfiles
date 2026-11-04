// 調停 (settle.ts) へ渡す snapshot の組み立てと、勝った提案を元の拡張へ知らせる journal の tap。
// 純関数 (pi の API・fs なし)。入力が欠けていたり壊れていたりしたら、継続しない側 (無効・圧縮中扱い) に倒す。
// 各拡張 (autocheckpoint.ts・todo) の生の状態は呼び出し側 (index.ts) が写して渡す。see docs/spec/work/settle.md
import type { SettleDeps, SettleSnapshot } from "./settle.ts";

export type RawPhase = "idle" | "saving" | "compacting";

/** autocheckpoint.ts の checkpointSnapshot() の形 */
export interface CheckpointRaw {
	phase?: unknown;
	percent?: unknown;
	threshold?: unknown;
	cooldown?: unknown;
	disabled?: unknown;
	llmStep?: unknown;
	prompt?: unknown;
}

/** globalThis.__piTodoSnapshot?.() の形 (ラベルは「#1 文面」の短い形) */
export interface TodoRaw {
	disabled?: unknown;
	doing?: unknown;
	blocked?: unknown;
	queued?: unknown;
	nudged?: unknown;
	nudgedWaiting?: unknown;
}

/** 台帳の投影 (runtime が無ければ渡さない = 空) */
export interface LedgerRaw {
	failed?: unknown;
	parentStep?: unknown;
	newUserWait?: unknown;
}

export interface SnapshotInput {
	checkpoint?: CheckpointRaw;
	todo?: TodoRaw;
	ledger?: LedgerRaw;
	streak?: unknown;
	maxStreak?: unknown;
}

/** 連続継続の既定の上限。streak は数えない (今は 0 固定) ので、従来どおり上限には当たらない */
export const DEFAULT_MAX_STREAK = 5;
export const DEFAULT_THRESHOLD = 80;
const PHASES: readonly string[] = ["idle", "saving", "compacting"];

const bool = (v: unknown): boolean => v === true;
const count = (v: unknown): number => (typeof v === "number" && Number.isFinite(v) && v > 0 ? Math.floor(v) : 0);
const labels = (v: unknown): string[] => (Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : []);

/** 各拡張の生の状態から、調停の snapshot を組む */
export function buildSnapshot(inp: SnapshotInput | undefined): SettleSnapshot {
	const i = inp ?? {};
	const c = i.checkpoint;
	const t = i.todo;
	const l = i.ledger;
	// 未知の phase は「圧縮中」(継続しない) に倒す
	const phase = c === undefined ? "idle" : typeof c.phase === "string" && PHASES.includes(c.phase) ? (c.phase as RawPhase) : "compacting";
	const percent = typeof c?.percent === "number" && Number.isFinite(c.percent) ? c.percent : null;
	const threshold = typeof c?.threshold === "number" && c.threshold > 0 && c.threshold <= 100 ? c.threshold : DEFAULT_THRESHOLD;
	const maxStreak = typeof i.maxStreak === "number" && Number.isFinite(i.maxStreak) && i.maxStreak > 0 ? i.maxStreak : DEFAULT_MAX_STREAK;
	const streak = typeof i.streak === "number" && Number.isFinite(i.streak) && i.streak >= 0 ? i.streak : 0;
	return {
		phase,
		compacting: phase === "compacting",
		streak,
		maxStreak,
		budgetExhausted: false,
		checkpoint: {
			percent,
			threshold,
			cooldown: bool(c?.cooldown),
			llmStep: c?.llmStep === undefined ? true : bool(c.llmStep),
			disabled: c === undefined ? true : bool(c.disabled), // 拡張が無い・未登録なら提案しない
			prompt: typeof c?.prompt === "string" ? c.prompt : "",
		},
		todo: {
			disabled: t === undefined ? true : bool(t.disabled),
			doing: labels(t?.doing),
			blocked: labels(t?.blocked),
			queued: labels(t?.queued),
			nudged: bool(t?.nudged),
			nudgedWaiting: bool(t?.nudgedWaiting),
		},
		goal: { active: false, claim: false, stall: false, unapproved: 0 }, // /goal の配線は別 feature
		children: { failed: count(l?.failed), parentStep: bool(l?.parentStep), newUserWait: bool(l?.newUserWait) },
	};
}

/** 勝った提案を元の拡張へ知らせる口 */
export interface WinHooks {
	/** autocheckpoint の保存の指示が勝った (phase を saving へ) */
	onSaving(): void;
	/** todo のリマインドが勝った (二重のリマインドを防ぐ旗を立てる) */
	onTodo(which: "nudged" | "nudgedWaiting"): void;
	/** その時点の todo の生の状態 (どちらの旗かを決める) */
	todo(): TodoRaw | undefined;
}

type Emit = (type: any, data?: Record<string, unknown>, node?: string) => void;

/**
 * settle の journal.emit を包み、勝った提案 (data.by = customType) を拡張へ知らせる。
 * 元の emit が無くても動く。例外は握りつぶす (効果の失敗で本体を止めない)。
 */
export function tapJournal(inner: { emit: Emit } | undefined, hooks: WinHooks): { emit: Emit } {
	return {
		emit(type, data, node) {
			try {
				if (type === "settle" && data) {
					if (data.by === "autocheckpoint") hooks.onSaving();
					else if (data.by === "todo-reminder") {
						const doing = labels(hooks.todo()?.doing);
						hooks.onTodo(doing.length > 0 ? "nudged" : "nudgedWaiting");
					}
				}
			} catch {
				/* 知らせの失敗で本体を止めない */
			}
			try {
				inner?.emit(type, data, node);
			} catch {
				/* 観測の失敗で本体を止めない */
			}
		},
	};
}

/** 配線の部品 (index.ts が実物を、試験が偽物を渡す) */
export interface WireParts {
	checkpointSnapshot(): CheckpointRaw;
	checkpointExec: {
		compact(): void;
		cancel(): void;
		markSaving(): void;
		notify(kind: "silent" | "line" | "alert", text: string): void;
	};
	/** globalThis.__piTodoSnapshot?.()。markNudged を持つ */
	todoSnapshot(): (TodoRaw & { markNudged?: (which: "nudged" | "nudgedWaiting") => void }) | undefined;
	/** 起床 (pi.sendUserMessage か triggerTurn の 1 か所だけ) */
	wake(prompt: string): void;
	ledger?(): LedgerRaw | undefined;
	/** 観測の journal (任意) */
	journal?: { emit: Emit };
}

/** registerSettle に渡す deps を組む */
export function makeSettleDeps(p: WireParts): SettleDeps {
	const todo = () => {
		try {
			return p.todoSnapshot();
		} catch {
			return undefined;
		}
	};
	return {
		snapshot: () => {
			let ledger: LedgerRaw | undefined;
			try {
				ledger = p.ledger?.();
			} catch {
				ledger = undefined;
			}
			return buildSnapshot({ checkpoint: p.checkpointSnapshot(), todo: todo(), ledger });
		},
		exec: {
			wake: (prompt) => p.wake(prompt),
			notify: (kind, text) => p.checkpointExec.notify(kind, text),
			checkpoint: (action) => (action === "cancel" ? p.checkpointExec.cancel() : p.checkpointExec.compact()),
		},
		journal: tapJournal(p.journal, {
			onSaving: () => p.checkpointExec.markSaving(),
			onTodo: (which) => todo()?.markNudged?.(which),
			todo,
		}),
	};
}
