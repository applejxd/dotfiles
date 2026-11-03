// PR ビューアの統合 API（段 A2 の S）。人がブラウザで押した「統合する」の POST で、アプリが develop への統合を同期実行する。
// 設計: docs/change/0062-pr-hub-simplify.md §3.5・契約: .tmp/keep/prv-app/api-contract-merge.md。
// 統合の権限は live の HTTP リクエスト（Origin・ヘッダー・expect を満たす POST）だけ。ref の承認・保留・merge_request は権限として読まない。
// ここは git を直接動かさない（読み取りは git-view.ts、統合は merge.ts、レビュー記録は review-api.ts を通す）。
import { randomUUID } from "node:crypto";
import { readFileSync, statSync } from "node:fs";
import type { IncomingHttpHeaders } from "node:http";
import { ApiError, git } from "./git-view.ts";
import type { Repo } from "./git-view.ts";
import { executeMerge, planMerge } from "./merge.ts";
import type { Cleanup, Refusal } from "./merge.ts";
import { recordMerge, reviewHints } from "./review-api.ts";
import type { PrCtx } from "./review-api.ts";

export type MergeEnv = { rulesFile: string; testDelayMs: number };
/** PR の概要から、統合に要る数字（PrCtx に無いもの）。 */
export type MergePr = { commits: number; additions: number; deletions: number };
export type PostResult = { status: number; body: unknown };

const MAX_RISKS = 50;
const MAX_CONFLICTS = 100;
const MAX_RULES_BYTES = 1024 * 1024;
const MAX_RISK_PATTERNS = 200;
const MAX_PATTERN_CHARS = 200;
const APP_PREFIX = "apps/pr-viewer/";

const bad = (code: string, message: string): ApiError => new ApiError(400, code, message);

// ---- 要求の検査（HTTP 層から呼ぶ） ----

/** merge 系の POST の入口の検査。無効・Funnel・Origin の順に断る。通れば null。 */
export function mergeRequestError(headers: IncomingHttpHeaders, allowMerge: boolean): ApiError | null {
	if (!allowMerge) return new ApiError(403, "merge_disabled", "この画面からは統合できません（サーバが統合を許可していません）。");
	// Tailscale Funnel（公開）経由の要求には、プロキシがこのヘッダーを付ける。公開側からの統合は断る
	if (headers["tailscale-funnel-request"] !== undefined) {
		return new ApiError(403, "forbidden_funnel", "公開（Funnel）経由では統合できません。");
	}
	if (!strictOriginOk(headers.origin, headers.host)) return new ApiError(403, "forbidden_origin", "この Origin は許可されていません。");
	return null;
}

/** Origin は必須。`null`・形の悪い値・別のホストは断る（既存の書き込み系は Origin 無しを許すが、統合は許さない）。 */
export function strictOriginOk(origin: string | undefined, host: string | undefined): boolean {
	if (origin === undefined || origin === "null" || host === undefined) return false;
	try {
		const u = new URL(origin);
		return (u.protocol === "http:" || u.protocol === "https:") && u.origin === origin && u.host.toLowerCase() === host.toLowerCase();
	} catch {
		return false;
	}
}

// ---- 停止・排他 ----

let stopping = false;
/** 停止の開始。以後、新しい merge-plan・merge は始めない。 */
export function stopMerges(): void {
	stopping = true;
}

const gates = new Set<string>();

/** 統合の処理が、このリポジトリで実行中か（ジョブの起動の排他に使う。ジョブ側は merge_running で断る）。 */
export function mergeRunning(repoId: string): boolean {
	return gates.has(repoId);
}

let jobProbe: (repoId: string) => boolean = () => false;
/** ジョブが実行中（予約を含む）かを答える関数を登録する（job-api.ts が起動時に 1 回呼ぶ。循環 import を避ける）。 */
export function setJobProbe(fn: (repoId: string) => boolean): void {
	jobProbe = fn;
}

const JOB_RUNNING_TEXT = "pi への依頼（ジョブ）が実行中です。終わってから統合してください。";

/** リポジトリ単位の「待たない」排他。取れなければ 409 busy。別のプロセスとの排他は、統合器のロックファイルが担う。 */
async function gated<T>(repo: Repo, fn: () => Promise<T>): Promise<T> {
	if (stopping) throw new ApiError(503, "shutting_down", "サーバを停止しています。");
	if (gates.has(repo.repoId)) throw new ApiError(409, "busy", "別の統合の処理が実行中です。しばらくして再試行してください。");
	gates.add(repo.repoId);
	try {
		return await fn();
	} finally {
		gates.delete(repo.repoId);
	}
}

// ---- 統合の拒否理由（blockers） ----

// 旧経路（/pending）の撤去で、拒否する理由は無くなった。API の形（blockers）は変えないので、空の配列を返す
type Blocker = { code: string; message: string };

// ---- リスクのあるパス（表示用） ----

/** glob を正規表現に直す（harness の integrate-plan.ts と同じ規則: `**` は階層をまたぎ、`*` は 1 階層）。 */
function globToRegExp(glob: string): RegExp {
	let re = "";
	for (let i = 0; i < glob.length; i++) {
		const c = glob[i];
		if (c === "*") {
			if (glob[i + 1] === "*") {
				i++;
				if (glob[i + 1] === "/") {
					i++;
					re += "(?:.*/)?";
				} else re += ".*";
			} else re += "[^/]*";
		} else if (c === "?") re += "[^/]";
		else re += c.replace(/[.+^${}()|[\]\\]/g, "\\$&");
	}
	return new RegExp(`^${re}$`);
}

/** rules.json の judge.common.pi.integrate.risk_paths。読めない・形が違うときは null（「リスクなし」と区別する）。 */
export function loadRiskPatterns(file: string): RegExp[] | null {
	try {
		if (statSync(file).size > MAX_RULES_BYTES) return null;
		const rules = JSON.parse(readFileSync(file, "utf8")) as { judge?: { common?: { pi?: { integrate?: { risk_paths?: unknown } } } } };
		const rp = rules?.judge?.common?.pi?.integrate?.risk_paths;
		if (!Array.isArray(rp)) return null;
		// 一部だけ評価できる状態を「読めた」としない（不正な要素・上限超過は、設定を読めない扱い）
		if (rp.length > MAX_RISK_PATTERNS || rp.some((p) => typeof p !== "string" || p.length > MAX_PATTERN_CHARS)) return null;
		return (rp as string[]).map((p) => globToRegExp(p));
	} catch {
		return null;
	}
}

// ---- メッセージ ----

const MSG_BAD_CHARS = /[\u0000-\u0008\u000b-\u001f\u007f-\u009f\u061c\u200e\u200f\u202a-\u202e\u2066-\u2069]/;
const LONE_SURROGATE = /[\ud800-\udbff](?![\udc00-\udfff])|(?<![\ud800-\udbff])[\udc00-\udfff]/;

/** 統合コミットのメッセージの検査。改行は \n にそろえて返す。 */
function checkMessage(m: unknown): string {
	const fail = (): ApiError => bad("bad_message", "メッセージが正しくありません（1〜4000 文字・1 行目は空白だけにしない・制御文字は不可）。");
	if (typeof m !== "string") throw fail();
	const s = m.replace(/\r\n?/g, "\n");
	if (s.length < 1 || s.length > 4000) throw fail();
	if (MSG_BAD_CHARS.test(s) || LONE_SURROGATE.test(s)) throw fail();
	if (s.split("\n")[0].trim() === "") throw fail();
	return s;
}

/** 下書きが無いときの既定: 枝の最新コミットの件名（リポジトリの規約に合うもの）と、ほかの件名を数行。 */
async function generatedMessage(c: PrCtx): Promise<string> {
	const r = await git(c.repo, ["log", "--no-color", "--max-count=4", "--format=%s", `${c.targetOid}..${c.sourceOid}`], true);
	const subjects = r.code === 0 ? r.out.split("\n").filter((l) => l.trim() !== "") : [];
	const fallback = `chore: ${c.branch} を統合する`;
	const title = subjects[0] ?? fallback;
	const text = subjects.length > 1 ? `${title}\n\n${subjects.slice(1).join("\n")}\n` : `${title}\n`;
	try {
		return checkMessage(text);
	} catch {
		return `${fallback}\n`;
	}
}

// ---- 本文の検査 ----

const OID40 = /^[0-9a-f]{40}$/;
const CLEANUPS: readonly string[] = ["none", "branch", "branch_and_worktree"];
const isObj = (x: unknown): x is Record<string, unknown> => typeof x === "object" && x !== null && !Array.isArray(x);

type MergeBody = { expect: { source: string; target: string }; message: string; cleanup: Cleanup };

function parseMergeBody(body: Record<string, unknown>): MergeBody {
	for (const k of Object.keys(body)) {
		if (k !== "expect" && k !== "message" && k !== "cleanup") throw bad("bad_request", "リクエストの形が正しくありません。");
	}
	const e = body.expect;
	const badExpect = (): ApiError => bad("bad_expect", "表示中の版の指定が正しくありません。");
	if (!isObj(e)) throw badExpect();
	const keys = Object.keys(e);
	if (keys.length !== 2 || !keys.includes("source") || !keys.includes("target")) throw badExpect();
	if (typeof e.source !== "string" || typeof e.target !== "string" || !OID40.test(e.source) || !OID40.test(e.target)) throw badExpect();
	const message = checkMessage(body.message);
	const cleanup = body.cleanup === undefined ? "none" : body.cleanup;
	if (typeof cleanup !== "string" || !CLEANUPS.includes(cleanup)) throw bad("bad_cleanup", "後始末の指定が正しくありません。");
	return { expect: { source: e.source, target: e.target }, message, cleanup: cleanup as Cleanup };
}

// ---- 統合器の拒否 → HTTP ----

const REFUSAL_STATUS: Record<string, number> = {
	bad_input: 400,
	policy_source: 403,
	policy_target: 403,
	no_source: 404,
	no_target: 404,
	stale: 409,
	already_merged: 409,
	conflict: 409,
	head_mismatch: 409,
	dirty: 409,
	ignored: 409,
	external_code: 409,
	busy: 409,
	recover_needed: 409,
	not_ff: 409,
	no_identity: 409,
	// P1 の事前検査（環境・変更の内容が原因で、統合しない）
	git_version: 409,
	unsupported_repo: 409,
	unsupported_change: 409,
	// 統合されたか確認できなかった（状態ファイルを残している。recover で確かめる）
	unverified: 500,
	failed: 500,
};

function refusalToError(r: Refusal): ApiError {
	const code = r.code === "stale" ? "stale_view" : r.code === "failed" ? "merge_failed" : r.code;
	const conflicts = r.code === "conflict" && Array.isArray(r.conflicts) ? r.conflicts.slice(0, MAX_CONFLICTS).map(String) : undefined;
	return new ApiError(REFUSAL_STATUS[r.code] ?? 500, code, r.reason, conflicts);
}

/** 診断ログ（標準エラーに 1 行の JSON）。本文・ヘッダー・パスは出さない。共有 ref と同じく、改ざんされうる記録ではなく、運用の手がかり。 */
function diag(entry: Record<string, unknown>): void {
	try {
		process.stderr.write(`${JSON.stringify({ t: "merge", ...entry })}\n`);
	} catch {
		// 出せなくても統合の結果は変えない
	}
}

// ---- merge-plan ----

export async function mergePlan(ctx: PrCtx, pr: MergePr, body: Record<string, unknown>, env: MergeEnv): Promise<PostResult> {
	if (Object.keys(body).length !== 0) throw bad("bad_request", "リクエストの形が正しくありません。");
	return await gated(ctx.repo, async () => {
		const blockers: Blocker[] = [];
		// ジョブは統合先の ref を動かさないが、実行中の worktree・保護 ref の照合を乱す。リポジトリ単位で断る
		if (jobProbe(ctx.repo.repoId)) blockers.push({ code: "job_running", message: JOB_RUNNING_TEXT });
		// plan はメッセージを使わない（検査を通すための仮の値 "plan" を渡す）
		const r = await planMerge({ repo: ctx.repo.gitDir, source: ctx.branch, target: ctx.target, message: "plan" });
		const hints = await reviewHints(ctx);
		const generated = hints.summaryMessage === null ? await generatedMessage(ctx) : null;
		let defaults: { message: string; messageSource: string; summaryStale: boolean; cleanup: string };
		if (hints.summaryMessage !== null) {
			let m: string | null = null;
			try {
				m = checkMessage(hints.summaryMessage);
			} catch {
				m = null; // 検査を通らない下書き（制御文字など）は使わない
			}
			defaults = m !== null
				? { message: m, messageSource: "summary", summaryStale: hints.summaryStale, cleanup: "none" }
				: { message: await generatedMessage(ctx), messageSource: "generated", summaryStale: false, cleanup: "none" };
		} else {
			defaults = { message: generated as string, messageSource: "generated", summaryStale: false, cleanup: "none" };
		}
		let refusal: { code: string; message: string; conflicts?: string[] } | null = null;
		let plan: Record<string, unknown> | null = null;
		if (!r.ok) {
			refusal = { code: r.code, message: r.reason };
			if (r.code === "conflict" && Array.isArray(r.conflicts)) refusal.conflicts = r.conflicts.slice(0, MAX_CONFLICTS).map(String);
		} else {
			const p = r.plan;
			if (p.source.oid !== ctx.sourceOid || p.target.oid !== ctx.targetOid) {
				throw new ApiError(409, "stale_view", "表示中の版から PR が更新されています。再読み込みしてください。");
			}
			const patterns = loadRiskPatterns(env.rulesFile);
			const risky = patterns === null ? [] : p.touched.filter((t) => patterns.some((re) => re.test(t)));
			plan = {
				source: { branch: ctx.branch, oid: p.source.oid },
				target: { branch: ctx.target, oid: p.target.oid },
				mergeBase: p.mergeBase,
				commits: pr.commits,
				files: p.files,
				fileCount: p.fileCount,
				additions: pr.additions,
				deletions: pr.deletions,
				risks: risky.slice(0, MAX_RISKS).map((path) => ({ path, reason: "risk_path" })),
				risksTruncated: risky.length > MAX_RISKS,
				riskConfig: patterns === null ? "unavailable" : "loaded",
				touchesApp: p.touched.some((t) => t.startsWith(APP_PREFIX)),
			};
		}
		return {
			status: 200,
			body: { mergeable: refusal === null && blockers.length === 0, refusal, blockers, plan, defaults, warnings: hints.warnings },
		};
	});
}

// ---- merge ----

export async function mergeExecute(ctx: PrCtx, body: Record<string, unknown>, env: MergeEnv): Promise<PostResult> {
	const input = parseMergeBody(body);
	// 画面が見ていた版と、いまの版が違えば、何も動かさずに断る（統合器の expect と二重に確かめる）
	if (input.expect.source !== ctx.sourceOid || input.expect.target !== ctx.targetOid) {
		throw new ApiError(409, "stale_view", "表示中の版から PR が更新されています。再読み込みしてから統合してください。");
	}
	return await gated(ctx.repo, async () => {
		const req = randomUUID();
		const who = { req, repo: ctx.repo.repoId, pr: ctx.prKey, expect: input.expect };
		// ジョブとの排他: gated の確認と同じ tick で見る（ジョブ側の予約も同期。どちらかが必ず先に断られる）
		if (jobProbe(ctx.repo.repoId)) {
			diag({ ...who, result: "job_running", commit: null, recorded: false });
			throw new ApiError(409, "job_running", JOB_RUNNING_TEXT);
		}
		const deps = env.testDelayMs > 0 ? { beforeAdvance: () => new Promise<void>((done) => setTimeout(done, env.testDelayMs)) } : undefined;
		const r = await executeMerge(
			{
				repo: ctx.repo.gitDir,
				source: ctx.branch,
				target: ctx.target,
				message: input.message,
				cleanup: input.cleanup,
				expect: { sourceOid: input.expect.source, targetOid: input.expect.target },
			},
			undefined,
			deps,
		);
		if (!r.ok) {
			diag({ ...who, result: r.code, commit: null, recorded: false });
			throw refusalToError(r);
		}
		let recorded = false;
		try {
			recorded = await recordMerge(ctx, { requestId: req, message: input.message, cleanup: input.cleanup, commit: r.result.commit });
		} catch {
			recorded = false; // 記録に失敗しても、統合の成功は取り消さない
		}
		diag({ ...who, result: "ok", commit: r.result.commit, recorded });
		return { status: 200, body: { merge: { ...r.result, recorded } } };
	});
}
