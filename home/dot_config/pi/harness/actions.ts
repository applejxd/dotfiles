// guarded_action: 承認つきで、表 (rules.json の judge.common.pi.actions) に宣言した操作 (git commit・gh issue comment) を実行する。
// 承認はこのツールが 1 回だけ取り、承認した argv をシェル無しでそのまま実行する。see docs/change/0038-guard-reclassification.md
//
// node の型除去でそのまま動く書き方だけを使う (enum・namespace は使わない)。

import { execFile } from "node:child_process";
import { createHash } from "node:crypto";
import { randomUUID } from "node:crypto";
import { mkdtempSync, realpathSync, rmSync, statSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { isAbsolute, join, relative, sep } from "node:path";
import { MAX_DISPLAY_CHARS, cellWidth, clipCells, confirmTimeoutSeconds, outcomeReason, sanitizeForDisplay } from "./confirm-view.ts";
import { showTextViewer } from "./text-viewer.ts";
import { classifyFreeZone, freeZoneSettings, type FreeZone } from "./freezone.ts";
import { gitSync } from "./gitrun.ts";
import { reconcilePending, repoTargetEnv, savePendingSnapshot, snapshotStaged, type Snapshot } from "./pending-store.ts";

export const ACTION_TOOL = "action";
const NOT_APPROVED = "not approved:";
const REPO_RE = /^[A-Za-z0-9][A-Za-z0-9_.-]*\/[A-Za-z0-9_.-]+$/;
const INT_MAX = 1_000_000_000;
const EXEC_TIMEOUT_MS = 120_000;
const OUTPUT_TAIL_CHARS = 8000;
const STAT_MAX_CHARS = 4000;

export type FieldSpec = { type: "repo" | "int" | "line" | "text" | "dir"; file?: boolean; content?: boolean; max_chars?: number; optional?: boolean };
export type ActionSpec = {
	id: string;
	label: string;
	argv: string[];
	fields: Record<string, FieldSpec>;
	replaces: string[];
	preview: "none" | "git_staged";
};

/** rules.judge.common.pi.actions (配列)。無い・形が違う項目は捨てる (生成器が起動前に検証している) */
export function loadActions(rules: any): ActionSpec[] {
	const raw = rules?.judge?.common?.pi?.actions;
	if (!Array.isArray(raw)) return [];
	return raw.filter((a: any) => a && typeof a.id === "string" && Array.isArray(a.argv) && a.fields && typeof a.fields === "object");
}

/** `gh_issue_comment(repo, number, body)  issue にコメントを投稿`。任意の引数は `dir?` */
export function actionLine(a: ActionSpec): string {
	return `${a.id}(${Object.entries(a.fields).map(([n, s]) => (s.optional ? `${n}?` : n)).join(", ")})  ${a.label}`;
}

export function actionDescription(actions: ActionSpec[]): string {
	return [
		"投稿・コミットは、このツールで行う。承認はこのツールが 1 回だけ取る。事前にチャットや ask で承認を取らない。",
		"引数: {action: 操作の ID, params: その操作の引数 (全て必須。`?` 付きは任意)}。操作:",
		...actions.map(actionLine),
		...(actions.some((a) => a.fields.dir) ? ["dir: cwd 配下にある別の git リポジトリ (入れ子・仮想 monorepo) の最上位を cwd からの相対パスで指す。省略すると cwd のリポジトリ"] : []),
	].join("\n");
}

export type Values = Record<string, string>;
type Checked = { ok: true; action: ActionSpec; values: Values } | { ok: false; error: string };

/** 未知の action・引数の欠落・型・長さ・未知のキーを、フィールドごとのエラーで返す (モデルが自己修正できるように) */
export function validateCall(actions: ActionSpec[], input: any): Checked {
	const id = input?.action;
	const action = actions.find((a) => a.id === id);
	if (!action) {
		return { ok: false, error: `unknown action ${JSON.stringify(id)}. 使える操作:\n${actions.map(actionLine).join("\n")}` };
	}
	const params = input?.params;
	if (params === null || typeof params !== "object" || Array.isArray(params)) {
		return { ok: false, error: `params は object で渡す。${actionLine(action)}` };
	}
	const errors: string[] = [];
	const values: Values = {};
	for (const key of Object.keys(params)) {
		if (!(key in action.fields)) errors.push(`params.${key}: 未知のキー (使えるのは ${Object.keys(action.fields).join(", ")})`);
	}
	for (const [name, spec] of Object.entries(action.fields)) {
		const v = (params as any)[name];
		if ((v === undefined || v === null) && spec.optional) continue;
		if (v === undefined || v === null) {
			errors.push(`params.${name}: 必須 (${spec.type})`);
			continue;
		}
		if (spec.type === "dir") {
			const d = normalizeDirParam(v);
			if (typeof d === "object") errors.push(`params.${name}: ${d.error}`);
			else if (d !== "") values[name] = d;
			continue;
		}
		if (spec.type === "repo") {
			if (typeof v !== "string" || !REPO_RE.test(v)) errors.push(`params.${name}: owner/name の形の文字列 (受け取った値: ${JSON.stringify(v)})`);
			else values[name] = v;
		} else if (spec.type === "int") {
			const n = typeof v === "number" ? v : typeof v === "string" && /^[0-9]+$/.test(v) ? Number(v) : NaN;
			if (!Number.isInteger(n) || n < 1 || n > INT_MAX) errors.push(`params.${name}: 1〜${INT_MAX} の整数 (受け取った値: ${JSON.stringify(v)})`);
			else values[name] = String(n);
		} else if (spec.type === "line") {
			// 1 行の短い文字列 (issue のタイトルなど)。改行・制御文字を含められない (確認画面と argv の見え方がずれないように)
			const max = spec.max_chars ?? 256;
			if (typeof v !== "string") errors.push(`params.${name}: 文字列`);
			else if (v.trim().length === 0) errors.push(`params.${name}: 空にできない`);
			else if (v.length > max) errors.push(`params.${name}: ${max} 字以下 (受け取った長さ: ${v.length})`);
			else if (/[\u0000-\u001f\u007f\u2028\u2029]/.test(v)) errors.push(`params.${name}: 改行・制御文字を含められない (1 行にする)`);
			else values[name] = v;
		} else {
			const max = spec.max_chars ?? 8000;
			if (typeof v !== "string") errors.push(`params.${name}: 文字列`);
			else if (v.length === 0) errors.push(`params.${name}: 空にできない`);
			else if (v.length > max) errors.push(`params.${name}: ${max} 字以下 (受け取った長さ: ${v.length})`);
			else if (v.includes("\0")) errors.push(`params.${name}: NUL を含められない`);
			else values[name] = v;
		}
	}
	if (errors.length > 0) return { ok: false, error: `${action.id} の引数が不正:\n${errors.join("\n")}` };
	const shown = Object.entries(action.fields).reduce((n, [name, s]) => n + (s.content ? (values[name]?.length ?? 0) : 0), 0);
	if (shown > MAX_DISPLAY_CHARS) return { ok: false, error: "本文が長すぎて確認できない。短くする" };
	return { ok: true, action, values };
}

/**
 * dir の引数 (cwd からの相対パス) を構文だけ検証して正規化する。空文字列は「cwd 自身」 (省略と同じ)。
 * 実体の検査 (cwd の中・シンボリックリンク・git の最上位) は resolveRepoDir。
 */
export function normalizeDirParam(v: unknown): string | { error: string } {
	if (typeof v !== "string") return { error: "文字列 (cwd からの相対パス)" };
	if (v.length > 256) return { error: `256 字以下 (受け取った長さ: ${v.length})` };
	if (/[\u0000-\u001f\u007f\u2028\u2029\\]/.test(v)) return { error: "改行・制御文字・バックスラッシュを含められない" };
	if (isAbsolute(v) || v.startsWith("~") || /^[A-Za-z]:/.test(v)) return { error: "cwd からの相対パスで指す (絶対パス・~ は不可)" };
	const parts = v.split("/").filter((p) => p !== "" && p !== ".");
	if (parts.includes("..")) return { error: "`..` を含められない" };
	return parts.join("/");
}

/** 解決済みの実体パスを、cwd からの相対パス (判定器が cwd に連結して見る形) にする。cwd 自身は空 */
export function relativeDir(base: string, real: string): string {
	try {
		return relative(realpathSync(base), real);
	} catch {
		return real;
	}
}

/**
 * dir を実体に解決し、cwd の中にあり、かつ git の最上位 (作業ツリーの根) であることを確かめて、その実体パスを返す。
 * 解決後のパスの区切りで比べる (箱外へのシンボリックリンクを拒否する)。省略 (空) は cwd をそのまま返す。
 * 対象を選ぶ継承環境変数 (GIT_DIR など) は、ここでも実行でも落とす (repoTargetEnv)。拒否はしない。
 */
export async function resolveRepoDir(base: string, dir: string | undefined): Promise<string> {
	if (!dir) return base;
	let realBase: string;
	let real: string;
	try {
		realBase = realpathSync(base);
		real = realpathSync(join(base, dir));
	} catch {
		throw new Error(`dir ${JSON.stringify(dir)} を解決できない (存在しない)`);
	}
	if (real !== realBase && !real.startsWith(realBase.endsWith(sep) ? realBase : realBase + sep)) {
		throw new Error(`dir ${JSON.stringify(dir)} が cwd の外を指す (シンボリックリンクを含む)`);
	}
	if (!statSync(real).isDirectory()) throw new Error(`dir ${JSON.stringify(dir)} がディレクトリではない`);
	const top = await run("git", ["rev-parse", "--show-toplevel"], real);
	if (top.code !== 0) throw new Error(`dir ${JSON.stringify(dir)} は git のリポジトリではない`);
	let realTop: string;
	try {
		realTop = realpathSync(String(top.stdout).trim());
	} catch {
		throw new Error(`dir ${JSON.stringify(dir)} のリポジトリの根を解決できない`);
	}
	if (realTop !== real) throw new Error(`dir ${JSON.stringify(dir)} はリポジトリの最上位ではない (最上位: ${realTop})。最上位を指す`);
	return real;
}

/** argv の置換。`{名前}` は値、`{名前_file}` は本文ファイルの絶対パス。値は 1 つの要素のまま (分割・解釈しない) */
export function buildArgv(action: ActionSpec, values: Values, files: Record<string, string>): string[] {
	return action.argv.map((el, i) =>
		i === 0
			? el
			: el.replace(/\{([a-z_][a-z0-9_]*)\}/g, (_m, key: string) => {
					const m = /^(.+)_file$/.exec(key);
					const v = m && action.fields[m[1]]?.file ? files[m[1]] : action.fields[key]?.file ? undefined : values[key];
					if (v === undefined) throw new Error(`argv の置換点 {${key}} を埋められない`);
					return v;
				}),
	);
}

export type Preview = { branch: string; head: string; indexId: string; stat: string };

function run(file: string, args: string[], cwd: string, opts: { buffer?: boolean; signal?: AbortSignal } = {}): Promise<{ code: number | string; stdout: any; stderr: string }> {
	return new Promise((resolve) => {
		execFile(file, args, { cwd, env: repoTargetEnv(), encoding: opts.buffer ? "buffer" : "utf8", maxBuffer: 64 * 1024 * 1024, signal: opts.signal, timeout: 30_000 }, (err: any, stdout: any, stderr: any) => {
			const code = err ? (typeof err.code === "number" || typeof err.code === "string" ? err.code : 1) : 0;
			resolve({ code, stdout: stdout ?? (opts.buffer ? Buffer.alloc(0) : ""), stderr: String(stderr ?? "") });
		});
	});
}

/** preview: "git_staged" (許可リスト。設定からコマンドを指定させない)。シェル無し・書き込み無し */
export async function gitStagedPreview(cwd: string): Promise<Preview> {
	const stat = await run("git", ["diff", "--cached", "--stat"], cwd);
	if (stat.code !== 0) throw new Error(`git のステージ済みを調べられない: ${String(stat.stderr).trim() || stat.code}`);
	let branch = await run("git", ["rev-parse", "--abbrev-ref", "HEAD"], cwd);
	let branchName = branch.code === 0 ? String(branch.stdout).trim() : "";
	if (!branchName) {
		branch = await run("git", ["symbolic-ref", "--short", "-q", "HEAD"], cwd);
		branchName = branch.code === 0 ? String(branch.stdout).trim() : "(不明)";
	}
	const head = await run("git", ["rev-parse", "HEAD"], cwd);
	const idx = await run("git", ["ls-files", "-s", "-z"], cwd, { buffer: true });
	if (idx.code !== 0) throw new Error("git の index を調べられない");
	return {
		branch: branchName,
		head: head.code === 0 ? String(head.stdout).trim() : "(コミット無し)",
		indexId: createHash("sha256").update(idx.stdout).digest("hex"),
		stat: String(stat.stdout).trim(),
	};
}

const PREVIEWS: Record<string, (cwd: string, values: Values) => Promise<Preview | null>> = {
	none: async () => null,
	git_staged: (cwd) => gitStagedPreview(cwd),
};

function samePreview(a: Preview | null, b: Preview | null): boolean {
	if (!a || !b) return a === b;
	return a.branch === b.branch && a.head === b.head && a.indexId === b.indexId;
}

function tail(s: string, n = OUTPUT_TAIL_CHARS): string {
	return s.length > n ? `…(先頭を省略)\n${s.slice(-n)}` : s;
}

export type SelectResult = { choice: string | undefined; elapsedMs: number; aborted: boolean; error: boolean };

export type ActionDeps = {
	actions: ActionSpec[];
	rules: any;
	child: boolean;
	env: NodeJS.ProcessEnv;
	redact: (text: string) => string;
	/** 判定器の最終確認 (allow 以外なら理由を返す) */
	judge: (input: unknown, cwd: string) => string | null;
	/** 確認の枠は 1 つなので、対話 (select・editor・input) は 1 件ずつこの中で行う */
	dialog: <T>(fn: () => Promise<T>) => Promise<T>;
	bell: () => void;
	/** 確認の前に、詳細をチャットへ出す (ツールの途中経過)。RPC だけで使う。無いときは、ダイアログに縮めた詳細を出す */
	progress?: (text: string) => boolean;
	/** 利用者が不在と分かった状態 (確認が時間切れ)。セッションごと。入力の世代 gen は、利用者の入力のたびに進む (index.ts) */
	absence?: { absent: boolean; gen: number };
	/** 自由区の判定 (試験で差し替える)。無ければ freezone.ts の classifyFreeZone */
	freeZone?: (cwd: string, protectedRefs: readonly string[]) => FreeZone;
};

/** TUI の組み込みの期限は、自前の期限より遅くして、保険にだけ使う (自前の期限で時間切れを判定する) */
const BACKSTOP_MS = 3000;

/** 退避して続行する結果 (deferred) または、退避できなかった結果 (defer_failed)。どちらも元の操作は未実行 */
function deferError(cwd: string, snap: Snapshot, why: string, signal: AbortSignal | undefined, dir?: string): Error {
	if (signal?.aborted) return notApproved(outcomeReason("aborted"));
	// dir 指定のときの退避は、その子のリポジトリに入る。/pending は cwd のリポジトリしか見ないので、場所を添える
	const where = dir ? ` (対象のリポジトリ: ${dir}。退避はこのリポジトリの refs/pi/pending/ にあり、/pending には出ない)` : "";
	const saved = savePendingSnapshot(cwd, snap);
	if (!saved.ok) {
		return notApproved(
			`${why}。元の操作は未実行で、内容も退避できなかった (${saved.reason})。再試行しない。この操作に依存しない作業を続け、最後に「保留したコミット」の再作成が要ると報告する${where}`,
		);
	}
	return notApproved(
		`${why}。元の操作は未実行。内容は ${saved.ref} (${saved.short}) に退避した。再試行しない。この操作に依存しない作業を続け、最後に「保留したコミット」として報告する (${dir ? `対象のリポジトリ: ${dir}。/pending には出ない。そのリポジトリの refs/pi/pending/ にある` : "利用者は /pending で確認・破棄できる"})`,
	);
}

const APPROVE = "承認して実行";
const EDIT = "編集して承認";
const REJECT = "拒否";
const VIEW_FULL = "全文を見る";

// TUI の git_commit の確認: 常に要約 + 「全文を見る」 (全文は先頭から読めるビューアで読む)。表示だけを変える: 同一性の照合・実行の argv は変えない
// see docs/spec/guard/pi-extensions.md#guarded_action
export { cellWidth, clipCells };
const SUMMARY_FILES = 5;

/** 要約を出す対象 (git_commit でプレビューがあるとき)。小さい変更も要約する: 全文を置くと、狭い画面 (スマホで約 46 桁) で全角の本文・プレビュー・argv が折り返して大きくなる。小さい変更の要約は全文とほとんど変わらない */
export function needsSummary(action: ActionSpec, _values: Values, preview: Preview | null): boolean {
	return action.id === "git_commit" && !!preview;
}

/** `git diff --stat` の棒グラフを落とし、「ファイル名 +追加 -削除」だけにする (狭い画面で棒が折り返して壊れるため)。読めない行はそのまま */
export function plainStat(stat: string): string {
	return stat
		.split("\n")
		.map((line) => {
			const sum = /^\s*(\d+) files? changed(?:, (\d+) insertions?\(\+\))?(?:, (\d+) deletions?\(-\))?\s*$/.exec(line);
			if (sum) return `${sum[1]} file${sum[1] === "1" ? "" : "s"} +${sum[2] ?? 0} -${sum[3] ?? 0}`;
			// 棒グラフの +/- は縮尺されていて正確ではないので、変更行の合計だけを出す (正確な内訳は合計行)
			const bin = /^\s*(.+?)\s+\|\s+Bin\b/.exec(line);
			if (bin) return `${bin[1]}  bin`;
			const f = /^\s*(.+?)\s+\|\s+(\d+)\s*[+-]*\s*$/.exec(line);
			if (f) return `${f[1]}  ${f[2]}`;
			return line.trim();
		})
		.join("\n");
}

/** 要約のリポジトリ名: dir の指定があればその最後の要素、無ければ作業ツリーの最後の要素 (絶対パスは、狭い画面で折り返すので出さない)。git が使えないときの代わり */
function repoName(values: Values, repo?: string): string {
	return (values.dir || repo || "").split(/[\\/]/).filter(Boolean).pop() ?? "";
}

/** 本体のリポジトリ名 (git の共通ディレクトリの親。worktree の名前ではない)。分からないときは undefined (呼び出し側がディレクトリ名に戻す) */
export function mainRepoName(cwd: string, env?: NodeJS.ProcessEnv): string | undefined {
	const r = gitSync(["rev-parse", "--path-format=absolute", "--git-common-dir"], cwd, { env });
	if (!r.ok) return undefined;
	const parts = r.stdout.trim().split(/[\\/]/).filter(Boolean);
	const last = parts.pop();
	// 通常のリポジトリは <名前>/.git、bare や submodule は共通ディレクトリ自体の名前
	return (last === ".git" ? parts.pop() : last) || undefined;
}

/** 変更ファイルの表示名: 同名が無ければ最後の要素だけ (狭い画面で長いパスが切れるため)。リネーム表記 (=>) と、同名が複数あるものはパスのまま */
export function shortenFiles(lines: string[]): string[] {
	const base = (p: string) => p.split("/").pop() || p;
	const parsed = lines.map((l) => {
		const i = l.lastIndexOf("  ");
		return i > 0 && /^(\d+|bin)$/.test(l.slice(i + 2)) && !l.slice(0, i).includes("=>") ? { path: l.slice(0, i), tail: l.slice(i) } : null;
	});
	const count = new Map<string, number>();
	for (const p of parsed) if (p) count.set(base(p.path), (count.get(base(p.path)) ?? 0) + 1);
	return lines.map((l, i) => {
		const p = parsed[i];
		return p && count.get(base(p.path)) === 1 ? `${base(p.path)}${p.tail}` : l;
	});
}

/** 見出し (prefix) つきで、幅 (セル数) を超えたら字下げして折り返す。全角は 2 桁。最大 maxLines 行で、超える分は末尾を … にする (異常に長い件名で画面を埋めない) */
export function wrapHanging(prefix: string, text: string, max: number, maxLines = 5, indent = "    "): string[] {
	const out: string[] = [];
	let cur = prefix;
	let w = cellWidth(prefix);
	for (const ch of text) {
		const cw = cellWidth(ch);
		if (w + cw > max) {
			out.push(cur);
			cur = indent;
			w = cellWidth(indent);
		}
		cur += ch;
		w += cw;
	}
	out.push(cur);
	return out.length > maxLines ? [...out.slice(0, maxLines - 1), clipCells(`${out[maxLines - 1]}…`, max)] : out;
}

/** 要約 (ラベル付きの箇条書き): リポジトリ名・ブランチと HEAD (短縮)・件名 (本文の 1 行目。切らずに折り返す)・ステージ済みの上位ファイルと統計。本文の全文は要約に出さない。width (端末のセル数) に合わせて行を切る */

export function summaryBody(action: ActionSpec, values: Values, preview: Preview, repo?: string, width = COMPACT_LINE_CHARS, repoLabel?: string): string {
	const max = Math.max(20, width - 2);
	const clip = (s: string) => clipCells(s, max);
	const lines: string[] = [];
	const name = repoLabel || repoName(values, repo);
	const head = /^[0-9a-f]{40,64}$/.test(preview.head) ? preview.head.slice(0, 8) : preview.head;
	if (name) lines.push(clip(`・リポジトリ: ${sanitizeForDisplay(name)}`));
	lines.push(clip(`・ブランチ: ${clipCells(sanitizeForDisplay(preview.branch), Math.max(10, max - cellWidth("・ブランチ: ") - cellWidth(` @ ${head}`)))} @ ${head}`));
	const texts = Object.entries(action.fields).filter(([n, s]) => s.content && values[n] !== undefined);
	for (const [n] of texts) {
		// 本文の欄が 1 つなら「件名」、複数なら欄の名前をラベルにする。件名 (本文の 1 行目) は切らずに折り返す (本文の 2 行目以降は、チャットと「全文を見る」で見る)
		lines.push(...wrapHanging(`・${texts.length > 1 ? n : "件名"}: `, sanitizeForDisplay(values[n].split("\n")[0]), max));
	}
	// 変更: 合計の行を見出しにし、ファイルをその下に字下げで出す
	const stat = sanitizeForDisplay(plainStat(compactStat(preview.stat, SUMMARY_FILES))).split("\n");
	const total = /^\d+ files? \+\d+ -\d+$/.test(stat[stat.length - 1] ?? "") ? (stat.pop() as string) : "";
	lines.push(clip(`・変更: ${total}`.trimEnd()), ...shortenFiles(stat).map((l) => clip(`    ${l}`)));
	return lines.join("\n");
}

function notApproved(why: string): Error {
	return new Error(`${NOT_APPROVED} ${why}`);
}

function viewBody(action: ActionSpec, values: Values, preview: Preview | null, argv: string[], repo?: string): string {
	const lines: string[] = [];
	const meta = Object.entries(action.fields).filter(([n, s]) => !s.content && values[n] !== undefined);
	if (meta.length > 0) lines.push("対象:", ...meta.map(([n]) => `  ${n}: ${sanitizeForDisplay(values[n])}`), "");
	for (const [n, s] of Object.entries(action.fields)) {
		if (s.content) lines.push(`${n} (全文):`, sanitizeForDisplay(values[n]), "");
	}
	if (preview) {
		lines.push("プレビュー:");
		if (repo) lines.push(`  リポジトリ: ${sanitizeForDisplay(repo)}`);
		lines.push(`  ブランチ: ${sanitizeForDisplay(preview.branch)}`, `  HEAD: ${preview.head}`, "  ステージ済み:");
		lines.push(...sanitizeForDisplay(tail(preview.stat, STAT_MAX_CHARS)).split("\n").map((l) => `    ${l}`), "");
	}
	lines.push("実行する argv (シェルは通さない):", sanitizeForDisplay(JSON.stringify(argv)));
	return lines.join("\n");
}

// RPC (Orca ・Zed など TUI 以外) の select は、title と選択肢しか持たない。全部を title に詰めると、chat UI で巨大になり読めない。
// ここでは、スマホの画面でも承認の選択肢まで見える行数を目標に縮める: 空行を入れず、本文と統計を短くし、
// 1 行の長さを制限し、argv の中の本文の重複 (--squash-message={message} など) を <名前> に置き換える。
// 全文は「編集して承認」のエディタで見られる。TUI は変えない。see docs/spec/guard/pi-extensions.md
const COMPACT_TEXT_LINES = 10;
const COMPACT_TEXT_CHARS = 800;
const COMPACT_STAT_FILES = 8;
const COMPACT_LINE_CHARS = 100;
const COMPACT_ARGV_CHARS = 240;

function clipLine(s: string): string {
	return s.length > COMPACT_LINE_CHARS ? `${s.slice(0, COMPACT_LINE_CHARS - 1)}…` : s;
}

function compactBody(action: ActionSpec, values: Values, preview: Preview | null, argv: string[], repo?: string): string {
	const lines: string[] = [];
	if (repo && preview) lines.push(clipLine(`リポジトリ: ${sanitizeForDisplay(repo)}`));
	const meta = Object.entries(action.fields).filter(([n, s]) => !s.content && values[n] !== undefined);
	if (meta.length > 0) lines.push(clipLine(`対象: ${meta.map(([n]) => `${n}=${sanitizeForDisplay(values[n])}`).join(" / ")}`));
	const contentFields = Object.entries(action.fields).filter(([n, s]) => s.content && values[n] !== undefined);
	for (const [n] of contentFields) {
		lines.push(`${n}:`, ...sanitizeForDisplay(compactText(values[n])).split("\n").map((l) => `  ${clipLine(l)}`));
	}
	if (preview) {
		const head = /^[0-9a-f]{40,64}$/.test(preview.head) ? preview.head.slice(0, 8) : preview.head;
		lines.push(clipLine(`ブランチ ${sanitizeForDisplay(preview.branch)} / HEAD ${head}`), "ステージ済み:");
		lines.push(...sanitizeForDisplay(compactStat(preview.stat)).split("\n").map((l) => `  ${clipLine(l)}`));
	}
	// content の値を含む argv の要素は、本文の重複を出さないように <名前> へ置き換える (実際に実行する配列は変えない)
	lines.push(`argv: ${argvLine(argv, values, contentFields.map(([n]) => n))}`);
	return lines.join("\n");
}

/** content の値を含む argv の要素は、本文の重複を出さないように <名前> へ置き換える (実際に実行する配列は変えない) */
function argvLine(argv: string[], values: Values, contentNames: string[]): string {
	const shown = argv.map((a) => {
		for (const n of contentNames) if (values[n] !== "" && a.includes(values[n])) return a.split(values[n]).join(`<${n}>`);
		return a;
	});
	const text = JSON.stringify(shown);
	return sanitizeForDisplay(text.length > COMPACT_ARGV_CHARS ? `${text.slice(0, COMPACT_ARGV_CHARS)}…` : text);
}

// 詳細をチャット (ツールの途中経過) へ出せたときの承認ダイアログは、要点も繰り返さず、上の詳細を指す 1 文だけにする (利用者の決定)。
// 対象のリポジトリ・ブランチ・本文・ファイル・argv や退避の注意は、詳細 (viewBody) にある。全文は「編集して承認」のエディタでも見られる。
const CONFIRM_PROMPT = "上記の内容で実行しますか";
const PROGRESS_FLUSH_MS = 300;

function compactText(text: string): string {
	const all = text.split("\n");
	let out = all.slice(0, COMPACT_TEXT_LINES).join("\n");
	if (out.length > COMPACT_TEXT_CHARS) out = out.slice(0, COMPACT_TEXT_CHARS);
	if (out.length < text.length) out += `\n… (全 ${all.length} 行・${text.length} 字のうち先頭だけ。「${EDIT}」で全文)`;
	return out;
}

/** git diff --stat の行を、ファイルの先頭数件と要約の行に絞る */
function compactStat(stat: string, max = COMPACT_STAT_FILES): string {
	const lines = stat.split("\n");
	const hasSummary = /\bchanged\b/.test(lines[lines.length - 1] ?? "");
	const files = hasSummary ? lines.slice(0, -1) : lines;
	if (files.length <= max) return stat;
	return [...files.slice(0, max), `… 他 ${files.length - max} ファイル`, ...(hasSummary ? [lines[lines.length - 1]] : [])].join("\n");
}

type ExecResult = { code: number | string; stdout: string; stderr: string; killed: boolean };

function runArgv(argv: string[], cwd: string, env: NodeJS.ProcessEnv, signal?: AbortSignal): Promise<ExecResult> {
	return new Promise((resolve) => {
		execFile(argv[0], argv.slice(1), { cwd, env: repoTargetEnv(env), encoding: "utf8", timeout: EXEC_TIMEOUT_MS, maxBuffer: 16 * 1024 * 1024, signal }, (err: any, stdout: any, stderr: any) => {
			const code = err ? (typeof err.code === "number" || typeof err.code === "string" ? err.code : 1) : 0;
			resolve({ code, stdout: String(stdout ?? ""), stderr: String(stderr ?? ""), killed: err?.killed === true });
		});
	});
}

/** guarded_action の execute() の本体。エラーは throw (isError)。承認 1 回につき実行 1 回 */
export async function executeAction(deps: ActionDeps, params: any, signal: AbortSignal | undefined, ctx: any): Promise<{ content: { type: "text"; text: string }[]; details: Record<string, unknown> }> {
	if (deps.child) throw notApproved("子エージェントは guarded_action を使えない");
	const why = deps.judge(params, ctx.cwd);
	if (why) throw new Error(`実行前の判定で止めた: ${why}`);
	const checked = validateCall(deps.actions, params);
	if (!checked.ok) throw new Error(checked.error);
	const { action } = checked;
	let values = checked.values;
	let cwd: string = ctx.cwd;
	let resolvedParams: any = params; // dir を解決したあとの判定用の入力 (解決済みの対象を指す)
	const zoneSettings = freeZoneSettings(deps.rules);

	const fileFields = Object.entries(action.fields).filter(([, s]) => s.type === "text" && s.file === true);
	const dir = mkdtempSync(join(tmpdir(), "pi-action-")); // 0700
	try {
		const files: Record<string, string> = {};
		for (const [name] of fileFields) files[name] = join(dir, `${name}.txt`);
		// dir (任意): cwd 配下の別の git リポジトリで実行する。プレビュー・退避・実行はすべてそのリポジトリを見る
		if ("dir" in action.fields) {
			cwd = await resolveRepoDir(ctx.cwd, values.dir);
			// 解決済みの対象に対しても判定を通す (元の dir を評価したあとでリンクが変わっていても、実行する場所を判定する)
			resolvedParams = { ...params, params: { ...params.params, dir: relativeDir(ctx.cwd, cwd) } };
			const why2 = deps.judge(resolvedParams, ctx.cwd);
			if (why2) throw new Error(`実行前の判定で止めた: ${why2}`);
		}
		const previewFn = PREVIEWS[action.preview];
		if (!previewFn) throw new Error(`未対応の preview: ${action.preview}`);
		// 退避の対象は git_commit だけ。表示の前に tree を確定し、あとから実のインデックスを読み直さない
		const snap: Snapshot | null = action.id === "git_commit" ? snapshotStaged(cwd, String(values.message ?? ""), randomUUID()) : null;
		const preview = await previewFn(cwd, values);
		if (preview && preview.stat === "") throw new Error("ステージ済みの変更が無い。git add してから呼ぶ");
		// 表示する状態は snapshot と同じでなければならない (取った間に変わったら、表示せずにやり直す)
		if (snap && preview && (snap.baseHeadOid !== (/^[0-9a-f]{40,64}$/.test(preview.head) ? preview.head : "") || snap.indexId !== preview.indexId)) {
			throw new Error("状態が変わった (HEAD・ステージ済みの内容)。もう一度 guarded_action を呼ぶ");
		}
		// 自由区 (feature の linked worktree) の git_commit は、設定が真のときだけ確認を省略する。偽の間も判定は行い、結果に添えて観測する
		const zone: FreeZone | null = action.id === "git_commit" ? (deps.freeZone ?? ((c, r) => classifyFreeZone(c, r, { env: deps.env })))(cwd, zoneSettings.protectedRefs) : null;
		const skipConfirm = zone?.free === true && zoneSettings.skip;
		// 確認の流れ (UI の確認・時間切れの退避・編集)。確認を省略するときは通らない
		const confirmFlow = async (): Promise<{ values: Values; edited: boolean }> => {
			if (!ctx.hasUI) {
				if (snap) throw deferError(cwd, snap, "確認できない実行なので承認が取れなかった", signal, values.dir);
				throw notApproved("確認できない実行 (print・子) では、確認が要る操作は拒否する。利用者が `pis` の対話で実行する");
			}
			const absence = deps.absence ?? { absent: false, gen: 0 };

			const timeoutMs = confirmTimeoutSeconds(deps.rules) * 1000;
			const minutes = timeoutMs >= 60_000 ? `${Math.round(timeoutMs / 60_000)} 分` : `${Math.round(timeoutMs / 1000)} 秒`;
			const notice =
				action.id !== "git_commit"
					? ""
					: snap
						? `\n\n(${minutes}応答が無ければ、実行せず内容を退避して作業を続けます。編集・拒否理由の入力中は対象外)`
						: `\n\n(退避できない状態なので、${minutes}応答が無ければ拒否します)`;
			const viewArgv = buildArgv(action, values, files);
			// RPC (TUI 以外): 詳細 (対象のリポジトリ・ブランチ・本文全文・対象ファイル・argv) をチャット (ツールの途中経過) に出し、承認ダイアログは「上記の内容で実行しますか」だけにする。
			// 途中経過を出せないときは、詳細を見せずに承認させないよう、スマホ向けに縮めた表示をダイアログに出す
			let title: string;
			const summarize = ctx.mode === "tui" && needsSummary(action, values, preview);
			const columns = Number(process.stdout?.columns) > 0 ? Number(process.stdout.columns) : COMPACT_LINE_CHARS;
			if (summarize) {
				// 要約では、狭い画面で選択肢を押し出さないよう、注意書きも 1 行に縮める
				const shortNotice = snap ? `\n(${minutes}無応答なら実行せず退避)` : `\n(退避不可。${minutes}無応答なら拒否)`;
				title = `${action.label}\n\n${summaryBody(action, values, preview!, cwd, columns, mainRepoName(cwd, deps.env))}${action.id === "git_commit" ? shortNotice : ""}`;
				// 詳細 (本文全文・argv など) をチャット (ツールの途中経過) にも出す。TUI で描かれるかは未確認なので、ダイアログの要約は残す (見ずに承認することはない)
				if (deps.progress?.(`${action.label}\n\n${viewBody(action, values, preview, viewArgv, cwd)}${notice}`)) await new Promise((r) => setTimeout(r, PROGRESS_FLUSH_MS));
			} else if (ctx.mode === "tui") {
				title = `${action.label}\n\n${viewBody(action, values, preview, viewArgv, cwd)}${notice}`;
			} else if (deps.progress?.(`${action.label}\n\n${viewBody(action, values, preview, viewArgv, cwd)}${notice}`)) {
				// 途中経過のイベントは pi が非同期に流すので、ダイアログの要求より後に出ることがある。「上記」を先に見せるため、少し待つ
				await new Promise((r) => setTimeout(r, PROGRESS_FLUSH_MS));
				title = `${action.label}\n${CONFIRM_PROMPT}`;
			} else {
				title = `${action.label}\n${compactBody(action, values, preview, viewArgv, cwd)}${notice}`;
			}
			const decision = await deps.dialog(async () => {
				if (signal?.aborted) return { kind: "aborted" as const };
				// 不在 (先の確認が時間切れで、そのあと利用者の入力が無い) なら、待たずに退避する
				if (snap && absence.absent) return { kind: "absent" as const };
				deps.bell();
				const gen0 = absence.gen;
				const options = summarize ? [APPROVE, VIEW_FULL, EDIT, REJECT] : [APPROVE, EDIT, REJECT];
				let timedOut = false;
				let choice: string | undefined;
				let error = false;
				// 「全文を見る」で select を押し直す。期限は select ごとに仕切り直す (editor には無い)
				for (;;) {
					const own = new AbortController();
					const forward = () => own.abort();
					if (signal?.aborted) own.abort();
					else signal?.addEventListener("abort", forward, { once: true });
					const timer = setTimeout(() => {
						timedOut = true;
						own.abort();
					}, timeoutMs);
					try {
						choice = await ctx.ui.select(title, options, { signal: own.signal, timeout: timeoutMs + BACKSTOP_MS });
					} catch {
						error = true;
					} finally {
						clearTimeout(timer);
						signal?.removeEventListener("abort", forward);
					}
					if (choice !== VIEW_FULL || signal?.aborted) break;
					try {
						// 読むだけ (変更しても反映されない)。先頭から表示するビューアで開き (pi の editor は末尾にカーソルを置くので末尾から見える)、閉じると確認に戻る
						const fullTitle = `${action.label}: 全文 (読むだけ。閉じると確認に戻る)`;
						const fullText = `${viewBody(action, values, preview, viewArgv, cwd)}${notice}`;
						if (typeof ctx.ui.custom === "function") await showTextViewer(ctx.ui as any, fullTitle, fullText);
						else await ctx.ui.editor(fullTitle, fullText);
					} catch {
						// 表示できなくても、確認に戻る
					}
				}
				if (choice === REJECT) {
					let reason: string | undefined;
					try {
						reason = await ctx.ui.input("拒否の理由 (任意。空でもよい)", "", { signal });
					} catch {
						// 理由は任意
					}
					return { kind: "denied" as const, reason: (reason ?? "").trim() };
				}
				// 時間切れは、自前のタイマーが発火したときだけ (取消・呼び出し元の中断・例外とは区別する)。選択が返っていれば承認を優先する
				const outcome = choice === APPROVE || choice === EDIT ? "approved" : signal?.aborted ? "aborted" : timedOut ? "timeout" : error ? "error" : "denied";
				if (outcome === "timeout" && absence.gen === gen0) absence.absent = true;
				if (outcome !== "approved") return { kind: "outcome" as const, outcome };
				if (choice !== EDIT) return { kind: "approved" as const, values, edited: false };
				const edited: Values = { ...values };
				for (const [name, s] of Object.entries(action.fields)) {
					if (!(s.type === "text" || s.type === "line") || !s.content) continue;
					const text = await ctx.ui.editor(`${action.label}: ${name} を編集`, values[name]);
					if (typeof text !== "string" || text.trim() === "") return { kind: "empty" as const };
					// 1 行の項目は、エディタが足す末尾の改行を落とす (途中の改行は再検証で拒否)
					edited[name] = s.type === "line" ? text.replace(/[\r\n]+$/, "") : text;
				}
				return { kind: "approved" as const, values: edited, edited: true };
			});
			if (decision.kind === "aborted") throw notApproved(outcomeReason("aborted"));
			if (decision.kind === "absent") throw deferError(cwd, snap!, "利用者が不在のため確認せずに退避した (先の確認が時間切れ)", signal, values.dir);
			if (decision.kind === "outcome") {
				if (decision.outcome === "timeout" && snap) throw deferError(cwd, snap, `確認が ${minutes}の時間切れになった`, signal, values.dir);
				throw notApproved(outcomeReason(decision.outcome));
			}
			if (decision.kind === "empty") throw notApproved("編集の結果が空、または取り消されたので拒否した");
			if (decision.kind === "denied") {
				throw notApproved(`${outcomeReason("denied")}${decision.reason ? `。利用者の理由: ${decision.reason}` : ""}`);
			}
			values = decision.values;
			// 編集後の内容も、型・長さ・NUL の検証をやり直す
			const recheck = validateCall(deps.actions, { action: action.id, params: values });
			if (!recheck.ok) throw notApproved(`編集後の内容が不正: ${recheck.error}`);
			return { values, edited: decision.edited };
		};
		const approved = skipConfirm ? { values, edited: false } : await confirmFlow();
		values = approved.values;

		// 実行の直前に、承認した状態のままか照合する
		const now = await previewFn(cwd, values);
		if (!samePreview(preview, now)) throw new Error("状態が変わった (HEAD・ブランチ・ステージ済みの内容)。もう一度 guarded_action を呼ぶ");
		// 確認を省略したときは、実行直前にも自由区かを判定し直す (なくなっていれば未実行)
		if (skipConfirm) {
			const again = (deps.freeZone ?? ((c, r) => classifyFreeZone(c, r, { env: deps.env })))(cwd, zoneSettings.protectedRefs);
			if (!again.free) throw new Error(`自由区ではなくなった (${again.reason})。確認を省略せず、実行しなかった。もう一度 guarded_action を呼ぶ`);
		}
		// 承認の間に dir の指す先が変わっていないか (リンクの差し替え。包含・最上位も検査し直す)。ここで確かめるのは「うっかり」の範囲で、最後の syscall 直前の差し替えまでは防げない
		if (values.dir && (await resolveRepoDir(ctx.cwd, values.dir)) !== cwd) throw new Error("dir の指す先が承認の間に変わった。もう一度 guarded_action を呼ぶ");
		// 承認の間に状態が変わっていないか。判定をもう一度通す。dir は解決済みの対象を見る
		const after = deps.judge(resolvedParams, ctx.cwd);
		if (after) throw new Error(`実行直前の判定で止めた: ${after}`);

		// 承認した内容 (編集した場合は編集後) を書く。承認後に再読みしない
		for (const [name] of fileFields) writeFileSync(files[name], values[name], { flag: "wx", mode: 0o600 });
		const argv = buildArgv(action, values, files);
		const r = await runArgv(argv, cwd, deps.env, signal);
		const out = deps.redact(tail(r.stdout.trim()));
		const err = deps.redact(tail(r.stderr.trim()));
		if (r.code !== 0) {
			const head = r.killed ? `${EXEC_TIMEOUT_MS / 1000} 秒で時間切れ` : `終了コード ${r.code}`;
			throw new Error([`${argv[0]} が失敗した (${head})`, out && `stdout:\n${out}`, err && `stderr:\n${err}`].filter(Boolean).join("\n"));
		}
		const used = Object.entries(action.fields)
			.filter(([, s]) => s.content)
			.map(([n]) => `${n}:\n${values[n]}`);
		// コミットできたら、取り込み済み・重複・古い退避を片付ける (失敗してもコミットの結果には影響させない)
		if (action.id === "git_commit") {
			try {
				reconcilePending(cwd);
			} catch {}
		}
		// 確認を省略した結果は「承認した内容のとおり」と表示しない。省略の理由と、実行後の HEAD を返す。偏の間は自由区の判定を添えて観測する
		const headNow = skipConfirm ? gitSync(["rev-parse", "--short", "HEAD"], cwd, { env: deps.env }) : null;
		const closing = approved.edited
			? `実際に使った最終の内容 (編集した):\n${used.join("\n\n")}`
			: skipConfirm
				? `確認なしで実行した (自由区: ${zone?.branch ?? ""}。実行後の HEAD: ${headNow?.ok ? headNow.stdout.trim() : "不明"})`
				: "実行した内容は、承認した内容のとおり";
		const shadow = zone && !skipConfirm ? `自由区の判定 (観測中。確認は省略していない): ${zone.free ? "free" : "not free"} (${zone.reason}${zone.branch ? `: ${zone.branch}` : ""})` : "";
		const text = [out || "(標準出力なし)", err && `stderr:\n${err}`, closing, shadow].filter(Boolean).join("\n\n");
		const details: Record<string, unknown> = { action: action.id };
		if (zone) details.freeZone = { free: zone.free, reason: zone.reason, branch: zone.branch, skipped: skipConfirm };
		return { content: [{ type: "text", text }], details };
	} finally {
		rmSync(dir, { recursive: true, force: true });
	}
}
