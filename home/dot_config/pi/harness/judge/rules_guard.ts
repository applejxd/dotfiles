// 防御機構そのものと、環境への永続的な変更の保護 (bashrules/rules_guard.py の移植)。
//
// hook や settings.json の改変、シェル起動ファイルへの追記、権限昇格、
// グローバルな環境変数の書き換えなどを扱う。
//
// node の型除去でそのまま動く書き方だけを使う。
// see docs/spec/pi-decide.md#ts-版への移植
import type { Ctx } from "./context.ts";
import { tableSet } from "./context.ts";
import { expandUser, isAbsolute, join, normpath, sep } from "./pathutil.ts";
import { basename, pyRegex, shlexSplit, ShlexError, split, stripChars } from "./pystr.ts";
import { argv } from "./shellparse.ts";
import { inlineCodeHead } from "./rules_exec.ts";
import {
	baseName,
	clip200,
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
	"/.git/config",
	"/.git/hooks",
	".git/config",
	".git/hooks",
];

const guardHits = (token: string): boolean => {
	const expanded = normalizeGuardPath(token);
	return GUARD_TARGETS.some((t) => expanded.includes(t));
};

const INLINE_PATH_RE = pyRegex(`['"]([^'"]*(?:\\.claude|\\.copilot|/agents|\\.git/)[^'"]*)['"]`, "g");
const HOOK_ENV_RE = pyRegex("\\b(AGENTS_CONFIG_DIR|PYTHONPATH|CLAUDE_[A-Z_]*HOOK[A-Z_]*)=(\\S*)", "g");

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
