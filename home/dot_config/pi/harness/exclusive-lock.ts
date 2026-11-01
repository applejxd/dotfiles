// 統合の実行を守る排他ロック (CHG-0055 の P8c)。refs/pi/lock/<鍵> の CAS ref 1 本。鍵は canonical common-dir 単位 (粗い 1 本)。
//
//   取得 = `update-ref --no-deref <ref> <新> <旧値なし>` (無いときだけ作る)。解放 = `update-ref -d <ref> <OID>` (OID が合うときだけ消す)。
//
// ★fail-closed: 自動で消すのは「検証できた同一の試行が reserved で、owner が gone」の 1 通りだけ。
//   読めない・symbolic・不正なロックと、alive / unknown / started / 検証できない試行は、人の復旧 (forceRelease) に回す。
// ★承認なしに動くので、git の hook・署名は動かさない (pending-ops.ts と同じ SAFE 設定)。保存層 (pending-ops.ts) とは別の名前空間で、一覧に出ない。
// pending-ops.ts の transact・makeCommit・refOid は非 export なので、必要な分だけ自前で持つ。
// see docs/change/0055-async-approval.md#設計の契約
import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { realpathSync } from "node:fs";
import { isAbsolute, resolve } from "node:path";
import { canonicalJson, validateOwner } from "./pending-ops.ts";
import { currentOwner } from "./pending-owner.ts";
import { repoTargetEnv } from "./pending-store.ts";

export const LOCK_PREFIX = "refs/pi/lock/";

export type Holder = { runningId: string; attemptId: string };
export type LockHandle = { ref: string; oid: string };
export type ProbeResult = {
	attempt: "reserved" | "started" | "absent" | "mismatch" | "unreadable";
	owner: "alive" | "gone" | "unknown";
};
export type LockRead =
	| { state: "missing" }
	| { state: "held"; oid: string; holder: Holder; at: string; owner: unknown }
	| { state: "invalid"; reason: string }
	| { state: "unreadable"; reason: string };
export type AcquireFail = {
	ok: false;
	code: "held" | "stale_started" | "unverifiable" | "invalid_lock" | "git_failed";
	reason: string;
	holder?: Holder;
};
export type AcquireResult = { ok: true; handle: LockHandle; recovered?: "reserved_gone" } | AcquireFail;

type Env = NodeJS.ProcessEnv | undefined;
type Run = { ok: boolean; out: string; err: string; status?: number | null };

const SAFE = ["-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false", "-c", "core.quotepath=false", "-c", "commit.gpgsign=false"];
const OID_RE = /^[0-9a-f]{40}([0-9a-f]{24})?$/;
const KEY_RE = /^[0-9a-f]{64}$/;
const RUNNING_ID_RE = /^\d{15}(-\d{2})?$/;
const ATTEMPT_ID_RE = /^[A-Za-z0-9_.-]{1,100}$/;
const MAX_LOCK_BYTES = 16 * 1024;

function git(cwd: string, args: string[], env: Env, opts: { input?: string; extra?: Record<string, string> } = {}): Run {
	const r = spawnSync("git", [...SAFE, ...args], {
		cwd,
		encoding: "utf8",
		timeout: 15000,
		input: opts.input,
		env: { ...repoTargetEnv(env ?? process.env), ...opts.extra, GIT_OPTIONAL_LOCKS: "0", GIT_TERMINAL_PROMPT: "0" },
	});
	return { ok: r.status === 0, out: String(r.stdout ?? "").replace(/\n+$/, ""), err: String(r.stderr ?? "").trim(), status: r.status };
}

// ---- 鍵 ----

/** common-dir (正規化した絶対パス) 単位の鍵。同じリポジトリの別 worktree・サブディレクトリ・symlink 経由で同じ鍵になる */
export function lockKeyOf(cwd: string, env?: NodeJS.ProcessEnv): { ok: true; key: string; commonDir: string } | { ok: false; reason: string } {
	const r = git(cwd, ["rev-parse", "--git-common-dir"], env);
	if (!r.ok || !r.out) return { ok: false, reason: "git の common-dir を取得できなかった" };
	let commonDir: string;
	try {
		commonDir = realpathSync(isAbsolute(r.out) ? r.out : resolve(cwd, r.out));
	} catch {
		return { ok: false, reason: "common-dir を正規化できなかった" };
	}
	const key = createHash("sha256").update(canonicalJson({ version: 1, commonDir })).digest("hex");
	return { ok: true, key, commonDir };
}

const refOf = (key: string) => `${LOCK_PREFIX}${key}`;

// ---- 検証・読み取り ----

export function validHolder(h: unknown): h is Holder {
	if (typeof h !== "object" || h === null || Array.isArray(h)) return false;
	const o = h as Record<string, unknown>;
	return typeof o.runningId === "string" && RUNNING_ID_RE.test(o.runningId) && typeof o.attemptId === "string" && ATTEMPT_ID_RE.test(o.attemptId);
}

/** 不存在と、読み取りの失敗・symbolic・不正を別の状態で返す (null に畳まない) */
export function readLock(cwd: string, key: string, env?: NodeJS.ProcessEnv): LockRead {
	if (!KEY_RE.test(key)) return { state: "invalid", reason: "鍵の形が不正" };
	const ref = refOf(key);
	const r = git(cwd, ["for-each-ref", "--format=%(refname)%00%(objectname)%00%(symref)", ref], env);
	if (!r.ok) return { state: "unreadable", reason: `ref を列挙できなかった: ${r.err.split("\n").pop() ?? ""}` };
	if (!r.out) {
		// 壊れた ref は警告だけで列挙から落ちる。stderr があれば「無い」と言わない
		if (r.err) return { state: "unreadable", reason: `ref の列挙に警告 (壊れた ref の疑い): ${r.err.split("\n")[0]}` };
		// dangling / loop の symbolic ref も列挙から黙って落ちる。symbolic-ref はその ref 自体を読む (無い・通常の ref なら状態 1)
		const s = git(cwd, ["symbolic-ref", "-q", ref], env);
		return s.ok ? { state: "invalid", reason: "symbolic ref (dangling を含む)" } : s.status === 1 ? { state: "missing" } : { state: "unreadable", reason: "symbolic-ref を読めなかった (loop など)" };
	}
	const lines = r.out.split("\n");
	const [name, oid, symref] = (lines[0] ?? "").split("\0");
	if (lines.length !== 1 || name !== ref) return { state: "invalid", reason: "想定外の ref が返った" };
	if (symref) return { state: "invalid", reason: "symbolic ref" };
	if (!OID_RE.test(oid ?? "")) return { state: "invalid", reason: "ref の OID が不正" };
	const c = git(cwd, ["cat-file", "commit", oid], env);
	if (!c.ok) return { state: "unreadable", reason: "commit を読めない (オブジェクトの欠落など)" };
	const tree = /^tree ([0-9a-f]+)$/.exec(c.out.split("\n")[0] ?? "")?.[1];
	if (!tree) return { state: "invalid", reason: "commit に tree が無い" };
	const ls = git(cwd, ["ls-tree", "-l", "-z", tree], env);
	if (!ls.ok) return { state: "unreadable", reason: "tree を読めない" };
	const entries = ls.out.split("\0").filter(Boolean);
	const m = entries.length === 1 ? /^100644 blob ([0-9a-f]+)\s+(\d+)\tlock\.json$/.exec(entries[0]) : null;
	if (!m) return { state: "invalid", reason: "tree が lock.json だけの通常ファイルではない" };
	if (Number(m[2]) > MAX_LOCK_BYTES) return { state: "invalid", reason: "lock.json が大きすぎる" };
	const b = git(cwd, ["cat-file", "blob", m[1]], env);
	if (!b.ok) return { state: "unreadable", reason: "lock.json を読めない" };
	let v: unknown;
	try {
		v = JSON.parse(b.out);
	} catch {
		return { state: "invalid", reason: "lock.json が JSON でない" };
	}
	if (typeof v !== "object" || v === null || Array.isArray(v)) return { state: "invalid", reason: "lock.json がオブジェクトでない" };
	const o = v as Record<string, unknown>;
	const keys = Object.keys(o).sort().join(",");
	if (keys !== "at,attemptId,owner,runningId,schema") return { state: "invalid", reason: "lock.json のキーが想定と違う" };
	if (o.schema !== 1 || !validHolder(o) || typeof o.at !== "string" || o.at.length > 40 || Number.isNaN(Date.parse(o.at)) || !validateOwner(o.owner)) {
		return { state: "invalid", reason: "lock.json の内容が不正" };
	}
	return { state: "held", oid, holder: { runningId: o.runningId as string, attemptId: o.attemptId as string }, at: o.at, owner: o.owner };
}

// ---- 書き込みの部品 ----

function identityEnv(cwd: string, env: Env): Record<string, string> {
	if (git(cwd, ["var", "GIT_COMMITTER_IDENT"], env).ok && git(cwd, ["var", "GIT_AUTHOR_IDENT"], env).ok) return {};
	return { GIT_AUTHOR_NAME: "pi lock", GIT_AUTHOR_EMAIL: "pi-lock@localhost", GIT_COMMITTER_NAME: "pi lock", GIT_COMMITTER_EMAIL: "pi-lock@localhost" };
}

function makeLockCommit(cwd: string, content: string, env: Env): { ok: true; oid: string } | { ok: false; reason: string } {
	const blob = git(cwd, ["hash-object", "-w", "--stdin"], env, { input: content });
	if (!blob.ok || !OID_RE.test(blob.out)) return { ok: false, reason: "blob を書けなかった" };
	const tree = git(cwd, ["mktree"], env, { input: `100644 blob ${blob.out}\tlock.json\n` });
	if (!tree.ok || !OID_RE.test(tree.out)) return { ok: false, reason: "tree を書けなかった" };
	const c = git(cwd, ["commit-tree", tree.out, "-F", "-"], env, { input: "pi exclusive lock\n", extra: identityEnv(cwd, env) });
	if (!c.ok || !OID_RE.test(c.out)) return { ok: false, reason: "commit-tree に失敗した" };
	return { ok: true, oid: c.out };
}

/** 無いときだけ作る (旧値 = オブジェクト名のゼロ)。symbolic ref を辿らない */
function createRef(cwd: string, ref: string, oid: string, env: Env): Run {
	return git(cwd, ["update-ref", "--no-deref", ref, oid, "0".repeat(oid.length)], env);
}

function deleteIf(cwd: string, ref: string, oid: string, env: Env): Run {
	if (!OID_RE.test(oid)) return { ok: false, out: "", err: "OID の形が不正" };
	return git(cwd, ["update-ref", "--no-deref", "-d", ref, oid], env);
}

// ---- 取得・解放 ----

function heldFail(read: Extract<LockRead, { state: "held" }>, why: string): AcquireFail {
	return { ok: false, code: "held", reason: `${why} (保持者: ${read.holder.runningId} / ${read.holder.attemptId})`, holder: read.holder };
}

/** 読み取りの結果 (held 以外) を取得の失敗に写す。自動では消さない */
function nonHeldFail(read: Exclude<LockRead, { state: "held" | "missing" }>): AcquireFail {
	return read.state === "invalid"
		? { ok: false, code: "invalid_lock", reason: `ロックの ref が不正で、自動では消さない: ${read.reason}` }
		: { ok: false, code: "git_failed", reason: `ロックを読めない: ${read.reason}` };
}

function tryCreate(cwd: string, key: string, holder: Holder, env: Env): { ok: true; handle: LockHandle } | { ok: false; why: string } {
	const content = JSON.stringify({
		schema: 1,
		runningId: holder.runningId,
		attemptId: holder.attemptId,
		owner: currentOwner("lock", holder.attemptId),
		at: new Date().toISOString(),
	});
	const made = makeLockCommit(cwd, content, env);
	if (!made.ok) return { ok: false, why: made.reason };
	const ref = refOf(key);
	const c = createRef(cwd, ref, made.oid, env);
	return c.ok ? { ok: true, handle: { ref, oid: made.oid } } : { ok: false, why: c.err.split("\n").pop() || "update-ref に失敗した" };
}

/**
 * ロックを取る。held のときだけ probe で保持者を調べ、`attempt === "reserved" && owner === "gone"` のときだけ、観測した OID の CAS 削除 → 再取得。
 * それ以外 (started・absent・mismatch・unreadable・alive・unknown・不正・読み取り失敗) は消さずに失敗を返す。
 * 回復の CAS が競合したら、再取得は 1 回だけ (ロックが消えていたときだけ)。ほかは再読み取りの結果を返す。
 */
export function acquireLock(cwd: string, holder: Holder, deps: { probe: (h: Holder) => ProbeResult; env?: NodeJS.ProcessEnv }): AcquireResult {
	const env = deps.env;
	if (!validHolder(holder)) return { ok: false, code: "git_failed", reason: "holder の形が不正" };
	const k = lockKeyOf(cwd, env);
	if (!k.ok) return { ok: false, code: "git_failed", reason: k.reason };
	const read = readLock(cwd, k.key, env);
	if (read.state === "invalid" || read.state === "unreadable") return nonHeldFail(read);
	if (read.state === "missing") {
		const c = tryCreate(cwd, k.key, holder, env);
		if (c.ok) return { ok: true, handle: c.handle };
		// 競合 (先に別者が作った)。再読み取りの結果を返す
		const again = readLock(cwd, k.key, env);
		if (again.state === "held") return heldFail(again, "ロックは別の保持者が取っている");
		if (again.state === "invalid" || again.state === "unreadable") return nonHeldFail(again);
		return { ok: false, code: "git_failed", reason: `ロックを作れなかった: ${c.why}` };
	}
	// held: 保持者を検証する
	let p: ProbeResult;
	try {
		p = deps.probe(read.holder);
	} catch (e) {
		return { ok: false, code: "unverifiable", reason: `保持者の試行を検証できない (probe が失敗: ${String((e as Error)?.message ?? e).slice(0, 100)})`, holder: read.holder };
	}
	if (p.attempt === "absent" || p.attempt === "mismatch" || p.attempt === "unreadable") {
		return { ok: false, code: "unverifiable", reason: `保持者の試行を検証できない (${p.attempt})。人の復旧が要る`, holder: read.holder };
	}
	if (p.attempt === "started") {
		return p.owner === "gone"
			? { ok: false, code: "stale_started", reason: "保持者の試行は started で owner が止まっている。副作用が残りうるので自動では回復しない", holder: read.holder }
			: heldFail(read, "保持者の試行が started で、owner の停止を確認できない");
	}
	if (p.attempt !== "reserved" || p.owner !== "gone") return heldFail(read, `ロックは保持されている (owner: ${p.owner})`);
	// reserved × gone だけ回復する (観測した OID の CAS 削除)
	const del = deleteIf(cwd, refOf(k.key), read.oid, env);
	if (!del.ok) {
		const again = readLock(cwd, k.key, env);
		if (again.state === "held") return heldFail(again, "回復の競合で、別の者が先に動いた");
		if (again.state === "invalid" || again.state === "unreadable") return nonHeldFail(again);
		// 消えていたとき (先に消した者が、まだ作っていない): 1 回だけ作る
		const c = tryCreate(cwd, k.key, holder, env);
		if (c.ok) return { ok: true, handle: c.handle, recovered: "reserved_gone" };
		return { ok: false, code: "held", reason: `回復の競合で取得できなかった: ${c.why}` };
	}
	const c = tryCreate(cwd, k.key, holder, env);
	if (c.ok) return { ok: true, handle: c.handle, recovered: "reserved_gone" };
	const again = readLock(cwd, k.key, env);
	if (again.state === "held") return heldFail(again, "回復の直後に別の者が取った");
	return { ok: false, code: "git_failed", reason: `回復後にロックを作れなかった: ${c.why}` };
}

/** CAS 削除。他者のロック (OID が違う) は消さない */
export function releaseLock(cwd: string, handle: LockHandle, env?: NodeJS.ProcessEnv): { ok: true } | { ok: false; reason: string } {
	if (!handle.ref.startsWith(LOCK_PREFIX) || !KEY_RE.test(handle.ref.slice(LOCK_PREFIX.length))) return { ok: false, reason: "ref がロックの名前空間でない" };
	const r = deleteIf(cwd, handle.ref, handle.oid, env);
	return r.ok ? { ok: true } : { ok: false, reason: r.err.split("\n").pop() || "ロックが別の値になっている (または無い)" };
}

/** 人の復旧用: 期待 OID の CAS 削除 (不正な内容でも消せる)。symbolic ref は消さない。自動では呼ばない */
export function forceRelease(cwd: string, oid: string, env?: NodeJS.ProcessEnv): { ok: boolean; reason?: string } {
	const k = lockKeyOf(cwd, env);
	if (!k.ok) return { ok: false, reason: k.reason };
	const ref = refOf(k.key);
	const s = git(cwd, ["for-each-ref", "--format=%(symref)", ref], env);
	if (!s.ok) return { ok: false, reason: "ref を列挙できなかった" };
	if (s.out) return { ok: false, reason: "symbolic ref は消さない (手で確認する)" };
	const r = deleteIf(cwd, ref, oid, env);
	return r.ok ? { ok: true } : { ok: false, reason: r.err.split("\n").pop() || "期待した OID と違う (または無い)" };
}
