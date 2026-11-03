// `/pending` (利用者専用。モデルは呼べない registerCommand だけ)。
// 承認が取れず退避した git commit (旧形式) の list / show / drop と、フッターの件数表示だけを持つ。
// 承認・巡回・resolve・unlock・設定は、旧い統合経路の撤去 (CHG-0062 の A5) で外した。
// pi の API (pi・ctx) は注入する (試験できるように。接続は index.ts)。
// see docs/change/0062-pr-hub-simplify.md
import { PENDING_PREFIX, dropPending, isLegacyEntry, listPending, showPending } from "./pending-store.ts";

export type Reply = { text: string; level: "info" | "warning" | "error" };

export type PendingCommandDeps = {
	redact?: (text: string) => string;
	/** 利用者の操作を受けたとき (不在の解除など) */
	touch?: () => void;
};

export const USAGE = "/pending [list | show <id> | drop <id>]  (<id> は `/pending list` の先頭の列)";

/** 旧形式の退避の一覧 (取り込み済み・重複は reconcile が片付ける) */
function legacyEntries(cwd: string) {
	return listPending(cwd).filter((e) => isLegacyEntry(cwd, e.oid));
}

/** フッターの「📥 保留 N 件」を更新する。UI があるときだけ。0 件なら消す */
export function updatePendingFooter(ctx: any): void {
	if (!ctx?.hasUI || typeof ctx.ui?.setStatus !== "function") return;
	let n = 0;
	try {
		n = legacyEntries(String(ctx.cwd ?? process.cwd())).length;
	} catch {}
	ctx.ui.setStatus("pending", n > 0 ? `📥 保留 ${n} 件` : undefined);
}

function legacyText(cwd: string): string {
	const all = legacyEntries(cwd);
	return all.length === 0 ? "" : all.map((e) => `${e.ref.slice(PENDING_PREFIX.length)}  ${e.oid.slice(0, 7)}  ${e.subject}  (${e.branch || "-"})`).join("\n");
}

export function registerPendingCommand(pi: any, deps: PendingCommandDeps): { refresh: (ctx: any) => void } {
	const redact = deps.redact ?? ((t: string) => t);
	const refresh = (ctx: any) => {
		// フッターは補助。更新で例外が出ても、本体を妨げない
		try {
			updatePendingFooter(ctx);
		} catch {}
	};

	function run(args: string, ctx: any): Reply {
		const cwd: string = ctx.cwd ?? process.cwd();
		const [sub = "list", rawArg = ""] = String(args ?? "").trim().split(/\s+/);
		const arg = rawArg.startsWith(PENDING_PREFIX) ? rawArg.slice(PENDING_PREFIX.length) : rawArg;
		const full = rawArg.startsWith("refs/") ? rawArg : `${PENDING_PREFIX}${rawArg}`;
		const info = (text: string): Reply => ({ text, level: "info" });
		if (sub === "" || sub === "list") return info(legacyText(cwd) || "退避したコミットは無い");
		if (sub === "show" && arg) return info(showPending(cwd, full) || "見つからない (/pending list で ref を確かめる)");
		if (sub === "drop" && arg) {
			return info(dropPending(cwd, full) ? `破棄した: ${full} (到達用の ref を外した。オブジェクトは git gc まで残る)` : "破棄できなかった (ref が無い・退避の ref ではない)");
		}
		return info(USAGE);
	}

	pi.registerCommand("pending", {
		description: "承認が取れず退避したコミットの一覧・表示・破棄: /pending [list | show <id> | drop <id>]",
		handler: async (args: string, ctx: any) => {
			deps.touch?.();
			let reply: Reply;
			try {
				reply = run(args, ctx);
			} catch (e) {
				reply = { text: `/pending の実行に失敗した: ${(e as Error)?.message ?? e}`, level: "error" };
			}
			ctx.ui?.notify?.(redact(reply.text), reply.level);
			refresh(ctx);
		},
	});
	return { refresh };
}
