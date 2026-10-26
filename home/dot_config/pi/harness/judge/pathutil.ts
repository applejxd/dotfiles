// パスの扱い (Python の os.path 相当)。判定器の各所で共有する。
// node の型除去でそのまま動く書き方だけを使う。
// see docs/spec/guard/pi-decide.md#ts-版への移植
import { realpathSync } from "node:fs";
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
