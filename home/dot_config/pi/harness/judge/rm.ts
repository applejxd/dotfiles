// 削除 (rm / find -delete) の判定 (bashrules/rm.py の移植)。
//
// 壊滅的な対象 (ルート・ホーム・workspace 全体・.git 配下) は deny、workspace
// 内と確証できるものは承認を省く。その「確証できるか」の判定が中心。
//
// node の型除去でそのまま動く書き方だけを使う。
// see docs/spec/guard/pi-decide.md#ts-版への移植
import type { Ctx } from "./context.ts";
import { tableSet } from "./context.ts";
import { expandUser, isAbsolute, join, normpath, sep } from "./pathutil.ts";
import { basename, pyRegex, strip } from "./pystr.ts";
import { argv } from "./shellparse.ts";
import { stripExecWrappers } from "./rules_exec.ts";
import {
	canonicalRmTarget,
	changesBaseDir,
	clip200,
	commands,
	isFindPlaceholder,
	realpathStaysInside,
	resolvesIntoScratch,
	workspaceRoot,
} from "./shared.ts";

const FIND_DANGEROUS_EXEC_RE = pyRegex(
	"\\bfind\\b.+?" +
		"(?:" +
		"-exec\\s+(?:rm|unlink|shred|rmdir)\\b" + // -exec rm/unlink/shred/rmdir
		"|-delete\\b" + // -delete フラグ
		")",
	"is",
);
const FIND_WORD_RE = pyRegex("\\bfind\\b");
const XARGS_RE = pyRegex("(?:^|[\\s;&|(])xargs(?![\\w-])");
const CD_RE = pyRegex("(?:^|[\\s;&|(\"'\\\\])(?:cd|pushd|popd|chdir)(?![\\w-])");
// /home/<user> や /Users/<user> のようなホームディレクトリそのもの
const HOME_DIR_RE = pyRegex("^/(?:home|Users)/[^/]+$");
const RM_BIN_RE = pyRegex("^(?:/\\S*/)?(?:rm|rmdir|unlink)$");

const isRm = (head: string): boolean => RM_BIN_RE.test(basename(head));
const isFind = (head: string): boolean => basename(head) === "find";

/** Python の `fnmatch.fnmatchcase` (`*` `?` `[seq]` `[!seq]`)。 */
export function fnmatchCase(name: string, pat: string): boolean {
	let out = "";
	const p = Array.from(pat);
	let i = 0;
	while (i < p.length) {
		const c = p[i++];
		if (c === "*") {
			out += "[^]*";
		} else if (c === "?") {
			out += "[^]";
		} else if (c === "[") {
			let j = i;
			if (j < p.length && p[j] === "!") j++;
			if (j < p.length && p[j] === "]") j++;
			while (j < p.length && p[j] !== "]") j++;
			if (j >= p.length) {
				out += "\\[";
			} else {
				let stuff = p.slice(i, j).join("");
				i = j + 1;
				stuff = stuff.replace(/\\/g, "\\\\");
				if (stuff[0] === "!") stuff = `^${stuff.slice(1)}`;
				else if (stuff[0] === "^" || stuff[0] === "[") stuff = `\\${stuff}`;
				out += `[${stuff}]`;
			}
		} else {
			out += c.replace(/[.*+?^${}()|[\]\\/-]/g, "\\$&");
		}
	}
	try {
		return new RegExp(`^${out}$`, "u").test(name);
	} catch {
		// Python は不正な範囲 (`[z-a]`) を空集合として扱う
		return false;
	}
}

/** 正規化済みのセグメントと元の文字列から、`isTarget` のコマンドの引数列を集める。実行ラッパーは外す。 */
function argvsOf(ctx: Ctx, cmd: string, isTarget: (head: string) => boolean): string[][] {
	const out: string[][] = [];
	for (const command of commands(ctx, cmd)) {
		const a = stripExecWrappers(ctx, argv(command));
		if (a.length > 0 && isTarget(a[0])) out.push(a);
	}
	return out;
}

function isCatastrophicRmTarget(ctx: Ctx, token: string): boolean {
	const canonical = canonicalRmTarget(token);
	if (canonical === null) return false;
	if (tableSet(ctx, "_shared", "home_tokens").has(canonical) || canonical === "..") return true;
	if (tableSet(ctx, "rm", "catastrophic_dirs").has(canonical)) return true;
	if (HOME_DIR_RE.test(canonical)) return true;
	if (canonical === expandUser("~")) return true;
	// `.git` は自身だけでなく配下も対象にする。`.g*t` のようにドット始まりの glob で届く形も含める
	const parts = canonical.split("/").filter((p) => p);
	for (const part of parts) {
		if (part === ".git") return true;
		if (part.startsWith(".") && fnmatchCase(".git", part)) return true;
		// ブレース展開の候補に `.git` が含まれる形
		if (part.includes("{") && part.split(/[{},]/).includes(".git")) return true;
	}
	// `~/.ssh` のような秘密領域そのものの削除も承認の対象外
	const base = basename(canonical);
	if ([".ssh", ".gnupg", ".aws", ".config", ".local"].includes(base)) return true;
	// `$PWD/../..` のように相対で上位へ抜ける形。`..` が 2 段以上あれば壊滅的とみなす
	return canonical.split("..").length - 1 >= 2;
}

/** `find -exec rm` や `find -delete` でファイルを削除しようとしていないか。 */
export function checkFindDangerous(ctx: Ctx, cmd: string): string | null {
	if (!FIND_WORD_RE.test(cmd)) return null;
	if (!FIND_DANGEROUS_EXEC_RE.test(cmd)) return null;
	// 探索起点が使い捨ての一時ディレクトリ配下だけなら承認を省く
	if (findTargetsScratchOnly(ctx, cmd)) return null;
	// find の探索起点が壊滅的なら deny 側で処理する
	for (const a of argvsOf(ctx, cmd, isFind)) {
		for (const token of a.slice(1)) {
			if (token.startsWith("-")) break;
			if (isCatastrophicRmTarget(ctx, token)) return null;
		}
	}
	return (
		"`find` コマンドによるファイル削除操作（-exec rm / -delete 等）です。\n" +
		`実行しようとしているコマンド: ${clip200(cmd)}\n` +
		"削除対象を確認して問題なければ承認してください。"
	);
}

/** `find ~ -delete` のように壊滅的な範囲を一括削除していないか。 */
export function checkFindRootGuard(ctx: Ctx, cmd: string): string | null {
	if (!FIND_DANGEROUS_EXEC_RE.test(cmd)) return null;
	for (const a of argvsOf(ctx, cmd, isFind)) {
		for (const token of a.slice(1)) {
			if (token.startsWith("-")) break;
			if (isCatastrophicRmTarget(ctx, token)) {
				return (
					`\`find\` が壊滅的なパス \`${token}\` を起点に削除しようとしています。\n` +
					"システム全体・ホーム・親ディレクトリの一括削除は承認の対象外です。"
				);
			}
		}
	}
	return null;
}

/** `rm` が ask になったとき、承認不要な書き方を示すヒント。 */
export function rmAskHint(cmd: string): string {
	if (!cmd.includes(".tmp")) return "";
	return (
		"\n代替: 対象が ./.tmp 配下なら `rm -rf .tmp/<名前>` の形で書けば承認は不要です。\n" +
		"`cd`・変数展開 (`$PWD` など)・`xargs` と混ぜると対象を静的に確認できず、承認が必要になります。"
	);
}

/** `rm` の対象がすべて workspace 内だと確証できるか。確証できないものは false (承認を求める)。 */
function rmIsWorkspaceLocal(ctx: Ctx, cmd: string): boolean {
	let workspace = ctx.payloadCwd;
	if (!workspace || !isAbsolute(workspace)) return false;
	workspace = normpath(workspace);
	// 基点を変えるもの (`cd` / `pushd` / `popd` / `chdir`) が含まれたら判定しない
	if (CD_RE.test(cmd)) return false;
	// 対象が標準入力から来る形は静的に読めない
	if (XARGS_RE.test(cmd)) return false;

	let sawTarget = false;
	for (const a of argvsOf(ctx, cmd, isRm)) {
		const targets = a.slice(1).filter((t) => !t.startsWith("-"));
		if (targets.length === 0) return false;
		for (const token of targets) {
			if (!token) return false;
			// 展開・ブレース展開は静的に解決できない
			if (Array.from("$`~{}").some((ch) => token.includes(ch))) return false;
			if (token.startsWith("/")) return false;
			const components = token.split("/").filter((p) => p);
			if (components.includes("..")) return false;
			// `.g*t` のように glob がドットディレクトリへ届く形は読めない
			if (components.some((c) => c.startsWith(".") && Array.from("*?[").some((g) => c.includes(g)))) return false;
			// `*` だけのようなトークンは範囲が読めない
			if (!/[^*?/.[\]]/u.test(token)) return false;
			const resolved = normpath(join(workspace, token));
			if (resolved !== workspace && !resolved.startsWith(workspace + sep)) return false;
			// 成分に symlink があると normpath だけでは外へ抜ける
			if (!realpathStaysInside(workspace, resolved)) return false;
			sawTarget = true;
		}
	}
	return sawTarget;
}

/** `rm` の対象がすべて scratch ディレクトリ配下だと確証できるか。 */
function rmTargetsScratchOnly(ctx: Ctx, cmd: string): boolean {
	const workspace = workspaceRoot(ctx);
	if (workspace === null) return false;
	if (changesBaseDir(cmd)) return false;
	if (XARGS_RE.test(cmd)) return false;

	let sawTarget = false;
	let findScratchOnly: boolean | null = null;
	for (const a of argvsOf(ctx, cmd, isRm)) {
		let targets = a.slice(1).filter((t) => !t.startsWith("-"));
		if (targets.length === 0) return false;
		// `find ... -exec rm {} +` 展開形の終端記号は削除対象ではない
		if (targets.some(isFindPlaceholder)) targets = targets.filter((t) => !["+", ";", "\\;"].includes(t));
		for (const token of targets) {
			if (isFindPlaceholder(token)) {
				// `find ./.tmp -exec rm {} +` を normalize が `rm {}` に展開した形。実際の対象は find の探索起点なので、そちらで判定する
				if (findScratchOnly === null) findScratchOnly = findTargetsScratchOnly(ctx, cmd);
				if (!findScratchOnly) return false;
				sawTarget = true;
				continue;
			}
			if (!resolvesIntoScratch(ctx, token, workspace)) return false;
			sawTarget = true;
		}
	}
	return sawTarget;
}

/** `find` の探索起点がすべて scratch 配下で、削除先も広がらないか。 */
function findTargetsScratchOnly(ctx: Ctx, cmd: string): boolean {
	const execFlags = tableSet(ctx, "rm", "find_exec_flags");
	const workspace = workspaceRoot(ctx);
	if (workspace === null) return false;
	if (changesBaseDir(cmd)) return false;
	if (XARGS_RE.test(cmd)) return false;

	let sawRoot = false;
	for (const a of argvsOf(ctx, cmd, isFind)) {
		const rest = a.slice(1);
		const roots: string[] = [];
		for (const token of rest) {
			if (token.startsWith("-")) break;
			roots.push(token);
		}
		// 起点の省略は cwd 全体が対象になる
		if (roots.length === 0) return false;
		for (const root of roots) {
			if (!resolvesIntoScratch(ctx, root, workspace)) return false;
			sawRoot = true;
		}
		for (let index = 0; index < rest.length; index++) {
			if (!execFlags.has(rest[index])) continue;
			// `-exec <cmd> [args...] ;|+` の args を見る
			let cursor = index + 2;
			while (cursor < rest.length && ![";", "\\;", "+"].includes(rest[cursor])) {
				if (rest[cursor] !== "{}") return false;
				cursor++;
			}
		}
	}
	return sawRoot;
}

export function rmAskExempt(ctx: Ctx, cmd: string): boolean {
	return rmIsWorkspaceLocal(ctx, cmd) || rmTargetsScratchOnly(ctx, cmd);
}

/** `rm` がシステム全体・ホーム・親ディレクトリを対象にしていないか。 */
export function checkRmRootGuard(ctx: Ctx, cmd: string): string | null {
	const workspaceRootTokens = tableSet(ctx, "rm", "workspace_root_tokens");
	for (const a of argvsOf(ctx, cmd, isRm)) {
		if (a.includes("--no-preserve-root")) {
			return "`rm --no-preserve-root` は許可されていません。\nルートディレクトリの削除は承認の対象外です。";
		}
		for (const token of a.slice(1)) {
			if (token.startsWith("-")) continue;
			// workspace ルートの一括削除。`find . -delete` のような探索起点とは意味が違うので、rm 側でだけ判定する
			if (workspaceRootTokens.has(strip(token))) {
				return (
					`\`rm\` が作業ディレクトリ全体 (\`${token}\`) を対象にしています。\n` +
					"git 管理外のファイルまで失われるため承認の対象外です。\n" +
					"削除したい対象を具体的なパスで指定し直してください。"
				);
			}
			if (isCatastrophicRmTarget(ctx, token)) {
				return (
					`\`rm\` が壊滅的なパス \`${token}\` を対象にしています。\n` +
					"システム全体・ホーム・親ディレクトリの削除は承認の対象外です。\n" +
					"削除したい対象を具体的なパスで指定し直してください。"
				);
			}
		}
	}
	return null;
}
