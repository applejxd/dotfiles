// bash の判定 (lib/decide.py の `_decide_bash` ほかの移植)。検査関数 (`checks.ts`) を順に当て、共通の禁止と役割の規則を返す。
//
// 共通の禁止 (deny) は bypass でも外れない。承認 (ask) は役割の許可の一覧より先に見る。
// 判定は呼び出しごとの文脈 `Ctx` で行い、呼び出し間で状態を持たない。
//
// node の型除去でそのまま動く書き方だけを使う。
// see docs/spec/pi-decide.md
import { ASK_NAMES, CHECKS, DENY_NAMES, PATH_NAMES } from "./checks.ts";
import type { Ctx, Tables } from "./context.ts";
import { newCtx } from "./context.ts";
import type { BashDecider, Response } from "./decide.ts";
import { errorResponse, response } from "./decide.ts";
import { expandUser } from "./pathutil.ts";
import { findMatch, normalize, splitCommandSegments } from "./normalize.ts";
import type { Common } from "./policy.ts";
import { basename, pyLen, pyRegex, shlexSplit, ShlexError } from "./pystr.ts";
import { expandCdTargets, splitHeredocBody } from "./shared.ts";

// 検査の上限。check_bash.py と同じ
const MAX_COMMAND_LEN = 10000;
// allow の一覧に当たっても、書き込みや実行時の展開の余地がある形は allow にしない
const UNSAFE_FOR_ALLOW = [">", "<", "`", "$", "--output"];
// git が任意のプログラムを起動しうるオプション。allow の一覧に当たっても allow にしない
// グローバル (git とサブコマンドの間) の -c / --config-env / --exec-path / --paginate / -p が対象。サブコマンドの後ろの -p / -c は別の意味
const GIT_GLOBAL_ARG_OPTS = new Set(["-C", "-c", "--config-env", "--git-dir", "--work-tree", "--namespace", "--exec-path", "--super-prefix", "--attr-source"]);
const GIT_SUB_EXEC_OPTS = ["--upload-pack", "--receive-pack", "--ext-diff", "--exec", "--textconv"];

function isGitGlobalExecOpt(t: string): boolean {
	return t.startsWith("-c") || t === "-p" || t === "--paginate" || t === "--config-env" || t.startsWith("--config-env=") || t === "--exec-path" || t.startsWith("--exec-path=");
}

/** 元のセグメントの `git` のグローバル領域に実行系オプションが、サブコマンド以降に GIT_SUB_EXEC_OPTS (`--opt=値` を含む) があるか。正規化は前置オプションを落とすのでここで見る。 */
function hasGitExecOption(cmd: string): boolean {
	for (const raw of splitCommandSegments(cmd)) {
		let tokens: string[];
		try {
			tokens = shlexSplit(raw);
		} catch (e) {
			if (!(e instanceof ShlexError)) throw e;
			tokens = [raw];
		}
		tokens = tokens.flatMap((t) => t.split(/[ \t\n]+/)).filter((t) => t);
		const git = tokens.findIndex((t) => basename(t) === "git");
		if (git < 0) continue;
		let i = git + 1;
		while (i < tokens.length && tokens[i].startsWith("-")) {
			if (isGitGlobalExecOpt(tokens[i])) return true;
			i += GIT_GLOBAL_ARG_OPTS.has(tokens[i]) ? 2 : 1;
		}
		if (tokens.slice(i).some((t) => GIT_SUB_EXEC_OPTS.some((o) => t === o || t.startsWith(`${o}=`)))) return true;
	}
	return false;
}

// 代入として渡してよい環境変数の名前 (LC_ で始まる名前も可)。これ以外の `NAME=` 形のトークンがあれば allow にしない
const SAFE_ENV_NAMES = new Set(["LANG", "LC_ALL", "TZ", "NO_COLOR", "COLUMNS", "LINES", "TERM", "CI", "FORCE_COLOR", "CLICOLOR", "PYTHONDONTWRITEBYTECODE"]);

/** 元のコマンドのどこかに、安全な名前以外の `NAME=` 形のトークンか、`-` 始まりの引数を持つ `env` があるか。shlex が失敗したら true。 */
function hasUnsafeEnvPrefix(cmd: string): boolean {
	for (const raw of splitCommandSegments(cmd)) {
		let tokens: string[];
		try {
			tokens = shlexSplit(raw);
		} catch (e) {
			if (!(e instanceof ShlexError)) throw e;
			return true;
		}
		tokens = tokens
			.flatMap((t) => t.split(/[ \t\n]+/))
			.filter((t) => t)
			.map((t) => t.replace(/^[({;!]+/, ""));
		for (let i = 0; i < tokens.length; i++) {
			const m = /^([A-Za-z_][A-Za-z0-9_]*)=/.exec(tokens[i]);
			if (m && !SAFE_ENV_NAMES.has(m[1]) && !m[1].startsWith("LC_")) return true;
			if (basename(tokens[i]) === "env" && i + 1 < tokens.length && tokens[i + 1].startsWith("-")) return true;
		}
	}
	return false;
}

type Obj = Record<string, any>;

function runChecks(ctx: Ctx, names: readonly string[], cmd: string, decision: "deny" | "ask", ruleName: string): Response | null {
	for (const name of names) {
		const check = CHECKS.get(name);
		if (check === undefined) throw new Error(`検査関数 ${name} が登録されていません`);
		const reason = check(ctx, cmd);
		if (reason) return response(decision, reason, name === ruleName ? "rule" : "check", { check: name });
	}
	return null;
}

/** check_bash.py の deny 側と同じ順で検査する。当たれば deny の応答。 */
function bashCommonDeny(ctx: Ctx, cmd: string): Response | null {
	const deny = runChecks(ctx, DENY_NAMES, cmd, "deny", "check_policy_deny");
	if (deny) return deny;
	let cdVariant = "";
	try {
		cdVariant = expandCdTargets(cmd);
	} catch {
		// 解析できないときは作らない
	}
	if (cdVariant) return runChecks(ctx, PATH_NAMES, cdVariant, "deny", "");
	return null;
}

function bashAsk(ctx: Ctx, cmd: string): Response | null {
	return runChecks(ctx, ASK_NAMES, cmd, "ask", "check_policy_ask");
}

/** `[[pi.guide]]` (誘導) に当たれば、案内を理由にした deny。bypass でも外れない。 */
function guide(cmd: string, pi: Obj): Response | null {
	for (const g of (pi.guide as Obj[] | undefined) ?? []) {
		// scope 付きはここでは評価しない (foreground は judge/call.ts が guarded_bash だけに当てる)
		if (g.scope) continue;
		const { pattern, unless } = g;
		if (typeof pattern !== "string" || typeof g.message !== "string") {
			throw new Error(`[[pi.guide]] ${JSON.stringify(g.id ?? null)} に pattern と message が要ります`);
		}
		if (pyRegex(pattern).test(cmd) && !(unless && pyRegex(unless).test(cmd))) {
			return response("deny", g.message, "rule", { guide: g.id ?? null });
		}
	}
	return null;
}

/** 全セグメントが allow の一覧に当たれば、当たった最初のパターンを返す。 */
function allSegmentsAllowed(cmd: string, patterns: readonly string[]): string | null {
	if (patterns.length === 0 || UNSAFE_FOR_ALLOW.some((t) => cmd.includes(t)) || hasGitExecOption(cmd) || hasUnsafeEnvPrefix(cmd)) return null;
	const segments = normalize(cmd);
	if (segments.length === 0) return null;
	let first: string | null = null;
	for (const segment of segments) {
		const matched = findMatch(segment, patterns);
		if (!matched) return null;
		first = first || matched;
	}
	return first;
}

/** `[pi.skill_scripts]` の形に完全に当たれば、そのスクリプトを返す。 */
function skillScriptAllowed(cmd: string, pi: Obj): string | null {
	if (UNSAFE_FOR_ALLOW.some((t) => cmd.includes(t)) || [";", "&", "|", "\n"].some((t) => cmd.includes(t))) return null;
	let tokens: string[];
	try {
		tokens = shlexSplit(cmd);
	} catch (e) {
		if (e instanceof ShlexError) return null;
		throw e;
	}
	const cfg: Obj = pi.skill_scripts ?? {};
	const runners: Obj = cfg.runners ?? {};
	for (const entry of (cfg.allow as Obj[] | undefined) ?? []) {
		const script = String(entry.script ?? "");
		const suffix = script.includes(".") ? script.slice(script.lastIndexOf(".") + 1) : "";
		const paths = new Set([script, expandUser(script)]);
		for (const runner of (runners[suffix] as string[] | undefined) ?? []) {
			if (tokens.length < 2 || tokens[0] !== runner || !paths.has(tokens[1])) continue;
			const rest = tokens.slice(2);
			const exact: string[] = entry.exact ?? [];
			const subcommands: string[] = entry.subcommands ?? [];
			if (exact.length > 0) {
				if (rest.length === exact.length && rest.every((r, i) => r === exact[i])) return script;
			} else if (subcommands.length > 0) {
				if (rest.length > 0 && subcommands.includes(rest[0])) return script;
			} else {
				return script;
			}
		}
	}
	return null;
}

// ローカルの shell が解釈する文字。クォートの外にあれば、ssh の引数が「リモートへ渡る文字列」だと言い切れない
const LOCAL_SHELL_META = ";&|<>(){}$`\n*?[~#!";

/**
 * `ssh <許可した宛先> <コマンド>` / `scp [-rpqCv] <許可した宛先>:<パス> <ローカル>` (逆向きも) なら、
 * 通常の判定にかける文字列を返す (それ以外は null)。
 * - ssh: リモートで実行される文字列そのもの。
 * - scp: 転送を `cp` に置き換えた形。ローカル側の読み取り・書き込みの検査が cp と同じに効く
 *   (リモート側は `/dev/null` に置き換える。リモートのパスはローカルでは判定できない)。
 * ローカルの shell が先に解釈しうる形 (クォート外のメタ文字・二重引用符内の `$` や `` ` ``) は対象にしない。
 * 宛先の前のオプション (`-o ProxyCommand=…` など) は受け付けず、コマンドなし (対話 shell) も対象外。
 * see docs/spec/pi-decide.md#ssh--scp-の許可
 */
function unwrapRemoteExec(cmd: string, targets: readonly string[]): string | null {
	if (targets.length === 0) return null;
	const text = cmd.trim();
	const isScp = text.startsWith("scp ");
	// scp はリモートのパスに `~` を書く (`host:~/x`)。語頭の `~` はローカルでは展開されない `host:` の後ろなので許す
	const meta = isScp ? LOCAL_SHELL_META.replace("~", "") : LOCAL_SHELL_META;
	let quote = "";
	for (const c of text) {
		if (quote === "'") {
			if (c === "'") quote = "";
		} else if (quote === '"') {
			if (c === '"') quote = "";
			else if (c === "$" || c === "`" || c === "\\" || c === "!") return null;
		} else if (c === "'" || c === '"') {
			quote = c;
		} else if (c === "\\" || meta.includes(c)) {
			return null;
		}
	}
	if (quote) return null;
	let tokens: string[];
	try {
		tokens = shlexSplit(text);
	} catch (e) {
		if (e instanceof ShlexError) return null;
		throw e;
	}
	if (isScp) return unwrapScp(tokens, targets);
	if (tokens.length < 3 || tokens[0] !== "ssh" || !targets.includes(tokens[1])) return null;
	return tokens.slice(2).join(" ");
}

const SCP_FLAGS = new Set(["-r", "-p", "-q", "-C", "-v"]);
const shq = (t: string): string => (/^[\w@%+=:,./~-]+$/.test(t) ? t : `'${t.replaceAll("'", "'\\''")}'`);

/** scp の引数を、リモート側を `/dev/null` にした `cp` に置き換える。許す形は、リモートがちょうど 1 つで、アップロードかダウンロード 1 件。 */
function unwrapScp(tokens: string[], targets: readonly string[]): string | null {
	let i = 1;
	const flags: string[] = [];
	while (i < tokens.length && tokens[i].startsWith("-")) {
		if (!SCP_FLAGS.has(tokens[i])) return null;
		if (tokens[i] === "-r") flags.push("-r");
		i++;
	}
	const operands = tokens.slice(i);
	if (operands.length < 2) return null;
	const isRemote = (t: string): boolean => targets.some((h) => t.startsWith(`${h}:`));
	// 宛先以外の `host:` 形 (別ホスト・scp:// の URL) は、ローカルのファイルではないので受け付けない
	if (operands.some((t) => !isRemote(t) && /^[^/]*:/.test(t))) return null;
	const remotes = operands.filter(isRemote).length;
	if (remotes !== 1) return null;
	const last = operands[operands.length - 1];
	let local: string[];
	if (isRemote(last)) local = [...operands.slice(0, -1), "/dev/null"];
	else if (isRemote(operands[0]) && operands.length === 2) local = ["/dev/null", last];
	else return null;
	return ["cp", ...flags, ...local.map(shq)].join(" ");
}

/** bash の判定器を作る。`tables` は tables.toml を JSON にしたもの。 */
export function makeBashDecider(tables: Tables): BashDecider {
	const decide = (
		rawCmd: string,
		cwd: string,
		pi: Obj,
		profile: Obj,
		common: Common,
		remote: boolean,
	): ReturnType<BashDecider> => {
		// 判定ごとに文脈を作り直す (呼び出しの順に依らない)
		const ctx = newCtx(tables, common, cwd);
		let cmd = rawCmd;
		const loaded = CHECKS.get("check_policy_loaded")?.(ctx, cmd);
		if (loaded) return { commonDeny: errorResponse(loaded), roleRule: null };
		if (pyLen(cmd) > MAX_COMMAND_LEN) {
			return { commonDeny: errorResponse(`コマンドが長すぎます (${pyLen(cmd)} 文字)`), roleRule: null };
		}
		try {
			cmd = splitHeredocBody(ctx, cmd);
		} catch {
			// 解析できないときは元の文字列で検査
		}
		// ssh の許可は 1 段だけ。中身は同じ判定にかけるので、リモート側の `ssh` はそのまま deny に当たる
		const targets = ((pi.remote_exec?.targets as unknown[] | undefined) ?? []).map(String);
		const inner = remote ? null : unwrapRemoteExec(cmd, targets);
		if (inner !== null) return decide(inner, cwd, pi, profile, common, true);
		const deny = bashCommonDeny(ctx, cmd);
		if (deny) return { commonDeny: deny, roleRule: null };
		const g = guide(cmd, pi);
		if (g) return { commonDeny: null, roleRule: g };
		// 役割だけの禁止。共通の禁止ではないが、bypass では外れない (bypass は ask だけを変える)
		const roleDeny = findMatch(cmd, ((profile.shell_deny as unknown[] | undefined) ?? []).map(String));
		if (roleDeny) {
			return { commonDeny: null, roleRule: response("deny", `\`${roleDeny}\` はこの役割の shell_deny にある`, "rule") };
		}
		const ask = bashAsk(ctx, cmd);
		if (ask) return { commonDeny: null, roleRule: ask };
		// 役割が shell_allow を持てば、[pi.shell] allow の代わりにそれを使う
		const own = profile.shell_allow;
		const allowList: unknown[] = own != null ? own : (pi.shell?.allow ?? []);
		const where = own != null ? "役割の shell_allow" : "[pi.shell] allow";
		const matched = allSegmentsAllowed(cmd, allowList.map(String));
		if (matched) return { commonDeny: null, roleRule: response("allow", `\`${matched}\` は ${where} にある`, "rule") };
		const script = skillScriptAllowed(cmd, pi);
		if (script) return { commonDeny: null, roleRule: response("allow", `\`${script}\` は [pi.skill_scripts] にある`, "rule") };
		return { commonDeny: null, roleRule: null };
	};
	return (rawCmd, cwd, pi, profile, common: Common) => decide(rawCmd, cwd, pi, profile, common, false);
}
