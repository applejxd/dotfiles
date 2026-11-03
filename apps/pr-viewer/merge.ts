// PR ビューアの統合器。人の承認の後に、feature の枝を develop へ merge commit で統合する。
// 設計: docs/change/0062-pr-hub-simplify.md §3.2・§3.3・§3.4.1、実験: docs/research/agents/pr-merge-spike.md の X1。
// 安全の条件 S1〜S10 は test/agents/test_pr_viewer_merge.py が固定する。この段では HTTP・画面につなげない。
import { randomUUID } from "node:crypto";
import {
	existsSync,
	linkSync,
	readFileSync,
	renameSync,
	unlinkSync,
	writeFileSync,
} from "node:fs";
import { join } from "node:path";
import {
	type Identity,
	type StatusEntry,
	configHasExternalCode,
	listWorktrees,
	parseStatus,
	readIdentity,
	resolveCommonDir,
	runGit,
} from "./merge-git.ts";

export type Cleanup = "none" | "branch" | "branch_and_worktree";
export type MergeInput = {
	repo: string;
	source: string;
	target?: string;
	message: string;
	cleanup?: Cleanup;
	expect?: { sourceOid?: string; targetOid?: string };
};
export type Policy = { sources: string[]; targets: string[] };
export type Refusal = { ok: false; code: string; reason: string; conflicts?: string[]; details?: Record<string, unknown> };
export type FileChange = { status: string; path: string };
export type Plan = {
	source: { ref: string; oid: string };
	target: { ref: string; oid: string };
	mergeBase: string | null;
	resultTree: string;
	alreadyMerged: false;
	files: FileChange[]; // 最大 200 件
	fileCount: number;
	touched: string[];
	conflicts: string[];
};
export type MergeResult = {
	commit: string;
	targetOld: string;
	targetNew: string;
	cleanup: { requested: Cleanup; done: string[] };
	warnings: string[];
};
/** 試験用の差し込み口。afterPlan は計画と最終の検査の間、beforeAdvance は状態ファイルを書いた後・ff の前に呼ばれる（競合の再現に使う）。 */
export type Deps = { afterPlan?: () => Promise<void> | void; beforeAdvance?: () => Promise<void> | void; beforeCleanup?: () => Promise<void> | void };

export const DEFAULT_POLICY: Policy = { sources: ["feature/", "bugfix/"], targets: ["develop"] };

const REASONS: Record<string, string> = {
	bad_input: "入力が正しくありません。",
	policy_source: "統合元の枝は許可されていません。",
	policy_target: "統合先の枝は許可されていません。",
	no_source: "統合元の枝が見つかりません。",
	no_target: "統合先の枝が見つかりません。",
	already_merged: "すでに統合済みです。",
	conflict: "統合先と衝突しています。",
	stale: "画面が古くなっています。開き直してください。",
	head_mismatch: "統合先の作業ツリーが別の枝を指しています。",
	dirty: "統合が触るファイルに未コミットの変更があります。",
	ignored: "統合が作るファイルと同名の無視ファイルがあります。",
	external_code: "外部のコードを動かしうる設定があるため、統合しません。",
	busy: "別の統合が実行中です。",
	recover_needed: "前回の統合が異常終了した可能性があります。他の git が動いていないことを確かめて、復旧（recover）を実行してください。",
	not_ff: "統合先が先に進んでいます。",
	failed: "統合に失敗しました。",
	unverified: "統合の結果を確認できませんでした。統合先の履歴を確かめ、必要なら復旧（recover）を実行してください。",
	no_identity: "コミットの作者（user.name・user.email）が設定されていません。",
};

function refuse(code: string, reason?: string): Refusal {
	return { ok: false, code, reason: reason ?? REASONS[code] ?? REASONS.failed };
}

const OID_RE = /^(?:[0-9a-f]{40}|[0-9a-f]{64})$/;
const CLEANUPS: readonly string[] = ["none", "branch", "branch_and_worktree"];
const LOCK_NAME = "pr-viewer-merge.lock";
const STATE_NAME = "pr-viewer-merge.state";

// ---- 入力の検査 ----

/** 枝の短い名前（refs/heads/ の後）の形。 */
function validShortRef(s: string): boolean {
	if (!/^[A-Za-z0-9._/-]+$/.test(s)) return false;
	if (s.startsWith("-") || s.startsWith("/") || s.endsWith("/") || s.endsWith(".")) return false;
	if (s.includes("..") || s.includes("//")) return false;
	return s.split("/").every((c) => c !== "" && !c.startsWith(".") && !c.endsWith(".lock"));
}

/** "feature/x" または "refs/heads/feature/x" を短い名前にする。形が悪ければ null。 */
function shortRefOf(s: unknown): string | null {
	if (typeof s !== "string" || s.length === 0 || s.length > 200) return null;
	let short = s;
	if (s.startsWith("refs/")) {
		if (!s.startsWith("refs/heads/")) return null;
		short = s.slice("refs/heads/".length);
	}
	return validShortRef(short) ? short : null;
}

function validMessage(m: unknown): m is string {
	if (typeof m !== "string" || m.length < 1 || m.length > 4000) return false;
	if (/[\u0000-\u0008\u000b-\u001f\u007f]/.test(m)) return false; // 改行（\n）とタブ以外の制御文字
	return m.split("\n")[0].trim() !== "";
}

type Ctx = {
	gitDir: string;
	source: { ref: string; short: string };
	target: { ref: string; short: string };
	message: string;
	cleanup: Cleanup;
	expect: { sourceOid?: string; targetOid?: string };
};

function policyOk(p: unknown): p is Policy {
	const q = p as Policy;
	return (
		typeof p === "object" &&
		p !== null &&
		Array.isArray(q.sources) &&
		Array.isArray(q.targets) &&
		q.sources.every((x) => typeof x === "string") &&
		q.targets.every((x) => typeof x === "string")
	);
}

/** 入力・policy・リポジトリ・設定を検査する（何も書かない）。 */
async function prepare(input: MergeInput, policy: Policy): Promise<Ctx | Refusal> {
	if (typeof input !== "object" || input === null || !policyOk(policy)) return refuse("bad_input");
	if (typeof input.repo !== "string" || input.repo === "" || input.repo.includes("\0")) return refuse("bad_input");
	const source = shortRefOf(input.source);
	const target = shortRefOf(input.target ?? "develop");
	if (source === null || target === null) return refuse("bad_input");
	if (!validMessage(input.message)) return refuse("bad_input");
	const cleanup = input.cleanup ?? "none";
	if (!CLEANUPS.includes(cleanup)) return refuse("bad_input");
	const expect = input.expect ?? {};
	for (const v of [expect.sourceOid, expect.targetOid]) {
		if (v !== undefined && (typeof v !== "string" || !OID_RE.test(v))) return refuse("bad_input");
	}
	if (!policy.sources.some((p) => source.startsWith(p) && source.length > p.length)) return refuse("policy_source");
	if (!policy.targets.includes(target)) return refuse("policy_target");
	const gitDir = await resolveCommonDir(input.repo);
	if (!gitDir) return refuse("bad_input");
	if (await repoConfigHasExternalCode(gitDir)) return refuse("external_code");
	return {
		gitDir,
		source: { ref: `refs/heads/${source}`, short: source },
		target: { ref: `refs/heads/${target}`, short: target },
		message: input.message,
		cleanup: cleanup as Cleanup,
		expect,
	};
}

async function repoConfigHasExternalCode(gitDir: string): Promise<boolean> {
	return (await configHasExternalCode(join(gitDir, "config"))) || (await configHasExternalCode(join(gitDir, "config.worktree")));
}

// ---- 計画 ----

async function revOid(gitDir: string, ref: string): Promise<string | null> {
	const r = await runGit(["rev-parse", "--verify", "--quiet", `${ref}^{commit}`], { gitDir });
	const oid = r.out.trim();
	return r.code === 0 && OID_RE.test(oid) ? oid : null;
}

type Wt = { path: string; gitDir: string };

function ancestorsOf(p: string): string[] {
	const parts = p.split("/");
	const res: string[] = [];
	for (let i = 1; i < parts.length; i++) res.push(parts.slice(0, i).join("/"));
	return res;
}

/** 2 つのパス集合が重なるか。同じパス、または一方が他方の親ディレクトリ。 */
function overlaps(touched: string[], other: string[]): boolean {
	const o = new Set(other);
	const oAnc = new Set<string>();
	for (const q of other) for (const a of ancestorsOf(q)) oAnc.add(a);
	for (const p of touched) {
		if (o.has(p) || oAnc.has(p)) return true;
		for (const a of ancestorsOf(p)) if (o.has(a)) return true;
	}
	return false;
}

const IN_PROGRESS = ["MERGE_HEAD", "rebase-merge", "rebase-apply", "CHERRY_PICK_HEAD", "REVERT_HEAD", "BISECT_LOG"];

/** target が checkout されている worktree。無ければ null。一覧が取れなければ undefined。 */
async function findWorktree(gitDir: string, ref: string): Promise<Wt | null | undefined> {
	const list = await listWorktrees(gitDir);
	if (list === null) return undefined;
	const w = list.find((x) => x.branch === ref);
	if (!w) return null;
	const g = await runGit(["rev-parse", "--absolute-git-dir"], { cwd: w.path });
	const line = g.out.split("\n")[0];
	if (g.code !== 0 || !line) return undefined;
	return { path: w.path, gitDir: line };
}

async function statusPaths(w: Wt, ignored: boolean): Promise<StatusEntry[] | null> {
	const args = ["status", "--porcelain=v1", "-z", "--untracked-files=all"];
	if (ignored) args.push("--ignored");
	const r = await runGit(args, { cwd: w.path });
	return r.code === 0 ? parseStatus(r.out) : null;
}

/** target の worktree の事前検査（S4 の 6〜9）。 */
async function checkWorktree(ctx: Ctx, w: Wt, touched: string[]): Promise<Refusal | null> {
	if (await configHasExternalCode(join(w.gitDir, "config.worktree"))) return refuse("external_code");
	const head = await runGit(["symbolic-ref", "-q", "HEAD"], { cwd: w.path });
	if (head.code !== 0 || head.out.trim() !== ctx.target.ref) return refuse("head_mismatch");
	if (IN_PROGRESS.some((n) => existsSync(join(w.gitDir, n)))) return refuse("dirty");
	if (existsSync(join(w.gitDir, "index.lock"))) return refuse("busy");
	const st = await statusPaths(w, false);
	if (st === null) return refuse("failed");
	if (overlaps(touched, st.map((e) => e.path))) return refuse("dirty");
	const ig = await statusPaths(w, true);
	if (ig === null) return refuse("failed");
	if (overlaps(touched, ig.filter((e) => e.code === "!!").map((e) => e.path))) return refuse("ignored");
	return null;
}

type Planned = { plan: Plan; wt: Wt | null; added: string[]; newDirs: string[] };

async function computePlan(ctx: Ctx): Promise<Planned | Refusal> {
	const sourceOid = await revOid(ctx.gitDir, ctx.source.ref);
	if (!sourceOid) return refuse("no_source");
	const targetOid = await revOid(ctx.gitDir, ctx.target.ref);
	if (!targetOid) return refuse("no_target");
	if (
		(ctx.expect.sourceOid && ctx.expect.sourceOid !== sourceOid) ||
		(ctx.expect.targetOid && ctx.expect.targetOid !== targetOid)
	) {
		return refuse("stale");
	}
	const anc = await runGit(["merge-base", "--is-ancestor", sourceOid, targetOid], { gitDir: ctx.gitDir });
	if (anc.code === 0) return refuse("already_merged");
	if (anc.code !== 1) return refuse("failed");

	// 結果の tree（object だけを書く。ref・作業ツリーは変えない）。
	// worktree の外で動かすと .gitattributes（binary など）が読まれず、porcelain の git merge と結果が変わる（P2 の差分試験で発見）。
	// 属性は target の tree から読む（git merge は target の作業ツリーの属性を読むのと同じ。git 2.40 以上）
	const mt = await runGit([`--attr-source=${targetOid}`, "merge-tree", "--write-tree", "--name-only", "-z", targetOid, sourceOid], {
		gitDir: ctx.gitDir,
	});
	const toks = mt.out.split("\0");
	if (mt.code === 1) {
		const conflicts: string[] = [];
		for (const t of toks.slice(1)) {
			if (t === "") break;
			conflicts.push(t);
		}
		return { ...refuse("conflict"), conflicts };
	}
	const resultTree = toks[0];
	if (mt.code !== 0 || !OID_RE.test(resultTree)) return refuse("failed");

	const mb = await runGit(["merge-base", targetOid, sourceOid], { gitDir: ctx.gitDir });
	const mergeBase = mb.code === 0 && OID_RE.test(mb.out.trim()) ? mb.out.trim() : null;

	const dt = await runGit(["diff-tree", "-r", "-z", "--name-status", "--no-renames", "--no-ext-diff", "--no-textconv", targetOid, resultTree], {
		gitDir: ctx.gitDir,
	});
	if (dt.code !== 0) return refuse("failed");
	const all: FileChange[] = [];
	const t = dt.out.split("\0");
	for (let i = 0; i + 1 < t.length; i += 2) all.push({ status: t[i], path: t[i + 1] });
	const touched = all.map((f) => f.path);
	const added = all.filter((f) => f.status === "A").map((f) => f.path);

	const wt = await findWorktree(ctx.gitDir, ctx.target.ref);
	if (wt === undefined) return refuse("failed");
	let newDirs: string[] = [];
	if (wt) {
		const bad = await checkWorktree(ctx, wt, touched);
		if (bad) return bad;
		// 統合で新しく作られるディレクトリ（復旧で、空なら消してよいもの）
		const dirs = new Set<string>();
		for (const p of added) for (const a of ancestorsOf(p)) if (!existsSync(join(wt.path, ...a.split("/")))) dirs.add(a);
		newDirs = [...dirs];
	}
	return {
		plan: {
			source: { ref: ctx.source.ref, oid: sourceOid },
			target: { ref: ctx.target.ref, oid: targetOid },
			mergeBase,
			resultTree,
			alreadyMerged: false,
			files: all.slice(0, 200),
			fileCount: all.length,
			touched,
			conflicts: [],
		},
		wt,
		added,
		newDirs,
	};
}

/** 読み取りだけの計画。object を書くほか、ref・index・作業ツリーを変えない。 */
export async function planMerge(input: MergeInput, policy: Policy = DEFAULT_POLICY): Promise<{ ok: true; plan: Plan } | Refusal> {
	try {
		const ctx = await prepare(input, policy);
		if ("ok" in ctx) return ctx;
		const p = await computePlan(ctx);
		if ("ok" in p) return p;
		return { ok: true, plan: p.plan };
	} catch {
		return refuse("failed");
	}
}

// ---- 排他（S5） ----

type LockFile = { pid: number; startedAt: string; id: string };

function pidAlive(pid: number): boolean {
	if (!Number.isInteger(pid) || pid <= 0) return false;
	try {
		process.kill(pid, 0);
		return true;
	} catch (e) {
		return (e as NodeJS.ErrnoException).code === "EPERM";
	}
}

function readLock(path: string): LockFile | null {
	try {
		const j = JSON.parse(readFileSync(path, "utf8")) as LockFile;
		return typeof j.pid === "number" && typeof j.id === "string" ? j : null;
	} catch {
		return null;
	}
}

/**
 * 待たずに取る。取れなければ Refusal。持ち主の pid が死んだ古いロックは自動では奪わない (recover_needed)。
 * 奪う処理は確認と削除の間で競合し、両方が保護区間に入ってしまうため。解除は利用者が明示する recover だけが行う。
 */
function acquireLock(gitDir: string): { id: string } | Refusal {
	const path = join(gitDir, LOCK_NAME);
	const id = randomUUID();
	try {
		// 中身を書いた一時ファイルを link で置く（排他的な作成で、中身が空のロックを他者に見せない）
		const tmp = `${path}.tmp-${id}`;
		writeFileSync(tmp, JSON.stringify({ pid: process.pid, startedAt: new Date().toISOString(), id }), { flag: "wx" });
		try {
			linkSync(tmp, path);
		} finally {
			unlinkSync(tmp);
		}
		return { id };
	} catch (e) {
		if ((e as NodeJS.ErrnoException).code !== "EEXIST") return refuse("failed");
	}
	const cur = readLock(path);
	return cur !== null && pidAlive(cur.pid) ? refuse("busy") : refuse("recover_needed");
}

function releaseLock(gitDir: string, id: string): void {
	const path = join(gitDir, LOCK_NAME);
	if (readLock(path)?.id !== id) return;
	try {
		unlinkSync(path);
	} catch {
		// 解放の失敗は無視
	}
}

// ---- 状態ファイル（S6） ----

type State = {
	id: string;
	source: string;
	target: string;
	targetOld: string;
	commit: string;
	touched: string[];
	added: string[];
	newDirs: string[];
	phase: "ff";
};

function writeState(gitDir: string, st: State): void {
	const path = join(gitDir, STATE_NAME);
	const tmp = `${path}.tmp-${st.id}`;
	writeFileSync(tmp, JSON.stringify(st));
	renameSync(tmp, path);
}

function removeState(gitDir: string): void {
	try {
		unlinkSync(join(gitDir, STATE_NAME));
	} catch {
		// 無ければよい
	}
}

/** 状態ファイル内のパスが、作業ツリーの中の相対パスとして安全か。 */
function safeRel(p: unknown): p is string {
	if (typeof p !== "string" || p === "" || p.includes("\0") || p.startsWith("/")) return false;
	return p.split("/").every((c) => c !== "" && c !== "." && c !== ".." && c.toLowerCase() !== ".git");
}

function readState(gitDir: string): State | null | "broken" {
	const path = join(gitDir, STATE_NAME);
	if (!existsSync(path)) return null;
	try {
		const j = JSON.parse(readFileSync(path, "utf8")) as State;
		const arr = (a: unknown): a is string[] => Array.isArray(a) && a.every(safeRel);
		const ref = (s: unknown): s is string => typeof s === "string" && shortRefOf(s) !== null;
		if (
			typeof j.id !== "string" ||
			!ref(j.source) ||
			!ref(j.target) ||
			!OID_RE.test(String(j.targetOld)) ||
			!OID_RE.test(String(j.commit)) ||
			!arr(j.touched) ||
			!arr(j.added) ||
			!arr(j.newDirs) ||
			j.phase !== "ff"
		) {
			return "broken";
		}
		return j;
	} catch {
		return "broken";
	}
}

// ---- 実行 ----

async function worktreeIsRestored(w: Wt, touched: string[]): Promise<boolean> {
	if (existsSync(join(w.gitDir, "index.lock"))) return false;
	const st = await statusPaths(w, false);
	return st !== null && !overlaps(touched, st.map((e) => e.path));
}

/** 公開の実行。想定外の例外は、絶対パスなどを含まない固定の拒否に変える (S8)。 */
export async function executeMerge(
	input: MergeInput,
	policy: Policy = DEFAULT_POLICY,
	deps: Deps = {},
): Promise<{ ok: true; result: MergeResult } | Refusal> {
	try {
		return await executeMergeInner(input, policy, deps);
	} catch {
		return refuse("failed");
	}
}

function holdsLock(gitDir: string, id: string): boolean {
	return readLock(join(gitDir, LOCK_NAME))?.id === id;
}

async function executeMergeInner(
	input: MergeInput,
	policy: Policy,
	deps: Deps,
): Promise<{ ok: true; result: MergeResult } | Refusal> {
	const ctx = await prepare(input, policy);
	if ("ok" in ctx) return ctx;
	const warnings: string[] = [];
	const lock = acquireLock(ctx.gitDir);
	if ("ok" in lock) return lock;
	try {
		// 前回の統合が途中で止まっている (状態ファイルが残っている) ときは、復旧を失わないように新しい統合を断る
		if (readState(ctx.gitDir) !== null) return refuse("recover_needed");
		const p = await computePlan(ctx);
		if ("ok" in p) return p;
		const ident = await readIdentity(ctx.gitDir, p.wt?.path);
		if (!ident) return refuse("no_identity");
		await deps.afterPlan?.();
		// 最終の検査（計画の後に変わっていないこと）
		const plan = p.plan;
		if ((await revOid(ctx.gitDir, ctx.source.ref)) !== plan.source.oid) return refuse("stale");
		if ((await revOid(ctx.gitDir, ctx.target.ref)) !== plan.target.oid) return refuse("not_ff");
		if (p.wt) {
			const bad = await checkWorktree(ctx, p.wt, plan.touched);
			if (bad) return bad;
		}
		const commit = await makeCommit(ctx, plan, ident);
		if (!commit) return refuse("failed");

		const st: State = {
			id: lock.id,
			source: ctx.source.short,
			target: ctx.target.short,
			targetOld: plan.target.oid,
			commit,
			touched: plan.touched,
			added: p.added,
			newDirs: p.newDirs,
			phase: "ff",
		};
		writeState(ctx.gitDir, st);
		await deps.beforeAdvance?.();
		// 状態を書いた後に、排他を失っていないこと・HEAD が target のままであることをもう一度確かめる (merge --ff-only は実行時の現在の枝を進めるため)
		if (!holdsLock(ctx.gitDir, lock.id)) {
			removeState(ctx.gitDir);
			return refuse("busy");
		}
		if (p.wt) {
			const head = await runGit(["symbolic-ref", "-q", "HEAD"], { cwd: p.wt.path });
			if (head.code !== 0 || head.out.trim() !== ctx.target.ref) {
				removeState(ctx.gitDir);
				return refuse("head_mismatch");
			}
		}
		const advanced = await advanceTarget(ctx, plan.target.oid, commit, p.wt);
		const now = await revOid(ctx.gitDir, ctx.target.ref);
		if (now === null) {
			// 反映を読めなかった。統合されたかどうか分からないので、「先に進んでいる」と言わず、状態ファイルを残して recover に確かさせる
			return refuse("unverified");
		}
		if (now !== commit) {
			// 自分のコミットは反映されていない。作業ツリーが汚れていないと確かめられたときだけ状態を消す
			// (ref が別の誰かに進められていても、作業ツリーが汚れていなければ、残す理由が無い)
			if (!p.wt || (await worktreeIsRestored(p.wt, plan.touched))) removeState(ctx.gitDir);
			return refuse(now === plan.target.oid && advanced === "failed" ? "failed" : "not_ff");
		}
		removeState(ctx.gitDir);

		await deps.beforeCleanup?.();
		const done = await runCleanup(ctx, plan.source.oid, warnings);
		return {
			ok: true,
			result: { commit, targetOld: plan.target.oid, targetNew: commit, cleanup: { requested: ctx.cleanup, done }, warnings },
		};
	} finally {
		releaseLock(ctx.gitDir, lock.id);
	}
}

/** merge commit（親は target・source の順）を作る。hook は走らない。メッセージは標準入力。 */
async function makeCommit(ctx: Ctx, plan: Plan, ident: Identity): Promise<string | null> {
	const env = {
		GIT_AUTHOR_NAME: ident.name,
		GIT_AUTHOR_EMAIL: ident.email,
		GIT_COMMITTER_NAME: ident.name,
		GIT_COMMITTER_EMAIL: ident.email,
	};
	const msg = `${ctx.message.replace(/\n+$/, "")}\n`;
	const r = await runGit(["commit-tree", plan.resultTree, "-p", plan.target.oid, "-p", plan.source.oid, "-F", "-"], {
		gitDir: ctx.gitDir,
		input: msg,
		write: true,
		env,
	});
	const oid = r.out.trim();
	return r.code === 0 && OID_RE.test(oid) ? oid : null;
}

/** target を commit へ進める。worktree があれば merge --ff-only (実行時の現在の枝を進める)、無ければ旧先頭を渡した update-ref (CAS)。
 *  worktree の経路では、HEAD が target のままであることを直前に確かめるだけで、外部の git による HEAD の切替との競合は防げない。 */
async function advanceTarget(ctx: Ctx, oldOid: string, commit: string, w: Wt | null): Promise<"ok" | "failed"> {
	if (w) {
		const r = await runGit(["merge", "--ff-only", "--no-overwrite-ignore", "--no-edit", "--no-stat", "-q", "--no-autostash", "--no-verify-signatures", commit], {
			cwd: w.path,
			write: true,
		});
		return r.code === 0 ? "ok" : "failed";
	}
	const r = await runGit(["update-ref", "--no-deref", "-m", "pr-viewer merge", ctx.target.ref, commit, oldOid], {
		gitDir: ctx.gitDir,
		write: true,
	});
	return r.code === 0 ? "ok" : "failed";
}

/** cleanup。失敗は統合の成功を取り消さず、warnings に載せる。 */
async function runCleanup(ctx: Ctx, sourceOid: string, warnings: string[]): Promise<string[]> {
	const done: string[] = [];
	if (ctx.cleanup === "none") return done;
	if (ctx.cleanup === "branch_and_worktree") {
		const list = await listWorktrees(ctx.gitDir);
		const sw = list?.find((x) => x.branch === ctx.source.ref);
		if (sw) {
			const g = await runGit(["rev-parse", "--absolute-git-dir"], { cwd: sw.path });
			const gd = g.out.split("\n")[0];
			// source 固有の設定 (filter など) が外部のコードを動かすかもしれないので、status を動かす前に検査する
			const risky = g.code !== 0 || !gd || (await configHasExternalCode(join(gd, "config.worktree")));
			// 無視ファイル (ignored) も入れて確かめる: git worktree remove は ignored を守らず再帰的に消す
			const st = risky ? null : await statusPaths({ path: sw.path, gitDir: gd }, true);
			const busy = risky || IN_PROGRESS.some((n) => existsSync(join(gd, n)));
			if (st === null || st.length > 0 || busy) {
				warnings.push("統合元の worktree に未コミットの変更・無視ファイル、または確かめられない設定があるため、worktree を残しました。");
			} else {
				const r = await runGit(["worktree", "remove", sw.path], { gitDir: ctx.gitDir, write: true });
				if (r.code === 0) done.push("worktree");
				else warnings.push("統合元の worktree を削除できませんでした。");
			}
		}
	}
	// 枝の削除。どこかの worktree で checkout 中の枝は消さない (update-ref -d は checkout 中でも消してしまうので、先に確かめる)。
	// 消すときは、承認した source の先頭を指定した CAS にする (統合の後に進んだ枝や、upstream 基準の「統合済み」判定で消える枝を守る)
	const list = await listWorktrees(ctx.gitDir);
	if (list === null || list.some((x) => x.branch === ctx.source.ref)) {
		warnings.push("統合元の枝が worktree で使われている (または確かめられない) ため、枝を残しました。");
		return done;
	}
	if ((await revOid(ctx.gitDir, ctx.source.ref)) !== sourceOid) {
		warnings.push("統合元の枝が統合の後に進んでいるため、枝を残しました。");
		return done;
	}
	const del = await runGit(["update-ref", "-d", "--no-deref", ctx.source.ref, sourceOid], { gitDir: ctx.gitDir, write: true });
	if (del.code === 0) {
		done.push("branch");
		// 枝の設定 (upstream など) の後片付け。失敗しても影響しない
		await runGit(["config", "--remove-section", `branch.${ctx.source.short}`], { gitDir: ctx.gitDir, write: true });
	} else {
		warnings.push("統合元の枝を削除できませんでした。");
	}
	return done;
}

// ---- 復旧（S7） ----
// 復旧は「確かめて、状態を解除する」だけで、ref・index・作業ツリーを書き換えない（利用者のデータを失わないため）。
// 途中で止まった ff が書いたものの片付けは、診断（details）の一覧を見て、利用者が手で行う。片付けた後にもう一度 recover すると、状態が解除される。

/** 状態ファイルのパスのうち、status に出ているもの（親ディレクトリの重なりを含む）。 */
function overlapping(paths: string[], entries: StatusEntry[]): string[] {
	const set = new Set(paths);
	const anc = new Set<string>();
	for (const p of paths) for (const a of ancestorsOf(p)) anc.add(a);
	const res: string[] = [];
	for (const e of entries) {
		if (set.has(e.path) || anc.has(e.path) || ancestorsOf(e.path).some((a) => set.has(a))) res.push(e.path);
	}
	return [...new Set(res)];
}

function manual(details: Record<string, unknown>): Refusal {
	return { ...refuse("failed", "手で確認が要ります。"), details };
}

/** 公開の復旧。想定外の例外は、絶対パスなどを含まない固定の拒否に変える (S8)。 */
export async function recoverMerge(repo: string): Promise<{ ok: true; state: "clean" | "completed" | "cleared" } | Refusal> {
	try {
		return await recoverMergeInner(repo);
	} catch {
		return manual({ cause: "exception" });
	}
}

async function recoverMergeInner(repo: string): Promise<{ ok: true; state: "clean" | "completed" | "cleared" } | Refusal> {
	if (typeof repo !== "string" || repo === "" || repo.includes("\0")) return refuse("bad_input");
	const gitDir = await resolveCommonDir(repo);
	if (!gitDir) return refuse("bad_input");
	if (await repoConfigHasExternalCode(gitDir)) return refuse("external_code");
	const lockPath = join(gitDir, LOCK_NAME);
	const stale = existsSync(lockPath) ? readLock(lockPath) : undefined; // undefined = 無い、null = 読めない
	if (stale && pidAlive(stale.pid)) return refuse("busy");
	// ロックが無いときは、確かめている間に新しい統合が始まらないよう、自分で取る。古いロックが残っているときは、それが新しい統合を止めている
	let mine: string | null = null;
	if (stale === undefined) {
		const l = acquireLock(gitDir);
		if ("ok" in l) return l;
		mine = l.id;
	}
	try {
		const done = (state: "clean" | "completed" | "cleared"): { ok: true; state: "clean" | "completed" | "cleared" } => {
			removeState(gitDir);
			if (stale !== undefined) {
				try {
					unlinkSync(lockPath); // 持ち主の pid が死んでいる古いロックを、利用者の復旧で解除する
				} catch {
					// 先に消えた
				}
			}
			return { ok: true, state };
		};
		const st = readState(gitDir);
		if (st === null) return done("clean");
		if (st === "broken") return manual({ cause: "state_unreadable" });
		const ref = `refs/heads/${st.target}`;
		const now = await revOid(gitDir, ref);
		if (now === st.commit) return done("completed"); // 統合は反映されていた
		if (now !== st.targetOld) return manual({ cause: "target_moved" });
		const w = await findWorktree(gitDir, ref);
		if (w === undefined) return manual({ cause: "worktree_unknown" });
		if (w !== null) {
			if (await configHasExternalCode(join(w.gitDir, "config.worktree"))) return refuse("external_code");
			const head = await runGit(["symbolic-ref", "-q", "HEAD"], { cwd: w.path });
			if (head.code !== 0 || head.out.trim() !== ref) return manual({ cause: "head_mismatch" });
			const operation = IN_PROGRESS.some((n) => existsSync(join(w.gitDir, n)));
			const indexLock = existsSync(join(w.gitDir, "index.lock")); // 消さない。他の git が使っているかもしれない
			const st1 = await statusPaths(w, true);
			if (st1 === null) return manual({ cause: "status_failed" });
			const diffs = overlapping([...new Set([...st.touched, ...st.added, ...st.newDirs])], st1);
			if (operation || indexLock || diffs.length > 0) {
				return manual({ cause: "worktree_not_clean", operation, indexLock, paths: diffs.slice(0, 50), pathCount: diffs.length });
			}
		}
		return done("cleared");
	} finally {
		if (mine !== null) releaseLock(gitDir, mine);
	}
}
