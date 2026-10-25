// guarded_* の説明の上書き・read の tail・write の append・読みの失敗のヒント・誘導 deny の言い換え。
// see docs/spec/guard/pi-guard.md
//
// node の型除去でそのまま動く書き方だけを使う (enum・namespace は使わない)。pi 本体は import しない。
import { appendFile, mkdir, open, stat } from "node:fs/promises";
import { readdirSync } from "node:fs";
import { homedir } from "node:os";
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
					`Waits of 10 seconds or more (sleep) and background jobs (&, nohup) go through bg_run.`,
				promptSnippet: "Run shell commands (build, test, git; search with grep/find/ls). Not for reading or writing file contents",
				promptGuidelines: [
					...(def.promptGuidelines ?? []),
					`Do not use ${P}bash to read, create, or change file contents. cat/head/tail/sed -n -> ${P}read (offset/limit for a range, tail for the last N lines); echo >, cat > f <<EOF, tee -> ${P}write (append: true to append); sed/awk edits -> ${P}edit.`,
					`To read several files, make parallel ${P}read calls; do not concatenate them in one ${P}bash command.`,
					`Run waits of 10 seconds or more (sleep) and background jobs (&, nohup) with bg_run, not ${P}bash.`,
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
					`When changing several separate places in one file, put them in edits[] of one ${P}edit call instead of several calls.`,
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
export function resolveInputPath(p: string, cwd: string): string {
	let s = p.startsWith("@") ? p.slice(1) : p;
	if (s === "~") s = homedir();
	else if (s.startsWith("~/")) s = join(homedir(), s.slice(2));
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
