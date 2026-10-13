// Python 標準の文字列・正規表現・shlex の挙動を TS で再現する部品。
//
// 判定器は Python 版の振る舞いを 1 文字まで揃えて移す (正解データとの全件一致が完了条件)。
// そのため、JS の `\s` `\b` `\w` や `String.prototype.trim` ではなく、Python と同じ範囲を使う。
// node の型除去でそのまま動く書き方だけを使う。
// see docs/spec/pi-decide.md#ts-版への移植

/** Python の `str.isspace()` が真になる文字 (`str.split()` / `strip()` が空白とみなす範囲)。 */
const WS_CLASS = " \\t\\n\\r\\f\\v\\x1c-\\x1f\\x85\\xa0\\u1680\\u2000-\\u200a\\u2028\\u2029\\u202f\\u205f\\u3000";
const WORD_CLASS = "\\p{L}\\p{N}_";

const WS_RE = new RegExp(`^[${WS_CLASS}]$`, "u");
export const isSpace = (ch: string): boolean => WS_RE.test(ch);

const LEADING_WS = new RegExp(`^[${WS_CLASS}]+`, "u");
const TRAILING_WS = new RegExp(`[${WS_CLASS}]+$`, "u");
const WS_RUN = new RegExp(`[${WS_CLASS}]+`, "u");

/** `s.strip()` */
export const strip = (s: string): string => s.replace(LEADING_WS, "").replace(TRAILING_WS, "");

/** `s.strip(chars)` (chars に含まれる文字を両端から落とす) */
export function stripChars(s: string, chars: string, left = true, right = true): string {
	const set = new Set(Array.from(chars));
	const cps = Array.from(s);
	let a = 0;
	let b = cps.length;
	if (left) while (a < b && set.has(cps[a])) a++;
	if (right) while (b > a && set.has(cps[b - 1])) b--;
	return cps.slice(a, b).join("");
}

/** `s.split()` (引数なし: 空白の連続で分け、空要素を作らない) */
export function split(s: string): string[] {
	return strip(s) === "" ? [] : strip(s).split(new RegExp(`[${WS_CLASS}]+`, "u"));
}

/** `s.split(None, 1)` (先頭の空白を落とし、最初の語と残りに分ける。残りの末尾の空白は残る) */
export function splitOnce(s: string): string[] {
	const t = s.replace(LEADING_WS, "");
	if (t === "") return [];
	const m = WS_RUN.exec(t);
	if (!m) return [t];
	const rest = t.slice(m.index + m[0].length);
	return rest === "" ? [t.slice(0, m.index)] : [t.slice(0, m.index), rest];
}

/** `s.splitlines()` */
export function splitLines(s: string): string[] {
	const out: string[] = [];
	let cur = "";
	for (let i = 0; i < s.length; i++) {
		const c = s[i];
		if (c === "\r" && s[i + 1] === "\n") {
			out.push(cur);
			cur = "";
			i++;
		} else if ("\n\r\v\f\x1c\x1d\x1e\x85\u2028\u2029".includes(c)) {
			out.push(cur);
			cur = "";
		} else {
			cur += c;
		}
	}
	if (cur !== "") out.push(cur);
	return out;
}

/** `s.rsplit("/", 1)[-1]` 相当 (パスの最後の要素) */
export const basename = (token: string): string => {
	const i = token.lastIndexOf("/");
	return i < 0 ? token : token.slice(i + 1);
};

/** Python の `len(str)` (コードポイントの数) */
export const pyLen = (s: string): number => Array.from(s).length;

/** `shlex.quote(s)` */
export function shlexQuote(s: string): string {
	if (s === "") return "''";
	if (!/[^A-Za-z0-9_@%+=:,./-]/.test(s)) return s;
	return `'${s.replaceAll("'", "'\"'\"'")}'`;
}

// ─── 正規表現 (Python の re と同じ意味にする) ───────────────────────────
// Python の `\s` `\S` `\w` `\d` `\b` は Unicode 対応。JS は ASCII だけなので、書き換えて `u` フラグで使う。
// 書き換えるのは、文字クラスの外・中の `\s` `\w` `\d` `\b` と、文字クラスの外の `\S`。

const BOUNDARY =
	`(?:(?<![${WORD_CLASS}])(?=[${WORD_CLASS}])|(?<=[${WORD_CLASS}])(?![${WORD_CLASS}]))`;

export function pyRegex(source: string, flags = ""): RegExp {
	let out = "";
	let inClass = false;
	for (let i = 0; i < source.length; i++) {
		const c = source[i];
		if (c === "\\") {
			const n = source[i + 1];
			i++;
			if (n === "s") out += inClass ? WS_CLASS : `[${WS_CLASS}]`;
			else if (n === "S") {
				if (inClass) throw new Error("文字クラスの中の \\S は未対応");
				out += `[^${WS_CLASS}]`;
			} else if (n === "w") out += inClass ? WORD_CLASS : `[${WORD_CLASS}]`;
			else if (n === "d") out += "\\p{Nd}";
			else if (n === "b") out += inClass ? "\\x08" : BOUNDARY;
			else out += `\\${n}`;
			continue;
		}
		if (c === "[" && !inClass) inClass = true;
		else if (c === "]" && inClass) inClass = false;
		out += c;
	}
	return new RegExp(out, flags.includes("u") ? flags : `${flags}u`);
}

// ─── shlex.split (POSIX モード、コメントなし) ───────────────────────────

export class ShlexError extends Error {
	constructor(message: string) {
		super(message);
		this.name = "ValueError";
	}
}

const SHLEX_WHITESPACE = " \t\r\n";

/** `shlex.split(s)`。引用が閉じない・末尾が `\` のときは ValueError と同じ ShlexError を投げる。 */
export function shlexSplit(s: string): string[] {
	const tokens: string[] = [];
	let token = "";
	let quoted = false;
	let state = " "; // " " 空白 / "a" 語の途中 / "'" `"` 引用の中 / "\\" エスケープの直後
	let escapedState = " ";
	const emit = () => {
		if (token !== "" || quoted) tokens.push(token);
		token = "";
		quoted = false;
	};
	for (const ch of s) {
		if (state === " ") {
			if (SHLEX_WHITESPACE.includes(ch)) {
				emit();
			} else if (ch === "\\") {
				escapedState = "a";
				state = ch;
			} else if (ch === "'" || ch === '"') {
				state = ch;
			} else {
				token = ch;
				state = "a";
			}
		} else if (state === "'" || state === '"') {
			quoted = true;
			if (ch === state) {
				state = "a";
			} else if (ch === "\\" && state === '"') {
				escapedState = state;
				state = ch;
			} else {
				token += ch;
			}
		} else if (state === "\\") {
			// 引用の中では、引用符自身とエスケープ文字だけがエスケープできる (それ以外は `\` も残す)
			if ((escapedState === "'" || escapedState === '"') && ch !== state && ch !== escapedState) {
				token += state;
			}
			token += ch;
			state = escapedState;
		} else {
			// state === "a"
			if (SHLEX_WHITESPACE.includes(ch)) {
				state = " ";
				emit();
			} else if (ch === "'" || ch === '"') {
				state = ch;
			} else if (ch === "\\") {
				escapedState = "a";
				state = ch;
			} else {
				token += ch;
			}
		}
	}
	if (state === "'" || state === '"') throw new ShlexError("No closing quotation");
	if (state === "\\") throw new ShlexError("No escaped character");
	emit();
	return tokens;
}
