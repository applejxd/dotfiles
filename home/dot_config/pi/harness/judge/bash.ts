// bash の判定 (lib/decide.py の `_decide_bash` ほかの移植)。検査関数 (`checks.ts`) を順に当て、共通の禁止と役割の規則を返す。
//
// 共通の禁止 (deny) は bypass でも外れない。承認 (ask) は役割の許可の一覧より先に見る。
// 判定は呼び出しごとの文脈 `Ctx` で行い、呼び出し間で状態を持たない。
//
// node の型除去でそのまま動く書き方だけを使う。
// see docs/spec/guard/pi-decide.md
import { ASK_NAMES, CHECKS, DENY_NAMES, PATH_NAMES } from "./checks.ts";
import type { Ctx, Tables } from "./context.ts";
import { newCtx } from "./context.ts";
import type { BashDecider, Response } from "./decide.ts";
import { errorResponse, response } from "./decide.ts";
import { expandUser } from "./pathutil.ts";
import { findMatch, normalize, patternMatches, splitCommandSegments } from "./normalize.ts";
import type { Common } from "./policy.ts";
import { basename, pyLen, pyRegex, shlexSplit, ShlexError } from "./pystr.ts";
import { clip200, expandCdTargets, splitHeredocBody } from "./shared.ts";

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

function runChecks(
	ctx: Ctx,
	names: readonly string[],
	cmd: string,
	decision: "deny" | "ask",
	ruleName: string,
	confirmChecks: readonly string[] = [],
): Response | null {
	for (const name of names) {
		const check = CHECKS.get(name);
		if (check === undefined) throw new Error(`検査関数 ${name} が登録されていません`);
		const reason = check(ctx, cmd);
		if (reason) {
			// [pi.confirm] checks に載る検査の ask は、bypass でも確認する (理由の先頭は契約の接頭辞)
			if (decision === "ask" && confirmChecks.includes(name)) {
				return response("ask", `${MUST_CONFIRM_PREFIX}${reason}`, name === ruleName ? "rule" : "check", { check: name, mustConfirm: true });
			}
			return response(decision, reason, name === ruleName ? "rule" : "check", { check: name });
		}
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

function bashAsk(ctx: Ctx, cmd: string, pi: Obj): Response | null {
	const confirmChecks = ((pi.confirm?.checks as unknown[] | undefined) ?? []).map(String);
	// 確認に格上げする検査 (mustConfirm) は、他の ask (check_policy_ask など) より先に引く。
	// 先に別の ask が当たると mustConfirm が付かず、bypass で確認なしに通ってしまうため
	if (confirmChecks.length > 0) {
		const first = runChecks(ctx, ASK_NAMES.filter((n) => confirmChecks.includes(n)), cmd, "ask", "check_policy_ask", confirmChecks);
		if (first) return first;
	}
	return runChecks(ctx, ASK_NAMES, cmd, "ask", "check_policy_ask", confirmChecks);
}

// 契約: mustConfirm の ask の理由はこの接頭辞で始める (ハーネスの確認 UI が見る)
const MUST_CONFIRM_PREFIX = "確認が必要な外部への送信・公開 (bypass でも確認する): ";
// 本文・タイトルを利用者が確認できない形 (標準入力・コマンド置換) を deny にする対象
const BODY_CMD_RE = /^gh (?:pr|issue) (?:create|comment|edit|review)$/u;
const BODY_STDIN_FLAGS = new Set(["--body-file", "-F", "-b", "--body"]);
const BLIND_BODY_REASON = "本文を確認できない形 (標準入力・コマンド置換)。--body か --body-file <ファイル> で書き直す";

/** 正規化したセグメントの本文引数が標準入力 (`--body-file -` / `-F -` / `-b -` / `--body-file=-`) か。 */
function bodyFromStdin(segment: string): boolean {
	let tokens: string[];
	try {
		tokens = shlexSplit(segment);
	} catch (e) {
		if (!(e instanceof ShlexError)) throw e;
		// 解析できない形は本文を確認できないとみなす
		return true;
	}
	return tokens.some((t, i) => t === "--body-file=-" || (BODY_STDIN_FLAGS.has(t) && tokens[i + 1] === "-"));
}

/**
 * `[pi.confirm] bash` の確認表。当たれば `mustConfirm` の ask (bypass もサンドボックスの緩和も効かない)。
 * 本文を確認できない形の `gh pr|issue create|comment|edit|review` は deny。
 * see docs/spec/guard/pi-decide.md#confirm
 */
function confirmTable(cmd: string, pi: Obj): Response | null {
	const patterns = ((pi.confirm?.bash as unknown[] | undefined) ?? []).map(String);
	if (patterns.length === 0) return null;
	let first: string | null = null;
	let blind = false;
	for (const segment of normalize(cmd)) {
		const pat = patterns.find((p) => patternMatches(segment, p));
		if (!pat) continue;
		first = first ?? pat;
		if (BODY_CMD_RE.test(pat) && bodyFromStdin(segment)) blind = true;
	}
	if (first === null) return null;
	if (!blind) {
		const bodyPatterns = patterns.filter((p) => BODY_CMD_RE.test(p));
		// コマンド置換は元のセグメントの文字で見る (正規化を通すと内側に展開されうる)
		blind = splitCommandSegments(cmd).some(
			(raw) => (raw.includes("$(") || raw.includes("`")) && normalize(raw).some((s) => bodyPatterns.some((p) => patternMatches(s, p))),
		);
	}
	if (blind) return response("deny", BLIND_BODY_REASON, "rule");
	return response(
		"ask",
		`${MUST_CONFIRM_PREFIX}\`${first}\`\n実行しようとしているコマンド: ${clip200(cmd)}`,
		"rule",
		{ mustConfirm: true },
	);
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
 * see docs/spec/guard/pi-decide.md#ssh--scp-の許可
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
		const confirm = confirmTable(cmd, pi);
		if (confirm) return { commonDeny: null, roleRule: confirm };
		const ask = bashAsk(ctx, cmd, pi);
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
