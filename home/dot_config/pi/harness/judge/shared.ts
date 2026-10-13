// 共通ユーティリティ (bashrules/_shared.py の移植)。各検査から使う汎用処理だけを置く。
//
// Python 版のグローバル変数 (`_PAYLOAD_CWD` `_LITERAL_HEREDOC_BODIES`) は、呼び出しごとの文脈 `Ctx` に置く。
// 表 (tables.toml) は `ctx.tables` から引く。
//
// node の型除去でそのまま動く書き方だけを使う。
// see docs/spec/pi-decide.md#ts-版への移植
import type { Ctx } from "./context.ts";
import { memo, tableList, tableSet } from "./context.ts";
import { normalize } from "./normalize.ts";
import { expandUser, isAbsolute, join, normcase, normpath, realpathLoose, sep } from "./pathutil.ts";
import { basename, pyRegex, split, strip, stripChars } from "./pystr.ts";
import type { Command } from "./shellparse.ts";
import { argv, parse, redirectWrites } from "./shellparse.ts";

// ─── 正規化と分割 (同じ判定の中で使い回す) ───────────────────────────────

export const normalizeCached = (ctx: Ctx, command: string): readonly string[] =>
	memo(ctx, `normalize:${command}`, () => normalize(command));

/** normalize 済みセグメント + 元の文字列。パターン照合では元の文字列も併せて見て取りこぼさない。 */
export const segments = (ctx: Ctx, cmd: string): readonly string[] =>
	memo(ctx, `segments:${cmd}`, () => [...normalizeCached(ctx, cmd), cmd]);

/** 正規化済みのセグメントと元の文字列を、単純コマンドへ分けたもの。 */
export const commands = (ctx: Ctx, cmd: string): Command[] =>
	segments(ctx, cmd).flatMap((segment) => parse(segment));

// ─── パス判定のヘルパ ───────────────────────────────────────────────────

/** `cmd.strip()[:200]` (理由の文面に入れるコマンドの先頭。コードポイントで数える)。 */
export const clip200 = (cmd: string): string => Array.from(strip(cmd)).slice(0, 200).join("");

/** `/bin/rm` -> `rm` */
export const baseName = (token: string): string => basename(token);

export function looksLikePath(ctx: Ctx, token: string): boolean {
	if (token.includes("/") || token.includes(sep) || token.startsWith("~")) return true;
	if (token.startsWith(".") && token.length > 1) return true;
	const suffixes = tableList(ctx, "_shared", "sensitive_suffixes");
	return suffixes.some((s) => token.toLowerCase().endsWith(s));
}

/** ネイティブのパスの意味は保ち、ガードのパターンは `/` 区切りにそろえる。 */
export function normalizeGuardPath(token: string): string {
	const expanded = stripChars(token, "'\"").replace("~", expandUser("~"));
	return normcase(normpath(expanded)).replaceAll(sep, "/");
}

// 環境変数名としてセンシティブなもの。PAT / KEY / AUTH は単語として現れるときだけ拾う ($PATH や $MONKEY に当てない)。
export const SENSITIVE_ENV_RE = pyRegex(
	"(?:SECRET|TOKEN|PASSWORD|PASSWD|PASSPHRASE|CREDENTIAL|SESSION" +
		"|API[_-]?KEY|PRIV(?:ATE)?[_-]?KEY|ACCESS[_-]?KEY" +
		"|(?:^|[_-])(?:PAT|KEY|AUTH)S?(?:[_-]|$))",
	"i",
);

// ─── 書き込み先の抽出 ───────────────────────────────────────────────────

/** リダイレクトで書き込む先 (`> f` / `>> f` / `&> f` / `>& f` など)。 */
export function redirectWriteTargets(ctx: Ctx, cmd: string): string[] {
	const out: string[] = [];
	for (const command of commands(ctx, cmd)) {
		for (const r of command.redirects) {
			if (redirectWrites(r) && r.target !== null) out.push(r.target.value);
		}
	}
	return out;
}

/** コマンドが書き込み・変更しようとしているトークンを返す。 */
export function writeTargets(ctx: Ctx, cmd: string): string[] {
	const targets = redirectWriteTargets(ctx, cmd);
	const destLast = tableSet(ctx, "_shared", "write_dest_last_commands");
	const allArgs = tableSet(ctx, "_shared", "write_all_args_commands");
	for (const command of commands(ctx, cmd)) {
		const args0 = argv(command);
		if (args0.length === 0) continue;
		const head = baseName(args0[0]);
		for (const token of args0.slice(1)) {
			if (token.startsWith("of=")) targets.push(token.slice(3));
		}
		const args = args0.slice(1).filter((t) => !t.startsWith("-"));
		if (args.length === 0) continue;
		if (head === "sed") {
			// in-place 指定が無ければ読み取りのみ
			if (args0.slice(1).some((t) => t.startsWith("-i"))) targets.push(...args);
		} else if (destLast.has(head)) {
			targets.push(args[args.length - 1]);
		} else if (allArgs.has(head)) {
			targets.push(...args);
		}
	}
	return targets;
}

/** 添付された値・別トークンの値のどちらでも、オプションの値と次の位置を返す。 */
export function takeOptionValue(
	args: readonly string[],
	index: number,
	token: string,
	short: string | null,
	long: string,
): [string | null, number] {
	if (token.startsWith(`${long}=`)) return [token.slice(long.length + 1), index + 1];
	if (short && token.startsWith(short) && token !== short) return [token.slice(short.length), index + 1];
	if (token === long || (short && token === short)) {
		if (index + 1 >= args.length) return [null, index + 1];
		return [args[index + 1], index + 2];
	}
	return [null, index];
}

/** curl / wget のペイロード指定が参照するローカルファイル。 */
export function payloadSource(ctx: Ctx, kind: string, value: string): string | null {
	const upload = tableSet(ctx, "_shared", "curl_upload_flags");
	const form = tableSet(ctx, "_shared", "curl_form_flags");
	if (upload.has(kind) || kind === "--post-file" || kind === "--body-file") return value;
	if (form.has(kind)) {
		const parts = value.split("=");
		const candidate = parts[parts.length - 1];
		if (candidate.startsWith("@") || candidate.startsWith("<")) return candidate.slice(1).split(";")[0];
		return null;
	}
	if (value.startsWith("@")) return value.slice(1);
	if (kind === "--data-urlencode" && value.includes("@")) return value.slice(value.indexOf("@") + 1);
	return null;
}

/** 添付されたオプションの値。一致しなければ null。 */
export function optionValue(token: string, short: string, long: string): string | null {
	if (token.startsWith(`${long}=`)) return token.slice(long.length + 1);
	if (token.startsWith(short) && token !== short) return token.slice(short.length);
	return null;
}

// ─── コマンド名 ─────────────────────────────────────────────────────────

/** トークンからコマンド名を取り出す (`python3` -> `python`)。`.` は 1 文字なので接尾辞の除去をしない。 */
export function cmdName(token: string): string {
	let name = baseName(stripChars(token, "'\""));
	if (Array.from(name).length > 1) name = name.replace(/[0-9.]+$/, "");
	return name;
}

export const FETCH_COMMAND_RE = pyRegex("\\b(?:curl|wget)\\b");

// ─── heredoc ───────────────────────────────────────────────────────────

const HEREDOC_SRC = "<<-?\\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\\1";

/**
 * heredoc 本文のうち実行されない部分を取り除いた検査対象を返す。
 * インタプリタに渡る本文は `-c` 形式に組み替える。引用付きの本文は ctx.literalHeredocBodies に記録する
 * (この判定の中だけ。Python 版のようにプロセスに積み残さない)。
 */
export function splitHeredocBody(ctx: Ctx, cmd: string): string {
	const shellBins = tableSet(ctx, "_shared", "heredoc_shell_bins");
	const codeBins = tableSet(ctx, "_shared", "heredoc_code_bins");
	const lines = cmd.split("\n");
	const kept: string[] = [];
	let i = 0;
	while (i < lines.length) {
		const line = lines[i];
		kept.push(line);
		const matches = [...line.matchAll(pyRegex(HEREDOC_SRC, "g"))];
		i += 1;
		if (matches.length === 0) continue;

		let kind: "shell" | "code" | null = null;
		for (const token of split(line)) {
			const head = baseName(stripChars(token, "'\"()`;|&")).replace(/[0-9.]+$/, "");
			if (shellBins.has(head)) {
				kind = "shell";
				break;
			}
			if (codeBins.has(head)) {
				kind = "code";
				break;
			}
		}

		const delimiters = new Set(matches.map((m) => m[2]));
		// `<<'EOF'` / `<<"EOF"` のように区切り子を引用すると、シェルは本文中の `$(...)` や `` ` `` を展開しない
		const quoted = matches.some((m) => m[1] !== "");
		const body: string[] = [];
		while (i < lines.length && !delimiters.has(strip(lines[i]))) {
			body.push(lines[i]);
			i += 1;
		}
		let terminator: string | null = null;
		if (i < lines.length) {
			terminator = lines[i];
			i += 1;
		}

		if (kind === "shell") {
			// `bash <<'EOF'` は本文を bash 自身が解釈するので、引用していても `$(...)` は実行時に展開される
			kept.push(...body);
		} else if (kind === "code") {
			const code = body.map((part) => strip(part)).join(" ");
			if (quoted) ctx.literalHeredocBodies.push(code);
			kept.push(`python3 -c ${code}`);
		}
		if (terminator !== null) kept.push(terminator);
	}
	return kept.join("\n");
}

/** `cd <dir> && <cmd> <relpath>` の相対パスを結合した変種を返す。 */
export function expandCdTargets(cmd: string): string {
	const variants: string[] = [];
	for (const chunk of cmd.split(/\n+/)) {
		const parts = chunk.split(/&&|\|\||;/);
		let cwd: string | null = null;
		for (const part of parts) {
			const tokens = split(part);
			if (tokens.length === 0) continue;
			const head = baseName(tokens[0]);
			if (head === "cd" && tokens.length >= 2) {
				cwd = stripChars(tokens[1], "'\"");
				continue;
			}
			if (cwd === null) continue;
			const rebuilt = [tokens[0]];
			for (const token of tokens.slice(1)) {
				if (token.startsWith("-") || token.startsWith("/") || token.startsWith("~") || token.startsWith("$")) {
					rebuilt.push(token);
				} else {
					rebuilt.push(`${stripChars(cwd, "/", false, true)}/${token}`);
				}
			}
			variants.push(rebuilt.join(" "));
		}
	}
	return variants.join("\n");
}

// ─── rm / scratch の判定 ─────────────────────────────────────────────────

/** rm の引数を guard 比較用の正準形にする (末尾の `/*` と `/` を畳む)。 */
export function canonicalRmTarget(raw: string): string | null {
	let token = stripChars(strip(raw), "'\"");
	if (!token) return null;
	while (token.endsWith("/*")) token = token.slice(0, -2) || "/";
	while (token.length > 1 && token.endsWith("/")) token = token.slice(0, -1);
	return token || null;
}

/** `path` が realpath 解決後も `root` の内側に留まるか。 */
export function realpathStaysInside(root: string, path: string): boolean {
	const realRoot = realpathLoose(root);
	const real = realpathLoose(path);
	return real === realRoot || real.startsWith(realRoot + sep);
}

/** PreToolUse payload の cwd。取れない・相対なら null (fail-closed)。 */
export function workspaceRoot(ctx: Ctx): string | null {
	const workspace = ctx.payloadCwd;
	if (!workspace || !isAbsolute(workspace)) return null;
	return normpath(workspace);
}

/** `cd` / `pushd` などで基点が変わるか。変わると相対パスを解決できない。 */
export function changesBaseDir(cmd: string): boolean {
	return pyRegex("(?:^|[\\s;&|(\"'\\\\])(?:cd|pushd|popd|chdir)(?![\\w-])").test(cmd);
}

/** `token` が `<workspace>/.tmp` 自身か、その配下に解決するか。 */
export function resolvesIntoScratch(ctx: Ctx, token: string, workspace: string): boolean {
	const canonical = canonicalRmTarget(token);
	if (canonical === null) return false;
	if (Array.from("$`~{}").some((ch) => canonical.includes(ch))) return false;
	const components = canonical.split("/").filter((p) => p);
	if (components.includes("..")) return false;
	const resolved = normpath(isAbsolute(canonical) ? canonical : join(workspace, canonical));
	for (const name of tableList(ctx, "_shared", "scratch_dir_names")) {
		const root = join(workspace, name);
		if (resolved !== root && !resolved.startsWith(root + sep)) continue;
		// scratch ルート自体が外を指す symlink なら、配下はすべて workspace の外にある
		if (!realpathStaysInside(workspace, root)) return false;
		// `.tmp/link` が外を指す symlink なら realpath が scratch の外へ出る
		if (realpathStaysInside(root, resolved)) return true;
	}
	return false;
}

/** `find -exec` の `{}` プレースホルダか (波括弧だけで構成されたトークン)。 */
export const isFindPlaceholder = (token: string): boolean =>
	token !== "" && Array.from(token).every((c) => c === "{" || c === "}");
