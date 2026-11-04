// bash の確認画面で、1 行のコマンドを手順に解きほぐして見せる (表示だけ。権限・判定には使わない)。
// 構文木は同梱の mvdan-sh (vendor/mvdan-sh。mvdan/sh の GopherJS 版) で作る。読み込めない・構文エラーのときは、
// 全体を原文の 1 手順にする (complete=false)。説明の語・副作用の印・本文のキーワードは、この中の固定の表。
// 原文に倒すのは、プロセス置換・関数定義・case・select・eval・((・構文エラー・入れ子の上限超えだけ (誤った説明は原文より悪い)。
// 例外は投げない。 see docs/spec/guard/pi-extensions.md#確認画面の手順の一覧
//
// node の型除去でそのまま動く書き方だけを使う (enum・namespace は使わない)。

import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { sanitizeForDisplay } from "./confirm-view.ts";
import { patternMatches } from "./judge/normalize.ts";

export type Step = { no: number; text: string; raw: string; marks: string[]; hit: boolean; level: number };

/** 手順の数の上限 (入れ子を含む全体) */
export const MAX_STEPS = 16;
export const MAX_STEP_CHARS = 200;
/** 入れ子の最大の深さ (最上位が 0) */
export const MAX_LEVEL = 3;
const MAX_CMD_CHARS = 100;

type Part = { text: string; raw: string; marks: string[]; level: number; hit: boolean };
type Doc = { quoted: boolean; body: string };
type W = { raw: string; value: string };
type R = { fd: string; op: string; target: W | null; dup: boolean; doc?: Doc };
type Call = { assigns: string[]; words: W[]; redirs: R[]; subs: any[]; conn: string; after: string; raw: string };
type Ctx = { hits: string[]; complete: boolean };
// 構文木の 1 回分の入力 (原文のバイト列。Offset() は UTF-8 のバイト位置なので、切り出しは Buffer 経由)
type Src = { buf: Buffer; file: any };

// ─── mvdan-sh の読み込み (遅延・1 回だけ。失敗したら null) ───────────────

let SYN: any = undefined;

/** 構文木の道具 (syntax)。読み込めなければ null。試験用に PI_EXPLAIN_VENDOR で読み込み先を変えられる */
function loadSyntax(): any {
	if (SYN !== undefined) return SYN;
	try {
		const override = process.env.PI_EXPLAIN_VENDOR;
		const path = override ? override : fileURLToPath(new URL("./vendor/mvdan-sh/index.js", import.meta.url));
		const req = createRequire(import.meta.url);
		const s = req(path)?.syntax;
		SYN = s && typeof s.NewParser === "function" ? s : null;
	} catch {
		SYN = null;
	}
	return SYN;
}

function parseSource(text: string): Src {
	const S = loadSyntax();
	if (S === null) throw new Error("mvdan-sh が読み込めない");
	const parser = S.NewParser(S.Variant(S.LangBash));
	return { buf: Buffer.from(text, "utf8"), file: parser.Parse(text, "") };
}

// ─── 構文木の小さな道具 ─────────────────────────────────────────

const arr = (x: any): any[] => {
	if (!x) return [];
	if (Array.isArray(x)) return x;
	if (typeof x.$length === "number") return Array.from({ length: x.$length }, (_, i) => x.$array[x.$offset + i]);
	return [];
};
const typeOf = (n: any): string => (n ? String(loadSyntax().NodeType(n)) : "");
const pos = (n: any): number => Number(n.Pos().Offset());
const end = (n: any): number => Number(n.End().Offset());
const cut = (src: Src, a: number, b: number): string => src.buf.subarray(a, Math.max(a, b)).toString("utf8");
const rawOf = (src: Src, n: any): string => cut(src, pos(n), end(n));

/** 単語の値 (引用・エスケープを外した値)。展開 ($x や $(…)) は原文のまま */
function valueOf(src: Src, n: any): string {
	switch (typeOf(n)) {
		case "Word":
			return arr(n.Parts).map((p) => valueOf(src, p)).join("");
		case "Lit":
			return String(n.Value).replace(/\\\n/g, "").replace(/\\([\s\S])/g, "$1");
		case "SglQuoted":
			return String(n.Value);
		case "DblQuoted":
			return arr(n.Parts).map((p) => valueOf(src, p)).join("");
		default:
			return rawOf(src, n);
	}
}

function toW(src: Src, n: any): W {
	return { raw: rawOf(src, n), value: valueOf(src, n) };
}

/** 文の中のコマンド置換 (入れ子の中は含めない) とプロセス置換の有無 */
function scanNodes(nodes: any[]): { subs: any[]; proc: boolean } {
	const S = loadSyntax();
	const subs: any[] = [];
	let proc = false;
	for (const nd of nodes) {
		if (!nd) continue;
		S.Walk(nd, (n: any) => {
			if (!n) return false;
			const t = String(S.NodeType(n));
			if (t === "ProcSubst") {
				proc = true;
				return false;
			}
			if (t === "CmdSubst") {
				subs.push(n);
				return false;
			}
			return true;
		});
	}
	return { subs, proc };
}

// ─── 固定の表 (説明の語。LLM に作らせない) ─────────────────────────

const GIT_SUB: Record<string, string> = {
	log: "履歴を表示", status: "状態を表示", diff: "差分を表示", show: "コミットを表示", add: "ステージに追加", commit: "コミット",
	push: "リモートへ送信", pull: "取得して統合", fetch: "リモートから取得", checkout: "ブランチ・ファイルを切り替え",
	switch: "ブランチを切り替え", restore: "ファイルを戻す", reset: "HEAD・ステージを戻す", rebase: "コミットを付け替え",
	merge: "統合", branch: "ブランチを操作", tag: "タグを操作", stash: "退避", clone: "複製", worktree: "worktree を操作",
	flow: "git flow", remote: "リモートを操作", config: "設定", rm: "追跡から外して削除", mv: "移動・改名",
	"cherry-pick": "コミットを取り込み", revert: "打ち消しのコミット", clean: "未追跡ファイルを削除", "ls-files": "追跡ファイルを列挙",
	"rev-parse": "参照を解決", blame: "行ごとの履歴を表示", grep: "追跡ファイルを検索",
};
const VERB: Record<string, string> = {
	rm: "ファイルを削除", mv: "移動・改名", cp: "コピー", cat: "内容を表示", ls: "一覧を表示", grep: "検索", rg: "検索", find: "探索",
	head: "先頭を表示", tail: "末尾を表示", curl: "HTTP 通信", wget: "ダウンロード", python3: "Python を実行", python: "Python を実行",
	node: "Node.js を実行", uv: "uv を実行", uvx: "uv でツールを実行", mise: "mise を実行", chezmoi: "chezmoi を実行", gh: "GitHub CLI",
	mkdir: "ディレクトリを作成", touch: "ファイルを作成・更新", echo: "文字列を出力", sed: "文字列を置換", awk: "テキストを処理",
	sort: "並べ替え", wc: "数を数える", tee: "標準入力をファイルにも書く", chmod: "権限を変更", npm: "npm を実行", pnpm: "pnpm を実行",
	pip: "pip を実行", pip3: "pip を実行", docker: "docker を実行", ssh: "リモートへ接続", scp: "リモートへコピー",
	diff: "差分を表示", pwd: "現在地を表示", test: "条件を確かめる", xargs: "引数を組み立てて実行", read: "入力を読む",
};
const NET_CMDS = new Set(["curl", "wget", "ssh", "scp", "rsync", "nc", "ftp", "gh"]);
const WRITE_CMDS = new Set(["mv", "cp", "touch", "mkdir", "tee", "ln", "chmod", "chown", "dd", "install", "truncate"]);
const PKG_MGRS = new Set(["npm", "pnpm", "yarn", "bun"]);
const PKG_VERBS = new Set(["install", "i", "add", "ci"]);
const SHELLS = new Set(["bash", "sh", "zsh", "dash"]);
const ASSIGN = /^[A-Za-z_][A-Za-z0-9_]*=/;

// 本文 (ヒアドキュメント) の中のキーワード表 (網羅は目指さない)
const PY_MARKS: [RegExp, string][] = [
	[/\bos\.(?:remove|unlink|rmdir|removedirs)\b|shutil\.rmtree|\.unlink\(/, "ファイルを削除する"],
	[/\bsubprocess\b|os\.system|os\.popen|os\.exec/, "別のコマンドを実行する"],
	[/\brequests\b|\burllib\b|http\.client|\bsocket\b|urlopen|aiohttp|httpx/, "ネットワークに接続する"],
	[/\bopen\([^)]*,\s*['"][wax][^'"]*['"]|write_text|write_bytes|shutil\.(?:copy|move)|os\.(?:rename|replace)/, "ファイルを書き込む"],
	[/\beval\(|\bexec\(|__import__/, "動的にコードを実行する"],
];
const JS_MARKS: [RegExp, string][] = [
	[/child_process|\bexecSync\b|\bspawn(?:Sync)?\(/, "別のコマンドを実行する"],
	[/\bfs\.(?:rm|rmSync|unlink|unlinkSync|rmdir|rmdirSync)\b/, "ファイルを削除する"],
	[/\bfs\.(?:writeFile|writeFileSync|appendFile|appendFileSync)\b/, "ファイルを書き込む"],
	[/\bfetch\(|\bhttps?\.(?:request|get)|net\.connect|XMLHttpRequest/, "ネットワークに接続する"],
	[/\beval\(/, "動的にコードを実行する"],
];
const SH_MARKS: [RegExp, string][] = [
	[/(?:^|[\s;&|])rm(?:\s|$)/, "ファイルを削除する"],
	[/(?:^|[\s;&|])(?:curl|wget)(?:\s|$)/, "ネットワークに接続する"],
	[/(?:^|[^>&0-9<])>>?\s*[^\s>&]/, "ファイルを書き込む"],
	[/(?:^|[\s;&|])sudo(?:\s|$)/, "管理者権限で実行する"],
];

function addMark(marks: string[], m: string): void {
	if (!marks.includes(m)) marks.push(m);
}

function gitSub(words: string[]): { sub: string; rest: string[] } {
	let i = 1;
	while (i < words.length && words[i].startsWith("-")) i += words[i] === "-C" || words[i] === "-c" ? 2 : 1;
	return { sub: words[i] ?? "", rest: words.slice(i + 1) };
}

function marksFor(words: string[]): string[] {
	const marks: string[] = [];
	const cmd = words[0] ?? "";
	if (cmd === "rm") addMark(marks, "ファイルを削除する");
	if (cmd === "find" && words.includes("-delete")) addMark(marks, "ファイルを削除する");
	if (NET_CMDS.has(cmd)) addMark(marks, "ネットワークに接続する");
	if (WRITE_CMDS.has(cmd)) addMark(marks, "ファイルを書き込む");
	if (cmd === "sed" && words.some((w) => /^-[A-Za-z]*i/.test(w) || w.startsWith("--in-place"))) addMark(marks, "ファイルを書き込む");
	if (cmd === "git") {
		const { sub, rest } = gitSub(words);
		if (sub === "push") {
			addMark(marks, "ネットワークに接続する");
			addMark(marks, "履歴・参照を書き換える");
		}
		if (sub === "fetch" || sub === "pull" || sub === "clone") addMark(marks, "ネットワークに接続する");
		if (["reset", "rebase", "cherry-pick", "revert", "filter-branch", "update-ref"].includes(sub)) addMark(marks, "履歴・参照を書き換える");
		if (sub === "commit" && rest.some((w) => w === "--amend")) addMark(marks, "履歴・参照を書き換える");
		if ((sub === "branch" && rest.some((w) => /^-[dDmM]$/.test(w))) || (sub === "tag" && rest.includes("-d"))) addMark(marks, "履歴・参照を書き換える");
		if (sub === "clean" || sub === "rm") addMark(marks, "ファイルを削除する");
	}
	const sub1 = words[1] ?? "";
	const sub2 = words[2] ?? "";
	if ((PKG_MGRS.has(cmd) && PKG_VERBS.has(sub1)) || (["pip", "pip3"].includes(cmd) && sub1 === "install")) addMark(marks, "パッケージを入れる");
	if (cmd === "uv" && (sub1 === "add" || (sub1 === "pip" && sub2 === "install") || (sub1 === "tool" && sub2 === "install"))) addMark(marks, "パッケージを入れる");
	if (["apt", "apt-get", "brew", "cargo", "gem", "go"].includes(cmd) && sub1 === "install") addMark(marks, "パッケージを入れる");
	return marks;
}

function purposeOf(words: string[]): string {
	const cmd = words[0] ?? "";
	if (cmd === "git") return GIT_SUB[gitSub(words).sub] ?? "";
	return VERB[cmd] ?? "";
}

// ─── 部品 ──────────────────────────────────────────────────────

function clip(s: string, max: number): string {
	const a = Array.from(s);
	return a.length <= max ? s : `${a.slice(0, max - 1).join("")}…`;
}

function hitSimple(ctx: Ctx, ...raws: string[]): boolean {
	return ctx.hits.some((h) =>
		raws.some((r) => {
			try {
				return patternMatches(r, h);
			} catch {
				return false;
			}
		}),
	);
}

function part(text: string, raw: string, level: number, marks: string[] = [], hit = false): Part {
	return { text, raw, marks, level, hit };
}

/** 解析できない部分 (原文のまま 1 手順) */
function fallback(raw: string, level: number, ctx: Ctx, why = "解析できない部分"): Part {
	ctx.complete = false;
	const r = raw.trim();
	const hit = ctx.hits.some((h) => h !== "" && r.includes(h.replace(/\s*\*$/, "")));
	return part(`${why}: ${r}`, r, level, [], hit);
}

function prefixFirst(parts: Part[], prefix: string): Part[] {
	if (parts.length > 0) parts[0] = { ...parts[0], text: `${prefix}${parts[0].text}` };
	return parts;
}

function excerpt(lines: string[]): string {
	const q = (l: string) => `「${clip(l.trim(), 50)}」`;
	if (lines.length <= 4) return lines.map(q).join(" ⏎ ");
	return `${lines.slice(0, 3).map(q).join(" ⏎ ")} ⏎ … ⏎ ${q(lines[lines.length - 1])}`;
}

function redirectClause(r: R, marks: string[]): string {
	const who = r.fd === "2" ? "標準エラー" : r.fd === "&" ? "標準出力と標準エラー" : "標準出力";
	if (r.op === "<<" || r.op === "<<-") {
		return r.doc ? `本文（${r.doc.body === "" ? 0 : r.doc.body.split("\n").length} 行）を標準入力として渡す` : "本文を標準入力として渡す";
	}
	if (r.dup || r.target === null) {
		if (r.dup && r.fd === "2" && r.target?.value === "1") return "標準エラーを標準出力へ向ける";
		return "入出力の接続を変更する";
	}
	const t = `\`${clip(r.target.raw, 60)}\``;
	if (r.op === "<") return `${t} を標準入力にする`;
	if (r.op === "<<<") return `文字列 ${t} を標準入力にする`;
	if ([">", ">|", ">>", ">&", "<>", "&>", "&>>"].includes(r.op)) {
		if (r.target.value === "/dev/null") return `${who}を捨てる（/dev/null）`;
		addMark(marks, "ファイルを書き込む");
		return `${who}を ${t} に書き込む（${r.op.endsWith(">>") ? "追記" : "上書き"}）`;
	}
	return "入出力の接続を変更する";
}

// ─── 文・複合コマンド ───────────────────────────────────────────────

/** 文のリストを手順にする。深すぎるときは原文に倒す */
function stmtList(list: any[], src: Src, level: number, ctx: Ctx): Part[] {
	if (list.length === 0) return [];
	if (level > MAX_LEVEL) {
		return [fallback(cut(src, pos(list[0]), end(list[list.length - 1])), level, ctx, "入れ子が深いので省略")];
	}
	const out: Part[] = [];
	for (const st of list) out.push(...stmtParts(st, src, level, ctx, ";", ""));
	return out;
}

/** 文字列を新しく解析して手順にする (bash -c・ヒアドキュメントの本文)。構文エラーなら原文に倒す */
function textParts(text: string, level: number, ctx: Ctx): Part[] {
	if (text.trim() === "") return [];
	if (level > MAX_LEVEL) return [fallback(text, level, ctx, "入れ子が深いので省略")];
	try {
		const s = parseSource(text);
		return stmtList(arr(s.file.Stmts), s, level, ctx);
	} catch {
		return [fallback(text, level, ctx)];
	}
}

function subParts(subs: any[], src: Src, level: number, ctx: Ctx, label: string): Part[] {
	const out: Part[] = [];
	for (const sub of subs) out.push(...prefixFirst(stmtList(arr(sub.Stmts), src, level, ctx), label));
	return out;
}

/** `X && Y` `X | Y` の演算子 (X の終わりと Y の始まりの間の原文) */
function opText(src: Src, b: any): string {
	const t = cut(src, end(b.X), pos(b.Y));
	for (const o of ["&&", "||", "|&", "|"]) if (t.includes(o)) return o;
	return t.trim();
}

type Leaf = { st: any; conn: string; after: string };

function flatten(st: any, src: Src, conn: string, after: string, out: Leaf[]): void {
	const a = st.Background ? "&" : after;
	if (st.Cmd && typeOf(st.Cmd) === "BinaryCmd") {
		const op = opText(src, st.Cmd);
		flatten(st.Cmd.X, src, conn, op, out);
		flatten(st.Cmd.Y, src, op, a, out);
	} else out.push({ st, conn, after: a });
}

function stmtParts(st: any, src: Src, level: number, ctx: Ctx, conn: string, after: string): Part[] {
	const leaves: Leaf[] = [];
	flatten(st, src, conn, after, leaves);
	const out: Part[] = [];
	for (const l of leaves) {
		const ps = leafParts(l, src, level, ctx);
		out.push(...(l.st.Negated ? prefixFirst(ps, "結果を反転して: ") : ps));
	}
	return out;
}

function tailNote(st: any, src: Src): string {
	const rs = arr(st.Redirs).map((r) => rawOf(src, r));
	return rs.length > 0 ? `。終了後の指定: ${clip(rs.join(" "), 60)}` : "";
}

function leafParts(l: Leaf, src: Src, level: number, ctx: Ctx): Part[] {
	const st = l.st;
	const raw = rawOf(src, st);
	const cmd = st.Cmd;
	const t = typeOf(cmd);
	const tail = tailNote(st, src);
	const nested = (list: any, label: string) => prefixFirst(stmtList(arr(list), src, level + 1, ctx), label);
	switch (t) {
		case "CallExpr": {
			const r = callParts(st, cmd, src, level, ctx, l, raw);
			return r ?? [fallback(raw, level, ctx)];
		}
		case "": {
			// 入出力の接続だけの文 (`> file`)
			const r = callParts(st, null, src, level, ctx, l, raw);
			return r ?? [fallback(raw, level, ctx)];
		}
		case "DeclClause": {
			const sc = scanNodes([cmd]);
			if (sc.proc) return [fallback(raw, level, ctx)];
			return [
				part(`変数を宣言・設定: \`${clip(rawOf(src, cmd), MAX_CMD_CHARS)}\``, raw, level),
				...subParts(sc.subs.slice(0, 4), src, level + 1, ctx, "コマンド置換（出力を引数に使う）: "),
			];
		}
		case "TestClause":
			return [part(`条件式を評価: \`${clip(rawOf(src, cmd), MAX_CMD_CHARS)}\``, raw, level)];
		case "TimeClause": {
			if (!cmd.Stmt) return [part("時間を測る", raw, level)];
			const inner = stmtParts(cmd.Stmt, src, level, ctx, l.conn, st.Background ? "&" : l.after);
			return prefixFirst(inner, "時間を測って: ");
		}
		case "Subshell":
			return [
				part(`サブシェルで次を実行（cd や変数の変更は外に影響しない）${tail}`, raw, level),
				...stmtList(arr(cmd.Stmts), src, level + 1, ctx),
			];
		case "Block":
			return [part(`グループとして次を実行${tail}`, raw, level), ...stmtList(arr(cmd.Stmts), src, level + 1, ctx)];
		case "ForClause": {
			const loop = cmd.Loop;
			if (cmd.Select || typeOf(loop) !== "WordIter") return [fallback(raw, level, ctx)];
			const items = arr(loop.Items);
			const list = items.map((w) => rawOf(src, w)).join(" ");
			const out = [
				part(`繰り返し: ${clip(String(loop.Name.Value), 40)} ごとに${items.length > 0 ? `（対象: ${clip(list, 80)}）` : "（引数の各値）"}${tail}`, raw, level),
			];
			const sc = scanNodes(items);
			if (sc.proc) return [fallback(raw, level, ctx)];
			out.push(...subParts(sc.subs.slice(0, 2), src, level + 1, ctx, "対象を作るコマンド置換: "));
			out.push(...nested(cmd.Do, "本体: "));
			return out;
		}
		case "WhileClause":
			return [
				part(`繰り返し（条件が${cmd.Until ? "偽" : "真"}の間）${tail}`, raw, level),
				...nested(cmd.Cond, "条件: "),
				...nested(cmd.Do, "本体: "),
			];
		case "IfClause":
			return ifParts(cmd, src, level, ctx, raw, tail);
		default:
			// CaseClause・FuncDecl・ArithmCmd・CoprocClause・LetClause など
			return [fallback(raw, level, ctx)];
	}
}

function ifParts(ic: any, src: Src, level: number, ctx: Ctx, raw: string, tail: string): Part[] {
	const nested = (list: any, label: string) => prefixFirst(stmtList(arr(list), src, level + 1, ctx), label);
	const out = [part(`条件分岐${tail}`, raw, level)];
	out.push(...nested(ic.Cond, "条件: "));
	out.push(...nested(ic.Then, "真なら: "));
	const el = ic.Else;
	if (el) {
		if (arr(el.Cond).length > 0) out.push(...prefixFirst(ifParts(el, src, level + 1, ctx, rawOf(src, el), ""), "偽なら: "));
		else out.push(...nested(el.Then, "偽なら: "));
	}
	return out;
}

// ─── 1 つの単純コマンドの説明 ────────────────────────────────────────

function callParts(st: any, cmd: any, src: Src, level: number, ctx: Ctx, l: Leaf, raw: string): Part[] | null {
	const nodes = [...arr(cmd?.Assigns), ...arr(cmd?.Args), ...arr(st.Redirs)];
	const sc = scanNodes(nodes);
	if (sc.proc) return null;
	const redirs: R[] = arr(st.Redirs).map((r) => {
		const start = r.N ? end(r.N) : pos(r);
		let op = cut(src, start, pos(r.Word)).trim();
		let fd = r.N ? String(r.N.Value) : "";
		if (op.startsWith("&")) {
			fd = "&";
			op = op.slice(1);
		}
		const word = toW(src, r.Word);
		const dup = (op === ">&" || op === "<&") && /^(?:\d+|-)$/.test(word.value);
		let doc: Doc | undefined;
		if ((op === "<<" || op === "<<-") && r.Hdoc) {
			let body = arr(r.Hdoc.Parts).map((p) => valueOf(src, p)).join("");
			if (body.endsWith("\n")) body = body.slice(0, -1);
			if (op === "<<-") body = body.replace(/^\t+/gm, "");
			doc = { quoted: /['"\\]/.test(word.raw), body };
		}
		return { fd, op, target: word, dup, doc };
	});
	const c: Call = {
		assigns: arr(cmd?.Assigns).map((a) => String(a.Name.Value)),
		words: arr(cmd?.Args).map((w) => toW(src, w)),
		redirs,
		subs: sc.subs,
		conn: l.conn,
		after: l.after,
		raw,
	};
	return explainCall(c, src, level, ctx, []);
}

function docParts(vals: string[], writeTarget: string | null, doc: Doc, level: number, ctx: Ctx): Part[] {
	const lines = doc.body === "" ? [] : doc.body.split("\n");
	const cmd = vals[0] ?? "";
	const args = vals.slice(1).filter((v) => !v.startsWith("-") || v === "-");
	const stdinScript = args.length === 0 || args[0] === "-" || vals.includes("-s");
	let nature = "標準入力として渡される";
	let table: [RegExp, string][] | null = null;
	let shell = false;
	if (/^python[0-9.]*$/.test(cmd) && stdinScript) {
		nature = "Python のスクリプトとして実行される";
		table = PY_MARKS;
	} else if (cmd === "node" && stdinScript) {
		nature = "Node.js のスクリプトとして実行される";
		table = JS_MARKS;
	} else if (SHELLS.has(cmd) && !vals.includes("-c") && stdinScript) {
		nature = "シェルスクリプトとして実行される";
		table = SH_MARKS;
		shell = true;
	} else if (cmd === "ssh") {
		nature = "リモートのシェルで実行される";
		table = SH_MARKS;
		shell = true;
	} else if ((cmd === "cat" || cmd === "tee") && writeTarget) {
		nature = `ファイル \`${clip(writeTarget, 60)}\` の内容になる`;
	} else if (cmd === "cat") nature = "そのまま出力される";
	const marks: string[] = [];
	if (table) for (const [re, m] of table) if (re.test(doc.body)) addMark(marks, m);
	const expand = !doc.quoted && /[$`]/.test(doc.body) ? "（シェルが変数・コマンドを展開してから渡す）" : "";
	const out = [part(`入力として渡す本文（${lines.length} 行）。${nature}${expand}: ${excerpt(lines)}`, doc.body, level, marks)];
	if (shell && level + 1 <= MAX_LEVEL) out.push(...textParts(doc.body, level + 1, ctx));
	return out;
}

/** 単純コマンドの説明。eval など解析しない形は null (呼び出し側が原文に倒す) */
function explainCall(c: Call, src: Src, level: number, ctx: Ctx, pre: string[]): Part[] | null {
	const W: W[] = [...c.words];
	const envNames = [...c.assigns];
	const prefixes = [...pre];
	const extraMarks: string[] = [];
	// 前置き (環境変数・env・time・nohup・sudo・command) を剥がす
	for (;;) {
		while (W.length > 0 && ASSIGN.test(W[0].raw)) envNames.push(W.shift()!.raw.split("=")[0]);
		const h = W[0]?.value;
		if (h === "env") {
			W.shift();
			while (W.length > 0 && W[0].value.startsWith("-")) W.shift();
		} else if (h === "time") {
			W.shift();
			prefixes.push("時間を測って、");
		} else if (h === "nohup") {
			W.shift();
			prefixes.push("切断後も続くように、");
		} else if (h === "command") {
			W.shift();
		} else if (h === "sudo") {
			W.shift();
			while (W.length > 0 && W[0].value.startsWith("-")) {
				const o = W.shift()!.value;
				if (o === "-u" || o === "-g") W.shift();
			}
			prefixes.push("管理者権限で、");
			addMark(extraMarks, "管理者権限で実行する");
		} else break;
	}
	if (W[0]?.value === "eval") return null;
	const vals = W.map((w) => w.value);
	const raws = W.map((w) => w.raw);
	const marks = marksFor(vals);
	for (const m of extraMarks) addMark(marks, m);
	const extras: string[] = [];
	let writeTarget: string | null = null;
	for (const r of c.redirs) {
		extras.push(redirectClause(r, marks));
		if (r.target && (r.op === ">" || r.op === ">>" || r.op === ">|") && (r.fd === "" || r.fd === "1")) writeTarget = r.target.value;
	}
	if (c.after === "&") extras.push("バックグラウンドで実行する");
	if (c.after === "|" || c.after === "|&") extras.push("出力を次へ渡す");
	const children: Part[] = [];
	// 入れ子で実行されるコマンド (xargs / find -exec): 語の並びをそのまま単純コマンドとして説明する
	const nestedCall = (rest: W[], label: string): Part[] => {
		const text = rest.map((w) => w.raw).join(" ");
		if (level + 1 > MAX_LEVEL) return [fallback(text, level + 1, ctx, "入れ子が深いので省略")];
		const sub: Call = { assigns: [], words: rest, redirs: [], subs: [], conn: "", after: "", raw: text };
		return prefixFirst(explainCall(sub, src, level + 1, ctx, []) ?? [fallback(text, level + 1, ctx)], label);
	};
	const cmd0 = vals[0] ?? "";
	if (cmd0 === "xargs") {
		let i = 1;
		while (i < vals.length && vals[i].startsWith("-")) {
			if (vals[i] === "--") {
				i++;
				break;
			}
			if (/^-[nIaPdLsE]$/.test(vals[i])) {
				if (vals[i] === "-a" && vals[i + 1]) extras.push(`ファイル \`${clip(vals[i + 1], 60)}\` の各行を引数にする`);
				i += 2;
			} else i++;
		}
		const rest = W.slice(i);
		if (rest.length > 0) {
			extras.push("受け取った各項目を引数にして次を実行する");
			children.push(...nestedCall(rest, "各項目に対して: "));
		}
	} else if (cmd0 === "find") {
		const e = vals.findIndex((v) => ["-exec", "-execdir", "-ok", "-okdir"].includes(v));
		if (e >= 0) {
			let stop = vals.findIndex((v, k) => k > e && (v === ";" || v === "+"));
			if (stop < 0) stop = vals.length;
			const rest = W.slice(e + 1, stop);
			if (rest.length > 0) {
				extras.push("見つかった各結果に対して次を実行する");
				children.push(...nestedCall(rest, "各結果に対して: "));
			}
		}
	} else if (SHELLS.has(cmd0) && vals.length >= 3 && /^-[a-z]*c[a-z]*$/.test(vals[1])) {
		extras.push("中身を次の手順で実行する");
		children.push(...textParts(vals[2], level + 1, ctx));
	}
	for (const r of c.redirs) if (r.doc) children.push(...docParts(vals, writeTarget, r.doc, level + 1, ctx));
	children.push(...subParts(c.subs.slice(0, 4), src, level + 1, ctx, "コマンド置換（出力を引数に使う）: "));
	let text: string;
	const envNote = envNames.length > 0 ? `環境変数 ${envNames.join(", ")} を設定し、` : "";
	if (W.length === 0) {
		text = envNames.length > 0 ? `変数 ${envNames.join(", ")} を設定` : "入出力の接続だけを設定";
	} else if (cmd0 === "cd") {
		text = `作業場所を \`${clip(raws[1] ?? "~", MAX_CMD_CHARS)}\` に変更`;
	} else {
		const purpose = purposeOf(vals);
		text = `${prefixes.join("")}${envNote}\`${clip(raws.join(" "), MAX_CMD_CHARS)}\`${purpose ? `（${purpose}）` : ""} を実行`;
	}
	if (extras.length > 0) text += `し、${extras.join("、")}`;
	if (c.conn === "||") text = `前が失敗したときだけ: ${text}`;
	const hit = hitSimple(ctx, c.raw, raws.join(" "));
	return [part(text, c.raw, level, marks, hit), ...children];
}

// 表示用: 制御文字などを可視化し、改行・タブを 1 行に畳み、長さを切る
function fit(s: string): string {
	const v = sanitizeForDisplay(String(s)).replace(/[\r\n]+/g, "⏎").replace(/\t/g, " ");
	return clip(v, MAX_STEP_CHARS);
}

/** コマンドを手順に解きほぐす (表示用)。例外は投げない。hit は、確認の理由になった規則のパターン */
export function explainCommand(cmd: string, hit?: string[]): { steps: Step[]; complete: boolean } {
	const whole = (): { steps: Step[]; complete: boolean } => ({
		steps: [{ no: 1, text: `解析できない部分: ${fit(cmd)}`, raw: fit(cmd), marks: [], hit: false, level: 0 }],
		complete: false,
	});
	try {
		const text = String(cmd ?? "");
		if (text.trim() === "") return { steps: [], complete: true };
		const ctx: Ctx = { hits: hit ?? [], complete: true };
		const src = parseSource(text);
		let parts = stmtList(arr(src.file.Stmts), src, 0, ctx);
		let extra = 0;
		if (parts.length > MAX_STEPS) {
			extra = parts.length - MAX_STEPS;
			parts = parts.slice(0, MAX_STEPS);
		}
		const steps: Step[] = parts.map((p, i) => ({
			no: i + 1,
			text: fit(p.text),
			raw: fit(p.raw),
			marks: p.marks.map((m) => fit(m)),
			hit: ctx.hits.length > 0 && p.hit,
			level: p.level,
		}));
		if (extra > 0) steps.push({ no: steps.length + 1, text: `ほか ${extra} 手順`, raw: "", marks: [], hit: false, level: 0 });
		return { steps, complete: ctx.complete };
	} catch {
		return whole();
	}
}

/** 確認画面に添える「手順:」の行。出さないとき (単純なコマンド・空) は空配列 */
export function explainLines(cmd: string, hit?: string[]): string[] {
	const { steps, complete } = explainCommand(cmd, hit);
	if (steps.length === 0) return [];
	if (steps.length === 1 && complete && steps[0].marks.length === 0 && !steps[0].hit) return [];
	const lines = ["手順:"];
	for (const s of steps) {
		const marks = s.marks.length > 0 ? `  [副作用の候補: ${s.marks.join("・")}]` : "";
		lines.push(`  ${"  ".repeat(s.level)}${s.no}. ${s.text}${marks}${s.hit ? "  ← 確認の理由に当たった箇所" : ""}`);
	}
	if (!complete) lines.push("  ⚠ 解析できない部分があります。原文を確認してください");
	lines.push("  (手順は理解を助ける補助です。判定には使っていません。常に原文を確認してください)");
	return lines;
}
