// 作業台帳のイベントのペイロード (LedgerEvent.data の中身)・検証・作成ヘルパ。pi の API にも fs にも依存しない純関数。
// 型 (types.ts) は契約なので変えず、足りない型はここに置く。仕様: docs/spec/work/ledger.md
import { USER_ONLY_EVENTS } from "./types.ts";
import type { EventType, Money, NewEvent } from "./types.ts";

/** イベントの出所。利用者専用のイベントは "user" でしか出せない (I10)。台帳にはイベントの source 欄として残る */
export type Source = "user" | "model" | "system";

export type WaitKind = "run" | "job" | "merge" | "user" | "time";
export type VerdictKind = "done" | "continue" | "retry" | "block" | "cancel" | "skip";
export type RunEndStatus = "done" | "blocked" | "failed" | "limit" | "aborted" | "lost";

export interface NodeInit {
	kind: "task" | "check" | "integrate";
	parent: string;
	title: string;
	after?: string[];
	writes?: string[];
	budget?: Money;
	attrs?: Record<string, unknown>;
}

/** 種類ごとのペイロード。node (イベントの対象) の意味は各行のコメントのとおり */
export interface Payloads {
	/** node = 新しい goal の id */
	"goal.created": { title: string; budget?: Money; attrs?: Record<string, unknown> };
	/** node = goal。hash は計画の内容の hash */
	"plan.proposed": { hash: string };
	/** node = goal。利用者専用。hash は直近の plan.proposed と一致しなければならない */
	"plan.approved": { hash: string };
	/** node = 新しいノードの id */
	"node.added": { node: NodeInit };
	/** node = from (依存する側)。from.after に to を足す。循環なら edge.rejected になる */
	"edge.added": { from: string; to: string };
	"edge.rejected": { from: string; to: string; reason: string };
	/** node = 新しい run の id。task = 親の task。est = 予約する見積り */
	"run.reserved": { task: string; est: Money; attrs?: Record<string, unknown> };
	"run.started": { pid?: number };
	"run.usage": { usage: Money };
	"run.ended": { status: RunEndStatus; usage?: Money; digestId?: string };
	/** node = task。pass で done、fail で failed */
	"check.result": { name: string; ok: boolean; detail?: string };
	"wait.opened": { wait: { on: WaitKind; ref: string; since: number; auto: boolean; prompt?: string } };
	/** by = 解除した事実の種類。user 待ちは user (かつ source が user) でしか解けない */
	"wait.resolved": { ref: string; by: WaitKind };
	"note.appended": { by: "user" | "llm" | `run:${string}`; text: string };
	/** 利用者専用 */
	"budget.adjusted": { budget: Money };
	"verdict": { verdict: VerdictKind; reason: string };
	"goal.paused": { reason: string };
	/** 利用者専用 */
	"goal.resumed": Record<string, never>;
	"goal.done": Record<string, never>;
	"lease.acquired": { holder: string; pid: number; startedAt?: number };
	"lease.released": { holder: string };
	"lease.expired": { holder: string };
}

/** 観測用 (aux) の種類。reducer は状態に使わず、seq だけ進める */
export const AUX_TYPES: ReadonlySet<EventType> = new Set<EventType>([
	"notice",
	"resource.429",
	"settle",
	"strategy",
	"tool.call",
	"session.start",
]);

export const WAIT_KINDS: readonly WaitKind[] = ["run", "job", "merge", "user", "time"];
export const VERDICTS: readonly VerdictKind[] = ["done", "continue", "retry", "block", "cancel", "skip"];
export const RUN_END_STATUSES: readonly RunEndStatus[] = ["done", "blocked", "failed", "limit", "aborted", "lost"];
export const NOTE_MAX = 300;
export const PROMPT_MAX_WIDTH = 46;

export class EventError extends Error {
	constructor(message: string) {
		super(message);
		this.name = "EventError";
	}
}

export const isAux = (ev: { type: EventType; aux?: boolean }): boolean => ev.aux === true || AUX_TYPES.has(ev.type);

const isObj = (x: unknown): x is Record<string, unknown> => typeof x === "object" && x !== null && !Array.isArray(x);
const isStr = (x: unknown): x is string => typeof x === "string" && x.length > 0;
const isNum = (x: unknown): x is number => typeof x === "number" && Number.isFinite(x);
const strList = (x: unknown): x is string[] => Array.isArray(x) && x.every((s) => isStr(s));

/** 桁数 (ASCII は 1、それ以外は 2) */
export const displayWidth = (s: string): number => {
	let w = 0;
	for (const ch of s) w += (ch.codePointAt(0) ?? 0) > 0x7f ? 2 : 1;
	return w;
};

export const ZERO: Money = { usd: 0, tokens: 0, ms: 0 };

export const isMoney = (x: unknown): x is Money =>
	isObj(x) &&
	["usd", "tokens", "ms"].every((k) => isNum(x[k]) && (x[k] as number) >= 0) &&
	(x.rounds === undefined || (isNum(x.rounds) && x.rounds >= 0));

/**
 * 利用者専用か。user 待ちの解除 (wait.resolved by:"user") も出所は利用者でなければならない。
 * goal の cancel (verdict) は対象の種類 (goal か task か) を知る reducer が拒否する (task の cancel はモデルでも通る)
 */
export const isUserOnly = (type: EventType, data?: Record<string, unknown>): boolean =>
	USER_ONLY_EVENTS.includes(type) || (type === "wait.resolved" && data?.by === "user");

/** ペイロードの形の検証。不正なら理由を返す (問題なければ null) */
export const validatePayload = (type: EventType, d: Record<string, unknown>): string | null => {
	if (!isObj(d)) return "data がオブジェクトでない";
	switch (type) {
		case "goal.created":
			if (!isStr(d.title)) return "title が必要";
			if (d.budget !== undefined && !isMoney(d.budget)) return "budget が Money でない";
			return null;
		case "plan.proposed":
		case "plan.approved":
			return isStr(d.hash) ? null : "hash が必要";
		case "node.added": {
			const n = d.node;
			if (!isObj(n)) return "node が必要";
			if (!["task", "check", "integrate"].includes(n.kind as string)) return "node.kind は task|check|integrate";
			if (!isStr(n.parent)) return "node.parent が必要";
			if (!isStr(n.title)) return "node.title が必要";
			if (n.after !== undefined && !strList(n.after)) return "node.after は文字列の配列";
			if (n.writes !== undefined && !strList(n.writes)) return "node.writes は文字列の配列";
			if (n.budget !== undefined && !isMoney(n.budget)) return "node.budget が Money でない";
			if (n.attrs !== undefined && !isObj(n.attrs)) return "node.attrs はオブジェクト";
			return null;
		}
		case "edge.added":
			return isStr(d.from) && isStr(d.to) ? null : "from と to が必要";
		case "edge.rejected":
			return isStr(d.from) && isStr(d.to) && isStr(d.reason) ? null : "from・to・reason が必要";
		case "run.reserved":
			if (!isStr(d.task)) return "task が必要";
			return isMoney(d.est) ? null : "est が Money でない";
		case "run.started":
			return d.pid === undefined || isNum(d.pid) ? null : "pid が数値でない";
		case "run.usage":
			return isMoney(d.usage) ? null : "usage が Money でない";
		case "run.ended":
			if (!RUN_END_STATUSES.includes(d.status as RunEndStatus)) return "status が不正";
			if (d.usage !== undefined && !isMoney(d.usage)) return "usage が Money でない";
			return d.digestId === undefined || isStr(d.digestId) ? null : "digestId が文字列でない";
		case "check.result":
			return isStr(d.name) && typeof d.ok === "boolean" ? null : "name と ok が必要";
		case "wait.opened": {
			const w = d.wait;
			if (!isObj(w)) return "wait が必要";
			if (!WAIT_KINDS.includes(w.on as WaitKind)) return "wait.on が不正";
			if (!isStr(w.ref)) return "wait.ref が必要";
			if (!isNum(w.since)) return "wait.since が必要";
			if (typeof w.auto !== "boolean") return "wait.auto が必要";
			if (w.on === "user") {
				if (w.auto) return "user 待ちは auto にできない (待ちを機械で埋めない)";
				if (!isStr(w.prompt)) return "user 待ちには prompt が必要";
			}
			if (w.prompt !== undefined && (!isStr(w.prompt) || displayWidth(w.prompt) > PROMPT_MAX_WIDTH)) {
				return `prompt は ${PROMPT_MAX_WIDTH} 桁以内`;
			}
			return null;
		}
		case "wait.resolved":
			if (!isStr(d.ref)) return "ref が必要";
			return WAIT_KINDS.includes(d.by as WaitKind) ? null : "by が不正";
		case "note.appended":
			if (!(d.by === "user" || d.by === "llm" || (typeof d.by === "string" && /^run:.+/.test(d.by)))) return "by が不正";
			if (typeof d.text !== "string" || d.text.length === 0) return "text が必要";
			return d.text.length <= NOTE_MAX ? null : `text は ${NOTE_MAX} 字以内`;
		case "budget.adjusted":
			return isMoney(d.budget) ? null : "budget が Money でない";
		case "verdict":
			if (!VERDICTS.includes(d.verdict as VerdictKind)) return "verdict が不正";
			return isStr(d.reason) ? null : "reason が必要";
		case "goal.paused":
			return isStr(d.reason) ? null : "reason が必要";
		case "goal.resumed":
		case "goal.done":
			return null;
		case "lease.acquired":
			if (!isStr(d.holder) || !isNum(d.pid)) return "holder と pid が必要";
			return d.startedAt === undefined || isNum(d.startedAt) ? null : "startedAt が数値でない";
		case "lease.released":
		case "lease.expired":
			return isStr(d.holder) ? null : "holder が必要";
		default:
			// 観測用 (aux) は検証しない
			return null;
	}
};

/** 台帳に載る形のイベントの検証 (形と出所)。aux は常に通す。不正なら理由を返す */
export const validateEvent = (ev: {
	type: EventType;
	node?: string;
	data: Record<string, unknown>;
	aux?: boolean;
	source?: Source;
	holder?: string;
}): string | null => {
	if (isAux(ev)) return null;
	if (!isStr(ev.node)) return "node が必要";
	const bad = validatePayload(ev.type, ev.data);
	if (bad) return bad;
	if (isUserOnly(ev.type, ev.data) && ev.source !== "user") {
		return `${ev.type} は利用者専用 (出所が user でない: ${String(ev.source ?? "system")}) [I10]`;
	}
	if (ev.holder !== undefined && !isStr(ev.holder)) return "holder が文字列でない";
	return null;
};

/**
 * イベントの作成ヘルパ。形を検証し、利用者専用のイベントは出所が user でなければ拒否する (I10)。
 * 出所は引数から、イベントの source 欄に設定する。data の中の source / holder は常に捨てる (偽装を効かせない)。
 * ただし lease.* の data.holder はペイロードそのものなので残す。holder 欄は store が付ける (I8)。
 */
export const makeEvent = <T extends keyof Payloads>(
	type: T,
	node: string,
	data: Payloads[T],
	source: Source = "system",
	opts: { holder?: string } = {},
): NewEvent => {
	const { source: _s, holder: h, ...rest } = data as Record<string, unknown>;
	const full: Record<string, unknown> = type.startsWith("lease.") && h !== undefined ? { ...rest, holder: h } : rest;
	const top = { source, ...(opts.holder !== undefined ? { holder: opts.holder } : {}) };
	const bad = validateEvent({ type, node, data: full, ...top });
	if (bad) throw new EventError(`${type}: ${bad}`);
	return { type, node, data: full, ...top };
};

/** 観測用イベントの作成 (aux)。検証しない */
export const makeAux = (type: EventType, data: Record<string, unknown> = {}, node?: string): NewEvent => ({
	type,
	...(node !== undefined ? { node } : {}),
	data,
	aux: true,
});
