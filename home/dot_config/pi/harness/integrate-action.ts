// git_integrate (feature ブランチを保護ブランチへ squash 統合) の、非同期承認のアダプタ (CHG-0055 の P8)。
// 要求側 (capture) と承認側 (plan・recheck・execute) を持つ。計算は integrate-plan.ts・integrate-exec.ts に任せ、pi には触らない。
// 契約: 記録は信頼しない入力。承認する側は、現在の設定・現在の状態で計画を作り直す (記録の request.cwd は権限の根拠にしない)。
// 要求時の前提と食い違っても、画面に「変わった点」として出して利用者が見て決める。承認した計画との同一性は recheck が確かめる。
// see docs/change/0055-async-approval.md
//
// node の型除去でそのまま動く書き方だけを使う (enum・namespace は使わない)。
import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { realpathSync } from "node:fs";
import type { ActionSpec, PendingAdapter } from "./actions.ts";
import { cellWidth, clipCells, fitWidth, sanitizeForDisplay, termSize } from "./confirm-view.ts";
import { computeIntegrationPlan, type IntegratePlan, type PlanProfile } from "./integrate-plan.ts";
import { executeIntegrationOutcome } from "./integrate-exec.ts";
import type { ApprovalAdapter } from "./pending-approve.ts";
import type { Json, OpRecord } from "./pending-ops.ts";
import { listOps, readOp } from "./pending-ops.ts";
import { repoTargetEnv } from "./pending-store.ts";

/** enabled は統合のキルスイッチ。省略時は有効 (従来どおり)。false のとき、要求・承認のアダプタは拒否する */
export type IntegrateCfg = {
	target: string;
	/** 統合元の接頭辞 (既定 feature/ と bugfix/)。省略した設定は既定として扱う */
	sourcePrefixes: readonly string[];
	protectedRefs: readonly string[];
	riskPaths: readonly string[];
	/** cwd ごとに解決したプロジェクト設定 (pi.json) の情報。cwd を渡さなかったときは無い */
	profile?: PlanProfile;
	enabled?: () => boolean;
};
/** 設定は呼ぶたびに読む (承認の時点の現在の設定で計画を作るため)。関数は対象の cwd ごとに解決する */
export type CfgSource = IntegrateCfg | ((cwd?: string) => IntegrateCfg);

export type Cleanup = "none" | "branch" | "branch_and_worktree";
const CLEANUPS: readonly string[] = ["none", "branch", "branch_and_worktree"];
const WIDTH = 46; // 端末の幅が不明 (試験・RPC・パイプ) のときの従来値。分かれば fitWidth が広げる
const HANG = "  ";
const MAX_SUBJECT_LINES = 3;
const DEFAULT_MESSAGE_BUDGET = 8;
const MIN_MESSAGE_BUDGET = 3;
const MAX_MESSAGE_BUDGET = 24;
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

const cfgOf = (c: CfgSource, cwd?: string): IntegrateCfg => (typeof c === "function" ? c(cwd) : c);
const digestOf = (s: string): string => createHash("sha256").update(s).digest("hex");
const oneLine = (s: unknown, max = 200): string => sanitizeForDisplay(String(s)).replace(/\s+/g, " ").trim().slice(0, max);
const short = (oid: string): string => oid.slice(0, 8);
const DISABLED = "git_integrate は無効 (設定で止められている)";

export type HereResult = { ok: true; here: boolean } | { ok: false; reason: string };

/** cwd の common-dir・git-dir・show-toplevel を、実体のパスで観測する。失敗は理由の文字列 */
function identityOf(cwd: string, env?: NodeJS.ProcessEnv): string[] | string {
	const r = spawnSync("git", ["rev-parse", "--path-format=absolute", "--git-common-dir", "--git-dir", "--show-toplevel"], {
		cwd,
		encoding: "utf8",
		timeout: 15000,
		env: { ...repoTargetEnv(env ?? process.env), GIT_OPTIONAL_LOCKS: "0", GIT_TERMINAL_PROMPT: "0" },
	});
	if (r.error || r.status !== 0) return `git で ${oneLine(cwd, 120)} を観測できない`;
	const lines = String(r.stdout).split("\n").filter((l) => l !== "");
	if (lines.length !== 3) return `git の観測が不正: ${oneLine(cwd, 120)}`;
	try {
		return lines.map((p) => realpathSync(p));
	} catch {
		return `パスを正規化できない: ${oneLine(cwd, 120)}`;
	}
}

/** 3 つの識別子 (common-dir・git-dir・toplevel) が、個別に全部一致するか。長さが違えば false */
export function sameIdentity(a: string[], b: string[]): boolean {
	return a.length === b.length && a.every((v, i) => v === b[i]);
}

/**
 * いまの cwd が、統合先の作業ツリーそのものか。common-dir・git-dir・show-toplevel の 3 つが全部一致したときだけ here: true。
 * パスの配下判定は使わない (feature の worktree は本体の配下にあるので、誤って許可する)。観測できなければ ok: false。
 * 統合先自体は作業ツリーのルートでなければならない (削除されて親へ遡った・サブディレクトリを指すときは ok: false)。cwd はサブディレクトリでよい。
 */
export function isTargetWorktree(cwd: string, targetWorktree: string, env?: NodeJS.ProcessEnv): HereResult {
	const a = identityOf(cwd, env);
	if (typeof a === "string") return { ok: false, reason: a };
	const b = identityOf(targetWorktree, env);
	if (typeof b === "string") return { ok: false, reason: b };
	try {
		if (realpathSync(targetWorktree) !== b[2]) return { ok: false, reason: `targetWorktree が作業ツリーのルートでない: ${oneLine(targetWorktree, 120)}` };
	} catch {
		return { ok: false, reason: `パスを正規化できない: ${oneLine(targetWorktree, 120)}` };
	}
	return { ok: true, here: sameIdentity(a, b) };
}
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
			if (cfgOf(cfg).enabled?.() === false) return { ok: false, reason: DISABLED };
			const cleanup = cleanupOf(values);
			if (!cleanup) return { ok: false, reason: `cleanup が不正: ${oneLine(values.cleanup, 40)} (none|branch|branch_and_worktree)` };
			const c = cfgOf(cfg, cwd);
			const plan = computeIntegrationPlan({
				cwd,
				source: values.source ?? "",
				target: c.target,
				message: values.message ?? "",
				protectedRefs: c.protectedRefs,
				sourcePrefixes: c.sourcePrefixes,
				profile: c.profile,
				riskPaths: c.riskPaths,
				env,
				// 要求時は統合先の作業ツリーを調べない (サンドボックスで読めず誤検知する)。承認側の再計画と実行器の precheck が検査する
				// see docs/change/0055-async-approval.md
				checkTargetWorktree: false,
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
				profileBlob: plan.profile.blob,
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
	// 古い記録 (キー無し) で誤って「違う」と出さないよう、null に寄せて比べる
	if (premise.target !== undefined && premise.target !== plan.target.ref) {
		out.push(`統合先が要求時と違う (${oneLine(branchName(String(premise.target)), 80)}→${oneLine(branchName(plan.target.ref), 80)})`);
	}
	if ((premise.profileBlob ?? null) !== (plan.profile.blob ?? null)) out.push(`${PROFILE_NOTE} が要求時と違う`);
	return out;
}

const PROFILE_NOTE = "プロジェクト設定 (pi.json)";

/** プロジェクト設定が「有効で既定と違う」「無効」のときだけの行 (設定が無いときは空)。診断は固定のコードだけ。
 * split=true は統合先・接頭辞の行を別行にする (summary は幅が狭く、一行だと切れる) */
function profileLines(plan: IntegratePlan, split: boolean): string[] {
	const p = plan.profile;
	if (p.diagnostics.length) {
		const codes = [...new Set(p.diagnostics.map((d) => oneLine(d.code, 40)))].join(",");
		return split ? [`${PROFILE_NOTE} は無効`, `  (${codes})`, "  全体の既定で処理"] : [`${PROFILE_NOTE} は無効 (${codes})。全体の既定で処理`];
	}
	if (!p.overridden) return [];
	const prefixes = plan.sourcePrefixes.map((x) => oneLine(x, 64)).join(" ");
	const detail = `統合先 ${oneLine(branchName(plan.target.ref), 80)}・統合元の接頭辞 ${prefixes}`;
	return split ? [`${PROFILE_NOTE}:`, `  ${detail}`] : [`${PROFILE_NOTE}: ${detail}`];
}

/** 統合元が未統合の他の feature を含むときだけの警告 1 行 (表示だけ。承認の判断・記録・再検査には使わない)。pend は ref → 保留 ID (未承認のもの) */
function stackedLine(plan: IntegratePlan, pend: Map<string, string> = new Map()): string | null {
	if (!plan.stacked?.length) return null;
	const names = plan.stacked.map((r) => {
		const id = pend.get(r);
		return `${oneLine(branchName(r), 80)}${id ? ` (保留 …${id} が未承認)` : ""}`;
	});
	return `含む他の feature (未統合): ${names.join(", ")} — この統合に含まれる。先に個別に統合すると、この統合が衝突することがある`;
}

/** 承認画面の summary は幅が狭く 1 行だと切れるので、保留が見つかったときは行を分ける */
function stackedSummaryLines(plan: IntegratePlan, pend: Map<string, string>): string[] {
	if (!plan.stacked?.length) return [];
	if (!pend.size) return [stackedLine(plan) as string];
	return [
		"含む他の feature (未統合):",
		...plan.stacked.map((r) => `  ${oneLine(branchName(r), 80)}${pend.get(r) ? ` (保留 …${pend.get(r)} が未承認)` : ""}`),
		"  この統合に含まれる。先に個別に統合すると、この統合が衝突することがある",
	];
}

/** 状態が pending の git_integrate の保留のうち、統合元が stacked の ref と一致するもの (ref → ID の末尾 4 桁)。読めなければ空 (表示だけの情報) */
function pendingStacked(plan: IntegratePlan, cwd: string): Map<string, string> {
	const out = new Map<string, string>();
	if (!plan.stacked?.length) return out;
	try {
		const want = new Set(plan.stacked);
		for (const e of listOps(cwd).entries) {
			if (e.state !== "pending" || e.kind !== "action") continue;
			const r = readOp(cwd, e.id);
			if (!r.ok || r.record.action !== "git_integrate") continue;
			const src = r.record.premise.source;
			const ref = typeof src === "string" ? src : `refs/heads/${branchName(r.record.params.source ?? "")}`;
			const tail = e.id.replace(/\D/g, "").slice(-4);
			if (want.has(ref) && tail && !out.has(ref)) out.set(ref, tail);
		}
	} catch {
		return new Map();
	}
	return out;
}

/** 承認の 4 択の画面に出すメッセージの行。空行を除く全行を、幅で折り返して (2 スペースのぶら下がり) 出す。
 * 件名 (1 行目) は最大 3 行まで必ず見せ、あふれるときだけ第 3 行を … で切る。本文は予算までで、超えたら最後に「残り N 行」を出す。全文は「全文を見る」 */
function messageLines(message: string, width: number, budget: number): string[] {
	const rows = sanitizeForDisplay(message)
		.split(/\r?\n/)
		.map((l) => l.trim())
		.filter((l) => l !== "");
	const label = "メッセージ: ";
	const subject = wrapHang(label, rows[0] ?? "(空)", width, MAX_SUBJECT_LINES);
	const body = rows.slice(1).flatMap((l) => wrapHang(HANG, l, width, Infinity));
	const room = Math.max(0, budget - subject.length);
	const out = [...subject, ...body.slice(0, room)];
	if (body.length > room) out.push(`… 残り ${body.length - room} 行 (「全文を見る」で全文)`);
	return out;
}

/** prefix を先頭に、続きの行は 2 スペースのぶら下がりで、幅 (セル) で折り返す。maxLines を超えると最終行を … で切る */
function wrapHang(prefix: string, text: string, width: number, maxLines: number): string[] {
	const lines: string[] = [];
	let cur = prefix;
	let w = cellWidth(prefix);
	let started = false; // cur に本文の文字が入ったか
	const chars = Array.from(text);
	for (let i = 0; i < chars.length; i++) {
		const cw = cellWidth(chars[i]);
		if (w + cw > width && started) {
			if (lines.length + 1 >= maxLines) {
				// 最終行: 残りを全部つなげて、幅に合わせて … で切る
				const rest = chars.slice(i).join("");
				lines.push(clipCells(`${cur}${rest}`, width));
				return lines;
			}
			lines.push(cur);
			cur = HANG;
			w = cellWidth(HANG);
			started = false;
		}
		cur += chars[i];
		w += cw;
		started = true;
	}
	lines.push(cur);
	return lines;
}

function summaryOf(plan: IntegratePlan, cleanup: Cleanup, changes: string[], pend: Map<string, string>): string {
	const { rows } = termSize();
	const width = fitWidth(WIDTH, 2);
	const head: string[] = [`${sanitizeForDisplay(branchName(plan.source.ref))} → ${sanitizeForDisplay(branchName(plan.target.ref))} (squash)`, "衝突: なし"];
	head.push(`${plan.stats.commits} コミット・${plan.stats.files} ファイル (+${plan.stats.additions}/-${plan.stats.deletions})`);
	head.push(...profileLines(plan, true));
	const tail: string[] = [];
	if (cleanup !== "none") tail.push(`後片付け: ${cleanup === "branch" ? "ブランチ削除" : "ブランチと worktree 削除"}`);
	tail.push(...stackedSummaryLines(plan, pend));
	if (plan.risks.length) {
		tail.push(`リスクのあるパス (${plan.risks.length} 件):`);
		for (const r of plan.risks.slice(0, MAX_RISKS)) tail.push(`  ${oneLine(r.path, 120)}`);
		if (plan.risks.length > MAX_RISKS) tail.push(`  ほか ${plan.risks.length - MAX_RISKS} 件`);
	} else tail.push("リスクのあるパス: なし");
	if (changes.length) {
		tail.push("要求時から変わった点:");
		for (const c of changes) tail.push(`  ${c}`);
	}
	// 予算: 他の行を先に作り、選択肢 4 つとタイトルを押し出さないように残りを割り当てる (行数不明は固定)
	const others = head.length + tail.length;
	const budget = rows === undefined ? DEFAULT_MESSAGE_BUDGET : Math.min(MAX_MESSAGE_BUDGET, Math.max(MIN_MESSAGE_BUDGET, rows - others - 8));
	const lines = [...head, ...messageLines(plan.message, width, budget), ...tail];
	return lines.map((l) => clipCells(l, width)).join("\n");
}

function viewOf(plan: IntegratePlan, cleanup: Cleanup, changes: string[], pend: Map<string, string>): string {
	const out = [
		`${sanitizeForDisplay(plan.source.ref)} (${short(plan.source.oid)}) → ${sanitizeForDisplay(plan.target.ref)} (${short(plan.target.oid)})  squash`,
		`統合先の worktree: ${oneLine(plan.targetWorktree ?? "(なし)", 300)}`,
		`後片付け: ${cleanup}`,
		...profileLines(plan, false),
		...(stackedLine(plan, pend) ? [stackedLine(plan, pend) as string] : []),
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
		if (cfgOf(cfg).enabled?.() === false) return { ok: false as const, reason: DISABLED };
		const cleanup = cleanupOf(rec.params);
		if (!cleanup) return { ok: false as const, reason: `cleanup が不正: ${oneLine(rec.params.cleanup, 40)}` };
		const c = cfgOf(cfg, cwd);
		const plan = computeIntegrationPlan({
			cwd,
			source: rec.params.source ?? "",
			target: c.target,
			message: rec.params.message ?? "",
			protectedRefs: c.protectedRefs,
			sourcePrefixes: c.sourcePrefixes,
			profile: c.profile,
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
			const pend = pendingStacked(r.plan, env.cwd);
			return { ok: true, plan: approved, summary: summaryOf(r.plan, r.cleanup, changes, pend), view: viewOf(r.plan, r.cleanup, changes, pend) };
		},
		recheck: async (p, env) => {
			const a = p as Approved;
			const r = compute({ params: { source: a.plan.source.ref, message: a.plan.message, cleanup: a.cleanup } }, env.cwd, env.env);
			if (!r.ok) return r;
			const n = r.plan;
			if (n.target.ref !== a.plan.target.ref) return { ok: false, reason: "承認した後に、統合先のブランチが変わった (設定が変わった)" };
			if (n.profile.blob !== a.plan.profile.blob) return { ok: false, reason: "承認した後に、プロジェクト設定 (pi.json) が変わった" };
			if (n.target.oid !== a.plan.target.oid) return { ok: false, reason: "承認した後に、統合先が進んだ" };
			if (n.source.oid !== a.plan.source.oid) return { ok: false, reason: "承認した後に、統合元が進んだ" };
			if (n.resultTree !== a.plan.resultTree) return { ok: false, reason: "承認した後に、結果の内容が変わった" };
			if (n.targetWorktree !== a.plan.targetWorktree) return { ok: false, reason: "承認した後に、統合先の worktree が変わった" };
			return { ok: true };
		},
		execute: async (p, env, signal) => {
			const a = p as Approved;
			const r = await executeIntegrationOutcome({ plan: a.plan, cleanup: a.cleanup, approverCwd: env.cwd, env: env.env, signal, protectedRefs: cfgOf(cfg).protectedRefs });
			if (r.body.outcome === "unknown") {
				// 証拠は、画面に出す前に制御文字を可視化し、件数・長さを制限する
				return { body: { ...r.body, evidence: r.body.evidence.slice(0, 10).map((e) => oneLine(e, 300)) }, termination: r.termination };
			}
			return r;
		},
		// ok: false はそのまま返す (許可に読み替えるのは呼び出し側の責任ではない)
		runsHere: (p, env) => isTargetWorktree(env.cwd, (p as Approved).plan.targetWorktree ?? "", env.env),
		exclusive: true,
	};
}
