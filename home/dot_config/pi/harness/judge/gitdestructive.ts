// 元に戻せない・参照を失う、ローカルの git 操作の検出 (`[pi.confirm] local_git`)。
//
// bypass は ask を確認なしで通す。`git branch -D`・`git clean`・`git tag -d` のように、コミットや未追跡のファイルを
// 失う操作は、bypass でも利用者に見せるため、判定器が mustConfirm の ask にする (bash.ts)。
// 検出は、前置の環境変数・`env`・`command` などと、git のグローバルオプション (`-C`・`-c`・`--git-dir` など) を
// 読み飛ばしてから、サブコマンドとフラグを見る。別の書き方 (`-fd`・`--delete --force`) も当てる。
// 保証の範囲は既存の判定器と同じ「うっかり防止」: git の alias・外部スクリプト・動的に組み立てた文字列は見ない。
//
// node の型除去でそのまま動く書き方だけを使う。
// see docs/spec/guard/pi-decide.md#confirm
import { normalize, splitCommandSegments } from "./normalize.ts";
import { basename, shlexSplit, ShlexError } from "./pystr.ts";

// 値を 1 つ取る git のグローバルオプション (`--opt=値` の形は 1 トークン)
const GLOBAL_WITH_VALUE = new Set(["-C", "-c", "--git-dir", "--work-tree", "--namespace", "--super-prefix", "--attr-source", "--config-env", "--exec-path"]);

// サブコマンドごとの、値を取る短いオプション (束ねたフラグの途中にあると、残りが値になる)
const SHORT_WITH_VALUE: Record<string, string> = { tag: "mFu", clean: "e", branch: "u" };
// 値を取る長いオプション (次のトークンを値として読み飛ばす)
const LONG_WITH_VALUE: Record<string, Set<string>> = {
	tag: new Set(["--message", "--file", "--local-user", "--sort", "--format", "--contains", "--no-contains", "--points-at", "--merged", "--no-merged", "--cleanup"]),
	clean: new Set(["--exclude"]),
	branch: new Set(["--set-upstream-to", "--sort", "--format", "--contains", "--no-contains", "--points-at", "--merged", "--no-merged", "--track", "--color", "--abbrev"]),
};

interface Flags {
	short: Set<string>;
	long: Set<string>;
}

/** サブコマンド以降のフラグを集める。`--` 以降と、値として消費されるトークンは数えない。 */
function collectFlags(sub: string, args: string[]): Flags {
	const short = new Set<string>();
	const long = new Set<string>();
	const shortValue = SHORT_WITH_VALUE[sub] ?? "";
	const longValue = LONG_WITH_VALUE[sub] ?? new Set<string>();
	for (let i = 0; i < args.length; i++) {
		const t = args[i];
		if (t === "--") break;
		if (t.startsWith("--")) {
			const name = t.split("=", 1)[0];
			long.add(name);
			if (longValue.has(name) && !t.includes("=")) i++;
			continue;
		}
		if (t.startsWith("-") && t.length > 1) {
			for (let j = 1; j < t.length; j++) {
				const c = t[j];
				short.add(c);
				if (shortValue.includes(c)) {
					// 値は同じトークンの残りか、次のトークン
					if (j === t.length - 1) i++;
					break;
				}
			}
		}
	}
	return { short, long };
}

function has(f: Flags, shortNames: string, longNames: string[]): boolean {
	return [...shortNames].some((c) => f.short.has(c)) || longNames.some((n) => f.long.has(n));
}

/** git のサブコマンドとその引数 (グローバルオプションを読み飛ばしたあと)。 */
function destructiveReason(sub: string, args: string[]): string | null {
	const f = collectFlags(sub, args);
	switch (sub) {
		case "branch": {
			const listing = has(f, "l", ["--list", "--show-current"]);
			if (f.short.has("D") || f.short.has("M")) return "git branch -D/-M (ブランチを強制的に消す・付け替える)";
			if (has(f, "d", ["--delete"]) && has(f, "f", ["--force"])) return "git branch --delete --force (ブランチを強制的に消す)";
			if (has(f, "f", ["--force"]) && !listing) return "git branch --force (ブランチの指す先を強制的に付け替える)";
			return null;
		}
		case "clean": {
			if (has(f, "n", ["--dry-run"])) return null;
			return "git clean (未追跡のファイルを消す。git でも復旧できない)";
		}
		case "tag": {
			if (has(f, "d", ["--delete"])) return "git tag -d (タグを消す)";
			if (has(f, "f", ["--force"]) && !has(f, "l", ["--list"])) return "git tag --force (タグを付け替える)";
			return null;
		}
		case "checkout": {
			// -B は強制の付け替え (小文字の -b は新規作成だけ)
			if (f.short.has("B")) return "git checkout -B (ブランチを強制的に付け替える)";
			return null;
		}
		case "switch": {
			if (f.short.has("C") || f.long.has("--force-create")) return "git switch -C (ブランチを強制的に付け替える)";
			return null;
		}
		default:
			return null;
	}
}

function tokensOf(segment: string): string[] {
	let tokens: string[];
	try {
		tokens = shlexSplit(segment);
	} catch (e) {
		if (!(e instanceof ShlexError)) throw e;
		tokens = [segment];
	}
	return tokens.flatMap((t) => t.split(/[ \t\n]+/)).filter((t) => t).map((t) => t.replace(/^[({;!]+/, ""));
}

function inspect(segment: string): string | null {
	const tokens = tokensOf(segment);
	// env・command・time などの後ろにある場合も拾うため、先頭に限らず最初の git を探す
	const git = tokens.findIndex((t) => basename(t) === "git");
	if (git < 0) return null;
	let i = git + 1;
	while (i < tokens.length && tokens[i].startsWith("-")) {
		const name = tokens[i].split("=", 1)[0];
		i += GLOBAL_WITH_VALUE.has(tokens[i]) && !tokens[i].includes("=") ? 2 : 1;
		if (name === "--") break;
	}
	if (i >= tokens.length) return null;
	return destructiveReason(tokens[i], tokens.slice(i + 1));
}

/** 元に戻せないローカルの git 操作に当たれば、その説明を返す (当たらなければ null)。 */
export function localGitDestructiveReason(cmd: string): string | null {
	// 元のセグメントと、正規化 (sh -c・コマンド置換などの展開) したセグメントの両方を見る
	const segments = [...splitCommandSegments(cmd), ...normalize(cmd)];
	for (const segment of segments) {
		const reason = inspect(segment);
		if (reason) return reason;
	}
	return null;
}
