// bash コマンドの解析結果 Plan (判定器の「一度だけ解析する」入口)。
//
// 構文木 (同梱の mvdan-sh。judge/syntax.ts が読み込む) を 1 回だけ歩いて、実行される箇所 (ExecSite) の平坦な一覧にする。
// 純関数で、例外は投げない。解析できない・読み込めない・原文が不正・上限超えは Plan { ok: false } (呼び出し側が deny にする)。
// この段では判定器に接続しない (接続は G1(b) 以降)。
//
// 注意 (mvdan-sh の実型。fixture は test/agents/golden/plan_ast_fixtures.json、解説は docs/research/agents/mvdan-sh-ast-fixtures.md):
//   - Lit の Value は引用外・二重引用符内ともバックスラッシュを残した原文のまま。`*` `{a,b}` `~/x` `a=~` も Lit なので、
//     「展開されない単語」の判定 (表 L) はこのファイルで行う。`Lit` かどうかでは決めない。
//   - `$'…'` は SglQuoted{Dollar}、`$"…"` は DblQuoted{Dollar}。復号せず unk (ansi-c・locale)。
//   - コメントは既定の解析では捨てられるので、KeepComments を付けた解析器を使う (complex の判定に要る)。
//
// node の型除去でそのまま動く書き方だけを使う (enum・namespace は使わない)。
// see docs/spec/guard/pi-decide.md#解析結果-plan-と-literal-の定義表
import type { Tables } from "./context.ts";
import { newCtx } from "./context.ts";
import { basename, pyLen, pyRegex } from "./pystr.ts";
import { expandCdTargets, splitHeredocBody } from "./shared.ts";
import type { Src } from "./syntax.ts";
import { arr, currentSyntax, cut, end, loadSyntax, pos, typeOf } from "./syntax.ts";

// ─── 型 (契約 v1 の A 節 + v2 の差分) ─────────────────────────────────

/** 原文の UTF-8 バイト位置 [a, b)。入れ子 (`bash -c` の中など) は、入れ子を含む最外の語の位置 */
export type Span = readonly [a: number, b: number];
export type UnkWhy = "param" | "cmdsubst" | "arith" | "procsubst" | "ansi-c" | "locale" | "extglob";
export type Word =
	| { k: "lit"; v: string; raw: string; span: Span }
	| { k: "tilde"; v: string; raw: string; span: Span }
	| { k: "pat"; raw: string; span: Span }
	| { k: "unk"; raw: string; span: Span; why: UnkWhy; refs?: string[] };
export type Via = { name: string; transparent: boolean; opts: string[]; appendsArgs: boolean; target?: string };
export type Cwd = { k: "caller" } | { k: "chain"; steps: readonly Word[] } | { k: "unknown" };
export type Sub = null | "cmdsubst" | "subshell" | "hdoc" | "-c" | "ssh" | "find-exec" | "xargs" | "procsubst" | "herestr" | "launcher";
export type ExecSite = {
	id: number;
	parent: number | null;
	depth: number;
	argv: Word[];
	rawArgv: Word[];
	assigns: { name: string; value: Word | null; span: Span }[];
	redirs: { fd: string; op: string; target: Word | null; hdoc?: { body: string; quoted: boolean }; span: Span }[];
	via: Via[];
	cmd: string | null;
	cwd: Cwd;
	/** 拒否側専用の view (許可の被覆には使わない) */
	tails: Word[][];
	/** 拒否側専用。git などのグローバルオプションを除いた view (元の argv も先頭に保持) */
	denyViews: Word[][];
	ctl: { pipe: boolean; bg: boolean; neg: boolean; sub: Sub };
	span: Span;
};
export type OpaqueKind = "interp-body" | "eval" | "source" | "nonlit-c" | "hdoc-to-interp" | "alias" | "func";
export type Opaque = { kind: OpaqueKind; text: string | null; span: Span };
export type PlanFail = "load" | "sha" | "eval" | "syntax" | "ctl" | "limit:len" | "limit:sites" | "limit:depth" | "limit:words" | "throw";
export type Plan =
	| {
			ok: true;
			source: string;
			sites: ExecSite[];
			opaque: Opaque[];
			complex: boolean;
			/** source 全体で `NAME=値` として可視の名前 (旧 normalize の近似展開と同じ字句の範囲) */
			varsVisible: ReadonlySet<string>;
			/** 旧検査用 (G7 で削除)。heredoc 書換え後・ssh 展開後の文字列など */
			legacy: { cmd: string; remote: boolean; cdVariant: string };
	  }
	| { ok: false; source: string; why: PlanFail; detail: string };

export const LIMITS = { len: 10000, sites: 200, depth: 4, words: 4000 } as const;

export type AnalyzeOpts = {
	sshTargets: readonly string[];
	/** vendor/mvdan-sh のディレクトリ (試験用の注入。本番は省略) */
	vendorDir?: string;
	/** legacy.cmd の heredoc 書換えに使う表 (省略時は書換えない) */
	tables?: Tables;
	/** legacy.cmd の ssh 展開 (bash.ts の unwrapRemoteExec。配線時に注入する。省略時は展開しない) */
	unwrapRemote?: (cmd: string, targets: readonly string[]) => string | null;
};

// ─── 固定の表 ───────────────────────────────────────────────────

// normalize.ts の WRAPPERS と同じ (G7 で一本化する)。xargs・parallel は入れ子の site にするので、ここでは剥がさない
const WRAPPERS = new Map<string, string>([
	["env", "flags"],
	["command", "flags"],
	["builtin", "flags"],
	["exec", "flags"],
	["nohup", "flags"],
	["setsid", "flags"],
	["stdbuf", "flags+args"],
	["nice", "flags+args"],
	["ionice", "flags+args"],
	["timeout", "duration"],
	["time", "flags"],
	["sudo", "flags+args"],
	["doas", "flags+args"],
	["proot", "flags+args"],
	["chroot", "flags+args"],
	["unshare", "flags+args"],
	["systemd-run", "flags+args"],
	["runuser", "flags+args"],
	["pkexec", "flags"],
	["run0", "flags+args"],
	["setpriv", "flags+args"],
	["capsh", "flags+args"],
	["watch", "flags+args"],
	["strace", "flags+args"],
	["ltrace", "flags+args"],
	["perf", "flags+args"],
	["valgrind", "flags+args"],
	["flock", "flags+args"],
	["ssh-agent", "flags"],
	["setarch", "flags+args"],
	["taskset", "flags+args"],
	["torify", "flags"],
	["torsocks", "flags"],
	["entr", "flags"],
	["watchexec", "flags+args"],
	["mise", "flags"],
]);
const NESTED_WRAPPERS = new Set(["xargs", "parallel"]);
const TRANSPARENT = new Set(["env", "command", "nohup", "time", "timeout"]);
// 値を取るオプション (長さ 2 の規則では取れないもの)
const VALUE_FLAGS = new Map<string, Set<string>>([
	["env", new Set(["-u", "-C", "-S", "--unset", "--chdir", "--split-string"])],
	["sudo", new Set(["-u", "-g", "-h", "-p", "-C", "-r", "-t", "-T", "-U", "-D", "--user", "--group", "--host", "--prompt"])],
	["doas", new Set(["-u", "-C"])],
]);
const RUNNER_SUBCOMMANDS = new Set(["exec", "run", "run-script", "x", "dlx"]);
const FIND_EXEC_FLAGS = new Set(["-exec", "-execdir", "-ok", "-okdir"]);
const SHELL_BINS = new Set(["sh", "bash", "zsh", "dash", "ksh", "fish", "ash", "script", "su", "busybox"]);
const SHELL_HDOC = new Set(["sh", "bash", "zsh", "dash", "ksh", "ash"]);
const INTERPRETER_FLAGS = new Map<string, string[]>([
	["python", ["-c"]],
	["perl", ["-e", "-E"]],
	["ruby", ["-e"]],
	["node", ["-e", "--eval", "-p", "--print"]],
	["php", ["-r"]],
	["deno", ["eval"]],
]);
const GLOBAL_OPTS = new Set(["git", "docker", "gh", "npm", "uv", "cargo", "kubectl", "systemctl", "chezmoi"]);
const GH_VALUE_FLAGS = new Set(["-R", "--repo", "--hostname"]);
const GIT_VALUE_FLAGS = new Set(["-C", "-c", "--git-dir", "--work-tree", "--namespace", "--super-prefix", "--config-env", "--attr-source"]);
const CD_NAMES = new Set(["cd", "pushd", "popd", "chdir"]);
const COMPLEX_TYPES = new Set([
	"Comment", "FuncDecl", "IfClause", "ForClause", "WhileClause", "CaseClause", "DeclClause", "LetClause", "ArithmCmd", "TestClause", "CoprocClause",
]);
// BinaryCmd の演算子の番号 (mvdan-sh 0.10.1。plan_ast_fixtures.json で固定)
const OP_AND = 10;
const OP_OR = 11;
const OP_PIPE = 12;
const OP_PIPE_ALL = 13;
const DUR_RE = /^[0-9]+(?:\.[0-9]+)?[smhd]?$/;
const NAME_EQ = /^[A-Za-z_][A-Za-z0-9_]*=/;
const OPTION_VALUE_NAME_RE = /^[A-Za-z][A-Za-z0-9_.+-]*$/;
const CTL_RE = /[\x00-\x08\x0b-\x1f]/;
const VAR_ASSIGN_SRC = "\\b([A-Za-z_][A-Za-z0-9_]*)=([^\\s;&|]+)";
const UNKNOWN: Cwd = { k: "unknown" };
const CALLER: Cwd = { k: "caller" };

class Fail extends Error {
	why: PlanFail;
	constructor(why: PlanFail, detail: string) {
		super(detail);
		this.why = why;
	}
}

const msg = (e: unknown): string => {
	const s = e instanceof Error ? e.message : String(e);
	return s === "[object Object]" ? "構文エラー" : s;
};

// ─── 単語 (表 L: literal の定義) ─────────────────────────────────────────

const RANK = { lit: 0, tilde: 1, pat: 2, unk: 3 } as const;
// unk の単語の「最後の / 以降が lit のときの basename」(cmd の導出用)。Word の型に足さないので、側表に持つ
const BASE = new WeakMap<object, string>();

/** 引用外の Lit を解く: `\c` は c (glob 記号も literal)、`\⏎` は除去。引用外の `* ? [ {` があれば glob */
function decodeUnquoted(raw: string): { v: string; glob: boolean } {
	let v = "";
	let glob = false;
	for (let i = 0; i < raw.length; i++) {
		const c = raw[i];
		if (c === "\\") {
			if (i + 1 < raw.length) {
				i++;
				if (raw[i] !== "\n") v += raw[i];
			} else v += "\\";
			continue;
		}
		if (c === "*" || c === "?" || c === "[" || c === "{") glob = true;
		v += c;
	}
	return { v, glob };
}

/** 二重引用符内の Lit を解く: 外すのは `\$` `` \` `` `\"` `\\` `\⏎` だけ。ほかの `\c` は 2 文字とも残す */
function decodeDq(raw: string): string {
	let v = "";
	for (let i = 0; i < raw.length; i++) {
		const c = raw[i];
		if (c === "\\" && i + 1 < raw.length) {
			const d = raw[i + 1];
			if (d === "$" || d === "`" || d === '"' || d === "\\") {
				v += d;
				i++;
				continue;
			}
			if (d === "\n") {
				i++;
				continue;
			}
		}
		v += c;
	}
	return v;
}

function refsOf(n: any, arith: boolean): string[] {
	const S = currentSyntax();
	const out: string[] = [];
	const add = (s: string): void => {
		if (!out.includes(s)) out.push(s);
	};
	S.Walk(n, (x: any) => {
		if (!x) return false;
		const t = String(S.NodeType(x));
		if (t === "ParamExp" && x.Param) add(String(x.Param.Value));
		else if (arith && t === "Lit" && /^[A-Za-z_][A-Za-z0-9_]*$/.test(String(x.Value))) add(String(x.Value));
		return true;
	});
	return out;
}

/** 部品の、実行時にも変わらない文字列 (変わるものは null) */
function staticText(p: any): string | null {
	switch (typeOf(p)) {
		case "Lit":
			return decodeUnquoted(String(p.Value)).v;
		case "SglQuoted":
			return p.Dollar ? null : String(p.Value);
		case "DblQuoted": {
			if (p.Dollar) return null;
			let s = "";
			for (const q of arr(p.Parts)) {
				if (typeOf(q) !== "Lit") return null;
				s += decodeDq(String(q.Value));
			}
			return s;
		}
		default:
			return null;
	}
}

/** 構文木の Word を表 L に従って分類する。引用・連結・glob・brace・`~`・ANSI-C・`\⏎` を扱う */
function classifyWord(node: any, src: Src, outer: Span | null): Word {
	const parts = arr(node.Parts);
	const raw = cut(src, pos(node), end(node));
	const span: Span = outer ?? [pos(node), end(node)];
	let v = "";
	let rank = 0;
	let why: UnkWhy = "param";
	let refs: string[] = [];
	let tilde = false;
	const bump = (r: number, w?: UnkWhy, rf?: string[]): void => {
		if (r === RANK.unk) {
			if (rank < RANK.unk) why = w ?? "param";
			for (const x of rf ?? []) if (!refs.includes(x)) refs.push(x);
		}
		if (r > rank) rank = r;
	};
	parts.forEach((p, idx) => {
		const t = typeOf(p);
		switch (t) {
			case "Lit": {
				const r = String(p.Value);
				if (idx === 0 && r.startsWith("~")) {
					if (/^~(?:\/|$)/.test(r) && (r !== "~" || parts.length === 1)) tilde = true;
					else bump(RANK.pat);
				}
				if (idx === 0 && NAME_EQ.test(r) && /(?:^|:)~/.test(r.slice(r.indexOf("=") + 1))) bump(RANK.pat);
				const d = decodeUnquoted(r);
				v += d.v;
				if (d.glob) bump(RANK.pat);
				break;
			}
			case "SglQuoted":
				if (p.Dollar) bump(RANK.unk, "ansi-c");
				else v += String(p.Value);
				break;
			case "DblQuoted":
				if (p.Dollar) {
					bump(RANK.unk, "locale", refsOf(p, false));
					break;
				}
				for (const q of arr(p.Parts)) {
					const qt = typeOf(q);
					if (qt === "Lit") v += decodeDq(String(q.Value));
					else if (qt === "CmdSubst") bump(RANK.unk, "cmdsubst", refsOf(q, false));
					else if (qt === "ArithmExp") bump(RANK.unk, "arith", refsOf(q, true));
					else bump(RANK.unk, "param", refsOf(q, false));
				}
				break;
			case "CmdSubst":
				bump(RANK.unk, "cmdsubst", refsOf(p, false));
				break;
			case "ArithmExp":
				bump(RANK.unk, "arith", refsOf(p, true));
				break;
			case "ProcSubst":
				bump(RANK.unk, "procsubst", refsOf(p, false));
				break;
			case "ExtGlob":
				bump(RANK.unk, "extglob");
				break;
			default:
				// ParamExp ほか
				bump(RANK.unk, "param", refsOf(p, false));
		}
	});
	if (rank === RANK.unk) {
		const w: Word = { k: "unk", raw, span, why };
		if (refs.length > 0) w.refs = refs;
		// 最後の `/` 以降が静的なら、その basename を覚える
		let tail = "";
		for (let i = parts.length - 1; i >= 0; i--) {
			const s = staticText(parts[i]);
			if (s === null) break;
			tail = s + tail;
		}
		const slash = tail.lastIndexOf("/");
		if (slash >= 0) BASE.set(w, tail.slice(slash + 1));
		return w;
	}
	if (rank === RANK.pat) return { k: "pat", raw, span };
	if (tilde) return { k: "tilde", v: v.startsWith("~/") ? v.slice(2) : "", raw, span };
	return { k: "lit", v, raw, span };
}

/** 比較・分解に使う文字列。lit は値、それ以外は原文 */
const tok = (w: Word): string => (w.k === "lit" ? w.v : w.raw);
const looksLikeOptionValue = (t: string): boolean => !t.startsWith("-") && !OPTION_VALUE_NAME_RE.test(t);

/** argv[0] の basename。unk でも最後の `/` 以降が lit ならそれ */
function cmdOf(w: Word | undefined): string | null {
	if (!w) return null;
	if (w.k === "lit" || w.k === "tilde") return basename(w.v);
	if (w.k === "unk") return BASE.get(w) ?? null;
	return null;
}

const litHead = (w: Word | undefined): string | null => (w && w.k === "lit" ? basename(w.v) : null);

// ─── ラッパーの剥がし (normalize.ts の stripWrapper を Word で移植) ─────────────

type Stripped = { rest: Word[]; opts: string[]; dur: Word | null; envAssigns: Word[] };

function stripOne(name: string, style: string, words: Word[]): Stripped | null {
	const valFlags = VALUE_FLAGS.get(name);
	const opts: string[] = [];
	const envAssigns: Word[] = [];
	let dur: Word | null = null;
	let i = 1;
	while (i < words.length) {
		const w = words[i];
		const t = tok(w);
		if (t === "--") {
			i++;
			break;
		}
		if (t.startsWith("-")) {
			if (valFlags?.has(t) && i + 1 < words.length) {
				opts.push(t, tok(words[i + 1]));
				i += 2;
				continue;
			}
			if ((style === "flags+args" || style === "duration") && !t.includes("=") && pyLen(t) === 2) {
				const nxt = i + 1 < words.length ? tok(words[i + 1]) : null;
				if (nxt !== null && looksLikeOptionValue(nxt)) {
					opts.push(t, nxt);
					i += 2;
					continue;
				}
			}
			opts.push(t);
			i++;
			continue;
		}
		if (style === "duration" && dur === null && (DUR_RE.test(t) || w.k !== "lit")) {
			dur = w;
			i++;
			continue;
		}
		if (style === "flags+args" && looksLikeOptionValue(t) && i + 1 < words.length) {
			opts.push(t);
			i++;
			continue;
		}
		if (t.includes("=") && !t.startsWith("/")) {
			if (NAME_EQ.test(t)) envAssigns.push(w);
			i++;
			continue;
		}
		break;
	}
	const rest = words.slice(i);
	if (rest.length === 0) return null;
	return { rest, opts, dur, envAssigns };
}

/** `NAME=値` の語を assigns の 1 件にする (値は語の `=` の後ろ。lit 以外は同じ種別・原文のまま) */
function assignFromWord(w: Word): ExecSite["assigns"][number] {
	const r = w.raw;
	const eq = r.indexOf("=");
	const name = r.slice(0, eq);
	let value: Word;
	if (w.k === "lit") value = { k: "lit", v: w.v.slice(w.v.indexOf("=") + 1), raw: r.slice(eq + 1), span: w.span };
	else value = { ...w, raw: r.slice(eq + 1) } as Word;
	return { name, value, span: w.span };
}

/** git などのグローバルオプションを除いた view (除くものが無ければ null)。値が unk でも除ける */
function stripGlobalW(words: Word[]): Word[] | null {
	const head = litHead(words[0]);
	if (head === null || !GLOBAL_OPTS.has(head) || words.length < 2) return null;
	let i = 1;
	while (i < words.length && tok(words[i]).startsWith("-")) {
		const t = tok(words[i]);
		if (t === "--") {
			i++;
			break;
		}
		if (head === "git") {
			i += GIT_VALUE_FLAGS.has(t) && i + 1 < words.length ? 2 : 1;
			continue;
		}
		if (head === "gh" && GH_VALUE_FLAGS.has(t) && i + 1 < words.length) {
			i += 2;
			continue;
		}
		if (!t.includes("=") && pyLen(t) === 2 && i + 1 < words.length && looksLikeOptionValue(tok(words[i + 1]))) {
			i += 2;
			continue;
		}
		i++;
	}
	if (i <= 1 || i >= words.length) return null;
	return [words[0], ...words.slice(i)];
}

// ─── 解析本体 ───────────────────────────────────────────────────

type Env = { src: Src; outer: Span | null; depth: number; parent: number | null; sub: Sub; via: Via[] };
type Leaf = { st: any; pipe: boolean; bg: boolean; neg: boolean; first: boolean };
type Ctl = { pipe: boolean; bg: boolean; neg: boolean };
type Mode = "top" | "nested";

function parseText(text: string): Src {
	const S = currentSyntax();
	try {
		if (typeof S.KeepComments !== "function") throw new Error("KeepComments が無い");
		const parser = S.NewParser(S.Variant(S.LangBash), S.KeepComments(true));
		return { buf: Buffer.from(text, "utf8"), file: parser.Parse(text, "") };
	} catch (e) {
		throw new Fail("syntax", `解析に失敗: ${msg(e)}`);
	}
}

class Analyzer {
	sites: ExecSite[] = [];
	opaque: Opaque[] = [];
	complex = false;
	words = 0;
	readonly taint: boolean;
	readonly targets: readonly string[];

	constructor(targets: readonly string[], source: string) {
		this.targets = targets;
		// 関数・alias の定義がある原文では、cd の効果が分からないので chain を作らない
		// CDPATH は cd の行き先を変える (環境から来る CDPATH は paths.ts 側の限界)
		this.taint = /(?:^|[\s;&|(])(?:alias|unalias|function)\b|\w+\s*\(\s*\)\s*\{|CDPATH/.test(source);
	}

	// ── 入口 ──

	run(src: Src): void {
		this.scan(src);
		this.walkList(arr(src.file.Stmts), { src, outer: null, depth: 0, parent: null, sub: null, via: [] }, CALLER, "top");
	}

	private scan(src: Src): void {
		const S = currentSyntax();
		S.Walk(src.file, (n: any) => {
			if (n && COMPLEX_TYPES.has(String(S.NodeType(n)))) this.complex = true;
			return true;
		});
	}

	private count(n: number): void {
		this.words += n;
		if (this.words > LIMITS.words) throw new Fail("limit:words", `語が ${LIMITS.words} 個を超えた`);
	}

	private word(n: any, env: Env): Word {
		return classifyWord(n, env.src, env.outer);
	}

	// ── 文の列 ──

	private walkList(stmts: any[], env: Env, S0: Cwd, mode: Mode): Cwd {
		let S = S0;
		for (const st of stmts) S = this.walkStmt(st, env, S, mode);
		return S;
	}

	private flatten(st: any, inh: Ctl & { first: boolean }, out: Leaf[]): void {
		const bg = inh.bg || !!st.Background;
		const neg = inh.neg || !!st.Negated;
		const c = st.Cmd;
		if (c && typeOf(c) === "BinaryCmd") {
			const op = Number(c.Op);
			if (op === OP_AND || op === OP_OR) {
				this.flatten(c.X, { pipe: inh.pipe, bg, neg, first: inh.first }, out);
				this.flatten(c.Y, { pipe: inh.pipe, bg, neg, first: false }, out);
			} else if (op === OP_PIPE || op === OP_PIPE_ALL) {
				this.flatten(c.X, { pipe: true, bg, neg, first: false }, out);
				this.flatten(c.Y, { pipe: true, bg, neg, first: false }, out);
			} else throw new Fail("throw", `未知の BinaryCmd 演算子 ${op}`);
		} else out.push({ st, pipe: inh.pipe, bg, neg, first: inh.first });
	}

	/** 文に `||` が含まれるか (cd が失敗したときだけ後ろが走る形は、cwd を決められない) */
	private hasOr(st: any): boolean {
		const c = st?.Cmd;
		if (!c || typeOf(c) !== "BinaryCmd") return false;
		return Number(c.Op) === OP_OR || this.hasOr(c.X) || this.hasOr(c.Y);
	}

	private walkStmt(st: any, env: Env, S0: Cwd, mode: Mode): Cwd {
		const leaves: Leaf[] = [];
		this.flatten(st, { pipe: false, bg: false, neg: false, first: true }, leaves);
		const orStmt = this.hasOr(st);
		let S = S0;
		for (const lf of leaves) {
			this.processLeaf(lf, env, S);
			const kind = this.cdKind(lf, env);
			if (kind === null) continue;
			if (kind !== "none" && mode === "top" && !orStmt && lf.first && !lf.bg && !lf.pipe && typeof kind === "object") {
				S = S.k === "unknown" ? S : { k: "chain", steps: [...(S.k === "chain" ? S.steps : []), kind.word] };
			} else if (kind !== "none") S = UNKNOWN;
		}
		return S;
	}

	/** 葉の文の cd の種類。null / "none" = 影響なし、{word} = 単純な `cd <lit|tilde>`、"like" = それ以外の cd 風 */
	private cdKind(lf: Leaf, env: Env): null | "none" | "like" | { word: Word } {
		const c = lf.st.Cmd;
		const t = typeOf(c);
		if (t === "Subshell") return "none";
		if (c && t !== "CallExpr") return this.hasCdLike(c) ? "like" : "none";
		if (!c) return "none";
		const args = arr(c.Args);
		const lits = args.slice(0, 3).map((a) => this.litOfNode(a));
		const hasCd = lits.some((x) => x !== null && CD_NAMES.has(x));
		if (!hasCd) return "none";
		if (this.taint || lits[0] !== "cd" || args.length !== 2 || arr(c.Assigns).length > 0 || arr(lf.st.Redirs).length > 0) return "like";
		const w = this.word(args[1], env);
		if ((w.k === "lit" && !w.v.startsWith("-") && w.v !== "") || w.k === "tilde") return { word: w };
		return "like";
	}

	private litOfNode(w: any): string | null {
		const ps = arr(w.Parts);
		return ps.length === 1 && typeOf(ps[0]) === "Lit" ? basename(String(ps[0].Value)) : null;
	}

	private hasCdLike(node: any): boolean {
		const S = currentSyntax();
		let found = false;
		S.Walk(node, (n: any) => {
			if (!n || found) return false;
			if (String(S.NodeType(n)) === "CallExpr") {
				if (arr(n.Args).slice(0, 3).some((a) => {
					const l = this.litOfNode(a);
					return l !== null && CD_NAMES.has(l);
				})) found = true;
			}
			return true;
		});
		return found;
	}

	// ── 葉 ──

	private processLeaf(lf: Leaf, env: Env, S: Cwd): void {
		const st = lf.st;
		const c = st.Cmd;
		const t = typeOf(c);
		const ctl: Ctl = { pipe: lf.pipe, bg: lf.bg, neg: lf.neg };
		if (!c || t === "CallExpr") {
			this.callSite(st, c, ctl, env, S);
			return;
		}
		// 複合コマンド自体へのリダイレクト (`(cd x) > out`) は、argv が空の site に残す
		if (t !== "DeclClause" && arr(st.Redirs).length > 0) this.callSite(st, null, ctl, env, S);
		switch (t) {
			case "Subshell":
			case "Block":
				this.walkList(arr(c.Stmts), { ...env, sub: "subshell" }, S, "nested");
				return;
			case "TimeClause":
				if (c.Stmt) {
					const via: Via = { name: "time", transparent: !c.PosixFormat, opts: c.PosixFormat ? ["-p"] : [], appendsArgs: false };
					this.walkStmt(c.Stmt, { ...env, via: [...env.via, via] }, S, "nested");
				}
				return;
			case "DeclClause":
				this.complex = true;
				this.declSite(st, c, ctl, env, S);
				return;
			default:
				this.complex = true;
				if (t === "FuncDecl") this.opaque.push({ kind: "func", text: cut(env.src, pos(c), end(c)), span: env.outer ?? [pos(c), end(c)] });
				this.walkCompound(c, env);
		}
	}

	/** if/for/while/case・関数・[[ ]] などの中身: 構文木を歩いて、見つけた文・置換を site にする (cwd は unknown) */
	private walkCompound(node: any, env: Env): void {
		const Sy = currentSyntax();
		Sy.Walk(node, (n: any) => {
			if (!n) return false;
			const t = String(Sy.NodeType(n));
			if (t === "Stmt") {
				const c = n.Cmd;
				const ct = c ? typeOf(c) : "";
				if (!c || ["CallExpr", "DeclClause", "TimeClause", "Subshell", "Block", "BinaryCmd"].includes(ct)) {
					this.walkList([n], env, UNKNOWN, "nested");
					return false;
				}
				if (arr(n.Redirs).length > 0) this.callSite(n, null, { pipe: false, bg: false, neg: false }, env, UNKNOWN);
				return true;
			}
			if (t === "CmdSubst" || t === "ProcSubst") {
				this.nestedList(n, env, env.parent, UNKNOWN);
				return false;
			}
			return true;
		});
	}

	/** コマンド置換・プロセス置換の中身を、入れ子の site にする */
	private nestedList(n: any, env: Env, parent: number | null, S: Cwd): void {
		const t = typeOf(n);
		const env2: Env = { ...env, depth: env.depth + 1, parent, sub: t === "ProcSubst" ? "procsubst" : "cmdsubst", via: [] };
		this.checkDepth(env2.depth);
		// コマンド置換・プロセス置換の中の cd は、外側へ積まない (中の後続も unknown。契約 M1)
		this.walkList(arr(n.Stmts), env2, S, "nested");
	}

	private substs(nodes: any[], env: Env, parent: number | null, S: Cwd): void {
		const Sy = currentSyntax();
		for (const node of nodes) {
			if (!node) continue;
			Sy.Walk(node, (n: any) => {
				if (!n) return false;
				const t = String(Sy.NodeType(n));
				if (t === "CmdSubst" || t === "ProcSubst") {
					this.nestedList(n, env, parent, S);
					return false;
				}
				return true;
			});
		}
	}

	private checkDepth(d: number): void {
		if (d > LIMITS.depth) throw new Fail("limit:depth", `入れ子が ${LIMITS.depth} 段を超えた`);
	}

	// ── 単純コマンド ──

	private redirOf(r: any, env: Env): ExecSite["redirs"][number] {
		const start = r.N ? end(r.N) : pos(r);
		const op = cut(env.src, start, pos(r.Word)).trim();
		const fd = r.N ? String(r.N.Value) : "";
		const span: Span = env.outer ?? [pos(r), end(r)];
		if (r.Hdoc) {
			const delim = cut(env.src, pos(r.Word), end(r.Word));
			let body = arr(r.Hdoc.Parts).map((p: any) => (typeOf(p) === "Lit" ? String(p.Value) : cut(env.src, pos(p), end(p)))).join("");
			if (body.endsWith("\n")) body = body.slice(0, -1);
			if (op === "<<-") body = body.replace(/^\t+/gm, "");
			return { fd, op, target: null, hdoc: { body, quoted: /['"\\]/.test(delim) }, span };
		}
		return { fd, op, target: this.word(r.Word, env), span };
	}

	private assignOf(a: any, env: Env): ExecSite["assigns"][number] {
		const span: Span = env.outer ?? [pos(a), end(a)];
		const name = a.Name ? String(a.Name.Value) : "";
		if (a.Value) return { name, value: this.word(a.Value, env), span };
		if (a.Array) return { name, value: null, span };
		return { name, value: { k: "lit", v: "", raw: "", span }, span };
	}

	private callSite(st: any, call: any, ctl: Ctl, env: Env, S: Cwd): void {
		const rawWords = arr(call?.Args).map((w: any) => this.word(w, env));
		const assigns = arr(call?.Assigns).map((a: any) => this.assignOf(a, env));
		const redirs = arr(st.Redirs).map((r: any) => this.redirOf(r, env));
		this.count(rawWords.length + assigns.length + redirs.length);
		const site = this.makeSite({
			raw: rawWords, assigns, redirs, ctl, env, S, span: env.outer ?? [pos(st), end(st)],
		});
		this.substs([...arr(call?.Assigns), ...arr(call?.Args), ...arr(st.Redirs)], env, site.id, S);
	}

	private declSite(st: any, c: any, ctl: Ctl, env: Env, S: Cwd): void {
		const span: Span = env.outer ?? [pos(st), end(st)];
		const head: Word = { k: "lit", v: String(c.Variant.Value), raw: String(c.Variant.Value), span };
		const args: Word[] = arr(c.Args).map((a: any) => {
			const raw = cut(env.src, pos(a), end(a));
			if (a.Naked && a.Value) return this.word(a.Value, env);
			const asg = this.assignOf(a, env);
			const val = asg.value;
			if (val === null) return { k: "unk", raw, span, why: "param" } as Word;
			if (val.k === "lit") return { k: "lit", v: `${asg.name}=${val.v}`, raw, span } as Word;
			if (val.k === "tilde") return { k: "pat", raw, span } as Word;
			return { ...val, raw } as Word;
		});
		const redirs = arr(st.Redirs).map((r: any) => this.redirOf(r, env));
		this.count(args.length + redirs.length + 1);
		const site = this.makeSite({ raw: [head, ...args], assigns: [], redirs, ctl, env, S, span });
		this.substs([...arr(c.Args), ...arr(st.Redirs)], env, site.id, S);
	}

	private makeSite(a: {
		raw: Word[]; assigns: ExecSite["assigns"]; redirs: ExecSite["redirs"]; ctl: Ctl; env: Env; S: Cwd; span: Span;
	}): ExecSite {
		const { env } = a;
		this.checkDepth(env.depth);
		const via: Via[] = [...env.via];
		const assigns = [...a.assigns];
		let cur = a.raw;
		for (let n = 0; n < 8 && cur.length > 0; n++) {
			const h = cur[0];
			if (h.k !== "lit") break;
			const name = basename(h.v);
			const style = WRAPPERS.get(name);
			if (style === undefined) break;
			const r = stripOne(name, style, cur);
			if (!r) break;
			via.push({
				name,
				transparent: TRANSPARENT.has(name) && r.opts.length === 0 && (name !== "timeout" || r.dur?.k === "lit"),
				opts: r.opts,
				appendsArgs: false,
			});
			for (const w of r.envAssigns) assigns.push(assignFromWord(w));
			cur = r.rest;
		}
		const site: ExecSite = {
			id: this.sites.length, parent: env.parent, depth: env.depth, argv: cur, rawArgv: a.raw, assigns, redirs: a.redirs, via,
			cmd: cmdOf(cur[0]), cwd: a.S, tails: [], denyViews: [],
			ctl: { pipe: a.ctl.pipe, bg: a.ctl.bg, neg: a.ctl.neg, sub: env.sub }, span: a.span,
		};
		if (this.sites.length >= LIMITS.sites) throw new Fail("limit:sites", `実行箇所が ${LIMITS.sites} を超えた`);
		this.sites.push(site);
		this.special(site, env);
		site.denyViews = site.argv.length > 0 ? [site.argv] : [];
		const g = stripGlobalW(site.argv);
		if (g) site.denyViews.push(g);
		return site;
	}

	// ── 入れ子 (bash -c・ssh・find -exec・xargs・heredoc・here-string・interpreter・eval) ──

	/** 文字列を別に解析して、入れ子の site にする。失敗は Fail("syntax") (tolerant なら握りつぶす) */
	private nestedText(text: string, site: ExecSite, env: Env, sub: Sub, outer: Span, tolerant: boolean, via: Via[] = []): boolean {
		const env2: Env = { src: env.src, outer, depth: env.depth + 1, parent: site.id, sub, via };
		this.checkDepth(env2.depth);
		let src: Src;
		try {
			src = parseText(text);
		} catch (e) {
			if (tolerant && e instanceof Fail && e.why === "syntax") return false;
			throw e;
		}
		this.scan(src);
		this.walkList(arr(src.file.Stmts), { ...env2, src }, site.cwd, "top");
		return true;
	}

	private nestedWords(words: Word[], site: ExecSite, env: Env, sub: Sub, via: Via[]): void {
		const env2: Env = { ...env, depth: env.depth + 1, parent: site.id, sub, via };
		this.count(words.length);
		this.makeSite({ raw: words, assigns: [], redirs: [], ctl: site.ctl, env: env2, S: site.cwd, span: site.span });
	}

	private special(site: ExecSite, env: Env): void {
		const argv = site.argv;
		const head = litHead(argv[0]);
		const tails: Word[][] = [];
		const span = site.span;

		// ssh: 許可宛先で、宛先の後ろが全部 lit なら、リモートの文字列を入れ子の site にする (外側の argv は空にして via に残す)
		if (head === "ssh" && argv.length >= 3 && argv[1].k === "lit" && this.targets.includes(argv[1].v) && !argv[1].v.startsWith("-")) {
			const remote = argv.slice(2);
			if (remote.every((w) => w.k === "lit")) {
				const text = remote.map((w) => tok(w)).join(" ");
				const ok = this.nestedText(text, site, env, "ssh", [remote[0].span[0], remote[remote.length - 1].span[1]], true);
				if (ok) {
					site.via.push({ name: "ssh", transparent: true, opts: [], appendsArgs: false, target: argv[1].v });
					site.argv = [];
					site.cmd = null;
					return this.finishSite(site, tails);
				}
			}
		}

		if (head !== null) {
			const hdoc = site.redirs.find((r) => r.hdoc);
			// シェルの -c
			if (SHELL_BINS.has(head)) {
				let ci = -1;
				for (let i = 1; i < argv.length; i++) {
					const t = tok(argv[i]);
					if (argv[i].k === "lit" && t.startsWith("-") && !t.startsWith("--") && t.includes("c")) {
						ci = i;
						break;
					}
				}
				if (ci >= 0 && ci + 1 < argv.length) {
					const code = argv[ci + 1];
					if (code.k === "lit") this.nestedText(code.v, site, env, "-c", code.span, false);
					else this.opaque.push({ kind: "nonlit-c", text: null, span: code.span });
				} else if (ci < 0 && hdoc?.hdoc && SHELL_HDOC.has(head) && argv.slice(1).every((w) => w.k === "lit" && w.v.startsWith("-"))) {
					this.nestedText(hdoc.hdoc.body, site, env, "hdoc", hdoc.span, false);
				}
			}
			// ssh の標準入力 (リモートのシェルが読む)
			if (head === "ssh" && argv.length <= 2) {
				const hd = site.redirs.find((r) => r.hdoc);
				if (hd?.hdoc) this.nestedText(hd.hdoc.body, site, env, "hdoc", hd.span, false);
			}
			// インタプリタ
			const iname = head.length > 1 ? head.replace(/[0-9.]+$/, "") : head;
			const flags = INTERPRETER_FLAGS.get(iname);
			if (flags) {
				const i = argv.findIndex((w, k) => k > 0 && w.k === "lit" && flags.includes(w.v));
				if (i >= 0) {
					const code = argv[i + 1];
					this.opaque.push({ kind: "interp-body", text: code && code.k === "lit" ? code.v : null, span: code?.span ?? span });
				} else if (hdoc?.hdoc && argv.length === 1) {
					this.opaque.push({ kind: "hdoc-to-interp", text: hdoc.hdoc.body, span: hdoc.span });
				}
			}
			if (head === "eval" || head === "source" || head === ".") {
				const rest = argv.slice(1);
				this.opaque.push({
					kind: head === "eval" ? "eval" : "source", text: rest.every((w) => w.k === "lit") ? rest.map(tok).join(" ") : null, span,
				});
				if (rest.length > 0) tails.push(rest);
			}
			if (head === "trap" && argv.length > 1) tails.push([argv[1]]);
			if (head === "alias") this.opaque.push({ kind: "alias", text: argv.slice(1).map(tok).join(" "), span });
			// find -exec
			if (head === "find") {
				for (let i = 1; i < argv.length; i++) {
					if (argv[i].k !== "lit" || !FIND_EXEC_FLAGS.has(argv[i].v as string)) continue;
					const rest: Word[] = [];
					let j = i + 1;
					while (j < argv.length && !(argv[j].k === "lit" && (tok(argv[j]) === ";" || tok(argv[j]) === "+"))) rest.push(argv[j++]);
					if (rest.length > 0) {
						this.nestedWords(rest, site, env, "find-exec", [{ name: "find-exec", transparent: false, opts: [], appendsArgs: true }]);
					}
					i = j;
				}
			}
			// xargs・parallel
			if (NESTED_WRAPPERS.has(head)) {
				const r = stripOne(head, "flags+args", argv);
				if (r) {
					let rest = r.rest;
					const sep = rest.findIndex((w) => w.k === "lit" && (w.v === ":::" || w.v === "::::"));
					if (sep >= 0) rest = rest.slice(0, sep);
					if (rest.length > 0) this.nestedWords(rest, site, env, "xargs", [{ name: head, transparent: false, opts: r.opts, appendsArgs: true }]);
				}
			}
		}
		// here-string: 本文を入れ子の site にし (tolerant)、語を tails に残す
		for (const r of site.redirs) {
			if (r.op === "<<<" && r.target && r.target.k === "lit") {
				const first = this.sites.length;
				this.nestedText(r.target.v, site, env, "herestr", r.span, true);
				for (const s of this.sites.slice(first)) if (s.parent === site.id && s.argv.length > 0) tails.push(s.argv);
			}
		}
		this.finishSite(site, tails);
	}

	/** tails (旧 expandEmbeddedCommands と同じ範囲) を組み立てる */
	private finishSite(site: ExecSite, tails: Word[][]): void {
		const views = site.argv === site.rawArgv ? [site.argv] : [site.argv, site.rawArgv];
		for (const t of views) {
			const h = litHead(t[0]);
			if (h === null || h === "find") continue;
			const vals = t.map(tok);
			if (["screen", "tmux", "at", "batch", "entr", "watchexec"].includes(h)) {
				let rest = t.slice(1).filter((w) => !tok(w).startsWith("-"));
				if (h === "tmux" && rest.length > 0 && ["new-session", "new", "new-window", "neww", "send-keys", "run-shell", "run"].includes(tok(rest[0]))) {
					rest = rest.slice(1);
				}
				if (rest.length > 0) tails.push(rest);
				continue;
			}
			if (h === "git" && t.length >= 4 && vals[1] === "submodule" && vals[2] === "foreach") {
				tails.push(t.slice(3));
				continue;
			}
			if (h === "docker" && t.length >= 3 && ["run", "exec"].includes(vals[1])) {
				let i = 2;
				while (i < t.length && vals[i].startsWith("-")) {
					if (!vals[i].includes("=") && pyLen(vals[i]) === 2 && i + 1 < t.length) {
						i += 2;
						continue;
					}
					i++;
				}
				i++;
				if (i < t.length) tails.push(t.slice(i));
				continue;
			}
			const dash = vals.indexOf("--", 1);
			if (dash >= 0 && site.cmd !== "git" && dash + 1 < t.length) tails.push(t.slice(dash + 1));
			if (["uv", "mise", "npm", "pnpm", "yarn", "cargo", "go", "poetry", "rye"].includes(h) && t.length >= 3 && RUNNER_SUBCOMMANDS.has(vals[1])) {
				const rest = t.slice(2).filter((w) => tok(w) !== "--");
				if (rest.length > 0) tails.push(rest);
			}
		}
		// 同じ view の重複は除く (`--` の後ろと runner の後ろが同じになる形)
		const seen = new Set<string>();
		site.tails = tails.filter((t) => {
			const key = t.map((w) => `${w.k}:${tok(w)}`).join("\u0000");
			if (seen.has(key)) return false;
			seen.add(key);
			return true;
		});
	}

	/** `$(echo git push)` `<(echo …)` の echo/printf の出力 (旧 echoPayloads) を、置換を含む site の tails に足す (拒否側専用) */
	echoTails(): void {
		for (const s of this.sites) {
			if (s.parent === null || (s.ctl.sub !== "cmdsubst" && s.ctl.sub !== "procsubst")) continue;
			if (s.cmd !== "echo" && s.cmd !== "printf") continue;
			const args = s.argv.slice(1).filter((w) => !tok(w).startsWith("-"));
			if (args.length > 0) this.sites[s.parent].tails.push(args);
		}
	}
}

// ─── 入口 ───────────────────────────────────────────────────────

function failure(source: string, why: PlanFail, detail: string): Plan {
	return { ok: false, source, why, detail };
}

/** 解析して Plan を返す。純関数 (読み込みの記憶以外に状態を持たない)。例外は投げない */
export function analyze(rawCmd: string, o: AnalyzeOpts): Plan {
	const source = typeof rawCmd === "string" ? rawCmd : "";
	try {
		if (typeof rawCmd !== "string") return failure(source, "throw", "コマンドが文字列でない");
		if (pyLen(source) > LIMITS.len) return failure(source, "limit:len", `コマンドが長すぎる (${pyLen(source)} 文字)`);
		if (CTL_RE.test(source)) return failure(source, "ctl", "CR・NUL などの制御文字がある (`\\t` `\\n` 以外の C0)");
		const loaded = loadSyntax(o.vendorDir);
		if (!loaded.ok) {
			const why: PlanFail = loaded.why.includes("sha256") ? "sha" : loaded.why.includes("評価") ? "eval" : "load";
			return failure(source, why, loaded.why);
		}
		const src = parseText(source);
		const A = new Analyzer(o.sshTargets, source);
		A.run(src);
		A.echoTails();
		const vars = new Set<string>();
		for (const m of source.matchAll(pyRegex(VAR_ASSIGN_SRC, "g"))) vars.add(m[1]);
		return {
			ok: true, source, sites: A.sites, opaque: A.opaque, complex: A.complex, varsVisible: vars, legacy: legacyOf(source, o),
		};
	} catch (e) {
		if (e instanceof Fail) return failure(source, e.why, e.message);
		return failure(source, "throw", msg(e));
	}
}

/** 旧検査に渡していた文字列: heredoc 書換え → ssh 展開 (bash.ts の decide と同じ順) */
function legacyOf(raw: string, o: AnalyzeOpts): { cmd: string; remote: boolean; cdVariant: string } {
	const rewrite = (c: string): string => {
		if (!o.tables) return c;
		try {
			return splitHeredocBody(newCtx(o.tables, {} as never, null), c);
		} catch {
			return c;
		}
	};
	let cmd = rewrite(raw);
	let remote = false;
	try {
		const inner = o.unwrapRemote ? o.unwrapRemote(cmd, o.sshTargets) : null;
		if (inner !== null) {
			cmd = rewrite(inner);
			remote = true;
		}
	} catch {
		// 展開できないときは外側のまま
	}
	let cdVariant = "";
	try {
		cdVariant = expandCdTargets(cmd);
	} catch {
		// 解析できないときは作らない
	}
	return { cmd, remote, cdVariant };
}
