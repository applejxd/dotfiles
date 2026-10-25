// シェルのコマンド文字列を、規則が使う単位 (単純コマンド) へ分ける (bashrules/shellparse.py の移植)。
//
// bash の完全な文法ではない。規則が要る範囲 (区切り・引用・エスケープ・リダイレクト) に絞る。
// `cd` の除去や `bash -c` の展開は normalize が担うので、ここは正規化済みのセグメントに当てる。
//
// node の型除去でそのまま動く書き方だけを使う。
// see docs/spec/guard/pi-decide.md#ts-版への移植

/** 1 語。`raw` は書かれたまま、`value` は引用とエスケープを外した値 (`$VAR` / `$(...)` は展開しない)。 */
export type Word = { readonly raw: string; readonly value: string };

export type Redirect = {
	/** 明示した fd (`2>` の `2`)。`&>` / `&>>` は `&`。無ければ空。 */
	readonly fd: string;
	/** `>` `>>` `>|` `>&` `<` `<<` `<<-` `<<<` `<&` `<>` のどれか。 */
	readonly op: string;
	/** 対象。fd の複製・クローズ (`2>&1` / `>&-`) と、対象が欠けた形は null。 */
	readonly target: Word | null;
};

export type Command = { readonly words: readonly Word[]; readonly redirects: readonly Redirect[] };

export const argv = (command: Command): string[] => command.words.map((w) => w.value);

const WRITE_OPS = new Set([">", ">>", ">|", ">&", "<>"]);
export const redirectWrites = (r: Redirect): boolean => r.target !== null && WRITE_OPS.has(r.op);

// 長いものを先に置く (前方一致で最初に当たったものを使う)
const SEPARATORS = ["&&", "||", "|&", ";;", ";", "|", "&", "\n", "(", ")"];
const REDIRECT_OPS = ["<<<", "<<-", "<<", "<>", "<&", ">>", ">|", ">&", "<", ">"];
const WORD_END = new Set(" \t\n;&|()<>");
// 単独の語として現れても実行するものを変えない記号
const GROUPING_WORDS = new Set(["{", "}", "!"]);

const isDigit = (c: string): boolean => /^\p{Nd}$/u.test(c);

/** シェルが `$` を展開する部分だけを残した `raw` (単引用符と `$'...'` の中身を除く)。 */
export function expandable(word: Word): string {
	const raw = word.raw;
	let out = "";
	let i = 0;
	const n = raw.length;
	let inDouble = false;
	while (i < n) {
		const ch = raw[i];
		if (ch === "\\" && i + 1 < n) {
			out += raw.slice(i, i + 2);
			i += 2;
			continue;
		}
		if (ch === "'" && !inDouble) {
			const end = raw.indexOf("'", i + 1);
			if (end !== -1) {
				i = end + 1;
				continue;
			}
		}
		if (ch === '"') inDouble = !inDouble;
		out += ch;
		i += 1;
	}
	return out;
}

/** `text` を単純コマンドの並びにする。区切り (`;` `&&` `|` 改行など) で分ける。 */
export function parse(text: string): Command[] {
	return new Parser(text).run();
}

class Parser {
	s: string;
	n: number;
	i = 0;
	commands: Command[] = [];
	words: Word[] = [];
	redirects: Redirect[] = [];

	constructor(text: string) {
		this.s = text;
		this.n = text.length;
	}

	run(): Command[] {
		const s = this.s;
		while (this.i < this.n) {
			const ch = s[this.i];
			if (ch === " " || ch === "\t") {
				this.i += 1;
				continue;
			}
			if (s.startsWith("\\\n", this.i)) {
				this.i += 2;
				continue;
			}
			if (ch === "#") {
				const end = s.indexOf("\n", this.i);
				this.i = end === -1 ? this.n : end;
				continue;
			}
			if (s.startsWith("<(", this.i) || s.startsWith(">(", this.i)) {
				const end = this.skipParens(this.i + 1);
				const text = s.slice(this.i, end);
				this.words.push({ raw: text, value: text });
				this.i = end;
				continue;
			}
			const redirect = this.redirect();
			if (redirect !== null) {
				this.redirects.push(redirect);
				continue;
			}
			const sep = SEPARATORS.find((op) => s.startsWith(op, this.i));
			if (sep !== undefined) {
				this.finish();
				this.i += sep.length;
				continue;
			}
			this.words.push(this.word());
		}
		this.finish();
		return this.commands;
	}

	finish(): void {
		const words = [...this.words];
		while (words.length > 0 && GROUPING_WORDS.has(words[0].raw)) words.shift();
		if (words.length > 0 || this.redirects.length > 0) {
			this.commands.push({ words, redirects: [...this.redirects] });
		}
		this.words = [];
		this.redirects = [];
	}

	redirect(): Redirect | null {
		const s = this.s;
		let j = this.i;
		while (j < this.n && isDigit(s[j])) j++;
		let fd = s.slice(this.i, j);
		if (!fd && s.startsWith("&>", j)) {
			fd = "&";
			j += 1;
		}
		const op = REDIRECT_OPS.find((o) => s.startsWith(o, j));
		if (op === undefined || (fd === "&" && op !== ">" && op !== ">>")) return null;
		this.i = j + op.length;
		while (this.i < this.n && (s[this.i] === " " || s[this.i] === "\t")) this.i++;
		let target: Word | null = null;
		if (this.i < this.n && !WORD_END.has(s[this.i])) target = this.word();
		if (
			(op === ">&" || op === "<&") &&
			target !== null &&
			((target.value !== "" && Array.from(target.value).every(isDigit)) || target.value === "-")
		) {
			target = null;
		}
		return { fd, op, target };
	}

	word(): Word {
		const s = this.s;
		const start = this.i;
		const value: string[] = [];
		let i = this.i;
		while (i < this.n) {
			const c = s[i];
			if (WORD_END.has(c)) break;
			if (c === "\\") {
				if (i + 1 >= this.n) {
					value.push(c);
					i += 1;
				} else if (s[i + 1] === "\n") {
					i += 2;
				} else {
					value.push(s[i + 1]);
					i += 2;
				}
				continue;
			}
			if (c === "'") {
				let end = s.indexOf("'", i + 1);
				end = end === -1 ? this.n : end;
				value.push(s.slice(i + 1, end));
				i = end + 1;
				continue;
			}
			if (c === '"') {
				i = this.doubleQuoted(i, value);
				continue;
			}
			if (s.startsWith("$'", i)) {
				const end = this.ansiCEnd(i + 2);
				value.push(s.slice(i + 2, end));
				i = end + 1;
				continue;
			}
			if (s.startsWith("$(", i)) {
				const end = this.skipParens(i + 1);
				value.push(s.slice(i, end));
				i = end;
				continue;
			}
			if (c === "`") {
				const end = this.skipBacktick(i);
				value.push(s.slice(i, end));
				i = end;
				continue;
			}
			value.push(c);
			i += 1;
		}
		if (i === start) {
			// 区切りの文字だけが残った形。進めないと呼び出し側が止まる
			value.push(s[i]);
			i += 1;
		}
		this.i = i;
		return { raw: s.slice(start, i), value: value.join("") };
	}

	/** `"` の中を読み、閉じ `"` の次の位置を返す。 */
	doubleQuoted(i: number, value: string[]): number {
		const s = this.s;
		let j = i + 1;
		while (j < this.n && s[j] !== '"') {
			if (s[j] === "\\" && j + 1 < this.n) {
				const nxt = s[j + 1];
				if ('"\\$`'.includes(nxt)) value.push(nxt);
				else if (nxt !== "\n") value.push(s.slice(j, j + 2));
				j += 2;
				continue;
			}
			if (s.startsWith("$(", j)) {
				const end = this.skipParens(j + 1);
				value.push(s.slice(j, end));
				j = end;
				continue;
			}
			if (s[j] === "`") {
				const end = this.skipBacktick(j);
				value.push(s.slice(j, end));
				j = end;
				continue;
			}
			value.push(s[j]);
			j += 1;
		}
		return Math.min(j + 1, this.n);
	}

	/** `$'...'` の閉じ `'` の位置 (`\'` は閉じない)。 */
	ansiCEnd(start: number): number {
		let j = start;
		while (j < this.n && this.s[j] !== "'") j += this.s[j] === "\\" ? 2 : 1;
		return Math.min(j, this.n);
	}

	/** `j` の `(` に対応する `)` の次の位置。引用の中の括弧は数えない。 */
	skipParens(start: number): number {
		const s = this.s;
		let j = start;
		let depth = 0;
		while (j < this.n) {
			const c = s[j];
			if (c === "\\") {
				j += 2;
				continue;
			}
			if (c === "'") {
				const end = s.indexOf("'", j + 1);
				j = end === -1 ? this.n : end + 1;
				continue;
			}
			if (c === '"') {
				j = this.doubleQuoted(j, []);
				continue;
			}
			if (c === "(") depth += 1;
			else if (c === ")") {
				depth -= 1;
				if (depth === 0) return j + 1;
			}
			j += 1;
		}
		return this.n;
	}

	/** `j` のバッククォートに対応する閉じの次の位置。 */
	skipBacktick(j: number): number {
		let k = j + 1;
		while (k < this.n && this.s[k] !== "`") k += this.s[k] === "\\" ? 2 : 1;
		return Math.min(k + 1, this.n);
	}
}
