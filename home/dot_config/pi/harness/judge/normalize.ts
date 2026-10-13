// コマンドの正規化と照合 (command_policy.py の normalize / find_match の移植)。
//
// 先頭トークンを変えるだけの飾り (cd・git -C・グルーピング・リダイレクト・環境変数・ラッパー・パス・
// グローバルオプション) を剥がし、`bash -c` / `$(...)` / here-string / 関数定義などに埋まったコードも
// 独立したセグメントとして取り出す。Python 版と同じ結果を返すことが完了条件 (正解データとの全件一致)。
//
// - 辞書引きは Map / Set で行う (`constructor` のようなコマンド名がプロトタイプに当たらない)
// - 状態を持たない (呼び出しの間で何も残さない。Python 版の `_LITERAL_HEREDOC_BODIES` のような記録を作らない)
//
// node の型除去でそのまま動く書き方だけを使う。
// see docs/spec/pi-decide.md#ts-版への移植
import {
	basename,
	isSpace,
	pyLen,
	pyRegex,
	ShlexError,
	shlexQuote,
	shlexSplit,
	split,
	splitLines,
	splitOnce,
	strip,
	stripChars,
} from "./pystr.ts";

// ─── 表 ───────────────────────────────────────────────────

// 複合演算子 (新しい論理コマンドを始める)。`&&` を先に判定するため順序が重要
const COMPOUND_OPS = ["&&", "||", ";;", ";", "|", "&", "\n"];

// コマンドをそのまま実行するラッパー。値は「コマンド名までに読み飛ばすオプションの取り方」
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
	["xargs", "flags+args"],
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
	["parallel", "flags+args"],
	["flock", "flags+args"],
	["ssh-agent", "flags"],
	["setarch", "flags+args"],
	["taskset", "flags+args"],
	["torify", "flags"],
	["torsocks", "flags"],
	["entr", "flags"],
	["watchexec", "flags+args"],
	["mise", "runner"],
]);

const RUNNER_SUBCOMMANDS = new Set(["exec", "run", "run-script", "x", "dlx"]);
const FIND_EXEC_FLAGS = new Set(["-exec", "-execdir", "-ok", "-okdir"]);
const SHELL_BINS = new Set(["sh", "bash", "zsh", "dash", "ksh", "fish", "ash", "script", "su", "busybox"]);
const NON_EXECUTING_PREFIX_BINS = new Set(["cat", "echo", "find", "grep", "rg", "sed", "awk", "gawk", "printf"]);
const EVAL_BINS = new Set(["eval", "source", "."]);
const TRAP_BINS = new Set(["trap"]);

const GLOBAL_OPTS = new Map<string, string>([
	["git", "flags+args"],
	["docker", "flags+args"],
	["gh", "flags+args"],
	["npm", "flags+args"],
	["uv", "flags+args"],
	["cargo", "flags+args"],
	["kubectl", "flags+args"],
	["systemctl", "flags+args"],
	["chezmoi", "flags+args"],
]);
const GLOBAL_OPTION_VALUE_FLAGS = new Map<string, Set<string>>([["gh", new Set(["-R", "--repo", "--hostname"])]]);

// サブコマンドの別名 (コマンド名 + NUL + サブコマンド -> 正規形)
const SUBCOMMAND_ALIASES = new Map<string, string>([
	["git\0send-pack", "push"],
	["npm\0i", "install"],
	["npm\0rm", "uninstall"],
	["npm\0un", "uninstall"],
	["npm\0r", "uninstall"],
	["docker\0container", "container"],
]);
const FLAG_NORMALIZED = new Map<string, { flags: Set<string>; canonical: string }>([
	["npm\0install", { flags: new Set(["-g", "--global"]), canonical: "install -g" }],
	["npm\0uninstall", { flags: new Set(["-g", "--global"]), canonical: "uninstall -g" }],
]);

const INTERPRETER_FLAGS = new Map<string, string[]>([
	["python", ["-c"]],
	["perl", ["-e", "-E"]],
	["ruby", ["-e"]],
	["node", ["-e", "--eval", "-p", "--print"]],
	["php", ["-r"]],
	["deno", ["eval"]],
]);
const AWK_BINS = new Set(["awk", "gawk", "mawk", "nawk"]);

const GROUPING_PREFIX = "({";
const GROUPING_SUFFIX = ")}";

// ─── 正規表現 ─────────────────────────────────────────────

const CD_PREFIX_RE = pyRegex("^\\s*cd\\s+\\S+\\s*(?:&&|;)\\s*(.+)$");
const GIT_C_RE = pyRegex("^\\s*git\\s+(?:-C\\s+\\S+\\s+)+(.+)$");
const CD_ONLY_RE = pyRegex("^\\s*cd(\\s+\\S+)?\\s*$");
const ENV_ASSIGN_RE = pyRegex("^(?:[A-Za-z_][A-Za-z0-9_]*=(?:\"[^\"]*\"|'[^']*'|\\S*)\\s+)+(.+)$");
const WRAPPER_POSITIONAL_ARG_RE = pyRegex("^[0-9]+(?:\\.[0-9]+)?[smhd]?$");
const SHELL_VAR_RE = pyRegex("^\\$\\{?(?:SHELL|BASH|ZSH)\\}?$");
const CONTROL_KEYWORD_RE = pyRegex(
	"^(?:if|then|elif|else|fi|for|while|until|do|done|case|esac|select|function|time|coproc|in)\\b\\s*",
);
const CASE_LABEL_RE = pyRegex("^[^\\s()]+\\s+in\\s+(?=[^\\s()]*\\))|^\\(?[^\\s()]+\\)\\s*");
const LEADING_REDIRECT_RE = pyRegex("^\\s*(?:[0-9]*[<>]{1,2}&?\\s*\\S+\\s+)+(.+)$");
const CMD_SUBST_SRC = "\\$\\(((?:[^()]|\\([^()]*\\))*)\\)|`([^`]*)`";
const ANSI_C_QUOTE_SRC = "\\$'([^']*)'";
const AWK_SYSTEM_SRC = "(?:system|print)\\s*\\(?\\s*[\"']?([^\"')]+)";
const HERE_STRING_RE = pyRegex("<<<\\s*(.+)$", "s");
const STDIN_SCRIPT_RE = pyRegex("-f\\s+(?:/dev/stdin|-)\\b");
const PROC_SUBST_SRC = "[<>]\\(([^()]*)\\)";
const FUNC_DEF_SRC = "[A-Za-z_][A-Za-z0-9_]*\\s*\\(\\s*\\)\\s*\\{(.*?)\\}";
const ALIAS_DEF_SRC = "alias\\s+[A-Za-z_][A-Za-z0-9_]*=(?:'([^']*)'|\"([^\"]*)\"|(\\S+))";
const VAR_ASSIGN_SRC = "\\b([A-Za-z_][A-Za-z0-9_]*)=([^\\s;&|]+)";
const VAR_REF_SRC = "\\$\\{?([A-Za-z_][A-Za-z0-9_]*)\\}?";
const OPTION_VALUE_NAME_RE = pyRegex("^[A-Za-z][A-Za-z0-9_.+-]*$");
const FUNC_HEADER_SRC =
	"(?:\\bfunction\\s+[A-Za-z_][A-Za-z0-9_]*(?:\\s*\\(\\s*\\))?|\\b[A-Za-z_][A-Za-z0-9_]*\\s*\\(\\s*\\))\\s*\\{";

/** グローバルな正規表現は lastIndex を持つので、使うたびに作る (状態を共有しない)。 */
const all = (src: string, flags = ""): RegExp => pyRegex(src, `${flags}g`);

// ─── 分割 ─────────────────────────────────────────────────

/** 引用の外の複合演算子で分ける (完全なシェルの構文解析ではない)。 */
function splitCompound(command: string): string[] {
	const segments: string[] = [];
	let buf = "";
	let i = 0;
	const n = command.length;
	let inSingle = false;
	let inDouble = false;
	while (i < n) {
		const ch = command[i];
		if (ch === "\\" && i + 1 < n && !inSingle) {
			buf += ch + command[i + 1];
			i += 2;
			continue;
		}
		if (ch === "'" && !inDouble) {
			inSingle = !inSingle;
			buf += ch;
			i += 1;
			continue;
		}
		if (ch === '"' && !inSingle) {
			inDouble = !inDouble;
			buf += ch;
			i += 1;
			continue;
		}
		if (!inSingle && !inDouble) {
			const op = COMPOUND_OPS.find((o) => command.startsWith(o, i));
			if (op !== undefined) {
				const seg = strip(buf);
				if (seg) segments.push(seg);
				buf = "";
				i += op.length;
				continue;
			}
		}
		buf += ch;
		i += 1;
	}
	const tail = strip(buf);
	if (tail) segments.push(tail);
	return segments;
}

export const splitCommandSegments = (command: string): string[] => splitCompound(command);

// ─── 先頭の飾りを剥がす ───────────────────────────────────

function stripCdPrefix(segment: string): string {
	const m = CD_PREFIX_RE.exec(segment);
	return m ? strip(m[1]) : segment;
}

function stripGitDashC(segment: string): string {
	const m = GIT_C_RE.exec(segment);
	return m ? `git ${strip(m[1])}` : segment;
}

function stripGrouping(segment: string): string {
	let seg = strip(segment);
	let changed = true;
	while (changed && seg) {
		changed = false;
		if (GROUPING_PREFIX.includes(seg[0])) {
			seg = strip(seg.slice(1));
			changed = true;
		}
		while (seg && (GROUPING_SUFFIX + ";&").includes(seg[seg.length - 1])) {
			seg = strip(seg.slice(0, -1));
			changed = true;
		}
		let m = CONTROL_KEYWORD_RE.exec(seg);
		if (m) {
			seg = strip(seg.slice(m[0].length));
			changed = true;
		}
		m = CASE_LABEL_RE.exec(seg);
		if (m) {
			seg = strip(seg.slice(m[0].length));
			changed = true;
		}
		if (seg.startsWith("!")) {
			seg = strip(seg.slice(1));
			changed = true;
		}
	}
	return seg;
}

function stripEnvAssignments(segment: string): string {
	const m = ENV_ASSIGN_RE.exec(strip(segment));
	return m ? strip(m[1]) : segment;
}

function normalizeLeadingPath(segment: string): string {
	let tokens: string[];
	try {
		tokens = shlexSplit(segment);
	} catch (e) {
		if (!(e instanceof ShlexError)) throw e;
		tokens = split(segment);
	}
	if (tokens.length === 0 || Array.from(tokens[0]).some(isSpace)) return segment;
	const head = basename(tokens[0]);
	const rest = splitOnce(segment);
	if (head === rest[0]) return segment;
	return rest.length > 1 ? `${head} ${rest[1]}` : head;
}

function stripLeadingRedirect(segment: string): string {
	const m = LEADING_REDIRECT_RE.exec(segment);
	return m ? strip(m[1]) : segment;
}

/** `-f git` の `git` のように、オプションの値ではなくコマンド名らしいか (値らしければ true)。 */
function looksLikeOptionValue(token: string): boolean {
	if (token.startsWith("-")) return false;
	return !OPTION_VALUE_NAME_RE.test(token);
}

const looksLikeWrapperOperand = looksLikeOptionValue;

function stripGlobalOptions(segment: string): string {
	let tokens: string[];
	try {
		tokens = shlexSplit(segment);
	} catch (e) {
		if (e instanceof ShlexError) return segment;
		throw e;
	}
	if (tokens.length < 2) return segment;
	const head = basename(tokens[0]);
	const style = GLOBAL_OPTS.get(head);
	if (style === undefined) return segment;

	let i = 1;
	const globalFlags: string[] = [];
	while (i < tokens.length && tokens[i].startsWith("-")) {
		const token = tokens[i];
		if (token === "--") {
			i += 1;
			break;
		}
		globalFlags.push(token);
		if (token.includes("=")) {
			i += 1;
			continue;
		}
		if (GLOBAL_OPTION_VALUE_FLAGS.get(head)?.has(token)) {
			if (i + 1 >= tokens.length) return segment;
			globalFlags.push(tokens[i + 1]);
			i += 2;
			continue;
		}
		if (style === "flags+args" && pyLen(token) === 2) {
			const nxt = i + 1 < tokens.length ? tokens[i + 1] : null;
			if (nxt !== null && looksLikeOptionValue(nxt)) {
				globalFlags.push(nxt);
				i += 2;
				continue;
			}
		}
		i += 1;
	}
	let rest = tokens.slice(i);
	if (rest.length === 0) return segment;

	let sub = rest[0];
	const alias = SUBCOMMAND_ALIASES.get(`${head}\0${sub}`);
	if (alias) {
		sub = alias;
		rest = [alias, ...rest.slice(1)];
	}

	const flagRule = FLAG_NORMALIZED.get(`${head}\0${sub}`);
	if (flagRule) {
		const tailFlags = rest.slice(1).filter((t) => flagRule.flags.has(t));
		const preFlags = globalFlags.filter((t) => flagRule.flags.has(t));
		if (tailFlags.length > 0 || preFlags.length > 0) {
			const kept = rest.slice(1).filter((t) => !flagRule.flags.has(t));
			return [head, flagRule.canonical, ...kept].join(" ");
		}
	}
	return [head, ...rest].join(" ");
}

function stripWrapper(segment: string): string {
	let tokens: string[];
	try {
		tokens = shlexSplit(segment);
	} catch (e) {
		if (e instanceof ShlexError) return segment;
		throw e;
	}
	if (tokens.length === 0) return segment;
	const head = basename(tokens[0]);
	const style = WRAPPERS.get(head);
	if (style === undefined) return segment;

	let i = 1;
	while (i < tokens.length) {
		const token = tokens[i];
		if (token === "--") {
			i += 1;
			break;
		}
		if (token.startsWith("-")) {
			if ((style === "flags+args" || style === "duration") && !token.includes("=") && pyLen(token) === 2) {
				const nxt = i + 1 < tokens.length ? tokens[i + 1] : null;
				if (nxt !== null && looksLikeOptionValue(nxt)) {
					i += 2;
					continue;
				}
			}
			i += 1;
			continue;
		}
		if (style === "duration" && WRAPPER_POSITIONAL_ARG_RE.test(token)) {
			i += 1;
			continue;
		}
		if (style === "flags+args" && looksLikeWrapperOperand(token) && i + 1 < tokens.length) {
			i += 1;
			continue;
		}
		if (token.includes("=") && !token.startsWith("/")) {
			i += 1;
			continue;
		}
		break;
	}
	const rest = tokens.slice(i);
	if (rest.length === 0) return segment;
	return rest.map((t) => (t.includes(" ") ? shlexQuote(t) : t)).join(" ");
}

function normalizeSegment(segment: string): string {
	let seg = segment;
	for (let n = 0; n < 8; n++) {
		let next = stripGrouping(seg);
		next = stripLeadingRedirect(next);
		next = stripCdPrefix(next);
		next = stripGitDashC(next);
		next = stripEnvAssignments(next);
		next = stripWrapper(next);
		next = normalizeLeadingPath(next);
		next = stripGlobalOptions(next);
		if (next === seg) break;
		seg = next;
	}
	return split(seg).join(" ");
}

// ─── 埋まったコードの取り出し ─────────────────────────────

function expandInterpreterCode(segment: string): string[] {
	let tokens: string[];
	try {
		tokens = shlexSplit(segment);
	} catch (e) {
		if (e instanceof ShlexError) return [];
		throw e;
	}
	if (tokens.length === 0) return [];
	const head = basename(tokens[0]).replace(/[0-9.]+$/, "");

	const out: string[] = [];
	if (AWK_BINS.has(head)) {
		for (const m of segment.matchAll(all(AWK_SYSTEM_SRC))) {
			const inner = strip(m[1]);
			if (inner) out.push(inner);
		}
		return out;
	}

	const flags = INTERPRETER_FLAGS.get(head);
	if (!flags) return [];
	for (let i = 1; i < tokens.length; i++) {
		const token = tokens[i];
		if (flags.includes(token) && i + 1 < tokens.length) {
			const code = tokens[i + 1];
			out.push(code);
			for (const m of code.matchAll(all("['\"]([^'\"]{3,})['\"]"))) {
				const inner = strip(m[1]);
				if (inner && inner.includes(" ")) out.push(inner);
			}
		}
	}
	return out;
}

/** `$(echo git push)` のように echo の出力をコマンドとして使う形。 */
function echoPayloads(segment: string): string[] {
	let tokens: string[];
	try {
		tokens = shlexSplit(segment);
	} catch (e) {
		if (e instanceof ShlexError) return [];
		throw e;
	}
	if (tokens.length < 2 || !["echo", "printf"].includes(basename(tokens[0]))) return [];
	const args = tokens.slice(1).filter((t) => !t.startsWith("-"));
	if (args.length === 0) return [];
	return [args.join(" ")];
}

function expandIndirectCode(segment: string, fullCommand = ""): string[] {
	const out: string[] = [];
	const sources = [segment];
	if (fullCommand && fullCommand !== segment) sources.push(fullCommand);

	for (const src of sources) {
		const m = HERE_STRING_RE.exec(src);
		if (m) {
			const body = stripChars(strip(m[1]), "'\"");
			out.push(body);
			if (STDIN_SCRIPT_RE.test(src)) {
				for (const line of splitLines(body.replaceAll("\\n", "\n").replaceAll("\\t", "\t"))) {
					const stripped = strip(stripChars(strip(line), "\t", true, false));
					if (stripped && !stripped.endsWith(":")) out.push(stripped);
				}
			}
		}

		for (const pm of src.matchAll(all(PROC_SUBST_SRC))) {
			const inner = strip(pm[1]);
			if (inner) {
				out.push(inner);
				out.push(...echoPayloads(inner));
			}
		}

		for (const fm of src.matchAll(all(FUNC_DEF_SRC, "s"))) {
			const body = strip(stripChars(strip(fm[1]), ";", false, true));
			if (body) out.push(body);
		}

		for (const am of src.matchAll(all(ALIAS_DEF_SRC))) {
			const value = strip(am[1] || am[2] || am[3] || "");
			if (value) out.push(value);
		}

		for (const qm of src.matchAll(all(ANSI_C_QUOTE_SRC))) {
			const inner = strip(qm[1]);
			if (inner) out.push(inner);
		}
	}

	// `p=push; git $p` のように、同じコマンド列で定義された変数を展開する
	if (fullCommand && pyRegex(VAR_REF_SRC).test(segment)) {
		const assignments = new Map<string, string>();
		for (const am of fullCommand.matchAll(all(VAR_ASSIGN_SRC))) assignments.set(am[1], am[2]);
		if (assignments.size > 0) {
			const expanded = segment.replace(all(VAR_REF_SRC), (whole, name: string) => assignments.get(name) ?? whole);
			if (expanded !== segment) out.push(expanded);
		}
	}
	return out;
}

function expandCommandSubstitution(segment: string): string[] {
	const found: string[] = [];
	const inners: string[] = [];
	for (const m of segment.matchAll(all(CMD_SUBST_SRC))) {
		const inner = strip(m[1] || m[2] || "");
		if (inner) {
			inners.push(inner);
			found.push(inner);
			found.push(...echoPayloads(inner));
		}
	}
	if (inners.length === 0) return found;

	const stripped = split(strip(segment.replace(all(CMD_SUBST_SRC), " "))).join(" ");
	if (stripped) {
		found.push(stripped);
		for (const inner of inners) {
			const innerTokens = split(inner);
			if (innerTokens.length > 0) found.push(`${innerTokens[innerTokens.length - 1]} ${stripped}`);
		}
	}
	return found;
}

export function extractCommandSubstitutions(command: string): string[] {
	const out: string[] = [];
	for (const m of command.matchAll(all(CMD_SUBST_SRC))) {
		const inner = strip(m[1] || m[2] || "");
		if (inner) out.push(inner);
	}
	return out;
}

export function extractFunctionBodies(command: string): string[] {
	const header = all(FUNC_HEADER_SRC);
	const bodies: string[] = [];
	let cursor = 0;
	for (;;) {
		header.lastIndex = cursor;
		const match = header.exec(command);
		if (!match) break;
		const start = match.index + match[0].length;
		let depth = 1;
		let quote: string | null = null;
		let escaped = false;
		let i = start;
		let closed = false;
		while (i < command.length) {
			const char = command[i];
			if (escaped) {
				escaped = false;
			} else if (char === "\\" && quote !== "'") {
				escaped = true;
			} else if (quote) {
				if (char === quote) quote = null;
			} else if (char === "'" || char === '"' || char === "`") {
				quote = char;
			} else if (char === "{") {
				depth += 1;
			} else if (char === "}") {
				depth -= 1;
				if (depth === 0) {
					const body = strip(stripChars(strip(command.slice(start, i)), ";", false, true));
					if (body) bodies.push(body);
					cursor = i + 1;
					closed = true;
					break;
				}
			}
			i += 1;
		}
		if (!closed) cursor = match.index + match[0].length;
	}
	return bodies;
}

function expandEmbeddedCommands(segment: string): string[] {
	let tokens: string[];
	try {
		tokens = shlexSplit(segment);
	} catch (e) {
		if (e instanceof ShlexError) return [];
		throw e;
	}
	if (tokens.length === 0) return [];
	const head = basename(tokens[0]);
	const out: string[] = [];

	if (head === "find") {
		for (let i = 0; i < tokens.length; i++) {
			if (FIND_EXEC_FLAGS.has(tokens[i]) && i + 1 < tokens.length) {
				const rest: string[] = [];
				for (const t of tokens.slice(i + 1)) {
					if ([";", "\\;", "+", "\\+", "\\"].includes(t)) break;
					rest.push(t);
				}
				if (rest.length > 0) out.push(rest.join(" "));
			}
		}
		return out;
	}

	if (["screen", "tmux", "at", "batch", "entr", "watchexec"].includes(head)) {
		let rest = tokens.slice(1).filter((t) => !t.startsWith("-"));
		if (
			head === "tmux" &&
			rest.length > 0 &&
			["new-session", "new", "new-window", "neww", "send-keys", "run-shell", "run"].includes(rest[0])
		) {
			rest = rest.slice(1);
		}
		if (rest.length > 0) out.push(rest.join(" "));
		return out;
	}

	if (head === "git" && tokens.length >= 4 && tokens[1] === "submodule" && tokens[2] === "foreach") {
		out.push(tokens.slice(3).join(" "));
		return out;
	}

	if (head === "docker" && tokens.length >= 3 && ["run", "exec"].includes(tokens[1])) {
		let i = 2;
		while (i < tokens.length && tokens[i].startsWith("-")) {
			if (!tokens[i].includes("=") && pyLen(tokens[i]) === 2 && i + 1 < tokens.length) {
				i += 2;
				continue;
			}
			i += 1;
		}
		i += 1;
		if (i < tokens.length) out.push(tokens.slice(i).join(" "));
		return out;
	}

	// `mise exec -- CMD` / `npm run x -- CMD` のように `--` の後ろが実コマンドになるもの
	const dash = tokens.indexOf("--", 1);
	if (dash >= 0) {
		const rest = tokens.slice(dash + 1);
		if (rest.length > 0) out.push(rest.join(" "));
	}

	if (
		["uv", "mise", "npm", "pnpm", "yarn", "cargo", "go", "poetry", "rye"].includes(head) &&
		tokens.length >= 3 &&
		RUNNER_SUBCOMMANDS.has(tokens[1])
	) {
		const rest = tokens.slice(2).filter((t) => t !== "--");
		if (rest.length > 0) out.push(rest.join(" "));
	}
	return out;
}

/** `bash -c "git push"` の中身を取り出す。対象外なら null。 */
function expandShellInvocation(segment: string): string[] | null {
	let tokens: string[];
	try {
		tokens = shlexSplit(segment);
	} catch (e) {
		if (e instanceof ShlexError) return null;
		throw e;
	}
	if (tokens.length === 0) return null;
	const head = basename(tokens[0]);

	if (EVAL_BINS.has(head) && tokens.length > 1) return [tokens.slice(1).join(" ")];
	if (TRAP_BINS.has(head) && tokens.length > 1) return [tokens[1]];

	if (!SHELL_BINS.has(head) && !SHELL_VAR_RE.test(tokens[0])) return null;
	for (let i = 1; i < tokens.length; i++) {
		const token = tokens[i];
		if (token.startsWith("-") && !token.startsWith("--") && token.includes("c")) {
			if (i + 1 < tokens.length) return [tokens.slice(i + 1).join(" ")];
			return null;
		}
	}
	return null;
}

function expandNestedShellInvocations(segment: string): string[] {
	let tokens: string[];
	try {
		tokens = shlexSplit(segment);
	} catch (e) {
		if (e instanceof ShlexError) return [];
		throw e;
	}
	if (tokens.length === 0 || NON_EXECUTING_PREFIX_BINS.has(basename(tokens[0]))) return [];
	const out: string[] = [];
	for (let i = 1; i < tokens.length; i++) {
		const token = tokens[i];
		if (!SHELL_BINS.has(basename(token)) && !SHELL_VAR_RE.test(token)) continue;
		for (let j = i + 1; j < tokens.length; j++) {
			const flag = tokens[j];
			if (flag.startsWith("-") && !flag.startsWith("--") && flag.includes("c")) {
				if (j + 1 < tokens.length) out.push(tokens.slice(j + 1).join(" "));
				break;
			}
		}
	}
	return out;
}

// ─── 正規化の入口 ─────────────────────────────────────────

// 展開の上限。病的な入力で処理時間が爆発しないように抑える
const MAX_SEGMENTS = 200;
const MAX_EXPANSION_LEN = 4000;

/** 照合に使う、正規化済みのコマンドセグメントの一覧。 */
export function normalize(command: string, depth = 0): string[] {
	let segments = splitCompound(command);
	if (segments.length > MAX_SEGMENTS) segments = segments.slice(0, MAX_SEGMENTS);
	const out: string[] = [];
	if (depth === 0 && strip(command) && command.length <= MAX_EXPANSION_LEN && !segments.includes(strip(command))) {
		for (const inner of expandIndirectCode(command, command)) out.push(...normalize(inner, depth + 1));
	}
	for (const raw of segments) {
		const seg = normalizeSegment(raw);
		if (seg && !CD_ONLY_RE.test(seg)) out.push(seg);
		if (depth >= 3 || raw.length > MAX_EXPANSION_LEN) continue;
		for (const inner of expandCommandSubstitution(raw)) out.push(...normalize(inner, depth + 1));
		for (const inner of expandIndirectCode(raw, command)) out.push(...normalize(inner, depth + 1));
		if (seg) {
			for (const chunk of expandShellInvocation(seg) ?? []) out.push(...normalize(chunk, depth + 1));
			for (const chunk of expandNestedShellInvocations(seg)) out.push(...normalize(chunk, depth + 1));
			for (const chunk of expandInterpreterCode(seg)) out.push(...normalize(chunk, depth + 1));
			for (const source of [seg, raw]) {
				for (const chunk of expandEmbeddedCommands(source)) out.push(...normalize(chunk, depth + 1));
			}
		}
	}
	return out;
}

// ─── 照合 ─────────────────────────────────────────────────

/** パターンが、正規化済みセグメントの先頭から連続するトークン列に当たるか。 */
export function patternMatches(segment: string, pattern: string): boolean {
	let segTokens: string[];
	try {
		segTokens = shlexSplit(segment);
	} catch (e) {
		if (!(e instanceof ShlexError)) throw e;
		segTokens = split(segment);
	}
	const patTokens = split(pattern);
	if (patTokens.length === 0 || segTokens.length === 0) return false;
	if (segTokens.length < patTokens.length) return false;
	return patTokens.every((t, i) => segTokens[i] === t);
}

/** 最初に当たるパターン。なければ null。 */
export function findMatch(command: string, patterns: Iterable<string>): string | null {
	const pats = [...patterns];
	if (pats.length === 0) return null;
	for (const segment of normalize(command)) {
		for (const pat of pats) {
			if (patternMatches(segment, pat)) return pat;
		}
	}
	return null;
}
