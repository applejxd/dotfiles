// パスの扱い (Python の os.path 相当)。判定器の各所で共有する。
// node の型除去でそのまま動く書き方だけを使う。
// see docs/spec/guard/pi-decide.md#ts-版への移植
import { lstatSync, readlinkSync, realpathSync } from "node:fs";
import { homedir } from "node:os";
import { isAbsolute, join, normalize, sep } from "node:path";

export { isAbsolute, join, sep };

/** `os.path.normpath` (末尾の `/` を落とす)。 */
export function normpath(path: string): string {
	const n = normalize(path);
	return n.length > 1 && n.endsWith(sep) ? n.slice(0, -1) : n;
}

/** `os.path.realpath` (存在しない後ろの部分はそのまま残す)。 */
export function realpathLoose(path: string): string {
	let head = path;
	let tail = "";
	for (;;) {
		try {
			const real = realpathSync(head);
			return tail ? join(real, tail) : real;
		} catch {
			const slash = head.lastIndexOf(sep);
			if (slash <= 0) return path;
			tail = tail ? `${head.slice(slash + 1)}${sep}${tail}` : head.slice(slash + 1);
			head = head.slice(0, slash);
		}
	}
}

/**
 * 厳格な解決: 先頭から成分を辿り、存在する symlink は (対象が無くても) 文字列として置き換えて続ける。
 * 深さの上限 (40) を超える・lstat が ENOENT 以外で失敗するときは例外 (呼び出し側が deny にする)。
 */
export function strictResolve(path: string): string {
	let queue = path.split(sep); // normpath しない (`f/..` や `link/..` を字句で畳むと実体と食い違う)
	let resolved = sep;
	let hops = 0;
	while (queue.length > 0) {
		const comp = queue.shift()!;
		if (comp === "" || comp === ".") continue;
		if (comp === "..") {
			resolved = resolved === sep ? sep : resolved.slice(0, resolved.lastIndexOf(sep)) || sep;
			continue;
		}
		const next = join(resolved, comp);
		let link: string | null = null;
		try {
			const st = lstatSync(next);
			if (st.isSymbolicLink()) link = readlinkSync(next);
			else if (!st.isDirectory() && queue.some((c) => c !== "" && c !== ".")) throw new Error("通常ファイルの後に成分が続く");
		} catch (e: any) {
			if (e?.code !== "ENOENT") throw e;
		}
		if (link === null) {
			resolved = next;
			continue;
		}
		if (++hops > 40) throw new Error("symlink が深すぎる");
		if (isAbsolute(link)) resolved = sep;
		queue = [...link.split(sep), ...queue];
	}
	return resolved;
}

/** `os.path.expanduser` (`~` と `~/` だけを展開する)。 */
export function expandUser(path: string): string {
	if (path === "~") return homedir();
	if (path.startsWith("~/") || (process.platform === "win32" && path.startsWith("~\\"))) {
		return homedir() + path.slice(1);
	}
	return path;
}

/**
 * win32 のとき、比較用にパスを揃える: MSYS・WSL 形式 (`/c/..`・`/cygdrive/c/..`・`/mnt/c/..`) → `c:/..`、`\` → `/`、小文字化。
 * それ以外の platform では何もしない。`platform` は試験で差し替える。
 */
export function normalizeForCompare(path: string, platform: string = process.platform): string {
	if (platform !== "win32") return path;
	return path
		.replaceAll("\\", "/")
		.replace(/^\/(?:cygdrive\/|mnt\/)?([A-Za-z])(?=\/|$)/, "$1:")
		.toLowerCase();
}

/** `os.path.normcase` (Windows では小文字にして `/` へ寄せる。それ以外は何もしない)。 */
export const normcase = (path: string): string =>
	process.platform === "win32" ? path.replaceAll("/", "\\").toLowerCase() : path;
