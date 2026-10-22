// 子エージェントの作業を git worktree に隔離する中核 (事前選別・スナップショット・作成・回収・記録)。
//
// 依存は node の標準モジュールと judge/policy.ts だけ。import しただけでは何も実行しない。
// 子の起動・停止の確認は呼び出し側 (S3) の仕事で、ここでは扱わない。
// node の型除去 (strip-types) でそのまま動く書き方だけを使う (enum・namespace・parameter property・`import =` を使わない)。
// 契約・順序・上限の根拠は docs/change/0029-worktree-isolation.md の「W1 の実装計画」と「W1 の前に決める仕様案」。
import { spawnSync } from "node:child_process";
import { createHash, randomBytes } from "node:crypto";
import * as fs from "node:fs";
import * as path from "node:path";
import { matchesReadDeny } from "./judge/policy.ts";
import type { DenyException } from "./judge/policy.ts";

// ─── 型・定数 ───────────────────────────────────────────────────────────

export class WorktreeError extends Error {
	code: string;
	detail: Record<string, unknown>;
	constructor(code: string, message: string, detail: Record<string, unknown> = {}) {
		super(message);
		this.name = "WorktreeError";
		this.code = code;
		this.detail = detail;
	}
}

const fail = (code: string, message: string, detail: Record<string, unknown> = {}): never => {
	throw new WorktreeError(code, message, detail);
};

/** 値は案の推測 (docs/change/0029 の「容量の上限」「時間の上限」)。呼び出し側が変えられる。 */
export type Limits = {
	gitTimeoutMs: number;
	totalMs: number;
	maxTotalBytes: number;
	maxFileBytes: number;
	maxWorktrees: number;
	/** ロックが取れないときに待つ最大の時間 (ms)。 */
	lockWaitMs: number;
	/** 管理領域の `index` (と index.lock など) の大きさの上限。 */
	maxAdminIndexBytes: number;
};

export const DEFAULT_LIMITS: Limits = {
	gitTimeoutMs: 30000,
	totalMs: 60000,
	maxTotalBytes: 200 * 1024 * 1024,
	maxFileBytes: 50 * 1024 * 1024,
	maxWorktrees: 8,
	lockWaitMs: 1000, // 同期待ちは親のイベントループを止めるので短くする (値は推測)
	maxAdminIndexBytes: 64 * 1024 * 1024,
};

export type ReadDeny = { globs: string[]; exceptions: DenyException[] };

export type RecordState = "creating" | "running" | "collecting" | "collected" | "kept";

// node の組み込みの Record<K, V> と名前が衝突するので、仕様の `Record` はこの名前にした。
export type IsolationRecord = {
	version: 1;
	jobId: string;
	repo: string;
	worktree: string;
	startCommit: string;
	snapshotCommit: string;
	createdAt: string;
	state: RecordState;
	resultCommit?: string;
	ref?: string;
	patch?: { path: string; sha256: string };
	note?: string;
};

export type BrokenRecord = { broken: true; file: string };

export type Candidates = { tracked: string[]; untracked: string[] };

export type CollectResult =
	| { changed: false }
	| { changed: true; resultCommit: string; ref: string; patch: { path: string; sha256: string }; warnings: string[] };

export type ReconcileIssue = {
	jobId: string;
	issue: "record_only" | "worktree_only" | "ref_only" | "patch_missing" | "stuck_running" | "stuck_creating";
	detail: Record<string, unknown>;
};

const GIT = "/usr/bin/git";
const MAX_BUFFER = 256 * 1024 * 1024;
const AGENT_NAME = "pi-agent";
const AGENT_EMAIL = "pi-agent@localhost.invalid";
const HELD_STATES: readonly string[] = ["creating", "running", "collecting", "collected", "kept"];
const JOB_ID_RE = /^job-[0-9a-f]{8,32}$/;
const PATCH_NAME_RE = /^[A-Za-z0-9._-]+\.patch$/;
const OID_RE = /^[0-9a-f]{40}([0-9a-f]{24})?$/;
/** `creating` がこれを過ぎたら stuck_creating と報告する。 */
const CREATING_STALE_MS = 10 * 60 * 1000;
const LOCK_POLL_MS = 50;
/** 死んだ pid のロックでも、ディレクトリの mtime がこれより新しければ stale としない。 */
const LOCK_STALE_MS = 60_000;

const REL = {
	tmp: ".tmp",
	worktrees: ".tmp/worktrees",
	subagents: ".tmp/subagents",
	records: ".tmp/subagents/worktrees",
};

// ─── 時間の予算 ─────────────────────────────────────────────────────────

export class Budget {
	deadline: number;
	constructor(totalMs: number) {
		this.deadline = Date.now() + totalMs;
	}
	remaining(): number {
		return Math.max(0, this.deadline - Date.now());
	}
	check(): void {
		if (this.remaining() <= 0) fail("timeout", "全工程の時間の上限を超えました");
	}
}

// ─── git の実行 ─────────────────────────────────────────────────────────

/** `GIT_*` をすべて落とす (HOME は変えない。global 設定の filter を検出するため)。 */
export function gitEnv(extra: Record<string, string> = {}): Record<string, string> {
	const env: Record<string, string> = {};
	for (const [k, v] of Object.entries(process.env)) {
		if (v !== undefined && !k.startsWith("GIT_")) env[k] = v;
	}
	env.GIT_AUTHOR_NAME = AGENT_NAME;
	env.GIT_AUTHOR_EMAIL = AGENT_EMAIL;
	env.GIT_COMMITTER_NAME = AGENT_NAME;
	env.GIT_COMMITTER_EMAIL = AGENT_EMAIL;
	env.GIT_TERMINAL_PROMPT = "0";
	return { ...env, ...extra };
}

// ハーネス自身の plumbing 用 (利用者のコミットの検証を飛ばすものではない)。see docs/change/0029-worktree-isolation.md の「git の実行」
const SAFE_GIT_ARGS = [
	"-c",
	"core.hooksPath=/dev/null",
	"-c",
	"core.fsmonitor=false",
	"-c",
	"core.attributesFile=/dev/null",
	"-c",
	"diff.external=",
];

export type GitOpts = {
	cwd?: string;
	env?: Record<string, string>;
	input?: string | Buffer;
	budget?: Budget;
	binary?: boolean;
	limits?: Limits;
};
export type GitResult = { status: number; stdout: string | Buffer; stderr: string };

/** 非ゼロの終了は例外にしない (status で返す)。タイムアウトと起動失敗だけ WorktreeError。 */
export function runGit(args: string[], opts: GitOpts = {}): GitResult {
	const limits = opts.limits ?? DEFAULT_LIMITS;
	if (opts.budget) opts.budget.check();
	const timeout = Math.max(
		1,
		Math.min(limits.gitTimeoutMs, opts.budget ? opts.budget.remaining() : limits.gitTimeoutMs),
	);
	const r = spawnSync(GIT, [...SAFE_GIT_ARGS, ...args], {
		cwd: opts.cwd,
		env: gitEnv(opts.env ?? {}),
		input: opts.input,
		timeout,
		maxBuffer: MAX_BUFFER,
		killSignal: "SIGKILL",
		// テキストは UTF-8。diff はバイナリのまま (CRLF を壊さない)
		encoding: opts.binary ? "buffer" : "utf8",
	});
	if (r.error) {
		const errno = errCode(r.error) ?? "unknown";
		if (errno === "ETIMEDOUT") fail("timeout", "git がタイムアウトしました", { args: args.slice(0, 4), timeoutMs: timeout });
		fail("git_failed", "git を起動できません", { args: args.slice(0, 4), errno });
	}
	if (r.status === null) fail("git_failed", "git がシグナルで終了しました", { args: args.slice(0, 4), signal: r.signal });
	const stderr = typeof r.stderr === "string" ? r.stderr : Buffer.from(r.stderr ?? []).toString("utf8");
	return { status: r.status, stdout: r.stdout ?? (opts.binary ? Buffer.alloc(0) : ""), stderr };
}

function git(args: string[], opts: GitOpts = {}): string {
	const r = runGit(args, { ...opts, binary: false });
	if (r.status !== 0) {
		fail("git_failed", `git ${args.find((a) => !a.startsWith("-")) ?? ""} が失敗しました`, {
			args: args.slice(0, 6),
			status: r.status,
			stderr: r.stderr.slice(0, 500),
		});
	}
	return r.stdout as string;
}

function gitBuf(args: string[], opts: GitOpts = {}): Buffer {
	const r = runGit(args, { ...opts, binary: true });
	if (r.status !== 0) {
		fail("git_failed", `git ${args.find((a) => !a.startsWith("-")) ?? ""} が失敗しました`, {
			args: args.slice(0, 6),
			status: r.status,
			stderr: r.stderr.slice(0, 500),
		});
	}
	return r.stdout as Buffer;
}

// ─── 小物 ───────────────────────────────────────────────────────────────

function errCode(e: unknown): string | undefined {
	return (e as { code?: string } | null)?.code;
}

function lstatOrNull(p: string): fs.Stats | null {
	try {
		return fs.lstatSync(p);
	} catch (e) {
		if (errCode(e) === "ENOENT" || errCode(e) === "ENOTDIR") return null;
		throw e;
	}
}

function rmForce(p: string): void {
	fs.rmSync(p, { recursive: true, force: true });
}

const splitNul = (s: string): string[] => s.split("\0").filter((x) => x.length > 0);

const isTmpPath = (p: string): boolean => p === REL.tmp || p.startsWith(`${REL.tmp}/`);

const within = (root: string, p: string): boolean => p === root || p.startsWith(root + path.sep);

const errLabel = (e: unknown): string => (e instanceof WorktreeError ? e.code : "error");

function sleepMs(ms: number): void {
	Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ms);
}

export function validateJobId(id: unknown): string {
	if (typeof id !== "string" || !JOB_ID_RE.test(id)) {
		fail("bad_job_id", "job id の形式が不正です", { id: typeof id === "string" ? id.slice(0, 80) : typeof id });
	}
	return id;
}

/** jobId があれば、名前がその jobId を含むことも要る (patch を job に結び付ける)。 */
export function validatePatchName(name: unknown, jobId?: string): string {
	if (
		typeof name !== "string" ||
		!PATCH_NAME_RE.test(name) ||
		name.includes("..") ||
		(jobId !== undefined && !name.includes(jobId))
	) {
		fail("bad_patch_name", "patch のファイル名が不正です", { name: typeof name === "string" ? name.slice(0, 80) : typeof name });
	}
	return name;
}

export const worktreePath = (repo: string, jobId: string): string =>
	path.join(repo, REL.worktrees, `pi-agent-${validateJobId(jobId)}`);
export const recordPath = (repo: string, jobId: string): string =>
	path.join(repo, REL.records, `${validateJobId(jobId)}.json`);
export const patchPath = (repo: string, patchName: string): string =>
	path.join(repo, REL.subagents, validatePatchName(patchName));
export const refName = (jobId: string): string => `refs/pi-agent/${validateJobId(jobId)}`;

function canonRepo(repo: string): string {
	try {
		return fs.realpathSync(path.resolve(repo));
	} catch {
		return fail("git_failed", "リポジトリのパスが存在しません", { repo });
	}
}

/** 各階層が (あれば) 実ディレクトリで、シンボリックリンクでなく、実体がリポジトリの下にあること。create なら無いものを 0700 で作る。 */
function ensureDirs(repo: string, rels: string[], create: boolean): void {
	for (const rel of rels) {
		const p = path.join(repo, rel);
		let st = lstatOrNull(p);
		if (!st) {
			if (!create) continue;
			try {
				fs.mkdirSync(p, { mode: 0o700 });
			} catch (e) {
				if (errCode(e) !== "EEXIST") fail("bad_placement", "ディレクトリを作れません", { path: rel, errno: errCode(e) });
			}
			st = lstatOrNull(p);
		}
		if (!st || st.isSymbolicLink() || !st.isDirectory()) {
			fail("bad_placement", "実ディレクトリではありません (シンボリックリンクなど)", { path: rel });
		}
		if (!within(repo, fs.realpathSync(p))) fail("bad_placement", "実体がリポジトリの外です", { path: rel });
	}
}

const PLACEMENT_DIRS = [REL.tmp, REL.worktrees, REL.subagents, REL.records];

/** 新規作成だけ (O_EXCL)。末尾がリンクなら開かない (O_NOFOLLOW)。 */
function writeNew(file: string, data: string | Buffer): void {
	const flags = fs.constants.O_WRONLY | fs.constants.O_CREAT | fs.constants.O_EXCL | (fs.constants.O_NOFOLLOW ?? 0);
	const fd = fs.openSync(file, flags, 0o600);
	try {
		fs.writeFileSync(fd, data);
	} finally {
		fs.closeSync(fd);
	}
}

function writeAtomic(dest: string, data: string | Buffer): void {
	const tmp = `${dest}.${process.pid}.${randomBytes(6).toString("hex")}.tmp`;
	try {
		writeNew(tmp, data);
		fs.renameSync(tmp, dest);
	} finally {
		rmForce(tmp);
	}
}

// ─── 記録 ───────────────────────────────────────────────────────────────

function isRecord(v: unknown): v is IsolationRecord {
	if (v === null || typeof v !== "object") return false;
	const r = v as Record<string, unknown>;
	const strs = ["jobId", "repo", "worktree", "startCommit", "snapshotCommit", "createdAt"];
	if (r.version !== 1 || !strs.every((k) => typeof r[k] === "string")) return false;
	if (typeof r.state !== "string" || !HELD_STATES.includes(r.state)) return false;
	if (r.patch !== undefined) {
		const p = r.patch as Record<string, unknown> | null;
		if (p === null || typeof p !== "object" || typeof p.path !== "string" || typeof p.sha256 !== "string") return false;
	}
	return true;
}

export function writeRecord(repo: string, rec: IsolationRecord): void {
	ensureDirs(repo, [REL.tmp, REL.subagents, REL.records], true);
	writeAtomic(recordPath(repo, rec.jobId), `${JSON.stringify(rec, null, 2)}\n`);
}

/** 無ければ null。壊れている・version や jobId が合わないときは bad_record。 */
export function readRecord(repo: string, jobId: string): IsolationRecord | null {
	const file = recordPath(repo, jobId);
	ensureDirs(repo, [REL.tmp, REL.subagents, REL.records], false);
	const st = lstatOrNull(file);
	if (!st) return null;
	if (!st.isFile()) fail("bad_record", "記録が通常のファイルではありません", { file });
	let parsed: unknown;
	try {
		parsed = JSON.parse(fs.readFileSync(file, "utf8"));
	} catch {
		return fail("bad_record", "記録を読めません", { file });
	}
	if (!isRecord(parsed) || parsed.jobId !== jobId) fail("bad_record", "記録の version か jobId が合いません", { file });
	return parsed;
}

export function listRecords(repo: string): (IsolationRecord | BrokenRecord)[] {
	const root = canonRepo(repo);
	ensureDirs(root, [REL.tmp, REL.subagents, REL.records], false);
	const dir = path.join(root, REL.records);
	let names: string[];
	try {
		names = fs.readdirSync(dir).filter((n) => n.endsWith(".json")).sort();
	} catch (e) {
		if (errCode(e) === "ENOENT" || errCode(e) === "ENOTDIR") return [];
		throw e;
	}
	const out: (IsolationRecord | BrokenRecord)[] = [];
	for (const name of names) {
		const file = path.join(dir, name);
		try {
			const st = fs.lstatSync(file);
			const parsed: unknown = st.isFile() ? JSON.parse(fs.readFileSync(file, "utf8")) : null;
			if (isRecord(parsed) && `${parsed.jobId}.json` === name && JOB_ID_RE.test(parsed.jobId)) out.push(parsed);
			else out.push({ broken: true, file });
		} catch {
			out.push({ broken: true, file });
		}
	}
	return out;
}

// ─── 直列化 (同じリポジトリでの作成・回収・破棄) ────────────────────────

function pidAlive(pid: number): boolean {
	try {
		process.kill(pid, 0);
		return true;
	} catch (e) {
		return errCode(e) === "EPERM";
	}
}

function readOrEmpty(p: string): string {
	try {
		return fs.readFileSync(p, "utf8");
	} catch {
		return "";
	}
}

/** ロックの持ち主の識別 (pid とトークン)。奪取の前後で同じかを比べる。 */
function lockIdent(dir: string): string {
	return `${readOrEmpty(path.join(dir, "pid")).trim()}|${readOrEmpty(path.join(dir, "token")).trim()}`;
}

type LockInfo = { ident: string; mtimeMs: number };

function readLockInfo(dir: string): LockInfo | null {
	try {
		return { ident: lockIdent(dir), mtimeMs: fs.statSync(dir).mtimeMs };
	} catch {
		return null;
	}
}

/** ロックの持ち主の pid (読めなければ null)。 */
function lockPid(info: LockInfo): number | null {
	const pid = Number.parseInt(info.ident.split("|")[0] ?? "", 10);
	return Number.isInteger(pid) && pid > 0 ? pid : null;
}

/** 古い (pid が死んでいる・読めない、かつ mtime が LOCK_STALE_MS より古い) なら null。そうでなければ消せない理由。 */
function lockKeepReason(info: LockInfo): "fresh" | "pid_alive" | null {
	if (Date.now() - info.mtimeMs <= LOCK_STALE_MS) return "fresh";
	const pid = lockPid(info);
	return pid !== null && pidAlive(pid) ? "pid_alive" : null;
}

/** 明示的な操作 (S4 の /worktrees・セッション開始) だけが呼ぶ。acquireLock は自動では奪わない。 */
export function clearStaleLock(repo: string): { cleared: boolean; reason: string } {
	const root = canonRepo(repo);
	ensureDirs(root, [REL.tmp, REL.subagents, REL.records], false);
	const dir = path.join(root, REL.records, ".lock");
	const st = lstatOrNull(dir);
	if (!st) return { cleared: false, reason: "no_lock" };
	if (st.isSymbolicLink() || !st.isDirectory()) return { cleared: false, reason: "not_directory" };
	const info = readLockInfo(dir);
	if (!info) return { cleared: false, reason: "unreadable" };
	const why = lockKeepReason(info);
	if (why !== null) return { cleared: false, reason: why };
	// 消す直前に読み直し、識別と mtime が同じときだけ消す
	const again = readLockInfo(dir);
	if (!again || again.ident !== info.ident || again.mtimeMs !== info.mtimeMs) return { cleared: false, reason: "changed" };
	rmForce(dir);
	return { cleared: true, reason: "stale" };
}

function acquireLock(repo: string, limits: Limits): () => void {
	const dir = path.join(repo, REL.records, ".lock");
	const token = randomBytes(8).toString("hex");
	const deadline = Date.now() + limits.lockWaitMs;
	for (;;) {
		try {
			fs.mkdirSync(dir, { mode: 0o700 });
			try {
				fs.writeFileSync(path.join(dir, "pid"), `${process.pid}\n`, { mode: 0o600 });
				fs.writeFileSync(path.join(dir, "token"), `${token}\n`, { mode: 0o600 });
			} catch (e) {
				rmForce(dir);
				throw e;
			}
			return () => {
				if (readOrEmpty(path.join(dir, "token")).trim() === token) rmForce(dir);
			};
		} catch (e) {
			if (errCode(e) !== "EEXIST") fail("git_failed", "ロックを作れません", { errno: errCode(e) });
		}
		if (Date.now() >= deadline) {
			const info = readLockInfo(dir);
			fail("busy", "同じリポジトリで別の操作が進行中です", {
				lock: `${REL.records}/.lock`,
				stale: info !== null && lockKeepReason(info) === null,
				pid: info ? lockPid(info) : null,
			});
		}
		sleepMs(LOCK_POLL_MS);
	}
}

/** 作成・回収・破棄は必ずこの中で行う。 */
function withLock<T>(repo: string, limits: Limits, fn: () => T): T {
	ensureDirs(repo, [REL.tmp, REL.subagents, REL.records], true);
	const release = acquireLock(repo, limits);
	try {
		return fn();
	} finally {
		release();
	}
}

// ─── 事前選別 ───────────────────────────────────────────────────────────

/** repo が作業ツリーの根で、HEAD がある。HEAD の commit を返す。 */
function assertRepoRoot(repo: string, budget: Budget, limits: Limits): string {
	const o = { cwd: repo, budget, limits };
	const top = git(["rev-parse", "--show-toplevel"], o).trim();
	let realTop = top;
	try {
		realTop = fs.realpathSync(top);
	} catch {
		// そのまま比べて不一致にする
	}
	if (realTop !== repo) fail("bad_placement", "リポジトリの作業ツリーの根ではありません", { repo, toplevel: realTop });
	const head = runGit(["rev-parse", "--verify", "--quiet", "HEAD^{commit}"], o);
	if (head.status !== 0) fail("no_head", "HEAD がありません (最初のコミットが要ります)", { repo });
	return (head.stdout as string).trim();
}

function listCandidates(repo: string, budget: Budget, limits: Limits): Candidates {
	const o = { cwd: repo, budget, limits };
	const untracked = splitNul(git(["ls-files", "-z", "--others", "--exclude-standard"], o)).filter((p) => !isTmpPath(p));
	const tracked = splitNul(git(["diff-index", "--name-only", "--no-renames", "-z", "HEAD"], o)).filter((p) => !isTmpPath(p));
	return { tracked: [...new Set(tracked)].sort(), untracked: [...new Set(untracked)].sort() };
}

function checkProtected(repo: string, paths: string[], readDeny: ReadDeny): void {
	const hits: { path: string; rule: string }[] = [];
	for (const rel of paths) {
		const rule =
			matchesReadDeny(rel, readDeny.globs, readDeny.exceptions) ??
			matchesReadDeny(path.join(repo, rel), readDeny.globs, readDeny.exceptions);
		if (rule) hits.push({ path: rel, rule });
	}
	if (hits.length > 0) {
		fail("protected_path", "保護対象のパスが候補に含まれています (内容は読んでいません)", {
			path: hits[0].path,
			rule: hits[0].rule,
			paths: hits.map((h) => h.path),
		});
	}
}

function measure(repo: string, paths: string[], limits: Limits): number {
	let total = 0;
	const sizes: { path: string; size: number }[] = [];
	for (const rel of paths) {
		const st = lstatOrNull(path.join(repo, rel));
		if (!st || !st.isFile()) continue; // 削除・シンボリックリンク・ディレクトリは 0
		if (st.size > limits.maxFileBytes) {
			fail("too_large", "1 ファイルの上限を超えています", { path: rel, size: st.size, limit: limits.maxFileBytes });
		}
		total += st.size;
		sizes.push({ path: rel, size: st.size });
	}
	if (total > limits.maxTotalBytes) {
		sizes.sort((a, b) => b.size - a.size);
		fail("too_large", "合計の上限を超えています", { total, limit: limits.maxTotalBytes, top: sizes.slice(0, 5) });
	}
	return total;
}

function checkFilters(repo: string, budget: Budget, limits: Limits): void {
	const r = runGit(["config", "--get-regexp", "^filter\\."], { cwd: repo, budget, limits });
	if (r.status === 1) return;
	if (r.status !== 0) fail("git_failed", "git config が失敗しました", { status: r.status, stderr: r.stderr.slice(0, 300) });
	const names = new Set<string>();
	for (const line of (r.stdout as string).split("\n")) {
		const key = line.split(/\s/)[0] ?? "";
		const parts = key.split(".");
		if (parts.length >= 3) names.add(parts.slice(1, -1).join("."));
	}
	fail("filter_driver", "filter driver の定義があります", { names: [...names].sort() });
}

/** 配置先の検査。何も作らず、書かない。jobId があれば作成先の不在も見る。 */
export function checkPlacement(repo: string, budget: Budget, limits: Limits, jobId?: string): void {
	ensureDirs(repo, PLACEMENT_DIRS, false);
	const o = { cwd: repo, budget, limits };
	for (const probe of [`${REL.worktrees}/x`, `${REL.records}/x.json`]) {
		const r = runGit(["check-ignore", "-q", probe], o);
		if (r.status === 1) fail("not_ignored", ".tmp が .gitignore で除外されていません", { path: probe });
		if (r.status !== 0) fail("git_failed", "git check-ignore が失敗しました", { status: r.status, stderr: r.stderr.slice(0, 300) });
	}
	const tracked = splitNul(git(["ls-files", "-z", REL.tmp], o));
	if (tracked.length > 0) fail("not_ignored", ".tmp の下に追跡されたファイルがあります", { tracked: tracked.slice(0, 5) });
	if (jobId !== undefined) {
		for (const p of [worktreePath(repo, jobId), recordPath(repo, jobId)]) {
			if (lstatOrNull(p)) fail("bad_placement", "作成先が既に存在します", { path: path.relative(repo, p) });
		}
	}
}

function countHeld(repo: string): { jobIds: string[]; states: Record<string, string> } {
	const states: Record<string, string> = {};
	for (const r of listRecords(repo)) {
		if ("broken" in r) continue;
		if (HELD_STATES.includes(r.state)) states[r.jobId] = r.state;
	}
	return { jobIds: Object.keys(states).sort(), states };
}

/** 順序は計画のとおり。オブジェクトを書かない (add・hash-object を呼ばない)。 */
export function preflight(
	repo: string,
	readDeny: ReadDeny,
	limits: Limits,
	budget: Budget,
	jobId?: string,
): { candidates: Candidates; totalBytes: number; head: string } {
	const root = canonRepo(repo);
	const head = assertRepoRoot(root, budget, limits); // (0)
	const candidates = listCandidates(root, budget, limits); // (1)
	const all = [...candidates.tracked, ...candidates.untracked];
	checkProtected(root, all, readDeny); // (2)
	const totalBytes = measure(root, all, limits); // (3)
	checkFilters(root, budget, limits); // (4)
	checkPlacement(root, budget, limits, jobId); // (5)
	const held = countHeld(root); // (6)
	if (held.jobIds.length >= limits.maxWorktrees) {
		fail("too_many", "保持中の worktree が上限に達しています (自動では消しません)", {
			max: limits.maxWorktrees,
			jobIds: held.jobIds,
			states: held.states,
		});
	}
	return { candidates, totalBytes, head };
}

// ─── スナップショット・作成 ─────────────────────────────────────────────

/** 一時 index で read-tree → add -A → write-tree。一時 index は必ず消す。実 index は触らない。 */
function snapshotTree(prefix: string[], cwd: string, indexPath: string, base: string, budget: Budget, limits: Limits): string {
	rmForce(indexPath);
	const o = { cwd, env: { GIT_INDEX_FILE: indexPath }, budget, limits };
	try {
		git([...prefix, "read-tree", base], o);
		git([...prefix, "add", "-A"], o);
		return git([...prefix, "write-tree"], o).trim();
	} finally {
		rmForce(indexPath);
	}
}

/** 本体の共通 git ディレクトリ (絶対パス)。 */
function commonDir(repo: string, budget: Budget, limits: Limits): string {
	const common = git(["rev-parse", "--git-common-dir"], { cwd: repo, budget, limits }).trim();
	return path.resolve(repo, common);
}

function adminDir(repo: string, jobId: string, budget: Budget, limits: Limits): string {
	return path.join(commonDir(repo, budget, limits), "worktrees", `pi-agent-${jobId}`);
}

/** 後始末 (失敗しても例外にしない)。他の worktree・ref・記録には触れない。残った理由を返す。 */
function removeWorktree(repo: string, jobId: string, limits: Limits): string[] {
	const notes: string[] = [];
	const wt = worktreePath(repo, jobId);
	const b = new Budget(limits.totalMs);
	const o = { cwd: repo, budget: b, limits };
	const tryGit = (args: string[]): GitResult | null => {
		try {
			return runGit(args, o);
		} catch (e) {
			notes.push(errLabel(e));
			return null;
		}
	};
	tryGit(["worktree", "unlock", wt]); // 未 lock なら失敗してよい
	const r = tryGit(["worktree", "remove", "--force", wt]);
	if (r && r.status !== 0) notes.push(`worktree remove: ${r.stderr.slice(0, 200).trim()}`);
	try {
		// ディレクトリが先に無くなっていると remove が拒むので、この job の管理領域だけを消す
		const admin = adminDir(repo, jobId, b, limits);
		if (!lstatOrNull(wt) && lstatOrNull(admin)) rmForce(admin);
	} catch (e) {
		notes.push(errLabel(e));
	}
	return notes;
}

/** worktree のパス・git への登録・管理領域のどれかがあれば true。調べられないときも true (消さない側に倒す)。 */
function hasWorktreeTraces(repo: string, jobId: string, limits: Limits): boolean {
	try {
		const wt = worktreePath(repo, jobId);
		if (lstatOrNull(wt)) return true;
		const b = new Budget(limits.totalMs);
		if (listWorktrees(repo, b, limits).some((w) => path.resolve(w.path) === wt)) return true;
		return lstatOrNull(adminDir(repo, jobId, b, limits)) !== null;
	} catch {
		return true;
	}
}

/**
 * `creating` の記録を書いた後に作成が失敗したときの処理。作りかけがあれば消さずに記録を `kept` にして git_failed、
 * 何も作られていないと確認できたときだけ記録を消して元の失敗を投げ直す。
 */
export function settleFailedCreate(repo: string, rec: IsolationRecord, stage: string, err: unknown, limits: Limits = DEFAULT_LIMITS): never {
	const cause = errLabel(err);
	if (!hasWorktreeTraces(repo, rec.jobId, limits)) {
		try {
			rmForce(recordPath(repo, rec.jobId));
		} catch {
			// 記録が残っても、reconcile が stuck_creating で拾う
		}
		if (err instanceof WorktreeError) throw err;
		throw new WorktreeError("git_failed", "作成に失敗しました", { stage, errno: errCode(err), message: String((err as Error)?.message ?? err).slice(0, 300) });
	}
	let recorded = true;
	try {
		writeRecord(repo, { ...rec, state: "kept", note: `${stage}: ${cause}` });
	} catch {
		recorded = false;
	}
	throw new WorktreeError("git_failed", `worktree の作成に失敗しました (${stage})。作りかけを保持しました`, {
		jobId: rec.jobId,
		stage,
		cause,
		kept: true,
		recorded,
	});
}

export function createIsolation(repo: string, jobId: string, readDeny: ReadDeny, limits: Limits = DEFAULT_LIMITS): IsolationRecord {
	validateJobId(jobId);
	const root = canonRepo(repo);
	const budget = new Budget(limits.totalMs);
	// 親の作業ツリーを書く前に、読むだけの検査で止める
	assertRepoRoot(root, budget, limits);
	checkPlacement(root, budget, limits, jobId);
	return withLock(root, limits, () => createLocked(root, jobId, readDeny, limits, budget));
}

function createLocked(root: string, jobId: string, readDeny: ReadDeny, limits: Limits, budget: Budget): IsolationRecord {
	let idx: string | null = null;
	let rec: IsolationRecord | null = null;
	let recorded = false;
	let stage = "snapshot";
	try {
		const pre = preflight(root, readDeny, limits, budget, jobId);
		const o = { cwd: root, budget, limits };
		const rawIdx = git(["rev-parse", "--git-path", `pi-agent-index-${jobId}`], o).trim();
		idx = path.resolve(root, rawIdx);
		const tree = snapshotTree([], root, idx, pre.head, budget, limits);
		// (7) 作成後の確認。ここで食い違っても、書いたオブジェクトは取り消せない
		const changed = splitNul(git(["diff-tree", "-r", "--name-only", "--no-renames", "-z", pre.head, tree], o));
		const allowed = new Set([...pre.candidates.tracked, ...pre.candidates.untracked].map((p) => p.replace(/\/$/, "")));
		const extra = changed.filter((p) => !allowed.has(p));
		if (extra.length > 0) {
			fail("snapshot_mismatch", "スナップショットが事前の候補と一致しません", {
				unexpected: extra.slice(0, 20),
				note: "オブジェクトは書き込み済みで取り消せません (参照されないまま gc まで残ります)",
			});
		}
		const snapshotCommit = git(["commit-tree", tree, "-p", pre.head, "-m", `pi-agent snapshot ${jobId}`], o).trim();
		ensureDirs(root, [REL.worktrees], true);
		const wt = worktreePath(root, jobId);
		// 記録を先に書く。worktree add の途中で落ちても、取り残しを reconcile と上限の計数が見つけられる
		rec = {
			version: 1,
			jobId,
			repo: root,
			worktree: wt,
			startCommit: pre.head,
			snapshotCommit,
			createdAt: new Date().toISOString(),
			state: "creating",
		};
		stage = "record-creating";
		writeRecord(root, rec);
		recorded = true;
		stage = "worktree-add";
		git(["worktree", "add", "--detach", wt, snapshotCommit], o);
		stage = "worktree-lock";
		git(["worktree", "lock", "--reason", `pi-agent ${jobId}`, wt], o);
		stage = "record-running";
		rec = { ...rec, state: "running" };
		writeRecord(root, rec);
		return rec;
	} catch (e) {
		if (recorded && rec) return settleFailedCreate(root, rec, stage, e, limits);
		if (e instanceof WorktreeError) throw e;
		throw new WorktreeError("git_failed", "作成に失敗しました", { errno: errCode(e), message: String((e as Error)?.message ?? e).slice(0, 300) });
	} finally {
		if (idx) rmForce(idx);
	}
}

// ─── 回収・破棄 ─────────────────────────────────────────────────────────

function publishExclusive(tmp: string, dest: string): void {
	try {
		fs.linkSync(tmp, dest);
		return;
	} catch (e) {
		if (errCode(e) === "EEXIST") fail("collect_failed", "patch が既に存在します (上書きしません)", { path: dest });
	}
	try {
		fs.copyFileSync(tmp, dest, fs.constants.COPYFILE_EXCL);
		fs.chmodSync(dest, 0o600);
	} catch (e) {
		if (errCode(e) === "EEXIST") fail("collect_failed", "patch が既に存在します (上書きしません)", { path: dest });
		throw e;
	}
}

// 管理領域 (`.git/worktrees/pi-agent-<id>`) に git が置くもの。これ以外の名前は拒否する。
const ADMIN_FILES = new Set(["HEAD", "ORIG_HEAD", "commondir", "gitdir", "locked", "index", "index.lock", "pi-agent-collect-index"]);
const ADMIN_DIRS = new Set(["logs", "refs"]);
const ADMIN_INDEX_FILES = new Set(["index", "index.lock", "pi-agent-collect-index"]);
const ADMIN_SMALL_BYTES = 1024;
const ADMIN_TREE_FILE_BYTES = 1024 * 1024;
const ADMIN_MAX_ENTRIES = 1000;
const ADMIN_HEAD_RE = /^([0-9a-f]{40}|[0-9a-f]{64})$/;

/** すべて通常ファイルかディレクトリ (lstat)。違反は bad を呼ぶ。 */
function walkAdminTree(dir: string, name: string, counter: { n: number }, bad: (v: string) => never): void {
	for (const ent of fs.readdirSync(dir, { withFileTypes: true })) {
		if (++counter.n > ADMIN_MAX_ENTRIES) bad("too_many_entries");
		const p = path.join(dir, ent.name);
		const st = fs.lstatSync(p);
		if (st.isSymbolicLink()) bad(`symlink_in_${name}`);
		else if (st.isDirectory()) walkAdminTree(p, name, counter, bad);
		else if (!st.isFile()) bad(`entry_type:${name}`);
		else if (st.size > ADMIN_TREE_FILE_BYTES) bad("bad_size");
	}
}

/** 通常ファイルで max 以下なら中身、無ければ null。種別・大きさの違反は bad。 */
function readSmall(p: string, name: string, bad: (v: string) => never, max = ADMIN_SMALL_BYTES): string | null {
	const st = lstatOrNull(p);
	if (!st) return null;
	if (!st.isFile()) return bad(`entry_type:${name}`);
	if (st.size > max) return bad("bad_size");
	return fs.readFileSync(p, "utf8");
}

/** 子が書ける管理領域を、git に渡す前に検証する。違反は collect_failed (detail.violation に種類)。 */
function verifyAdmin(root: string, jobId: string, wt: string, common: string, admin: string, limits: Limits): void {
	const bad = (violation: string): never =>
		fail("collect_failed", "worktree の管理領域の検証に失敗しました", { jobId, violation, admin: path.relative(root, admin) });
	let realCommon: string;
	try {
		realCommon = fs.realpathSync(common);
	} catch {
		return bad("common_dir");
	}
	const ast = lstatOrNull(admin);
	if (!ast || ast.isSymbolicLink() || !ast.isDirectory()) return bad("admin_not_directory");
	let realAdmin: string;
	try {
		realAdmin = fs.realpathSync(admin);
	} catch {
		return bad("admin_realpath");
	}
	if (realAdmin !== path.join(realCommon, "worktrees", `pi-agent-${jobId}`)) return bad("admin_outside_common");

	const cd = readSmall(path.join(admin, "commondir"), "commondir", bad);
	if (cd === null) return bad("commondir_missing");
	let cdReal: string;
	try {
		cdReal = fs.realpathSync(path.resolve(admin, cd.trim()));
	} catch {
		return bad("commondir_unresolved");
	}
	if (cdReal !== realCommon) return bad("commondir_mismatch");

	const gd = readSmall(path.join(admin, "gitdir"), "gitdir", bad);
	if (gd === null) return bad("gitdir_missing");
	if (gd.trim() !== path.join(wt, ".git")) return bad("gitdir_mismatch");

	const dot = readSmall(path.join(wt, ".git"), ".git", bad, 4096);
	if (dot === null) return bad("worktree_dotgit_missing");
	const want = dot.trim();
	if (want !== `gitdir: ${admin}` && want !== `gitdir: ${realAdmin}`) return bad("worktree_dotgit_mismatch");

	if (lstatOrNull(path.join(admin, "config.worktree"))) return bad("config_worktree");
	const counter = { n: 0 };
	for (const ent of fs.readdirSync(admin, { withFileTypes: true })) {
		const p = path.join(admin, ent.name);
		if (ADMIN_FILES.has(ent.name)) {
			if (!ent.isFile()) return bad(`entry_type:${ent.name}`);
			const max = ADMIN_INDEX_FILES.has(ent.name) ? limits.maxAdminIndexBytes : ADMIN_SMALL_BYTES;
			if (fs.lstatSync(p).size > max) return bad("bad_size");
			if (ent.name === "HEAD" && !ADMIN_HEAD_RE.test(fs.readFileSync(p, "utf8").replace(/\r?\n$/, ""))) {
				return bad("head_not_detached");
			}
		} else if (ADMIN_DIRS.has(ent.name)) {
			if (!ent.isDirectory()) return bad(`entry_type:${ent.name}`);
			walkAdminTree(p, ent.name, counter, bad);
		} else {
			return bad(`unexpected_entry:${ent.name}`);
		}
	}
}

/** `jobId` 以外の記録が、同じ patch のパスを参照しているか。 */
function patchReferencedByOthers(root: string, jobId: string, patchFile: string): boolean {
	return listRecords(root).some((r) => !("broken" in r) && r.jobId !== jobId && r.patch?.path === patchFile);
}

/** 呼び出し側が子のプロセスグループの停止を確認した後にだけ呼ぶ。see docs/change/0029-worktree-isolation.md の「子の停止の確認」 */
export function collect(repo: string, jobId: string, patchName: string, readDeny: ReadDeny, limits: Limits = DEFAULT_LIMITS): CollectResult {
	validateJobId(jobId);
	validatePatchName(patchName, jobId);
	const root = canonRepo(repo);
	ensureDirs(root, [REL.tmp, REL.subagents, REL.records], false);
	if (!lstatOrNull(path.join(root, REL.records))) return fail("collect_failed", "記録がありません", { jobId });
	return withLock(root, limits, () => collectLocked(root, jobId, patchName, readDeny, limits));
}

function collectLocked(root: string, jobId: string, patchName: string, readDeny: ReadDeny, limits: Limits): CollectResult {
	const budget = new Budget(limits.totalMs);
	let cur: IsolationRecord;
	try {
		const rec = readRecord(root, jobId);
		if (!rec) return fail("collect_failed", "記録がありません", { jobId });
		cur = rec;
	} catch (e) {
		if (e instanceof WorktreeError && e.code === "collect_failed") throw e;
		throw new WorktreeError("collect_failed", "記録を読めません", { jobId, cause: errLabel(e) });
	}
	if (cur.repo !== root) fail("collect_failed", "記録のリポジトリが違います", { jobId });
	if (cur.state !== "running" && cur.state !== "collecting" && cur.state !== "kept") {
		fail("collect_failed", "この状態では回収できません", { jobId, state: cur.state });
	}
	const wt = worktreePath(root, jobId);
	let stage = "record";
	let result: { resultCommit: string; ref: string; patch: { path: string; sha256: string } };
	try {
		const o = { cwd: root, budget, limits };
		cur = { ...cur, state: "collecting" };
		delete cur.note;
		writeRecord(root, cur);

		stage = "worktree";
		if (cur.worktree !== wt) fail("collect_failed", "記録の worktree のパスが規約と違います", { jobId });
		const st = lstatOrNull(wt);
		if (!st || st.isSymbolicLink() || !st.isDirectory()) fail("collect_failed", "worktree がありません", { jobId });

		stage = "admin";
		const common = commonDir(root, budget, limits);
		const admin = path.join(common, "worktrees", `pi-agent-${jobId}`);
		verifyAdmin(root, jobId, wt, common, admin, limits);

		stage = "snapshot";
		// extensions.worktreeConfig=false は config.worktree を読ませないための追加の防御 (検証 (e) が本命)
		const prefix = ["-c", "extensions.worktreeConfig=false", `--git-dir=${admin}`, `--work-tree=${wt}`];
		const tree = snapshotTree(prefix, wt, path.join(admin, "pi-agent-collect-index"), cur.snapshotCommit, budget, limits);
		const snapTree = git(["rev-parse", `${cur.snapshotCommit}^{tree}`], o).trim();
		if (tree === snapTree) {
			stage = "cleanup";
			runGit(["worktree", "unlock", wt], o); // 再回収で既に外れていてもよい
			git(["worktree", "remove", "--force", wt], o);
			rmForce(recordPath(root, jobId));
			return { changed: false };
		}

		stage = "protected";
		const paths = splitNul(git(["diff-tree", "-r", "--name-only", "--no-renames", "-z", snapTree, tree], o));
		checkProtected(root, paths, readDeny);

		stage = "commit";
		const ref = refName(jobId);
		const rev = (spec: string): string => {
			const r = runGit(["rev-parse", "--verify", "--quiet", spec], o);
			return r.status === 0 ? (r.stdout as string).trim() : "";
		};
		// 前回の回収が途中で落ちて同じ結果が ref に残っているなら再利用する (commit は時刻で変わるので tree と親で比べる)
		const prevCommit = rev(ref);
		const reuse = prevCommit !== "" && rev(`${prevCommit}^{tree}`) === tree && rev(`${prevCommit}^`) === cur.snapshotCommit;
		const resultCommit = reuse
			? prevCommit
			: git(["commit-tree", tree, "-p", cur.snapshotCommit, "-m", `pi-agent result ${jobId}`], o).trim();
		stage = "ref";
		if (!reuse) git(["update-ref", ref, resultCommit], o);
		cur = { ...cur, resultCommit, ref };

		stage = "patch";
		const buf = gitBuf(
			["diff", "--binary", "--full-index", "--no-renames", "--no-ext-diff", "--no-textconv", cur.snapshotCommit, resultCommit],
			o,
		);
		ensureDirs(root, [REL.tmp, REL.subagents], true);
		const dest = patchPath(root, patchName);
		const sha256 = createHash("sha256").update(buf).digest("hex");
		const existing = lstatOrNull(dest);
		if (existing) {
			// 前回の回収が公開後に落ちたときだけ再利用する (内容が同じ patch に限る。上書きはしない)。
			// 記録の patch.path が自分のものか、他の記録が参照していないときに限る
			const mine = cur.patch?.path === dest;
			if (!mine && patchReferencedByOthers(root, jobId, dest)) {
				fail("collect_failed", "patch を別の記録が参照しています (再利用しません)", { path: dest });
			}
			const same =
				existing.isFile() &&
				existing.size === buf.length &&
				createHash("sha256").update(fs.readFileSync(dest)).digest("hex") === sha256;
			if (!same) fail("collect_failed", "patch が既に存在します (上書きしません)", { path: dest });
		} else {
			const tmp = path.join(root, REL.subagents, `.${patchName}.${randomBytes(6).toString("hex")}.tmp`);
			try {
				writeNew(tmp, buf);
				publishExclusive(tmp, dest);
			} finally {
				rmForce(tmp);
			}
		}
		const patch = { path: dest, sha256 };

		stage = "record-collected";
		cur = { ...cur, state: "collected", patch };
		delete cur.note;
		writeRecord(root, cur);
		result = { resultCommit, ref, patch };
	} catch (e) {
		const code = errLabel(e);
		let recorded = true;
		try {
			writeRecord(root, { ...cur, state: "kept", note: `${stage}: ${code}` });
		} catch {
			recorded = false;
		}
		throw new WorktreeError("collect_failed", `回収に失敗しました (${stage})`, {
			jobId,
			stage,
			cause: code,
			causeDetail: e instanceof WorktreeError ? e.detail : { message: String((e as Error)?.message ?? e).slice(0, 300) },
			recorded,
		});
	}

	// 確定後。ここでの失敗で成果物の状態 (collected) は変えない
	const warnings: string[] = [];
	const warnUnlock = (why: string): void => {
		warnings.push(`unlock に失敗: ${why}`);
		try {
			writeRecord(root, { ...cur, note: `unlock に失敗: ${why}` });
		} catch {
			warnings.push("記録への注記に失敗");
		}
	};
	try {
		// 再回収で既に外れていてもよい ("is not locked" は警告しない)
		const u = runGit(["worktree", "unlock", wt], { cwd: root, budget: new Budget(limits.gitTimeoutMs), limits });
		if (u.status !== 0 && !/not locked/.test(u.stderr)) warnUnlock(`status ${u.status}`);
	} catch (e) {
		warnUnlock(errLabel(e));
	}
	return { changed: true, ...result, warnings };
}

/** 利用者のコマンド (S4) だけが呼ぶ。記録のない job は not_owned で何も消さない。 */
export function discard(repo: string, jobId: string, limits: Limits = DEFAULT_LIMITS): { notes: string[] } {
	validateJobId(jobId);
	const root = canonRepo(repo);
	ensureDirs(root, PLACEMENT_DIRS, false);
	if (!lstatOrNull(path.join(root, REL.records))) return fail("not_owned", "記録がありません", { jobId });
	return withLock(root, limits, () => discardLocked(root, jobId, limits));
}

function discardLocked(root: string, jobId: string, limits: Limits): { notes: string[] } {
	let rec: IsolationRecord | null;
	try {
		rec = readRecord(root, jobId);
	} catch {
		return fail("not_owned", "記録が壊れています (何も消していません)", { jobId });
	}
	if (!rec) return fail("not_owned", "記録がありません。このハーネスが作ったものではないので触りません", { jobId });
	if (rec.repo !== root) return fail("not_owned", "記録のリポジトリが違います (何も消していません)", { jobId });

	const notes: string[] = [];
	const wt = worktreePath(root, jobId);
	let blocked = false; // 残したもの (照合失敗・削除失敗) があれば、所有の証拠として記録を kept で残す

	// 管理領域の違反は、子が書いたものを信用できないので、ref・patch を含めて何も消さずに止める
	let violation: string | null = null;
	try {
		if (lstatOrNull(wt)) {
			const b = new Budget(limits.totalMs);
			const common = commonDir(root, b, limits);
			verifyAdmin(root, jobId, wt, common, path.join(common, "worktrees", `pi-agent-${jobId}`), limits);
		}
	} catch (e) {
		const v = e instanceof WorktreeError ? e.detail.violation : undefined;
		violation = typeof v === "string" ? v : errLabel(e);
	}
	if (violation !== null) {
		notes.push(`worktree kept: 管理領域の検証に失敗 (${violation})`, "record kept");
		try {
			writeRecord(root, { ...rec, state: "kept", note: `discard: ${notes.join("; ")}`.slice(0, 1000) });
		} catch (e) {
			notes.push(`record note: ${errCode(e) ?? "error"}`);
		}
		return { notes };
	}

	// worktree: 規約のパス・git への登録と完全一致・起点の子孫、がすべて合うときだけ
	try {
		const budget = new Budget(limits.totalMs);
		const entry = listWorktrees(root, budget, limits).find((w) => path.resolve(w.path) === wt);
		if (rec.worktree !== wt) {
			notes.push("worktree kept: 記録のパスが規約と違います");
			blocked = true;
		} else if (!entry) {
			if (lstatOrNull(wt)) {
				notes.push("worktree kept: git に登録されていません");
				blocked = true;
			}
		} else if (!OID_RE.test(rec.snapshotCommit) || !entry.head || entry.head.startsWith("-")) {
			notes.push("worktree kept: 起点を確認できません");
			blocked = true;
		} else {
			const anc = runGit(["merge-base", "--is-ancestor", rec.snapshotCommit, entry.head], { cwd: root, budget, limits });
			if (anc.status !== 0) {
				notes.push("worktree kept: HEAD が記録の起点の子孫ではありません");
				blocked = true;
			} else {
				notes.push(...removeWorktree(root, jobId, limits));
				if (hasWorktreeTraces(root, jobId, limits)) {
					notes.push("worktree kept: 削除後も残っています");
					blocked = true;
				}
			}
		}
	} catch (e) {
		notes.push(`worktree kept: ${errLabel(e)}`);
		blocked = true;
	}

	// ref: 記録が refs/pi-agent/<jobId> を指し、値が resultCommit と一致するときだけ
	try {
		const ref = refName(jobId);
		const r = runGit(["rev-parse", "--verify", "--quiet", ref], { cwd: root, budget: new Budget(limits.totalMs), limits });
		if (r.status === 0) {
			const value = (r.stdout as string).trim();
			if (rec.ref !== ref || rec.resultCommit === undefined || value !== rec.resultCommit) {
				notes.push("ref kept: 記録と値が一致しません");
				blocked = true;
			} else {
				const d = runGit(["update-ref", "-d", ref, value], { cwd: root, budget: new Budget(limits.totalMs), limits });
				if (d.status !== 0) {
					notes.push(`ref kept: update-ref -d: ${d.stderr.slice(0, 200).trim()}`);
					blocked = true;
				}
			}
		}
	} catch (e) {
		notes.push(`ref kept: ${errLabel(e)}`);
		blocked = true;
	}

	// patch: .tmp/subagents/ の直下の通常ファイルで、sha256 が記録と一致するときだけ
	if (rec.patch) {
		try {
			const p = rec.patch.path;
			const st = lstatOrNull(p);
			if (path.dirname(p) !== path.join(root, REL.subagents) || !PATCH_NAME_RE.test(path.basename(p))) {
				notes.push("patch kept: 記録のパスが規約と違います");
				blocked = true;
			} else if (st) {
				if (!st.isFile()) {
					notes.push("patch kept: 通常のファイルではありません");
					blocked = true;
				} else if (createHash("sha256").update(fs.readFileSync(p)).digest("hex") !== rec.patch.sha256) {
					notes.push("patch kept: sha256 が記録と一致しません");
					blocked = true;
				} else if (patchReferencedByOthers(root, jobId, p)) {
					notes.push("patch kept: 他の記録が参照");
				} else rmForce(p);
			}
		} catch (e) {
			notes.push(`patch kept: ${errLabel(e)}`);
			blocked = true;
		}
	}

	if (blocked) {
		notes.push("record kept");
		try {
			writeRecord(root, { ...rec, state: "kept", note: `discard: ${notes.join("; ")}`.slice(0, 1000) });
		} catch (e) {
			notes.push(`record note: ${errCode(e) ?? "error"}`);
		}
	} else {
		try {
			rmForce(recordPath(root, jobId));
		} catch (e) {
			notes.push(`rm record: ${errCode(e) ?? "error"}`);
		}
	}
	return { notes };
}

// ─── 照合 ───────────────────────────────────────────────────────────────

function listWorktrees(repo: string, budget: Budget, limits: Limits): { path: string; locked: boolean; head?: string }[] {
	const out = git(["worktree", "list", "--porcelain"], { cwd: repo, budget, limits });
	const result: { path: string; locked: boolean; head?: string }[] = [];
	for (const block of out.split(/\n\n+/)) {
		const lines = block.split("\n");
		const first = lines.find((l) => l.startsWith("worktree "));
		if (!first) continue;
		const head = lines.find((l) => l.startsWith("HEAD "));
		result.push({
			path: first.slice("worktree ".length),
			locked: lines.some((l) => l === "locked" || l.startsWith("locked ")),
			head: head ? head.slice("HEAD ".length).trim() : undefined,
		});
	}
	return result;
}

/** 食い違いの一覧だけを返す。何も消さない・直さない。このハーネスが作ったものだけを対象にする。 */
export function reconcile(repo: string, liveJobIds: string[] = [], limits: Limits = DEFAULT_LIMITS): ReconcileIssue[] {
	const root = canonRepo(repo);
	const budget = new Budget(limits.totalMs);
	const live = new Set(liveJobIds);
	const records = new Map<string, IsolationRecord>();
	for (const r of listRecords(root)) if (!("broken" in r)) records.set(r.jobId, r);

	const wtDir = path.join(root, REL.worktrees);
	const worktrees = new Map<string, { path: string; locked: boolean }>();
	for (const w of listWorktrees(root, budget, limits)) {
		const p = path.resolve(w.path);
		const base = path.basename(p);
		if (path.dirname(p) !== wtDir || !base.startsWith("pi-agent-")) continue;
		const id = base.slice("pi-agent-".length);
		if (JOB_ID_RE.test(id)) worktrees.set(id, w);
	}

	const refs = new Map<string, string>();
	const refOut = git(["for-each-ref", "--format=%(refname)", "refs/pi-agent/"], { cwd: root, budget, limits });
	for (const line of refOut.split("\n")) {
		const id = line.trim().slice("refs/pi-agent/".length);
		if (line.trim().startsWith("refs/pi-agent/") && JOB_ID_RE.test(id)) refs.set(id, line.trim());
	}

	const issues: ReconcileIssue[] = [];
	const ids = [...new Set([...records.keys(), ...worktrees.keys(), ...refs.keys()])].sort();
	for (const id of ids) {
		const rec = records.get(id);
		const wt = worktrees.get(id);
		const ref = refs.get(id);
		if (rec && rec.state === "creating") {
			// 作成の途中は他の食い違いを報告しない。長く続くものだけ stuck_creating
			const age = Date.now() - Date.parse(rec.createdAt);
			if (!(age < CREATING_STALE_MS)) {
				issues.push({ jobId: id, issue: "stuck_creating", detail: { createdAt: rec.createdAt, worktreePresent: Boolean(wt) } });
			}
			continue;
		}
		if (rec && !wt && !ref) {
			issues.push({ jobId: id, issue: "record_only", detail: { state: rec.state, patch: rec.patch?.path ?? null } });
			continue;
		}
		if (!rec && wt) issues.push({ jobId: id, issue: "worktree_only", detail: { worktree: wt.path, locked: wt.locked, ref: ref ?? null } });
		if (ref && !wt) issues.push({ jobId: id, issue: "ref_only", detail: { ref, hasRecord: Boolean(rec), state: rec?.state ?? null } });
		if (rec && (rec.state === "collected" || rec.patch)) {
			if (!rec.patch || !lstatOrNull(rec.patch.path)) {
				issues.push({ jobId: id, issue: "patch_missing", detail: { state: rec.state, patch: rec.patch?.path ?? null } });
			}
		}
		if (rec && (rec.state === "running" || rec.state === "collecting") && !live.has(id)) {
			issues.push({ jobId: id, issue: "stuck_running", detail: { state: rec.state, createdAt: rec.createdAt, worktreePresent: Boolean(wt) } });
		}
	}
	return issues;
}
