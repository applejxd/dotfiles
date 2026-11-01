// 保存専用の操作 (CHG-0055 の P8c)。argv で実行せず、確認画面も出さず、前提を取って保留に保存するだけ。
// 実行は利用者の `/pending approve` だけが行う。
import { outcomeReason } from "./confirm-view.ts";
import { requestApproval } from "./pending-request.ts";
import type { Reason } from "./pending-ops.ts";
import type { PendingDeps } from "./actions.ts";

export const NATIVE_ACTIONS = new Set(["git_integrate"]);

export type NativeDeps = {
	child: boolean;
	env: NodeJS.ProcessEnv;
	pending?: PendingDeps;
};

type Ctx = { cwd: string; mode?: string; sessionManager?: { getSessionId?: () => unknown } };

/** 保存して、未実行の結果を Error (モデルには isError で返る) として投げる。成功も未実行なので、必ず throw */
export async function executeNative(action: string, values: Record<string, string>, ctx: Ctx, deps: NativeDeps, signal: AbortSignal | undefined): Promise<never> {
	const fail = (why: string): Error => new Error(`not approved: ${why}`);
	if (signal?.aborted) throw fail(outcomeReason("aborted"));
	let sessionId = "unknown";
	try {
		sessionId = String(ctx.sessionManager?.getSessionId?.() ?? "unknown");
	} catch {}
	const p = deps.pending;
	const r = await requestApproval(
		{ action, cwd: ctx.cwd, sessionId, values },
		{
			adapters: p?.adapters ?? {},
			enabled: p?.enabled === true,
			modes: p?.modes ?? [],
			mode: String(ctx.mode ?? ""),
			child: deps.child,
			save: p?.save,
			limits: p?.limits,
			env: deps.env,
			signal,
		},
	);
	if (!r.ok) throw fail(`保存できなかった。元の操作は実行していない (${r.code}: ${r.reason})。再試行しない。この操作に依存しない作業を続け、最後に「承認が取れなかった操作」として報告する`);
	p?.onSaved?.({ id: r.id, ref: r.ref, duplicate: r.duplicate, action, reason: "request" as Reason });
	throw fail(
		`元の操作は未実行。保留 ${r.id} に保存した${r.duplicate ? " (同じ要求が、すでに保留中)" : ""}。再試行しない。この操作に依存しない作業を続け、最後に「保留した操作」として報告する。利用者が統合先の worktree (本体) で \`/pending approve\` を実行し、一覧から選ぶと実行される (ID の末尾 4 桁を添えて \`/pending approve ${r.id.slice(-4)}\` と指定してもよい)`,
	);
}
