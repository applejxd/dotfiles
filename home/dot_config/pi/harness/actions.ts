// guarded_action: 承認つきで、表 (rules.json の judge.common.pi.actions) に宣言した操作 (git commit・gh issue comment) を実行する。
// 承認はこのツールが 1 回だけ取り、承認した argv をシェル無しでそのまま実行する。see docs/change/0038-guard-reclassification.md
//
// node の型除去でそのまま動く書き方だけを使う (enum・namespace は使わない)。

import { execFile } from "node:child_process";
import { createHash } from "node:crypto";
import { randomUUID } from "node:crypto";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { MAX_DISPLAY_CHARS, confirmTimeoutSeconds, outcomeReason, sanitizeForDisplay } from "./confirm-view.ts";
import { reconcilePending, savePendingSnapshot, snapshotStaged, type Snapshot } from "./pending-store.ts";
import { validateFeatureName } from "./gitflow.ts";
import { gitflowCommitPreview, gitflowDiscardPreview, gitflowFinishPreview, gitflowStartPreview, isFeatureWorktreeCommit, leftoverWorktreeHint, resolveFeatureWorktree, type ReadDenyLike } from "./gitflow-ops.ts";

export const ACTION_TOOL = "action";
const NOT_APPROVED = "not approved:";
const REPO_RE = /^[A-Za-z0-9][A-Za-z0-9_.-]*\/[A-Za-z0-9_.-]+$/;
const INT_MAX = 1_000_000_000;
const EXEC_TIMEOUT_MS = 120_000;
const OUTPUT_TAIL_CHARS = 8000;
const STAT_MAX_CHARS = 4000;

export type FieldSpec = { type: "repo" | "int" | "line" | "text" | "featurename"; file?: boolean; content?: boolean; max_chars?: number };
export type ActionSpec = {
	id: string;
	label: string;
	argv: string[];
	fields: Record<string, FieldSpec>;
	replaces: string[];
	preview: "none" | "git_staged" | "gitflow_start" | "gitflow_finish" | "gitflow_commit" | "gitflow_discard";
	/** 確認の省略。コードの許可リスト (AUTO_CONFIRM) にある操作だけ。既定は確認する */
	confirm?: "ask" | "gitflow_start" | "gitflow_wip";
};

/** 確認なしで実行してよい操作。設定ではなくコードで決める (名前の型だけを引数に持ち、実効設定の検査を通った git flow の起票だけ) */
const AUTO_CONFIRM = new Set(["gitflow_feature_start", "gitflow_feature_commit"]);

/** rules.judge.common.pi.actions (配列)。無い・形が違う項目は捨てる (生成器が起動前に検証している) */
export function loadActions(rules: any): ActionSpec[] {
	const raw = rules?.judge?.common?.pi?.actions;
	if (!Array.isArray(raw)) return [];
	return raw.filter((a: any) => a && typeof a.id === "string" && Array.isArray(a.argv) && a.fields && typeof a.fields === "object");
}

/** `gh_issue_comment(repo, number, body)  issue にコメントを投稿` */
export function actionLine(a: ActionSpec): string {
	return `${a.id}(${Object.keys(a.fields).join(", ")})  ${a.label}`;
}

export function actionDescription(actions: ActionSpec[]): string {
	return [
		"投稿・コミットは、このツールで行う。承認はこのツールが 1 回だけ取る。事前にチャットや ask で承認を取らない。",
		"引数: {action: 操作の ID, params: その操作の引数 (全て必須)}。操作:",
		...actions.map(actionLine),
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
		if (v === undefined || v === null) {
			errors.push(`params.${name}: 必須 (${spec.type})`);
			continue;
		}
		if (spec.type === "repo") {
			if (typeof v !== "string" || !REPO_RE.test(v)) errors.push(`params.${name}: owner/name の形の文字列 (受け取った値: ${JSON.stringify(v)})`);
			else values[name] = v;
		} else if (spec.type === "int") {
			const n = typeof v === "number" ? v : typeof v === "string" && /^[0-9]+$/.test(v) ? Number(v) : NaN;
			if (!Number.isInteger(n) || n < 1 || n > INT_MAX) errors.push(`params.${name}: 1〜${INT_MAX} の整数 (受け取った値: ${JSON.stringify(v)})`);
			else values[name] = String(n);
		} else if (spec.type === "featurename") {
			const bad = validateFeatureName(v);
			if (bad) errors.push(`params.${name}: ${bad}`);
			else values[name] = v as string;
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
		execFile(file, args, { cwd, encoding: opts.buffer ? "buffer" : "utf8", maxBuffer: 64 * 1024 * 1024, signal: opts.signal, timeout: 30_000 }, (err: any, stdout: any, stderr: any) => {
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
	gitflow_start: async (cwd, values) => gitflowStartPreview(cwd, values),
	gitflow_finish: async (cwd, values) => gitflowFinishPreview(cwd, values),
	gitflow_discard: async (cwd, values) => gitflowDiscardPreview(cwd, values),
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
	/** 保護対象のパスの一覧 (gitflow_feature_commit が、まとめてステージする前に検査する) */
	readDeny?: () => ReadDenyLike;
	/** 利用者が不在と分かった状態 (確認が時間切れ)。セッションごと。入力の世代 gen は、利用者の入力のたびに進む (index.ts) */
	absence?: { absent: boolean; gen: number };
};

/** TUI の組み込みの期限は、自前の期限より遅くして、保険にだけ使う (自前の期限で時間切れを判定する) */
const BACKSTOP_MS = 3000;

/** 退避して続行する結果 (deferred) または、退避できなかった結果 (defer_failed)。どちらも元の操作は未実行 */
function deferError(cwd: string, snap: Snapshot, why: string, signal: AbortSignal | undefined): Error {
	if (signal?.aborted) return notApproved(outcomeReason("aborted"));
	const saved = savePendingSnapshot(cwd, snap);
	if (!saved.ok) {
		return notApproved(
			`${why}。元の操作は未実行で、内容も退避できなかった (${saved.reason})。再試行しない。この操作に依存しない作業を続け、最後に「保留したコミット」の再作成が要ると報告する`,
		);
	}
	return notApproved(
		`${why}。元の操作は未実行。内容は ${saved.ref} (${saved.short}) に退避した。再試行しない。この操作に依存しない作業を続け、最後に「保留したコミット」として報告する (利用者は /pending で確認・破棄できる)`,
	);
}

const APPROVE = "承認して実行";
const EDIT = "編集して承認";
const REJECT = "拒否";

function notApproved(why: string): Error {
	return new Error(`${NOT_APPROVED} ${why}`);
}

function viewBody(action: ActionSpec, values: Values, preview: Preview | null, argv: string[]): string {
	const lines: string[] = [];
	const meta = Object.entries(action.fields).filter(([n, s]) => !s.content && values[n] !== undefined);
	if (meta.length > 0) lines.push("対象:", ...meta.map(([n]) => `  ${n}: ${sanitizeForDisplay(values[n])}`), "");
	for (const [n, s] of Object.entries(action.fields)) {
		if (s.content) lines.push(`${n} (全文):`, sanitizeForDisplay(values[n]), "");
	}
	if (preview) {
		lines.push("プレビュー:", `  ブランチ: ${sanitizeForDisplay(preview.branch)}`, `  HEAD: ${preview.head}`, "  ステージ済み:");
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

function compactBody(action: ActionSpec, values: Values, preview: Preview | null, argv: string[]): string {
	const lines: string[] = [];
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

// 詳細をチャット (ツールの途中経過) に出し、承認ダイアログは要点だけにするときのダイアログ。
// 対象・本文の 1 行目・ファイルの先頭数件と要約・argv だけ。詳細は上の出力で、全文は「編集して承認」で見る。
const SUMMARY_STAT_FILES = 3;

function summaryBody(action: ActionSpec, values: Values, preview: Preview | null, argv: string[]): string {
	const lines: string[] = [];
	const meta = Object.entries(action.fields).filter(([n, s]) => !s.content && values[n] !== undefined);
	if (meta.length > 0) lines.push(clipLine(`対象: ${meta.map(([n]) => `${n}=${sanitizeForDisplay(values[n])}`).join(" / ")}`));
	const contentFields = Object.entries(action.fields).filter(([n, s]) => s.content && values[n] !== undefined);
	for (const [n] of contentFields) {
		const all = values[n].split("\n");
		lines.push(clipLine(`${n}: ${sanitizeForDisplay(all[0])}${all.length > 1 ? ` (全 ${all.length} 行)` : ""}`));
	}
	if (preview) {
		const head = /^[0-9a-f]{40,64}$/.test(preview.head) ? preview.head.slice(0, 8) : preview.head;
		lines.push(clipLine(`ブランチ ${sanitizeForDisplay(preview.branch)} / HEAD ${head}`));
		lines.push(...sanitizeForDisplay(compactStat(preview.stat, SUMMARY_STAT_FILES)).split("\n").map((l) => `  ${clipLine(l)}`));
	}
	lines.push(`argv: ${argvLine(argv, values, contentFields.map(([n]) => n))}`);
	lines.push(`詳細は上のツール出力。全文は「${EDIT}」で見られます`);
	return lines.join("\n");
}

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
		execFile(argv[0], argv.slice(1), { cwd, env, encoding: "utf8", timeout: EXEC_TIMEOUT_MS, maxBuffer: 16 * 1024 * 1024, signal }, (err: any, stdout: any, stderr: any) => {
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

	const fileFields = Object.entries(action.fields).filter(([, s]) => s.type === "text" && s.file === true);
	const dir = mkdtempSync(join(tmpdir(), "pi-action-")); // 0700
	try {
		const files: Record<string, string> = {};
		for (const [name] of fileFields) files[name] = join(dir, `${name}.txt`);
		// WIP コミットは、feature の worktree の中で行う (cwd をその worktree にする。検査は resolveFeatureWorktree と preview)
		if (action.preview === "gitflow_commit") cwd = resolveFeatureWorktree(cwd, values.name);
		const previewFn =
			action.preview === "gitflow_commit"
				? async (c: string, v: Values) => gitflowCommitPreview(c, v, deps.readDeny ? deps.readDeny() : null)
				: PREVIEWS[action.preview];
		if (!previewFn) throw new Error(`未対応の preview: ${action.preview}`);
		// 退避の対象は git_commit だけ。表示の前に tree を確定し、あとから実のインデックスを読み直さない
		const snap: Snapshot | null = action.id === "git_commit" ? snapshotStaged(cwd, String(values.message ?? ""), randomUUID()) : null;
		const preview = await previewFn(cwd, values);
		if (preview && preview.stat === "") throw new Error("ステージ済みの変更が無い。git add してから呼ぶ");
		// 表示する状態は snapshot と同じでなければならない (取った間に変わったら、表示せずにやり直す)
		if (snap && preview && (snap.baseHeadOid !== (/^[0-9a-f]{40,64}$/.test(preview.head) ? preview.head : "") || snap.indexId !== preview.indexId)) {
			throw new Error("状態が変わった (HEAD・ステージ済みの内容)。もう一度 guarded_action を呼ぶ");
		}
		// 確認の省略は、コードの許可リストにある操作だけ (子の拒否・判定器・型検証・実効設定の検査は、すでに通っている)
		// feature の worktree の中の WIP コミットも省略する (条件: gitflow-ops.ts の isFeatureWorktreeCommit)。squash の確認 (finish) で、最終の内容を見る
		const wip = action.id === "git_commit" && isFeatureWorktreeCommit(cwd);
		const auto = wip || ((action.confirm === "gitflow_start" || action.confirm === "gitflow_wip") && AUTO_CONFIRM.has(action.id));
		if (!auto && !ctx.hasUI) {
			if (snap) throw deferError(cwd, snap, "確認できない実行なので承認が取れなかった", signal);
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
		// RPC (TUI 以外): 詳細をチャット (ツールの途中経過) に出し、承認ダイアログは要点だけにする。
		// 途中経過を出せないときは、詳細を見せずに承認させないよう、スマホ向けに縮めた表示をダイアログに出す
		let title: string;
		if (ctx.mode === "tui") {
			title = `${action.label}\n\n${viewBody(action, values, preview, viewArgv)}${notice}`;
		} else if (!auto && deps.progress?.(`${action.label}\n\n${viewBody(action, values, preview, viewArgv)}`)) {
			title = `${action.label}\n${summaryBody(action, values, preview, viewArgv)}${notice}`;
		} else {
			title = `${action.label}\n${compactBody(action, values, preview, viewArgv)}${notice}`;
		}
		const decision = auto ? ({ kind: "approved" as const, values }) : await deps.dialog(async () => {
			if (signal?.aborted) return { kind: "aborted" as const };
			// 不在 (先の確認が時間切れで、そのあと利用者の入力が無い) なら、待たずに退避する
			if (snap && absence.absent) return { kind: "absent" as const };
			deps.bell();
			const gen0 = absence.gen;
			const own = new AbortController();
			let timedOut = false;
			const forward = () => own.abort();
			if (signal?.aborted) own.abort();
			else signal?.addEventListener("abort", forward, { once: true });
			const timer = setTimeout(() => {
				timedOut = true;
				own.abort();
			}, timeoutMs);
			let choice: string | undefined;
			let error = false;
			try {
				choice = await ctx.ui.select(title, [APPROVE, EDIT, REJECT], { signal: own.signal, timeout: timeoutMs + BACKSTOP_MS });
			} catch {
				error = true;
			} finally {
				clearTimeout(timer);
				signal?.removeEventListener("abort", forward);
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
			if (choice !== EDIT) return { kind: "approved" as const, values };
			const edited: Values = { ...values };
			for (const [name, s] of Object.entries(action.fields)) {
				if (!(s.type === "text" || s.type === "line") || !s.content) continue;
				const text = await ctx.ui.editor(`${action.label}: ${name} を編集`, values[name]);
				if (typeof text !== "string" || text.trim() === "") return { kind: "empty" as const };
				// 1 行の項目は、エディタが足す末尾の改行を落とす (途中の改行は再検証で拒否)
				edited[name] = s.type === "line" ? text.replace(/[\r\n]+$/, "") : text;
			}
			return { kind: "approved" as const, values: edited };
		});
		if (decision.kind === "aborted") throw notApproved(outcomeReason("aborted"));
		if (decision.kind === "absent") throw deferError(cwd, snap!, "利用者が不在のため確認せずに退避した (先の確認が時間切れ)", signal);
		if (decision.kind === "outcome") {
			if (decision.outcome === "timeout" && snap) throw deferError(cwd, snap, `確認が ${minutes}の時間切れになった`, signal);
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

		// 実行の直前に、承認した状態のままか照合する
		const now = await previewFn(cwd, values);
		if (!samePreview(preview, now)) throw new Error("状態が変わった (HEAD・ブランチ・ステージ済みの内容)。もう一度 guarded_action を呼ぶ");
		// 承認の間にブランチが develop / main に変わっていないか。判定をもう一度通す (gitflow 規約の強制。CHG-0049)
		const after = deps.judge(params, ctx.cwd);
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
		const hint = action.id === "gitflow_feature_finish" ? leftoverWorktreeHint(cwd, values.name) : null;
		const autoNote = auto ? (wip ? "確認なしで実行した (feature の worktree の WIP コミット。最終の内容は finish の確認で見る)" : `確認なしで実行した (${action.id}。対象: ${preview?.stat ?? ""})`) : "";
		const text = [out || "(標準出力なし)", err && `stderr:\n${err}`, autoNote, hint, `実際に使った最終の内容:\n${used.join("\n\n")}`].filter(Boolean).join("\n\n");
		return { content: [{ type: "text", text }], details: { action: action.id, auto } };
	} finally {
		rmSync(dir, { recursive: true, force: true });
	}
}
