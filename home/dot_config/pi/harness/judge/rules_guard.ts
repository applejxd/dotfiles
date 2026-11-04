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
import { argv } from "./shellparse.ts";
import { splitCommandSegments } from "./normalize.ts";
import { inlineCodeHead } from "./rules_exec.ts";
import { ledgerRoots, underLedgerRoot } from "./ledger_root.ts";
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
