// bypass でも出す確認 (mustConfirm) の本文の組み立て・gh の引数の解析・結果の分類 (純関数)。see docs/spec/guard/pi-guard.md
//
// node の型除去でそのまま動く書き方だけを使う (enum・namespace は使わない)。

export const DEFAULT_TIMEOUT_SECONDS = 300;
// 本文・タイトルの表示の上限 (合計の字数)。超えたら確認を出さず止める
export const MAX_DISPLAY_CHARS = 8000;
// --body-file として読む上限 (バイト)
export const MAX_BODY_FILE_BYTES = 32 * 1024;
export const MUST_CONFIRM_TITLE = "⚠ bypass でも確認が要る操作 (外部への送信・公開、元に戻せない git 操作)";
// 保護ブランチへの統合の確認 (integration-gate.ts)。理由の先頭がこの接頭辞のとき、見出しと導入の文を変える
export const MUST_CONFIRM_INTEGRATION_PREFIX = "確認が必要な保護ブランチへの統合 (bypass でも確認する): ";
export const INTEGRATION_CONFIRM_TITLE = "⚠ 保護ブランチへの統合 (bypass でも確認が要る)";
// finish がコマンドの先頭以外にあるとき (cd が付くなど) の注記。解析は先頭だけ (別の文脈の git を見せないため)
const FINISH_ANYWHERE = /\bgit\s+flow\s+(?:feature|bugfix)\s+finish\b/;
const FINISH_NOT_LEADING_NOTE = "※ squash メッセージと衝突の事前検査は、コマンドの先頭が「git flow feature finish」のときだけ出る (cd などが付くと出ない)";

/** rules の judge.common.pi.confirm.timeout_seconds (正の整数)。無い・不正なら 300 */
export function confirmTimeoutSeconds(rules: any): number {
	const v = rules?.judge?.common?.pi?.confirm?.timeout_seconds;
	return typeof v === "number" && Number.isInteger(v) && v > 0 ? v : DEFAULT_TIMEOUT_SECONDS;
}

/** 表示用に制御文字を可視化する。\n と \t は残す。ANSI の ESC は `\x1b` と見える */
export function sanitizeForDisplay(s: string): string {
	// C0 (\t \n 以外)・DEL・C1・ゼロ幅・双方向制御・BOM
	return String(s).replace(/[\u0000-\u0008\u000b-\u001f\u007f-\u009f\u200b-\u200f\u202a-\u202e\u2060-\u2064\u2066-\u2069\ufeff]/g, (ch) => {
		const code = ch.codePointAt(0) as number;
		return code < 0x100 ? `\\x${code.toString(16).padStart(2, "0")}` : `\\u{${code.toString(16)}}`;
	});
}

/** 単純な shell の語分割。引用・`\`・行継続を扱う。展開や制御の記号が出たら null (解釈しない) */
export function shellWords(src: string): string[] | null {
	const words: string[] = [];
	let cur = "";
	let has = false;
	let i = 0;
	const n = src.length;
	while (i < n) {
		const c = src[i];
		if (c === " " || c === "\t") {
			if (has) {
				words.push(cur);
				cur = "";
				has = false;
			}
			i++;
			continue;
		}
		if (c === "\\") {
			const nx = src[i + 1];
			if (nx === undefined) return null;
			if (nx === "\n") {
				i += 2;
				continue;
			}
			cur += nx;
			has = true;
			i += 2;
			continue;
		}
		if (c === "'") {
			const j = src.indexOf("'", i + 1);
			if (j < 0) return null;
			cur += src.slice(i + 1, j);
			has = true;
			i = j + 1;
			continue;
		}
		if (c === '"') {
			i++;
			let closed = false;
			while (i < n) {
				const d = src[i];
				if (d === '"') {
					closed = true;
					i++;
					break;
				}
				if (d === "$" || d === "`") return null;
				if (d === "\\") {
					const nx = src[i + 1];
					if (nx === undefined) return null;
					if (nx === "\n") {
						i += 2;
						continue;
					}
					if ('"\\$`'.includes(nx)) {
						cur += nx;
						i += 2;
						continue;
					}
					cur += "\\";
					i++;
					continue;
				}
				cur += d;
				i++;
			}
			if (!closed) return null;
			has = true;
			continue;
		}
		if ("$`;|&<>(){}*?~#\n\r".includes(c)) return null;
		cur += c;
		has = true;
		i++;
	}
	if (has) words.push(cur);
	return words;
}

export type GhParsed = {
	kind: string;
	action: string;
	title?: string;
	body?: string;
	bodyFile?: string;
	base?: string;
	head?: string;
	repo?: string;
	positional: string[];
	others: string[];
};

const GH_ACTIONS: Record<string, string[]> = {
	pr: ["create", "comment", "edit", "review", "close", "reopen", "merge", "ready"],
	issue: ["create", "comment", "edit", "close", "reopen"],
};
const LONG_VALUE = new Set([
	"title", "body", "body-file", "base", "head", "repo", "assignee", "label", "milestone", "project", "reviewer", "template",
	"comment", "reason", "subject", "author-email", "match-head-commit", "add-assignee", "remove-assignee", "add-label",
	"remove-label", "add-reviewer", "remove-reviewer", "add-project", "remove-project",
]);
const LONG_BOOL = new Set([
	"draft", "fill", "fill-first", "fill-verbose", "web", "editor", "edit-last", "delete-last", "create-if-none", "approve",
	"request-changes", "delete-branch", "admin", "auto", "disable-auto", "squash", "merge", "rebase", "no-maintainer-edit",
	"dry-run", "remove-milestone", "comment",
]);
const NAMED = new Set(["title", "body", "body-file", "base", "head", "repo"]);

function shortFlags(action: string): { value: Record<string, string>; bool: string } {
	const create = { t: "title", b: "body", F: "body-file", B: "base", H: "head", R: "repo", a: "assignee", l: "label", m: "milestone", p: "project", r: "reviewer", T: "template" };
	switch (action) {
		case "create":
			return { value: create, bool: "dfw" };
		case "edit":
			return { value: { t: "title", b: "body", F: "body-file", B: "base", R: "repo" }, bool: "" };
		case "comment":
			return { value: { b: "body", F: "body-file", R: "repo" }, bool: "ew" };
		case "review":
			return { value: { b: "body", F: "body-file", R: "repo" }, bool: "arc" };
		case "close":
			return { value: { c: "comment", r: "reason", R: "repo" }, bool: "d" };
		case "reopen":
			return { value: { c: "comment", R: "repo" }, bool: "" };
		case "merge":
			return { value: { t: "subject", b: "body", F: "body-file", A: "author-email", R: "repo" }, bool: "mrsd" };
		default:
			return { value: { R: "repo" }, bool: "" };
	}
}

/**
 * `gh pr|issue <action> ...` の引数を保守的に解析する (確認画面の参考表示用)。
 * 解釈できない形 (展開・連結・未知のフラグ・値の欠落) は null
 */
export function parseGh(command: string): GhParsed | null {
	const words = shellWords(String(command).trim());
	if (!words || words.length < 3 || words[0] !== "gh") return null;
	const kind = words[1];
	const action = words[2];
	if (!GH_ACTIONS[kind]?.includes(action)) return null;
	const out: GhParsed = { kind, action, positional: [], others: [] };
	const short = shortFlags(action);
	const assign = (name: string, value: string | null) => {
		if (NAMED.has(name) && value !== null) {
			const key = name === "body-file" ? "bodyFile" : name;
			(out as any)[key] = value;
		} else out.others.push(value === null ? `--${name}` : `--${name} ${value}`);
	};
	let rest = false;
	for (let i = 3; i < words.length; i++) {
		const w = words[i];
		if (rest || w === "-" || !w.startsWith("-")) {
			out.positional.push(w);
			continue;
		}
		if (w === "--") {
			rest = true;
			continue;
		}
		if (w.startsWith("--")) {
			const eq = w.indexOf("=");
			const name = eq < 0 ? w.slice(2) : w.slice(2, eq);
			const isBool = LONG_BOOL.has(name) && !(name === "comment" && action !== "review");
			if (isBool) {
				if (eq >= 0) return null;
				assign(name, null);
			} else if (LONG_VALUE.has(name)) {
				if (eq >= 0) assign(name, w.slice(eq + 1));
				else {
					if (i + 1 >= words.length) return null;
					assign(name, words[++i]);
				}
			} else return null;
			continue;
		}
		// 短縮形 (束ね `-dw`、値の連結 `-tT`・`-t=T`)
		for (let k = 1; k < w.length; k++) {
			const ch = w[k];
			const name = short.value[ch];
			if (name) {
				let v = w.slice(k + 1);
				if (v.startsWith("=")) v = v.slice(1);
				if (v === "") {
					if (i + 1 >= words.length) return null;
					v = words[++i];
				}
				assign(name, v);
				break;
			}
			if (short.bool.includes(ch)) continue;
			return null;
		}
	}
	return out;
}

export type BodyFileResult = { ok: true; text: string } | { ok: false; why: string };
export type MustView =
	| { kind: "confirm"; title: string; body: string; bodyFile?: { path: string; text: string } }
	| { kind: "block"; reason: string };

function field(name: string, value: string): string {
	const v = sanitizeForDisplay(value);
	return v.includes("\n") ? `  ${name}:\n${v.split("\n").map((l) => `    ${l}`).join("\n")}` : `  ${name}: ${v}`;
}

// --- git flow finish の確認 (統合の内容と squash メッセージ) ---
// 純関数。git の結果は呼び出し側 (index.ts) が集めて渡す

export type FinishTarget = { topic: string; name: string; branch: string };

/** 先頭が `git flow feature|bugfix finish <name>` のときの対象。`cd` や `&&` が付く形は解釈しない */
export function parseFinishTarget(command: string): FinishTarget | null {
	const m = /^\s*git\s+flow\s+(feature|bugfix)\s+finish\s+([A-Za-z0-9][A-Za-z0-9._\/-]*)(?=\s|$)/.exec(command);
	if (!m) return null;
	const topic = m[1];
	const name = m[2];
	return { topic, name, branch: name.startsWith(`${topic}/`) ? name : `${topic}/${name}` };
}

export type SquashMessage =
	| { kind: "literal"; text: string }
	| { kind: "file"; path: string }
	| { kind: "unresolved"; why: string };

// 引用された語 (または引用なしの語) の先頭の 1 つ。展開 ($ と `) を含むものは null
function firstShellWord(s: string): string | null {
	const c = s[0];
	if (c === "'") {
		const j = s.indexOf("'", 1);
		return j < 0 ? null : s.slice(1, j);
	}
	if (c === '"') {
		let out = "";
		let i = 1;
		while (i < s.length) {
			const d = s[i];
			if (d === '"') return out;
			if (d === "$" || d === "`") return null;
			if (d === "\\") {
				const nx = s[i + 1];
				if (nx === undefined) return null;
				if (nx === "\n") {
					i += 2;
					continue;
				}
				if ('"\\$`'.includes(nx)) {
					out += nx;
					i += 2;
					continue;
				}
				out += "\\";
				i++;
				continue;
			}
			out += d;
			i++;
		}
		return null;
	}
	const m = /^[^\s"'`$;&|<>(){}*?~#\\]+/.exec(s);
	return m ? m[0] : null;
}

/** `--squash-message` の値。`"$(cat <path>)"` だけはファイルとして読む。ほかの展開は確認画面では解けない */
export function extractSquashMessage(command: string): SquashMessage | null {
	const m = /--squash-message(=|[ \t]+)/.exec(command);
	if (!m) return null;
	const rest = command.slice(m.index + m[0].length);
	const sub = /^"?\$\(\s*cat\s+([^\s"'`$;&|<>()\\-][^\s"'`$;&|<>()\\]*)\s*\)"?(?=\s|$)/.exec(rest);
	if (sub) return { kind: "file", path: sub[1] };
	const w = firstShellWord(rest);
	return w === null
		? { kind: "unresolved", why: "コマンド置換や変数を含むので、確認画面では展開できない (実行時に展開される)" }
		: { kind: "literal", text: w };
}

export type ChangedFile = { path: string; add: number | null; del: number | null };

/** `git diff --numstat` の出力。バイナリ (`-`) は null */
export function parseNumstat(text: string): ChangedFile[] {
	const out: ChangedFile[] = [];
	for (const line of text.split("\n")) {
		const m = /^(\d+|-)\t(\d+|-)\t(.+)$/.exec(line);
		if (!m) continue;
		out.push({ path: m[3], add: m[1] === "-" ? null : Number(m[1]), del: m[2] === "-" ? null : Number(m[2]) });
	}
	return out;
}

/** `git merge-tree --write-tree --name-only --no-messages <統合先> <ブランチ>` の結果 (統合の衝突の事前検査)。ref・インデックス・作業ツリーは変えない (オブジェクトだけを書く) */
export type MergeCheck = { kind: "none" } | { kind: "conflict"; files: string[] } | { kind: "unknown"; why: string };

const OID_LINE = /^[0-9a-f]{40}([0-9a-f]{24})?$/;

/**
 * merge-tree の出力を解釈する。先頭の行が結果の tree の OID、続く行が衝突したファイル名。
 * 終了コード 0 は衝突なし、1 は衝突あり。この形でないもの (git が古い・ブランチが無い・書き込めない) は、確認できなかったとする。
 */
export function parseMergeTree(stdout: string, code: number | undefined, reason?: string): MergeCheck {
	const lines = stdout.split("\n");
	if (!OID_LINE.test(lines[0] ?? "")) return { kind: "unknown", why: reason ?? "merge-tree の出力を解釈できない" };
	if (code === 0) return { kind: "none" };
	if (code === 1) {
		const files = [...new Set(lines.slice(1).filter((l) => l.length > 0))];
		return files.length > 0 ? { kind: "conflict", files } : { kind: "unknown", why: "衝突と報告されたが、ファイル名を読めない" };
	}
	return { kind: "unknown", why: reason ?? `merge-tree が終了コード ${code ?? "不明"} で終わった` };
}

export type IntegrationFacts =
	| {
			ok: true;
			branch: string;
			target: string;
			commitCount: number;
			commits: string[];
			files: ChangedFile[];
			/** 統合先にあってブランチに無いコミット数 (分岐後に統合先が進んだ件数)。無ければ出さない */
			targetAhead?: number;
			/** 無ければ出さない */
			merge?: MergeCheck;
	  }
	| { ok: false; branch: string; target: string; why: string };

const SUMMARY_COMMITS = 5;
const MESSAGE_LINES = 8;
const SUMMARY_CONFLICTS = 8;
const MESSAGE_CHARS = 3000;
// 箇条書きの行 (`- ` `* ` `・` `1. `)。続きの字下げ行も、まとめて省く
const BULLET = /^\s*(?:[-*+•・]|\d+[.)])\s+\S/;

function indent(text: string, pad: string): string[] {
	return sanitizeForDisplay(text).split("\n").map((l) => (l.length > 0 ? `${pad}${l}` : ""));
}

function lastName(path: string): string {
	return path.split("/").pop() || path;
}

/** squash メッセージの行。件名 + 地の文 (箇条書きは省き、空行は 1 つにまとめ、MESSAGE_LINES 行まで)。見せられないときは、その理由の 1 行 */
function squashMessageLines(msg: SquashMessage, msgFile: BodyFileResult | undefined): string[] {
	let label: string;
	let text: string;
	let whole: string;
	if (msg.kind === "literal") {
		label = "squash メッセージ:";
		text = msg.text;
		whole = "上のコマンド";
	} else if (msg.kind === "file") {
		if (!msgFile?.ok) {
			return [`squash メッセージ: ${sanitizeForDisplay(msgFile?.why ?? `ファイル ${msg.path} を読めない`)}。確認画面では見せられない (実行時に読まれる)`];
		}
		label = `squash メッセージ (${sanitizeForDisplay(lastName(msg.path))}):`;
		// `$(cat ...)` は末尾の改行を落とす
		text = msgFile.text.replace(/\n+$/, "");
		whole = sanitizeForDisplay(msg.path);
	} else {
		return [`squash メッセージ: ${sanitizeForDisplay(msg.why)}`];
	}
	// 先頭の空行は落とし、連続する空行は 1 つにまとめる。箇条書き (と、その続きの字下げ行) は省く
	const rows: string[] = [];
	let bullets = 0;
	let inBullet = false;
	for (const l of text.slice(0, MESSAGE_CHARS).split("\n")) {
		if (BULLET.test(l)) {
			bullets++;
			inBullet = true;
			continue;
		}
		if (inBullet && /^\s+\S/.test(l)) continue;
		inBullet = false;
		const blank = l.trim() === "";
		if (blank && (rows.length === 0 || rows[rows.length - 1] === "")) continue;
		rows.push(blank ? "" : l);
	}
	while (rows.length > 0 && rows[rows.length - 1] === "") rows.pop();
	const shown = rows.slice(0, 1 + MESSAGE_LINES);
	const rest = rows.length - shown.length;
	const out = [label, ...indent(shown.join("\n"), "  ")];
	const omitted: string[] = [];
	if (bullets > 0) omitted.push(`箇条書き ${bullets} 項目`);
	if (rest > 0) omitted.push(`あと ${rest} 行`);
	if (text.length > MESSAGE_CHARS) omitted.push("以降");
	if (omitted.length > 0) out.push(`  … ${omitted.join("・")}を省略 (全文は ${whole})`);
	return out;
}

/**
 * `git flow feature|bugfix finish` の確認画面の本文 (実行するコマンドより前)。結論を先に、メッセージを変更の一覧より先に出す。
 * 変更の一覧は出さず、衝突の有無だけを出す (あり・確認できなかったときは先頭、なしはメッセージの後に 1 行)。メッセージの箇条書きは省く。導入文と理由は出さない (見出しと同じことなので)
 */
export function finishBodyLines(
	command: string,
	finish: FinishTarget,
	facts: IntegrationFacts | undefined,
	msg: SquashMessage | null,
	msgFile: BodyFileResult | undefined,
): string[] {
	const sq = msg !== null || /(^|\s)--squash(\s|$)/.test(command) ? " (squash)" : "";
	const lines: string[] = [
		facts
			? `${sanitizeForDisplay(facts.branch)} → ${sanitizeForDisplay(facts.target)}${sq}`
			: `${sanitizeForDisplay(finish.branch)} を統合${sq}`,
	];
	const merge = facts?.ok ? facts.merge : undefined;
	if (merge?.kind === "conflict") {
		lines.push(`⚠ 衝突あり (${merge.files.length} ファイル)。統合すると失敗する見込み`);
		for (const f of merge.files.slice(0, SUMMARY_CONFLICTS)) lines.push(`    ${sanitizeForDisplay(f)}`);
		if (merge.files.length > SUMMARY_CONFLICTS) lines.push(`    … ほか ${merge.files.length - SUMMARY_CONFLICTS} ファイル`);
	} else if (merge?.kind === "unknown") {
		lines.push(`衝突の事前検査: 確認できなかった (${sanitizeForDisplay(merge.why)})`);
	}
	if (facts && !facts.ok) lines.push(`(統合の内容を取得できなかった: ${sanitizeForDisplay(facts.why)})`);
	if (msg) lines.push(...squashMessageLines(msg, msgFile));
	if (facts?.ok) {
		// 変更の一覧 (件数・ファイル・統合先の進み) は出さない (履歴で見る)。衝突は、あり・確認できなかったときは先頭に出したので、なしだけをここに 1 行
		if (merge?.kind === "none") lines.push("衝突: なし");
		// メッセージが無いときだけ、コミットの件名を出す (何を統合するかが、ほかに見えないので)
		if (!msg) {
			for (const c of facts.commits.slice(0, SUMMARY_COMMITS)) lines.push(`  ${sanitizeForDisplay(c)}`);
			if (facts.commitCount > SUMMARY_COMMITS) lines.push(`  … ほか ${facts.commitCount - SUMMARY_COMMITS} 件`);
		}
	}
	return lines;
}

/**
 * mustConfirm の確認画面を組む。コマンドは全文を出す。gh なら解析結果を参考として別に出し、
 * --body-file は readBodyFile で読んで本文を出す。読めない・長すぎるときは確認を出さず block。
 * 統合の確認で、`git flow feature finish` なら、統合の内容 (facts。git の結果) と squash メッセージも出す
 * (`"$(cat <path>)"` はファイルを読んで見せ、承認の後に変わったら実行を止める)
 */
export function buildMustConfirmView(
	command: string,
	reason: string,
	readBodyFile: (path: string) => BodyFileResult,
	facts?: IntegrationFacts,
): MustView {
	const parsed = parseGh(command);
	let fileText: string | undefined;
	if (parsed?.bodyFile !== undefined) {
		const r = readBodyFile(parsed.bodyFile);
		if (!r.ok) return { kind: "block", reason: `本文のファイルを読めないので確認できない: ${sanitizeForDisplay(r.why)}` };
		fileText = r.text;
	}
	const size = (parsed?.title?.length ?? 0) + (parsed?.body?.length ?? 0) + (fileText?.length ?? 0);
	if (size > MAX_DISPLAY_CHARS) {
		return { kind: "block", reason: "本文が長すぎて確認できない。短くするか、利用者が自分で実行する" };
	}
	const integration = reason.startsWith(MUST_CONFIRM_INTEGRATION_PREFIX);
	// finish は、結論 (行き先・メッセージ・変更) を先に、実行するコマンドを最後に出す (導入文と理由は出さない)
	const finish = integration ? parseFinishTarget(command) : null;
	if (finish) {
		const msg = extractSquashMessage(command);
		const msgFile = msg?.kind === "file" ? readBodyFile(msg.path) : undefined;
		if (facts || msg) {
			const body = [...finishBodyLines(command, finish, facts, msg, msgFile), "", "実行:", sanitizeForDisplay(command)].join("\n");
			const compact: MustView = { kind: "confirm", title: INTEGRATION_CONFIRM_TITLE, body };
			// 承認の後に変わったら実行を止めるための印 (index.ts の execute() が読み直して比べる)
			if (msg?.kind === "file" && msgFile?.ok) compact.bodyFile = { path: msg.path, text: msgFile.text };
			return compact;
		}
	}
	const lead = integration
		? "保護ブランチ (develop など) への統合、または保護 ref を変える操作です。内容を確認してから承認してください。"
		: "bypass でも確認が要る操作です (外部への送信・公開、元に戻せない git 操作)。";
	const lines = [lead, ""];
	// 先頭が finish でないと結論の画面にならない。黙って汎用の画面に戻らないよう、理由を 1 行出す
	if (integration && !finish && FINISH_ANYWHERE.test(command)) lines.push(FINISH_NOT_LEADING_NOTE, "");
	lines.push("コマンド (全文):", sanitizeForDisplay(command));
	if (parsed) {
		lines.push("", "解析結果 (参考。実際に実行されるのは上のコマンド):", `  対象: gh ${parsed.kind} ${parsed.action}`);
		if (parsed.repo !== undefined) lines.push(field("repo", parsed.repo));
		if (parsed.positional.length > 0) lines.push(field("対象の番号・ブランチ", parsed.positional.join(" ")));
		if (parsed.base !== undefined) lines.push(field("base", parsed.base));
		if (parsed.head !== undefined) lines.push(field("head", parsed.head));
		if (parsed.title !== undefined) lines.push(field("title", parsed.title));
		if (parsed.body !== undefined) lines.push(field("body", parsed.body));
		if (parsed.bodyFile !== undefined) lines.push(field("body-file", parsed.bodyFile));
		for (const o of parsed.others) lines.push(field("その他", o));
	}
	if (fileText !== undefined && parsed?.bodyFile !== undefined) {
		lines.push("", `本文ファイル ${sanitizeForDisplay(parsed.bodyFile)} の内容 (ハーネスが読んだもの):`, sanitizeForDisplay(fileText));
	}
	// 統合の確認は、見出しと同じ接頭辞と、「コマンド (全文)」の重複になる末尾のコマンドを落とす
	const shown = integration ? reason.slice(MUST_CONFIRM_INTEGRATION_PREFIX.length).split("\n実行しようとしているコマンド:")[0] : reason;
	lines.push("", `理由: ${sanitizeForDisplay(shown)}`);
	const view: MustView = { kind: "confirm", title: integration ? INTEGRATION_CONFIRM_TITLE : MUST_CONFIRM_TITLE, body: lines.join("\n") };
	if (fileText !== undefined && parsed?.bodyFile !== undefined) view.bodyFile = { path: parsed.bodyFile, text: fileText };
	return view;
}

export type ConfirmOutcome = "approved" | "denied" | "timeout" | "aborted" | "error";
export type ConfirmRaw = { ok: boolean; elapsedMs: number; aborted: boolean; error: boolean };

// タイマーの誤差 (ms)。期限のこの手前までに false で戻れば時間切れとみなす
const TIMEOUT_SLACK_MS = 250;

/** confirm の false は拒否・取消・時間切れが区別できないので、経過時間と期限で見分ける */
export function classifyConfirm(r: ConfirmRaw, timeoutMs: number): ConfirmOutcome {
	if (r.ok) return "approved";
	if (r.error) return "error";
	if (r.aborted) return "aborted";
	return r.elapsedMs >= timeoutMs - TIMEOUT_SLACK_MS ? "timeout" : "denied";
}

export const NO_UI_REASON = "確認できない実行 (print・子) では、確認が要る操作は拒否する。利用者が `pis` の対話で実行する";

/** block の理由 (接頭辞 `not approved:` は呼び出し側が付ける) */
export function outcomeReason(o: ConfirmOutcome): string {
	switch (o) {
		case "timeout":
			return "確認が時間内に無かったので拒否した（元の操作は未実行）。同じ操作は再試行しない。この操作に依存しない作業を続け、最後に「拒否された操作」として報告すること。依存する作業しか残っていなければ、そこで止まって理由を報告する";
		case "aborted":
			return "確認の途中で中断された（元の操作は未実行）。同じ操作は再試行しない。この操作に依存しない作業を続け、最後に「拒否された操作」として報告すること。依存する作業しか残っていなければ、そこで止まって理由を報告する";
		case "error":
			return "確認を表示できなかったので拒否した（元の操作は未実行）。同じ操作は再試行しない。この操作に依存しない作業を続け、最後に「拒否された操作」として報告すること。依存する作業しか残っていなければ、そこで止まって理由を報告する";
		case "approved":
			return "";
		default:
			return "利用者が拒否した。同じ操作をくり返さない";
	}
}

/** 表示の幅 (端末のセル数)。全角 (CJK・全角記号) は 2 */
export function cellWidth(s: string): number {
	let w = 0;
	for (const ch of s) {
		const c = ch.codePointAt(0) ?? 0;
		w += (c >= 0x1100 && c <= 0x115f) || (c >= 0x2e80 && c <= 0xa4cf) || (c >= 0xac00 && c <= 0xd7a3) || (c >= 0xf900 && c <= 0xfaff) || (c >= 0xfe30 && c <= 0xfe6f) || (c >= 0xff00 && c <= 0xff60) || (c >= 0xffe0 && c <= 0xffe6) ? 2 : 1;
	}
	return w;
}

/** 端末の大きさ。数でなければ undefined (試験・RPC・パイプ。呼び出し側は従来の固定値に戻る) */
export function termSize(): { columns?: number; rows?: number } {
	const num = (v: unknown): number | undefined => (typeof v === "number" && Number.isFinite(v) && v > 0 ? Math.floor(v) : undefined);
	return { columns: num(process.stdout?.columns), rows: num(process.stdout?.rows) };
}

/** 表示に使う幅 (セル数)。端末の幅が分かれば `columns - margin` (30〜200 に収める)。ただし `fallback` (従来の固定値) より狭くはしない。不明なら `fallback` */
export function fitWidth(fallback: number, margin: number): number {
	const { columns } = termSize();
	if (columns === undefined) return fallback;
	return Math.max(fallback, Math.min(200, Math.max(30, columns)) - margin);
}

/** 幅 (セル数) を超える行を、末尾を … にして切る */
export function clipCells(s: string, max: number): string {
	if (cellWidth(s) <= max) return s;
	let out = "";
	let w = 0;
	for (const ch of s) {
		const cw = cellWidth(ch);
		if (w + cw > max - 1) break;
		out += ch;
		w += cw;
	}
	return `${out}…`;
}
