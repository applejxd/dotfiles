// PR レビュー状態のイベントログ (純粋関数。I/O なし)。app (別プロセス) と pi の両方が使う共有ライブラリ。
// スキーマの正本: docs/change/0060-local-pr-viewer.md と .tmp/keep/pr-viewer/design-decisions.md §2。
// import は node:crypto だけ (app が pending-*.ts などに依存しないため)。
import { createHash, randomUUID } from "node:crypto";

export const SCHEMA = 1;
/** この版の読み手が読める meta.schema の上限。これより大きい ref は「版が新しい」読み取り専用として扱う */
export const SCHEMA_MAX = 2;
/** brief を書ける最小の schema。起票で作る ref はこの版にする */
export const SCHEMA_BRIEF = 2;

/** brief の字数 (コードポイント数) の上限。合計は題名・目的・守る条件・完了条件・担当範囲の和 */
export const BRIEF_LIMITS = {
	title: 100,
	goal: 1500,
	constraints: 1500,
	acceptance: 800,
	scopeItems: 20,
	scopeItem: 120,
	total: 4000,
	name: 64,
	via: 32,
} as const;

export const LIMITS = {
	/** 1 イベントの本文 (d の JSON) の最大バイト数 */
	bodyBytes: 16384,
	/** events.jsonl の最大バイト数 */
	eventsBytes: 524288,
	/** イベントの最大件数 */
	events: 2000,
	/** この件数以上では、終端の種別以外を断る (終端記録用の余裕) */
	reservedFrom: 1900,
	/** リポジトリあたりの PR の最大数 */
	prs: 200,
	/** meta.json の最大バイト数 */
	metaBytes: 4096,
	/** events.jsonl の末尾に、終端の種別 (receipt・merge_*) 専用に残すバイト数。通常のイベントはここを使えない */
	reserveBytes: 32768,
	/** brief 1 件の d の最大バイト数 (日本語は 1 字 3 バイトなので、字数の上限とは別に検査する) */
	briefBytes: 15000,
} as const;

/** 余裕の範囲でも追記できる種別 */
export const TERMINAL_TYPES: readonly string[] = ["receipt", "merge_started", "merge_result"];

export type Vs = { source: string; target: string; base: string };
export type Meta = { schema: number; pr: string; branch: string; target: string; createdAt: string };
export type By = "app" | "pi";
export type Anchor = { path: string; side: "old" | "new"; blob: string; line: number; lineEnd: number };
export type SubmitKind = "comment" | "changes" | "approve";
export type Outcome = "success" | "refused" | "failed" | "unknown";

type Base = { v: 1; id: string; by: By; at: string; vs: Vs };
export type CommentEvent = Base & { t: "comment"; d: { thread: string; anchor: Anchor | null; body: string } };
export type SummaryEvent = Base & {
	t: "summary";
	d: { done: string; files: string[]; findings: { ref: string; reply: string }[]; notes?: string; mergeMessage?: string };
};
export type SubmitEvent = Base & {
	t: "submit";
	d: { batchId: string; kind: SubmitKind; items: string[]; dest: { worktreeId: string }; resendOf?: string };
};
export type ReceiptEvent = Base & { t: "receipt"; d: { batchId: string; sessionId: string } };
export type MergeRequestEvent = Base & {
	t: "merge_request";
	d: {
		requestId: string;
		sourceRef: string;
		sourceOid: string;
		targetRef: string;
		targetOid: string;
		baseOid: string;
		message: string;
		cleanup: string;
	};
};
export type MergeStartedEvent = Base & { t: "merge_started"; d: { requestId: string; pendingId: string } };
export type MergeResultEvent = Base & {
	t: "merge_result";
	d: { requestId: string; outcome: Outcome; reason?: string; doneOid?: string };
};
export type BriefEvent = Base & {
	t: "brief";
	d: {
		requestId: string;
		rev: number;
		kind: "feature";
		name: string;
		title: string;
		goal: string;
		constraints: string;
		scope: string[];
		acceptance: string;
		via: string;
	};
};
export type ReviewEvent =
	| CommentEvent
	| SummaryEvent
	| SubmitEvent
	| ReceiptEvent
	| MergeRequestEvent
	| MergeStartedEvent
	| MergeResultEvent
	| BriefEvent;

const OID_RE = /^[0-9a-f]{40}$/;
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const ISO_RE = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,9})?(Z|[+-]\d{2}:\d{2})$/;
const KNOWN = ["comment", "summary", "submit", "receipt", "merge_request", "merge_started", "merge_result", "brief"];
const BRIEF_KEYS = ["requestId", "rev", "kind", "name", "title", "goal", "constraints", "scope", "acceptance", "via"];
const BRIEF_NAME_RE = /^[a-z0-9][a-z0-9._-]{0,63}$/;
/** コードポイント数 (絵文字などのサロゲートペアを 1 字と数える) */
const cpLen = (s: string): number => [...s].length;

/** ブランチ名から PR の鍵を作る。API 契約と同じ: "p" + sha256("v1\0refs/heads/<branch>") の先頭 16 桁 */
export function prKeyOf(branch: string): string {
	return "p" + createHash("sha256").update(`v1\0refs/heads/${branch}`).digest("hex").slice(0, 16);
}

export function newId(): string {
	return randomUUID();
}

export function serializeEvents(events: ReviewEvent[]): string {
	return events.map((e) => JSON.stringify(e) + "\n").join("");
}

const isObj = (x: unknown): x is Record<string, unknown> => typeof x === "object" && x !== null && !Array.isArray(x);
const isStr = (x: unknown): x is string => typeof x === "string";
const isOid = (x: unknown): x is string => isStr(x) && OID_RE.test(x);
const isUuid = (x: unknown): x is string => isStr(x) && UUID_RE.test(x);
const isInt = (x: unknown): x is number => typeof x === "number" && Number.isInteger(x) && x >= 0;
const isStrArr = (x: unknown): x is string[] => Array.isArray(x) && x.every(isStr);
const optStr = (x: unknown): boolean => x === undefined || isStr(x);
const optOid = (x: unknown): boolean => x === undefined || isOid(x);

/** イベントの本文 (d) の JSON のバイト数 */
export function bodyBytesOf(e: { d: unknown }): number {
	return Buffer.byteLength(JSON.stringify(e.d), "utf8");
}

function validAnchor(a: unknown): boolean {
	if (a === null) return true;
	if (!isObj(a)) return false;
	return isStr(a.path) && (a.side === "old" || a.side === "new") && isOid(a.blob) && isInt(a.line) && isInt(a.lineEnd);
}

/** brief の d の検査。形の問題は "bad_brief"、バイト数の超過は "body_too_large" (入力の本文を含めない) */
function validBrief(d: Record<string, unknown>): string | null {
	if (Object.keys(d).length !== BRIEF_KEYS.length || !BRIEF_KEYS.every((k) => Object.hasOwn(d, k))) return "bad_brief";
	const L = BRIEF_LIMITS;
	const { name, title, goal, constraints, acceptance, via, scope } = d;
	if (!isUuid(d.requestId) || !isInt(d.rev) || d.rev < 1 || d.kind !== "feature") return "bad_brief";
	if (!isStr(name) || !BRIEF_NAME_RE.test(name) || cpLen(name) > L.name) return "bad_brief";
	if (!isStr(title) || title === "" || cpLen(title) > L.title) return "bad_brief";
	if (!isStr(goal) || goal === "" || cpLen(goal) > L.goal) return "bad_brief";
	if (!isStr(constraints) || cpLen(constraints) > L.constraints) return "bad_brief";
	if (!isStr(acceptance) || cpLen(acceptance) > L.acceptance) return "bad_brief";
	if (!isStr(via) || via === "" || cpLen(via) > L.via) return "bad_brief";
	if (!isStrArr(scope) || scope.length > L.scopeItems) return "bad_brief";
	if (!scope.every((s) => s !== "" && cpLen(s) <= L.scopeItem)) return "bad_brief";
	const total = cpLen(title) + cpLen(goal) + cpLen(constraints) + cpLen(acceptance) + scope.reduce((n, s) => n + cpLen(s), 0);
	if (total > L.total) return "bad_brief";
	if (Buffer.byteLength(JSON.stringify(d), "utf8") > LIMITS.briefBytes) return "body_too_large";
	return null;
}

/** d の形の検査。問題があれば短い理由 (入力の本文を含めない)、無ければ null */
function validD(t: string, d: Record<string, unknown>): string | null {
	switch (t) {
		case "brief":
			return validBrief(d);
		case "comment":
			return isStr(d.thread) && d.thread !== "" && validAnchor(d.anchor) && isStr(d.body) ? null : "bad_comment";
		case "summary": {
			const findings = d.findings;
			const okFind = Array.isArray(findings) && findings.every((f) => isObj(f) && isStr(f.ref) && isStr(f.reply));
			return isStr(d.done) && isStrArr(d.files) && okFind && optStr(d.notes) && optStr(d.mergeMessage) ? null : "bad_summary";
		}
		case "submit": {
			const dest = d.dest;
			const okKind = d.kind === "comment" || d.kind === "changes" || d.kind === "approve";
			const okDest = isObj(dest) && isStr(dest.worktreeId) && dest.worktreeId !== "";
			return isUuid(d.batchId) && okKind && isStrArr(d.items) && okDest && optStr(d.resendOf) ? null : "bad_submit";
		}
		case "receipt":
			return isUuid(d.batchId) && isStr(d.sessionId) ? null : "bad_receipt";
		case "merge_request":
			return isUuid(d.requestId) &&
				isStr(d.sourceRef) &&
				isOid(d.sourceOid) &&
				isStr(d.targetRef) &&
				isOid(d.targetOid) &&
				isOid(d.baseOid) &&
				isStr(d.message) &&
				isStr(d.cleanup)
				? null
				: "bad_merge_request";
		case "merge_started":
			return isUuid(d.requestId) && isStr(d.pendingId) ? null : "bad_merge_started";
		case "merge_result": {
			const okOut = d.outcome === "success" || d.outcome === "refused" || d.outcome === "failed" || d.outcome === "unknown";
			return isUuid(d.requestId) && okOut && optStr(d.reason) && optOid(d.doneOid) ? null : "bad_merge_result";
		}
	}
	return "unknown_type";
}

export type ParseResult = { ok: true; events: ReviewEvent[] } | { ok: false; reason: string };

/** JSONL を厳密に検査して読む。理由には入力の本文を含めない (行番号と規則名だけ) */
export function parseEvents(text: string): ParseResult {
	if (text === "") return { ok: true, events: [] };
	if (text.split("\n").length - 1 > LIMITS.events) return { ok: false, reason: "too_many_events" };
	if (Buffer.byteLength(text, "utf8") > LIMITS.eventsBytes) return { ok: false, reason: "events_too_large" };
	if (!text.endsWith("\n")) return { ok: false, reason: "no_trailing_newline" };
	const lines = text.slice(0, -1).split("\n");
	if (lines.length > LIMITS.events) return { ok: false, reason: "too_many_events" };
	const events: ReviewEvent[] = [];
	const ids = new Set<string>();
	const batches = new Set<string>();
	const requests = new Set<string>();
	const briefRevs = new Set<number>();
	for (let i = 0; i < lines.length; i++) {
		const at = `line ${i + 1}`;
		let o: unknown;
		try {
			o = JSON.parse(lines[i]);
		} catch {
			return { ok: false, reason: `${at}: invalid_json` };
		}
		if (!isObj(o)) return { ok: false, reason: `${at}: not_object` };
		if (o.v !== 1) return { ok: false, reason: `${at}: bad_version` };
		if (!isStr(o.t) || !KNOWN.includes(o.t)) return { ok: false, reason: `${at}: unknown_type` };
		if (!isUuid(o.id)) return { ok: false, reason: `${at}: bad_id` };
		if (ids.has(o.id)) return { ok: false, reason: `${at}: duplicate_id` };
		ids.add(o.id);
		if (o.by !== "app" && o.by !== "pi") return { ok: false, reason: `${at}: bad_by` };
		if (!isStr(o.at) || !ISO_RE.test(o.at) || Number.isNaN(Date.parse(o.at))) return { ok: false, reason: `${at}: bad_at` };
		const vs = o.vs;
		if (!isObj(vs) || !isOid(vs.source) || !isOid(vs.target) || !isOid(vs.base)) return { ok: false, reason: `${at}: bad_vs` };
		if (!isObj(o.d)) return { ok: false, reason: `${at}: bad_d` };
		const bad = validD(o.t, o.d);
		if (bad) return { ok: false, reason: `${at}: ${bad}` };
		if (bodyBytesOf({ d: o.d }) > LIMITS.bodyBytes) return { ok: false, reason: `${at}: body_too_large` };
		const d = o.d;
		if (o.t === "submit") {
			if (batches.has(d.batchId as string)) return { ok: false, reason: `${at}: duplicate_batch` };
			batches.add(d.batchId as string);
		} else if (o.t === "receipt") {
			if (!batches.has(d.batchId as string)) return { ok: false, reason: `${at}: receipt_without_submit` };
		} else if (o.t === "merge_request") {
			if (requests.has(d.requestId as string)) return { ok: false, reason: `${at}: duplicate_request` };
			requests.add(d.requestId as string);
		} else if (o.t === "brief") {
			// 版 (rev) は ref の中で一意。最大のものが現在の依頼文になる
			if (briefRevs.has(d.rev as number)) return { ok: false, reason: `${at}: duplicate_brief_rev` };
			briefRevs.add(d.rev as number);
		} else if (o.t === "merge_started" || o.t === "merge_result") {
			if (!requests.has(d.requestId as string)) return { ok: false, reason: `${at}: merge_without_request` };
		}
		events.push(o as unknown as ReviewEvent);
	}
	return { ok: true, events };
}

export type AppendCheck = { ok: true } | { ok: false; reason: "body_too_large" | "events_too_large" | "too_many_events" | "reserved" };

/** 追記の前の上限の検査。1900 件以上と、末尾の 32 KB は、終端の種別以外を断る (終端記録用の余裕) */
export function checkAppend(currentBytes: number, currentCount: number, event: ReviewEvent): AppendCheck {
	if (bodyBytesOf(event) > LIMITS.bodyBytes) return { ok: false, reason: "body_too_large" };
	if (event.t === "brief" && bodyBytesOf(event) > LIMITS.briefBytes) return { ok: false, reason: "body_too_large" };
	if (currentCount >= LIMITS.events) return { ok: false, reason: "too_many_events" };
	const terminal = TERMINAL_TYPES.includes(event.t);
	if (currentCount >= LIMITS.reservedFrom && !terminal) return { ok: false, reason: "reserved" };
	const line = Buffer.byteLength(JSON.stringify(event) + "\n", "utf8");
	if (!terminal && currentBytes + line > LIMITS.eventsBytes - LIMITS.reserveBytes) return { ok: false, reason: "reserved" };
	if (currentBytes + line > LIMITS.eventsBytes) return { ok: false, reason: "events_too_large" };
	return { ok: true };
}

export type ThreadStatus = "unsent" | "sent" | "read" | "replied";
export type Thread = { id: string; comments: CommentEvent[]; status: ThreadStatus; stale: boolean };
export type Batch = {
	batchId: string;
	kind: SubmitKind;
	items: string[];
	dest: { worktreeId: string };
	received: boolean;
	sessionId?: string;
	resendOf?: string;
};
export type ReviewState = "none" | "changes" | "approve";
export type MergeStatus = "none" | "requested" | "started" | "done";
export type State = {
	meta: Meta;
	threads: Thread[];
	batches: Batch[];
	review: ReviewState;
	/** 最後のレビュー (changes / approve) を書いた時点の vs。comment の送信では変わらない */
	reviewVs: Vs | null;
	/** 最後のレビューが、現在の source・target・base のどれかと違う (古いレビュー) */
	reviewStale: boolean;
	/** 最後の記録の vs が、現在の source・target・base のどれかと違う */
	stale: boolean;
	staleParts: { source: boolean; target: boolean; base: boolean };
	summary: SummaryEvent | null;
	/** rev が最大の brief (無ければ null) */
	brief: BriefEvent | null;
	merge: {
		status: MergeStatus;
		request: MergeRequestEvent | null;
		pendingId: string | null;
		result: MergeResultEvent | null;
		/** どれかの merge_result が success */
		succeeded: boolean;
	};
	count: number;
};

function staleOf(vs: Vs, cur: Vs): { source: boolean; target: boolean; base: boolean } {
	return { source: vs.source !== cur.source, target: vs.target !== cur.target, base: vs.base !== cur.base };
}

/** イベントから状態を導く。`by` は判定に使わない (表示用に持ち回るだけ) */
export function foldState(meta: Meta, events: ReviewEvent[], current: Vs): State {
	const batches: Batch[] = [];
	const sentItems = new Set<string>();
	const comments: { e: CommentEvent; idx: number }[] = [];
	const receiptIdx = new Map<string, number>();
	let review: ReviewState = "none";
	let reviewVs: Vs | null = null;
	let summary: SummaryEvent | null = null;
	let brief: BriefEvent | null = null;
	let request: MergeRequestEvent | null = null;
	let started: string | null = null;
	let result: MergeResultEvent | null = null;
	let succeeded = false;

	events.forEach((e, idx) => {
		switch (e.t) {
			case "comment":
				comments.push({ e, idx });
				break;
			case "brief":
				if (brief === null || e.d.rev >= brief.d.rev) brief = e;
				break;
			case "summary":
				summary = e;
				break;
			case "submit": {
				const b: Batch = { batchId: e.d.batchId, kind: e.d.kind, items: e.d.items, dest: e.d.dest, received: false };
				if (e.d.resendOf !== undefined) b.resendOf = e.d.resendOf;
				batches.push(b);
				for (const id of e.d.items) sentItems.add(id);
				// レビュー状態は changes / approve だけで決まる (comment の送信では変わらない。GitHub と同じ)
				if (e.d.kind === "changes" || e.d.kind === "approve") {
					review = e.d.kind;
					reviewVs = e.vs;
				}
				break;
			}
			case "receipt": {
				const b = batches.find((x) => x.batchId === e.d.batchId);
				if (b && !b.received) {
					b.received = true;
					b.sessionId = e.d.sessionId;
					receiptIdx.set(b.batchId, idx);
				}
				break;
			}
			case "merge_request":
				request = e;
				started = null;
				result = null;
				break;
			case "merge_started":
				if (request && e.d.requestId === request.d.requestId) started = e.d.pendingId;
				break;
			case "merge_result":
				if (e.d.outcome === "success") succeeded = true;
				if (request && e.d.requestId === request.d.requestId) result = e;
				break;
		}
	});

	const order: string[] = [];
	const byThread = new Map<string, { e: CommentEvent; idx: number }[]>();
	for (const c of comments) {
		const k = c.e.d.thread;
		if (!byThread.has(k)) {
			byThread.set(k, []);
			order.push(k);
		}
		byThread.get(k)!.push(c);
	}
	const threads: Thread[] = order.map((id) => {
		const cs = byThread.get(id)!;
		const ids = new Set(cs.map((c) => c.e.id));
		const mine = batches.filter((b) => b.items.some((x) => ids.has(x)));
		const got = mine.filter((b) => b.received).map((b) => receiptIdx.get(b.batchId)!);
		let status: ThreadStatus = "unsent";
		if (mine.length > 0) status = "sent";
		if (got.length > 0) {
			status = "read";
			const first = Math.min(...got);
			// 「返信済み」は表示用の状態。pi の道具が書いたコメント (by = pi) だけを数える。利用者が受領後に足したコメントでは変わらない。権限・統合の判定には使わない
			if (cs.some((c) => c.idx > first && c.e.by === "pi")) status = "replied";
		}
		const root = cs[0].e;
		const st = staleOf(root.vs, current);
		return { id, comments: cs.map((c) => c.e), status, stale: st.source || st.target || st.base };
	});

	const last = events.length > 0 ? events[events.length - 1] : null;
	const parts = last ? staleOf(last.vs, current) : { source: false, target: false, base: false };
	let status: MergeStatus = "none";
	if (request) status = result ? "done" : started !== null ? "started" : "requested";
	return {
		meta,
		threads,
		batches,
		review,
		reviewVs,
		reviewStale: reviewVs !== null && (() => {
			const p = staleOf(reviewVs, current);
			return p.source || p.target || p.base;
		})(),
		stale: parts.source || parts.target || parts.base,
		staleParts: parts,
		summary,
		brief,
		merge: { status, request, pendingId: started, result, succeeded },
		count: events.length,
	};
}

/** 宛先が一致し、受領がまだ無い batch */
export function unreadBatches(state: State, destWorktreeId: string): Batch[] {
	return state.batches.filter((b) => b.dest.worktreeId === destWorktreeId && !b.received);
}

export function mergedOk(state: State): boolean {
	return state.merge.succeeded;
}
