// ジョブの保存先と回復。設計: .tmp/keep/prv-app/api-contract-job.md の「保存先」。試験: test/agents/test_pr_viewer_jobs_store.py。
// 置き場: <stateDir>/<repoId>/jobs/<id>/{job.json,log.txt,prompt.txt} と <stateDir>/<repoId>/locks/<sha16(枝)>.lock。
// stateDir の既定は $XDG_STATE_HOME/pr-viewer（--state-dir で変える）。共通 .git の中には置かない（Fence から書けるため）。
// ディレクトリは 0700・ファイルは 0600。job.json は状態遷移ごとに atomic rename。ログは先頭 1 MiB まで。
import { createHash, randomUUID } from "node:crypto";
import {
	chmodSync,
	closeSync,
	existsSync,
	fsyncSync,
	linkSync,
	lstatSync,
	mkdirSync,
	openSync,
	readFileSync,
	readdirSync,
	realpathSync,
	renameSync,
	rmSync,
	statSync,
	unlinkSync,
	writeSync,
} from "node:fs";
import { homedir } from "node:os";
import { basename, dirname, join, resolve } from "node:path";

export const JOB_STATES = [
	"starting",
	"running",
	"finalizing",
	"succeeded",
	"no_change",
	"needs_review",
	"failed",
	"timed_out",
	"cancelled",
	"interrupted",
] as const;
export type JobState = (typeof JOB_STATES)[number];
export type JobFile = { path: string; status: "A" | "M" | "D" };

/** 契約の `job`（API でそのまま返す形）。reasons はコードだけ。 */
export type Job = {
	id: string;
	kind: string;
	state: JobState;
	reasons: string[];
	createdAt: string;
	startedAt: string | null;
	endedAt: string | null;
	elapsedSec: number;
	baseOid: string;
	resultOid: string | null;
	batchIds: string[];
	files: JobFile[] | null;
	exitCode: number | null;
};
/** 保存する形。契約の job に、API へ出さない内部の項目を足す。 */
export type JobRecord = Omit<Job, "elapsedSec"> & {
	branch: string;
	pid: number | null;
	pidStart: string | null;
	/** 起動前の記録の採取結果など、job-git.ts が使う自由な領域。API へは出さない。 */
	internal: unknown;
};
export type JobPatch = Partial<Omit<JobRecord, "id" | "createdAt" | "kind" | "branch" | "batchIds" | "baseOid">>;

export const LOG_LIMIT_BYTES = 1024 * 1024;
export const LOG_READ_MAX = 16 * 1024;
export const RETAIN_JOBS = 30;
export const RETAIN_DAYS = 14;

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const REPO_RE = /^r[0-9a-f]{8}$/;
const REASON_RE = /^[a-z][a-z0-9_]{0,40}$/;
const RANK: Record<string, number> = { starting: 0, running: 1, finalizing: 2 };

export function isTerminal(s: JobState): boolean {
	return !(s in RANK);
}

/** 既定の stateDir（$XDG_STATE_HOME/pr-viewer）。 */
export function defaultStateDir(env: NodeJS.ProcessEnv = process.env): string {
	const base = env.XDG_STATE_HOME && env.XDG_STATE_HOME.startsWith("/") ? env.XDG_STATE_HOME : join(homedir(), ".local", "state");
	return join(base, "pr-viewer");
}

export type Store = { root: string; repoId: string; jobsDir: string; locksDir: string };

function uid(): number | null {
	return typeof process.getuid === "function" ? process.getuid() : null;
}

/** 自分の持ち物の 0700 のディレクトリを用意する。シンボリックリンク・他人の持ち物は断る。 */
function ensureDir(dir: string, secure: boolean): void {
	try {
		mkdirSync(dir, { mode: 0o700 });
		chmodSync(dir, 0o700);
		return;
	} catch (e) {
		if ((e as NodeJS.ErrnoException).code !== "EEXIST") throw e; // 別のプロセスが先に作った
	}
	const st = lstatSync(dir);
	if (!st.isDirectory()) throw new Error("state dir is not a directory");
	if (uid() !== null && st.uid !== uid()) throw new Error("state dir is not owned by the current user");
	if (secure && (st.mode & 0o077) !== 0) chmodSync(dir, 0o700);
}

/** パスの realpath。まだ無い部分は、存在する一番深い祖先の realpath に残りをつなぐ（祖先の symlink を解決する）。 */
function realPathLoose(p: string): string {
	let cur = resolve(p);
	const rest: string[] = [];
	for (;;) {
		try {
			return join(realpathSync(cur), ...rest.reverse());
		} catch {
			const parent = dirname(cur);
			if (parent === cur) return resolve(p);
			rest.push(basename(cur));
			cur = parent;
		}
	}
}

/**
 * 保存先が、対象リポジトリの共通 .git や worktree の中なら断る（何も作る前に）。Fence 側から書ける場所に置かないため。
 * forbidden は共通 .git と worktree のパス（realpath で包含を判定する）。
 */
export function assertStateDirIsolated(stateDir: string, forbidden: string[]): void {
	const s = realPathLoose(stateDir);
	for (const f of forbidden) {
		const r = realPathLoose(f);
		if (s === r || s.startsWith(r.endsWith("/") ? r : `${r}/`)) throw new Error("state dir must not be inside the repository or a worktree");
	}
}

/** stateDir（絶対パス）の下に repoId の置き場を作って返す。forbidden の中への配置は、何も作る前に断る。 */
export function openStore(stateDir: string, repoId: string, forbidden: string[] = []): Store {
	if (!stateDir.startsWith("/")) throw new Error("state dir must be absolute");
	if (!REPO_RE.test(repoId)) throw new Error("bad repoId");
	assertStateDirIsolated(stateDir, forbidden);
	if (!existsSync(stateDir)) mkdirSync(stateDir, { recursive: true, mode: 0o700 });
	// 既存の stateDir（利用者が指定した場所）の権限は、他人に書かれないときは触らない
	const root = lstatSync(stateDir);
	if (!root.isDirectory()) throw new Error("state dir is not a directory");
	if (uid() !== null && root.uid !== uid()) throw new Error("state dir is not owned by the current user");
	if ((root.mode & 0o022) !== 0) throw new Error("state dir is writable by group or others");
	const repoDir = join(stateDir, repoId);
	const jobsDir = join(repoDir, "jobs");
	const locksDir = join(repoDir, "locks");
	for (const d of [repoDir, jobsDir, locksDir]) ensureDir(d, true);
	return { root: stateDir, repoId, jobsDir, locksDir };
}

function jobDir(store: Store, id: string): string {
	if (!UUID_RE.test(id)) throw new Error("bad job id");
	return join(store.jobsDir, id);
}

/** 同じディレクトリの一時ファイルに書いて fsync し、rename で置き換える（0600）。 */
function atomicWrite(path: string, text: string): void {
	const tmp = `${path}.${randomUUID()}.tmp`;
	const fd = openSync(tmp, "wx", 0o600);
	try {
		writeSync(fd, text);
		fsyncSync(fd);
	} finally {
		closeSync(fd);
	}
	try {
		renameSync(tmp, path);
	} catch (e) {
		rmSync(tmp, { force: true });
		throw e;
	}
}

// ---- プロセスの識別 ----

/** /proc/<pid>/stat の starttime（起動からの時刻）。pid の再利用の見分けに使う。取れなければ null。 */
export function procStartOf(pid: number): string | null {
	if (!Number.isInteger(pid) || pid <= 0) return null;
	try {
		const stat = readFileSync(`/proc/${pid}/stat`, "utf8");
		const rest = stat.slice(stat.lastIndexOf(")") + 2).split(" "); // 3 番目の項目（state）から
		if (rest[0] === "Z") return null; // 終わっていて回収待ちのプロセスは、死んだものとして扱う
		return rest[19] ?? null; // 22 番目 = starttime
	} catch {
		return null;
	}
}

/** pid が生きていて、記録した開始時刻と一致するか（pid の再利用は別物として扱う）。 */
export function sameProcess(pid: number | null, start: string | null): boolean {
	if (pid === null || start === null) return false;
	return procStartOf(pid) === start;
}

// ---- job.json ----

function validRecord(x: unknown): x is JobRecord {
	if (typeof x !== "object" || x === null) return false;
	const r = x as Record<string, unknown>;
	return (
		typeof r.id === "string" &&
		UUID_RE.test(r.id) &&
		typeof r.state === "string" &&
		(JOB_STATES as readonly string[]).includes(r.state) &&
		typeof r.createdAt === "string" &&
		Array.isArray(r.reasons) &&
		Array.isArray(r.batchIds)
	);
}

/** job.json を読む。無い・壊れているときは null。 */
export function readJob(store: Store, id: string): JobRecord | null {
	try {
		const parsed: unknown = JSON.parse(readFileSync(join(jobDir(store, id), "job.json"), "utf8"));
		return validRecord(parsed) ? parsed : null;
	} catch {
		return null;
	}
}

/** API に出す形（内部の項目を落とし、elapsedSec を足す）。 */
export function publicJob(r: JobRecord, now: number = Date.now()): Job {
	const start = r.startedAt ? Date.parse(r.startedAt) : NaN;
	const end = r.endedAt ? Date.parse(r.endedAt) : now;
	const elapsedSec = Number.isFinite(start) ? Math.max(0, Math.floor((end - start) / 1000)) : 0;
	return {
		id: r.id,
		kind: r.kind,
		state: r.state,
		reasons: r.reasons,
		createdAt: r.createdAt,
		startedAt: r.startedAt,
		endedAt: r.endedAt,
		elapsedSec,
		baseOid: r.baseOid,
		resultOid: r.resultOid,
		batchIds: r.batchIds,
		files: r.files,
		exitCode: r.exitCode,
	};
}

export type NewJob = { kind: string; branch: string; baseOid: string; batchIds: string[] };

/** ジョブを `starting` で作る（ディレクトリ 0700・job.json 0600・空の log.txt）。 */
export function createJob(store: Store, input: NewJob, now: number = Date.now()): JobRecord {
	const id = randomUUID();
	const dir = jobDir(store, id);
	mkdirSync(dir, { mode: 0o700 });
	chmodSync(dir, 0o700);
	const rec: JobRecord = {
		id,
		kind: input.kind,
		state: "starting",
		reasons: [],
		createdAt: new Date(now).toISOString(),
		startedAt: null,
		endedAt: null,
		baseOid: input.baseOid,
		resultOid: null,
		batchIds: input.batchIds,
		files: null,
		exitCode: null,
		branch: input.branch,
		pid: null,
		pidStart: null,
		internal: null,
	};
	atomicWrite(join(dir, "job.json"), `${JSON.stringify(rec, null, "\t")}\n`);
	closeSync(openSync(join(dir, "log.txt"), "a", 0o600));
	return rec;
}

/**
 * 状態・結果を更新する（atomic rename）。終端のジョブは変えられない。状態は前へだけ進む。
 * 終端へ進めたときは endedAt を入れる。pid だけを渡したら、開始時刻（pidStart）も採取する。
 */
export function updateJob(store: Store, id: string, patch: JobPatch, now: number = Date.now()): JobRecord {
	const cur = readJob(store, id);
	if (!cur) throw new Error("job not found");
	if (isTerminal(cur.state)) throw new Error("job is already terminal");
	const next: JobRecord = { ...cur, ...patch };
	if (patch.state !== undefined) {
		if (!(JOB_STATES as readonly string[]).includes(patch.state)) throw new Error("bad state");
		if (!isTerminal(patch.state) && RANK[patch.state] < RANK[cur.state]) throw new Error("state cannot go back");
	}
	if (!next.reasons.every((r) => typeof r === "string" && REASON_RE.test(r))) throw new Error("reasons must be codes");
	if (patch.pid !== undefined && patch.pid !== null && patch.pidStart === undefined) next.pidStart = procStartOf(patch.pid);
	if (next.state === "running" && next.startedAt === null) next.startedAt = new Date(now).toISOString();
	if (isTerminal(next.state)) next.endedAt = new Date(now).toISOString();
	atomicWrite(join(jobDir(store, id), "job.json"), `${JSON.stringify(next, null, "\t")}\n`);
	return next;
}

/** 新しい順（createdAt、同じなら id）。壊れた job.json は飛ばす。 */
export function listJobs(store: Store, limit: number = Number.POSITIVE_INFINITY): JobRecord[] {
	const out: JobRecord[] = [];
	for (const name of readdirSync(store.jobsDir)) {
		if (!UUID_RE.test(name)) continue;
		const r = readJob(store, name);
		if (r) out.push(r);
	}
	out.sort((a, b) => (a.createdAt === b.createdAt ? (a.id < b.id ? 1 : -1) : a.createdAt < b.createdAt ? 1 : -1));
	return out.slice(0, limit);
}

// ---- prompt.txt・log.txt ----

export function writePrompt(store: Store, id: string, text: string): void {
	atomicWrite(join(jobDir(store, id), "prompt.txt"), text);
}

/** ログへ追記する。先頭 LOG_LIMIT_BYTES までだけ保存し、超えた分は捨てる。 */
export function appendLog(store: Store, id: string, chunk: Buffer | string): { written: number; truncated: boolean } {
	const buf = typeof chunk === "string" ? Buffer.from(chunk, "utf8") : chunk;
	const path = join(jobDir(store, id), "log.txt");
	const fd = openSync(path, "a", 0o600);
	try {
		const size = statSync(path).size;
		const room = Math.max(0, LOG_LIMIT_BYTES - size);
		const n = Math.min(room, buf.length);
		if (n > 0) writeSync(fd, buf, 0, n);
		return { written: n, truncated: n < buf.length || size + n >= LOG_LIMIT_BYTES };
	} finally {
		closeSync(fd);
	}
}

/** ログの from（バイト位置）以降を最大 max バイト返す。文字の途中では切らない。衛生化（パスの置換など）は呼び出し側。 */
export function readLog(store: Store, id: string, from: number, max: number = LOG_READ_MAX): { from: number; next: number; text: string; truncated: boolean } {
	const buf = readFileSync(join(jobDir(store, id), "log.txt"));
	const start = Number.isInteger(from) ? Math.min(Math.max(0, from), buf.length) : 0;
	let end = Math.min(buf.length, start + Math.max(0, max));
	while (end < buf.length && end > start && (buf[end] & 0xc0) === 0x80) end--;
	return { from: start, next: end, text: buf.subarray(start, end).toString("utf8"), truncated: buf.length >= LOG_LIMIT_BYTES };
}

// ---- 行境界のログ ----

/** 長すぎる 1 行の代わりに返す表示（中身は返さない）。 */
export const LONG_LINE_MARK = "[長すぎる行を省略]\n";

/**
 * ログを「生ログの行境界」で返す（行をまたいだパスの断片を返さないため）。
 * from が行の途中なら、その行の残りは捨てて次の行首から返す。終わりも改行まで。
 * max を超える 1 行は LONG_LINE_MARK に置き換え、行末まで進める。改行の無い末尾の短い行は、
 * final（ジョブが終端）のときだけ返す（まだ書かれている行は待つ）。
 */
export function readLogLines(
	store: Store,
	id: string,
	from: number,
	max: number = LOG_READ_MAX,
	final = false,
): { from: number; next: number; text: string; truncated: boolean } {
	const buf = readFileSync(join(jobDir(store, id), "log.txt"));
	const truncated = buf.length >= LOG_LIMIT_BYTES;
	let start = Number.isInteger(from) ? Math.min(Math.max(0, from), buf.length) : 0;
	if (start > 0 && start < buf.length && buf[start - 1] !== 0x0a) {
		const nl = buf.indexOf(0x0a, start);
		start = nl < 0 ? buf.length : nl + 1; // 行の途中からは返さない
	}
	const out: Buffer[] = [];
	let pos = start;
	let size = 0;
	while (pos < buf.length) {
		const nl = buf.indexOf(0x0a, pos);
		const lineEnd = nl < 0 ? buf.length : nl + 1;
		const len = lineEnd - pos;
		if (nl < 0 && !final && len <= max) break; // まだ書かれている行
		const piece = len > max ? Buffer.from(LONG_LINE_MARK, "utf8") : buf.subarray(pos, lineEnd);
		if (size + piece.length > max && size > 0) break;
		out.push(piece);
		size += piece.length;
		pos = lineEnd;
	}
	return { from: start, next: pos, text: Buffer.concat(out).toString("utf8"), truncated };
}

// ---- 排他ファイル ----

type LockBody = { pid: number; start: string | null; jobId: string };

function lockPath(store: Store, branch: string): string {
	return join(store.locksDir, `${createHash("sha256").update(branch, "utf8").digest("hex").slice(0, 16)}.lock`);
}

function readLock(path: string): LockBody | null {
	try {
		const x = JSON.parse(readFileSync(path, "utf8")) as Record<string, unknown>;
		if (typeof x.pid === "number" && typeof x.jobId === "string") return { pid: x.pid, start: typeof x.start === "string" ? x.start : null, jobId: x.jobId };
	} catch {
		/* 壊れたロックは古いものとして扱う */
	}
	return null;
}

/** ロックが古い（持ち主が死んでいる・ジョブが終端・壊れている）か。 */
function lockIsStale(store: Store, body: LockBody | null): boolean {
	if (!body) return true;
	if (!sameProcess(body.pid, body.start)) return true;
	const job = UUID_RE.test(body.jobId) ? readJob(store, body.jobId) : null;
	return job !== null && isTerminal(job.state);
}

export type LockResult = { ok: true } | { ok: false; holder: { pid: number; jobId: string } | null };

/**
 * 同じ枝のロックを取る。ロックは「内容を書き終えた一時ファイルを link する」ので、空のロックは見えない。
 * 古いロック（持ち主が死んだ・ジョブが終端）は 1 度だけ掃除して取り直す。持ち主は既定でこのプロセス。
 */
export function acquireLock(store: Store, branch: string, jobId: string, pid: number = process.pid): LockResult {
	const path = lockPath(store, branch);
	const body: LockBody = { pid, start: procStartOf(pid), jobId };
	for (let attempt = 0; attempt < 2; attempt++) {
		const tmp = `${path}.${randomUUID()}.tmp`;
		const fd = openSync(tmp, "wx", 0o600);
		try {
			writeSync(fd, JSON.stringify(body));
			fsyncSync(fd);
		} finally {
			closeSync(fd);
		}
		try {
			linkSync(tmp, path);
			return { ok: true };
		} catch (e) {
			if ((e as NodeJS.ErrnoException).code !== "EEXIST") throw e;
		} finally {
			rmSync(tmp, { force: true });
		}
		const holder = readLock(path);
		if (!lockIsStale(store, holder)) return { ok: false, holder: holder ? { pid: holder.pid, jobId: holder.jobId } : null };
		// 古いロックは rename で 1 つのプロセスだけが取り除く（他は ENOENT）。別の者が取り直した新しいロックを奪ったら戻す
		const grave = `${path}.${randomUUID()}.stale`;
		try {
			renameSync(path, grave);
		} catch {
			continue;
		}
		const seen = readLock(grave);
		if (seen && !lockIsStale(store, seen)) {
			try {
				linkSync(grave, path);
			} catch {
				/* 戻せなければ、持ち主の側が次の確認で気づく */
			}
			rmSync(grave, { force: true });
			return { ok: false, holder: { pid: seen.pid, jobId: seen.jobId } };
		}
		rmSync(grave, { force: true });
	}
	return { ok: false, holder: readLock(path) };
}

/** 自分（jobId）のロックだけを外す。 */
export function releaseLock(store: Store, branch: string, jobId: string): boolean {
	const path = lockPath(store, branch);
	const cur = readLock(path);
	if (!cur || cur.jobId !== jobId) return false;
	try {
		unlinkSync(path);
		return true;
	} catch {
		return false;
	}
}

// ---- 日次の数え ----

/** 日付（UTC の YYYY-MM-DD）。 */
const dayOf = (now: number): string => new Date(now).toISOString().slice(0, 10);

/** 日次の数えは、費用の上限なので stateDir の直下に 1 つ（リポジトリをまたぐ）。保持の整理では消えない。 */
function dailyPath(store: Store): string {
	return join(store.root, "daily.json");
}

export function dailyCount(store: Store, now: number = Date.now()): number {
	try {
		const x = JSON.parse(readFileSync(dailyPath(store), "utf8")) as { day?: unknown; count?: unknown };
		return x.day === dayOf(now) && typeof x.count === "number" && x.count >= 0 ? x.count : 0;
	} catch {
		return 0;
	}
}

/** 上限に達していなければ 1 つ数える（ok）。達していたら数えずに ok:false。 */
export function countDaily(store: Store, limit: number, now: number = Date.now()): { ok: boolean; count: number } {
	const count = dailyCount(store, now);
	if (count >= limit) return { ok: false, count };
	atomicWrite(dailyPath(store), `${JSON.stringify({ day: dayOf(now), count: count + 1 })}\n`);
	return { ok: true, count: count + 1 };
}

// ---- 保持・回復 ----

/** 終端のジョブを、14 日より古いもの・新しい順で 30 件を超えるものから消す。実行中は消さない。消した id を返す。 */
export function prune(store: Store, now: number = Date.now(), maxJobs: number = RETAIN_JOBS, maxDays: number = RETAIN_DAYS): string[] {
	const removed: string[] = [];
	const done = listJobs(store).filter((j) => isTerminal(j.state));
	done.forEach((j, i) => {
		const t = Date.parse(j.endedAt ?? j.createdAt);
		const old = Number.isFinite(t) && now - t > maxDays * 86400_000;
		if (i >= maxJobs || old) {
			rmSync(jobDir(store, j.id), { recursive: true, force: true });
			removed.push(j.id);
		}
	});
	return removed;
}

const sleep = (ms: number): Promise<void> => new Promise((r) => setTimeout(r, ms));

function signalGroup(pid: number, sig: NodeJS.Signals): void {
	try {
		process.kill(-pid, sig); // detached で起動した子は、pid がプロセスグループの先頭
	} catch {
		/* すでに居ない */
	}
}

/** このプロセスとその祖先の pid（実 /proc から辿る）。cwd 走査で、アプリ自身や起動元を撃たないために除く。 */
function selfAndAncestors(): Set<number> {
	const s = new Set<number>([process.pid]);
	for (let pid = process.pid; pid > 1; ) {
		try {
			const stat = readFileSync(`/proc/${pid}/stat`, "utf8");
			pid = Number(stat.slice(stat.lastIndexOf(")") + 2).split(" ")[1]);
		} catch {
			break;
		}
		if (!Number.isInteger(pid) || pid <= 0 || s.has(pid)) break;
		s.add(pid);
	}
	return s;
}

/** 記録の internal.pre.worktree（pis の作業場所）。無ければ null。 */
export function worktreeOf(rec: { internal?: unknown } | null | undefined): string | null {
	const wt = (rec?.internal as { pre?: { worktree?: unknown } } | null | undefined)?.pre?.worktree;
	return typeof wt === "string" && wt.startsWith("/") ? wt : null;
}

/**
 * 停止の対象の pid（このプロセスとその祖先を除く）。次の 2 系統の和。pid の再利用に影響されない。
 * (a) 環境に PR_VIEWER_JOB_ID=<id> を持つ。
 * (b) worktree が与えられたとき、cwd が worktree の中（realpath。末尾 `/` つきの前方一致で wt2 を取り違えない）。
 *     印を持たない子孫（通信の中継 envoy など）を拾う。
 */
export function findByJobId(jobId: string, procRoot = "/proc", worktree: string | null = null): number[] {
	const mark = `PR_VIEWER_JOB_ID=${jobId}`;
	const out: number[] = [];
	let names: string[];
	try {
		names = readdirSync(procRoot);
	} catch {
		return out;
	}
	let wt: string | null = null;
	if (worktree !== null) {
		try {
			const r = realpathSync(worktree);
			wt = r.endsWith("/") ? r : `${r}/`;
		} catch {
			wt = null; // 作業場所が既に無い: cwd 走査はしない
		}
	}
	const skip = selfAndAncestors();
	for (const name of names) {
		if (!/^\d+$/.test(name) || skip.has(Number(name))) continue;
		try {
			if (readFileSync(`${procRoot}/${name}/environ`).toString("latin1").split("\0").includes(mark)) {
				out.push(Number(name));
				continue;
			}
		} catch {
			// 読めない・既に終了
		}
		if (wt === null) continue;
		try {
			const cwd = realpathSync(`${procRoot}/${name}/cwd`);
			if (`${cwd}/`.startsWith(wt)) out.push(Number(name));
		} catch {
			// cwd が読めない・既に終了
		}
	}
	return out;
}

/** 停止の対象へシグナルを送る。送った数を返す（runner と回復で共通）。 */
export function signalByJobId(jobId: string, sig: NodeJS.Signals, procRoot = "/proc", worktree: string | null = null): number {
	let n = 0;
	for (const pid of findByJobId(jobId, procRoot, worktree)) {
		try {
			process.kill(pid, sig);
			n++;
		} catch {
			// 既に終了
		}
	}
	return n;
}

export type RecoverResult = {
	interrupted: string[];
	killed: string[];
	/** 残存プロセスの消滅を確認できなかったジョブ。interrupted にせず、ロックも残す。 */
	survivors: string[];
	locksRemoved: number;
	pruned: string[];
};

/** SIGKILL 後に消滅を確認する待ち（ポーリング）。 */
export const CONFIRM_MS = 10_000;

/**
 * 起動時の回復。非終端のジョブは `interrupted`（reasons: shutdown）にする。自動では再開しない。
 * 停止対象は 2 系統の和: (a) pid と開始時刻が一致して生きている親のプロセスグループ、
 * (b) 親の生死に関係なく、環境に PR_VIEWER_JOB_ID=<id> を持つか、cwd が当該ジョブの worktree の中のプロセス（/proc 走査。setsid で抜けた子孫・印のない envoy を含む）。
 * SIGTERM → graceMs 待つ → SIGKILL → 消滅を確認する。確認できないジョブは survivors に入れ、
 * 状態もロックも変えない（呼び出し側がそのリポジトリのジョブ受付を止める）。
 * そのうえで古いロックを掃除し、保持の整理をする。
 */
export async function recover(store: Store, opts: { graceMs?: number; now?: number; procRoot?: string; confirmMs?: number } = {}): Promise<RecoverResult> {
	const graceMs = opts.graceMs ?? 15_000;
	const now = opts.now ?? Date.now();
	const root = opts.procRoot ?? "/proc";
	const res: RecoverResult = { interrupted: [], killed: [], survivors: [], locksRemoved: 0, pruned: [] };
	const live = listJobs(store).filter((j) => !isTerminal(j.state));
	const parentOk = (j: JobRecord): boolean => j.pid !== null && sameProcess(j.pid, j.pidStart);
	const groupTargets = new Set(live.filter(parentOk).map((j) => j.id));
	const remains = (j: JobRecord): boolean => (groupTargets.has(j.id) && parentOk(j)) || findByJobId(j.id, root, worktreeOf(j)).length > 0;
	const touched = live.filter(remains);
	for (const j of touched) {
		if (groupTargets.has(j.id)) signalGroup(j.pid as number, "SIGTERM");
		signalByJobId(j.id, "SIGTERM", root, worktreeOf(j));
	}
	for (let end = Date.now() + graceMs; Date.now() < end && touched.some(remains); ) await sleep(50);
	for (const j of touched.filter(remains)) {
		if (groupTargets.has(j.id) && parentOk(j)) signalGroup(j.pid as number, "SIGKILL"); // 直前に生死と開始時刻を確かめた親だけ
		signalByJobId(j.id, "SIGKILL", root, worktreeOf(j));
	}
	for (let end = Date.now() + (opts.confirmMs ?? CONFIRM_MS); Date.now() < end && touched.some(remains); ) await sleep(50);
	const survivors = new Set(touched.filter(remains).map((j) => j.id));
	for (const j of touched) {
		if (survivors.has(j.id)) res.survivors.push(j.id);
		else res.killed.push(j.id);
	}
	for (const j of live) {
		if (survivors.has(j.id)) continue;
		updateJob(store, j.id, { state: "interrupted", reasons: ["shutdown"] }, now);
		res.interrupted.push(j.id);
	}
	for (const name of readdirSync(store.locksDir)) {
		const p = join(store.locksDir, name);
		if (!name.endsWith(".lock")) {
			rmSync(p, { force: true }); // 途中で落ちた一時ファイルの残り
			continue;
		}
		const body = readLock(p);
		if (body && survivors.has(body.jobId)) continue; // 子孫が残っている間は、同じ枝を受け付けない
		if (lockIsStale(store, body)) {
			rmSync(p, { force: true });
			res.locksRemoved++;
		}
	}
	res.pruned = prune(store, now);
	return res;
}
