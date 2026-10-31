// git_integrate (feature ブランチを保護ブランチへ squash 統合) の、非同期承認のアダプタ (CHG-0055 の P8)。
// 要求側 (capture) と承認側 (plan・recheck・execute) を持つ。計算は integrate-plan.ts・integrate-exec.ts に任せ、pi には触らない。
// 契約: 記録は信頼しない入力。承認する側は、現在の設定・現在の状態で計画を作り直す (記録の request.cwd は権限の根拠にしない)。
// 要求時の前提と食い違っても、画面に「変わった点」として出して利用者が見て決める。承認した計画との同一性は recheck が確かめる。
// see docs/change/0055-async-approval.md
//
// node の型除去でそのまま動く書き方だけを使う (enum・namespace は使わない)。
import { createHash } from "node:crypto";
import type { ActionSpec, PendingAdapter } from "./actions.ts";
import { clipCells, sanitizeForDisplay } from "./confirm-view.ts";
import { computeIntegrationPlan, type IntegratePlan } from "./integrate-plan.ts";
import { executeIntegration } from "./integrate-exec.ts";
import type { ApprovalAdapter } from "./pending-approve.ts";
import type { Json, OpRecord, ResultBody } from "./pending-ops.ts";

export type IntegrateCfg = { target: string; protectedRefs: readonly string[]; riskPaths: readonly string[] };
/** 設定は呼ぶたびに読む (承認の時点の現在の設定で計画を作るため) */
export type CfgSource = IntegrateCfg | (() => IntegrateCfg);

export type Cleanup = "none" | "branch" | "branch_and_worktree";
const CLEANUPS: readonly string[] = ["none", "branch", "branch_and_worktree"];
const WIDTH = 46;
const MAX_RISKS = 8;
const MAX_FILES = 40;

/** 組込みの操作定義。generate.py の [[pi.actions]] 表には載せられない (argv で実行する操作ではないため、argv は空) */
export const GIT_INTEGRATE_SPEC: ActionSpec = {
	id: "git_integrate",
	label: "保護ブランチへの統合 (squash)",
	argv: [],
	fields: {
		source: { type: "line", max_chars: 200 },
		message: { type: "text", content: true, max_chars: 1200 },
		cleanup: { type: "line", max_chars: 30, optional: true },
	},
	replaces: [],
	preview: "none",
};

const cfgOf = (c: CfgSource): IntegrateCfg => (typeof c === "function" ? c() : c);
const digestOf = (s: string): string => createHash("sha256").update(s).digest("hex");
const oneLine = (s: unknown, max = 200): string => sanitizeForDisplay(String(s)).replace(/\s+/g, " ").trim().slice(0, max);
const short = (oid: string): string => oid.slice(0, 8);
const branchName = (ref: string): string => ref.replace(/^refs\/heads\//, "");

function cleanupOf(values: Record<string, string>): Cleanup | null {
	const c = values.cleanup ?? "none";
	return CLEANUPS.includes(c) ? (c as Cleanup) : null;
}

const REFUSAL_LABEL: Record<string, string> = {
	conflict: "衝突する",
	already_merged: "すでに統合済み",
	dirty_target_worktree: "統合先の worktree に未コミットの変更がある",
};

function refusalText(r: { code: string; reason: string; files?: string[] }): string {
	const files = r.files?.length ? ` (${r.files.slice(0, 5).map((f) => oneLine(f, 80)).join(", ")})` : "";
	return `統合できない [${r.code}]: ${REFUSAL_LABEL[r.code] ?? oneLine(r.reason, 200)}${files}`;
}

/** 要求側。保留の記録に入れる前提を取る。拒否される統合は、保留しない (従来どおり) */
export function integrateRequestAdapter(cfg: CfgSource): PendingAdapter {
	return {
		capture: async ({ cwd, values, env }) => {
			const cleanup = cleanupOf(values);
			if (!cleanup) return { ok: false, reason: `cleanup が不正: ${oneLine(values.cleanup, 40)} (none|branch|branch_and_worktree)` };
			const c = cfgOf(cfg);
			const plan = computeIntegrationPlan({
				cwd,
				source: values.source ?? "",
				target: c.target,
				message: values.message ?? "",
				protectedRefs: c.protectedRefs,
				riskPaths: c.riskPaths,
				env,
			});
			if (!plan.ok) return { ok: false, reason: refusalText(plan) };
			const premise: Record<string, Json> = {
				kind: "git_integrate",
				source: plan.source.ref,
				target: plan.target.ref,
				sourceOid: plan.source.oid,
				targetOid: plan.target.oid,
				resultTree: plan.resultTree,
				mergeBase: plan.mergeBase,
				cleanup,
				messageDigest: digestOf(plan.message),
			};
			return plan.targetWorktree ? { ok: true, premise, worktree: plan.targetWorktree } : { ok: true, premise };
		},
	};
}

/** 承認した (表示した) 計画。recheck と execute が使う */
type Approved = { plan: IntegratePlan; cleanup: Cleanup };

/** 要求時の前提と今の計画の食い違い */
function changesOf(premise: Record<string, Json>, plan: IntegratePlan): string[] {
	const out: string[] = [];
	if (premise.targetOid !== plan.target.oid) out.push(`統合先が進んだ (${short(String(premise.targetOid ?? "?"))}→${short(plan.target.oid)})`);
	if (premise.sourceOid !== plan.source.oid) out.push(`統合元が進んだ (${short(String(premise.sourceOid ?? "?"))}→${short(plan.source.oid)})`);
	if (premise.resultTree !== plan.resultTree) out.push("結果の内容が要求時と変わった");
	if (premise.messageDigest !== digestOf(plan.message)) out.push("メッセージが要求時と違う");
	return out;
}

function summaryOf(plan: IntegratePlan, cleanup: Cleanup, changes: string[]): string {
	const lines: string[] = [`${branchName(plan.source.ref)} → ${branchName(plan.target.ref)} (squash)`, "衝突: なし"];
	lines.push(`${plan.stats.commits} コミット・${plan.stats.files} ファイル (+${plan.stats.additions}/-${plan.stats.deletions})`);
	if (cleanup !== "none") lines.push(`後片付け: ${cleanup === "branch" ? "ブランチ削除" : "ブランチと worktree 削除"}`);
	if (plan.risks.length) {
		lines.push(`リスクのあるパス (${plan.risks.length} 件):`);
		for (const r of plan.risks.slice(0, MAX_RISKS)) lines.push(`  ${oneLine(r.path, 120)}`);
		if (plan.risks.length > MAX_RISKS) lines.push(`  ほか ${plan.risks.length - MAX_RISKS} 件`);
	} else lines.push("リスクのあるパス: なし");
	if (changes.length) {
		lines.push("要求時から変わった点:");
		for (const c of changes) lines.push(`  ${c}`);
	}
	return lines.map((l) => clipCells(l, WIDTH)).join("\n");
}

function viewOf(plan: IntegratePlan, cleanup: Cleanup, changes: string[]): string {
	const out = [
		`${plan.source.ref} (${short(plan.source.oid)}) → ${plan.target.ref} (${short(plan.target.oid)})  squash`,
		`統合先の worktree: ${oneLine(plan.targetWorktree ?? "(なし)", 300)}`,
		`後片付け: ${cleanup}`,
		changes.length ? `要求時から変わった点: ${changes.join(" / ")}` : "要求時から変わった点: なし",
		"",
		"メッセージ:",
		sanitizeForDisplay(plan.message),
		"",
		`変更ファイル (${plan.stats.files} 件):`,
	];
	for (const f of plan.files.slice(0, MAX_FILES)) out.push(`  ${f.status} ${oneLine(f.path, 200)}  ${f.add === null ? "bin" : `+${f.add}/-${f.del}`}`);
	if (plan.files.length > MAX_FILES) out.push(`  ほか ${plan.files.length - MAX_FILES} 件`);
	if (plan.risks.length) {
		out.push("", "リスクのあるパス:");
		for (const r of plan.risks) out.push(`  ${oneLine(r.path, 200)}  ${oneLine(r.reason, 100)}`);
	}
	return out.join("\n");
}

/** 承認側。記録は信頼しない入力として、params を検証し、承認する pi の cwd・現在の設定・現在の状態で計画を作り直す */
export function integrateApprovalAdapter(cfg: CfgSource): ApprovalAdapter {
	const compute = (rec: Pick<OpRecord, "params">, cwd: string, env: NodeJS.ProcessEnv) => {
		const cleanup = cleanupOf(rec.params);
		if (!cleanup) return { ok: false as const, reason: `cleanup が不正: ${oneLine(rec.params.cleanup, 40)}` };
		const c = cfgOf(cfg);
		const plan = computeIntegrationPlan({
			cwd,
			source: rec.params.source ?? "",
			target: c.target,
			message: rec.params.message ?? "",
			protectedRefs: c.protectedRefs,
			riskPaths: c.riskPaths,
			env,
		});
		if (!plan.ok) return { ok: false as const, reason: refusalText(plan) };
		return { ok: true as const, plan, cleanup };
	};
	return {
		action: "git_integrate",
		label: "保護ブランチへの統合",
		plan: async (rec, env) => {
			const r = compute(rec, env.cwd, env.env);
			if (!r.ok) return r;
			const changes = changesOf(rec.premise, r.plan);
			const approved: Approved = { plan: r.plan, cleanup: r.cleanup };
			return { ok: true, plan: approved, summary: summaryOf(r.plan, r.cleanup, changes), view: viewOf(r.plan, r.cleanup, changes) };
		},
		recheck: async (p, env) => {
			const a = p as Approved;
			const r = compute({ params: { source: a.plan.source.ref, message: a.plan.message, cleanup: a.cleanup } }, env.cwd, env.env);
			if (!r.ok) return r;
			const n = r.plan;
			if (n.target.oid !== a.plan.target.oid) return { ok: false, reason: "承認した後に、統合先が進んだ" };
			if (n.source.oid !== a.plan.source.oid) return { ok: false, reason: "承認した後に、統合元が進んだ" };
			if (n.resultTree !== a.plan.resultTree) return { ok: false, reason: "承認した後に、結果の内容が変わった" };
			if (n.targetWorktree !== a.plan.targetWorktree) return { ok: false, reason: "承認した後に、統合先の worktree が変わった" };
			return { ok: true };
		},
		execute: async (p, env, signal) => {
			const a = p as Approved;
			const body: ResultBody = await executeIntegration({ plan: a.plan, cleanup: a.cleanup, approverCwd: env.cwd, env: env.env, signal });
			if (body.outcome === "unknown") {
				// 証拠は、画面に出す前に制御文字を可視化し、件数・長さを制限する
				return { ...body, evidence: body.evidence.slice(0, 10).map((e) => oneLine(e, 300)) };
			}
			return body;
		},
	};
}
