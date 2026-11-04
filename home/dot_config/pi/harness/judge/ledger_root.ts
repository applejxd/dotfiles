// 作業台帳の置き場の実体を、cwd から fs だけで解く (プロセスは起動しない)。
//
// 保存側 (work/root.ts) は `git rev-parse --git-common-dir` の `<common>/pi-work` を使うので、
// `.git` 以外の名前の common-dir (`--separate-git-dir`・`GIT_DIR`) では名前の正規表現に当たらない。
// その実体を求め、判定器が名前の照合に加えて照合する。読めない・不正な形は例外にせず、解決できた分だけ返す。
// node の型除去でそのまま動く書き方だけを使う。
// see docs/spec/work/store.md#保護
import { existsSync, readFileSync, statSync } from "node:fs";
import { dirname, isAbsolute, join, normalize, resolve, sep } from "node:path";
import { realpathLoose } from "./pathutil.ts";

const CACHE_MAX = 64;
const cache = new Map<string, string[]>();

/** 文字列の先頭行 (改行を除く) だけを読む。読めなければ null。 */
function readLine(path: string): string | null {
	try {
		return readFileSync(path, "utf8").split(/\r?\n/u)[0].trim();
	} catch {
		return null;
	}
}

/** gitdir (worktree なら `commondir` を持つ) から common-dir を求める。`commondir` が自分を指す・読めない形は gitdir 自身。 */
function commonOf(gitdir: string): string {
	const rel = readLine(join(gitdir, "commondir"));
	if (!rel) return gitdir;
	const common = resolve(gitdir, rel);
	return common === resolve(gitdir) ? gitdir : common;
}

/** `.git` (ディレクトリまたは `gitdir: <path>` のファイル) から gitdir を求める。解けなければ null。 */
function gitdirOf(dotGit: string): string | null {
	try {
		const st = statSync(dotGit);
		if (st.isDirectory()) return dotGit;
		if (!st.isFile()) return null;
		const m = /^gitdir:\s*(.+)$/u.exec(readLine(dotGit) ?? "");
		if (!m) return null;
		return resolve(dirname(dotGit), m[1].trim());
	} catch {
		return null;
	}
}

function resolveRoots(cwd: string, env: Record<string, string | undefined>): string[] {
	const commons: string[] = [];
	// cwd から上へ `.git` を探す (上限 64 階層。循環しない)
	let dir = resolve(cwd);
	for (let depth = 0; depth < 64; depth++) {
		const dotGit = join(dir, ".git");
		if (existsSync(dotGit)) {
			const gitdir = gitdirOf(dotGit);
			if (gitdir) commons.push(commonOf(gitdir));
			break;
		}
		const parent = dirname(dir);
		if (parent === dir) break;
		dir = parent;
	}
	const abs = (p: string): string => (isAbsolute(p) ? normalize(p) : resolve(cwd, p));
	if (env.GIT_COMMON_DIR) commons.push(abs(env.GIT_COMMON_DIR));
	if (env.GIT_DIR) commons.push(commonOf(abs(env.GIT_DIR)));
	const roots = commons.map((c) => join(c, "pi-work"));
	roots.push(join(resolve(cwd), ".tmp", "work"));
	// symlink を解いた実体も加える (照合する側の形が実体になる場合)
	const real = roots.map((r) => realpathLoose(r));
	return [...new Set([...roots, ...real].map((r) => (r.length > 1 && r.endsWith(sep) ? r.slice(0, -1) : r)))];
}

/**
 * cwd から求めた台帳の置き場 (`<common-dir>/pi-work` と cwd 直下の `.tmp/work`)。例外を投げない。
 * 結果は (cwd, GIT_DIR, GIT_COMMON_DIR) ごとに最大 64 件キャッシュする。
 */
export function ledgerRoots(cwd: string, env: Record<string, string | undefined> = process.env): string[] {
	const key = `${cwd}\0${env.GIT_DIR ?? ""}\0${env.GIT_COMMON_DIR ?? ""}`;
	const hit = cache.get(key);
	if (hit) return hit;
	let roots: string[];
	try {
		roots = resolveRoots(cwd, env);
	} catch {
		roots = [];
	}
	if (cache.size >= CACHE_MAX) cache.delete(cache.keys().next().value as string);
	cache.set(key, roots);
	return roots;
}

/** テスト用: キャッシュの件数と消去。 */
export function ledgerRootsCacheSize(): number {
	return cache.size;
}

/** `path` (絶対・正規化済み) が、台帳の置き場そのもの、またはその配下か (成分境界つき)。 */
export function underLedgerRoot(path: string, roots: string[]): boolean {
	return roots.some((r) => path === r || path.startsWith(r.endsWith(sep) ? r : r + sep));
}
