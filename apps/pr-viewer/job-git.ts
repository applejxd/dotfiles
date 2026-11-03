// ジョブ（変更を依頼 = pis -p の都度起動）の git 層。起動前の検査（P2〜P4・P6）・終了後の照合（Q2）・
// 使い捨て index での tree の構築（Q3）・結果の検査（Q4・Q5。規則は job-check.ts）・commit と CAS（Q6・Q7）。
// 設計: .tmp/subagents/4-job-849eef96c69975b3.md の「検査と commit」。試験: test/agents/test_pr_viewer_jobs_git.py。
//
// 前提: pis（Fence 内）は feature の worktree と共通 .git の ref・worktrees/<n>/・worktree の .git ポインタを書き換えうる。
// だから、起動前に採った記録（Snapshot）と終了後を照合して改ざんを検出し、tree は worktree の .git・index を使わずに作る。
// git の実行は merge-git.ts の runGit だけを使う（新しい実行器は作らない。hook・外部の driver・filter は SAFE_ARGS が止める）。
import { createHash } from "node:crypto";
import { existsSync, lstatSync, mkdtempSync, readFileSync, readdirSync, readlinkSync, realpathSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { type ChangedFile, type CheckResult, LIMITS, checkChanges, parseNumstatBinary, parseRaw } from "./job-check.ts";
import { assertStateDirIsolated } from "./job-store.ts";
import { configHasExternalCode, listWorktrees, parseStatus, readIdentity, resolveCommonDir, runGit } from "./merge-git.ts";

export type Refusal = { ok: false; code: string; reason: string };
/** 起動前の検査の結果。JSON にできる（呼び出し側が job.json に保存してよい）。 */
export type Pre = {
	gitDir: string; // 共通ディレクトリ（realpath）
	adminDir: string; // worktree の管理ディレクトリ（linked worktree は <共通>/worktrees/<n>。主 worktree は共通と同じ）
	worktree: string; // realpath
	ref: string; // refs/heads/<feature>
	baseOid: string;
	protectedRefs: string[]; // refs/heads/<名前>
};
/** 起動前に採る記録（P6）。値は内容のハッシュか OID。無いものは null。 */
export type Snapshot = {
	pointer: string | null;
	admin: { HEAD: string | null; gitdir: string | null; commondir: string | null };
	configWorktree: string | null;
	attributes: string | null;
	exclude: string | null;
	refs: Record<string, string | null>;
};
export type PreflightInput = {
	repo: string;
	source: string; // feature の短い名前
	expectOid: string;
	protectedRefs?: string[]; // 短い名前。既定は develop・main・master
};
export type JobMeta = { jobId: string; batchIds: string[] };
export type FinalizeResult = {
	state: "tampered" | "no_change" | "needs_review" | "committed" | "failed";
	/** コードだけ。tampered・needs_review の理由（job-check の理由・tampered・ref_moved など） */
	reasons: string[];
	/** 違いのあった記録の項目名（診断用のコード。パスを含めない） */
	diffs?: string[];
	files: ChangedFile[];
	fileCount: number;
	resultOid?: string;
};
/** 試験用の差し込み口。beforeUpdateRef は commit 作成の後・update-ref の前に呼ばれる（CAS の競合の再現に使う）。 */
export type FinalizeDeps = { beforeUpdateRef?: () => Promise<void> | void };

export const DEFAULT_PROTECTED = ["develop", "main", "master"];
const OID_RE = /^(?:[0-9a-f]{40}|[0-9a-f]{64})$/;
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const IN_PROGRESS = ["MERGE_HEAD", "rebase-merge", "rebase-apply", "CHERRY_PICK_HEAD", "REVERT_HEAD", "BISECT_LOG", "sequencer"];

const REASONS: Record<string, string> = {
	bad_request: "入力が正しくありません。",
	stale_view: "画面が古くなっています。開き直してください。",
	no_worktree: "この枝を checkout している worktree が（ちょうど 1 つ）見つかりません。",
	head_mismatch: "worktree が別の枝を指しています。",
	in_progress: "worktree で別の git の操作が進行中です。",
	external_code: "外部のコードを動かしうる設定があるため、実行しません。",
	dirty: "worktree に未コミットの変更があります。",
	fence_request_present: "worktree に .opencode があるため、実行しません。",
	tampered: "worktree の管理情報が想定と違います。",
	failed: "失敗しました。",
};

function refuse(code: string): Refusal {
	return { ok: false, code, reason: REASONS[code] ?? REASONS.failed };
}

// ---- 入力の検査 ----

function validShortRef(s: string): boolean {
	if (!/^[A-Za-z0-9._/-]+$/.test(s)) return false;
	if (s.startsWith("refs/") || s.length > 200 || s.startsWith("-") || s.startsWith("/") || s.endsWith("/") || s.endsWith(".")) return false;
	if (s.includes("..") || s.includes("//")) return false;
	return s.split("/").every((c) => c !== "" && !c.startsWith(".") && !c.endsWith(".lock"));
}

// ---- 記録の部品 ----

/** ファイルの内容のハッシュ。無ければ null。symlink・ディレクトリ・読めないものは、それと分かる固定の文字列。 */
function fingerprint(path: string): string | null {
	let st;
	try {
		st = lstatSync(path);
	} catch (e) {
		return (e as NodeJS.ErrnoException).code === "ENOENT" ? null : "unreadable";
	}
	try {
		if (st.isSymbolicLink()) return `symlink:${readlinkSync(path)}`;
		if (st.isDirectory()) return "dir";
		return createHash("sha256").update(readFileSync(path)).digest("hex");
	} catch {
		return "unreadable";
	}
}

function realOrNull(p: string): string | null {
	try {
		return realpathSync(p);
	} catch {
		return null;
	}
}

type Layout = { adminDir: string };

/**
 * worktree の管理情報の整合を、共通側から確かめる。**この間は worktree の .git を読む git を動かさない**
 * （ポインタが別の gitdir を指していても、その設定を読まないため）。
 * 共通の worktrees/<n>/gitdir が「<worktree>/.git」を指し、worktree の .git ポインタが worktrees/<n> を指し、commondir が共通を指すこと。
 */
function checkLayout(common: string, worktree: string): Layout | Refusal {
	const dotgit = join(worktree, ".git");
	let st;
	try {
		st = lstatSync(dotgit);
	} catch {
		return refuse("tampered");
	}
	if (st.isDirectory()) {
		// 主 worktree: .git が共通ディレクトリそのもの
		return realOrNull(dotgit) === common ? { adminDir: common } : refuse("tampered");
	}
	if (!st.isFile()) return refuse("tampered");
	const wtRoot = join(common, "worktrees");
	let names: string[];
	try {
		names = readdirSync(wtRoot);
	} catch {
		return refuse("no_worktree");
	}
	const matches = names.filter((n) => {
		try {
			return readFileSync(join(wtRoot, n, "gitdir"), "utf8").trim() === dotgit;
		} catch {
			return false;
		}
	});
	if (matches.length !== 1) return refuse(matches.length === 0 ? "no_worktree" : "tampered");
	const adminDir = join(wtRoot, matches[0]);
	let pointer: string;
	let commondir: string;
	try {
		pointer = readFileSync(dotgit, "utf8");
		commondir = readFileSync(join(adminDir, "commondir"), "utf8").trim();
	} catch {
		return refuse("tampered");
	}
	const m = /^gitdir: ([^\n]+)\n?$/.exec(pointer);
	if (!m || realOrNull(m[1]) !== realOrNull(adminDir)) return refuse("tampered");
	if (realOrNull(resolve(adminDir, commondir)) !== common) return refuse("tampered");
	return { adminDir: realOrNull(adminDir) ?? adminDir };
}

async function refOid(common: string, ref: string): Promise<string | null> {
	const r = await runGit(["rev-parse", "--verify", "--quiet", ref], { gitDir: common });
	const oid = r.out.trim();
	return r.code === 0 && OID_RE.test(oid) ? oid : null;
}

async function externalCodeIn(common: string, adminDir: string): Promise<boolean> {
	const files = [join(common, "config"), join(common, "config.worktree"), join(adminDir, "config.worktree")];
	for (const f of files) if (await configHasExternalCode(f)) return true;
	return false;
}

/** P6: 記録の採取。ファイルの読み取りと、共通ディレクトリへの rev-parse だけ（worktree の .git を読む git は動かさない）。 */
export async function collectSnapshot(pre: Pre): Promise<Snapshot> {
	const refs: Record<string, string | null> = {};
	for (const ref of [pre.ref, ...pre.protectedRefs]) {
		// symref（別の ref への参照）は OID と区別できる固定の値にする（OID だけ見ると、参照先の枝を更新させる置き換えを見逃す）
		const sym = await runGit(["symbolic-ref", "-q", ref], { gitDir: pre.gitDir });
		refs[ref] = sym.code === 0 ? `symref:${sym.out.trim()}` : await refOid(pre.gitDir, ref);
	}
	return {
		pointer: fingerprint(join(pre.worktree, ".git")),
		admin: {
			HEAD: fingerprint(join(pre.adminDir, "HEAD")),
			gitdir: fingerprint(join(pre.adminDir, "gitdir")),
			commondir: fingerprint(join(pre.adminDir, "commondir")),
		},
		configWorktree: fingerprint(join(pre.adminDir, "config.worktree")),
		attributes: fingerprint(join(pre.gitDir, "info", "attributes")),
		exclude: fingerprint(join(pre.gitDir, "info", "exclude")),
		refs,
	};
}

// ---- 起動前の検査（P2〜P4・P6） ----

/** 起動時の検査: 保存先が、どのリポジトリの共通 .git・worktree の中にも無いこと（Fence から書ける場所に置かない）。 */
export async function stateDirIsolated(cfg: { stateDir: string }, repos: { gitDir: string }[]): Promise<boolean> {
	for (const r of repos) {
		const wts = (await listWorktrees(r.gitDir)) ?? [];
		try {
			assertStateDirIsolated(cfg.stateDir, [r.gitDir, ...wts.map((w) => w.path)]);
		} catch {
			return false;
		}
	}
	return true;
}

/** worktree の中・HEAD の tree の最上位に `.opencode`（大文字小文字違いを含む）があるか。 */
async function hasOpencode(common: string, worktree: string, baseOid: string): Promise<boolean | null> {
	try {
		if (readdirSync(worktree).some((n) => n.toLowerCase() === ".opencode")) return true;
	} catch {
		return null;
	}
	const r = await runGit(["ls-tree", "--name-only", "-z", baseOid], { gitDir: common });
	if (r.code !== 0) return null;
	return r.out.split("\0").some((n) => n.toLowerCase() === ".opencode");
}

/**
 * 起動前の検査。worktree の特定 → .git ポインタの整合 → 外部コード → 進行中の操作 → HEAD と OID → .opencode → dirty → 記録の採取。
 * 何も書かない。通ったら Pre と記録を返す（呼び出し側が保存して、終了後に finalizeJob へ渡す）。
 */
export async function preflight(input: PreflightInput): Promise<{ ok: true; pre: Pre; record: Snapshot } | Refusal> {
	try {
		if (typeof input !== "object" || input === null) return refuse("bad_request");
		if (typeof input.repo !== "string" || input.repo === "" || input.repo.includes("\0")) return refuse("bad_request");
		if (typeof input.source !== "string" || !validShortRef(input.source)) return refuse("bad_request");
		if (typeof input.expectOid !== "string" || !OID_RE.test(input.expectOid)) return refuse("bad_request");
		const prot = input.protectedRefs ?? DEFAULT_PROTECTED;
		if (!Array.isArray(prot) || prot.length > 16 || !prot.every((p) => typeof p === "string" && validShortRef(p))) return refuse("bad_request");

		const common = await resolveCommonDir(input.repo);
		if (!common) return refuse("bad_request");
		const ref = `refs/heads/${input.source}`;

		// P3: feature を checkout している worktree がちょうど 1 つ
		const list = await listWorktrees(common);
		if (list === null) return refuse("no_worktree");
		const mine = list.filter((w) => w.branch === ref);
		if (mine.length !== 1) return refuse("no_worktree");
		const worktree = realOrNull(mine[0].path);
		if (!worktree) return refuse("no_worktree");

		const layout = checkLayout(common, mine[0].path);
		if ("ok" in layout) return layout;
		const adminDir = layout.adminDir;

		if (await externalCodeIn(common, adminDir)) return refuse("external_code");
		if (IN_PROGRESS.some((n) => existsSync(join(adminDir, n))) || existsSync(join(adminDir, "index.lock"))) return refuse("in_progress");

		const head = await runGit(["symbolic-ref", "-q", "HEAD"], { gitDir: adminDir });
		if (head.code !== 0 || head.out.trim() !== ref) return refuse("head_mismatch");
		const oid = await refOid(common, ref);
		if (oid === null) return refuse("no_worktree");
		if (oid !== input.expectOid) return refuse("stale_view");

		// P4: .opencode は dirty より先に見る（より具体的な理由を返す）
		const oc = await hasOpencode(common, worktree, oid);
		if (oc === null) return refuse("failed");
		if (oc) return refuse("fence_request_present");

		// dirty（.gitignore された物を除く、追跡外を含む全部）
		const st = await runGit(["--work-tree=" + worktree, "status", "--porcelain=v1", "-z", "--untracked-files=all"], { gitDir: adminDir, cwd: worktree });
		if (st.code !== 0) return refuse("failed");
		if (parseStatus(st.out).length > 0) return refuse("dirty");

		const pre: Pre = { gitDir: common, adminDir, worktree, ref, baseOid: oid, protectedRefs: prot.map((p) => `refs/heads/${p}`) };
		const record = await collectSnapshot(pre);
		if (record.refs[ref] !== oid) return refuse("tampered"); // feature の ref が symref
		return { ok: true, pre, record };
	} catch {
		return refuse("failed");
	}
}

// ---- 終了後の照合（Q2） ----

/** 記録と今を照合する。違いのあった項目名の一覧を返す（空なら一致）。1 つでもあれば tampered（commit しない）。 */
export async function verifySnapshot(pre: Pre, before: Snapshot): Promise<string[]> {
	const diffs: string[] = [];
	const wtName = (list: string[], name: string) => {
		if (!list.includes(name)) list.push(name);
	};
	const layout = checkLayout(pre.gitDir, pre.worktree);
	if ("ok" in layout || layout.adminDir !== pre.adminDir) wtName(diffs, "layout");
	const now = await collectSnapshot(pre);
	if (now.pointer !== before.pointer) wtName(diffs, "pointer");
	for (const k of ["HEAD", "gitdir", "commondir"] as const) if (now.admin[k] !== before.admin[k]) wtName(diffs, `admin_${k}`);
	if (now.configWorktree !== before.configWorktree) wtName(diffs, "config_worktree");
	if (now.attributes !== before.attributes) wtName(diffs, "info_attributes");
	if (now.exclude !== before.exclude) wtName(diffs, "info_exclude");
	const names = new Set([...Object.keys(before.refs), ...Object.keys(now.refs)]);
	for (const r of names) if (now.refs[r] !== before.refs[r]) wtName(diffs, r === pre.ref ? "feature_ref" : "protected_ref");
	if (now.refs[pre.ref] !== pre.baseOid) wtName(diffs, "feature_ref");
	if (await externalCodeIn(pre.gitDir, pre.adminDir)) wtName(diffs, "config_code");
	return diffs;
}

// ---- tree の構築（Q3）と検査（Q4・Q5） ----

/**
 * 使い捨ての index で、基点の tree に作業ツリーの変更を載せた tree を作る（read-tree → add -A → write-tree）。
 * 共通ディレクトリ + worktree のパスで動かし、worktree の .git・index は使わない。ref・本物の index は変えない（object だけ書く）。
 */
export async function buildResultTree(pre: Pre): Promise<{ ok: true; tree: string; baseTree: string } | Refusal> {
	let dir: string | null = null;
	try {
		const bt = await runGit(["rev-parse", "--verify", `${pre.baseOid}^{tree}`], { gitDir: pre.gitDir });
		const baseTree = bt.out.trim();
		if (bt.code !== 0 || !OID_RE.test(baseTree)) return refuse("failed");
		dir = mkdtempSync(join(tmpdir(), "prv-job-index-"));
		const opts = { gitDir: pre.gitDir, cwd: pre.worktree, write: true, env: { GIT_INDEX_FILE: join(dir, "index") }, timeoutMs: 120_000 };
		const wtArg = "--work-tree=" + pre.worktree;
		if ((await runGit([wtArg, "read-tree", pre.baseOid], opts)).code !== 0) return refuse("failed");
		if ((await runGit([wtArg, "add", "-A"], opts)).code !== 0) return { ok: false, code: "add_failed", reason: "変更の取り込みに失敗しました。" };
		const wr = await runGit([wtArg, "write-tree"], opts);
		const tree = wr.out.trim();
		if (wr.code !== 0 || !OID_RE.test(tree)) return refuse("failed");
		return { ok: true, tree, baseTree };
	} catch {
		return refuse("failed");
	} finally {
		if (dir) {
			try {
				rmSync(dir, { recursive: true, force: true });
			} catch {
				// 後片付けの失敗は無視
			}
		}
	}
}

/** 基点と tree の差を集めて、Q4・Q5 の規則に当てる。riskPaths が null（読めない）なら needs_review。 */
export async function inspectTree(pre: Pre, tree: string, riskPaths: RegExp[] | null): Promise<CheckResult | Refusal> {
	const common = { gitDir: pre.gitDir };
	const flags = ["-r", "-z", "--no-renames", "--no-ext-diff", "--no-textconv"];
	const raw = await runGit(["diff-tree", ...flags, "--raw", "--no-abbrev", pre.baseOid, tree], { ...common, maxBytes: 4 * 1024 * 1024 });
	const review = (reasons: string[]): CheckResult => ({ verdict: "needs_review", reasons, files: [], fileCount: 0 });
	if (raw.code === 125) return review(["too_many_files"]); // 出力が大きすぎる
	if (raw.code !== 0) return refuse("failed");
	const all = parseRaw(raw.out);
	if (all === null) return review(["unsupported_file"]);
	if (all.length > LIMITS.maxFiles) {
		// 件数が上限を超えたら、大きさ・バイナリの調査はしない（拒否は確定）
		const r = checkChanges({ entries: all.slice(0, LIMITS.maxFiles + 1), riskPaths });
		return { ...r, fileCount: all.length };
	}
	let binary = new Set<string>();
	if (all.length > 0) {
		const ns = await runGit(["diff-tree", ...flags, "--numstat", pre.baseOid, tree], { ...common, maxBytes: 4 * 1024 * 1024 });
		const parsed = ns.code === 0 ? parseNumstatBinary(ns.out) : null;
		if (parsed === null) return refuse("failed");
		binary = parsed;
	}
	const oids = [...new Set(all.filter((e) => e.status === "A" || e.status === "M").map((e) => e.newOid))];
	const sizes: Record<string, number> = {};
	if (oids.length > 0) {
		const cf = await runGit(["cat-file", "--batch-check=%(objectname) %(objecttype) %(objectsize)"], { ...common, input: oids.join("\n") + "\n" });
		if (cf.code !== 0) return refuse("failed");
		for (const line of cf.out.split("\n")) {
			const m = /^([0-9a-f]+) blob (\d+)$/.exec(line);
			if (m) sizes[m[1]] = Number(m[2]);
		}
	}
	return checkChanges({ entries: all, binaryPaths: binary, sizes, riskPaths });
}

// ---- commit の作成と CAS（Q6・Q7） ----

function commitMessage(meta: JobMeta, count: number): string {
	return [
		"fix: レビュー指摘への対応（PR ビューアのジョブ）",
		"",
		`ジョブ: ${meta.jobId}`,
		`batch: ${meta.batchIds.join(", ")}`,
		`変更ファイル数: ${count}`,
		"",
	].join("\n");
}

/**
 * 終了後の一連の処理。照合（Q2）→ tree の構築（Q3）→ 検査（Q4・Q5）→ commit の作成（Q6）→ ref の CAS 更新と worktree の index の整合（Q7）。
 * commit するのは、すべてを通ったときだけ。通らなければ作業ツリーはそのまま残す（自動では戻さない）。
 */
export async function finalizeJob(
	pre: Pre,
	record: Snapshot,
	opts: JobMeta & { riskPaths: RegExp[] | null },
	deps: FinalizeDeps = {},
): Promise<FinalizeResult> {
	const none = { files: [] as ChangedFile[], fileCount: 0 };
	const failed = (reasons: string[]): FinalizeResult => ({ state: "failed", reasons, ...none });
	try {
		if (!UUID_RE.test(opts.jobId) || opts.batchIds.length > 10 || !opts.batchIds.every((b) => UUID_RE.test(b))) return failed(["bad_input"]);
		const tampered = async (): Promise<FinalizeResult | null> => {
			const diffs = await verifySnapshot(pre, record);
			return diffs.length > 0 ? { state: "tampered", reasons: ["tampered"], diffs, ...none } : null;
		};
		const t1 = await tampered();
		if (t1) return t1;

		const built = await buildResultTree(pre);
		if (!built.ok) return failed([built.code]);
		if (built.tree === built.baseTree) return { state: "no_change", reasons: [], ...none };

		const check = await inspectTree(pre, built.tree, opts.riskPaths);
		if ("ok" in check) return failed([check.code]);
		if (check.verdict !== "commit") return { state: "needs_review", reasons: check.reasons, files: check.files, fileCount: check.fileCount };

		// 作者は共通ディレクトリの設定だけから読む（worktree の .git を読む git は動かさない）
		const who = await readIdentity(pre.gitDir);
		if (!who) return failed(["no_identity"]);
		const msg = commitMessage(opts, check.fileCount);
		const author = { GIT_AUTHOR_NAME: who.name, GIT_AUTHOR_EMAIL: who.email, GIT_COMMITTER_NAME: who.name, GIT_COMMITTER_EMAIL: who.email };
		const ct = await runGit(["commit-tree", built.tree, "-p", pre.baseOid, "-F", "-"], { gitDir: pre.gitDir, input: msg, write: true, env: author });
		const newOid = ct.out.trim();
		if (ct.code !== 0 || !OID_RE.test(newOid)) return failed(["commit_failed"]);

		// ref を動かす直前にもう一度照合する（検査と更新の間の窓を狭める）
		const t2 = await tampered();
		if (t2) return t2;
		await deps.beforeUpdateRef?.();
		const up = await runGit(["update-ref", "--no-deref", "-m", "pr-viewer job", pre.ref, newOid, pre.baseOid], { gitDir: pre.gitDir, write: true });
		if (up.code !== 0) return failed(["ref_moved"]);

		// worktree の index を新しい HEAD に揃える（作業ツリーは変えない）
		const rs = await runGit(["--work-tree=" + pre.worktree, "reset", "-q"], { gitDir: pre.adminDir, cwd: pre.worktree, write: true });
		return {
			state: "committed",
			reasons: rs.code === 0 ? [] : ["reset_failed"],
			files: check.files,
			fileCount: check.fileCount,
			resultOid: newOid,
		};
	} catch {
		return failed(["exception"]);
	}
}
