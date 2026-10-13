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
import { findMatch, normalize } from "./normalize.ts";
import type { Common } from "./policy.ts";
import { pyLen, pyRegex, shlexSplit, ShlexError } from "./pystr.ts";
import { expandCdTargets, splitHeredocBody } from "./shared.ts";

// 検査の上限。check_bash.py と同じ
const MAX_COMMAND_LEN = 10000;
// allow の一覧に当たっても、書き込みや実行時の展開の余地がある形は allow にしない
const UNSAFE_FOR_ALLOW = [">", "<", "`", "$(", "--output"];

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
	if (patterns.length === 0 || UNSAFE_FOR_ALLOW.some((t) => cmd.includes(t))) return null;
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

/** bash の判定器を作る。`tables` は tables.toml を JSON にしたもの。 */
export function makeBashDecider(tables: Tables): BashDecider {
	return (rawCmd, cwd, pi, profile, common: Common) => {
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
}
