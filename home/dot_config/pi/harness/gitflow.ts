// git-flow-next (git flow) の固定の引数の操作 (CHG-0047)。純粋な関数だけ: 名前の検証・実効設定の安全プロファイル・引数の組み立て。
// ★git flow は、実効設定 (gitflow.*) で意味が変わる (例: gitflow.<type>.finish.push=true で finish が push する)。
//   操作の直前に、実効設定を許可リストと照合し、外れたら実行しない。
// see docs/change/0047-gitflow.md#許可の形の設計の修正review-の反映上の案に優先する

/** `git config --get-regexp '^gitflow\.'` の 1 行 = 1 件。キーは git が正規化した形 (先頭と末尾は小文字) */
export type ConfigEntry = { key: string; value: string };

const NAME_RE = /^[a-z0-9][a-z0-9._-]{0,63}$/;

/** feature の名前を検証する。問題があれば理由、無ければ null */
export function validateFeatureName(name: unknown): string | null {
	if (typeof name !== "string") return "名前が文字列でない";
	if (!NAME_RE.test(name)) return "名前は英小文字か数字で始まり、英小文字・数字・`.`・`_`・`-` の 1〜64 字";
	if (name.includes("..")) return "名前に `..` を含められない";
	if (name.endsWith(".") || name.endsWith(".lock")) return "名前の末尾に `.` や `.lock` を使えない";
	return null;
}

/** `git config --get-regexp` の出力 (1 行に `key value`) を読む。同じキーが複数あれば全て残す */
export function parseConfigLines(text: string): ConfigEntry[] {
	const out: ConfigEntry[] = [];
	for (const line of text.split("\n")) {
		if (!line.trim()) continue;
		const i = line.indexOf(" ");
		out.push(i < 0 ? { key: line.trim(), value: "" } : { key: line.slice(0, i), value: line.slice(i + 1).trim() });
	}
	return out;
}

// 知っているキー (git が小文字にする先頭 gitflow と末尾以外の、ブランチの種類の名前は大文字小文字を保つ)
const KNOWN_KEYS: RegExp[] = [
	/^gitflow\.version$/,
	/^gitflow\.initialized$/,
	/^gitflow\.worktreepath$/,
	// push 系は false のときだけ (true は下の検査で拒否)。origin は origin のときだけ
	/^gitflow\.feature\.(start|finish)\.(push|pushtag)$/,
	/^gitflow\.origin$/,
	/^gitflow\.branch\.(main|develop|feature)\.(type|parent|startpoint|upstreamstrategy|downstreamstrategy|prefix|autoupdate|tag|worktree)$/,
	// 実行時の状態 (start が書き、finish が消す。サンドボックスの内側では書けない)
	/^gitflow\.branch\.feature\/[^.]*\.base$/,
	/^gitflow\.worktree\.feature\/[^.]*\.managed$/,
];

export type Profile = { ok: boolean; problems: string[] };

function valueOf(entries: ConfigEntry[], key: string): string | undefined {
	const hits = entries.filter((e) => e.key === key);
	return hits.length === 0 ? undefined : hits[hits.length - 1].value;
}

export type Model = "gitflow-lite" | "other";

/**
 * コミット済みの `.gitflow` (を `git config --blob --get-regexp` で読んだもの) が、gitflow-lite (main / develop / feature、feature は squash) か。
 * 規約の強制 (CHG-0049) を掛けるかの識別で、固定操作を安全に実行できるか (checkSafeProfile) とは別。
 * ブランチ名のカスタムは未対応なので other にする。
 */
export function identifyModel(entries: ConfigEntry[]): Model {
	const v = (key: string) => valueOf(entries, key);
	if (v("gitflow.initialized") !== "true") return "other";
	const branches = new Set<string>();
	for (const e of entries) {
		const m = /^gitflow\.branch\.([^.]+)\./.exec(e.key);
		if (m) branches.add(m[1]);
	}
	if (branches.size !== 3 || !["main", "develop", "feature"].every((b) => branches.has(b))) return "other";
	const lite =
		v("gitflow.branch.main.type") === "base" &&
		v("gitflow.branch.develop.type") === "base" &&
		v("gitflow.branch.develop.parent") === "main" &&
		v("gitflow.branch.feature.type") === "topic" &&
		v("gitflow.branch.feature.parent") === "develop" &&
		v("gitflow.branch.feature.prefix") === "feature/" &&
		v("gitflow.branch.feature.upstreamstrategy") === "squash";
	return lite ? "gitflow-lite" : "other";
}

/** このリポジトリの gitflow-lite (main / develop / feature、squash) として安全かを検査する。repoRoot は worktree の置き場の検査に使う */
export function checkSafeProfile(entries: ConfigEntry[], repoRoot: string): Profile {
	const problems: string[] = [];
	const want = (key: string, expected: string) => {
		const v = valueOf(entries, key);
		if (v !== expected) problems.push(`${key} は ${expected} でなければならない (今: ${v ?? "未設定"})`);
	};
	want("gitflow.initialized", "true");
	want("gitflow.branch.feature.type", "topic");
	want("gitflow.branch.feature.parent", "develop");
	want("gitflow.branch.feature.startpoint", "develop");
	want("gitflow.branch.feature.prefix", "feature/");
	want("gitflow.branch.feature.upstreamstrategy", "squash");
	want("gitflow.branch.develop.type", "base");
	want("gitflow.branch.develop.parent", "main");
	const tag = valueOf(entries, "gitflow.branch.feature.tag");
	if (tag !== undefined && tag !== "false") problems.push("gitflow.branch.feature.tag は false でなければならない");

	const wt = valueOf(entries, "gitflow.worktreepath");
	if (wt === undefined) problems.push("gitflow.worktreePath が未設定 (.tmp/worktrees/ の下にする)");
	else if (!isUnderWorktrees(wt, repoRoot)) problems.push(`gitflow.worktreePath が .tmp/worktrees/ の下でない (今: ${wt})`);

	for (const e of entries) {
		// 危険な設定: 外へ送る・外のコードを動かす
		if (/^gitflow\.[^.]+\.[^.]+\.(push|pushtag)$/.test(e.key) && e.value !== "false") problems.push(`${e.key}=${e.value} は、finish などが push する設定`);
		if (/^gitflow\.path\./.test(e.key) || /hook|filter/.test(e.key)) problems.push(`${e.key} は、外のコードを動かす設定`);
		if (/^gitflow\.(origin|remote)$/.test(e.key) && e.value !== "origin") problems.push(`${e.key} が origin 以外 (今: ${e.value})`);
		if (!KNOWN_KEYS.some((re) => re.test(e.key)) && !problems.some((p) => p.startsWith(e.key))) problems.push(`${e.key} は、許可リストに無い設定`);
	}
	return { ok: problems.length === 0, problems };
}

function isUnderWorktrees(value: string, repoRoot: string): boolean {
	// 相対 (.tmp/worktrees/…) か、repoRoot の .tmp/worktrees/ の下の絶対パス。`..` は拒否
	if (value.includes("..") || value.includes("~")) return false;
	const root = repoRoot.replace(/\/+$/, "");
	const rel = value.startsWith("/") ? (value.startsWith(`${root}/`) ? value.slice(root.length + 1) : null) : value.replace(/^\.\//, "");
	return rel !== null && rel.startsWith(".tmp/worktrees/");
}

/** feature の起票。確認なし。ネットワークに触れない (--no-fetch)。worktree を作る */
export function startArgv(name: string): string[] {
	return ["git", "flow", "feature", "start", name, "--worktree", "--no-fetch"];
}

/** feature の破棄 (ブランチと worktree を消す)。リモートに触れない (--no-fetch --no-remote)。--force は未マージでも消すためで、確認の画面で件数を見せる。未コミットの変更がある worktree は --force-worktree を付けないので拒否される */
export function discardArgv(name: string): string[] {
	return ["git", "flow", "feature", "delete", name, "--force", "--no-fetch", "--no-remote"];
}

/** feature のクローズ (squash)。リモートに触れない (--keepremote --no-fetch --no-push --no-pushtag)。タグを作らない。メッセージは `=` で渡し、`-` で始まっても引数として読まれない */
export function finishArgv(name: string, message: string): string[] {
	return [
		"git", "flow", "feature", "finish", name,
		"--squash", `--squash-message=${message}`,
		"--keepremote", "--no-fetch", "--no-push", "--no-pushtag", "--notag",
	];
}
