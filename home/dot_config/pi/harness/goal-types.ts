// `/goal` の型 (契約)。純関数の goal-core.ts・評価役・配線が共通で参照する。pi の API には依存しない。
// 小さく安定させる: 型を変えると他の feature が壊れるので、足すときは任意の項目にする。
// see docs/spec/guard/pi-extensions.md (配線の後に仕様を書く)

/** 目標の状態。done・cleared は復元しない */
export type GoalStatus = "active" | "paused" | "done";

/** 一時停止の理由 */
export type PauseReason =
	| "user"
	| "input"
	| "interrupted"
	| "restored"
	| "rounds"
	| "minutes"
	| "tokens"
	| "stalled"
	| "blocked"
	| "unapproved"
	| "run-error"
	| "eval-failed";

/** 予算。回数と時間は常に有限 (無制限は受け付けない)。tokens は任意 */
export interface Budget {
	rounds: number;
	minutes: number;
	tokens?: number;
}

export type VerdictKind = "done" | "continue" | "blocked";

export interface GoalState {
	v: 1;
	id: string;
	/** 目標の原文 (全文) */
	text: string;
	status: GoalStatus;
	pause?: { reason: PauseReason; detail?: string };
	budget: Budget;
	/** 今の予算の消費。resume で 0 に戻る */
	used: { rounds: number; runMs: number; tokens: number; evalCalls: number; evalTokens: number };
	/** 通算。減らない */
	lifetime: { rounds: number; tokens: number; evalCalls: number; evalTokens: number; resumes: number };
	/** 連続の停滞の数。resume で 0 に戻る */
	counters: { noTool: number; same: number; unapproved: number; evalFail: number; sameReason: number };
	lastTextHash?: string;
	lastReasonHash?: string;
	lastVerdict?: { verdict: VerdictKind; reason: string; at: number };
	/** 真なら、review の実施が無いと完了にしない */
	audit: boolean;
	createdAt: number;
	updatedAt: number;
}

/** 永続する破棄の印 (`goal-state` エントリの data) */
export interface GoalCleared {
	v: 1;
	cleared: true;
	id: string;
}

/** assistant の最終行の申告 */
export interface Claim {
	kind: "complete" | "blocked";
	detail: string;
}

/** 直近の境界以降の 1 回の run の集計 */
export interface RunFacts {
	toolCalls: number;
	/** `not approved:` で始まる tool 結果の数 */
	unapproved: number;
	/** 最後の assistant メッセージの text */
	text: string;
	/** usage の合計 (input + output。キャッシュ分は含めない) */
	tokens: number;
	claim: Claim | null;
}

export type OutcomeKind = "completed" | "error" | "aborted";
export type RunMode = "tui" | "rpc" | "print" | "json";

/** `agent_before_settle` の時点の事実。時刻は呼び出し側が渡す */
export interface SettleFacts {
	mode: RunMode;
	outcome: OutcomeKind;
	/** 圧縮中 (autocheckpoint・compactDefer) */
	compacting: boolean;
	planMode: boolean;
	/** `hasPendingMessages()` */
	pending: boolean;
	/** 背景の子・ジョブの数 */
	bgBusy: number;
	run: RunFacts;
	/** この run の作業時間 (ms)。待ち時間は含めない */
	runMs: number;
	now: number;
}

export type EvalWhy = "claim" | "stall";

export type SettleDecision =
	| { kind: "skip"; why: string }
	| { kind: "pause"; reason: PauseReason; detail?: string }
	| { kind: "continue"; reason?: string }
	| { kind: "evaluate"; why: EvalWhy; claim: Claim | null; detail?: string }
	| { kind: "done" };

/** 評価役の判定 */
export interface Verdict {
	verdict: VerdictKind;
	reason: string;
}

/** `applyVerdict` へ渡す事実 */
export interface VerdictFacts {
	/** review の実施が transcript にあるか (audit のとき) */
	auditSeen: boolean;
	/** 何のための評価か (省略は claim) */
	why?: EvalWhy;
	/** 評価役の呼び出しで使ったトークン */
	evalTokens?: number;
}

export interface SettleConfig {
	evalMode: "claim" | "every";
}

export type GoalCommand =
	| { kind: "set"; text: string; budget: Partial<Budget>; audit: boolean }
	| { kind: "status" | "pause" | "resume" | "clear" }
	| { kind: "draft"; text: string }
	| { kind: "budget"; budget: Partial<Budget> }
	| { kind: "error"; message: string };

export interface NewGoalOpts {
	audit?: boolean;
	/** 省略時は now から決定的に作る */
	id?: string;
}

/** セッションの branch のエントリ (getBranch() の要素)。形は最小限の仮定 */
export type BranchEntry = any;
