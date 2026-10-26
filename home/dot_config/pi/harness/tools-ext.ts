// guarded_* の説明の上書き・read の tail・write の append・読みの失敗のヒント・誘導 deny の言い換え。
// see docs/spec/guard/pi-guard.md
//
// node の型除去でそのまま動く書き方だけを使う (enum・namespace は使わない)。pi 本体は import しない。
import { appendFile, mkdir, open, readFile, stat } from "node:fs/promises";
import { readdirSync } from "node:fs";
import { expandTilde } from "./platform.ts";
import { basename, dirname, isAbsolute, join, resolve } from "node:path";

// ─── ツールの説明 (A) ───────────────────────────────────────────────

export type ToolText = { description?: string; promptSnippet: string; promptGuidelines: string[] };

/**
 * 登録するツールの description / promptSnippet / promptGuidelines の上書き。P は名前の接頭辞 (`guarded_`)。
 * description は組み込みの文 (def.description) の後ろに足す。無い道具は null (組み込みのまま)。
 */
export function toolText(tool: string, P: string, def: { description?: string; promptGuidelines?: string[] }): ToolText | null {
	const base = def.description ? `${def.description} ` : "";
	switch (tool) {
		case "bash":
			return {
				description:
					`${base}Use it to run things: builds, tests, git, package managers, and grep/find/ls. ` +
					`Do NOT use it to read, create, or change file contents: use ${P}read instead of cat/head/tail/sed -n (offset/limit for a range, tail for the last N lines), ` +
					`${P}write instead of echo > / cat > f <<EOF / tee (append: true to append), and ${P}edit instead of sed/awk edits. ` +
					`To read several files, make parallel ${P}read calls instead of chaining them in one command. ` +
					`Waits of 10 seconds or more (sleep) and background jobs (&, nohup) go through bg_run. ` +
					`Exception: git commit and gh issue comment go through ${P}action when ${P}action is available (it asks for approval itself).`,
				promptSnippet: "Run shell commands (build, test, git; search with grep/find/ls). Not for reading or writing file contents",
				promptGuidelines: [
					...(def.promptGuidelines ?? []),
					`Do not use ${P}bash to read, create, or change file contents. cat/head/tail/sed -n -> ${P}read (offset/limit for a range, tail for the last N lines); echo >, cat > f <<EOF, tee -> ${P}write (append: true to append); sed/awk edits -> ${P}edit.`,
					`To read several files, make parallel ${P}read calls; do not concatenate them in one ${P}bash command.`,
					`Run waits of 10 seconds or more (sleep) and background jobs (&, nohup) with bg_run, not ${P}bash.`,
					`Exception to running git in ${P}bash: git commit and gh issue comment use ${P}action (when ${P}action is available), not ${P}bash.`,
				],
			};
		case "read":
			return {
				description:
					`${base}Use it instead of cat/head/tail/sed -n. Range: offset (1-indexed line) and limit; the last N lines: tail (not with offset). ` +
					`Read only the range you need (saves tokens). To read several files, make parallel ${P}read calls.`,
				promptSnippet: "Read file contents (offset/limit for a range, tail for the last N lines)",
				promptGuidelines: [
					`Use ${P}read instead of cat/head/tail/sed -n: offset (1-indexed) and limit for a range, tail for the last N lines. Read only the range you need.`,
					`To read several files, make parallel ${P}read calls instead of one ${P}bash command.`,
				],
			};
		case "write":
			return {
				description:
					`${base}Use it for new files and complete rewrites. For a partial change to an existing file use ${P}edit (fewer tokens than rewriting the whole file). ` +
					`To add to the end of a file, set append: true: content is concatenated as is, with no newline added. ` +
					`You handle newlines: if the file does not end with a newline, start content with one.`,
				promptSnippet: "Create a file or rewrite it completely (append: true adds to the end)",
				promptGuidelines: [
					`Use ${P}write for new files and complete rewrites. Use ${P}edit for partial changes (fewer tokens). Use append: true to add to the end of a file; no newline is added, so start content with one if the file does not end with a newline.`,
				],
			};
		case "edit":
			return {
				description:
					`${base}Use it for any partial change to an existing file (fewer tokens than rewriting it with ${P}write). ` +
					`Put several separate changes to one file into one call as edits[]. Each oldText must match exactly one place in the original file. ` +
					`Do not edit files with sed/awk.`,
				promptSnippet: "Make precise file edits with exact text replacement, including multiple disjoint edits in one call",
				promptGuidelines: [
					`Use ${P}edit for partial changes to a file (edits[].oldText must match exactly one place in the original file). Do not edit with sed/awk.`,
					`When changing several separate places in one file, put them in edits[] of one ${P}edit call instead of several calls. ` +
					`Do not put several ${P}edit calls for the same file in one response: they are applied one after another, so a later oldText can stop matching.`,
				],
			};
		case "grep":
			return {
				promptSnippet: "Search file contents for patterns (respects .gitignore)",
				promptGuidelines: [`Use ${P}grep to search file contents; independent searches can be made as parallel ${P}grep calls.`],
			};
		case "find":
			return {
				promptSnippet: "Find files by glob pattern (respects .gitignore)",
				promptGuidelines: [`Use ${P}find to find files by name; independent searches can be made as parallel ${P}find calls.`],
			};
		case "ls":
			return {
				promptSnippet: "List directory contents",
				promptGuidelines: [`Use ${P}ls to list a directory; to read a file use ${P}read, not ${P}bash.`],
			};
		default:
			return null;
	}
}

// ─── スキーマ ───────────────────────────────────────────────────────

/** guarded_read の引数。tail の 1 以上の整数は実行時に確かめる (厳格なスキーマの対応差を避ける)。 */
export function readParameters(Type: any): any {
	return Type.Object({
		path: Type.String({ description: "Path to the file to read (relative or absolute)" }),
		offset: Type.Optional(Type.Number({ description: "Line number to start reading from (1-indexed). Not with tail" })),
		limit: Type.Optional(Type.Number({ description: "Maximum number of lines to read" })),
		tail: Type.Optional(Type.Integer({ description: "Read the last N lines (N >= 1). Not with offset; limit is ignored. Not for images or files over 32 MiB" })),
	});
}

/** guarded_write の引数。 */
export function writeParameters(Type: any): any {
	return Type.Object({
		path: Type.String({ description: "Path to the file to write (relative or absolute)" }),
		content: Type.String({ description: "Content to write to the file" }),
		append: Type.Optional(
			Type.Boolean({ description: "Add content to the end of the file as is (no newline is added; creates the file if missing) instead of overwriting" }),
		),
	});
}

/** append: true 用の書き込み (組み込みの write の operations に差す。mutation queue と親ディレクトリの作成は組み込みのまま)。 */
export function appendOperations() {
	return {
		writeFile: (absolutePath: string, content: string) => appendFile(absolutePath, content, "utf-8"),
		mkdir: (dir: string) => mkdir(dir, { recursive: true }).then(() => {}),
	};
}

/** append の結果の文言 (組み込みは「Successfully wrote to」と出すので、追記だと分かる形に直す)。 */
export function appendResult(result: any, path: string, chars: number): any {
	if (!result || !Array.isArray(result.content)) return result;
	const content = result.content.map((b: any) => (b?.type === "text" ? { ...b, text: `Successfully appended ${chars} chars to ${path}` } : b));
	return { ...result, content };
}

// ─── read の tail と、失敗のヒント ─────────────────────────────────

export const TAIL_MAX_BYTES = 32 * 1024 * 1024;

/** pi の read と同じ向きで、相対パスを cwd で解く (~ と先頭の @ だけ扱う)。 */
export function resolveInputPath(p: string, cwd: string, home?: string): string {
	let s = p.startsWith("@") ? p.slice(1) : p;
	s = expandTilde(s, home);
	return resolve(cwd, s);
}

/** 行数。改行の数に、最後の行が改行で終わらなければ 1 を足す (空ファイルは 0)。 */
export async function countLines(absPath: string): Promise<number> {
	const fh = await open(absPath, "r");
	try {
		const buf = Buffer.alloc(64 * 1024);
		let newlines = 0;
		let lastByte = 0x0a;
		let any = false;
		for (;;) {
			const { bytesRead } = await fh.read(buf, 0, buf.length, null);
			if (bytesRead === 0) break;
			any = true;
			for (let i = 0; i < bytesRead; i++) if (buf[i] === 0x0a) newlines++;
			lastByte = buf[bytesRead - 1];
		}
		return any && lastByte !== 0x0a ? newlines + 1 : newlines;
	} finally {
		await fh.close();
	}
}

function editDistance(a: string, b: string): number {
	const prev = Array.from({ length: b.length + 1 }, (_, j) => j);
	for (let i = 1; i <= a.length; i++) {
		let diag = prev[0];
		prev[0] = i;
		for (let j = 1; j <= b.length; j++) {
			const tmp = prev[j];
			prev[j] = Math.min(prev[j] + 1, prev[j - 1] + 1, diag + (a[i - 1] === b[j - 1] ? 0 : 1));
			diag = tmp;
		}
	}
	return prev[b.length];
}

/** 名前が似たもの (大文字小文字の違い・前方一致・編集距離が小さい) を、近い順に最大 max 件。 */
export function similarNames(entries: readonly string[], target: string, max = 3): string[] {
	const t = target.toLowerCase();
	const limit = t.length <= 4 ? 1 : 2;
	const scored: { name: string; score: number }[] = [];
	for (const name of entries) {
		if (name === target) continue;
		const n = name.toLowerCase();
		let score = -1;
		if (n === t) score = 0;
		else if (Math.min(n.length, t.length) >= 3 && (n.startsWith(t) || t.startsWith(n))) score = 1;
		else {
			const d = editDistance(n, t);
			if (d <= limit) score = 1 + d;
		}
		if (score >= 0) scored.push({ name, score });
	}
	scored.sort((x, y) => x.score - y.score || x.name.localeCompare(y.name));
	return scored.slice(0, max).map((s) => s.name);
}

export type ReadHooks = {
	cwd: string;
	/** 読んでよいか (判定器の `read` が allow か)。deny / ask の名前は提案しない */
	canRead: (absPath: string) => boolean;
};

/** 失敗の文面に役立つ情報を足した例外へ直す。元のメッセージは残す。足せなければ元の例外のまま。 */
export function decorateReadError(e: unknown, path: string, hooks: ReadHooks): unknown {
	try {
		const msg = e instanceof Error ? e.message : String(e);
		const extra: string[] = [];
		const m = /^Offset (\d+) is beyond end of file \((\d+) lines total\)/.exec(msg);
		if (m) extra.push(`有効な offset は 1〜${m[2]} (末尾の N 行は tail: N)`);
		if ((e as any)?.code === "ENOENT" || /ENOENT/.test(msg)) {
			const abs = resolveInputPath(path, hooks.cwd);
			const names = similarNames(readdirSync(dirname(abs)), basename(abs), 10).filter((n) => hooks.canRead(join(dirname(abs), n))).slice(0, 3);
			if (names.length > 0) extra.push(`似たファイル: ${names.join(", ")}`);
		}
		if (extra.length === 0) return e;
		const err = new Error(`${msg}\n${extra.join("\n")}`, { cause: e });
		if ((e as any)?.code !== undefined) (err as any).code = (e as any).code;
		return err;
	} catch {
		return e;
	}
}

/**
 * guarded_read の実行。tail は offset / limit へ直して組み込みの def.execute を呼ぶ。
 * 判定は path だけに掛かるので、判定の後で引数を直してよい。
 */
export async function runRead(
	def: { execute: (...a: any[]) => Promise<any> },
	toolCallId: string,
	params: any,
	signal: any,
	onUpdate: any,
	ctx: any,
	hooks: ReadHooks,
): Promise<any> {
	const path = String(params?.path ?? "");
	let p = params;
	const tailGiven = params?.tail !== undefined && params?.tail !== null;
	if (tailGiven) {
		const tail = params.tail;
		if (!Number.isInteger(tail) || tail < 1) throw new Error("tail must be an integer of 1 or more");
		if (params.offset !== undefined && params.offset !== null) {
			throw new Error("tail and offset cannot be used together. Use tail alone for the last N lines, or offset (and limit) for a range.");
		}
		const abs = resolveInputPath(path, ctx?.cwd || hooks.cwd);
		let size: number | null = null;
		try {
			const st = await stat(abs);
			if (st.isFile()) size = st.size;
		} catch {
			// 無い・読めないときは、組み込みの read に同じ失敗を出させる (tail は付けずに渡す)
		}
		if (size === null) p = { path };
		else {
			if (size > TAIL_MAX_BYTES) {
				throw new Error(`tail cannot be used on files over 32 MiB (${size} bytes). Use offset and limit instead (e.g. offset: <line>, limit: 200).`);
			}
			const total = await countLines(abs);
			p = { path, offset: Math.max(1, total - tail + 1), limit: tail };
		}
	} else if (params && "tail" in params) {
		p = { path: params.path, offset: params.offset, limit: params.limit };
	}
	let result: any;
	try {
		result = await def.execute(toolCallId, p, signal, onUpdate, ctx);
	} catch (e) {
		throw decorateReadError(e, path, { ...hooks, cwd: ctx?.cwd || hooks.cwd });
	}
	if (tailGiven && Array.isArray(result?.content) && result.content.some((b: any) => b?.type === "image")) {
		throw new Error("tail cannot be used on image files. Read the file without tail.");
	}
	return result;
}

// ─── 誘導の deny の言い換え (G) ─────────────────────────────────────

type Frag = { text: string; complex: boolean };

/** 引用の外の `&&` と `;` で分ける。パイプ・リダイレクト・`&`・括弧などを含む断片は complex。 */
function scan(line: string): Frag[] {
	const out: Frag[] = [];
	let cur = "";
	let complex = false;
	let q: string | null = null;
	const push = () => {
		const t = cur.trim();
		if (t) out.push({ text: t, complex });
		cur = "";
		complex = false;
	};
	for (let i = 0; i < line.length; i++) {
		const c = line[i];
		if (q) {
			cur += c;
			if (c === q) q = null;
			else if (c === "\\" && q === '"' && i + 1 < line.length) cur += line[++i];
			continue;
		}
		if (c === "'" || c === '"') {
			q = c;
			cur += c;
			continue;
		}
		if (c === "\\" && i + 1 < line.length) {
			cur += c + line[++i];
			continue;
		}
		if (c === "#" && (cur === "" || /\s$/.test(cur))) break;
		if (c === ";") {
			push();
			continue;
		}
		if (c === "&" && line[i + 1] === "&") {
			push();
			i++;
			continue;
		}
		if ("|<>&`(){}$".includes(c)) complex = true;
		cur += c;
	}
	if (q) return [{ text: line.trim(), complex: true }];
	push();
	return out;
}

/** シェルの語に分ける。展開・グロブ・括弧を含むときは null (言い換えを付けない)。 */
function tokenize(s: string): string[] | null {
	const toks: string[] = [];
	let cur = "";
	let has = false;
	for (let i = 0; i < s.length; i++) {
		const c = s[i];
		if (c === "'") {
			const end = s.indexOf("'", i + 1);
			if (end < 0) return null;
			cur += s.slice(i + 1, end);
			has = true;
			i = end;
		} else if (c === '"') {
			let j = i + 1;
			for (; j < s.length && s[j] !== '"'; j++) {
				if (s[j] === "$" || s[j] === "`") return null;
				if (s[j] === "\\" && j + 1 < s.length) j++;
				cur += s[j];
			}
			if (j >= s.length) return null;
			has = true;
			i = j;
		} else if (c === "\\") {
			if (i + 1 >= s.length) return null;
			cur += s[++i];
			has = true;
		} else if (/\s/.test(c)) {
			if (has) toks.push(cur);
			cur = "";
			has = false;
		} else if ("$`*?[{()".includes(c)) {
			return null;
		} else {
			cur += c;
			has = true;
		}
	}
	if (has) toks.push(cur);
	return toks;
}

const SCRIPT_RUNNERS = /^(python[\d.]*|bash|sh|zsh|node|ruby|perl|php|deno|bun)(\s|$)/;

function pathOf(f: string, dir: string | null): string {
	if (!dir || isAbsolute(f) || f.startsWith("~")) return f;
	return `${dir.replace(/\/+$/, "")}/${f}`;
}

/** `cat` / `head` / `tail` / `sed -n` の 1 断片を guarded_read の呼び出しへ。形が違えば null。 */
function rewriteRead(text: string, dir: string | null, P: string): string | null {
	const toks = tokenize(text);
	if (!toks || toks.length < 2) return null;
	const [cmd, ...args] = toks;
	const call = (f: string, extra: string) => `${P}read {path: ${JSON.stringify(pathOf(f, dir))}${extra}}`;
	if (cmd === "cat") {
		if (args.some((a) => a.startsWith("-"))) return null;
		if (args.length === 1) return call(args[0], "");
		return `${args.map((f) => call(f, "")).join(" and ")} (separate parallel calls)`;
	}
	if (cmd === "head" || cmd === "tail") {
		let n: number | null = null;
		let plus = false;
		const files: string[] = [];
		const num = (v: string | undefined): boolean => {
			if (v === undefined) return false;
			const m = /^(\+?)(\d+)$/.exec(v);
			if (!m || (m[1] && cmd === "head")) return false;
			plus = m[1] === "+";
			n = Number(m[2]);
			return true;
		};
		for (let i = 0; i < args.length; i++) {
			const a = args[i];
			if (a === "-n" || a === "--lines") {
				if (!num(args[++i])) return null;
			} else if (a.startsWith("-n") && a.length > 2) {
				if (!num(a.slice(2))) return null;
			} else if (/^-\d+$/.test(a)) {
				n = Number(a.slice(1));
			} else if (a.startsWith("-")) {
				return null;
			} else files.push(a);
		}
		if (files.length !== 1 || n === 0) return null;
		if (cmd === "head") return call(files[0], `, limit: ${n ?? 10}`);
		if (plus) return call(files[0], `, offset: ${n}`);
		return call(files[0], `, tail: ${n ?? 10}`);
	}
	if (cmd === "sed" && args[0] === "-n" && args.length === 3) {
		const m = /^(\d+)(?:,(\d+))?p$/.exec(args[1]);
		if (!m) return null;
		const a = Number(m[1]);
		const b = m[2] === undefined ? a : Number(m[2]);
		if (a < 1 || b < a) return null;
		return call(args[2], `, offset: ${a}, limit: ${b - a + 1}`);
	}
	return null;
}

/** ヒアドキュメントを付けた 1 断片 (`<<` より前の部分) を guarded_write などの案内へ。形が違えば null。 */
function rewriteHeredoc(head: string, dir: string | null, P: string): string | null {
	const cat = /^cat\s*(>>?)\s*(.+)$/.exec(head);
	if (cat) {
		const f = tokenize(cat[2]);
		if (!f || f.length !== 1) return null;
		return `${P}write {path: ${JSON.stringify(pathOf(f[0], dir))}, content: "..."${cat[1] === ">>" ? ", append: true" : ""}}`;
	}
	const tee = /^tee\s+(?:(-a|--append)\s+)?(.+)$/.exec(head);
	if (tee) {
		const f = tokenize(tee[2]);
		if (!f || f.length !== 1 || f[0].startsWith("-")) return null;
		return `${P}write {path: ${JSON.stringify(pathOf(f[0], dir))}, content: "..."${tee[1] ? ", append: true" : ""}}`;
	}
	if (SCRIPT_RUNNERS.test(head)) return `${P}write でスクリプトのファイル (例: .tmp/script.py) を作ってから、${P}bash で実行する`;
	return null;
}

const HEREDOC = /(?<!<)<<(?!<)(-?)\s*(["']?)(\w+)\2/;

/** `<<` が引用の外にあるか (前の引用符の数で見る。粗いが、言い換えが付くかどうかにだけ効く)。 */
function outsideQuotes(prefix: string): boolean {
	return (prefix.match(/'/g) ?? []).length % 2 === 0 && (prefix.match(/"/g) ?? []).length % 2 === 0;
}

const clip = (s: string) => (s.length > 80 ? `${s.slice(0, 77)}...` : s);

/**
 * 読み取り・書き込みの誘導で deny された bash の command から、該当の断片の具体的な言い換えの文を作る。
 * 機械的で保守的: 解析できない形・パイプやリダイレクトを含む断片には付けない。何も作れなければ null。
 * 例外は投げない (deny の判定そのものは変えない)。
 */
export function guideHint(command: string, P: string): string | null {
	try {
		const lines = command.split("\n");
		const rewrites: { from: string; to: string }[] = [];
		let others = 0;
		let dir: string | null = null;
		for (let i = 0; i < lines.length; ) {
			const line = lines[i++];
			const m = HEREDOC.exec(line);
			let heredoc = m !== null && outsideQuotes(line.slice(0, m.index));
			const body = heredoc ? line.slice(0, m!.index) : line;
			if (heredoc) {
				while (i < lines.length && (m![1] ? lines[i].trim() : lines[i]) !== m![3]) i++;
				i++;
			}
			const frags = scan(body);
			frags.forEach((f, k) => {
				const toks = f.complex ? null : tokenize(f.text);
				if (toks && toks[0] === "cd" && toks.length === 2) {
					dir = toks[1];
					return;
				}
				const isHeredocFrag = heredoc && k === frags.length - 1;
				const to = isHeredocFrag ? rewriteHeredoc(f.text, dir, P) : f.complex ? null : rewriteRead(f.text, dir, P);
				if (to) rewrites.push({ from: isHeredocFrag ? `${f.text} <<...` : f.text, to });
				else others++;
			});
			// 同じ行で `<<EOF` の後ろに続く断片は、言い換えない
			if (heredoc && line.slice(m!.index + m![0].length).trim() !== "") others++;
			heredoc = false;
		}
		if (rewrites.length === 0) return null;
		const out = ["具体的な言い換え (機械的に作った、該当の断片だけ):", ...rewrites.map((r) => `- \`${clip(r.from)}\` → ${r.to}`)];
		if (others > 0) out.push(`該当の断片だけをこれらのツールに置き換え、残りの断片はそのまま ${P}bash で実行し直してください。`);
		return out.join("\n");
	} catch {
		return null;
	}
}

// ─── edit の失敗のヒント ─────────────────────────────────────────────

export const EDIT_HINT_MAX_BYTES = 512 * 1024;

/** 制御文字を可視化し、max 字で切る。 */
export function visible(s: string, max = 80): string {
	let out = s
		.replace(/\t/g, "→")
		.replace(/\r/g, "␍")
		.replace(/[\u0000-\u001f\u007f]/g, (c) => `\\x${c.charCodeAt(0).toString(16).padStart(2, "0")}`);
	if (out.length > max) out = `${out.slice(0, max)}…`;
	return out;
}

function normLine(s: string): string {
	return s.replace(/\s+/g, " ").trim();
}

export type NearestMatch = { start: number; end: number; exact: boolean; diffLine: number; expected: string; actual: string };

/** oldText に最も近い箇所 (行単位。空白を正規化した行が一致した数が最大の窓)。無ければ null。行番号は 1 始まり。 */
export function nearestMatch(fileText: string, oldText: string): NearestMatch | null {
	const fileLines = fileText.replace(/\r\n/g, "\n").split("\n");
	const oldLines = oldText.replace(/\r\n/g, "\n").split("\n");
	while (oldLines.length > 0 && normLine(oldLines[oldLines.length - 1]) === "") oldLines.pop();
	while (oldLines.length > 0 && normLine(oldLines[0]) === "") oldLines.shift();
	if (oldLines.length === 0) return null;
	const o = oldLines.slice(0, 200).map(normLine);
	const f = fileLines.map(normLine);
	let best = -1;
	let bestScore = 0;
	for (let s = 0; s < f.length; s++) {
		let score = 0;
		for (let i = 0; i < o.length && s + i < f.length; i++) if (o[i] !== "" && o[i] === f[s + i]) score++;
		if (score > bestScore) {
			bestScore = score;
			best = s;
		}
	}
	if (best < 0) return null;
	const len = Math.min(o.length, f.length - best);
	let diff = -1;
	for (let i = 0; i < o.length; i++) {
		if (best + i >= f.length || o[i] !== f[best + i]) {
			diff = i;
			break;
		}
	}
	if (diff >= 0) {
		return { start: best + 1, end: best + len, exact: false, diffLine: best + diff + 1, expected: oldLines[diff] ?? "", actual: fileLines[best + diff] ?? "(ファイルの末尾)" };
	}
	// 正規化すれば一致。生の行で最初に違う行を示す
	let raw = 0;
	while (raw < o.length - 1 && oldLines[raw] === fileLines[best + raw]) raw++;
	return { start: best + 1, end: best + len, exact: true, diffLine: best + raw + 1, expected: oldLines[raw], actual: fileLines[best + raw] };
}

function editsOf(input: any): { oldText: string; newText: string }[] {
	if (Array.isArray(input?.edits)) {
		return input.edits.map((e: any) => ({ oldText: typeof e?.oldText === "string" ? e.oldText : "", newText: typeof e?.newText === "string" ? e.newText : "" }));
	}
	if (typeof input?.oldText === "string") return [{ oldText: input.oldText, newText: typeof input.newText === "string" ? input.newText : "" }];
	return [];
}

export type EditErrorKind = "invalid" | "notfound" | "nochange" | "multiple" | "overlap";

/** 失敗の文面から、ヒントの種類と edits の添字 (単独の edit は null) を読む。足さないもの (ガードの拒否・EROFS・ENOENT など) は null。 */
export function classifyEditError(msg: string): { kind: EditErrorKind; index: number | null } | null {
	if (/^Invalid arguments for tool /.test(msg)) return { kind: "invalid", index: null };
	if (/^edits\[\d+\] and edits\[\d+\] overlap in /.test(msg)) return { kind: "overlap", index: null };
	let m = /^Could not find (?:the exact text|edits\[(\d+)\]) in /.exec(msg);
	if (m) return { kind: "notfound", index: m[1] !== undefined ? Number(m[1]) : null };
	m = /^Found \d+ occurrences of (?:the text|edits\[(\d+)\]) in /.exec(msg);
	if (m) return { kind: "multiple", index: m[1] !== undefined ? Number(m[1]) : null };
	if (/^No changes made to /.test(msg)) return { kind: "nochange", index: null };
	return null;
}

function lineOf(text: string, pos: number): number {
	let n = 1;
	for (let i = text.indexOf("\n"); i >= 0 && i < pos; i = text.indexOf("\n", i + 1)) n++;
	return n;
}

/**
 * edit の失敗の文面 msg に足すヒント (複数行の文字列。純関数)。足せなければ null。
 * fileText は対象の本文 (読めない・大きい・バイナリなら null。本文が要らない種類は null でも足す)。
 */
export function editFailureHint(msg: string, input: unknown, fileText: string | null): string | null {
	const c = classifyEditError(msg);
	if (!c) return null;
	if (c.kind === "invalid") {
		return "oldText・newText に引用符・バックスラッシュ・改行を含む長い編集は、edits を小さく分けるか、ファイル全体を書き換えるなら guarded_write を使う";
	}
	if (c.kind === "overlap") return "近い編集を 1 つにまとめる";
	if (fileText === null) return null;
	const edits = editsOf(input);
	const edit = edits[c.index !== null && c.index < edits.length ? c.index : 0];
	if (!edit) return null;
	const text = fileText.replace(/\r\n/g, "\n");
	if (c.kind === "nochange") {
		const nt = edits[0].newText.replace(/\r\n/g, "\n");
		const at = nt !== "" ? text.indexOf(nt) : -1;
		if (at >= 0) return `すでに適用済みの可能性: newText が行 ${lineOf(text, at)} にある。再編集は不要`;
		return "oldText と newText が同じ内容になっている。編集の意図を見直す";
	}
	if (c.kind === "multiple") {
		const needle = edit.oldText.replace(/\r\n/g, "\n");
		if (needle === "") return null;
		const lines = text.split("\n");
		const hits: string[] = [];
		let total = 0;
		for (let p = text.indexOf(needle); p >= 0; p = text.indexOf(needle, p + 1)) {
			total++;
			if (hits.length < 5) {
				const ln = lineOf(text, p);
				hits.push(`行 ${ln} (直前: ${ln > 1 ? `\`${visible(lines[ln - 2], 60)}\`` : "なし"})`);
			}
		}
		if (total === 0) return null;
		return `一致: ${hits.join("、")}${total > hits.length ? `、ほか ${total - hits.length} 件` : ""}。直前の行を含めて oldText を一意にする`;
	}
	// notfound
	const near = nearestMatch(text, edit.oldText);
	if (!near) return "guarded_read で該当箇所を読み直してから、oldText をコピーし直す";
	const head = `最も近い箇所: 行 ${near.start}〜${near.end}。違い: 行 ${near.diffLine} (期待: \`${visible(near.expected)}\` / 実際: \`${visible(near.actual)}\`)`;
	return near.exact ? `${head}\n空白・タブ・改行コードの違いの可能性` : head;
}

/**
 * guarded_edit の失敗結果 (tool_result) に足す差分。足さなければ undefined。元の本文は消さず、末尾へ追記する。
 * 読めない (読み取り拒否・無い・512 KiB 超・バイナリ・例外) ときは、本文が要るヒントを省く。
 */
export async function decorateEditResult(
	event: { isError?: boolean; input?: any; content?: any[] },
	cwd: string,
	canRead: (absPath: string) => boolean,
): Promise<{ content: any[] } | undefined> {
	try {
		if (!event?.isError || !Array.isArray(event.content)) return undefined;
		const at = event.content.findIndex((b: any) => b?.type === "text" && typeof b.text === "string");
		if (at < 0) return undefined;
		const msg: string = event.content[at].text;
		if (!classifyEditError(msg)) return undefined;
		let fileText: string | null = null;
		const path = event.input?.path;
		if (typeof path === "string" && path !== "") {
			try {
				const abs = resolveInputPath(path, cwd);
				const st = await stat(abs);
				if (st.isFile() && st.size <= EDIT_HINT_MAX_BYTES && canRead(abs)) {
					const buf = await readFile(abs);
					if (!buf.includes(0)) fileText = buf.toString("utf-8");
				}
			} catch {
				fileText = null;
			}
		}
		const hint = editFailureHint(msg, event.input, fileText);
		if (!hint) return undefined;
		const content = event.content.map((b: any, i: number) => (i === at ? { ...b, text: `${b.text}\n${hint}` } : b));
		return { content };
	} catch {
		return undefined;
	}
}
