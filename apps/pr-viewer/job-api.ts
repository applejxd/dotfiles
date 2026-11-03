// PR ビューアのジョブ API（変更を依頼 = pis -p の都度起動）。契約: .tmp/keep/prv-app/api-contract-job.md。
// 起動の権限は live の POST だけ。ref・記録・コメント・ファイルの内容は入力データとしてだけ読み、可否の根拠にしない。
// 仕組みと判断基準は docs/spec/pr-viewer.md（ジョブ）が正本。ここには編集時に要る注記だけを書く。
// ここは git を直接動かさない（検査・commit は job-git.ts、実行は job-runner.ts、記録は review-api.ts を通す）。
import { accessSync, constants, statSync } from "node:fs";
import type { IncomingHttpHeaders } from "node:http";
import { homedir } from "node:os";
import { isAbsolute } from "node:path";
import { ApiError } from "./git-view.ts";
import type { Repo } from "./git-view.ts";
import { preflight } from "./job-git.ts";
export { stateDirIsolated } from "./job-git.ts";
import { buildPrompt, inputDigest } from "./job-prompt.ts";
import { acquireInstanceLock, runJob, shutdown as shutdownRunner } from "./job-runner.ts";
export { acquireInstanceLock };
import type { RunHandle } from "./job-runner.ts";
import {
	acquireLock,
	countDaily,
	createJob,
	dailyCount,
	isTerminal,
	listJobs,
	openStore,
	publicJob,
	readJob,
	readLogLines,
	recover,
	releaseLock,
	updateJob,
	writePrompt,
	LOG_READ_MAX,
} from "./job-store.ts";
import type { JobRecord, Store } from "./job-store.ts";
import { loadRiskPatterns, mergeRunning, setJobProbe, strictOriginOk } from "./merge-api.ts";
import type { PostResult } from "./merge-api.ts";
import { JOB_INPUT_LIMITS, claimJobBatches, featureWorktreeId, liveJobBatches, resolveJobBatches, worktreeIdFor } from "./review-api.ts";
import type { PrCtx } from "./review-api.ts";

/** サーバの旗から作る設定。 */
export type JobsConfig = {
	/** `--allow-jobs`。既定は無効 */
	enabled: boolean;
	/** process.platform（試験は `--test-platform` で差し替える） */
	platform: string;
	/** pis の絶対パス */
	pisCommand: string;
	/** state dir（絶対パス） */
	stateDir: string;
	timeoutMs: number;
	model: string | null;
	rulesFile: string;
};
/** PR の概要から、ジョブに要る項目。 */
export type JobPr = { state: "open" | "merged" };

export const DEFAULT_JOB_TIMEOUT_MS = 10 * 60_000;
export const MAX_JOB_TIMEOUT_MS = 30 * 60_000;
const CONCURRENT = 1;
const DAILY = 30;
const LIST_LIMIT = 5;
const CANCEL_WAIT_MS = 3000;
const OID40 = /^[0-9a-f]{40}$/;
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const DIGEST_RE = /^[0-9a-f]{64}$/;
const isObj = (x: unknown): x is Record<string, unknown> => typeof x === "object" && x !== null && !Array.isArray(x);
const bad = (code: string, message: string): ApiError => new ApiError(400, code, message);

// ---- 能力・入口の検査 ----

function pisUsable(path: string): boolean {
	try {
		if (!isAbsolute(path) || !statSync(path).isFile()) return false;
		accessSync(path, constants.X_OK);
		return true;
	} catch {
		return false;
	}
}

/** GET /api/capabilities に足す項目。パスを含めない。 */
export function jobCapabilities(cfg: JobsConfig): {
	jobs: boolean;
	jobsReason: "unsupported_platform" | "pis_missing" | null;
	jobLimits: { timeoutMin: number; concurrent: number; daily: number };
} {
	const reason = cfg.platform !== "linux" ? "unsupported_platform" : !pisUsable(cfg.pisCommand) ? "pis_missing" : null;
	return { jobs: cfg.enabled && reason === null, jobsReason: reason, jobLimits: { timeoutMin: timeoutMin(cfg), concurrent: CONCURRENT, daily: DAILY } };
}

const timeoutMin = (cfg: JobsConfig): number => Math.max(1, Math.round(cfg.timeoutMs / 60_000));

/**
 * ジョブ系の経路の入口の検査。無効・Funnel・Origin の順に断る。通れば null。
 * POST は Origin 必須。GET はブラウザが同一オリジンの GET に Origin を付けないので、付いているときだけ照合する。
 */
export function jobRequestError(headers: IncomingHttpHeaders, cfg: JobsConfig, method: "GET" | "POST"): ApiError | null {
	if (!cfg.enabled) return new ApiError(403, "jobs_disabled", "この画面からは pi に依頼できません（サーバがジョブを許可していません）。");
	if (headers["tailscale-funnel-request"] !== undefined) return new ApiError(403, "forbidden_funnel", "公開（Funnel）経由では依頼できません。");
	if ((method === "POST" || headers.origin !== undefined) && !strictOriginOk(headers.origin, headers.host)) {
		return new ApiError(403, "forbidden_origin", "この Origin は許可されていません。");
	}
	return null;
}

/** 動かせる環境か（入口の検査の後）。 */
function requireRunnable(cfg: JobsConfig): void {
	if (cfg.platform !== "linux") throw new ApiError(501, "unsupported_platform", "この環境では使えません（Linux のみ）。");
	if (!pisUsable(cfg.pisCommand)) throw new ApiError(503, "pis_missing", "pis が見つかりません。");
}

// ---- 実行中の集合・停止 ----

type Reservation = { repoId: string; branch: string; id: string | null; handle: RunHandle | null };
/** 起動の予約（検査の途中から）と実行中。同じ tick の同期処理で見るので、統合との間に窓が無い。 */
const reservations = new Set<Reservation>();
const starts = new Set<Promise<unknown>>();
let stopping = false;

setJobProbe((repoId) => [...reservations].some((r) => r.repoId === repoId));

/** 停止の開始。新しい起動は断り、起動の途中のものを待ち、実行中は interrupted にして（finalizing だけ待って）返す。 */
export async function stopJobs(): Promise<void> {
	stopping = true;
	await Promise.allSettled([...starts]);
	await shutdownRunner();
}

const stores = new Map<string, Store>();

function storeOf(cfg: JobsConfig, repo: Repo): Store {
	const repoId = repo.repoId;
	let s = stores.get(repoId);
	if (!s) {
		try {
			s = openStore(cfg.stateDir, repoId, [repo.gitDir]);
		} catch {
			throw new ApiError(500, "state_unavailable", "ジョブの保存先を開けません。");
		}
		stores.set(repoId, s);
	}
	return s;
}

/** 回復で残存プロセスの消滅を確認できなかった（または回復に失敗した）リポジトリ。ジョブの受付を止める。 */
const blockedRepos = new Set<string>();

function requireNotBlocked(repo: Repo): void {
	if (blockedRepos.has(repo.repoId)) {
		throw new ApiError(503, "recovery_failed", "前回の依頼の残りを止められませんでした。サーバを再起動するか、手で確認してください。");
	}
}

/**
 * 起動時の回復: 前回の実行中のジョブを interrupted にし、古い排他を掃除する。ジョブが無効なら何もしない。
 * 残存プロセスを止め切れない、あるいは回復に失敗したリポジトリは、ジョブの受付を止める（起動は続ける）。
 */
export async function recoverJobs(cfg: JobsConfig, repos: Repo[]): Promise<void> {
	if (!cfg.enabled) return;
	for (const r of repos) {
		try {
			const res = await recover(storeOf(cfg, r));
			if (res.survivors.length > 0) blockedRepos.add(r.repoId);
		} catch {
			blockedRepos.add(r.repoId);
		}
	}
}

// ---- 衛生化（ログ） ----

const ANSI_RE = /\u001b\[[0-9;?]*[ -/]*[@-~]|\u001b\][^\u0007\u001b]*(?:\u0007|\u001b\\)/g;
// eslint-disable-next-line no-control-regex
const CTRL_RE = /[\u0000-\u0008\u000b-\u001f\u007f-\u009f\u2028\u2029\u202a-\u202e\u2066-\u2069]/g;
const ABS_PATH_RE = /(?<![\w.:/-])(?:\/[^\s"'`<>|;,(){}[\]\\]+)+|~(?:\/[^\s"'`<>|;,(){}[\]\\]+)+|[A-Za-z]:\\[^\s"'`<>|]+/g;

/** ログを画面へ返す前の衛生化: ANSI・制御文字を除き、既知の根のパスと絶対パスを <path> に置き換える。 */
export function sanitizeLog(text: string, roots: string[]): string {
	let t = text.replace(ANSI_RE, "").replace(CTRL_RE, "");
	for (const root of [...new Set(roots)].filter((r) => r.length > 1).sort((a, b) => b.length - a.length)) t = t.split(root).join("<path>");
	return t.replace(ABS_PATH_RE, "<path>");
}

function rootsOf(cfg: JobsConfig, repo: Repo, rec: JobRecord | null): string[] {
	const roots = [homedir(), cfg.stateDir, repo.gitDir, cfg.pisCommand];
	const internal = rec?.internal as { pre?: { worktree?: unknown; gitDir?: unknown; adminDir?: unknown } } | null | undefined;
	for (const v of [internal?.pre?.worktree, internal?.pre?.gitDir, internal?.pre?.adminDir]) if (typeof v === "string") roots.push(v);
	return roots;
}

// ---- 入力の検査 ----

type StartBody = { expect: { source: string; target: string }; batches: string[]; inputDigest: string };

function parseStartBody(body: Record<string, unknown>): StartBody {
	for (const k of Object.keys(body)) {
		if (k !== "kind" && k !== "expect" && k !== "batches" && k !== "inputDigest") throw bad("bad_request", "リクエストの形が正しくありません。");
	}
	if (body.kind !== "address_review") throw bad("bad_request", "リクエストの形が正しくありません。");
	const e = body.expect;
	const badExpect = (): ApiError => bad("bad_expect", "表示中の版の指定が正しくありません。");
	if (!isObj(e)) throw badExpect();
	const keys = Object.keys(e);
	if (keys.length !== 2 || !keys.includes("source") || !keys.includes("target")) throw badExpect();
	if (typeof e.source !== "string" || typeof e.target !== "string" || !OID40.test(e.source) || !OID40.test(e.target)) throw badExpect();
	const b = body.batches;
	const badBatches = (): ApiError => bad("bad_batches", "渡す送信の指定が正しくありません。");
	if (!Array.isArray(b) || b.length < 1 || b.length > 10) throw badBatches();
	if (!b.every((x) => typeof x === "string" && UUID_RE.test(x)) || new Set(b).size !== b.length) throw badBatches();
	if (typeof body.inputDigest !== "string" || !DIGEST_RE.test(body.inputDigest)) throw bad("bad_digest", "入力の識別子が正しくありません。");
	return { expect: { source: e.source, target: e.target }, batches: b as string[], inputDigest: body.inputDigest };
}

const REFUSAL_STATUS: Record<string, number> = { bad_request: 400, failed: 500 };

/** 起動前の検査（job-git）の拒否 → HTTP。理由の文は job-git の固定文（パス・git の出力を含まない）。 */
function refusalToError(code: string, reason: string): ApiError {
	return new ApiError(REFUSAL_STATUS[code] ?? 409, code === "failed" ? "job_failed" : code, reason);
}

const BLOCK_TEXT: Record<string, string> = {
	merged: "この PR は統合済みです。",
	merge_running: "統合の処理が実行中です。終わってから依頼してください。",
	job_running: "この PR への依頼が実行中です。",
	busy: "ほかの依頼が実行中です。終わってから依頼してください。",
	nothing_to_do: "渡すコメントがありません（未受領の送信がありません）。",
	quota: "今日の依頼の上限に達しました。",
};

/** 同じ PR・同じ repo・全体の排他の確認（同期）。 */
function exclusionError(repoId: string, branch: string): ApiError | null {
	if (mergeRunning(repoId)) return new ApiError(409, "merge_running", BLOCK_TEXT.merge_running);
	for (const r of reservations) if (r.repoId === repoId && r.branch === branch) return new ApiError(409, "job_running", BLOCK_TEXT.job_running);
	if (reservations.size >= CONCURRENT) return new ApiError(409, "busy", BLOCK_TEXT.busy);
	return null;
}

function protectedRefs(ctx: PrCtx): string[] {
	return [...new Set([ctx.target, "develop", "main", "master"])];
}

// ---- GET …/job-input ----

type Blocker = { code: string; message: string };

export async function jobInput(ctx: PrCtx, pr: JobPr, cfg: JobsConfig): Promise<{ input: unknown }> {
	requireRunnable(cfg);
	const blockers: Blocker[] = [];
	const add = (code: string, message: string = BLOCK_TEXT[code] ?? "実行できません。"): void => {
		if (!blockers.some((b) => b.code === code)) blockers.push({ code, message });
	};
	if (pr.state === "merged") add("merged");
	const ex = exclusionError(ctx.repo.repoId, ctx.branch);
	if (ex) add(ex.code, ex.message);
	const worktreeId = await featureWorktreeId(ctx.repo, ctx.branch);
	const live = await liveJobBatches(ctx, worktreeId);
	if (live.merged) add("merged");
	if (ex?.code !== "job_running") {
		const pf = await preflight({ repo: ctx.repo.gitDir, source: ctx.branch, expectOid: ctx.sourceOid, protectedRefs: protectedRefs(ctx) });
		if (!pf.ok) add(pf.code, pf.reason);
	}
	if (live.batches.length === 0) {
		if (worktreeId !== null) add("nothing_to_do");
	} else {
		// 上限（件数・本文・全体のバイト数）は、起動時と同じ組み立てで確かめる
		const over = buildPrompt({ branch: ctx.branch, batches: live.batches });
		if (!over.ok) add("too_large", over.message);
	}
	try {
		if (dailyCount(storeOf(cfg, ctx.repo)) >= DAILY) add("quota");
	} catch (e) {
		if (e instanceof ApiError) add(e.code, e.message);
	}
	if (blockedRepos.has(ctx.repo.repoId)) add("recovery_failed", "前回の依頼の残りを止められませんでした。サーバを再起動するか、手で確認してください。");
	return {
		input: {
			inputDigest: inputDigest(live.batches),
			batches: live.batches,
			blockers,
			limits: JOB_INPUT_LIMITS,
			notice: { timeoutMin: timeoutMin(cfg), writes: "worktree", commit: "app" },
		},
	};
}

// ---- POST …/jobs ----

export async function jobStart(ctx: PrCtx, pr: JobPr, body: Record<string, unknown>, cfg: JobsConfig): Promise<PostResult> {
	if (stopping) throw new ApiError(503, "shutting_down", "サーバを停止しています。");
	requireRunnable(cfg);
	const input = parseStartBody(body);
	if (input.expect.source !== ctx.sourceOid || input.expect.target !== ctx.targetOid) {
		throw new ApiError(409, "stale_view", "表示中の版から PR が更新されています。再読み込みしてから依頼してください。");
	}
	if (pr.state === "merged") throw new ApiError(409, "merged", BLOCK_TEXT.merged);
	// ここから予約までは同期（await を挟まない）。統合の gated の確認と対になり、どちらかが必ず先に断られる
	const ex = exclusionError(ctx.repo.repoId, ctx.branch);
	if (ex) throw ex;
	const rsv: Reservation = { repoId: ctx.repo.repoId, branch: ctx.branch, id: null, handle: null };
	reservations.add(rsv);
	const run = startJob(ctx, input, cfg, rsv);
	starts.add(run);
	try {
		return await run;
	} finally {
		starts.delete(run);
		if (rsv.handle === null) reservations.delete(rsv); // 起動できなかった。起動できたら handle.done の後に外す
	}
}

function diag(entry: Record<string, unknown>): void {
	try {
		process.stderr.write(`${JSON.stringify({ t: "job", ...entry })}\n`);
	} catch {
		// 出せなくても結果は変えない
	}
}

async function startJob(ctx: PrCtx, input: StartBody, cfg: JobsConfig, rsv: Reservation): Promise<PostResult> {
	const store = storeOf(cfg, ctx.repo);
	requireNotBlocked(ctx.repo);
	if (dailyCount(store) >= DAILY) throw new ApiError(429, "quota", BLOCK_TEXT.quota);

	const pf = await preflight({ repo: ctx.repo.gitDir, source: ctx.branch, expectOid: ctx.sourceOid, protectedRefs: protectedRefs(ctx) });
	if (!pf.ok) throw refusalToError(pf.code, pf.reason);

	// 記録は入力データとして読む。指名された batch が未受領で宛先がこの worktree かを確かめ、digest を照合する
	const worktreeId = worktreeIdFor(pf.pre.worktree);
	const chosen = await resolveJobBatches(ctx, worktreeId, input.batches);
	if (!chosen.ok) {
		throw chosen.code === "nothing_to_do"
			? new ApiError(409, "nothing_to_do", "指定した送信は、すでに受領されています。")
			: bad("bad_batches", "指定した送信が見つかりません。");
	}
	if (inputDigest(chosen.batches) !== input.inputDigest) throw new ApiError(409, "stale_input", "渡す内容が変わりました。開き直してください。");
	const prompt = buildPrompt({ branch: ctx.branch, batches: chosen.batches });
	if (!prompt.ok) {
		if (prompt.code === "no_comments") throw new ApiError(409, "nothing_to_do", BLOCK_TEXT.nothing_to_do);
		if (prompt.code === "bad_input") throw bad("bad_request", "リクエストの形が正しくありません。");
		throw new ApiError(413, "too_large", prompt.message);
	}
	if (!countDaily(store, DAILY).ok) throw new ApiError(429, "quota", BLOCK_TEXT.quota);

	const batchIds = chosen.batches.map((b) => b.batchId);
	const job = createJob(store, { kind: "address_review", branch: ctx.branch, baseOid: pf.pre.baseOid, batchIds });
	rsv.id = job.id;
	const fail = (reasons: string[]): void => {
		try {
			updateJob(store, job.id, { state: "failed", reasons });
		} catch {
			// すでに終端
		}
		releaseLock(store, ctx.branch, job.id);
	};
	try {
		if (!acquireLock(store, ctx.branch, job.id).ok) {
			fail(["lock_failed"]);
			throw new ApiError(409, "job_running", BLOCK_TEXT.job_running);
		}
		writePrompt(store, job.id, prompt.prompt);
		updateJob(store, job.id, { internal: { pre: pf.pre, record: pf.record } });
	} catch (e) {
		if (e instanceof ApiError) throw e;
		fail(["state_failed"]);
		throw new ApiError(500, "state_unavailable", "ジョブの保存先に書けません。");
	}
	// 受領の claim（receipt）。ここから先は、失敗してもコメントは「読んだ」になる（再送で救う）
	const claimErr = await claimJobBatches(ctx, { jobId: job.id, batchIds, worktreeId, digest: input.inputDigest });
	if (claimErr) {
		fail(["claim_failed"]);
		diag({ job: job.id, pr: ctx.prKey, result: claimErr.code });
		throw claimErr;
	}
	let handle: RunHandle;
	try {
		handle = runJob({
			store,
			job,
			pre: pf.pre,
			record: pf.record,
			pisCommand: cfg.pisCommand,
			argvTail: { prompt: prompt.prompt, model: cfg.model },
			timeoutMs: cfg.timeoutMs,
			riskPaths: loadRiskPatterns(cfg.rulesFile),
		});
	} catch {
		fail(["spawn_failed"]);
		throw new ApiError(500, "job_failed", "依頼を開始できませんでした。");
	}
	rsv.handle = handle;
	void handle.done.then((rec) => {
		reservations.delete(rsv); // 終端と排他の解除が済んでから外す
		diag({ job: rec.id, pr: ctx.prKey, state: rec.state, exitCode: rec.exitCode, reasons: rec.reasons });
	});
	return { status: 202, body: { job: publicJob(readJob(store, job.id) ?? job) } };
}

// ---- GET …/jobs・…/jobs/<id> ----

export async function jobList(ctx: PrCtx, cfg: JobsConfig): Promise<{ jobs: unknown[] }> {
	requireRunnable(cfg);
	const store = storeOf(cfg, ctx.repo);
	return { jobs: listJobs(store).filter((j) => j.branch === ctx.branch).slice(0, LIST_LIMIT).map((j) => publicJob(j)) };
}

function ownJob(store: Store, ctx: PrCtx, id: string): JobRecord {
	const rec = UUID_RE.test(id) ? readJob(store, id) : null;
	if (!rec || rec.branch !== ctx.branch) throw new ApiError(404, "not_found", "見つかりません。");
	return rec;
}

export async function jobGet(ctx: PrCtx, id: string, fromRaw: string | null, cfg: JobsConfig): Promise<unknown> {
	requireRunnable(cfg);
	if (fromRaw !== null && !/^\d{1,10}$/.test(fromRaw)) throw bad("bad_request", "from の形が正しくありません。");
	const store = storeOf(cfg, ctx.repo);
	const rec = ownJob(store, ctx, id);
	const raw = readLogLines(store, id, fromRaw === null ? 0 : Number(fromRaw), LOG_READ_MAX, isTerminal(rec.state));
	return {
		job: publicJob(rec),
		log: { from: raw.from, next: raw.next, text: sanitizeLog(raw.text, rootsOf(cfg, ctx.repo, rec)), truncated: raw.truncated },
	};
}

// ---- POST …/jobs/<id>/cancel ----

export async function jobCancel(ctx: PrCtx, id: string, body: Record<string, unknown>, cfg: JobsConfig): Promise<PostResult> {
	requireRunnable(cfg);
	if (Object.keys(body).length !== 0) throw bad("bad_request", "リクエストの形が正しくありません。");
	const store = storeOf(cfg, ctx.repo);
	const rec = ownJob(store, ctx, id);
	const rsv = [...reservations].find((r) => r.id === id && r.handle !== null);
	const notCancellable = (): ApiError => new ApiError(409, "not_cancellable", "この依頼は停止できません（終了済み、または結果を確定中です）。");
	if (isTerminal(rec.state) || rec.state === "finalizing" || !rsv?.handle) throw notCancellable();
	if (!rsv.handle.cancel()) throw notCancellable();
	await Promise.race([rsv.handle.done, new Promise<void>((done) => setTimeout(done, CANCEL_WAIT_MS).unref())]);
	return { status: 200, body: { job: publicJob(readJob(store, id) ?? rec) } };
}
