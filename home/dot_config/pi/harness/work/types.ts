// 作業台帳 (work ledger) の型。pi の API に依存しない純粋な型だけを置く (reducer・store・digest・調停・スケジューラが共有する契約)。
// 台帳は追記専用のイベントログで、状態はその畳み込み (reducer) で導く。詳細: .tmp/keep/plan/work-ledger.md (B・C・D・G 節)
// この型を変えるときは、依存する feature (work-core・work-store・work-digest・work-sched・work-journal) を同時に直す。

/** 金額・トークン・時間の組。階層で合算する (子・評価役・計画の使用量を 1 か所に集める)。すべて 0 以上。 */
export interface Money {
	usd: number;
	tokens: number;
	ms: number;
}

export type Kind = "goal" | "task" | "run" | "check" | "integrate" | "wait";

/** task の状態。遷移は transitions.ts の表が唯一の定義 */
export type TaskState = "proposed" | "ready" | "running" | "waiting" | "checking" | "done" | "failed" | "blocked" | "cancelled" | "skipped";
/** run (子の 1 回の実行) の状態。children.ts の 6 分類 + lost (プロセスが消えた) */
export type RunState = "reserved" | "started" | "done" | "blocked" | "failed" | "limit" | "aborted" | "lost";
/** goal の状態 */
export type GoalState = "draft" | "planned" | "active" | "paused" | "done" | "cancelled";
export type NodeState = TaskState | RunState | GoalState;

/** 待ち先。run・job・merge は事実の観測で自動解除する。user は利用者のイベントでしか解除しない (待ちを機械で埋めない) */
export interface WaitOn {
	on: "run" | "job" | "merge" | "user" | "time";
	ref: string;
	since: number;
	/** 事実の観測で自動解除するか (user は常に false) */
	auto: boolean;
	/** user 待ちのときに利用者へ出す 1 行 (46 桁以内) */
	prompt?: string;
}

/** 注釈。追記のみ (更新・削除のイベントは無い)。1 つのノードに複数の子が付けられる */
export interface Note {
	by: "user" | "llm" | `run:${string}`;
	at: number;
	/** 300 字以内 */
	text: string;
}

/** ゴール (台帳) の所有。1 つのゴールを駆動できる会話は 1 つだけ */
export interface Lease {
	holder: string;
	pid: number;
	startedAt: number;
	heartbeat: number;
}

export interface Node {
	id: string;
	kind: Kind;
	parent?: string;
	/** 1 行 (40 字前後)。詳細は notes と evidence へ */
	title: string;
	state: NodeState;
	/** 依存 (これらが全部 done になるまで ready にならない)。循環は拒否する */
	after: string[];
	/** 書き込み集合 (glob)。実行中の task どうしで互いに素でなければならない。run・check は親 task の writes を継ぐ */
	writes: string[];
	budget?: Money;
	reserved: Money;
	spent: Money;
	waits: WaitOn[];
	owner?: Lease;
	/** 証拠 (検査の出力・差分・行数・子の全文へのパス) の id */
	evidence: string[];
	notes: Note[];
	/** 種類ごとの追加項目 (role・agent・model・isolation・commit_message など。reducer は中身を解釈しない) */
	attrs: Record<string, unknown>;
}

/** 台帳に載るイベント。aux が真のものは観測用で、reducer は状態に使わない (journal と台帳は 1 本のログ) */
export type EventType =
	| "goal.created"
	| "plan.proposed"
	| "plan.approved"
	| "node.added"
	| "edge.added"
	| "edge.rejected"
	| "run.reserved"
	| "run.started"
	| "run.usage"
	| "run.ended"
	| "check.result"
	| "wait.opened"
	| "wait.resolved"
	| "note.appended"
	| "budget.adjusted"
	| "verdict"
	| "goal.paused"
	| "goal.resumed"
	| "goal.done"
	| "lease.acquired"
	| "lease.released"
	| "lease.expired"
	// 観測用 (aux)
	| "notice"
	| "resource.429"
	| "settle"
	| "strategy"
	| "tool.call"
	| "session.start";

/** 利用者だけが出せるイベント (モデルの tool 呼び出しからは出せない。不変条件 I10) */
export const USER_ONLY_EVENTS: readonly EventType[] = ["plan.approved", "budget.adjusted", "goal.resumed"];

export interface LedgerEvent {
	/** 追記時刻 (ms) */
	ts: number;
	/** 1 から連番。欠番は不変条件違反 (I9) */
	seq: number;
	type: EventType;
	/** 対象のノード (無いイベントもある) */
	node?: string;
	/** イベント固有の内容。型の細目は work-core の events.ts が持つ */
	data: Record<string, unknown>;
	/** 観測用。reducer は無視する */
	aux?: boolean;
}

/** 追記するイベント (seq と ts は store が付ける) */
export type NewEvent = Omit<LedgerEvent, "seq" | "ts">;

/** 永続の読み出し結果。壊れた行は黙って捨てず、回復の種類を返す */
export interface LoadResult {
	events: LedgerEvent[];
	/** 末尾の途中の行を切り詰めた (torn write からの回復) */
	recovered?: boolean;
	/** 途中の破損を隔離した (読み取り専用に落とす。alert する) */
	degraded?: { quarantined: string; reason: string };
}

/** 台帳の永続 (work-store が実装する)。追記は ack 後に fsync 済み */
export interface LedgerStore {
	/** 1 件追記して seq を返す。2 人目の書き手は拒否する (捨てない) */
	append(ev: NewEvent): Promise<LedgerEvent>;
	load(): Promise<LoadResult>;
	/** ゴールの駆動権。取れなければ null (読み取り専用で開く) */
	acquireLease(holder: string, pid: number): Promise<Lease | null>;
	heartbeat(): Promise<void>;
	releaseLease(): Promise<void>;
}

// ── 通知と表示 (Digest) ──────────────────────────────────────────

export type NoticeLevel = "ok" | "warn" | "error";

/** 子・ジョブ・検査の結果の要約。モデルへの本文・畳んだ 1 行・パネルの行・`/goal log` を、すべてここから導く (文面のずれを構造で防ぐ) */
export interface Digest {
	/** run の id (r12 など) */
	id: string;
	node: string;
	role: string;
	title: string;
	status: "done" | "failed" | "blocked" | "limit" | "aborted" | "lost";
	level: NoticeLevel;
	/** 所要 (ms) */
	dur: number;
	usd: number;
	/** 200 字以内。子の最終メッセージの「結論」節の先頭 (追加の LLM 呼び出しは無し) */
	summary: string;
	checks: { name: string; ok: boolean; detail: string }[];
	/** 形式違反・申告と実測の差など */
	warnings: string[];
	paths: { result: string; evidence: string[] };
	next?: string;
}

/** モデルへの本文の上限 (字)。失敗・警告があるときは 1,000 */
export const MODEL_TEXT_LIMIT = 600;
export const MODEL_TEXT_LIMIT_FAILURE = 1000;
/** 畳んだ 1 行の既定の幅 (桁。全角は 2 桁) */
export const LINE_WIDTH = 46;
