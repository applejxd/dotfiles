// 作業台帳を pi に登録する最小の配線。ツール `work`・コマンド `/work`・パネル (ウィジェット) を足す。
// 既定は無効: PI_WORK_TOOL=1 のときだけ登録する。PI_WORK=0 で一括無効。子 (child) では登録しない (子は台帳に書かない)。
// 台帳の開閉は runtime.ts、引数の検査とイベント生成は tool.ts が持ち、ここは pi の API へ繋ぐだけ。see docs/spec/work/register.md
import { join } from "node:path";
import { select } from "./notices.ts";
import { renderPanel } from "./panel.ts";
import type { PanelInput } from "./panel.ts";
import { budgetStatus, waitingUser } from "./project.ts";
import type { LedgerState } from "./reduce.ts";
import { createRuntime } from "./runtime.ts";
import type { Runtime, RuntimeOptions } from "./runtime.ts";
import { createJournal } from "./journal.ts";
import type { Journal } from "./journal.ts";
import { handleWork, WORK_TOOL_SCHEMA } from "./tool.ts";
import { isTaskLike } from "./reduce.ts";
import type { EventType } from "./types.ts";

export const WIDGET_KEY = "work";

export interface RegisterWorkOptions {
	child: boolean;
	env?: Record<string, string | undefined>;
	/** 記録器 (試験用)。省略時は <cwd>/.tmp/work/journal の `<session>-work.jsonl` に作る */
	journal?: Pick<Journal, "emit">;
	/** runtime への追加の設定 (試験用: root・timers・now・autoLease など) */
	runtime?: Partial<RuntimeOptions>;
	pid?: number;
}

/** 台帳の登録が有効か (旗を明示したときだけ) */
export const workEnabled = (env: Record<string, string | undefined>, child: boolean): boolean =>
	!child && !env.PI_HARNESS_CHILD && env.PI_WORK !== "0" && env.PI_WORK_TOOL === "1";

const LIVE_GOAL = ["draft", "planned", "active", "paused"];

/** 台帳の状態からパネルの入力を作る (作業中の goal が無ければ goal は null) */
export function panelInput(state: LedgerState, now: number): PanelInput {
	const gid = state.goals.find((id) => LIVE_GOAL.includes(state.nodes.get(id)?.state ?? ""));
	const g = gid ? state.nodes.get(gid) : undefined;
	const tasks = [...state.nodes.values()].filter(isTaskLike);
	const failed = tasks.filter((t) => t.state === "failed");
	const warnings: string[] = [];
	if (g) {
		const b = budgetStatus(g);
		if (b.usd.level !== "ok") warnings.push(b.usd.level === "over" ? "予算超過" : "予算が 80% を超えた");
	}
	return {
		goal: g
			? {
					title: g.title,
					usd: g.spent.usd,
					usdLimit: g.budget?.usd,
					elapsedMin: g.owner ? Math.max(0, (now - g.owner.startedAt) / 60000) : 0,
				}
			: null,
		running: tasks.filter((t) => t.state === "running").length,
		waitingUser: waitingUser(state).length,
		failed: failed.length,
		done: tasks.filter((t) => t.state === "done").length,
		total: tasks.length,
		waits: waitingUser(state).map((w, i) => ({ prompt: w.prompt, rank: i })),
		failures: failed.map((t) => t.title),
		warnings,
	};
}

const text = (s: string, details: Record<string, unknown> = {}) => ({ content: [{ type: "text", text: s }], details });

export function registerWork(pi: any, opts: RegisterWorkOptions): void {
	const env = opts.env ?? process.env;
	if (!workEnabled(env, opts.child)) return;
	const pid = opts.pid ?? process.pid;
	let rt: Runtime | null = null;
	let key = "";
	let opening: Promise<void> | null = null;
	let holder = "";
	let curCtx: any = null;
	let journal: Pick<Journal, "emit"> | undefined = opts.journal;
	const emit = (type: EventType, data: Record<string, unknown>) => {
		try {
			journal?.emit(type, data);
		} catch {
			/* 観測の失敗で本体を止めない */
		}
	};
	const render = (state: LedgerState) => {
		const ctx = curCtx;
		if (!ctx?.hasUI) return;
		try {
			const lines = renderPanel(panelInput(state, Date.now()));
			ctx.ui.setWidget(WIDGET_KEY, lines.length > 0 ? lines : undefined);
		} catch {
			/* 表示の失敗で台帳の処理を止めない */
		}
	};
	const alert = (message: string) => {
		// 通知は選別の表を通す。silent は出さない
		if (select("run.warning").show === "silent") return;
		const ctx = curCtx;
		if (ctx?.hasUI) ctx.ui.notify(message, "warning");
	};

	const open = async (ctx: any): Promise<void> => {
		const sessionId = String(ctx.sessionManager?.getSessionId?.() ?? "session");
		const k = `${ctx.cwd}\n${sessionId}`;
		curCtx = ctx;
		if (opening && key === k) return opening; // new / fork / resume で複数回来ても 1 つだけ
		const old = rt;
		rt = null;
		key = k;
		holder = `${pid}:${sessionId}`;
		if (!opts.journal) journal = createJournal({ dir: join(ctx.cwd, ".tmp", "work", "journal"), sessionId: `${sessionId}-work` });
		opening = (async () => {
			if (old) await old.close().catch(() => {});
			const r = createRuntime({
				cwd: ctx.cwd,
				sessionId,
				holder,
				pid,
				env,
				...opts.runtime,
				onChange: (s) => render(s),
				onAlert: alert,
			});
			await r.start();
			rt = r;
			emit("session.start", { work: true, mode: r.mode });
			render(r.state());
		})();
		return opening;
	};

	pi.on("session_start", async (_event: any, ctx: any) => {
		try {
			await open(ctx);
		} catch (e) {
			emit("session.start", { work: false, error: e instanceof Error ? e.message : String(e) });
		}
		return undefined;
	});
	pi.on("session_shutdown", async () => {
		const r = rt;
		rt = null;
		opening = null;
		key = "";
		if (r) await r.close().catch(() => {});
		if (curCtx?.hasUI) curCtx.ui.setWidget(WIDGET_KEY, undefined);
		return undefined;
	});

	pi.registerTool({
		name: "work",
		label: "Work",
		promptSnippet: "Keep the work ledger: add / set / note / list / plan / cancel tasks",
		description:
			"作業台帳 (todo の置き換え先)。op: add (title) / set (id と status か deps) / note (id と text) / list (filter) / " +
			"plan (goal と tasks。承認は利用者だけ) / cancel (id と reason)。spawn・承認・予算変更は持たない。",
		parameters: WORK_TOOL_SCHEMA,
		async execute(_id: string, params: any, _signal: unknown, _onUpdate: unknown, ctx: any) {
			if (ctx) curCtx = ctx;
			const op = typeof params?.op === "string" ? params.op : "?";
			if (!rt) return text("拒否: 台帳が開いていない", { error: "not-open" });
			const r = handleWork(rt.state(), params, { now: Date.now(), holder });
			if (!r.ok) {
				emit("tool.call", { tool: "work", op, ok: false });
				return text(r.text, r.details);
			}
			if (r.events.length === 0) {
				emit("tool.call", { tool: "work", op, ok: true });
				return text(r.text, r.details);
			}
			const s = await rt.submit(r.events);
			emit("tool.call", { tool: "work", op, ok: s.ok });
			if (!s.ok) return text(`拒否: 台帳に書けない (${s.error ?? "不明"})。状態は変わっていない`, { error: s.error ?? "failed" });
			return text(r.text, r.details);
		},
	});

	pi.registerCommand("work", {
		description: "作業台帳の一覧",
		handler: async (_args: string, ctx: any) => {
			if (ctx) curCtx = ctx;
			const body = rt
				? handleWork(rt.state(), { op: "list" }, { now: Date.now(), holder }).text
				: "台帳が開いていない";
			const note = rt && rt.mode !== "driver" ? `\n(読み取り専用: ${rt.readonlyReason ?? rt.mode})` : "";
			if (ctx?.hasUI) ctx.ui.notify(body + note, "info");
			emit("tool.call", { tool: "/work" });
		},
	});
}
