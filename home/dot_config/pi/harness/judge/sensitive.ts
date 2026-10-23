// 秘密情報 (鍵・トークン・認証ファイル) の検出 (bashrules/sensitive.py の移植)。
//
// 守る対象のファイル名・ディレクトリ・環境変数名は tables.toml (tables.json) にある。
//
// node の型除去でそのまま動く書き方だけを使う。
// see docs/spec/pi-decide.md#ts-版への移植
import type { Ctx } from "./context.ts";
import { tableList, tableSet } from "./context.ts";
import { basename as osBasename, isSpace, pyRegex, split, stripChars } from "./pystr.ts";
import {
	baseName,
	clip200,
	cmdName,
	commands,
	looksLikePath,
	normalizeGuardPath,
	segments,
	SENSITIVE_ENV_RE,
} from "./shared.ts";
import type { Command, Word } from "./shellparse.ts";
import { argv as argvOf, expandable, parse, redirectWrites } from "./shellparse.ts";

// basename に含まれると秘密とみなす語 (パスらしいトークンにのみ適用)
const SENSITIVE_WORD_RE = pyRegex(
	"(?:secret|password|passwd|credential|api[_-]?key|private[_-]?key|access[_-]?key)",
	"i",
);
// 明示的に除外する (サンプル・テンプレート)
const SENSITIVE_EXEMPT_RE = pyRegex("(?:\\.example$|\\.sample$|\\.template$|\\.tmpl$|\\.md$|\\.rst$|\\.txt\\.example$)", "i");
// プロセスの環境変数を覗くパス
const PROC_ENVIRON_RE = pyRegex("/proc/(?:\\d+|self)/environ");

const endsWithAny = (s: string, suffixes: readonly string[]): boolean => suffixes.some((x) => s.endsWith(x));
const startsWithAny = (s: string, prefixes: readonly string[]): boolean => prefixes.some((x) => s.startsWith(x));

/** パスらしいトークンがセンシティブなら、その理由を返す。`heuristic=false` なら語彙による曖昧な判定をしない。 */
export function isSensitiveToken(ctx: Ctx, token: string, heuristic = true): string | null {
	const cleaned = stripChars(token, "'\"");
	if (!cleaned) return null;

	const normalized = normalizeGuardPath(cleaned);
	const base = osBasename(normalized);

	if (SENSITIVE_EXEMPT_RE.test(base)) return null;
	// `.env.example` のようにサンプルであることが接尾辞で分かるもの
	if (base.startsWith(".env.") && base !== ".env.local") return null;
	// credentials のような既知の basename は slash や拡張子がなくても、ファイル名そのものが秘密を意味する
	if (
		tableSet(ctx, "sensitive", "sensitive_basenames").has(base) ||
		startsWithAny(base, tableList(ctx, "sensitive", "sensitive_basename_prefixes"))
	) {
		return base;
	}
	if (tableSet(ctx, "sensitive", "history_basenames").has(base)) return `シェル履歴 (${base})`;
	if (!looksLikePath(ctx, cleaned)) return null;

	if (tableSet(ctx, "sensitive", "sensitive_abs_paths").has(normalized)) return normalized;
	if (PROC_ENVIRON_RE.test(normalized)) return "プロセスの環境変数";
	for (const cred of tableList(ctx, "sensitive", "credential_paths")) {
		if (normalized.endsWith(cred)) return base;
	}
	const parts = normalized.split("/");
	for (const d of tableList(ctx, "sensitive", "sensitive_dirs")) {
		if (parts.includes(d) || (d.split("/").length - 1 > 0 && normalized.includes(d))) return `${d} 配下`;
	}
	if (heuristic) {
		for (const d of tableList(ctx, "sensitive", "heuristic_sensitive_dirs")) {
			if (parts.includes(d)) return `${d} 配下`;
		}
	}
	const lower = base.toLowerCase();
	if (endsWithAny(lower, tableList(ctx, "_shared", "sensitive_suffixes"))) return base;
	if (
		heuristic &&
		SENSITIVE_WORD_RE.test(base) &&
		!endsWithAny(lower, tableList(ctx, "sensitive", "source_code_suffixes"))
	) {
		return base;
	}
	return null;
}

/** コマンド文字列にセンシティブなパス引数が含まれていれば理由を返す。 */
export function isSensitivePath(ctx: Ctx, text: string, heuristic = true): string | null {
	for (const command of parse(text)) {
		const reason = sensitivePathInCommand(ctx, command, heuristic);
		if (reason) return reason;
	}
	return null;
}

/** 引数中の http(s) URL はローカルのパスではない (sensitive.py の `_URL_RE` と同じ)。直前が `/` `.` `~` や語の文字のものや `file://` は除かない。 */
const URL_RE = pyRegex(`(?<![\\w/.~-])https?://(?:\\[[0-9a-f:.]*\\])?[^\\s'"\`)>,\\[\\]]*`, "ig");

/** 空白を含む引数 (`python3 -c "..."` のコード) は断片も見る。 */
const pieces = (value: string): string[] => (Array.from(value).some((c) => isSpace(c)) ? split(value) : [value]);

/** 解析済みの単純コマンドの引数とリダイレクトの対象に、センシティブなパスがあれば理由を返す。 */
export function sensitivePathInCommand(ctx: Ctx, command: Command, heuristic = true): string | null {
	const argv = argvOf(command);
	let candidates: string[] = [];
	if (argv.length > 0) candidates = pathArguments(ctx, baseName(argv[0]), argv.slice(1));
	// リダイレクトの対象 (`cat < .env`)。ヒアドキュメントの区切り語は対象ではない
	for (const r of command.redirects) {
		if (r.target !== null && r.op !== "<<" && r.op !== "<<-") candidates.push(r.target.value);
	}
	for (const candidate of candidates) {
		for (const piece of pieces(candidate.replace(URL_RE, " "))) {
			const reason = isSensitiveToken(ctx, piece, heuristic);
			if (reason) return reason;
		}
	}
	return null;
}

/** パスとして扱う引数 (フラグ・検索語・コピー先を除いたもの)。 */
function pathArguments(ctx: Ctx, head: string, args0: string[]): string[] {
	let args = args0;
	if (tableSet(ctx, "sensitive", "dest_last_commands").has(head) && args.length >= 2) {
		args = args.slice(0, -1); // 末尾は書き込み先。読み取り元だけを見る
	}
	const out: string[] = [];
	let skipPatternArg = tableSet(ctx, "sensitive", "pattern_first_commands").has(head);
	let skipNext = false;
	for (const token of args) {
		if (skipNext) {
			skipNext = false; // -e / -f の値 (検索語・スクリプト・検索語のファイル)
			continue;
		}
		if (token.startsWith("-")) {
			if (skipPatternArg) {
				const [given, separate] = patternOption(head, token);
				if (given) {
					skipPatternArg = false; // 検索語をオプションで渡すと、非フラグ引数はすべてパスになる
					skipNext = separate;
				}
			}
			continue;
		}
		if (skipPatternArg) {
			skipPatternArg = false; // 最初の非フラグ引数は検索語なので飛ばす
			continue;
		}
		out.push(token);
	}
	return out;
}

// 検索語 (スクリプト) をオプションで渡すときの短い文字・長いオプションと、短いオプションの束で
// 後ろを値として取る文字 (-A3 / -m1 / awk の -F: など。ここで束の解釈をやめる)。
// 意味がコマンドで違うので、コマンドごとに持つ
type PatternOptions = [shorts: string, longs: readonly string[], valued: string];
const GREP: PatternOptions = ["ef", ["--regexp", "--file"], "ABCDdm"];
const AWK: PatternOptions = ["f", ["--file"], "Fv"];
const PATTERN_OPTIONS = new Map<string, PatternOptions>([
	["grep", GREP],
	["egrep", GREP],
	["fgrep", GREP],
	["rg", ["ef", ["--regexp", "--file"], "ABCMmgtTdj"]],
	["sed", ["ef", ["--expression", "--file"], "l"]],
	["awk", AWK],
	["mawk", AWK],
	["gawk", ["ef", ["--file", "--source"], "Fv"]],
	["ack", ["g", [], "ABCm"]],
	["ag", ["g", [], "ABCGm"]],
]);
// 検索語を取らなくなるオプション (値なし)
const NO_PATTERN_FLAGS = new Map<string, readonly string[]>([
	["rg", ["--files"]],
	["ack", ["-f"]],
]);

/** 検索語 (スクリプト) をオプションで渡しているか、値が次のトークンか。 */
function patternOption(head: string, token: string): [boolean, boolean] {
	if ((NO_PATTERN_FLAGS.get(head) ?? []).includes(token)) return [true, false];
	const [shorts, longs, valued] = PATTERN_OPTIONS.get(head) ?? ["", [], ""];
	if (longs.includes(token)) return [true, true];
	if (longs.some((opt) => token.startsWith(`${opt}=`))) return [true, false];
	if (token.startsWith("--") || token === "-") return [false, false];
	const chars = Array.from(token);
	for (let i = 1; i < chars.length; i++) {
		const ch = chars[i];
		if (shorts.includes(ch)) return [true, i === chars.length - 1];
		if (/^\p{Nd}$/u.test(ch) || valued.includes(ch)) break;
	}
	return [false, false];
}

/** `git add .env` のようにセンシティブファイルをバージョン管理に載せていないか */
export function checkGitAddSensitive(ctx: Ctx, cmd: string): string | null {
	for (const command of commands(ctx, cmd)) {
		const argv = argvOf(command);
		if (argv.length < 3) continue;
		if (baseName(argv[0]) !== "git" || (argv[1] !== "add" && argv[1] !== "stage")) continue;
		for (const token of argv.slice(2)) {
			if (token.startsWith("-")) continue;
			const reason = isSensitiveToken(ctx, token);
			if (reason) {
				return (
					`センシティブなファイルを git に追加しようとしています (${reason})。\n` +
					"秘密情報はコミットせず、.gitignore に追加してください。"
				);
			}
		}
	}
	return null;
}

const envRefRe = () => pyRegex("(?<!\\\\)\\$\\{?([A-Za-z_][A-Za-z0-9_]*)\\}?", "g");

/** `text` が参照するセンシティブな環境変数の名前。`\$X` (エスケープ) は除く。 */
function secretNames(text: string): string[] {
	const out: string[] = [];
	for (const m of text.matchAll(envRefRe())) {
		if (SENSITIVE_ENV_RE.test(m[1])) out.push(m[1]);
	}
	return out;
}

/** 単純コマンドの引数と、読み込み側のリダイレクト (`<<< "$TOKEN"`) が参照する名前。 */
function commandSecretNames(command: Command, honourQuotes: boolean): string[] {
	const words: Word[] = [...command.words];
	for (const r of command.redirects) {
		if (r.target !== null && !redirectWrites(r)) words.push(r.target);
	}
	return words.flatMap((word) => secretNames(honourQuotes ? expandable(word) : word.raw));
}

/** センシティブな環境変数の値を出力先へ流していないか。 */
export function checkSecretEnvEcho(ctx: Ctx, cmd: string): string | null {
	const shells = tableSet(ctx, "_shared", "stdin_code_shells");
	const interpreters = tableSet(ctx, "_shared", "stdin_code_interpreters");
	const shellFlags = tableSet(ctx, "_shared", "shell_code_arg_flags");
	const interpFlags = tableSet(ctx, "_shared", "interpreter_code_arg_flags");
	const sinks = tableSet(ctx, "sensitive", "secret_sink_commands");
	const egress = tableSet(ctx, "sensitive", "secret_egress_commands");

	/** `sh -c CODE` / `python -c CODE` のコード引数を返す。 */
	const codeArgument = (argv: string[]): string | null => {
		const name = cmdName(argv[0]);
		if (!shells.has(name) && !interpreters.has(name)) return null;
		for (let i = 1; i < argv.length; i++) {
			if ((shellFlags.has(argv[i]) || interpFlags.has(argv[i])) && i + 1 < argv.length) return argv[i + 1];
		}
		return null;
	};

	const scan = (text: string, honourQuotes: boolean, depth = 0): string | null => {
		for (const segment of segments(ctx, text)) {
			for (const command of parse(segment)) {
				const argv = argvOf(command);
				if (argv.length === 0) continue;
				const names = commandSecretNames(command, honourQuotes);
				if (names.length === 0) continue;
				const head = baseName(argv[0]);
				if (sinks.has(head)) {
					return (
						`センシティブな環境変数 \`$${names[0]}\` を出力しようとしています。\n` +
						`実行しようとしているコマンド: ${clip200(cmd)}\n` +
						"値を画面やファイルに出さない形で扱ってください。"
					);
				}
				if (egress.has(head)) {
					return (
						`センシティブな環境変数 \`$${names[0]}\` を外部へ送信しようとしています。\n` +
						`実行しようとしているコマンド: ${clip200(cmd)}\n` +
						"値を外部に出さない形で扱ってください。"
					);
				}
				// `sh -c '...'` はコード引数を展開して同じ判定を続ける
				if (depth < 2) {
					const inner = codeArgument(argv);
					if (inner) {
						const hit = scan(inner, false, depth + 1);
						if (hit) return hit;
					}
				}
			}
		}
		return null;
	};

	if (secretNames(cmd).length === 0) return null;
	const hit = scan(cmd, true);
	if (hit) return hit;
	// リダイレクトでファイルへ書き出す形 (`printf %s "$TOKEN" > f` など)
	for (const command of commands(ctx, cmd)) {
		if (!command.redirects.some((r) => redirectWrites(r))) continue;
		const names = commandSecretNames(command, true);
		if (names.length > 0) {
			return (
				`センシティブな環境変数 \`$${names[0]}\` をファイルへ書き出そうとしています。\n` +
				`実行しようとしているコマンド: ${clip200(cmd)}`
			);
		}
	}
	return null;
}

/** `history` でシェル履歴を読み出していないか (過去の秘密が残っている)。 */
export function checkHistoryAccess(ctx: Ctx, cmd: string): string | null {
	for (const command of commands(ctx, cmd)) {
		const argv = argvOf(command);
		if (argv.length > 0 && (baseName(argv[0]) === "history" || baseName(argv[0]) === "fc")) {
			return "シェル履歴には過去に入力した秘密が残っている可能性があるため、参照は許可されていません。";
		}
	}
	return null;
}
