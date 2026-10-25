// 任意コード実行に繋がる形の検出 (bashrules/rules_exec.py の移植)。
//
// `curl | sh` / `python -c` / `base64 -d | sh` / リバースシェルなど、
// 「取得したものや文字列をそのまま実行する」パターンを扱う。
//
// node の型除去でそのまま動く書き方だけを使う。
// see docs/spec/guard/pi-decide.md#ts-版への移植
import type { Ctx } from "./context.ts";
import { tableDict, tableList, tableSet } from "./context.ts";
import { extractCommandSubstitutions, splitCommandSegments } from "./normalize.ts";
import { basename, pyRegex, split, strip, stripChars } from "./pystr.ts";
import { argv, parse } from "./shellparse.ts";
import { clip200, cmdName, commands, FETCH_COMMAND_RE, SENSITIVE_ENV_RE, segments } from "./shared.ts";
import { fetchedOutputPaths } from "./http.ts";
import { isSensitivePath } from "./sensitive.ts";

// コード片から外部コマンドを起動する形
const INLINE_EXEC_RE = pyRegex(
	"(?:os\\.system|subprocess\\.|popen|execSync|spawnSync|child_process|" +
		"\\bsystem\\s*\\(|\\bexec\\s*\\(|\\bqx\\s*[({/]|`[^`]+`|\\bshell_exec\\b|\\bpassthru\\b)",
	"i",
);

// シェルの `$VAR` 展開を経由しない環境変数アクセス
const INLINE_ENV_READ_RE = pyRegex(
	"os\\.environ(?:\\.get)?\\s*[\\[(]\\s*['\"]([A-Za-z_][A-Za-z0-9_]*)['\"]" +
		"|process\\.env\\s*\\[\\s*['\"]([A-Za-z_][A-Za-z0-9_]*)['\"]" +
		"|process\\.env\\.([A-Za-z_][A-Za-z0-9_]*)" +
		"|\\$ENV\\{\\s*['\"]?([A-Za-z_][A-Za-z0-9_]*)['\"]?\\s*\\}" +
		"|ENVIRON\\s*\\[\\s*['\"]([A-Za-z_][A-Za-z0-9_]*)['\"]" +
		"|getenv\\s*\\(\\s*['\"]([A-Za-z_][A-Za-z0-9_]*)['\"]",
	"g",
);

// コマンド置換そのものをコマンドとして起動する形 (`$(curl ...)` 単体)
const SUBST_HEAD_RE = /^["']?(?:\$\(|`)/u;

// プロセス置換 `<(...)` / `>(...)`
const PROC_SUBST_RE = /[<>]\(([^()]*(?:\([^()]*\)[^()]*)*)\)/gu;

const reEscape = (s: string): string => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

/** find | xargs cat/grep のような組み合わせを検出 */
export function checkXargsPipe(ctx: Ctx, cmd: string): string | null {
	if (cmd.includes("xargs")) {
		for (const readCmd of tableList(ctx, "_shared", "file_read_commands")) {
			if (pyRegex(`\\bxargs\\b[^\\n]*\\b${reEscape(readCmd)}\\b`).test(cmd)) {
				const matched = isSensitivePath(ctx, cmd);
				if (matched) {
					return `xargs + \`${readCmd}\` でセンシティブなパスを読み込もうとしています (パターン: ${matched})`;
				}
			}
		}
	}
	return null;
}

/** `env` / `timeout 5` / `nohup` などのラッパーを剥がしたトークン列を返す。
 *
 * `keep` に挙げたラッパーは剥がさない。`xargs` は stdin の扱いそのものが判定材料なので、パイプ右辺では残す必要がある。
 */
export function stripExecWrappers(ctx: Ctx, tokens: readonly string[], keep: ReadonlySet<string> = new Set()): string[] {
	const wrapperValueOpts = tableDict(ctx, "rules_exec", "wrapper_value_opts");
	const numericWrappers = tableSet(ctx, "rules_exec", "wrapper_numeric_arg");
	let i = 0;
	while (i < tokens.length) {
		const name = cmdName(tokens[i]);
		if (!wrapperValueOpts.has(name) || keep.has(name)) break;
		const valueOpts = wrapperValueOpts.get(name) as string[];
		const numeric = numericWrappers.has(name);
		i += 1;
		while (i < tokens.length) {
			const token = tokens[i];
			// `env -S "bash -s"` の値はコマンドラインそのもの。読み飛ばすと実行対象を見失うので、展開して解析を続ける
			let splitString: string | null = null;
			let rest: string[] = [];
			if ((token === "-S" || token === "--split-string") && i + 1 < tokens.length) {
				splitString = tokens[i + 1];
				rest = tokens.slice(i + 2);
			} else if (token.startsWith("--split-string=")) {
				splitString = token.slice(token.indexOf("=") + 1);
				rest = tokens.slice(i + 1);
			} else if (token.startsWith("-S") && Array.from(token).length > 2) {
				splitString = Array.from(token).slice(2).join("");
				rest = tokens.slice(i + 1);
			}
			if (splitString !== null) {
				return stripExecWrappers(ctx, [...split(stripChars(splitString, "'\"")), ...rest], keep);
			}
			if (/^[A-Za-z_][A-Za-z0-9_]*=/u.test(token)) {
				i += 1;
				continue;
			}
			if (valueOpts.includes(token)) {
				i += 2;
				continue;
			}
			if (token.startsWith("-") && token !== "-") {
				i += 1;
				continue;
			}
			if (numeric && pyRegex("^\\d+(?:\\.\\d+)?[smhd]?(?![^])").test(token)) {
				i += 1;
				continue;
			}
			break;
		}
	}
	return tokens.slice(i);
}

/** パイプ右辺などから、実際に起動されるコマンドのトークン列を得る。 */
function executableHeadTokens(ctx: Ctx, part: string): string[] {
	const tokens = split(strip(part)).map((t) => stripChars(stripChars(t, "'\""), "(){}"));
	return stripExecWrappers(
		ctx,
		tokens.filter((t) => t),
		new Set(["xargs"]),
	);
}

/** このコマンドが標準入力をコードとして解釈するか。 */
function readsStdinAsCode(ctx: Ctx, tokens: readonly string[]): boolean {
	if (tokens.length === 0) return false;
	const shells = tableSet(ctx, "_shared", "stdin_code_shells");
	const interpreters = tableSet(ctx, "_shared", "stdin_code_interpreters");
	const head = cmdName(tokens[0]);
	if (head === "sudo") return readsStdinAsCode(ctx, tokens.slice(1));
	if (head === "xargs") {
		// `curl ... | xargs -0 sh -c` のように、流れてきた内容がそのままコマンド文字列になる形を対象にする。
		// `find . | xargs node script.js` はスクリプトを渡しているので対象外
		const rest = tokens.slice(1);
		// `-I{}` は stdin の内容を後続の引数へ埋め込むので、引数の有無を問わずコードとして扱う
		const replaces = rest.some((t) => t.startsWith("-I") || t.startsWith("-i") || t.startsWith("--replace"));
		for (let i = 0; i < rest.length; i++) {
			const name = cmdName(rest[i]);
			if (shells.has(name) || interpreters.has(name)) {
				if (replaces) return true;
				return !rest.slice(i + 1).some((a) => !a.startsWith("-"));
			}
		}
		return false;
	}
	const isShell = shells.has(head);
	if (!isShell && !interpreters.has(head)) return false;
	const args = tokens.slice(1);
	// `bash -s` は引数があっても stdin をコードとして読む
	if (isShell && args.includes("-s")) return true;
	const codeFlags = tableSet(ctx, "_shared", isShell ? "shell_code_arg_flags" : "interpreter_code_arg_flags");
	// `-c CODE` / `-m module` はそれ自体がコード。併記される `-` は入力データを指すのでコードではない
	if (args.some((a) => codeFlags.has(a))) return false;
	const stdinFlags = tableSet(ctx, "rules_exec", "stdin_code_flags");
	if (args.some((a) => stdinFlags.has(a))) return true;
	// スクリプトファイルを渡していれば stdin はデータ
	return !args.some((a) => !a.startsWith("-"));
}

/** 取得した内容をそのままコードとして実行していないか (パイプ・コマンド置換・プロセス置換・保存してから実行)。 */
export function checkPipeToShell(ctx: Ctx, cmd: string): string | null {
	const blocked = (detail: string): string =>
		`取得した内容をそのままコードとして実行しようとしています (${detail})。\n` +
		`実行しようとしているコマンド: ${clip200(cmd)}\n` +
		"内容を検証できないため許可されていません。\n" +
		"一度ファイルに保存して内容を確認してから実行してください。";
	const shells = tableSet(ctx, "_shared", "stdin_code_shells");
	const interpreters = tableSet(ctx, "_shared", "stdin_code_interpreters");

	// パイプの右辺が stdin をコードとして読む形。引用を無視して文字列全体を `|` で切るのは意図的 (引用の中のパイプも拾う安全側)
	let joined = cmd.replace(pyRegex("\\\\\\s*\\n", "g"), " ");
	joined = joined.replace(pyRegex("\\|\\s*\\n\\s*", "g"), "| ");
	for (const chunk of joined.split(/[\n;]+/)) {
		const parts = chunk.split("|");
		for (const part of parts.slice(1)) {
			if (readsStdinAsCode(ctx, executableHeadTokens(ctx, part))) return blocked("パイプ");
		}
	}

	// コマンド置換・プロセス置換で取得したものを実行系に渡す形。
	// 引用付き heredoc の本文はシェルが展開しないため置換ではない。splitHeredocBody が組み立てた行と一致する
	// セグメントだけを、記録した回数まで見送る
	const pending = ctx.literalHeredocBodies.map((literal) => `python3 -c ${literal}`);
	for (const segment of splitCommandSegments(cmd)) {
		const at = pending.indexOf(strip(segment));
		if (at !== -1) {
			pending.splice(at, 1);
			continue;
		}
		const bodies = [...extractCommandSubstitutions(segment)];
		for (const m of segment.matchAll(PROC_SUBST_RE)) bodies.push(m[1]);
		if (!bodies.some((body) => FETCH_COMMAND_RE.test(body))) continue;
		for (const command of parse(segment)) {
			const tokens = argv(command);
			if (tokens.length === 0) continue;
			if (SUBST_HEAD_RE.test(tokens[0])) return blocked("コマンド置換・プロセス置換");
			// `env bash -c ...` / `timeout 5 sh -c ...` のようにラッパーで前置されても head を見失わないようにする
			const stripped = stripExecWrappers(ctx, tokens);
			if (stripped.length === 0) continue;
			const head = cmdName(stripped[0]);
			if (shells.has(head) || interpreters.has(head)) return blocked("コマンド置換・プロセス置換");
		}
	}

	// 取得先へ保存したファイルを、同じコマンドの中で実行する形
	const saved = fetchedOutputPaths(ctx, cmd);
	if (saved.size > 0) {
		const isSaved = (token: string): boolean => Boolean(token) && (saved.has(token) || saved.has(basename(token)));
		for (const command of commands(ctx, cmd)) {
			const tokens = stripExecWrappers(ctx, argv(command));
			if (tokens.length === 0) continue;
			// `./install.sh` のように保存したファイルを直接起動する形
			if (isSaved(tokens[0])) return blocked("保存したファイルの実行");
			const head = cmdName(tokens[0]);
			if (!shells.has(head) && !interpreters.has(head)) continue;
			// 最初の非オプション引数が実行されるスクリプト。`python3 process.py data.csv` の data.csv では反応しない
			for (const token of tokens.slice(1)) {
				if (token.startsWith("-")) continue;
				if (isSaved(token)) return blocked("保存したファイルの実行");
				break;
			}
		}
	}
	return null;
}

/** インラインコードを実行するインタプリタ名を返す (無ければ null)。先頭に限らず探す (`uv run python -c ...` のため)。 */
export function inlineCodeHead(ctx: Ctx, segment: string): string | null {
	const bins = tableSet(ctx, "rules_exec", "inline_code_bins");
	const awkBins = tableSet(ctx, "rules_exec", "awk_bins");
	const flags = tableSet(ctx, "rules_exec", "inline_code_flags");
	for (const command of parse(segment)) {
		const tokens = argv(command);
		for (let i = 0; i < tokens.length; i++) {
			const candidate = cmdName(tokens[i]);
			if (!bins.has(candidate)) continue;
			const rest = tokens.slice(i + 1);
			if (rest.some((t) => flags.has(t))) return candidate;
			// awk 系はプログラムを位置引数で受け取る (`-f` はファイル指定)
			if (
				awkBins.has(candidate) &&
				!rest.some((t) => t === "-f" || t.startsWith("-f") || t.startsWith("--file")) &&
				rest.some((t) => !t.startsWith("-"))
			) {
				return candidate;
			}
			break;
		}
	}
	return null;
}

/** `python3 -c "..."` / `perl -e "..."` の中でセンシティブな操作をしていないか。 */
export function checkInterpreterInlineCode(ctx: Ctx, cmd: string): string | null {
	for (const segment of segments(ctx, cmd)) {
		const head = inlineCodeHead(ctx, segment);
		if (head === null) continue;
		// コード片にセンシティブなパスや外部実行が含まれていないか
		const reason = isSensitivePath(ctx, segment);
		if (reason) return `\`${head}\` のインラインコードがセンシティブなパスを参照しています (${reason})。`;
		if (INLINE_EXEC_RE.test(segment)) {
			return (
				`\`${head}\` のインラインコードから外部コマンドを実行しようとしています。\n` +
				`実行しようとしているコマンド: ${clip200(segment)}\n` +
				"スクリプトファイルに書いて内容を確認できる形にしてください。"
			);
		}
		// `os.environ['GITHUB_TOKEN']` のように、シェルの `$VAR` 展開を経由しない環境変数アクセス
		for (const m of segment.matchAll(INLINE_ENV_READ_RE)) {
			const name = m.slice(1).find((g) => g);
			if (name && SENSITIVE_ENV_RE.test(name)) {
				return `\`${head}\` のインラインコードがセンシティブな環境変数 \`${name}\` を読み出そうとしています。`;
			}
		}
	}
	return null;
}

/** リバースシェル・待ち受けソケットの形を検出する。 */
export function checkReverseShell(ctx: Ctx, cmd: string): string | null {
	const m = pyRegex("/dev/(?:tcp|udp)/[^/\\s]+/\\d+").exec(cmd);
	if (m) {
		return (
			`\`${m[0]}\` へのシェルリダイレクトはリバースシェルの形です。\n` +
			"外部への接続を伴うシェル実行は許可されていません。"
		);
	}
	const listeners = new Set(["nc", "netcat", "ncat", "socat", "telnet"]);
	const execFlags = ["-e", "-c", "--exec", "--sh-exec", "--lua-exec"];
	const listenFlags = ["-l", "-lp", "-lvp", "--listen", "-L"];
	for (const command of commands(ctx, cmd)) {
		const tokens = argv(command);
		if (tokens.length === 0) continue;
		const head = basename(tokens[0]);
		if (!listeners.has(head)) continue;
		for (const token of tokens.slice(1)) {
			if (execFlags.includes(token) || token.startsWith("EXEC:")) {
				return (
					`\`${head} ${token}\` はコマンドを外部接続に紐付ける形です。\n` +
					"リバースシェルに繋がるため許可されていません。"
				);
			}
			if (listenFlags.includes(token)) {
				return (
					`\`${head} ${token}\` は待ち受けソケットを開く形です。\n` +
					"外部からの侵入経路になるため許可されていません。"
				);
			}
		}
	}
	return null;
}

const DECODERS = "(?:base64\\s+(?:-d|--decode|-D)|xxd\\s+-r|uudecode|openssl\\s+enc\\s+-d)";
const SHELLS = "(?:ba|z|k|da)?sh\\b|python3?\\b|perl\\b|ruby\\b|node\\b";
const DECODE_TO_SHELL_RE = pyRegex(`${DECODERS}[^|]*\\|\\s*(?:${SHELLS})`);
const ESCAPE_TO_SHELL_RE = pyRegex(
	`printf\\s+['"][^'"]*\\\\x[0-9a-fA-F]{2}[^'"]*['"]\\s*\\|\\s*(?:${SHELLS})`,
);

/** デコード結果をそのままシェルへ流す形を検出する (`base64 -d | sh` など)。 */
export function checkEncodedCommand(_ctx: Ctx, cmd: string): string | null {
	if (DECODE_TO_SHELL_RE.test(cmd)) {
		return (
			"デコード結果を直接シェルに渡そうとしています。\n" +
			"内容を検査できないため許可されていません。" +
			"デコード結果をファイルに書き出して確認してから実行してください。"
		);
	}
	if (ESCAPE_TO_SHELL_RE.test(cmd)) {
		return (
			"エスケープ列で組み立てたコマンドをシェルに渡そうとしています。\n" +
			"内容を検査できないため許可されていません。"
		);
	}
	return null;
}
