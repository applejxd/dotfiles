// PR ビューアの API（読み取り専用）。契約: .tmp/keep/prv-app/api-contract.md
import {
	ApiError,
	git,
	gitCapped,
	isOid,
	listBranches,
	parseDiff,
	parseNumstat,
	parseRaw,
	prKeyOf,
	resolveTarget,
} from "./git-view.ts";
import type { BranchRef, FileEntry, Hunk, Repo } from "./git-view.ts";
import { mergeExecute, mergePlan } from "./merge-api.ts";
import type { MergeEnv, PostResult } from "./merge-api.ts";
import { blobsFor, getReview, postComment, postSubmit } from "./review-api.ts";
import type { PrCtx } from "./review-api.ts";

const MAX_FILES = 400;
const MAX_COMMITS = 200;
const MAX_FILE_DIFF_BYTES = 200 * 1024;
const MAX_PATH_LEN = 4096;
const MAX_PRS_PER_REPO = 200;
const OVERLAP_SHOW = 20; // 画面へ返すパスの上限
const OVERLAP_SCAN = 2000; // 統合先側の変更がこれを超えたら「多数」として打ち切る

type LastCommit = { oid: string; subject: string; author: string; at: string };
export type PrSummary = {
	repoId: string;
	prKey: string;
	id: string;
	repoName: string;
	branch: string;
	target: string;
	state: "open" | "merged";
	commits: number;
	files: number;
	additions: number;
	deletions: number;
	lastCommit: LastCommit;
	sourceOid: string;
	targetOid: string;
	baseOid: string;
	/** 分岐後に統合先が進んだコミット数（0 なら進んでいない） */
	behind: number;
	/** 分岐後に PR の枝と統合先の両方が変更したファイル（衝突の可能性の目安。判定ではない） */
	overlap: Overlap;
};
export type Overlap = { count: number; paths: string[]; truncated: boolean };
type Commit = LastCommit;

type Computed = { summary: PrSummary; files: FileEntry[] };

// source・target の OID が同じなら結果も同じ（不変）。上限つきで覚える
const cache = new Map<string, Computed>();
const CACHE_MAX = 500;

function notFound(): ApiError {
	return new ApiError(404, "not_found", "見つかりません。");
}

async function diffFiles(repo: Repo, base: string, source: string): Promise<FileEntry[]> {
	const common = ["diff", "-z", "--no-ext-diff", "--no-textconv", "-M", base, source, "--"];
	const raw = parseRaw((await git(repo, [...common.slice(0, 2), "--raw", ...common.slice(2)])).out);
	const num = new Map(parseNumstat((await git(repo, [...common.slice(0, 2), "--numstat", ...common.slice(2)])).out).map((e) => [e.path, e]));
	return raw.map((r) => {
		const n = num.get(r.path);
		return {
			path: r.path,
			oldPath: r.status === "R" ? r.oldPath : null,
			status: r.status,
			additions: n?.additions ?? 0,
			deletions: n?.deletions ?? 0,
			binary: n?.binary ?? false,
		};
	});
}

const NO_OVERLAP: Overlap = { count: 0, paths: [], truncated: false };

/** 統合先が分岐後に変えたファイルと、PR 側の変更ファイルの積集合。読み取りだけ。 */
async function overlapOf(repo: Repo, base: string, targetOid: string, files: FileEntry[]): Promise<Overlap> {
	const r = await git(repo, ["diff", "--name-only", "-z", "--no-ext-diff", "--no-textconv", base, targetOid, "--"]);
	const theirs = r.out.split("\0").filter((p) => p !== "");
	if (theirs.length > OVERLAP_SCAN) return { count: theirs.length, paths: [], truncated: true };
	const mine = new Set<string>();
	for (const f of files) {
		mine.add(f.path);
		if (f.oldPath) mine.add(f.oldPath);
	}
	const both = theirs.filter((p) => mine.has(p)).sort();
	return { count: both.length, paths: both.slice(0, OVERLAP_SHOW), truncated: both.length > OVERLAP_SHOW };
}

/** 統合先が上流（<target>@{upstream}、なければ origin/<target>）より先にある件数。上流が読めないときは null。 */
async function unpushedOf(repo: Repo, target: string): Promise<number | null> {
	let up = await git(repo, ["rev-parse", "--verify", "--quiet", `refs/heads/${target}@{upstream}`], true);
	let ref = up.out.trim();
	if (up.code !== 0 || !isOid(ref)) {
		up = await git(repo, ["rev-parse", "--verify", "--quiet", `refs/remotes/origin/${target}`], true);
		ref = up.out.trim();
		if (up.code !== 0 || !isOid(ref)) return null;
	}
	const n = await git(repo, ["rev-list", "--count", `${ref}..refs/heads/${target}`], true);
	const count = Number(n.out.trim());
	return n.code === 0 && Number.isFinite(count) ? count : null;
}

async function compute(repo: Repo, b: BranchRef, target: { name: string; oid: string }): Promise<Computed | null> {
	const key = `${repo.repoId}:${b.oid}:${target.oid}:${target.name}:${b.branch}`;
	const hit = cache.get(key);
	if (hit) return hit;
	const mb = await git(repo, ["merge-base", target.oid, b.oid], true);
	const base = mb.out.trim();
	if (mb.code !== 0 || !isOid(base)) return null; // 共通の祖先が無いブランチは PR にしない
	const anc = await git(repo, ["merge-base", "--is-ancestor", b.oid, target.oid], true);
	const count = await git(repo, ["rev-list", "--count", `${target.oid}..${b.oid}`]);
	const files = await diffFiles(repo, base, b.oid);
	const behindOut = anc.code === 0 ? null : await git(repo, ["rev-list", "--count", `${base}..${target.oid}`]); // 統合済みの枝は進みを数えない
	const behind = Number(behindOut?.out.trim()) || 0;
	const overlap = behind > 0 ? await overlapOf(repo, base, target.oid, files) : NO_OVERLAP;
	const prKey = prKeyOf(b.branch);
	const summary: PrSummary = {
		repoId: repo.repoId,
		prKey,
		id: `${repo.repoId}/${prKey}`,
		repoName: repo.name,
		branch: b.branch,
		target: target.name,
		state: anc.code === 0 ? "merged" : "open",
		commits: Number(count.out.trim()) || 0,
		files: files.length,
		additions: files.reduce((s, f) => s + f.additions, 0),
		deletions: files.reduce((s, f) => s + f.deletions, 0),
		lastCommit: { oid: b.oid, subject: b.subject, author: b.author, at: b.at },
		sourceOid: b.oid,
		targetOid: target.oid,
		baseOid: base,
		behind,
		overlap,
	};
	const value = { summary, files };
	if (cache.size >= CACHE_MAX) cache.clear();
	cache.set(key, value);
	return value;
}

async function requireTarget(repo: Repo): Promise<{ name: string; oid: string }> {
	const t = await resolveTarget(repo);
	if (!t) throw new ApiError(404, "repo_unusable", "統合先のブランチが無いリポジトリです。");
	return t;
}

/** レビューの記録 (refs/pi/review/<prKey>) がある PR の prKey。読めないときは null (隠さない側に倒す) */
async function reviewedKeys(repo: Repo): Promise<Set<string> | null> {
	const r = await git(repo, ["for-each-ref", "--format=%(refname)", "refs/pi/review/"], true);
	if (r.code !== 0) return null;
	const keys = new Set<string>();
	for (const line of r.out.split("\n")) {
		const m = /^refs\/pi\/review\/(p[0-9a-f]{16})$/.exec(line.trim());
		if (m) keys.add(m[1]);
	}
	return keys;
}

async function listRepoPrs(repo: Repo): Promise<PrSummary[]> {
	const target = await resolveTarget(repo);
	if (!target) return []; // 使えないリポジトリは一覧に出さない
	const branches = (await listBranches(repo)).sort((a, b) => b.atUnix - a.atUnix).slice(0, MAX_PRS_PER_REPO);
	const reviewed = await reviewedKeys(repo);
	const out: PrSummary[] = [];
	for (const b of branches) {
		const c = await compute(repo, b, target);
		if (!c) continue;
		// 差分が無く (0 コミット。統合先と同じか祖先)、レビューの記録も無い枝は、PR として一覧に出さない (ID を直接指定すれば読める)。
		// 記録の有無を読めなかったとき (reviewed が null) は、隠さずに出す。
		if (c.summary.commits === 0 && reviewed && !reviewed.has(c.summary.prKey)) continue;
		out.push(c.summary);
	}
	return out;
}

async function findPr(repos: Repo[], repoId: string, prKey: string): Promise<{ repo: Repo; c: Computed; b: BranchRef }> {
	if (!/^r[0-9a-f]{8}$/.test(repoId) || !/^p[0-9a-f]{16}$/.test(prKey)) {
		throw new ApiError(400, "bad_id", "ID の形が正しくありません。");
	}
	const repo = repos.find((r) => r.repoId === repoId);
	if (!repo) throw notFound();
	const target = await requireTarget(repo);
	const b = (await listBranches(repo)).find((x) => prKeyOf(x.branch) === prKey);
	if (!b) throw notFound();
	const c = await compute(repo, b, target);
	if (!c) throw notFound();
	return { repo, c, b };
}

function checkPath(p: string | null): string {
	if (p === null || p === "") throw new ApiError(400, "bad_path", "path が必要です。");
	if (p.length > MAX_PATH_LEN) throw new ApiError(400, "bad_path", "path が長すぎます。");
	if (p.includes("\0") || p.includes("\n") || p.includes("\r") || p.startsWith("/") || p.split("/").includes("..")) {
		throw new ApiError(400, "bad_path", "path の形が正しくありません。");
	}
	return p;
}

async function commitsOf(repo: Repo, s: PrSummary): Promise<Commit[]> {
	const r = await git(repo, [
		"log",
		"-z",
		"--no-color",
		`--max-count=${MAX_COMMITS}`,
		"--format=%H%x1f%an%x1f%aI%x1f%s",
		`${s.targetOid}..${s.sourceOid}`,
	]);
	const out: Commit[] = [];
	for (const rec of r.out.split("\0")) {
		const f = rec.split("\x1f");
		if (f.length < 4 || !isOid(f[0])) continue;
		out.push({ oid: f[0], author: f[1], at: f[2], subject: f.slice(3).join("\x1f") });
	}
	return out;
}

async function fileDiff(
	repo: Repo,
	c: Computed,
	path: string,
): Promise<{ path: string; binary: boolean; truncated: boolean; hunks: Hunk[]; oldBlob: string | null; newBlob: string | null }> {
	const file = c.files.find((f) => f.path === path);
	if (!file) throw new ApiError(404, "not_in_diff", "このブランチの差分に含まれないファイルです。");
	const blobs = await blobsFor(repo, c.summary, file);
	if (file.binary) return { path, binary: true, truncated: false, hunks: [], ...blobs };
	const specs = file.oldPath !== null ? [file.oldPath, file.path] : [file.path];
	const r = await gitCapped(
		repo,
		[
			"diff",
			"--no-ext-diff",
			"--no-textconv",
			"--no-color",
			"-U3",
			"-M",
			c.summary.baseOid,
			c.summary.sourceOid,
			"--",
			...specs,
		],
		MAX_FILE_DIFF_BYTES,
	);
	let text = r.out;
	if (r.truncated) {
		// 途中の行は捨てて、完全な行までにする
		const cut = text.lastIndexOf("\n");
		text = cut >= 0 ? text.slice(0, cut + 1) : "";
	}
	return { path, binary: false, truncated: r.truncated, hunks: parseDiff(text), ...blobs };
}

function ctxOf(repo: Repo, c: Computed): PrCtx {
	const s = c.summary;
	return {
		repo,
		prKey: s.prKey,
		branch: s.branch,
		target: s.target,
		sourceOid: s.sourceOid,
		targetOid: s.targetOid,
		baseOid: s.baseOid,
		files: c.files,
	};
}

/** 書き込み API（POST）の入口。body は検査済みの JSON のオブジェクト。 */
export function isPostRoute(pathname: string): boolean {
	return /^\/api\/prs\/[^/]+\/[^/]+\/(?:comments|submit|merge-plan|merge)$/.test(pathname);
}

/** 統合系の POST（Origin 必須・--allow-merge が要る経路）。 */
export function isMergePostRoute(pathname: string): boolean {
	return /^\/api\/prs\/[^/]+\/[^/]+\/(?:merge-plan|merge)$/.test(pathname);
}

export async function handlePost(
	repos: Repo[],
	pathname: string,
	body: Record<string, unknown>,
	env: MergeEnv,
): Promise<PostResult> {
	const m = /^\/api\/prs\/([^/]+)\/([^/]+)\/(comments|submit|merge-plan|merge)$/.exec(pathname);
	if (!m) throw notFound();
	const { repo, c } = await findPr(repos, m[1], m[2]);
	const ctx = ctxOf(repo, c);
	if (m[3] === "merge-plan") return await mergePlan(ctx, c.summary, body, env);
	if (m[3] === "merge") return await mergeExecute(ctx, body, env);
	return { status: 201, body: m[3] === "comments" ? await postComment(ctx, body) : await postSubmit(ctx, body) };
}

/** API の入口。成功なら応答の本体、失敗なら ApiError を投げる。 */
export async function handleApi(repos: Repo[], pathname: string, query: URLSearchParams): Promise<unknown> {
	if (pathname === "/api/repos") {
		const out: Array<{ repoId: string; name: string; target: string; unpushed: number | null }> = [];
		for (const r of repos) {
			const t = await resolveTarget(r);
			if (t) out.push({ repoId: r.repoId, name: r.name, target: t.name, unpushed: await unpushedOf(r, t.name) });
		}
		return { repos: out };
	}
	if (pathname === "/api/prs") {
		const all: PrSummary[] = [];
		for (const r of repos) all.push(...(await listRepoPrs(r)));
		all.sort((a, b) => Date.parse(b.lastCommit.at) - Date.parse(a.lastCommit.at));
		return { prs: all };
	}
	const m = /^\/api\/prs\/([^/]+)\/([^/]+)(\/diff|\/review)?$/.exec(pathname);
	if (m) {
		if (m[3] === "/review") {
			const { repo, c } = await findPr(repos, m[1], m[2]);
			return await getReview(ctxOf(repo, c));
		}
		if (m[3] === undefined) {
			const { repo, c } = await findPr(repos, m[1], m[2]);
			return {
				pr: c.summary,
				commits: await commitsOf(repo, c.summary),
				files: c.files.slice(0, MAX_FILES),
				filesTruncated: c.files.length > MAX_FILES,
			};
		}
		const path = checkPath(query.get("path"));
		const { repo, c } = await findPr(repos, m[1], m[2]);
		return await fileDiff(repo, c, path);
	}
	throw notFound();
}
