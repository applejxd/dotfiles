// `/goal` を作業台帳の上に載せる pi への接着 (コマンド登録・利用者入力での一時停止・計画の承認・settle への goal の事実)。
// 既定は無効: PI_WORK_GOAL=1 のときだけ登録する。PI_WORK=0 で一括無効。子 (child) では登録しない。
// 台帳の runtime は PI_WORK_TOOL が有効なら register.ts のものを共有し (globalThis.__piWorkRuntime)、無効なら自分で開く。
// 純関数は goal.ts (変換・導出)・goal-core.ts (引数の解析・予算)。see docs/spec/work/goal-run.md
import { join } from "node:path";
import { parseGoalArgs } from "../goal-core.ts";
import { goalCommandToEvents, goalStateOf, settleFactsOfGoal } from "./goal.ts";
import type { GoalRuntime } from "./goal.ts";
import { makeEvent } from "./events.ts";
import { createJournal } from "./journal.ts";
import type { Journal } from "./journal.ts";
import type { LedgerState } from "./reduce.ts";
import { workEnabled } from "./register.ts";
import { createRuntime } from "./runtime.ts";
import { clipCells } from "./text-width.ts";
import { sanitizeUntrusted } from "./digest.ts";
import type { Runtime, RuntimeOptions } from "./runtime.ts";
import type { EventType } from "./types.ts";

export type GoalFacts = ReturnType<typeof settleFactsOfGoal>;

export type Redact = (s: string) => string;

/** 伏字化が注入されないときの最低限 (代表的な秘密の形)。本番は index.ts が redact.ts の redactText を渡す */
const SECRET_RES = [
	/sk-[A-Za-z0-9_-]{16,}/g,
	/gh[pousr]_[A-Za-z0-9]{20,}/g,
	/AKIA[0-9A-Z]{16}/g,
	/-----BEGIN [A-Z ]*PRIVATE KEY-----/g,
	/Bearer\s+[A-Za-z0-9._~+/=-]{16,}/gi,
];
const defaultRedact: Redact = (s) => SECRET_RES.reduce((t, re) => t.replace(re, () => "[伏字]"), s);

export interface RegisterGoalOptions {
	/** 確認画面に出す題の伏字化 (既定は最低限の形)。index.ts が redactText を渡す */
	redact?: Redact;
	child: boolean;
	env?: Record<string, string | undefined>;
	/** 台帳の runtime の取得 (試験用)。省略時は register.ts が公開する globalThis.__piWorkRuntime (PI_WORK_TOOL 有効時) か、自分で開く */
	runtime?: Partial<RuntimeOptions> & { shared?: () => Runtime | null };
	journal?: Pick<Journal, "emit">;
	/** 評価役の注入点 (この feature では呼ばない。別 feature が (input) => 判定 を渡す) */
	evalFn?: (input: string, signal?: AbortSignal) => Promise<unknown>;
	pid?: number;
}

export interface GoalHandle {
	/** settle へ渡す goal の事実。台帳が使えない・目標が不完全なら undefined (提案しない) */
	facts(): GoalFacts | undefined;
	runtime(): Runtime | null;
	evalFn?: RegisterGoalOptions["evalFn"];
}

export const goalEnabled = (env: Record<string, string | undefined>, child: boolean): boolean =>
	!child && !env.PI_HARNESS_CHILD && env.PI_WORK !== "0" && env.PI_WORK_GOAL === "1";

const LIVE = ["draft", "planned", "active", "paused"];

/** 確認画面の本文。再承認は未承認の task の id と title (最大 10 件) と総件数を出す。
 *  題は 伏字化 → sanitizeUntrusted (ANSI・制御・双方向制御を除去/可視化) → 一行化 → 結合文字の連続を制限 → clipCells の順で安全にする */
export const approveBody = (goalTitle: string, a?: { total: number; titles: string[]; ids?: string[] }, redact: Redact = defaultRedact): string => {
	const safe = (s: string, n: number): string => {
		let t = String(s ?? "");
		try {
			t = redact(t);
		} catch {
			t = defaultRedact(t);
		}
		t = sanitizeUntrusted(defaultRedact(t)).replace(/\s+/g, " ").trim();
		t = t.replace(/(\p{M}{2})\p{M}+/gu, "$1");
		return clipCells(t, n);
	};
	if (!a) return `目標「${safe(goalTitle, 60)}」の計画を承認しますか`;
	const lines = a.titles.map((t, i) => `- ${a.ids?.[i] !== undefined ? `[${safe(a.ids[i]!, 24)}] ` : ""}${safe(t, 60)}`);
	const more = a.total > a.titles.length ? `\n… ほか ${a.total - a.titles.length} 件` : "";
	return `目標「${safe(goalTitle, 60)}」に、承認後に足された task が ${a.total} 件あります。承認しますか\n${lines.join("\n")}${more}`;
};
const currentGoal = (s: LedgerState) => {
	const id = s.goals[s.goals.length - 1];
	const n = id === undefined ? undefined : s.nodes.get(id);
	return n && LIVE.includes(n.state) ? n : null;
};

/** settle-snapshot が使える完全な形か (数値・真偽値が揃っているときだけ) */
export const goalFactsValid = (f: GoalFacts | undefined): f is GoalFacts =>
	!!f &&
	typeof f.budgetExhausted === "boolean" &&
	typeof f.goal?.active === "boolean" &&
	typeof f.goal.claim === "boolean" &&
	typeof f.goal.stall === "boolean" &&
	Number.isFinite(f.goal.unapproved);

export function registerGoal(pi: any, opts: RegisterGoalOptions): GoalHandle | null {
	const env = opts.env ?? process.env;
	if (!goalEnabled(env, opts.child)) return null;
	const pid = opts.pid ?? process.pid;
	const sharedGetter =
		opts.runtime?.shared ?? (workEnabled(env, opts.child) ? () => ((globalThis as any).__piWorkRuntime?.() as Runtime | null) ?? null : null);
	let own: Runtime | null = null;
	let key = "";
	let opening: Promise<void> | null = null;
	let curCtx: any = null;
	let journal = opts.journal;
	const rtGoal: GoalRuntime = {};
	const emit = (type: EventType, data: Record<string, unknown>) => {
		try {
			journal?.emit(type, data);
		} catch {
			/* 観測の失敗で本体を止めない */
		}
	};
	const rt = (): Runtime | null => (sharedGetter ? sharedGetter() : own);
	const say = (ctx: any, message: string, level = "info") => {
		if (ctx?.hasUI) ctx.ui.notify(message, level);
	};

	const open = async (ctx: any) => {
		curCtx = ctx;
		if (sharedGetter) return; // register.ts が開く
		const sessionId = String(ctx.sessionManager?.getSessionId?.() ?? "session");
		const k = `${ctx.cwd}\n${sessionId}`;
		if (opening && key === k) return opening;
		const old = own;
		own = null;
		key = k;
		if (!opts.journal) journal = createJournal({ dir: join(ctx.cwd, ".tmp", "work", "journal"), sessionId: `${sessionId}-goal` });
		opening = (async () => {
			if (old) await old.close().catch(() => {});
			const { shared: _s, ...ro } = opts.runtime ?? {};
			const r = createRuntime({ cwd: ctx.cwd, sessionId, holder: `${pid}:${sessionId}`, pid, env, ...ro });
			await r.start();
			own = r;
		})();
		return opening;
	};

	pi.on("session_start", async (_e: any, ctx: any) => {
		try {
			await open(ctx);
		} catch (e) {
			emit("session.start", { goal: false, error: e instanceof Error ? e.message : String(e) });
		}
		return undefined;
	});
	pi.on("session_shutdown", async () => {
		const r = own;
		own = null;
		opening = null;
		key = "";
		if (r) await r.close().catch(() => {});
		return undefined;
	});

	// 利用者の通常入力 (対話・RPC) で、実行中の目標を一時停止する。拡張が自分で送る入力 (起床など) は対象外
	pi.on("input", async (event: any, ctx: any) => {
		if (ctx) curCtx = ctx;
		const text = typeof event?.text === "string" ? event.text.trim() : "";
		if (event?.source === "extension" || text.startsWith("/goal")) return undefined;
		const r = rt();
		if (!r || r.mode !== "driver") return undefined;
		const g = currentGoal(r.state());
		if (!g || g.state !== "active") return undefined;
		const s = await r.submit([makeEvent("goal.paused", g.id, { reason: "input" }, "system")]);
		emit("tool.call", { tool: "goal.input-pause", ok: s.ok });
		if (s.ok) say(ctx, "🎯 利用者の入力で目標を一時停止しました (/goal resume で再開)");
		return undefined;
	});

	const approve = async (ctx: any): Promise<string> => {
		const r = rt();
		if (!r) return "拒否: 台帳が開いていない";
		if (r.mode !== "driver") return `拒否: 読み取り専用 (${r.readonlyReason ?? r.mode})`;
		const g = currentGoal(r.state());
		if (!g) return "承認待ちの計画はありません";
		const res = goalCommandToEvents({ kind: "approve" }, r.state(), Date.now());
		if (!res.ok) return res.error ?? "承認待ちの計画はありません";
		if (ctx?.hasUI && typeof ctx.ui.confirm === "function") {
			const ok = await ctx.ui.confirm(res.approval ? "task の再承認" : "計画の承認", approveBody(g.title, res.approval, opts.redact));
			if (!ok) return "承認を取りやめました";
		}
		const s = await r.submit(res.events);
		if (!s.ok && res.approval && String(s.error ?? "").includes("承認の対象が確認後に変わった")) {
			return "拒否: 確認後に対象が変わりました。もう一度 /goal approve してください";
		}
		return s.ok ? (res.approval ? `計画を承認しました (再承認: task ${res.approval.total} 件)` : "計画を承認しました") : `拒否: ${s.error ?? "不明"}`;
	};

	pi.registerCommand("goal", {
		description: "自律で目標に向かって継続する (status / pause / resume / clear / budget / approve)",
		handler: async (args: string, ctx: any) => {
			if (ctx) curCtx = ctx;
			const arg = (args ?? "").trim();
			const r = rt();
			if (!r) return say(ctx, "台帳が開いていない", "warning");
			if (arg === "approve") {
				const m = await approve(ctx);
				emit("tool.call", { tool: "/goal", op: "approve" });
				return say(ctx, m, m.startsWith("計画を承認") ? "info" : "warning");
			}
			const cmd = parseGoalArgs(arg);
			const res = goalCommandToEvents(cmd, r.state(), Date.now());
			if (!res.ok) return say(ctx, `拒否: ${res.error}`, "warning");
			if (res.events.length > 0) {
				if (r.mode !== "driver") return say(ctx, `拒否: 読み取り専用 (${r.readonlyReason ?? r.mode})`, "warning");
				const s = await r.submit(res.events);
				emit("tool.call", { tool: "/goal", op: cmd.kind, ok: s.ok });
				if (!s.ok) return say(ctx, `拒否: 台帳に書けない (${s.error ?? "不明"})`, "warning");
				return say(ctx, res.text ?? `🎯 /goal ${cmd.kind} を記録しました`);
			}
			emit("tool.call", { tool: "/goal", op: cmd.kind });
			return say(ctx, res.text ?? res.draft ?? "変更なし");
		},
	});

	const facts = (): GoalFacts | undefined => {
		const r = rt();
		if (!r || r.mode !== "driver") return undefined;
		const state = r.state();
		if (!goalStateOf(state, rtGoal)) return undefined;
		const f = settleFactsOfGoal(state, { claim: false, rt: rtGoal });
		return goalFactsValid(f) ? f : undefined;
	};
	(globalThis as any).__piGoalSnapshot = facts;
	return { facts, runtime: rt, evalFn: opts.evalFn };
}
