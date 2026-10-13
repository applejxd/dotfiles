// ファイルの読み取り・持ち出し・書き込み先に関するルール (bashrules/rules_files.py の移植)。
//
// node の型除去でそのまま動く書き方だけを使う。
// see docs/spec/pi-decide.md#ts-版への移植
import type { Ctx } from "./context.ts";
import { tableList, tableSet } from "./context.ts";
import { pyRegex } from "./pystr.ts";
import { baseName, clip200, commands, normalizeCached, SENSITIVE_ENV_RE } from "./shared.ts";
import { sensitivePathInCommand } from "./sensitive.ts";
import type { Command } from "./shellparse.ts";
import { argv, parse } from "./shellparse.ts";

/** メッセージに出すためのコマンド (書かれたままの語を空白で結ぶ)。 */
const commandText = (command: Command): string => command.words.map((w) => w.raw).join(" ");

/** ファイル読み込み・複製コマンドがセンシティブパスを対象にしていないか。 */
export function checkFileRead(ctx: Ctx, cmd: string): string | null {
	const gitSubcommands = tableSet(ctx, "rules_files", "git_file_subcommands");
	const listing = tableSet(ctx, "rules_files", "listing_commands");
	const readCommands = new Set(tableList(ctx, "_shared", "file_read_commands"));
	for (const command of commands(ctx, cmd)) {
		const a = argv(command);
		if (a.length === 0) continue;
		const head = baseName(a[0]);
		if (head === "git" && a.length > 2 && gitSubcommands.has(a[1])) {
			// `git diff` を `diff` のコマンドとして判定する (サブコマンドを先頭に据える)
			const sub: Command = { words: command.words.slice(1), redirects: command.redirects };
			const matched = sensitivePathInCommand(ctx, sub);
			if (matched) return `\`git ${a[1]}\` がセンシティブなパスを対象にしています (パターン: ${matched})`;
			continue;
		}
		if (!readCommands.has(head)) continue;
		const matched = sensitivePathInCommand(ctx, command, !listing.has(head));
		if (matched) return `\`${head}\` がセンシティブなパスを対象にしています (パターン: ${matched})`;
	}
	return null;
}

/** 環境変数を露出するコマンドを検出 (全件出力・個別参照・絞り込み)。 */
export function checkEnvExposure(ctx: Ctx, cmd: string): string | null {
	const exposureBins = tableSet(ctx, "rules_files", "env_exposure_bins");
	const bareOnly = tableSet(ctx, "rules_files", "bare_only_dump_bins");
	for (const command of commands(ctx, cmd)) {
		const a = argv(command);
		if (a.length === 0) continue;
		const head = baseName(a[0]);
		if (!exposureBins.has(head)) continue;
		const text = commandText(command);
		const args = a.slice(1).filter((t) => !t.startsWith("-"));
		if (args.length === 0 && !(bareOnly.has(head) && a.length > 1)) {
			return (
				`環境変数を全件出力するコマンドは許可されていません: \`${text}\`\n` +
				"特定の変数を確認する場合は `echo $VAR_NAME` を使用してください。"
			);
		}
		if (args.some((x) => SENSITIVE_ENV_RE.test(x))) return `センシティブな環境変数を出力しようとしています: \`${text}\``;
	}
	// `env | grep -i key` のように絞り込む形
	if (pyRegex("\\b(?:env|printenv)\\b\\s*(?:\\||$)").test(cmd) && SENSITIVE_ENV_RE.test(cmd)) {
		return `環境変数からセンシティブな値を抽出しようとしています: \`${clip200(cmd)}\``;
	}
	return null;
}

/** アーカイブコマンドがセンシティブパスを含んでいないか */
export function checkArchive(ctx: Ctx, cmd: string): string | null {
	const archives = tableList(ctx, "rules_files", "archive_commands");
	for (const command of commands(ctx, cmd)) {
		const a = argv(command);
		if (a.length === 0) continue;
		const head = baseName(a[0]);
		if (!archives.includes(head)) continue;
		const matched = sensitivePathInCommand(ctx, command);
		if (matched) return `\`${head}\` でセンシティブなパスをアーカイブしようとしています (パターン: ${matched})`;
	}
	return null;
}

/** pip コマンドに対応する uv/uvx の代替案を返す */
function pipSuggestion(cmd: string): string {
	if (pyRegex("\\binstall\\b").test(cmd)) return "代替: `uv add <package>` または `uvx <package>`";
	if (pyRegex("\\buninstall\\b").test(cmd)) return "代替: `uv remove <package>`";
	if (pyRegex("\\blist\\b").test(cmd)) return "代替: `uv pip list`";
	if (pyRegex("\\bshow\\b").test(cmd)) return "代替: `uv pip show <package>`";
	if (pyRegex("\\bfreeze\\b").test(cmd)) return "代替: `uv pip freeze`";
	return "代替: `uv <subcommand>` または `uvx <tool>`";
}

const PIP_BIN_RE = pyRegex("^(?:/\\S*/)?pip[0-9.]*$");
const PYTHON_BIN_RE = pyRegex("^(?:/\\S*/)?python[0-9.]*$");
// -mpip のように -m と値がくっついた形
const PYTHON_DASH_M_RE = pyRegex("^-m([^\\n]+)$");

/** pip / python -m pip の直接使用を uv/uvx にリダイレクトする (ランナー経由・絶対パス・-mpip も含む)。 */
export function checkPipRedirect(ctx: Ctx, cmd: string): string | null {
	const runners = tableSet(ctx, "rules_files", "pip_runners");
	const runnerValueOpts = tableSet(ctx, "rules_files", "pip_runner_value_opts");
	const segs = normalizeCached(ctx, cmd);
	for (const command of segs.flatMap((segment) => parse(segment))) {
		const tokens = argv(command);
		if (tokens.length === 0) continue;
		const segment = tokens.join(" ");
		const head = baseName(tokens[0]);
		if (PIP_BIN_RE.test(head)) {
			return `pip の直接使用は禁止されています。uv / uvx を使用してください。\n${pipSuggestion(segment)}`;
		}
		if (runners.has(head) && tokens.length > 1) {
			// uvx pip install ... / pipx run pip ...。`--from pkg` のように値を取るオプションは、その値ごと読み飛ばす
			let i = 1;
			// `pipx run pkg` の run のように、実行対象の前に挟まるサブコマンド
			if (head === "pipx" && i < tokens.length && tokens[i] === "run") i += 1;
			while (i < tokens.length) {
				const token = tokens[i];
				if (token.startsWith("-")) {
					if (!token.includes("=") && runnerValueOpts.has(token)) i += 2;
					else i += 1;
					continue;
				}
				if (PIP_BIN_RE.test(baseName(token))) {
					return (
						`\`${head}\` 経由の pip 実行は禁止されています。uv / uvx を使用してください。\n${pipSuggestion(segment)}`
					);
				}
				break;
			}
		}
		if (PYTHON_BIN_RE.test(head)) {
			for (let i = 1; i < tokens.length; i++) {
				const token = tokens[i];
				// -m pip (値が別トークン)
				if (token === "-m" && i + 1 < tokens.length && PIP_BIN_RE.test(baseName(tokens[i + 1]))) {
					return `\`${head} -m pip\` は禁止されています。uv / uvx を使用してください。\n${pipSuggestion(segment)}`;
				}
				// -mpip (値がくっついた形)
				const m = PYTHON_DASH_M_RE.exec(token);
				if (m && PIP_BIN_RE.test(baseName(m[1]))) {
					return `\`${head} -m pip\` は禁止されています。uv / uvx を使用してください。\n${pipSuggestion(segment)}`;
				}
			}
		}
	}
	return null;
}
