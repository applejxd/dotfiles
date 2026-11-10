// 防御機構そのものと、環境への永続的な変更の保護 (bashrules/rules_guard.py の移植)。
//
// hook や settings.json の改変、シェル起動ファイルへの追記、権限昇格、
// グローバルな環境変数の書き換えなどを扱う。
//
// node の型除去でそのまま動く書き方だけを使う。
// see docs/spec/guard/pi-decide.md#ts-版への移植
import type { Ctx } from "./context.ts";
import { tableSet } from "./context.ts";
import { expandUser, isAbsolute, join, normpath, realpathLoose, sep, strictResolve } from "./pathutil.ts";
import { basename, pyRegex, shlexSplit, ShlexError, split, stripChars } from "./pystr.ts";
import { argv, parse } from "./shellparse.ts";
import type { Command } from "./shellparse.ts";
import { splitCommandSegments } from "./normalize.ts";
import { inlineCodeHead } from "./rules_exec.ts";
import { ledgerCommonDirs, ledgerRoots, underLedgerRoot } from "./ledger_root.ts";
import {
	baseName,
	clip200,
	cmdName,
	commands,
	normalizeGuardPath,
	redirectWriteTargets,
	segments,
	workspaceRoot,
	writeTargets,
} from "./shared.ts";

/** `shlex.split` が失敗したら空白で割る (Python 版の `except ValueError` と同じ)。 */
function shlexOrSplit(segment: string): string[] {
	try {
		return shlexSplit(segment);
	} catch (e) {
		if (e instanceof ShlexError) return split(segment);
		throw e;
	}
}

const GUARD_TARGETS = [
	"/.claude/hooks",
	"/.claude/settings.json",
	"/.copilot/hooks",
	"/.copilot/permissions-config.json",
	"/.config/agents",
	// pi のフルガードの設定とコード (素の pi は Fence で凍結できない)
	"/.pi/agent/settings.json",
	"/.pi/agent/mcp.json",
	"/.pi/agent/extensions",
	"/.config/pi/harness",
	"/.git/config",
	"/.git/hooks",
	".git/config",
	".git/hooks",
	// 作業台帳の置き場 (ハーネスだけが fs で書く)。"/.tmp/work/" は "/.tmp/worktrees/" に当たらない
	"/.git/pi-work",
	".git/pi-work",
	"/.tmp/work/",
	".tmp/work/",
];

const guardHits = (token: string): boolean => {
	const expanded = normalizeGuardPath(token);
	return GUARD_TARGETS.some((t) => expanded.includes(t));
};

// 作業台帳の置き場を、成分境界つきで照合する (`.tmp/worktrees` には当たらず、置き場そのもの `.tmp/work` には当たる)。
// 先頭の境界は付けない: `-o.tmp/work/x` のような短いオプションと値の連結にも当てるため (読み取り専用コマンドは対象外なので偽陽性は出ない)
const LEDGER_RE = /\.tmp\/work(?:\/|$)|\.git\/pi-work(?:\/|$)/u;

// 台帳のパスが引数に現れても書き込まない、既知の読み取り専用コマンド (これ以外は fail-closed で拒否する)
const LEDGER_READ_ONLY = new Set([
	"cat", "ls", "head", "tail", "grep", "egrep", "fgrep", "rg", "wc", "stat", "file", "jq", "find", "diff", "less", "more",
	"du", "realpath", "readlink", "basename", "dirname", "echo", "printf", "test", "[", "pwd", "sha256sum", "md5sum",
	"cut", "sort", "tac", "nl", "column",
]);
const LEDGER_GIT_READ = new Set(["log", "show", "diff", "status", "rev-parse", "ls-files", "blame", "grep", "cat-file", "rev-list"]);
const FIND_WRITE_FLAGS = new Set(["-delete", "-exec", "-execdir", "-ok", "-okdir", "-fprint", "-fprint0", "-fprintf", "-fls"]);

/** `token` (または `--opt=値` の値) が、cwd 基点の絶対パス・symlink の実体のどちらかで台帳に当たるか。動的な展開は字面だけ見る。 */
function ledgerHit(token: string, base: string | null): boolean {
	const raw = stripChars(token, "'\"");
	const forms = [raw];
	const eq = raw.indexOf("=");
	if (eq > 0) forms.push(raw.slice(eq + 1));
	// 連結した短いオプションの値 (`-oledger/x`・`-aoledger/x`): 先頭の `-` と 1〜3 文字の英字を剥いだ候補を全部加える
	if (/^-[A-Za-z]/u.test(raw)) {
		for (let n = 1; n <= 3; n++) {
			if (!/^[A-Za-z]+$/u.test(raw.slice(1, 1 + n))) break;
			forms.push(raw.slice(1 + n));
		}
	}
	for (const form of forms) {
		if (!form) continue;
		if (LEDGER_RE.test(normalizeGuardPath(form))) return true;
		if (base === null || Array.from("$`").some((ch) => form.includes(ch))) continue;
		const expanded = expandUser(form);
		const abs = normpath(isAbsolute(expanded) ? expanded : join(base, expanded));
		if (LEDGER_RE.test(abs.replaceAll(sep, "/"))) return true;
		if (LEDGER_RE.test(realpathLoose(abs).replaceAll(sep, "/"))) return true;
		// `.git` 以外の名前の git-common-dir (separate-git-dir や GIT_DIR) の実体: fs で解いた置き場と照合する
		const roots = ledgerRoots(base);
		if (underLedgerRoot(abs, roots) || underLedgerRoot(realpathLoose(abs), roots)) return true;
		// symlink と `..` を成分ごとに順に解決する (`link/..` を先に畳まない)。失敗 (循環・権限など) は字面の判定のままにする
		try {
			const strict = strictResolve(isAbsolute(expanded) ? expanded : `${base}${sep}${expanded}`);
			if (LEDGER_RE.test(strict.replaceAll(sep, "/"))) return true;
			if (underLedgerRoot(strict, roots)) return true;
		} catch {
			// 安全側: 上の字面の判定に任せる
		}
	}
	return false;
}

/** git の読み取り専用のサブコマンドで、`--output` / `-o` を持たないか。`-C` の基点は `bases` へ積む。 */
function gitReadOnly(tokens: string[], base: string | null): { readOnly: boolean; base: string | null } {
	let cur = base;
	let i = 1;
	while (i < tokens.length && tokens[i].startsWith("-")) {
		const t = tokens[i];
		if (t === "-C" && i + 1 < tokens.length) {
			cur = chdirBase(cur, tokens[i + 1]);
			i += 2;
		} else if (t.length > 2 && t.startsWith("-C")) {
			cur = chdirBase(cur, t.slice(2));
			i += 1;
		} else if (t === "-c" && i + 1 < tokens.length) {
			i += 2;
		} else {
			i += 1;
		}
	}
	const sub = tokens[i];
	const outputFlag = tokens.some((t) => t === "-o" || t.startsWith("--output") || (/^-o./u.test(t) && !t.startsWith("--")));
	return { readOnly: sub !== undefined && LEDGER_GIT_READ.has(sub) && !outputFlag, base: cur };
}

/** `git -C <dir>` の基点の更新。 */
function chdirBase(cur: string | null, dir: string): string | null {
	const d = expandUser(stripChars(dir, "'\""));
	if (cur === null && !isAbsolute(d)) return null;
	if (Array.from("$`").some((ch) => d.includes(ch))) return null;
	const full = isAbsolute(d) ? d : `${cur ?? ""}${sep}${d}`;
	const lexical = normpath(full);
	try {
		// symlink の後ろの `..` を字句で畳むと実体とずれるので、ずれる・解決できないときは基点を不明 (null) にする
		return strictResolve(full) === lexical ? lexical : null;
	} catch {
		return null;
	}
}

/** 値を取るラッパーのオプション (次のトークンを 1 つ食う)。 */
const WRAPPER_VALUE_OPTS: Record<string, Set<string>> = {
	env: new Set(["-u", "--unset", "-C", "--chdir"]),
	timeout: new Set(["-s", "--signal", "-k", "--kill-after"]),
	time: new Set(["-f", "--format", "-o", "--output"]),
	nice: new Set(["-n", "--adjustment"]),
	stdbuf: new Set(["-o", "-i", "-e"]),
	exec: new Set(["-a"]),
};
const WRAPPERS = new Set(["env", "timeout", "time", "nice", "nohup", "command", "stdbuf", "builtin", "exec"]);

/**
 * 既知のラッパー (env / timeout / time / nice / nohup / command / stdbuf / builtin / exec) 自身のオプションを読み飛ばし、
 * 実コマンドの argv と、読み飛ばしたトークン (台帳向けの引数があり得るので別に検査する) を返す。解釈できない形は変えずに返す。
 */
function unwrapCommand(tokens: string[]): { rest: string[]; skipped: string[] } {
	let cur = tokens;
	const skipped: string[] = [];
	for (let depth = 0; depth < 8 && cur.length > 0; depth++) {
		const head = baseName(cur[0]);
		if (!WRAPPERS.has(head)) break;
		const valueOpts = WRAPPER_VALUE_OPTS[head] ?? new Set<string>();
		let i = 1;
		let ok = true;
		while (i < cur.length) {
			const t = cur[i];
			if (head === "env" && (t.startsWith("-S") || t.startsWith("--split-string"))) {
				ok = false; // 文字列から命令を作る形は解釈しない (読み取り専用に見えず、拒否側へ倒れる)
				break;
			}
			if (head === "env" && /^[A-Za-z_][A-Za-z0-9_]*=/u.test(t)) {
				i += 1;
			} else if (t === "--") {
				i += 1;
				break;
			} else if (valueOpts.has(t)) {
				i += 2;
			} else if (t.startsWith("-") && t.length > 1) {
				i += 1;
			} else {
				break;
			}
		}
		if (!ok) break;
		if (head === "timeout" && i < cur.length) i += 1; // DURATION
		skipped.push(...cur.slice(1, Math.min(i, cur.length)));
		cur = cur.slice(i);
	}
	return { rest: cur, skipped };
}

/** find の探索起点だけ (先頭の -H/-L/-P/-D…/-O… を読み飛ばし、最初の式 (`-name`・`(`・`!`) の手前まで)。式の値は対象に含めない。 */
function findStartPoints(args: string[]): string[] {
	let i = 0;
	while (i < args.length && /^-(?:[HLP]|D\S*|O\S*)$/u.test(args[i])) i += 1;
	const out: string[] = [];
	for (; i < args.length; i++) {
		const t = args[i];
		if (t.startsWith("-") || t === "(" || t === "!" || t === ",") break;
		out.push(t);
	}
	return out;
}

/** common-dir 自身 (台帳を含む `.git` 以外の名前の置き場) と等しい対象か。削除・移動系だけがこれで拒否される。 */
function commonDirHit(token: string, base: string | null): boolean {
	if (base === null) return false;
	const raw = stripChars(token, "'\"");
	if (!raw || raw.startsWith("-") || Array.from("$`").some((ch) => raw.includes(ch))) return false;
	const commons = ledgerCommonDirs(base);
	if (commons.length === 0) return false;
	const expanded = expandUser(raw);
	const abs = normpath(isAbsolute(expanded) ? expanded : join(base, expanded));
	const forms = [abs, realpathLoose(abs)];
	try {
		forms.push(strictResolve(isAbsolute(expanded) ? expanded : `${base}${sep}${expanded}`));
	} catch {
		// 字面の判定に任せる
	}
	return forms.some((f) => commons.includes(f.length > 1 && f.endsWith(sep) ? f.slice(0, -1) : f));
}
const LEDGER_REMOVE_MOVE = new Set(["rm", "rmdir", "unlink", "mv", "shred"]);

/** 台帳への書き込み・削除 (リダイレクト・書き込みオプション・symlink の別名・置き場そのものの削除) を、追加の判定として拒否する。 */
function checkLedgerWrite(ctx: Ctx, cmd: string): string | null {
	const workspace = workspaceRoot(ctx);
	const deny = (target: string): string =>
		`作業台帳の置き場 (\`${target}\`) への書き込み・削除は許可されていません。\n` +
		"台帳はハーネスだけが書きます (`.tmp/work`・`.git/pi-work`)。読み取りは cat / grep / ls などを使ってください。";
	for (const target of redirectWriteTargets(ctx, cmd)) {
		if (ledgerHit(target, workspace)) return deny(target);
	}
	for (const command of commands(ctx, cmd)) {
		const all = argv(command);
		if (all.length === 0) continue;
		const { rest: tokens, skipped } = unwrapCommand(all);
		// ラッパー自身の引数 (`env -C .tmp/work` など) は従来どおり検査する
		for (const token of skipped) {
			if (ledgerHit(token, workspace)) return deny(token);
		}
		if (tokens.length === 0) continue;
		const head = baseName(tokens[0]);
		// 削除・移動は、台帳を含む common-dir 自身が対象でも拒否する (配下だけでは見えない)
		if (LEDGER_REMOVE_MOVE.has(head) || (head === "find" && tokens.includes("-delete"))) {
			for (const token of head === "find" ? findStartPoints(tokens.slice(1)) : tokens.slice(1)) {
				if (commonDirHit(token, workspace)) return deny(token);
			}
		}
		let base = workspace;
		let readOnly = LEDGER_READ_ONLY.has(head);
		if (head === "git") {
			const g = gitReadOnly(tokens, workspace);
			readOnly = g.readOnly;
			base = g.base;
			// `-C` の基点が不明 (symlink の後ろの `..` など) で書き込みうる形は、台帳に当たりうるとして拒否する
			if (base === null && workspace !== null && !readOnly) return deny("git -C");
		} else if (head === "find") {
			readOnly = !tokens.some((t) => FIND_WRITE_FLAGS.has(t));
		} else if (head === "less") {
			readOnly = !tokens.some((t) => /^-[oO]/u.test(t) || t.startsWith("--log-file") || t.startsWith("--LOG-FILE"));
		} else if (head === "sort") {
			readOnly = !tokens.some((t) => /^-[A-Za-z]*o/u.test(t) || t.startsWith("--output"));
		} else if (/^python3?(?:\.\d+)?$/u.test(head)) {
			readOnly = !tokens.includes("-c") && tokens.some((t) => t.endsWith("scripts/work_stats.py"));
		}
		// ledger の中へ入ると、以後の相対パスの書き込みを字面で見られない
		const enters = head === "cd" || head === "pushd" || head === "chdir";
		if (readOnly && !enters) continue;
		for (const token of tokens.slice(1)) {
			if (ledgerHit(token, base)) return deny(token);
		}
	}
	return null;
}

const INLINE_PATH_RE = pyRegex(`['"]([^'"]*(?:\\.claude|\\.copilot|/agents|\\.git/|\\.pi/agent|config/pi/harness|\\.tmp/work/)[^'"]*)['"]`, "g");
const HOOK_ENV_RE = pyRegex("\\b(AGENTS_CONFIG_DIR|PYTHONPATH|CLAUDE_[A-Z_]*HOOK[A-Z_]*)=(\\S*)", "g");

// シェルが値をコードとして実行する入口の環境変数 (名前は完全一致。BASH_FUNC_ だけ前方一致)。
// 検出する形・入れないもの・限界は docs/spec/guard/pi-guard.md#コードの入口になる環境変数
// 通常の引数は走査しない: 単純コマンドの語の列の、代入になりうる位置だけを見る (同じ規則が rules_guard.py の code_entry_env にある)
const ENTRY_NAMES = new Set(["PS4", "PROMPT_COMMAND", "BASH_ENV", "LD_PRELOAD", "LD_AUDIT", "DYLD_INSERT_LIBRARIES"]);
const ENTRY_ASSIGN_WORD_RE = /^([A-Za-z_][A-Za-z0-9_]*|BASH_FUNC_[^=]*)(?:\[[^\]]*\])?\+?=([\s\S]*)$/u;
const PS4_EXPANSION_RE = /\$(?:[A-Za-z_][A-Za-z0-9_]*|\{[A-Za-z_][A-Za-z0-9_]*(?:\[(?:[0-9]+|@)\])?\})/gu;
const ENTRY_KEYWORDS = new Set(["if", "then", "else", "elif", "do", "while", "until", "!", "{", "}"]);
const ENTRY_WRAPPERS = new Set(["env", "sudo", "doas", "time", "command", "nice", "nohup", "timeout", "stdbuf", "xargs", "exec", "builtin"]);
const ENTRY_WRAPPER_VALUE_OPTS: Record<string, Set<string>> = {
	env: new Set(["-u", "--unset", "-C", "--chdir", "--argv0"]),
	sudo: new Set([
		"-u", "-g", "-h", "-p", "-C", "-D", "-R", "-T", "-U", "-r", "-t",
		"--user", "--group", "--host", "--prompt", "--chdir", "--close-from", "--role", "--type", "--other-user", "--command-timeout",
	]),
	doas: new Set(["-u", "-C"]),
	time: new Set(["-f", "--format", "-o", "--output"]),
	nice: new Set(["-n", "--adjustment"]),
	timeout: new Set(["-s", "--signal", "-k", "--kill-after"]),
	stdbuf: new Set(["-i", "-o", "-e", "--input", "--output", "--error"]),
	xargs: new Set([
		"-I", "-n", "-P", "-s", "-L", "-E", "-d", "-a",
		"--max-args", "--max-procs", "--max-lines", "--max-chars", "--delimiter", "--arg-file", "--process-slot-var",
	]),
	exec: new Set(["-a"]),
};
const ENTRY_DECLARE = new Set(["export", "declare", "typeset", "local", "readonly"]);
const ENTRY_SHELLS = new Set(["bash", "sh", "zsh", "dash", "ksh"]);

const entryName = (name: string): boolean => ENTRY_NAMES.has(name) || name.startsWith("BASH_FUNC_");

/** PS4 の値が、リテラルと単純な展開 (`$NAME`・`${NAME}`・`${NAME[数字]}`・`${NAME[@]}`) だけか。 */
function ps4Safe(value: string): boolean {
	return !/[$`\\]/u.test(value.replace(PS4_EXPANSION_RE, ""));
}

/** `NAME=値`・`NAME+=値` の語が名簿の変数への代入なら名前を返す (値が安全な PS4 は除く)。 */
function entryAssign(word: string): string | null {
	const m = ENTRY_ASSIGN_WORD_RE.exec(word);
	if (m === null || !entryName(m[1])) return null;
	return m[1] === "PS4" && ps4Safe(m[2]) ? null : m[1];
}

/** `read`・`printf -v` の設定先の変数名 (`NAME[idx]` の添字は外す)が名簿なら名前を返す。値は取れないので常に拒否側。 */
function entryTarget(word: string | null): string | null {
	if (word === null) return null;
	const name = word.replace(/\[.*$/su, "");
	return entryName(name) ? name : null;
}

/** 短いオプションを読む。`valueChars` の文字は値を取る (同じ語の残り、無ければ次の語)。`--` と長いオプションは読み飛ばす。 */
function shortOpts(args: string[], valueChars: string): { opts: Array<[string, string | null]>; operands: string[] } {
	const opts: Array<[string, string | null]> = [];
	let i = 0;
	for (; i < args.length; i++) {
		const t = args[i];
		if (t === "--") {
			i += 1;
			break;
		}
		if (t.startsWith("--")) continue;
		if (!t.startsWith("-") || t.length < 2) break;
		for (let k = 1; k < t.length; k++) {
			if (valueChars.includes(t[k])) {
				const rest = t.slice(k + 1);
				if (rest !== "") {
					opts.push([t[k], rest]);
				} else {
					opts.push([t[k], i + 1 < args.length ? args[i + 1] : null]);
					i += 1;
				}
				break;
			}
			opts.push([t[k], null]);
		}
	}
	return { opts, operands: args.slice(i) };
}

/** `env -S` の文字列 (語の残り・`=` の後・次の語) と、消費した語数。 */
function envSplitString(args: string[], j: number): { text: string | null; used: number } {
	const t = args[j];
	if (t === "-S" || t === "--split-string") return { text: j + 1 < args.length ? args[j + 1] : null, used: 2 };
	if (t.startsWith("--split-string=")) return { text: t.slice("--split-string=".length), used: 1 };
	if (t.startsWith("-S") && !t.startsWith("--")) return { text: t.slice(2), used: 1 };
	return { text: null, used: 0 };
}

/** 1 つの単純コマンドの語の列から、名簿の変数の設定・コールバックの入口を見つける。 */
function entryInWords(words: string[], depth: number): string | null {
	let i = 0;
	while (i < words.length && ENTRY_KEYWORDS.has(words[i])) i += 1;
	while (i < words.length && ENTRY_ASSIGN_WORD_RE.test(words[i])) {
		const hit = entryAssign(words[i]);
		if (hit !== null) return hit;
		i += 1;
	}
	if (i >= words.length) return null;
	const head = baseName(words[i]);
	const args = words.slice(i + 1);
	if (ENTRY_WRAPPERS.has(head)) {
		const valueOpts = ENTRY_WRAPPER_VALUE_OPTS[head] ?? new Set<string>();
		let j = 0;
		while (j < args.length) {
			const t = args[j];
			if (t === "--") {
				j += 1;
				break;
			}
			if (head === "env" && (t.startsWith("-S") || t.startsWith("--split-string"))) {
				const s = envSplitString(args, j);
				if (s.text === null) return null;
				return entryInWords(["env", ...shlexOrSplit(s.text), ...args.slice(j + s.used)], depth);
			}
			if (t.startsWith("-") && t.length > 1) {
				j += valueOpts.has(t) ? 2 : 1;
				continue;
			}
			break;
		}
		if (head === "timeout" && j < args.length) j += 1; // DURATION
		return entryInWords(args.slice(j), depth);
	}
	if (head === "find") {
		// -exec 系の直後から `;` / `+` の手前までを、コマンドの語の列として見る (`{}` はそのまま)
		for (let k = 0; k < args.length; k++) {
			if (!["-exec", "-execdir", "-ok", "-okdir"].includes(args[k])) continue;
			let e = k + 1;
			while (e < args.length && args[e] !== ";" && args[e] !== "+") e += 1;
			const hit = entryInWords(args.slice(k + 1, e), depth);
			if (hit !== null) return hit;
			k = e;
		}
		return null;
	}
	if (ENTRY_DECLARE.has(head)) {
		for (const t of args) {
			const hit = entryAssign(t);
			if (hit !== null) return hit;
		}
		return null;
	}
	if (head === "printf") {
		for (const [ch, value] of shortOpts(args, "v").opts) {
			if (ch === "v") return entryTarget(value);
		}
		return null;
	}
	if (head === "read") {
		const { opts, operands } = shortOpts(args, "adinNptu");
		for (const [ch, value] of opts) {
			if (ch === "a") {
				const hit = entryTarget(value);
				if (hit !== null) return hit;
			}
		}
		for (const t of operands) {
			const hit = entryTarget(t);
			if (hit !== null) return hit;
		}
		return null;
	}
	if (head === "mapfile" || head === "readarray") {
		const { opts, operands } = shortOpts(args, "dnOsuCc");
		if (opts.some(([ch]) => ch === "C")) return "mapfile -C";
		for (const t of operands) {
			const hit = entryTarget(t);
			if (hit !== null) return hit;
		}
		return null;
	}
	if (head === "compgen" || head === "complete") {
		return shortOpts(args, "AFGWPSXoC").opts.some(([ch]) => ch === "C") ? "compgen -C" : null;
	}
	if (ENTRY_SHELLS.has(head) && depth < 3) {
		for (let k = 0; k < args.length; k++) {
			const t = args[k];
			if (!t.startsWith("-") || t.startsWith("--") || t.length < 2) break;
			if (t.slice(1).includes("c")) {
				if (k + 1 >= args.length) return null;
				for (const inner of parse(args[k + 1])) {
					const hit = entryInCommand(inner, depth + 1);
					if (hit !== null) return hit;
				}
				return null;
			}
		}
	}
	return null;
}

/** 単純コマンドの先頭 (キーワード・前置代入を除く) がシェルか。 */
function isShellCommand(words: string[]): boolean {
	let i = 0;
	while (i < words.length && (ENTRY_KEYWORDS.has(words[i]) || ENTRY_ASSIGN_WORD_RE.test(words[i]))) i += 1;
	return i < words.length && ENTRY_SHELLS.has(baseName(words[i]));
}

/** 単純コマンド 1 つ。シェルが here-string (`<<<`) を受けるときは、その文字列も `-c` と同じく調べる (深さ 3 まで)。 */
function entryInCommand(command: Command, depth: number): string | null {
	const words = argv(command);
	const hit = entryInWords(words, depth);
	if (hit !== null || depth >= 3 || !isShellCommand(words)) return hit;
	for (const r of command.redirects) {
		if (r.op !== "<<<" || r.target === null) continue;
		for (const inner of parse(r.target.value)) {
			const h = entryInCommand(inner, depth + 1);
			if (h !== null) return h;
		}
	}
	return null;
}

/** 正規化は here-string の本文を別のセグメントにする。シェル以外が受ける本文はデータなので、そのセグメントは見ない。 */
function dataHereStrings(cmd: string): Set<string> {
	const skip = new Set<string>();
	for (const c of parse(cmd)) {
		if (isShellCommand(argv(c))) continue;
		for (const r of c.redirects) {
			if (r.op === "<<<" && r.target !== null) skip.add(r.target.value.trim());
		}
	}
	return skip;
}

/** コードの入口になる環境変数の設定・コールバックの入口を見つける。見つからなければ null。 */
export function codeEntryEnv(ctx: Ctx, cmd: string): string | null {
	const skip = dataHereStrings(cmd);
	for (const segment of segments(ctx, cmd)) {
		if (segment !== cmd && skip.has(segment.trim())) continue;
		for (const command of parse(segment)) {
			const hit = entryInCommand(command, 0);
			if (hit !== null) return hit;
		}
	}
	return null;
}

const MUTATING = new Set([
	"rm",
	"rmdir",
	"unlink",
	"mv",
	"cp",
	"chmod",
	"chown",
	"truncate",
	"shred",
	"ln",
	"sed",
	"tee",
	"dd",
	"install",
]);
// chezmoi は破壊的サブコマンドのときだけ対象にする (diff / status は無害)
const CHEZMOI_MUTATING = new Set(["forget", "destroy", "remove", "unmanage"]);

/** hook や permission 設定そのものを無効化しようとしていないか。 */
export function checkGuardTampering(ctx: Ctx, cmd: string): string | null {
	const ledger = checkLedgerWrite(ctx, cmd);
	if (ledger !== null) return ledger;
	// リダイレクト先がガード設定なら、どのコマンドでも上書きになる
	for (const target of redirectWriteTargets(ctx, cmd)) {
		if (guardHits(target)) {
			return (
				`エージェントのガード設定 (\`${target}\`) を上書きしようとしています。\n` +
				"hook や permission の無効化に繋がるため許可されていません。"
			);
		}
	}

	// インラインコードの中でパスを直接触る形 (`open('...', 'w')` など)。
	// この走査はコマンド全体ではなく、インタプリタのインラインコードセグメントに限定する
	for (const segment of segments(ctx, cmd)) {
		if (inlineCodeHead(ctx, segment) === null) continue;
		for (const m of segment.matchAll(INLINE_PATH_RE)) {
			if (guardHits(m[1])) {
				return (
					`エージェントのガード設定 (\`${m[1]}\`) を操作しようとしています。\n` +
					"インラインコードは読み書きの区別が付かないため許可されていません。\n" +
					`代替: 内容を見るだけなら \`cat ${m[1]}\` や \`grep <pattern> ${m[1]}\` を使ってください。\n` +
					"設定を変えたい場合は chezmoi のソースを編集してください。"
				);
			}
		}
	}

	// 環境変数の差し替えで hook の読み込み先やモジュール解決を乗っ取る形
	for (const m of cmd.matchAll(HOOK_ENV_RE)) {
		const name = m[1];
		const value = m[2];
		if (name === "PYTHONPATH") {
			const home = expandUser("~");
			const expanded = stripChars(value, "'\"").replace("~", () => home);
			const cwd = process.cwd();
			const absolute = normpath(isAbsolute(expanded) ? expanded : join(cwd, expanded));
			// プロジェクト内への追加は正当なので、外部を指す場合だけ止める
			if (!absolute.startsWith(cwd + sep)) {
				return (
					`\`PYTHONPATH=${value}\` で hook のモジュール解決先を差し替えようとしています。\n` +
					"リポジトリ外のパスの指定は許可されていません。"
				);
			}
			continue;
		}
		return (
			`\`${name}\` を差し替えて hook の設定読み込み先を変えようとしています。\n` +
			"hook や permission の無効化に繋がるため許可されていません。"
		);
	}

	const entry = codeEntryEnv(ctx, cmd);
	if (entry !== null) {
		return (
			`シェルが値をコードとして実行する入口の環境変数 (\`PS4\` など。今回は \`${entry}\`) の設定は許可されていません。\n` +
			"対象は PROMPT_COMMAND・BASH_ENV・LD_PRELOAD・LD_AUDIT・DYLD_INSERT_LIBRARIES・BASH_FUNC_* と、" +
			"値にコマンド置換などを含む PS4、`compgen -C` / `complete -C` / `mapfile -C` です。"
		);
	}

	for (const command of commands(ctx, cmd)) {
		const tokens = argv(command);
		if (tokens.length === 0) continue;
		const head = baseName(tokens[0]);
		if (head === "chezmoi") {
			if (tokens.length < 2 || !CHEZMOI_MUTATING.has(tokens[1])) continue;
		} else if (!MUTATING.has(head)) {
			continue;
		}
		for (const token of tokens.slice(1)) {
			if (guardHits(token)) {
				return (
					`エージェントのガード設定 (\`${token}\`) を変更しようとしています。\n` +
					"hook や permission の無効化に繋がるため許可されていません。\n" +
					"設定を変えたい場合は chezmoi のソースを編集してください。"
				);
			}
		}
	}
	return null;
}

const STARTUP_TARGETS = [
	".bashrc",
	".bash_profile",
	".bash_login",
	".zshrc",
	".zshenv",
	".zprofile",
	".profile",
	".login",
	".cshrc",
	".kshrc",
	"authorized_keys",
	"known_hosts",
	".ssh/config",
	".netrc",
	"crontab",
	".gitconfig",
];

function startupHits(token: string): string | null {
	const cleaned = stripChars(token, "'\"");
	const base = basename(cleaned.replace(/\/+$/, ""));
	for (const target of STARTUP_TARGETS) {
		if (target.includes("/")) {
			if (cleaned.endsWith(target)) return target;
		} else if (base === target) {
			return target;
		}
	}
	return null;
}

/** シェル起動ファイルや認証ファイルへの書き込みを検出する。読み取りは許可する。 */
export function checkShellStartupWrite(ctx: Ctx, cmd: string): string | null {
	for (const token of writeTargets(ctx, cmd)) {
		if (startupHits(token)) {
			return `シェル起動ファイル \`${token}\` へ書き込もうとしています。\n以後のシェルで任意コードが走るため許可されていません。`;
		}
	}
	// インラインコードからの書き込み。起動ファイルのパスを参照している時点で止める
	for (const segment of segments(ctx, cmd)) {
		if (inlineCodeHead(ctx, segment) === null) continue;
		for (const token of segment.split(pyRegex("[^\\w./~@:-]+"))) {
			// `users[0].login` のような属性アクセスと区別するため、パス区切りかホーム参照を含むものだけを対象にする
			if (!token || !(token.includes("/") || token.startsWith("~"))) continue;
			if (startupHits(token)) {
				return `インラインコードがシェル起動ファイル \`${token}\` を参照しています。\n読み書きの区別が付かないため許可されていません。`;
			}
		}
	}
	return null;
}

/** setuid 付与やアカウント/認証設定の変更を検出する。 */
export function checkPrivilegeEscalation(ctx: Ctx, cmd: string): string | null {
	const accountBins = new Set(["usermod", "useradd", "adduser", "groupadd", "passwd", "chpasswd", "visudo", "gpasswd"]);
	for (const command of commands(ctx, cmd)) {
		const tokens = argv(command);
		if (tokens.length === 0) continue;
		const head = baseName(tokens[0]);
		if (head === "chmod") {
			for (const token of tokens.slice(1)) {
				// `a+s` などの記号表記と、setuid/setgid ビットを含む 4 桁表記
				if (
					/^[ugoa]*\+[rwxXst]*s[rwxXst]*(?![^])/u.test(token) ||
					(/^[0-7]{4}(?![^])/u.test(token) && (Number.parseInt(token[0], 10) & 0o6) !== 0)
				) {
					return `\`chmod ${token}\` は setuid/setgid を付与する操作です。\n権限昇格に繋がるため許可されていません。`;
				}
			}
		}
		if (accountBins.has(head)) {
			return `\`${head}\` はアカウント・認証設定を変更する操作です。\n権限昇格に繋がるため許可されていません。`;
		}
	}
	// shadow / sudoers は root 専用で、読み取り自体が機密。passwd / group は書き換えるときだけ止める
	if (/\/etc\/(?:sudoers|shadow)/u.test(cmd)) {
		return "認証設定ファイル (/etc/shadow, /etc/sudoers) を操作しようとしています。\n権限昇格に繋がるため許可されていません。";
	}
	if (writeTargets(ctx, cmd).some((target) => /\/etc\/(?:passwd|group)/u.test(target))) {
		return "アカウント設定ファイル (/etc 配下) を書き換えようとしています。\n権限昇格に繋がるため許可されていません。";
	}
	return null;
}

const MISE_GLOBAL_SUBCOMMANDS: [string[], string][] = [
	[["settings", "set"], "mise の設定を書き換えます"],
	[["settings", "unset"], "mise の設定を書き換えます"],
	[["settings", "add"], "mise の設定を書き換えます"],
	[["global"], "ホームのグローバル設定を書き換えます"],
];

// ツール自身を置き換える / 導入物を消す操作。承認の余地なく拒否する。
// common.toml に書けない (mise は runner 扱いで normalize が先頭を落とす)
const MISE_FATAL_SUBCOMMANDS: [string[], string][] = [
	[["self-update"], "mise 自身を更新します"],
	[["implode"], "mise の導入物をすべて削除します"],
];

const startsWithPrefix = (items: readonly string[], prefix: readonly string[]): boolean =>
	items.length >= prefix.length && prefix.every((p, i) => items[i] === p);

/** コンパイラの出力先などが workspace の外を指すか (判定できないときは false)。 */
function writesOutsideWorkspace(ctx: Ctx, path: string): boolean {
	const workspace = workspaceRoot(ctx);
	if (workspace === null || !path) return false;
	if (Array.from("$`").some((ch) => path.includes(ch))) return false;
	const expanded = expandUser(path);
	const resolved = normpath(isAbsolute(expanded) ? expanded : join(workspace, expanded));
	return !resolved.startsWith(workspace + sep);
}

/** ツール自身を置き換える / 導入物を消す操作 (`mise self-update` など) を検出する。 */
export function checkToolSelfUpdate(ctx: Ctx, cmd: string): string | null {
	for (const segment of segments(ctx, cmd)) {
		const tokens = shlexOrSplit(segment);
		if (tokens.length === 0 || baseName(stripChars(tokens[0], "'\"")) !== "mise") continue;
		const subcommands = tokens
			.slice(1)
			.filter((t) => !t.startsWith("-"))
			.map((t) => stripChars(t, "'\""));
		for (const [prefix, why] of MISE_FATAL_SUBCOMMANDS) {
			if (startsWithPrefix(subcommands, prefix)) {
				return (
					`\`mise ${prefix.join(" ")}\` は${why}。\n` +
					"全プロジェクトに影響し元に戻しにくいため許可されていません。\n" +
					"必要ならユーザー自身で実行してください。"
				);
			}
		}
	}
	return null;
}

/** プロジェクトの外に残る環境変更 (`mise use -g`・`cmake --target install`・コンパイラの出力先) を検出する。 */
export function checkGlobalEnvMutation(ctx: Ctx, cmd: string): string | null {
	const globalFlags = tableSet(ctx, "rules_guard", "mise_global_flags");
	const compilers = tableSet(ctx, "rules_guard", "compiler_bins");
	for (const segment of segments(ctx, cmd)) {
		const tokens = shlexOrSplit(segment);
		if (tokens.length === 0) continue;
		const head = baseName(stripChars(tokens[0], "'\""));
		const rest = tokens.slice(1).map((t) => stripChars(t, "'\""));
		if (head === "mise") {
			const subcommands = rest.filter((t) => !t.startsWith("-"));
			if (subcommands[0] === "use" && rest.some((t) => globalFlags.has(t))) {
				return (
					"`mise use -g` はホームのグローバル設定を書き換えます。\n" +
					`実行しようとしているコマンド: ${clip200(segment)}\n` +
					"プロジェクト内で済むなら `-g` を外してください。"
				);
			}
			for (const [prefix, why] of MISE_GLOBAL_SUBCOMMANDS) {
				if (startsWithPrefix(subcommands, prefix)) {
					return (
						`\`mise ${prefix.join(" ")}\` は${why}。\n` +
						`実行しようとしているコマンド: ${clip200(segment)}\n` +
						"内容を確認して問題なければ承認してください。"
					);
				}
			}
		}
		if (head === "cmake" && rest.includes("--target")) {
			const target = rest.slice(rest.indexOf("--target") + 1);
			if (target.length > 0 && target[0] === "install") {
				return (
					"`cmake --build --target install` はビルド成果物をシステムへインストールします。\n" +
					`実行しようとしているコマンド: ${clip200(segment)}\n` +
					"インストール先を確認して問題なければ承認してください。"
				);
			}
		}
		if (compilers.has(head) && rest.includes("-o")) {
			const output = rest.slice(rest.indexOf("-o") + 1);
			if (output.length > 0 && writesOutsideWorkspace(ctx, output[0])) {
				return (
					`\`${head} -o ${output[0]}\` はプロジェクトの外へ実行ファイルを書き出します。\n` +
					`実行しようとしているコマンド: ${clip200(segment)}\n` +
					"出力先を確認して問題なければ承認してください。"
				);
			}
		}
	}
	return null;
}

const GIT_CONFIG_DANGEROUS = [
	"alias.",
	"core.hookspath",
	"core.editor",
	"core.pager",
	"core.sshcommand",
	"core.fsmonitor",
	"credential.",
	"url.",
	"filter.",
	"diff.external",
	"difftool.",
	"mergetool.",
	"pager.",
	"include.path",
	"includeif.",
	"sequence.editor",
	"gpg.program",
	"ssh.variant",
	"protocol.",
];

/** 任意コマンド実行や資格情報の奪取に繋がる git config の書き込みを止める。 */
export function checkGitConfigWrite(ctx: Ctx, cmd: string): string | null {
	for (const command of commands(ctx, cmd)) {
		const tokens = argv(command);
		if (tokens.length < 3) continue;
		if (baseName(tokens[0]) !== "git" || tokens[1] !== "config") continue;
		const rest = tokens.slice(2).filter((t) => !t.startsWith("-"));
		if (rest.length === 0) continue;
		const key = rest[0].toLowerCase();
		if (GIT_CONFIG_DANGEROUS.some((prefix) => key.startsWith(prefix)) && rest.length > 1) {
			return `\`git config ${rest[0]}\` は任意コマンドの実行や資格情報の取得に繋がる設定です。\nエージェント経由での変更は許可されていません。`;
		}
	}
	return null;
}

/** `dd of=/dev/sda` のようにブロックデバイスへ直接書き込んでいないか。 */
export function checkBlockDeviceWrite(ctx: Ctx, cmd: string): string | null {
	for (const segment of segments(ctx, cmd)) {
		const m = pyRegex("\\bof=(/dev/\\S+)").exec(segment);
		if (m && !pyRegex("^/dev/(?:null|stdout|stderr|tty|zero)$").test(m[1])) {
			return `ブロックデバイス \`${m[1]}\` へ直接書き込もうとしています。\nディスクを破壊する操作は許可されていません。`;
		}
	}
	return null;
}

// PR ビューアの統合 CLI (merge-cli.ts) を起動するランタイムと、実行しない先頭のコマンド
const MERGE_CLI_RUNTIMES = new Set(["node", "nodejs", "tsx", "ts-node", "bun", "bunx", "deno", "npx", "pnpx", "pnpm", "yarn", "npm"]);
const MERGE_CLI_NON_EXECUTING = new Set(["echo", "printf", "grep", "rg", "cat", "man", "which", "type"]);
const MERGE_CLI_DENIED_SUBCOMMANDS = new Set(["merge", "recover"]);

/** PR ビューアの統合 CLI の `merge` / `recover` を、エージェントが叩く操作を拒否する (`plan` と参照は拒否しない)。 */
export function checkPrViewerMergeCli(ctx: Ctx, cmd: string): string | null {
	for (const segment of segments(ctx, cmd)) {
		for (const part of splitCommandSegments(segment)) {
			let tokens = shlexOrSplit(part);
			while (tokens.length > 0 && /^[A-Za-z_][A-Za-z0-9_]*=/u.test(tokens[0])) tokens = tokens.slice(1);
			if (tokens.length === 0 || MERGE_CLI_NON_EXECUTING.has(baseName(tokens[0]))) continue;
			const script = tokens.findIndex((t) => t.endsWith("merge-cli.ts"));
			if (script === -1) continue;
			if (script > 0 && !tokens.slice(0, script).some((t) => MERGE_CLI_RUNTIMES.has(cmdName(t)))) continue;
			const subcommand = tokens.slice(script + 1).find((t) => !t.startsWith("-"));
			if (subcommand !== undefined && MERGE_CLI_DENIED_SUBCOMMANDS.has(subcommand)) {
				return "PR ビューアの統合 CLI の merge / recover は、人が操作するものです。エージェントは実行できません。";
			}
		}
	}
	return null;
}
