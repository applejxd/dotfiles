// `/pending` (利用者専用。モデルは呼べない registerCommand だけ) の全体 (CHG-0055 の P5b)。
// 旧形式 (承認が取れず退避した git commit) の list / show / drop は従来の出力のまま、新形式 (構造化した保留) は pending-approve.ts / pending-ops.ts を使う。
// pi の API (pi・ctx) と設定・ApproveDeps の元は注入する (試験できるように。接続は index.ts)。
//
// キルスイッチ ([pi.pending] enabled = false) が止めるのは、新しい保留の保存と承認だけ。一覧・表示・破棄・復旧 (resolve) は残す。
// see docs/change/0055-async-approval.md#設計の契約
import { PENDING_PREFIX, dropPending, isLegacyEntry, listPending, showPending } from "./pending-store.ts";
import { approvePending, listText, logText, resolvePending, showText, unlockPending, type ApproveDeps, type Reply, type ResolveArgs } from "./pending-approve.ts";
import { DEFAULT_LIMITS, countPending, discardOp, doneOid, runningOid, type Limits } from "./pending-ops.ts";
import { chooseId, completeArgs, pickCandidates, resolveInteractive, resolveShortId, type PickKind } from "./pending-pick.ts";

export type PendingSettings = {
	enabled: boolean;
	modes: readonly string[];
	retentionDays: number;
	resultRetentionDays: number;
	limits: Limits;
};

/** `rules.judge.common.pi.pending` の生の値から、既定を補った設定を作る (呼ぶたびに読む)。不正な値は既定 (無効側) に倒す */
export function pendingSettings(raw: any): PendingSettings {
	const num = (v: unknown, d: number) => (typeof v === "number" && Number.isFinite(v) && v > 0 ? v : d);
	return {
		enabled: raw?.enabled === true,
		modes: Array.isArray(raw?.modes) ? raw.modes.map(String) : ["tui"],
		retentionDays: num(raw?.retention_days, 30),
		resultRetentionDays: num(raw?.result_retention_days, 90),
		limits: { ...DEFAULT_LIMITS, maxPending: num(raw?.max_pending, DEFAULT_LIMITS.maxPending) },
	};
}

export type PendingCommandDeps = {
	/** 設定 (呼ぶたびに読む) */
	settings: () => PendingSettings;
	/** approve / resolve 用の ApproveDeps (呼ぶたびに作る。enabled は設定を呼ぶたびに読む) */
	approveDeps: (ctx: any) => ApproveDeps;
	redact?: (text: string) => string;
	/** 利用者の操作を受けたとき (不在の解除など) */
	touch?: () => void;
};

export const USAGE = "/pending [list | show <id> | approve [<id>] | resolve [<id>] [<success|failed|retry|pending|abandon> [--confirm-stopped]] | drop <id> | unlock | log]  (<id> は末尾 3 桁以上でもよい。show・drop・resolve の <id> も省略すると選べる)";
const RESOLVE_KINDS = ["success", "failed", "retry", "pending", "abandon"] as const;

/** フッターの「📥 保留 N 件」を更新する。UI があるときだけ。0 件なら消す */
export function updatePendingFooter(ctx: any, limits: Limits = DEFAULT_LIMITS): void {
	if (!ctx?.hasUI || typeof ctx.ui?.setStatus !== "function") return;
	let n = 0;
	try {
		n = countPending(String(ctx.cwd ?? process.cwd()), limits);
	} catch {}
	ctx.ui.setStatus("pending", n > 0 ? `📥 保留 ${n} 件` : undefined);
}

function legacyText(cwd: string): string {
	const all = listPending(cwd).filter((e) => isLegacyEntry(cwd, e.oid));
	return all.length === 0 ? "" : all.map((e) => `${e.ref.slice(PENDING_PREFIX.length)}  ${e.oid.slice(0, 7)}  ${e.subject}  (${e.branch || "-"})`).join("\n");
}

export function registerPendingCommand(pi: any, deps: PendingCommandDeps): { abortAll: () => void; refresh: (ctx: any) => void } {
	const controllers = new Set<AbortController>();
	const redact = deps.redact ?? ((t: string) => t);
	const refresh = (ctx: any) => updatePendingFooter(ctx, deps.settings().limits);
	let lastCtx: any;

	async function run(args: string, ctx: any): Promise<Reply> {
		const cwd: string = ctx.cwd ?? process.cwd();
		lastCtx = ctx;
		const [sub = "list", rawArg = "", ...rest] = String(args ?? "").trim().split(/\s+/);
		let arg = rawArg.startsWith(PENDING_PREFIX) ? rawArg.slice(PENDING_PREFIX.length) : rawArg;
		let full = rawArg.startsWith("refs/") ? rawArg : `${PENDING_PREFIX}${rawArg}`;
		const limits = deps.settings().limits;
		const info = (text: string): Reply => ({ text, level: "info" });
		const tui = ctx.mode === "tui" && ctx.hasUI;
		if (["approve", "show", "drop", "resolve"].includes(sub)) {
			// ID を決めるだけ (末尾一致・選択)。決めた後は、ID 指定の経路にそのまま進む
			const picked = !arg
				? sub === "resolve" || !tui
					? undefined
					: await chooseId(ctx, deps.approveDeps(ctx), sub as PickKind, pickCandidates(cwd, sub as PickKind, deps.approveDeps(ctx)))
				: !rawArg.startsWith("refs/") && /^\d{1,14}$/.test(arg)
					? await resolveShortId(ctx, deps.approveDeps(ctx), sub as PickKind, arg)
					: undefined;
			if (picked && !picked.ok) return picked.reply;
			if (picked) {
				arg = picked.id;
				full = `${PENDING_PREFIX}${arg}`;
			}
		}
		if (sub === "approve" && !arg && !tui) return approvePending("", ctx, deps.approveDeps(ctx));
		if (sub === "" || sub === "list") {
			const legacy = legacyText(cwd);
			const modern = listText(cwd, { liveness: deps.approveDeps(ctx).liveness, limits }, Date.now());
			const parts = [legacy, modern].filter(Boolean);
			return info(parts.length ? parts.join("\n") : "退避したコミットは無い");
		}
		if (sub === "log") return info(logText(cwd, limits));
		if (sub === "show" && arg) {
			const entry = listPending(cwd).find((e) => e.ref === full);
			if (entry && isLegacyEntry(cwd, entry.oid)) return info(showPending(cwd, full) || "見つからない (/pending list で ref を確かめる)");
			if (entry || runningOid(cwd, arg) || doneOid(cwd, arg)) return info(showText(cwd, arg, limits));
			return info("見つからない (/pending list で ref を確かめる)");
		}
		if (sub === "drop" && arg) {
			const entry = listPending(cwd).find((e) => e.ref === full);
			if (entry && !isLegacyEntry(cwd, entry.oid)) {
				const d = discardOp(cwd, arg, entry.oid, limits);
				return d.ok ? info(`破棄した: ${arg} (到達用の ref を外した。オブジェクトは git gc まで残る)`) : { text: d.reason, level: "warning" };
			}
			return info(dropPending(cwd, full) ? `破棄した: ${full} (到達用の ref を外した。オブジェクトは git gc まで残る)` : "破棄できなかった (ref が無い・退避の ref ではない)");
		}
		if (sub === "approve" && arg) {
			const ac = new AbortController();
			controllers.add(ac);
			try {
				return await approvePending(arg, ctx, deps.approveDeps(ctx), ac.signal);
			} finally {
				controllers.delete(ac);
			}
		}
		if (sub === "resolve") {
			const kind = rest.find((t) => !t.startsWith("--"));
			if (!arg || !kind) return resolveInteractive(arg || undefined, ctx, deps.approveDeps(ctx));
			if (!(RESOLVE_KINDS as readonly string[]).includes(kind)) return { text: `resolve <id> <${RESOLVE_KINDS.join("|")}> [--confirm-stopped]`, level: "warning" };
			const args2: ResolveArgs = { kind: kind as ResolveArgs["kind"], confirmStopped: rest.includes("--confirm-stopped") };
			return resolvePending(arg, args2, ctx, deps.approveDeps(ctx));
		}
		if (sub === "unlock") return unlockPending(ctx, deps.approveDeps(ctx));
		return info(USAGE);
	}

	pi.registerCommand("pending", {
		description: "保留した操作の一覧・表示・承認・破棄: /pending [list | show [<id>] | approve [<id>] | resolve [<id>] [<結果>] | drop [<id>] | unlock | log] (<id> は末尾 3 桁以上でもよい)",
		getArgumentCompletions: (prefix: string) => {
			try {
				const ctx = lastCtx ?? { cwd: process.cwd() };
				return completeArgs(prefix, String(ctx.cwd ?? process.cwd()), deps.approveDeps(ctx));
			} catch {
				return null;
			}
		},
		handler: async (args: string, ctx: any) => {
			deps.touch?.();
			let reply: Reply;
			try {
				reply = await run(args, ctx);
			} catch (e) {
				reply = { text: `/pending の実行に失敗した: ${(e as Error)?.message ?? e}`, level: "error" };
			}
			ctx.ui?.notify?.(redact(reply.text), reply.level);
			refresh(ctx);
		},
	});
	return {
		abortAll: () => {
			for (const c of controllers) c.abort();
			controllers.clear();
		},
		refresh,
	};
}
