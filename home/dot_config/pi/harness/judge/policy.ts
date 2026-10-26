// 判定器の設定と glob 照合 (command_policy.py の自己完結した部分の移植)。
//
// 設定は common.toml を JSON にしたもの (`Common`) を受け取る。TOML は読まない
// (配るときに Python の生成器が JSON にする。OpenCode の guide plugin の rules.json と同じ形)。
// 文字列の扱いと例外の種類は Python 版と同じにして、応答の理由まで一致させる。
//
// node の型除去 (strip-types) でそのまま動く書き方だけを使う (enum・namespace・parameter property を使わない)。
// see docs/spec/guard/pi-decide.md
import { homedir } from "node:os";
import { normalizeForCompare } from "./pathutil.ts";

/** Python の ValueError / TypeError に相当する。応答の理由に名前が出るので、名前まで揃える。 */
export class ValueError extends Error {
	constructor(message: string) {
		super(message);
		this.name = "ValueError";
	}
}
export class TypeErrorPy extends Error {
	constructor(message: string) {
		super(message);
		this.name = "TypeError";
	}
}

export type Common = Record<string, any>;

const isObject = (v: unknown): v is Record<string, any> =>
	v !== null && typeof v === "object" && !Array.isArray(v);

/** `[section] key` の文字列の配列。無ければ空。形が違えば TypeError (fail-closed)。 */
export function loadStrList(common: Common, section: string, key: string): string[] {
	const table = common[section] ?? {};
	if (!isObject(table)) throw new TypeErrorPy(`[${section}] セクションがテーブルではありません`);
	const value = table[key] ?? [];
	if (!Array.isArray(value)) {
		throw new TypeErrorPy(`[${section}] ${key} がリストではありません: ${pyTypeName(value)}`);
	}
	if (!value.every((v) => typeof v === "string")) {
		throw new TypeErrorPy(`[${section}] ${key} に文字列以外が含まれています`);
	}
	return [...value];
}

export function loadFileGlobs(common: Common, key: string): string[] {
	return loadStrList(common, "file", key);
}

export type DenyException = { deny: string; except: string[] };

export function loadReadDenyExceptions(common: Common): DenyException[] {
	const table = common.file ?? {};
	if (!isObject(table)) throw new TypeErrorPy("[file] セクションがテーブルではありません");
	const value = table.deny_exceptions ?? [];
	if (!Array.isArray(value)) throw new TypeErrorPy("[[file.deny_exceptions]] が配列ではありません");
	const out: DenyException[] = [];
	for (const entry of value) {
		const deny = isObject(entry) ? entry.deny : undefined;
		const globs = isObject(entry) ? entry.except : undefined;
		if (typeof deny !== "string" || !Array.isArray(globs) || !globs.every((g) => typeof g === "string")) {
			throw new TypeErrorPy("[[file.deny_exceptions]] は deny (文字列) と except (文字列の配列) が要ります");
		}
		out.push({ deny, except: [...globs] });
	}
	return out;
}

// ─── glob 照合 (permission の Read() / Edit() と同じ記法) ───────────────
// `**/` と `*` だけを解釈する。

const regexCache = new Map<string, RegExp>();

const escapeRegExp = (c: string): string => c.replace(/[.*+?^${}()|[\]\\/]/g, "\\$&");

export function globToRegex(glob: string, ignoreCase = false): RegExp {
	const cacheKey = `${ignoreCase ? "i" : "s"}:${glob}`;
	const cached = regexCache.get(cacheKey);
	if (cached) return cached;
	let out = "";
	let i = 0;
	while (i < glob.length) {
		if (glob.startsWith("**/", i)) {
			out += "(?:.*/)?";
			i += 3;
		} else if (glob.startsWith("**", i)) {
			out += ".*";
			i += 2;
		} else if (glob[i] === "*") {
			out += "[^/]*";
			i += 1;
		} else {
			// サロゲートペアを分けないよう、コードポイント単位で進める
			const cp = String.fromCodePoint(glob.codePointAt(i)!);
			out += escapeRegExp(cp);
			i += cp.length;
		}
	}
	const re = new RegExp(`^${out}$`, ignoreCase ? "iu" : "u");
	regexCache.set(cacheKey, re);
	return re;
}

const isWindows = (): boolean => process.platform === "win32";

/** `~` を ~ のホームに展開する (`~user` は展開しない。Python の expanduser と同じ範囲)。 */
export function expandUser(path: string): string {
	if (path === "~") return homedir();
	if (path.startsWith("~/") || (isWindows() && path.startsWith("~\\"))) return homedir() + path.slice(1);
	return path;
}

/** 最初に当たる glob。パスは区切りを `/` に揃えてから照合する。Windows では大小文字も区別しない。 */
export function matchesAnyGlob(
	path: string,
	globs: readonly string[],
	platform: string = process.platform,
	homeDir: string = homedir(),
): string | null {
	if (!path) return null;
	if (platform === "win32") return matchesAnyGlobWin(path, globs, homeDir);
	const ignoreCase = isWindows();
	let normalized = path.replaceAll("\\", "/");
	while (normalized.startsWith("./")) normalized = normalized.slice(2);
	const candidates = [normalized];
	const home = homeDir.replaceAll("\\", "/");
	const check = ignoreCase ? (s: string) => s.toLowerCase() : (s: string) => s;
	if (home && check(normalized).startsWith(`${check(home)}/`)) {
		candidates.push(`~/${normalized.slice(home.length + 1)}`);
	}
	for (const glob of globs) {
		const pattern = globToRegex(glob, ignoreCase);
		if (candidates.some((c) => pattern.test(c))) return glob;
	}
	return null;
}

/** win32: MSYS・Windows 形式・`$HOME` のどれで書いても、ホーム固定 (`~/`) の glob に当たるようにする。 */
function matchesAnyGlobWin(path: string, globs: readonly string[], homeDir: string): string | null {
	let n = normalizeForCompare(path, "win32");
	while (n.startsWith("./")) n = n.slice(2);
	const candidates = [n];
	const home = normalizeForCompare(homeDir, "win32").replace(/\/+$/, "");
	if (home && n.startsWith(`${home}/`)) candidates.push(`~/${n.slice(home.length + 1)}`);
	for (const prefix of ["$home/", "${home}/"]) {
		if (n.startsWith(prefix)) candidates.push(`~/${n.slice(prefix.length)}`);
	}
	for (const glob of globs) {
		const pattern = globToRegex(glob, true);
		if (candidates.some((c) => pattern.test(c))) return glob;
	}
	return null;
}

/** read_deny_globs に当たる最初の glob。例外は対の deny にだけ効く。 */
export function matchesReadDeny(
	path: string,
	globs: readonly string[],
	exceptions: readonly DenyException[] = [],
	platform: string = process.platform,
	homeDir: string = homedir(),
): string | null {
	for (const glob of globs) {
		if (!matchesAnyGlob(path, [glob], platform, homeDir)) continue;
		if (exceptions.some((e) => e.deny === glob && matchesAnyGlob(path, e.except, platform, homeDir))) continue;
		return glob;
	}
	return null;
}

/** Python の type(x).__name__ に近い名前 (エラーメッセージの一致のため)。 */
export function pyTypeName(value: unknown): string {
	if (value === null || value === undefined) return "NoneType";
	if (typeof value === "string") return "str";
	if (typeof value === "number") return Number.isInteger(value) ? "int" : "float";
	if (typeof value === "boolean") return "bool";
	if (Array.isArray(value)) return "list";
	return "dict";
}
