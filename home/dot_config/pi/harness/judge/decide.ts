// 判定 API (decide.py の移植)。CLI に依存せず、allow / ask / deny と理由を必ず返す。例外は投げない。
//
// 評価順: 共通の禁止 → 役割のツール → 役割の確認と許可 → 既定 → bypass (ask だけを allow にする)。
// bash の意味解析 (bashrules / command_policy の正規化) はまだ移植していない。移植が済むまで、
// bash は「判定に失敗した」deny (source: error) を返す (許可側へは倒れない)。
// 正解データ (test/agents/golden/decide_golden.jsonl) との一致で進捗を測る (test/agents/pi/judge_golden.mjs)。
//
// node の型除去でそのまま動く書き方だけを使う。
// see docs/spec/pi-decide.md
import { realpathSync } from "node:fs";
import { isAbsolute, join, normalize, sep } from "node:path";
import type { Common } from "./policy.ts";
import {
	expandUser,
	loadFileGlobs,
	loadReadDenyExceptions,
	matchesAnyGlob,
	matchesReadDeny,
	TypeErrorPy,
	ValueError,
} from "./policy.ts";

export type Decision = "allow" | "ask" | "deny";
export type Response = { decision: Decision; reason: string; source: string; [extra: string]: unknown };
export type Request = {
	tool: string;
	input: Record<string, any>;
	cwd: string;
	role: string;
	bypass?: boolean;
	/** サンドボックスの内側と証明できているか。true のときだけ、下の緩和が効く (基準は保守的) */
	boundary?: boolean;
	/** サンドボックスが実際に開けた場所 (起動時の許可)。boundary のとき、作業ツリーの外の判定に使う */
	allowed?: { read: string[]; write: string[] };
};

const DECISIONS: readonly string[] = ["allow", "ask", "deny"];
const FILE_READ_TOOLS = ["read", "grep", "find", "ls"];
const FILE_WRITE_TOOLS = ["edit", "write"];
const TASK_TOOL = "task";
const TODO_TOOL = "todo";
const ASK_TOOL = "ask";

/** bash の判定器。移植が済むまでは差し込まれない。 */
export type BashDecider = (
	cmd: string,
	cwd: string,
	pi: Record<string, any>,
	profile: Record<string, any>,
	common: Common,
) => { commonDeny: Response | null; roleRule: Response | null };

export const response = (decision: Decision, reason: string, source: string, extra: Record<string, unknown> = {}): Response => ({
	decision,
	reason,
	source,
	...extra,
});
export const errorResponse = (reason: string): Response => response("deny", reason, "error");

/** Python の repr(str) に近い表記 (応答の理由の一致のため)。 */
const pyRepr = (s: string): string => {
	const quote = s.includes("'") && !s.includes('"') ? '"' : "'";
	const body = s.replaceAll("\\", "\\\\").replaceAll("\n", "\\n").replaceAll("\r", "\\r").replaceAll("\t", "\\t");
	return quote + (quote === "'" ? body.replaceAll("'", "\\'") : body) + quote;
};

const isObject = (v: unknown): v is Record<string, any> =>
	v !== null && typeof v === "object" && !Array.isArray(v);

function loadPi(common: Common): Record<string, any> {
	const pi = common.pi;
	if (!isObject(pi)) throw new ValueError("[pi] がありません");
	return pi;
}

function profileOf(pi: Record<string, any>, role: string): Record<string, any> {
	const profiles = pi.profiles;
	const profile = isObject(profiles) ? profiles[role] : undefined;
	if (!isObject(profile)) throw new ValueError(`役割 ${pyRepr(role)} が [pi.profiles] にありません`);
	const { tools, default: dflt } = profile;
	if (!Array.isArray(tools) || !tools.every((t) => typeof t === "string")) {
		throw new ValueError(`[pi.profiles.${role}] tools が文字列の配列ではありません`);
	}
	if (!DECISIONS.includes(dflt)) {
		throw new ValueError(`[pi.profiles.${role}] default が allow / ask / deny ではありません`);
	}
	for (const key of ["shell_allow", "shell_deny"]) {
		const value = profile[key];
		if (value !== undefined && (!Array.isArray(value) || !value.every((c) => typeof c === "string"))) {
			throw new ValueError(`[pi.profiles.${role}] ${key} が文字列の配列ではありません`);
		}
	}
	return profile;
}

/** 役割の tools に入っているか。末尾が `*` の項目は前方一致 (`mcp__*` など)。 */
const toolIn = (tool: string, tools: string[]): boolean =>
	tools.some((t) => (t.endsWith("*") ? tool.startsWith(t.slice(0, -1)) : tool === t));

// ─── ファイル ──────────────────────────────────────────────

/** Python の os.path.normpath (末尾の `/` を落とす)。 */
function normpath(path: string): string {
	const n = normalize(path);
	return n.length > 1 && n.endsWith(sep) ? n.slice(0, -1) : n;
}

/** Python の os.path.realpath (存在しない後ろの部分はそのまま残す)。 */
function realpathLoose(path: string): string {
	let head = path;
	let tail = "";
	for (;;) {
		try {
			const real = realpathSync(head);
			return tail ? join(real, tail) : real;
		} catch {
			const slash = head.lastIndexOf(sep);
			if (slash <= 0) return path;
			tail = tail ? `${head.slice(slash + 1)}${sep}${tail}` : head.slice(slash + 1);
			head = head.slice(0, slash);
		}
	}
}

/** 照合に使うパスの形: 渡されたまま・cwd で解いた絶対パス・symlink を解いた実体。 */
function candidates(path: string, cwd: string): string[] {
	const expanded = expandUser(path);
	const absolute = normpath(isAbsolute(expanded) ? expanded : join(cwd, expanded));
	const out = [path, absolute];
	try {
		out.push(realpathLoose(absolute));
	} catch {
		// 解けなければ見送る
	}
	return [...new Set(out)];
}

function inside(path: string, root: string): boolean {
	const r = normpath(root);
	return path === r || path.startsWith(r.replace(/\/+$/, "") + sep);
}

function decideFile(
	tool: string,
	path: string,
	cwd: string,
	pi: Record<string, any>,
	common: Common,
	allowed?: Request["allowed"],
): { commonDeny: Response | null; roleRule: Response | null } {
	const write = FILE_WRITE_TOOLS.includes(tool);
	const key = write ? "write_deny_globs" : "read_deny_globs";
	const globs = loadFileGlobs(common, key);
	if (globs.length === 0) return { commonDeny: errorResponse(`[file] ${key} がありません`), roleRule: null };
	const exceptions = loadReadDenyExceptions(common);
	let cands = candidates(path, cwd);
	// ディレクトリを渡す grep / find / ls は、中のファイルの形でも見る (.ssh -> .ssh/x)
	if (["grep", "find", "ls"].includes(tool)) cands = [...cands, ...cands.map((c) => `${c.replace(/\/+$/, "")}/_`)];
	for (const candidate of cands) {
		const matched = matchesReadDeny(candidate, globs, exceptions);
		if (matched) {
			return {
				commonDeny: response("deny", `\`${path}\` は [file] ${key} の \`${matched}\` に当たる`, "rule"),
				roleRule: null,
			};
		}
	}

	const absolute = candidates(path, cwd).at(-1)!;
	const insideCwd = inside(absolute, realpathLoose(cwd));
	if (write) {
		const askGlobs = loadFileGlobs(common, "write_ask_globs");
		const matched = matchesAnyGlob(path, askGlobs) || matchesAnyGlob(absolute, askGlobs);
		if (matched) {
			return {
				commonDeny: null,
				roleRule: response("ask", `\`${path}\` は [file] write_ask_globs の \`${matched}\` に当たる`, "rule"),
			};
		}
		if (!insideCwd) {
			// サンドボックスの内側: OS が開けた場所なら許可、外なら理由つきの deny (確認しても OS が拒否する)
			if (allowed) return { commonDeny: null, roleRule: sandboxFile("書き込み", path, absolute, allowed.write) };
			return { commonDeny: null, roleRule: response("ask", `\`${path}\` は作業ツリーの外への書き込み`, "rule") };
		}
		return { commonDeny: null, roleRule: response("allow", "作業ツリーの中への書き込み", "rule") };
	}

	const askGlobs = loadFileGlobs(common, "read_ask_globs");
	const matched = matchesAnyGlob(path, askGlobs) || matchesAnyGlob(absolute, askGlobs);
	if (matched) {
		return {
			commonDeny: null,
			roleRule: response("ask", `\`${path}\` は [file] read_ask_globs の \`${matched}\` に当たる`, "rule"),
		};
	}
	if (insideCwd) return { commonDeny: null, roleRule: response("allow", "作業ツリーの中の読み取り", "rule") };
	const opened = ((pi.external_read ?? {}).paths ?? []).map((d: string) => realpathLoose(expandUser(String(d))));
	if (opened.some((d: string) => inside(absolute, d))) {
		return { commonDeny: null, roleRule: response("allow", "[pi.external_read] で開けた場所の読み取り", "rule") };
	}
	if (allowed) {
		return { commonDeny: null, roleRule: sandboxFile("読み取り", path, absolute, [...allowed.read, ...allowed.write]) };
	}
	return { commonDeny: null, roleRule: response("ask", `\`${path}\` は作業ツリーの外の読み取り`, "rule") };
}

/** サンドボックスの内側での、作業ツリーの外の読み書き。OS が開けた場所だけ allow し、外は理由つきの deny。 */
function sandboxFile(kind: string, path: string, absolute: string, opened: string[]): Response {
	const roots = opened.map((d) => realpathLoose(expandUser(String(d))));
	if (roots.some((d) => inside(absolute, d))) {
		return response("allow", `サンドボックスが開けた場所の${kind}`, "rule");
	}
	const fix =
		kind === "読み取り"
			? "読み取りを足すには、起動前に環境変数 `PIS_EXTRA_READ` (例: `PIS_EXTRA_READ=~/dataset`)、またはそのリポジトリの `.opencode/sandbox.toml` の `read` に書いて、`pis` を起動し直す"
			: "書き込みを足すには、そのリポジトリの `.opencode/sandbox.toml` の `write` に書いて、`pis` を起動し直す";
	return response("deny", `\`${path}\` はサンドボックスの外の${kind}。OS も拒否する (${fix})`, "rule");
}

// ─── 入口 ────────────────────────────────────────────────

function validate(request: unknown): string | null {
	if (!isObject(request)) return "request がオブジェクトではありません";
	if (typeof request.tool !== "string") return "tool が文字列ではありません";
	if (!isObject(request.input)) return "input がオブジェクトではありません";
	if (typeof request.cwd !== "string" || !isAbsolute(request.cwd)) return "cwd が絶対パスではありません";
	if (typeof request.role !== "string") return "role が文字列ではありません";
	for (const key of ["bypass", "boundary"]) {
		const value = request[key];
		if (value !== undefined && typeof value !== "boolean") return `${key} が真偽値ではありません`;
	}
	const allowed = request.allowed;
	if (allowed !== undefined) {
		const strings = (v: unknown) => Array.isArray(v) && v.every((x) => typeof x === "string");
		if (!isObject(allowed) || !strings(allowed.read) || !strings(allowed.write)) {
			return "allowed が { read, write } (文字列の配列) ではありません";
		}
	}
	return null;
}

/** bash の判定器。差し込まれていなければ「判定に失敗した」deny になる (許可側へ倒れない)。 */
let bashDecider: BashDecider | null = null;
export function setBashDecider(decider: BashDecider | null): void {
	bashDecider = decider;
}

function decideInner(request: unknown, common: Common): Response {
	const invalid = validate(request);
	if (invalid) return errorResponse(invalid);
	const req = request as Request;
	const { tool, input: toolInput, cwd } = req;

	const pi = loadPi(common);
	const profile = profileOf(pi, req.role);

	// 1. 共通の禁止と、2〜3 の材料
	let commonDeny: Response | null;
	let roleRule: Response | null;
	if (tool === "bash") {
		const cmd = toolInput.command;
		if (typeof cmd !== "string" || !cmd) return errorResponse("bash の command がありません");
		if (!bashDecider) throw new TypeErrorPy("bash の判定器は未移植");
		({ commonDeny, roleRule } = bashDecider(cmd, cwd, pi, profile, common));
	} else if (FILE_READ_TOOLS.includes(tool) || FILE_WRITE_TOOLS.includes(tool)) {
		const path = toolInput.path ?? (["grep", "find", "ls"].includes(tool) ? "." : undefined);
		if (typeof path !== "string" || !path) return errorResponse(`${tool} の path がありません`);
		({ commonDeny, roleRule } = decideFile(tool, path, cwd, pi, common, req.boundary ? req.allowed : undefined));
	} else if (tool === TASK_TOOL) {
		commonDeny = null;
		roleRule = response("allow", "子エージェントは同じハーネスと判定器で動く", "rule");
	} else if (tool === TODO_TOOL) {
		commonDeny = null;
		roleRule = response("allow", "タスクリストはメモリの状態だけを変える", "rule");
	} else if (tool === ASK_TOOL) {
		commonDeny = null;
		roleRule = response("allow", "利用者への質問は UI だけを使う (ファイルも外部も触らない)", "rule");
	} else {
		commonDeny = null;
		roleRule = null;
	}
	if (commonDeny) return commonDeny;

	// 2. 役割のツール
	if (!toolIn(tool, profile.tools)) {
		return response("deny", `役割 ${pyRepr(req.role)} は ${tool} を使えない`, "rule");
	}

	// 3. 役割の確認と許可、4. 既定
	const result =
		roleRule ?? response(profile.default, `どの規則にも当たらない (役割 ${pyRepr(req.role)} の既定)`, "default");

	// 4'. サンドボックスの内側 (証明済み) では、日常の shell の確認だけを外す。
	//     [bash] ask・意味解析の ask・誘導・deny はそのまま (どの規則にも当たらず、役割の既定の ask になったものだけ)
	if (req.boundary && tool === "bash" && result.source === "default" && result.decision === "ask") {
		return response("allow", "サンドボックスの内側の日常の shell (どの規則にも当たらない)", "rule", { sandboxed: true });
	}

	// 5. bypass は ask だけを allow にする (deny はそのまま)
	if (req.bypass && result.decision === "ask") return { ...result, decision: "allow", bypassed: true };
	return result;
}

/** 判定する。例外は投げず、異常はすべて `source: error` の deny にする。 */
export function decide(request: unknown, common: Common): Response {
	try {
		return decideInner(request, common);
	} catch (exc) {
		const name = exc instanceof Error ? exc.name : "Error";
		const message = exc instanceof Error ? exc.message : String(exc);
		return errorResponse(`判定に失敗しました (${name}: ${message})`);
	}
}
