// `/pending` (利用者専用。モデルは呼べない registerCommand だけ) の全体 (CHG-0055 の P5b)。
// 旧形式 (承認が取れず退避した git commit) の list / show / drop は従来の出力のまま、新形式 (構造化した保留) は pending-approve.ts / pending-ops.ts を使う。
// pi の API (pi・ctx) と設定・ApproveDeps の元は注入する (試験できるように。接続は index.ts)。
//
// キルスイッチ ([pi.pending] enabled = false) が止めるのは、新しい保留の保存と承認だけ。一覧・表示・破棄・復旧 (resolve) は残す。
// see docs/change/0055-async-approval.md#設計の契約
import { PENDING_PREFIX, dropPending, isLegacyEntry, listPending, showPending } from "./pending-store.ts";
import {
	approvePending,
	executeApproval,
	listText,
	logText,
	planApproval,
	resolvePending,
	showText,
	unlockPending,
	type ApproveDeps,
	type Reply,
	type ResolveArgs,
} from "./pending-approve.ts";
import { VIEW_FULL, presentConfirm } from "./confirm-present.ts";
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

// 巡回 (CHG-0058 の段 1)。「ここで終える」を先頭に置く (B8: 直前の Enter の勢いで次の画面を承認しない)
export const PATROL_MAX = 8;
export const CHOICE_PATROL_STOP = "ここで終える（残りは保留のまま）";
export const CHOICE_PATROL_APPROVE = "承認して実行";
export const CHOICE_PATROL_NEXT = "保留のまま次へ";
export const CHOICE_PATROL_DISCARD = "破棄";
/** 実行中の Esc (素の Esc と、kitty の拡張入力の Esc) */
const ESC_KEY = /^\u001b(?:\[27(?:;\d+)?u)?$/;

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
	const refresh = (ctx: any) => {
		// フッターは補助。更新で例外が出ても、巡回やモデルへの通知を妨げない
		try {
			updatePendingFooter(ctx, deps.settings().limits);
		} catch {}
	};
	let lastCtx: any;

	/**
	 * 承認待ちを古い順に 1 件ずつ開く巡回。既存の経路 (planApproval → 画面 → executeApproval → runApproved) を 1 件ずつ通すだけで、新しい実行経路は作らない。
	 * Esc・中断・成功以外は全体を止め、モデルへの通知は巡回の終わりまで溜める (B4・B9・B10)
	 */
	async function patrol(firstId: string, total: number, ctx: any): Promise<Reply> {
		const cwd = String(ctx.cwd ?? process.cwd());
		const base = deps.approveDeps(ctx);
		const held: [string, Record<string, unknown>][] = [];
		const pd: ApproveDeps = { ...base, tellModel: (content, details) => void held.push([content, details]) };
		const ac = new AbortController();
		controllers.add(ac);
		const seen = new Set<string>();
		const n = Math.min(total, PATROL_MAX);
		const c = { approved: 0, success: 0, skipped: 0, discarded: 0 };
		let stop: Reply | undefined;
		let id = firstId;
		try {
			for (;;) {
				if (ac.signal.aborted) {
					stop = { text: "中断した", level: "info" };
					break;
				}
				seen.add(id);
				const pl = await planApproval(id, ctx, pd, ac.signal);
				if (!pl.ok) {
					stop = pl.reply;
					break;
				}
				const snap = pl.snapshot;
				const r = await pd.dialog(async () => {
					if (ac.signal.aborted) return undefined;
					pd.bell();
					return presentConfirm(ctx.ui, {
						title: `巡回 ${seen.size}/${n}: ${snap.adapter.label}の承認 (${id})\n\n${snap.summary}`,
						options: [CHOICE_PATROL_STOP, CHOICE_PATROL_APPROVE, VIEW_FULL, CHOICE_PATROL_NEXT, CHOICE_PATROL_DISCARD],
						signal: ac.signal,
						viewFull: { title: `${snap.adapter.label}: 全文 (読むだけ。閉じると確認に戻る)`, text: () => snap.view },
					});
				});
				// Esc・中断・エラー・期限・未知の選択は、「保留のまま次へ」とは別扱いで全体を止める (B10)
				const choice = r?.choice;
				if (!r || r.error || r.timedOut || choice === undefined || ac.signal.aborted) {
					stop = { text: "中断した (次の画面は開かない)", level: "info" };
					break;
				}
				if (choice === CHOICE_PATROL_STOP) {
					stop = { text: "ここで終えた (残りは保留のまま)", level: "info" };
					break;
				}
				if (choice === CHOICE_PATROL_NEXT) c.skipped++;
				else if (choice === CHOICE_PATROL_DISCARD) {
					const d = discardOp(cwd, id, snap.oid, deps.settings().limits);
					if (!d.ok) {
						stop = { text: d.reason, level: "warning" };
						break;
					}
					c.discarded++;
					base.notify(redact(`破棄した: ${id}`), "info");
				} else if (choice === CHOICE_PATROL_APPROVE) {
					c.approved++;
					// 実行中の Esc: 実行は止めない (保護ブランチへの統合の途中で止めるほうが危険)。この件の後で巡回を止め、次の画面を開かない (B10)
					let escWhileRunning = false;
					let unsubscribe: (() => void) | undefined;
					try {
						unsubscribe = ctx.ui?.onTerminalInput?.((data: string) => {
							if (ESC_KEY.test(String(data))) escWhileRunning = true;
							return undefined;
						});
					} catch {}
					let ex: Awaited<ReturnType<typeof executeApproval>>;
					try {
						ex = await executeApproval(snap, ctx, pd, ac.signal);
					} finally {
						try {
							unsubscribe?.();
						} catch {}
					}
					base.notify(redact(ex.reply.text), ex.reply.level);
					if (ex.kind === "refused") {
						c.approved--; // 実行していない
						stop = ex.reply;
						break;
					}
					if (ex.outcome === "success") c.success++;
					if (!(ex.outcome === "success" && ex.saved && !ex.cleanup)) {
						stop = { text: `止めた: ${ex.outcome}${ex.saved ? "" : "・結果を保存できていない"}${ex.cleanup ? "・後片付けが残っている" : ""}`, level: ex.reply.level === "info" ? "warning" : ex.reply.level };
						break;
					}
					if (escWhileRunning) {
						stop = { text: "実行中に Esc が押されたので、ここで終えた (実行した操作は止めていない)", level: "warning" };
						break;
					}
				} else {
					stop = { text: "中断した (未知の選択)", level: "info" };
					break;
				}
				refresh(ctx);
				if (ac.signal.aborted) {
					stop = { text: "中断した", level: "info" };
					break;
				}
				if (seen.size >= PATROL_MAX) {
					stop = { text: `上限 (${PATROL_MAX} 件) に達した`, level: "info" };
					break;
				}
				const next = pickCandidates(cwd, "approve", pd).find((x) => !seen.has(x.id));
				if (!next) break;
				id = next.id;
			}
		} catch (e) {
			stop = { text: `巡回を止めた (内部エラー: ${(e as Error)?.message ?? e})`, level: "error" };
		} finally {
			controllers.delete(ac);
			refresh(ctx);
			// 溜めたモデルへの通知を、溜めた順に出す (正常・止めた・例外のどれでも)
			for (const [content, details] of held) {
				try {
					base.tellModel(content, details);
				} catch {}
			}
		}
		let left = 0;
		try {
			left = countPending(cwd, deps.settings().limits);
		} catch {}
		const head = `巡回を終えた (${seen.size} 件を見た): 承認して実行 ${c.approved} (成功 ${c.success})・見送り ${c.skipped}・破棄 ${c.discarded}`;
		const parts = [head, stop ? `止めた理由: ${stop.text}` : "", `残りの保留: ${left} 件`].filter(Boolean);
		return { text: parts.join("\n"), level: stop && stop.level !== "info" ? stop.level : "info" };
	}

	async function run(args: string, ctx: any): Promise<Reply> {
		const cwd: string = ctx.cwd ?? process.cwd();
		lastCtx = ctx;
		const [sub0 = "list", rawArg = "", ...rest] = String(args ?? "").trim().split(/\s+/);
		let sub = sub0;
		let arg = rawArg.startsWith(PENDING_PREFIX) ? rawArg.slice(PENDING_PREFIX.length) : rawArg;
		let full = rawArg.startsWith("refs/") ? rawArg : `${PENDING_PREFIX}${rawArg}`;
		const limits = deps.settings().limits;
		const info = (text: string): Reply => ({ text, level: "info" });
		const tui = ctx.mode === "tui" && ctx.hasUI;
		const typedId = rawArg !== ""; // 利用者が ID を打ったときは巡回しない
		if (sub === "" && tui) {
			// 引数なし (TUI): 候補から選び、状態に合った操作の既存の経路へ進む。0 件は従来の一覧
			const cands = pickCandidates(cwd, "hub", deps.approveDeps(ctx));
			if (cands.length > 0) {
				const c = await chooseId(ctx, deps.approveDeps(ctx), "hub", cands);
				if (!c.ok) return c.reply;
				sub = c.act ?? "show";
				arg = c.id;
				full = `${PENDING_PREFIX}${arg}`;
			}
		}
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
		if (sub === "approve" && arg && tui && !typedId) {
			const total = pickCandidates(cwd, "approve", deps.approveDeps(ctx)).length;
			if (total >= 2) return patrol(arg, total, ctx);
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
		description: "引数なしで選んで進む / 保留した操作の一覧・表示・承認・破棄: /pending [list | show [<id>] | approve [<id>] | resolve [<id>] [<結果>] | drop [<id>] | unlock | log] (<id> は末尾 3 桁以上でもよい)",
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
