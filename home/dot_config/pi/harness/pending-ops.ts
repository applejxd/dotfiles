// 非同期承認の保存層 (CHG-0055 の P2)。承認が取れなかった構造化した操作を、記録として保存し、状態を遷移させる。
// 承認・実行・通知はここでは行わない (P4・P5)。ここは「記録を信頼しない入力として読む」「ref の遷移を原子的にする」だけを持つ。
//
//   refs/pi/pending/<id>  記録 (commit。tree は record.json だけ)。旧形式の退避 (pending-store.ts) も同じ名前空間にある
//   refs/pi/running/<id>  承認して実行中の試行 (commit。tree は attempt.json。親は記録、または前の試行)
//   refs/pi/done/<id>     結果 (commit。tree は result.json。親は最後の試行)
//   refs/pi/key/<digest>  重複の抑止の鍵 (記録の commit を指す。作成を原子的にする)
//
// ★承認なしに動くので、git の hook は無効にする。ref の遷移はすべて 1 回の `update-ref --stdin` のトランザクションで、
//   各コマンドの前に `option no-deref` を付け (symbolic ref を辿らない)、期待する OID を指定する。
// node の型除去でそのまま動く書き方だけを使う (enum・namespace は使わない)。
// see docs/change/0055-async-approval.md#設計の契約
import { spawnSync } from "node:child_process";
import { createHash, randomUUID } from "node:crypto";
import { PENDING_PREFIX, repoTargetEnv } from "./pending-store.ts";

export const NS = { pending: PENDING_PREFIX, running: "refs/pi/running/", done: "refs/pi/done/", key: "refs/pi/key/" } as const;

export type Limits = { maxPending: number; maxRecordBytes: number; maxScan: number };
export const DEFAULT_LIMITS: Limits = { maxPending: 50, maxRecordBytes: 64 * 1024, maxScan: 1000 };

export type Reason = "timeout" | "absent" | "no_ui" | "later";
export type Json = null | boolean | number | string | Json[] | { [k: string]: Json };

export type OpRecord = {
	schema: 1;
	/** 操作の ID (git_integrate など) */
	action: string;
	/** 型つきの引数 (すべて文字列) */
	params: Record<string, string>;
	/** 前提 (取得時の状態。承認の時点で再検査する) */
	premise: Record<string, Json>;
	reason: Reason;
	/** 表示用。権限の根拠にしない */
	request: { id: string; sessionId: string; cwd: string };
	createdAt: string;
	/** 対象が worktree に依存する操作の識別 (重複の抑止に含める) */
	worktree?: string;
	/** 接続先のホスト (gh など。重複の抑止に含める) */
	host?: string;
	/** この要求が置き換える前の要求の id */
	supersedes?: string;
	/** 検証用。検証済みの値から再計算した値と一致しなければ拒否する */
	digest: string;
};
export type SaveInput = Omit<OpRecord, "schema" | "digest">;

export type Owner = { sessionId: string; runtimeEpoch: string; pid: number; processStart: string | null; host: string };
export type Stage = "reserved" | "started";
export type Attempt = { schema: 1; attemptId: string; stage: Stage; owner: Owner; at: string };

export type Outcome = "not_executed" | "success" | "failed_confirmed" | "unknown";
export type ResultBody = {
	outcome: Outcome;
	/** どこまで進んだか */
	phase: string;
	/** 成立したと確認できた副作用 */
	confirmedEffects: string[];
	/** 残った後片付け */
	remainingCleanup: string[];
	/** 判断の材料 */
	evidence: string[];
};
export type ResultRecord = ResultBody & { schema: 1; attemptId: string; at: string; resolvedBy: "executor" | "human" };

export type Kind = "legacy" | "action" | "attempt" | "result" | "invalid";
export type State = "pending" | "running" | "done";
export type Entry = { state: State; id: string; ref: string; oid: string; /** trailer が名乗る種類 (検証前) */ kind: Kind; committedAt: number };

type Run = { ok: boolean; out: string; err: string };
type Fail = { ok: false; reason: string };

const SAFE = ["-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false", "-c", "core.quotepath=false", "-c", "commit.gpgsign=false"];
const ID_RE = /^\d{15}(-\d{2})?$/;
const DIGEST_RE = /^[0-9a-f]{64}$/;
const OID_RE = /^[0-9a-f]{40}([0-9a-f]{24})?$/;
const NAME_RE = /^[a-z][a-z0-9_]{0,40}$/;
const KIND_TRAILER = "Pi-Pending-Kind";
const ID_TRAILER = "Pi-Pending-Id";
const REQUEST_TRAILER = "Pi-Pending-Request";
const FILE_OF: Record<string, string> = { action: "record.json", attempt: "attempt.json", result: "result.json" };
const MAX_PARAM_CHARS = 20000;
const MAX_SMALL_BYTES = 16 * 1024;

function git(cwd: string, args: string[], opts: { env?: Record<string, string>; input?: string } = {}): Run {
	const r = spawnSync("git", [...SAFE, ...args], {
		cwd,
		encoding: "utf8",
		timeout: 15000,
		input: opts.input,
		env: { ...repoTargetEnv(), ...opts.env, GIT_OPTIONAL_LOCKS: "0", GIT_TERMINAL_PROMPT: "0" },
	});
	return { ok: r.status === 0, out: String(r.stdout ?? "").replace(/\n+$/, ""), err: String(r.stderr ?? "").trim() };
}

// ---- 検証 ----

/** キーの順序に依らない JSON (配列は順序を保つ)。digest の入力にする */
export function canonicalJson(v: Json): string {
	if (v === null || typeof v !== "object") return JSON.stringify(v);
	if (Array.isArray(v)) return `[${v.map(canonicalJson).join(",")}]`;
	return `{${Object.keys(v)
		.sort()
		.map((k) => `${JSON.stringify(k)}:${canonicalJson(v[k])}`)
		.join(",")}}`;
}

function isJson(v: unknown, depth = 0): v is Json {
	if (depth > 6) return false;
	if (v === null || typeof v === "boolean" || typeof v === "string") return typeof v !== "string" || !v.includes("\0");
	if (typeof v === "number") return Number.isFinite(v);
	if (Array.isArray(v)) return v.length <= 200 && v.every((x) => isJson(x, depth + 1));
	if (typeof v === "object") {
		const keys = Object.keys(v as object);
		return keys.length <= 100 && keys.every((k) => !k.includes("\0") && isJson((v as Record<string, unknown>)[k], depth + 1));
	}
	return false;
}

/** 重複の抑止の識別子 (版つき)。保存された値は信用せず、検証済みの値から再計算する。承認済みの証明でも、永久のリプレイ防止の鍵でもない */
export function computeDigest(r: Pick<OpRecord, "action" | "params" | "premise" | "worktree" | "host">): string {
	const body: Json = { action: r.action, params: r.params, premise: r.premise, worktree: r.worktree ?? null, host: r.host ?? null };
	return createHash("sha256").update(`pi-pending-digest-v1\0${canonicalJson(body)}`).digest("hex");
}

function isObj(v: unknown): v is Record<string, unknown> {
	return typeof v === "object" && v !== null && !Array.isArray(v);
}
function keysOk(o: Record<string, unknown>, required: string[], optional: string[] = []): boolean {
	const allowed = new Set([...required, ...optional]);
	return required.every((k) => k in o) && Object.keys(o).every((k) => allowed.has(k));
}
const str = (v: unknown, max = 500): v is string => typeof v === "string" && v.length <= max && !v.includes("\0");

export function validateOwner(v: unknown): v is Owner {
	return (
		isObj(v) &&
		keysOk(v, ["sessionId", "runtimeEpoch", "pid", "processStart", "host"]) &&
		str(v.sessionId, 200) &&
		str(v.runtimeEpoch, 200) &&
		Number.isInteger(v.pid) &&
		(v.processStart === null || str(v.processStart, 200)) &&
		str(v.host, 300)
	);
}

/** 記録の検証 (未知のキーは拒否)。digest も再計算して照合する */
export function validateRecord(v: unknown): { ok: true; rec: OpRecord } | Fail {
	if (!isObj(v)) return { ok: false, reason: "記録が JSON のオブジェクトでない" };
	if (!keysOk(v, ["schema", "action", "params", "premise", "reason", "request", "createdAt", "digest"], ["worktree", "host", "supersedes"])) {
		return { ok: false, reason: "記録のキーが想定と違う (未知のキー・不足)" };
	}
	if (v.schema !== 1) return { ok: false, reason: "記録の schema が未対応" };
	if (typeof v.action !== "string" || !NAME_RE.test(v.action)) return { ok: false, reason: "action の形が不正" };
	if (!isObj(v.params) || Object.keys(v.params).length > 20) return { ok: false, reason: "params が不正" };
	for (const [k, x] of Object.entries(v.params)) {
		if (!NAME_RE.test(k) || !str(x, MAX_PARAM_CHARS)) return { ok: false, reason: `params の ${k.slice(0, 40)} が不正 (文字列だけ。長さ・NUL)` };
	}
	if (!isObj(v.premise) || !isJson(v.premise)) return { ok: false, reason: "premise が不正 (JSON の値だけ。深さ・個数)" };
	if (!["timeout", "absent", "no_ui", "later"].includes(String(v.reason))) return { ok: false, reason: "reason が不正" };
	const q = v.request;
	if (!isObj(q) || !keysOk(q, ["id", "sessionId", "cwd"]) || !str(q.id, 100) || !str(q.sessionId, 200) || !str(q.cwd, 1000)) {
		return { ok: false, reason: "request が不正" };
	}
	if (!str(v.createdAt, 40) || Number.isNaN(Date.parse(v.createdAt))) return { ok: false, reason: "createdAt が不正" };
	for (const k of ["worktree", "host"] as const) if (k in v && !str(v[k], 1000)) return { ok: false, reason: `${k} が不正` };
	if ("supersedes" in v && !(typeof v.supersedes === "string" && ID_RE.test(v.supersedes))) return { ok: false, reason: "supersedes が不正" };
	if (typeof v.digest !== "string" || !DIGEST_RE.test(v.digest)) return { ok: false, reason: "digest の形が不正" };
	const rec = v as unknown as OpRecord;
	if (computeDigest(rec) !== rec.digest) return { ok: false, reason: "digest が、記録の内容から再計算した値と違う (改ざん・版違い)" };
	return { ok: true, rec };
}

function validateAttempt(v: unknown): v is Attempt {
	return (
		isObj(v) &&
		keysOk(v, ["schema", "attemptId", "stage", "owner", "at"]) &&
		v.schema === 1 &&
		str(v.attemptId, 100) &&
		(v.stage === "reserved" || v.stage === "started") &&
		validateOwner(v.owner) &&
		str(v.at, 40)
	);
}

const listOk = (v: unknown): v is string[] => Array.isArray(v) && v.length <= 50 && v.every((x) => str(x, 500));
export function validateResultBody(v: unknown): v is ResultBody {
	return (
		isObj(v) &&
		["not_executed", "success", "failed_confirmed", "unknown"].includes(String(v.outcome)) &&
		str(v.phase, 100) &&
		listOk(v.confirmedEffects) &&
		listOk(v.remainingCleanup) &&
		listOk(v.evidence)
	);
}
function validateResult(v: unknown): v is ResultRecord {
	return (
		isObj(v) &&
		keysOk(v, ["schema", "attemptId", "at", "resolvedBy", "outcome", "phase", "confirmedEffects", "remainingCleanup", "evidence"]) &&
		v.schema === 1 &&
		str(v.attemptId, 100) &&
		str(v.at, 40) &&
		(v.resolvedBy === "executor" || v.resolvedBy === "human") &&
		validateResultBody(v)
	);
}

// ---- 読み出し (commit の構造と trailer) ----

type Commit = { oid: string; parents: string[]; message: string; tree: string };

function readCommit(cwd: string, oid: string): Commit | null {
	if (!OID_RE.test(oid)) return null;
	const r = git(cwd, ["cat-file", "commit", oid]);
	if (!r.ok) return null;
	const sep = r.out.indexOf("\n\n");
	const head = (sep < 0 ? r.out : r.out.slice(0, sep)).split("\n");
	const message = sep < 0 ? "" : r.out.slice(sep + 2);
	const tree = /^tree ([0-9a-f]+)$/.exec(head[0] ?? "")?.[1];
	if (!tree) return null;
	return { oid, parents: head.filter((l) => l.startsWith("parent ")).map((l) => l.slice(7)), message, tree };
}

export function trailerOf(message: string, key: string): string {
	const m = new RegExp(`^${key}: (.*)$`, "m").exec(message);
	return m ? m[1].trim() : "";
}

/** tree が、ちょうど 1 つの通常ファイル (name) だけか。その blob の OID と大きさ (バイト) を返す */
function singleFile(cwd: string, tree: string, name: string): { blob: string; size: number } | null {
	const r = git(cwd, ["ls-tree", "-l", "-z", tree]);
	if (!r.ok) return null;
	const rows = r.out.split("\0").filter((x) => x !== "");
	if (rows.length !== 1) return null;
	const m = /^100644 blob ([0-9a-f]+)\s+(\d+)\t(.*)$/.exec(rows[0]);
	return m && m[3] === name ? { blob: m[1], size: Number(m[2]) } : null;
}

/** commit の種類。Pi-Pending-Kind を名乗るものは、構造も合うときだけその種類。構造が合わなければ invalid (旧形式へ戻さない) */
export function classifyCommit(cwd: string, oid: string): Kind {
	const c = readCommit(cwd, oid);
	if (!c) return "invalid";
	const claimed = trailerOf(c.message, KIND_TRAILER);
	if (claimed !== "") {
		const file = FILE_OF[claimed];
		return file && singleFile(cwd, c.tree, file) ? (claimed as Kind) : "invalid";
	}
	// 名乗りが無い。旧形式の退避は、任意の tree を持つので、新形式のファイル 1 つだけの tree は旧形式として扱わない
	for (const f of Object.values(FILE_OF)) if (singleFile(cwd, c.tree, f)) return "invalid";
	return "legacy";
}

function readJsonBlob(cwd: string, tree: string, name: string, maxBytes: number): { ok: true; value: unknown } | Fail {
	const f = singleFile(cwd, tree, name);
	if (!f) return { ok: false, reason: `tree が ${name} だけの形でない` };
	if (f.size > maxBytes) return { ok: false, reason: `${name} が大きすぎる (${f.size} バイト)` };
	const b = git(cwd, ["cat-file", "blob", f.blob]);
	if (!b.ok) return { ok: false, reason: `${name} を読めない` };
	try {
		return { ok: true, value: JSON.parse(b.out) };
	} catch {
		return { ok: false, reason: `${name} が JSON でない` };
	}
}

export type ReadOp = { ok: true; id: string; oid: string; record: OpRecord } | Fail;

/** 記録の commit を、信頼しない入力として読む (trailer・tree の形・大きさ・schema・digest・id の整合) */
export function readOpAt(cwd: string, id: string, oid: string, limits: Limits = DEFAULT_LIMITS): ReadOp {
	if (!ID_RE.test(id)) return { ok: false, reason: "id の形が不正" };
	const c = readCommit(cwd, oid);
	if (!c) return { ok: false, reason: "commit を読めない" };
	if (trailerOf(c.message, KIND_TRAILER) !== "action") return { ok: false, reason: "種類が action でない" };
	if (trailerOf(c.message, ID_TRAILER) !== id) return { ok: false, reason: "trailer の id が、ref の id と違う" };
	const j = readJsonBlob(cwd, c.tree, FILE_OF.action, limits.maxRecordBytes);
	if (!j.ok) return j;
	const v = validateRecord(j.value);
	if (!v.ok) return v;
	if (trailerOf(c.message, REQUEST_TRAILER) !== v.rec.request.id) return { ok: false, reason: "trailer の要求 ID が、記録と違う" };
	return { ok: true, id, oid, record: v.rec };
}

function refOid(cwd: string, ref: string): string | null {
	const sym = git(cwd, ["symbolic-ref", "-q", ref]);
	if (sym.ok) return null; // symbolic ref は扱わない
	const r = git(cwd, ["rev-parse", "-q", "--verify", `${ref}^{commit}`]);
	return r.ok && OID_RE.test(r.out) ? r.out : null;
}

/** pending の記録を ref から読む */
export function readOp(cwd: string, id: string, limits: Limits = DEFAULT_LIMITS): ReadOp {
	if (!ID_RE.test(id)) return { ok: false, reason: "id の形が不正" };
	const oid = refOid(cwd, NS.pending + id);
	if (!oid) return { ok: false, reason: "pending の ref が無い (または symbolic ref)" };
	return readOpAt(cwd, id, oid, limits);
}

type AttemptAt = { ok: true; attempt: Attempt; parent: string } | Fail;
function readAttemptAt(cwd: string, id: string, oid: string): AttemptAt {
	const c = readCommit(cwd, oid);
	if (!c || c.parents.length !== 1) return { ok: false, reason: "試行の commit を読めない" };
	if (trailerOf(c.message, KIND_TRAILER) !== "attempt" || trailerOf(c.message, ID_TRAILER) !== id) return { ok: false, reason: "試行の commit の種類・id が違う" };
	const j = readJsonBlob(cwd, c.tree, FILE_OF.attempt, MAX_SMALL_BYTES);
	if (!j.ok) return j;
	if (!validateAttempt(j.value)) return { ok: false, reason: "attempt.json が不正" };
	return { ok: true, attempt: j.value, parent: c.parents[0] };
}

/** 試行の鎖 (started → reserved → 記録) をたどって、記録の commit の OID を返す */
function recordOidOf(cwd: string, id: string, attemptOid: string): { ok: true; oid: string; attempt: Attempt } | Fail {
	const a = readAttemptAt(cwd, id, attemptOid);
	if (!a.ok) return a;
	let parent = a.parent;
	if (a.attempt.stage === "started") {
		const prev = readAttemptAt(cwd, id, parent);
		if (!prev.ok || prev.attempt.stage !== "reserved" || prev.attempt.attemptId !== a.attempt.attemptId) return { ok: false, reason: "試行の鎖が不正" };
		parent = prev.parent;
	}
	return { ok: true, oid: parent, attempt: a.attempt };
}

export type ReadResult = { ok: true; result: ResultRecord; parent: string } | Fail;
export function readResultAt(cwd: string, id: string, oid: string): ReadResult {
	const c = readCommit(cwd, oid);
	if (!c || c.parents.length !== 1) return { ok: false, reason: "結果の commit を読めない" };
	if (trailerOf(c.message, KIND_TRAILER) !== "result" || trailerOf(c.message, ID_TRAILER) !== id) return { ok: false, reason: "結果の commit の種類・id が違う" };
	const j = readJsonBlob(cwd, c.tree, FILE_OF.result, MAX_SMALL_BYTES);
	if (!j.ok) return j;
	if (!validateResult(j.value)) return { ok: false, reason: "result.json が不正" };
	return { ok: true, result: j.value, parent: c.parents[0] };
}

// ---- 書き込みの部品 ----

function identityEnv(cwd: string): Record<string, string> {
	if (git(cwd, ["var", "GIT_COMMITTER_IDENT"]).ok && git(cwd, ["var", "GIT_AUTHOR_IDENT"]).ok) return {};
	return { GIT_AUTHOR_NAME: "pi pending", GIT_AUTHOR_EMAIL: "pi-pending@localhost", GIT_COMMITTER_NAME: "pi pending", GIT_COMMITTER_EMAIL: "pi-pending@localhost" };
}

/** ファイル 1 つだけの tree の commit を作る (ref は動かさない。hook は動かさない) */
function makeCommit(cwd: string, fileName: string, content: string, parent: string | null, message: string): { ok: true; oid: string } | Fail {
	const blob = git(cwd, ["hash-object", "-w", "--stdin"], { input: content });
	if (!blob.ok || !OID_RE.test(blob.out)) return { ok: false, reason: "blob を書けなかった" };
	const tree = git(cwd, ["mktree"], { input: `100644 blob ${blob.out}\t${fileName}\n` });
	if (!tree.ok || !OID_RE.test(tree.out)) return { ok: false, reason: "tree を書けなかった" };
	const c = git(cwd, ["commit-tree", tree.out, ...(parent ? ["-p", parent] : []), "-F", "-"], { input: message, env: identityEnv(cwd) });
	if (!c.ok || !OID_RE.test(c.out)) return { ok: false, reason: "commit-tree に失敗した" };
	return { ok: true, oid: c.out };
}

/** 1 回のトランザクションで ref を動かす。各コマンドの前に `option no-deref` を付ける (option は次の 1 コマンドだけに効く) */
function transact(cwd: string, cmds: string[]): { ok: true } | Fail {
	const body = ["start", ...cmds.flatMap((c) => ["option no-deref", c]), "prepare", "commit"].join("\n") + "\n";
	const r = git(cwd, ["update-ref", "--stdin"], { input: body });
	return r.ok ? { ok: true } : { ok: false, reason: r.err.split("\n").pop() || "update-ref に失敗した" };
}

function nowIso(now?: number): string {
	return new Date(now ?? Date.now()).toISOString();
}

// ---- 一覧 ----

/** 3 つの名前空間の ref を 1 回で数える。種類は trailer の名乗り (検証前)。symbolic ref は除く。上限を超えたら truncated */
export function listOps(cwd: string, limits: Limits = DEFAULT_LIMITS): { entries: Entry[]; truncated: boolean } {
	const fmt = "%(refname)%00%(objectname)%00%(symref)%00%(committerdate:unix)%00%(contents:trailers:key=Pi-Pending-Kind,valueonly)";
	const r = git(cwd, ["for-each-ref", `--count=${limits.maxScan + 1}`, "--sort=-refname", `--format=${fmt}`, NS.pending, NS.running, NS.done]);
	if (!r.ok || !r.out) return { entries: [], truncated: false };
	const lines = r.out.split("\n").filter((l) => l.includes("\0"));
	const entries: Entry[] = [];
	for (const line of lines.slice(0, limits.maxScan)) {
		const [ref, oid, symref, ts, trailer] = line.split("\0");
		if (symref) continue;
		const state: State | null = ref.startsWith(NS.pending) ? "pending" : ref.startsWith(NS.running) ? "running" : ref.startsWith(NS.done) ? "done" : null;
		if (!state) continue;
		const id = ref.slice(NS[state].length);
		const t = (trailer ?? "").trim();
		const kind: Kind = t === "" ? "legacy" : t === "action" || t === "attempt" || t === "result" ? t : "invalid";
		entries.push({ state, id, ref, oid, kind, committedAt: Number(ts) || 0 });
	}
	return { entries, truncated: lines.length > limits.maxScan };
}

/** 保留中の新形式の記録の数 (running も含めた「承認待ち + 実行中」ではなく、pending の action だけ) */
export function countPending(cwd: string, limits: Limits = DEFAULT_LIMITS): number {
	return listOps(cwd, limits).entries.filter((e) => e.state === "pending" && e.kind === "action").length;
}

// ---- 保存と重複の抑止 ----

export type SaveResult =
	| { ok: true; id: string; ref: string; oid: string; duplicate: boolean }
	| { ok: false; code: "invalid" | "limit" | "git_failed"; reason: string };

type Active = { id: string; ref: string } | null;

/** 鍵の指す記録が、まだ決着していないか (pending・running・未解決の unknown)。決着済みなら null (鍵は古い) */
function activeOf(cwd: string, recordOid: string): { active: Active; id: string } {
	const c = readCommit(cwd, recordOid);
	const id = c ? trailerOf(c.message, ID_TRAILER) : "";
	if (!ID_RE.test(id)) return { active: null, id: "" };
	if (refOid(cwd, NS.pending + id) === recordOid) return { active: { id, ref: NS.pending + id }, id };
	if (refOid(cwd, NS.running + id)) return { active: { id, ref: NS.running + id }, id };
	const done = refOid(cwd, NS.done + id);
	if (done) {
		const r = readResultAt(cwd, id, done);
		if (r.ok && r.result.outcome === "unknown" && r.result.resolvedBy === "executor") return { active: { id, ref: NS.done + id }, id };
	}
	return { active: null, id };
}

/** 記録を保存する。同じ digest の未決着の要求があれば、新しく作らず既存を返す (duplicate)。作成は 1 回のトランザクション (記録の ref と鍵) */
export function saveOp(cwd: string, input: SaveInput, limits: Limits = DEFAULT_LIMITS, now?: number): SaveResult {
	const base: Omit<OpRecord, "digest"> = { schema: 1, ...input };
	const rec: OpRecord = { ...base, digest: computeDigest(base) };
	const v = validateRecord(JSON.parse(JSON.stringify(rec)));
	if (!v.ok) return { ok: false, code: "invalid", reason: v.reason };
	const bytes = Buffer.byteLength(canonicalJson(v.rec as unknown as Json));
	if (bytes > limits.maxRecordBytes) return { ok: false, code: "invalid", reason: `記録が大きすぎる (${bytes} バイト)` };

	const listed = listOps(cwd, limits);
	if (listed.truncated) return { ok: false, code: "limit", reason: "保留の ref が多すぎて数えきれない (上限を超えた)" };
	const live = listed.entries.filter((e) => e.kind === "action" && (e.state === "pending" || e.state === "running")).length;
	const keyRef = NS.key + v.rec.digest;
	for (let n = 0; n < 25; n++) {
		const keyOid = refOid(cwd, keyRef);
		let supersedes = v.rec.supersedes;
		if (keyOid) {
			const a = activeOf(cwd, keyOid);
			if (a.active) {
				const ref = a.active.ref;
				return { ok: true, id: a.active.id, ref, oid: refOid(cwd, ref) ?? keyOid, duplicate: true };
			}
			if (!supersedes && ID_RE.test(a.id)) supersedes = a.id;
		}
		if (live >= limits.maxPending) return { ok: false, code: "limit", reason: `保留が上限 (${limits.maxPending} 件) に達している` };
		const stamp = String(now ?? Date.now()).padStart(15, "0");
		const id = n === 0 ? stamp : `${stamp}-${String(n).padStart(2, "0")}`;
		const finalBase: Omit<OpRecord, "digest"> = { ...base, ...(supersedes ? { supersedes } : {}) };
		const finalRec: OpRecord = { ...finalBase, digest: computeDigest(finalBase) };
		const text = JSON.stringify(finalRec);
		const msg = `pi pending: ${finalRec.action}\n\n${KIND_TRAILER}: action\n${ID_TRAILER}: ${id}\n${REQUEST_TRAILER}: ${finalRec.request.id}\n`;
		const made = makeCommit(cwd, FILE_OF.action, text, null, msg);
		if (!made.ok) return { ok: false, code: "git_failed", reason: made.reason };
		const keyCmd = keyOid ? `update ${keyRef} ${made.oid} ${keyOid}` : `create ${keyRef} ${made.oid}`;
		const t = transact(cwd, [`create ${NS.pending}${id} ${made.oid}`, keyCmd]);
		if (t.ok) return { ok: true, id, ref: NS.pending + id, oid: made.oid, duplicate: false };
		// id の衝突、または鍵の競合。ID を変えて、鍵を読み直してやり直す
	}
	return { ok: false, code: "git_failed", reason: "ref を作れなかった (競合が続いた)" };
}

// ---- 承認の遷移 ----

export type Transition<T = Record<string, never>> = ({ ok: true } & T) | { ok: false; code: "mismatch" | "invalid" | "git_failed" | "refused"; reason: string };

/** pending → running(reserved)。表示した記録の OID が、今の pending の OID と同じときだけ (CAS)。running を作れなければ (既にある) 失敗する */
export function beginApproval(cwd: string, id: string, shownOid: string, owner: Owner, limits: Limits = DEFAULT_LIMITS, now?: number): Transition<{ attempt: Attempt; attemptOid: string }> {
	if (!ID_RE.test(id) || !OID_RE.test(shownOid)) return { ok: false, code: "invalid", reason: "id・OID の形が不正" };
	if (!validateOwner(owner)) return { ok: false, code: "invalid", reason: "owner が不正" };
	const rec = readOpAt(cwd, id, shownOid, limits);
	if (!rec.ok) return { ok: false, code: "invalid", reason: rec.reason };
	const attempt: Attempt = { schema: 1, attemptId: randomUUID(), stage: "reserved", owner, at: nowIso(now) };
	const msg = `pi pending attempt: ${rec.record.action}\n\n${KIND_TRAILER}: attempt\n${ID_TRAILER}: ${id}\n`;
	const made = makeCommit(cwd, FILE_OF.attempt, JSON.stringify(attempt), shownOid, msg);
	if (!made.ok) return { ok: false, code: "git_failed", reason: made.reason };
	const t = transact(cwd, [`create ${NS.running}${id} ${made.oid}`, `delete ${NS.pending}${id} ${shownOid}`]);
	if (!t.ok) return { ok: false, code: "mismatch", reason: `承認を始められなかった (表示した後に変わった、または既に実行中): ${t.reason}` };
	return { ok: true, attempt, attemptOid: made.oid };
}

/** reserved → started。副作用を始める意図を永続化する。**これに成功するまで、副作用のあるプロセスを起動しない** */
export function markStarted(cwd: string, id: string, reservedOid: string, now?: number): Transition<{ attempt: Attempt; attemptOid: string }> {
	const a = readAttemptAt(cwd, id, reservedOid);
	if (!a.ok) return { ok: false, code: "invalid", reason: a.reason };
	if (a.attempt.stage !== "reserved") return { ok: false, code: "refused", reason: "予約の段階でない" };
	const next: Attempt = { ...a.attempt, stage: "started", at: nowIso(now) };
	const msg = `pi pending attempt: started\n\n${KIND_TRAILER}: attempt\n${ID_TRAILER}: ${id}\n`;
	const made = makeCommit(cwd, FILE_OF.attempt, JSON.stringify(next), reservedOid, msg);
	if (!made.ok) return { ok: false, code: "git_failed", reason: made.reason };
	const t = transact(cwd, [`update ${NS.running}${id} ${made.oid} ${reservedOid}`]);
	if (!t.ok) return { ok: false, code: "mismatch", reason: `開始を記録できなかった: ${t.reason}` };
	return { ok: true, attempt: next, attemptOid: made.oid };
}

/** reserved → pending (未実行のまま戻す)。開始の前だけ */
export function returnToPending(cwd: string, id: string, reservedOid: string): Transition {
	const a = recordOidOf(cwd, id, reservedOid);
	if (!a.ok) return { ok: false, code: "invalid", reason: a.reason };
	if (a.attempt.stage !== "reserved") return { ok: false, code: "refused", reason: "開始した試行は、未実行として戻せない (結果を記録する)" };
	const t = transact(cwd, [`create ${NS.pending}${id} ${a.oid}`, `delete ${NS.running}${id} ${reservedOid}`]);
	return t.ok ? { ok: true } : { ok: false, code: "mismatch", reason: `pending へ戻せなかった: ${t.reason}` };
}

function finishWith(cwd: string, id: string, attemptOid: string, body: ResultBody, by: "executor" | "human", previousDone?: string): Transition<{ doneOid: string }> {
	if (!validateResultBody(body)) return { ok: false, code: "invalid", reason: "結果の形が不正" };
	const root = recordOidOf(cwd, id, attemptOid);
	if (!root.ok) return { ok: false, code: "invalid", reason: root.reason };
	const rec = readOpAt(cwd, id, root.oid);
	const res: ResultRecord = { schema: 1, attemptId: root.attempt.attemptId, at: nowIso(), resolvedBy: by, ...body };
	const msg = `pi pending result: ${body.outcome}\n\n${KIND_TRAILER}: result\n${ID_TRAILER}: ${id}\n`;
	const made = makeCommit(cwd, FILE_OF.result, JSON.stringify(res), attemptOid, msg);
	if (!made.ok) return { ok: false, code: "git_failed", reason: made.reason };
	// 決着したら鍵を外す (executor の unknown は、人が resolve するまで鍵を残して、同じ要求を作らせない)
	const keyRef = rec.ok ? NS.key + rec.record.digest : "";
	const keyOid = keyRef ? refOid(cwd, keyRef) : null;
	const dropKey = keyOid !== null && keyOid === root.oid && !(body.outcome === "unknown" && by === "executor");
	const cmds = [previousDone ? `update ${NS.done}${id} ${made.oid} ${previousDone}` : `create ${NS.done}${id} ${made.oid}`];
	if (!previousDone) cmds.push(`delete ${NS.running}${id} ${attemptOid}`);
	if (dropKey) cmds.push(`delete ${keyRef} ${keyOid}`);
	let t = transact(cwd, cmds);
	if (!t.ok && dropKey) t = transact(cwd, cmds.slice(0, -1)); // 鍵だけが競合したなら、鍵を残して結果を記録する
	return t.ok ? { ok: true, doneOid: made.oid } : { ok: false, code: "mismatch", reason: `結果を記録できなかった: ${t.reason}` };
}

/** running → done。実行器が、結果を記録する (4 値)。結果の保存に失敗したら、呼び出し側は running を残して失敗を表示する */
export function finishApproval(cwd: string, id: string, attemptOid: string, body: ResultBody): Transition<{ doneOid: string }> {
	return finishWith(cwd, id, attemptOid, body, "executor");
}

export type Liveness = (owner: Owner) => { state: "alive" | "gone" | "unknown"; reason: string };
export type Decision = { kind: "pending" } | { kind: "abandon" } | { kind: "success" | "failed" | "retry"; evidence?: string[] };
export type ResolveContext = { liveness: Liveness; userConfirmedStopped?: boolean };

/** 実行中かもしれない試行 (running) を、人が決着させる。実行者が生きているかもしれないときは拒否する */
export function resolveRunning(cwd: string, id: string, attemptOid: string, decision: Decision, ctx: ResolveContext, limits: Limits = DEFAULT_LIMITS): Transition<{ newId?: string }> {
	if (refOid(cwd, NS.running + id) !== attemptOid) return { ok: false, code: "mismatch", reason: "その試行は、今の running と違う (もう決着した、または別の試行)" };
	const root = recordOidOf(cwd, id, attemptOid);
	if (!root.ok) return { ok: false, code: "invalid", reason: root.reason };
	const live = ctx.liveness(root.attempt.owner);
	if (live.state === "alive") return { ok: false, code: "refused", reason: `実行者が生きている (${live.reason})。終わるのを待つ` };
	if (live.state === "unknown" && ctx.userConfirmedStopped !== true) {
		return { ok: false, code: "refused", reason: `実行者が止まったか確認できない (${live.reason})。止まっていると確かめて、明示して承認する` };
	}
	const proof = live.state === "gone" ? `実行者は止まっている (${live.reason})` : `利用者が、実行者は止まっていると明示した (${live.reason})`;
	if (decision.kind === "pending") return returnToPending(cwd, id, attemptOid);
	const body = (outcome: Outcome, phase: string, evidence: string[]): ResultBody => ({ outcome, phase, confirmedEffects: [], remainingCleanup: [], evidence: [proof, ...evidence].slice(0, 50) });
	if (root.attempt.stage === "reserved") {
		if (decision.kind !== "abandon") return { ok: false, code: "refused", reason: "開始前の試行は、pending へ戻すか、放棄するだけ" };
		const r = finishWith(cwd, id, attemptOid, body("not_executed", "reserved", []), "human");
		return r.ok ? { ok: true } : r;
	}
	if (decision.kind === "abandon" || decision.kind === "pending") return { ok: false, code: "refused", reason: "開始した試行は、結果 (success・failed・retry) で決着させる" };
	const evidence = decision.evidence ?? [];
	if (decision.kind === "retry") {
		const rec = readOpAt(cwd, id, root.oid, limits);
		if (!rec.ok) return { ok: false, code: "invalid", reason: rec.reason };
		const r = finishWith(cwd, id, attemptOid, body("unknown", "started", [...evidence, "retry: 新しい要求を作って再承認させる"]), "human");
		if (!r.ok) return r;
		const { schema: _s, digest: _d, ...input } = rec.record;
		const saved = saveOp(cwd, { ...input, supersedes: id, createdAt: nowIso() }, limits);
		return saved.ok ? { ok: true, newId: saved.id } : { ok: false, code: "git_failed", reason: `古い試行は決着したが、新しい要求を作れなかった: ${saved.reason}` };
	}
	const r = finishWith(cwd, id, attemptOid, body(decision.kind === "success" ? "success" : "failed_confirmed", "started", evidence), "human");
	return r.ok ? { ok: true } : r;
}

/** 実行器が記録した unknown (未解決) を、人が決着させる (結果を上書きして、鍵を外す) */
export function resolveUnknown(cwd: string, id: string, decision: { kind: "success" | "failed"; evidence?: string[] }): Transition {
	const doneOid = refOid(cwd, NS.done + id);
	if (!doneOid) return { ok: false, code: "invalid", reason: "done の ref が無い" };
	const r = readResultAt(cwd, id, doneOid);
	if (!r.ok) return { ok: false, code: "invalid", reason: r.reason };
	if (r.result.outcome !== "unknown" || r.result.resolvedBy !== "executor") return { ok: false, code: "refused", reason: "未解決の unknown ではない" };
	const body: ResultBody = {
		outcome: decision.kind === "success" ? "success" : "failed_confirmed",
		phase: r.result.phase,
		confirmedEffects: r.result.confirmedEffects,
		remainingCleanup: r.result.remainingCleanup,
		evidence: [...r.result.evidence, ...(decision.evidence ?? []), "人が決着させた"].slice(0, 50),
	};
	const out = finishWith(cwd, id, r.parent, body, "human", doneOid);
	return out.ok ? { ok: true } : out;
}

// ---- 期限 ----

/** 期限切れの新形式の記録・結果と、古い鍵を消す (CAS)。running は消さない。旧形式 (legacy) と不正な形式には触れない。消した ref を返す */
export function reconcileOps(cwd: string, cfg: { retentionDays: number; resultRetentionDays: number; now?: number }, limits: Limits = DEFAULT_LIMITS): string[] {
	const now = (cfg.now ?? Date.now()) / 1000;
	const out: string[] = [];
	const { entries } = listOps(cwd, limits);
	for (const e of entries) {
		const age = (now - e.committedAt) / 86400;
		if (e.state === "pending" && e.kind === "action" && age > cfg.retentionDays) {
			if (classifyCommit(cwd, e.oid) !== "action") continue;
			const rec = readOpAt(cwd, e.id, e.oid, limits);
			const keyOid = rec.ok ? refOid(cwd, NS.key + rec.record.digest) : null;
			const cmds = [`delete ${e.ref} ${e.oid}`];
			if (rec.ok && keyOid === e.oid) cmds.push(`delete ${NS.key}${rec.record.digest} ${keyOid}`);
			if (transact(cwd, cmds).ok) out.push(e.ref);
		} else if (e.state === "done" && e.kind === "result" && age > cfg.resultRetentionDays) {
			if (transact(cwd, [`delete ${e.ref} ${e.oid}`]).ok) out.push(e.ref);
		}
	}
	// 孤児の鍵 (指す記録が決着済み・消えている)
	const keys = git(cwd, ["for-each-ref", `--count=${limits.maxScan}`, "--format=%(refname)%00%(objectname)%00%(symref)", NS.key]);
	if (keys.ok && keys.out) {
		for (const line of keys.out.split("\n")) {
			const [ref, oid, symref] = line.split("\0");
			if (symref || !oid) continue;
			if (!activeOf(cwd, oid).active && transact(cwd, [`delete ${ref} ${oid}`]).ok) out.push(ref);
		}
	}
	return out;
}
