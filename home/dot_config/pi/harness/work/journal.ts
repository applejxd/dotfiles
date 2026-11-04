// 作業台帳の観測ログ (journal)。LedgerEvent (aux: true) を 1 行 1 JSON で追記するだけで、振る舞いは変えない。
// 並列度の律速 (親の接触回数・同時数・待ち時間・見える自動メッセージ・モデルの文脈に入った通知の文字数) の実測が目的。
// 置き場: <作業ツリー>/.tmp/work/journal/<session>.jsonl。PI_JOURNAL=0 で無効。子では記録しない。
// 購読は journal 自身が pi のイベントで行う (既存の拡張を変更しない)。see docs/spec/work/journal.md
import { appendFileSync, mkdirSync } from "node:fs";
import { join } from "node:path";
import { foldNotice, quietEnabled, RESUME_MARK, type NoticeKind } from "../quiet-notices.ts";
import type { EventType, LedgerEvent } from "./types.ts";

/** 文字列の値の上限。超えたら本文を捨てて文字数だけ残す (巨大な本文・秘密を入れない) */
export const MAX_STRING = 120;
const MAX_DEPTH = 3;

export interface JournalOptions {
	dir: string;
	sessionId: string;
	now?: () => number;
}

export interface Journal {
	readonly path: string;
	readonly lastError: string | undefined;
	emit(type: EventType, data?: Record<string, unknown>, node?: string): void;
}

/** 記録してよい形へ落とす。長い文字列は `<N chars>` に置き換える (本文は残さない)。深い入れ子と配列の長さも制限する */
export function sanitize(v: unknown, depth = 0): unknown {
	if (typeof v === "string") return v.length > MAX_STRING ? `<${v.length} chars>` : v;
	if (v === null || typeof v === "number" || typeof v === "boolean") return v;
	if (v === undefined) return undefined;
	if (depth >= MAX_DEPTH) return "<nested>";
	if (Array.isArray(v)) return v.slice(0, 20).map((x) => sanitize(x, depth + 1));
	if (typeof v === "object") {
		const out: Record<string, unknown> = {};
		for (const [k, x] of Object.entries(v as Record<string, unknown>)) {
			const s = sanitize(x, depth + 1);
			if (s !== undefined) out[k] = s;
		}
		return out;
	}
	return undefined;
}

const safeName = (s: string) => s.replace(/[^A-Za-z0-9._-]/g, "_").slice(0, 80) || "session";

/** 追記だけの記録器。書けなくても例外を出さず lastError に残す (観測用なので fsync もしない) */
export function createJournal(opts: JournalOptions): Journal {
	const now = opts.now ?? Date.now;
	const path = join(opts.dir, `${safeName(opts.sessionId)}.jsonl`);
	let seq = 0;
	let lastError: string | undefined;
	let made = false;
	return {
		path,
		get lastError() {
			return lastError;
		},
		emit(type, data = {}, node) {
			try {
				const ev: LedgerEvent = { ts: now(), seq: ++seq, type, data: (sanitize(data) as Record<string, unknown>) ?? {}, aux: true };
				if (node !== undefined) ev.node = node;
				if (!made) {
					mkdirSync(opts.dir, { recursive: true });
					made = true;
				}
				appendFileSync(path, `${JSON.stringify(ev)}\n`);
			} catch (e) {
				lastError = e instanceof Error ? e.message : String(e);
			}
		},
	};
}

// ─── pi のイベントの購読 ───

const NOTICE_KINDS: readonly string[] = ["child-finished", "bg-job-finished", "todo-reminder", "autocheckpoint"];

export interface RegisterOptions {
	child: boolean;
	env?: Record<string, string | undefined>;
	now?: () => number;
	/** 置き場の上書き (試験用)。既定は <cwd>/.tmp/work/journal */
	dir?: string;
}

const textLen = (content: unknown): number => {
	if (typeof content === "string") return content.length;
	if (!Array.isArray(content)) return 0;
	let n = 0;
	for (const b of content) if (b && typeof b.text === "string") n += b.text.length;
	return n;
};

const lineCount = (s: string): number => (s === "" ? 0 : s.split("\n").length);

/** 通知 (custom メッセージ・自動の再開) を notice / run.ended / wait.resolved へ写す */
function observeMessage(j: Journal, env: Record<string, string | undefined>, message: any): void {
	let kind: string | undefined;
	let content = "";
	if (message?.role === "custom" && NOTICE_KINDS.includes(message.customType)) {
		kind = message.customType;
		content = typeof message.content === "string" ? message.content : JSON.stringify(message.content ?? "");
	} else if (message?.role === "user") {
		const t = typeof message.content === "string" ? message.content : "";
		if (!t.startsWith(RESUME_MARK)) return;
		kind = "autocheckpoint-resume";
		content = t;
	} else return;
	const shown = message.role === "user" || message.display === true;
	const folded = shown && quietEnabled(env);
	let text = "";
	if (folded) {
		text = message.role === "user" ? "▶ 再開を指示（自動）" : foldNotice(kind as NoticeKind, content, message.details).text;
	}
	j.emit("notice", {
		kind,
		shown,
		folded,
		lines_shown: shown ? (folded ? 1 : lineCount(content)) : 0,
		chars_shown: shown ? (folded ? text.length : content.length) : 0,
		chars_to_model: content.length,
	});
	const d = message.details ?? {};
	if (kind === "child-finished") {
		const st = d.stats ?? {};
		j.emit("run.ended", {
			id: d.id ?? d.jobId,
			role: d.agent,
			state: Array.isArray(d.statuses) ? "batch" : d.status,
			ms: Number(st.durationMs) || undefined,
			usd: Number(st.cost) || undefined,
			n: Array.isArray(d.statuses) ? d.statuses.length : undefined,
		});
	} else if (kind === "bg-job-finished") {
		j.emit("wait.resolved", { on: "job", ref: d.id ?? (Array.isArray(d.ids) ? d.ids[0] : undefined) });
	}
}

/** guarded_task の呼び出しから、起動する子の数と役割を数える (状態の確認・停止・指示は起動ではない) */
function taskStarts(args: any): { agent: string; bg: boolean }[] {
	if (!args || typeof args !== "object" || args.status || args.list || args.abort || args.steer) return [];
	const bg = args.background === true;
	const name = (a: unknown) => (typeof a === "string" ? a.slice(0, 40) : "?");
	if (Array.isArray(args.tasks)) return args.tasks.slice(0, 20).map((t: any) => ({ agent: name(t?.agent), bg }));
	if (typeof args.agent === "string") return [{ agent: name(args.agent), bg }];
	if (typeof args.jobId === "string" && typeof args.task === "string") return [{ agent: "follow-up", bg }];
	return [];
}

/** journal 自身が pi のイベントを購読する。購読は観測だけで、どのハンドラも undefined を返す (挙動を変えない) */
export function registerJournal(pi: any, opts: RegisterOptions): void {
	const env = opts.env ?? process.env;
	if (opts.child || env.PI_JOURNAL === "0") return;
	let j: Journal | undefined;
	const promptStart = new Map<string, number>();
	const now = opts.now ?? Date.now;
	const guard =
		(fn: (event: any, ctx: any) => void) =>
		(event: any, ctx: any): undefined => {
			try {
				fn(event, ctx);
			} catch {
				/* 観測の失敗で本体を止めない */
			}
			return undefined;
		};
	pi.on(
		"session_start",
		guard((event, ctx) => {
			const cwd = ctx?.cwd ?? process.cwd();
			const id = String(ctx?.sessionManager?.getSessionId?.() ?? `s${now().toString(36)}`);
			j = createJournal({ dir: opts.dir ?? join(cwd, ".tmp", "work", "journal"), sessionId: id, now: opts.now });
			j.emit("session.start", { reason: event?.reason, session: id });
		}),
	);
	pi.on(
		"tool_execution_start",
		guard((event) => {
			if (event?.parentToolCallId || typeof event?.toolName !== "string" || !event.toolName.endsWith("task")) return;
			for (const s of taskStarts(event.args)) j?.emit("run.started", { role: s.agent, background: s.bg });
		}),
	);
	pi.on(
		"tool_execution_end",
		guard((event) => {
			j?.emit("tool.call", {
				tool: event?.toolName,
				ms: event?.durationMs,
				isError: event?.isError === true,
				chars: textLen(event?.result?.content),
				nested: event?.parentToolCallId ? true : undefined,
			});
		}),
	);
	pi.on(
		"ui_prompt_start",
		guard((event) => {
			const ref = `${event?.kind ?? "prompt"}`;
			promptStart.set(ref, now());
			j?.emit("wait.opened", { on: "user", ref });
		}),
	);
	pi.on(
		"ui_prompt_end",
		guard((event) => {
			const ref = `${event?.kind ?? "prompt"}`;
			const t0 = promptStart.get(ref);
			promptStart.delete(ref);
			j?.emit("wait.resolved", { on: "user", ref, ms: t0 === undefined ? undefined : now() - t0 });
		}),
	);
	pi.on(
		"agent_before_settle",
		guard((event) => {
			// 先に走った handler (todo・autocheckpoint) が追加した entries と continue が見える (後に走る handler の分は見えない)
			const entries: any[] = Array.isArray(event?.entries) ? event.entries : [];
			const custom = entries.filter((e) => e?.type === "custom_message").map((e) => String(e.customType));
			j?.emit("settle", {
				outcome: event?.outcome,
				continue: event?.continue === true,
				by: custom.length > 0 ? custom[custom.length - 1] : undefined,
			});
		}),
	);
	pi.on(
		"message_end",
		guard((event) => {
			if (j) observeMessage(j, env, event?.message);
		}),
	);
	pi.on(
		"after_provider_response",
		guard((event) => {
			if (event?.status === 429) j?.emit("resource.429", { status: 429 });
		}),
	);
}
