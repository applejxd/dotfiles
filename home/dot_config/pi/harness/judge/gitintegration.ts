// bash の「統合コマンド」(保護ブランチへ入る・保護 ref を書き換える操作) の静的な検出 (純関数)。
//
// 判定器へはまだ接続しない。kind だけを返し、deny は返さない。
//   always  保護 ref を直接書き換える (どの worktree からでも統合)
//   head    現在のブランチを動かす (feature の worktree なら日常。保護ブランチの上なら統合。後続の動的検査が決める)
//   unknown 宛先・対象のリポジトリを静的に決められない
//   none    上のどれでもない (一覧外の git の書き込みも none)
// 検出は gitdestructive.ts と同じ流儀: 前置の環境変数・`env`・`command` と git のグローバルオプションを読み飛ばし、
// 引用の中の文字列はコマンドとして数えない。
//
// node の型除去でそのまま動く書き方だけを使う。
// see docs/change/0053-worktree-integration-gate.md
import { normalize, splitCommandSegments } from "./normalize.ts";
import { basename, shlexSplit, ShlexError } from "./pystr.ts";
import { isProtectedRef } from "./protectedrefs.ts";

export type Integration = { kind: "always" | "head" | "unknown" | "none"; reason: string; sub?: string };
type Kind = Integration["kind"];

const STRENGTH: Record<Kind, number> = { none: 0, head: 1, unknown: 2, always: 3 };
const NONE: Integration = { kind: "none", reason: "" };

const FLOW_TYPES = new Set(["feature", "release", "hotfix", "support", "bugfix"]);
const FLOW_ACTIONS = new Set(["finish", "delete", "abort"]);
const HEAD_SUBS = new Set(["merge", "cherry-pick", "revert", "pull", "am"]);

// 値を 1 つ取る git のグローバルオプション (`--opt=値` の形は 1 トークン)
const GLOBAL_WITH_VALUE = new Set(["-C", "-c", "--git-dir", "--work-tree", "--namespace", "--super-prefix", "--attr-source", "--config-env"]);
// 別のリポジトリ・作業ツリーを指す指定
const REPO_REDIRECT = new Set(["-C", "--git-dir", "--work-tree"]);

const WRAPPER_SKIP = new Set(["command", "time", "nohup", "exec", "builtin", "sudo", "!", "{", "(", "if", "then", "elif", "else", "do", "while", "until"]);
const ENV_ASSIGN = /^[A-Za-z_][A-Za-z0-9_]*=/;
const ENV_WITH_VALUE = new Set(["-u", "--unset", "-C", "--chdir", "-S", "--split-string"]);

// 解析に失敗したとき、統合系の語を含むかの粗い検査
const INTEGRATION_WORDS =
	/\bgit(?:-flow)?\b[\s\S]*\b(?:merge|cherry-pick|revert|pull|am|reset|flow|finish|update-ref|symbolic-ref|branch|fetch|worktree|fast-import|reflog)\b|\bgit-flow\b/;

const isDynamic = (s: string): boolean => /[$`*?[\]{}]/.test(s);

const strongest = (a: Integration, b: Integration): Integration => (STRENGTH[b.kind] > STRENGTH[a.kind] ? b : a);

/** heredoc の本文を落とす (本文はコマンドではない)。 */
function stripHeredocs(command: string): string {
	if (!command.includes("<<")) return command;
	const lines = command.split("\n");
	const out: string[] = [];
	let delim: string | null = null;
	let dash = false;
	for (const line of lines) {
		if (delim !== null) {
			if ((dash ? line.replace(/^\t+/, "") : line) === delim) delim = null;
			continue;
		}
		out.push(line);
		const m = /<<(-?)\s*(['"]?)([A-Za-z_][A-Za-z0-9_]*)\2/.exec(line);
		if (m && !line.includes("<<<")) {
			delim = m[3];
			dash = m[1] === "-";
		}
	}
	return out.join("\n");
}

interface Parsed {
	/** git (または git-flow) の呼び出し。なければ null */
	git: { flow: boolean; sub: string; args: string[] } | null;
	/** 対象のリポジトリ・ブランチを静的に決められなくする要素 (cd・-C・GIT_DIR= など) */
	redirect: boolean;
	/** `-c alias.…` で alias を定義している */
	alias: boolean;
	failed: boolean;
}

function parseSegment(segment: string): Parsed {
	const res: Parsed = { git: null, redirect: false, alias: false, failed: false };
	let tokens: string[];
	try {
		tokens = shlexSplit(segment);
	} catch (e) {
		if (!(e instanceof ShlexError)) throw e;
		res.failed = true;
		return res;
	}
	tokens = tokens.map((t) => t.replace(/^[({]+(?=.)/, ""));
	let i = 0;
	// 前置の環境変数・ラッパーを読み飛ばす
	while (i < tokens.length) {
		const t = tokens[i];
		if (ENV_ASSIGN.test(t)) {
			if (/^(?:GIT_DIR|GIT_WORK_TREE|GIT_COMMON_DIR|GIT_CONFIG_COUNT|GIT_CONFIG_PARAMETERS)=/.test(t)) res.redirect = true;
			i++;
		} else if (basename(t) === "env") {
			i++;
			while (i < tokens.length && (tokens[i].startsWith("-") || ENV_ASSIGN.test(tokens[i]))) {
				if (ENV_ASSIGN.test(tokens[i])) {
					if (/^(?:GIT_DIR|GIT_WORK_TREE|GIT_COMMON_DIR)=/.test(tokens[i])) res.redirect = true;
					i++;
				} else {
					i += ENV_WITH_VALUE.has(tokens[i]) ? 2 : 1;
				}
			}
		} else if (WRAPPER_SKIP.has(t)) {
			i++;
			if (t === "command" && i < tokens.length && /^-[vV]/.test(tokens[i])) return res; // 探すだけで実行しない
			while (t === "command" && i < tokens.length && tokens[i].startsWith("-")) i++;
		} else {
			break;
		}
	}
	if (i >= tokens.length) return res;
	const cmd = basename(tokens[i]);
	if (cmd === "cd" || cmd === "pushd") {
		res.redirect = true;
		return res;
	}
	const flow = cmd === "git-flow";
	if (cmd !== "git" && !flow) return res;
	i++;
	if (!flow) {
		while (i < tokens.length && tokens[i].startsWith("-")) {
			const t = tokens[i];
			const name = t.split("=", 1)[0];
			if (REPO_REDIRECT.has(name)) res.redirect = true;
			if (name === "-c" || name === "--config-env") {
				const value = t.includes("=") && name !== "-c" ? t.slice(name.length + 1) : (tokens[i + 1] ?? "");
				if (/^alias\./i.test(value)) res.alias = true;
			}
			i += GLOBAL_WITH_VALUE.has(t) ? 2 : 1;
			if (t === "--") break;
		}
	}
	if (i >= tokens.length) return res;
	res.git = flow
		? { flow: true, sub: "flow", args: tokens.slice(i) }
		: { flow: false, sub: tokens[i], args: tokens.slice(i + 1) };
	return res;
}

/** オプションを除いた引数 (位置引数) と、見つかったフラグ。valueShort/valueLong はその値を取るもの。 */
function scanArgs(args: string[], valueShort: string, valueLong: Set<string>) {
	const short = new Set<string>();
	const long = new Set<string>();
	const values: string[] = [];
	const positional: string[] = [];
	for (let i = 0; i < args.length; i++) {
		const t = args[i];
		if (t === "--") {
			positional.push(...args.slice(i + 1));
			break;
		}
		if (t.startsWith("--")) {
			const name = t.split("=", 1)[0];
			long.add(name);
			if (valueLong.has(name)) {
				if (t.includes("=")) values.push(t.slice(name.length + 1));
				else if (i + 1 < args.length) values.push(args[++i]);
			}
			continue;
		}
		if (t.startsWith("-") && t.length > 1) {
			for (let j = 1; j < t.length; j++) {
				const c = t[j];
				short.add(c);
				if (valueShort.includes(c)) {
					const rest = t.slice(j + 1);
					if (rest) values.push(rest);
					else if (i + 1 < args.length) values.push(args[++i]);
					break;
				}
			}
			continue;
		}
		positional.push(t);
	}
	return { short, long, values, positional };
}

// classifyIntegration の呼び出しの間だけ持つ保護 ref (同期処理なので入れ子にならない)
const PROTECTED: { current: readonly string[] } = { current: [] };

const hit = (kind: Kind, reason: string, sub: string): Integration => ({ kind, reason, sub });

/** 宛先の ref の判定。保護なら always、判定できなければ unknown、保護でなければ null。 */
function refVerdict(ref: string, what: string, sub: string): Integration | null {
	const patterns = PROTECTED.current;
	if (isDynamic(ref)) return hit("unknown", `${what}の宛先 ${ref} を静的に判定できない`, sub);
	if (isProtectedRef(ref, patterns)) return hit("always", `保護ブランチ ${ref.replace(/^refs\/heads\//i, "")} を変える ${what}`, sub);
	return null;
}

function classifyGit(g: NonNullable<Parsed["git"]>): Integration {
	const { sub, args } = g;
	if (g.flow) {
		const rest = args.filter((a) => !a.startsWith("-"));
		if (rest[0] === "integrate") return hit("always", "git flow integrate (保護ブランチへ統合する)", "flow");
		if (FLOW_TYPES.has(rest[0] ?? "") && FLOW_ACTIONS.has(rest[1] ?? "")) {
			return hit("always", `git flow ${rest[0]} ${rest[1]} (保護ブランチへ統合・削除する)`, "flow");
		}
		return NONE;
	}
	if (HEAD_SUBS.has(sub)) return hit("head", `git ${sub} (現在のブランチを動かす)`, sub);
	switch (sub) {
		case "flow":
			return classifyGit({ flow: true, sub, args });
		case "reset": {
			if (args.includes("--hard")) return NONE;
			return hit("head", "git reset (現在のブランチを動かす)", sub);
		}
		case "fast-import":
			return hit("unknown", "git fast-import (宛先の ref を静的に判定できない)", sub);
		case "reflog": {
			const act = args.find((a) => !a.startsWith("-"));
			if ((act === "delete" || act === "expire") && !args.includes("--dry-run") && !args.includes("-n")) {
				return hit("unknown", `git reflog ${act} (参照ログの書き込み)`, sub);
			}
			return NONE;
		}
		case "update-ref": {
			const a = scanArgs(args, "m", new Set());
			if (a.long.has("--stdin")) return hit("unknown", "git update-ref --stdin (宛先を静的に判定できない)", sub);
			const ref = a.positional[0];
			if (ref === undefined) return NONE;
			if (a.short.has("d") || a.long.has("--delete")) {
				return refVerdict(ref, "git update-ref -d", sub) ?? NONE;
			}
			if (ref.toUpperCase() === "HEAD") return hit("head", "git update-ref HEAD (現在のブランチを動かす)", sub);
			return refVerdict(ref, "git update-ref", sub) ?? NONE;
		}
		case "symbolic-ref": {
			const a = scanArgs(args, "m", new Set(["--message"]));
			if (a.short.has("d") || a.long.has("--delete")) return NONE;
			if (a.positional.length < 2) return NONE;
			let unknown: Integration | null = null;
			for (const ref of a.positional.slice(0, 2)) {
				const v = refVerdict(ref, "git symbolic-ref", sub);
				if (v?.kind === "always") return v;
				unknown = unknown ?? v;
			}
			return unknown ?? NONE;
		}
		case "branch": {
			const a = scanArgs(args, "u", new Set(["--set-upstream-to", "--sort", "--format", "--contains", "--no-contains", "--points-at", "--merged", "--no-merged", "--color", "--abbrev"]));
			const listing = a.short.has("l") || a.long.has("--list") || a.long.has("--show-current") || a.short.has("v") || a.long.has("--verbose");
			const writes = ["m", "M", "c", "C", "f"].some((c) => a.short.has(c)) || ["--move", "--copy", "--force"].some((n) => a.long.has(n));
			if (listing && !writes) return NONE;
			const plain = a.short.size === 0 && a.long.size === 0;
			const targets = writes ? a.positional : plain ? a.positional.slice(0, 1) : [];
			let unknown: Integration | null = null;
			for (const ref of targets) {
				const v = refVerdict(ref, writes ? "git branch (移動・複製・強制)" : "git branch (既存の保護ブランチと同名)", sub);
				if (v?.kind === "always") return v;
				unknown = unknown ?? v;
			}
			return unknown ?? NONE;
		}
		case "fetch": {
			const a = scanArgs(
				args,
				"jo",
				new Set(["--depth", "--deepen", "--shallow-since", "--shallow-exclude", "--jobs", "--server-option", "--refmap", "--filter", "--negotiation-tip", "--upload-pack", "--recurse-submodules"]),
			);
			let unknown: Integration | null = null;
			for (const spec of a.positional.slice(1)) {
				const colon = spec.indexOf(":");
				if (colon < 0) continue;
				const dst = spec.slice(colon + 1);
				if (dst === "") continue;
				// refs/heads/ の外に決まっている宛先は、保護ブランチではない
				if (/^refs\/(?!heads\/)/i.test(dst)) continue;
				const v = refVerdict(dst, "git fetch", sub);
				if (v?.kind === "always") return v;
				unknown = unknown ?? v;
			}
			return unknown ?? NONE;
		}
		case "worktree": {
			if (args[0] !== "add") return NONE;
			// -b / -B の値。`--reason` の値は branch ではない
			const wanted: string[] = [];
			const rest = args.slice(1);
			for (let i = 0; i < rest.length; i++) {
				const t = rest[i];
				if (t === "--") break;
				if (t === "--reason") i++;
				else if (/^-[bB]./.test(t)) wanted.push(t.slice(2));
				else if (t === "-b" || t === "-B") wanted.push(rest[++i] ?? "");
			}
			let unknown: Integration | null = null;
			for (const ref of wanted) {
				const v = refVerdict(ref, "git worktree add -b/-B", sub);
				if (v?.kind === "always") return v;
				unknown = unknown ?? v;
			}
			return unknown ?? NONE;
		}
		default:
			return NONE;
	}
}

/** コマンド全体を分類し、一番強いもの (always > unknown > head > none) を返す。 */
export function classifyIntegration(command: string, protectedRefs: readonly string[]): Integration {
	if (!/git/i.test(command)) return NONE;
	const cleaned = stripHeredocs(command);
	PROTECTED.current = protectedRefs;
	try {
		const originals = splitCommandSegments(cleaned);
		const seen = new Set(originals);
		const segments = [...originals];
		for (const s of normalize(cleaned)) {
			if (!seen.has(s)) {
				seen.add(s);
				segments.push(s);
			}
		}
		let best: Integration = NONE;
		let redirect = false;
		let alias = false;
		let failed = false;
		for (const segment of segments) {
			const p = parseSegment(segment);
			failed = failed || p.failed;
			redirect = redirect || p.redirect;
			alias = alias || p.alias;
			if (p.git) best = strongest(best, classifyGit(p.git));
		}
		if (alias) return hit("unknown", "git の alias を定義していて、実際の操作を静的に判定できない", "alias");
		if (best.kind !== "none" && best.kind !== "unknown" && redirect) {
			return hit("unknown", `${best.reason}。cd・-C・GIT_DIR などで対象のリポジトリ・ブランチが静的に決まらない`, best.sub);
		}
		if (failed && best.kind !== "always" && INTEGRATION_WORDS.test(cleaned)) {
			return STRENGTH[best.kind] > STRENGTH.unknown ? best : hit("unknown", "解析できないコマンドに統合系の語がある", best.sub);
		}
		return best;
	} finally {
		PROTECTED.current = [];
	}
}
