// `/worktrees` の本体と、起動時の取り残しの照合。依存は worktree.ts だけ (node の型除去でそのまま読める)。
// 起動時に自動で変えるのは古いロックの解除だけ (worktree・ref・記録は消さない)。秘密の値・ファイルの内容は出さず、パスと job id と状態だけを出す。
// 仕様は docs/change/0029-worktree-isolation.md の「W1 の実装計画」(S3 の段 5・S4)。
import { existsSync, lstatSync, realpathSync } from "node:fs";
import type { Stats } from "node:fs";
import { basename, dirname, join, relative, resolve } from "node:path";
import {
	Budget,
	DEFAULT_LIMITS,
	WorktreeError,
	clearStaleLock,
	collect,
	discard,
	listRecords,
	readRecord,
	reconcile,
	runGit,
	validateJobId,
	worktreePath,
} from "./worktree.ts";
import type { IsolationRecord, Limits, ReadDeny, ReconcileIssue } from "./worktree.ts";

/** 起動時の照合の時間の上限 (ms)。起動を待たせすぎない。値は推測 */
export const STARTUP_TOTAL_MS = 5000;
/** 起動時の git 呼び出しの上限 (根の探索と照合で共通) */
export const STARTUP_LIMITS: Limits = { ...DEFAULT_LIMITS, gitTimeoutMs: 3000, totalMs: STARTUP_TOTAL_MS };

export type WorktreesDeps = {
	/** git リポジトリの根。リポジトリでなければ null */
	repoRoot: string | null;
	/** いま親が持っている job の id (子が生きている job への collect・discard を拒否する) */
	liveJobIds: string[];
	readDeny: () => ReadDeny;
	/** 利用者に確認する。UI が無ければ null */
	confirm: ((title: string, body: string) => Promise<boolean>) | null;
	limits?: Limits;
};

export type CommandResult = { level: "info" | "warning"; text: string };

const USAGE = "使い方: /worktrees [show <jobId> | collect <jobId> | discard <jobId> | unlock]";
const REF_PREFIX = "refs/pi-agent/";

const oneLine = (v: unknown, max = 200): string => String(v ?? "").replace(/[\r\n\t]+/g, " ").slice(0, max);

function describeError(e: unknown): string {
	if (e instanceof WorktreeError) {
		const cause = typeof e.detail.cause === "string" ? ` (${oneLine(e.detail.cause)})` : "";
		return `${e.code}: ${oneLine(e.message)}${cause}`;
	}
	return oneLine(e instanceof Error ? e.message : e);
}

/** リポジトリの根 (realpath)。git リポジトリでなければ null。起動失敗などは例外のまま (呼び出し側が扱う) */
export function findRepoRoot(cwd: string, limits?: Limits): string | null {
	const top = runGit(["rev-parse", "--show-toplevel"], limits ? { cwd, limits, budget: new Budget(limits.totalMs) } : { cwd });
	if (top.status !== 0) return null;
	return realpathSync(String(top.stdout).trim());
}

/**
 * 起動を遅くしないための事前確認 (git を呼ばない)。cwd から上へ最初の `.git` を探し、
 * それがディレクトリ (主たる作業ツリー。子の worktree やサブモジュールは `.git` がファイル) で、
 * 記録の置き場か worktree の置き場があるときだけ、その根を返す。
 */
export function isolationTraceRoot(cwd: string): string | null {
	let dir = resolve(cwd);
	for (;;) {
		let st: Stats | null = null;
		try {
			st = lstatSync(join(dir, ".git"));
		} catch {
			st = null;
		}
		if (st) {
			if (!st.isDirectory()) return null;
			return existsSync(join(dir, ".tmp", "subagents", "worktrees")) || existsSync(join(dir, ".tmp", "worktrees")) ? dir : null;
		}
		const up = dirname(dir);
		if (up === dir) return null;
		dir = up;
	}
}

function issueText(i: ReconcileIssue, root: string): string {
	const d = i.detail;
	const rel = (p: unknown): string => (typeof p === "string" ? oneLine(relative(root, p) || p, 120) : "?");
	switch (i.issue) {
		case "record_only":
			return `記録だけが残っている (worktree も ref も無い。状態 ${oneLine(d.state, 20)})`;
		case "worktree_only":
			return `worktree だけがある (記録が無い。自動では扱わない): ${rel(d.worktree)}`;
		case "ref_only":
			return `ref だけがある (worktree が無い。${d.hasRecord ? `状態 ${oneLine(d.state, 20)}` : "記録なし"})`;
		case "patch_missing":
			return `patch が見つからない (状態 ${oneLine(d.state, 20)})`;
		case "stuck_running":
			return `状態 ${oneLine(d.state, 20)} のまま (子は動いていない。作成 ${oneLine(d.createdAt, 40)})`;
		case "stuck_creating":
			return `作成の途中で止まっている (作成 ${oneLine(d.createdAt, 40)})`;
		default:
			return "食い違い";
	}
}

/**
 * 起動時の照合。食い違いがあれば 1 つの警告文を返す (無ければ null)。何も消さない・直さない。
 * 例外は投げない (失敗は 1 行の警告文にする)。古いロックの解除だけは行う (pid が死んでいて古いときに限る)。
 */
export function startupReconcile(repoRoot: string, liveJobIds: string[], limits: Limits = STARTUP_LIMITS): string | null {
	const lines: string[] = [];
	try {
		const lock = clearStaleLock(repoRoot);
		if (lock.cleared) lines.push("古いロック (死んだ pid・60 秒以上前) を 1 つ解除した (worktree・ref・記録は消していない)");
		const broken = listRecords(repoRoot).filter((r): r is { broken: true; file: string } => "broken" in r);
		const issues = reconcile(repoRoot, liveJobIds, limits);
		for (const b of broken) lines.push(`- 壊れた記録: ${oneLine(relative(repoRoot, b.file), 120)}`);
		for (const i of issues) lines.push(`- ${i.jobId} ${i.issue}: ${issueText(i, repoRoot)}`);
		const count = broken.length + issues.length;
		if (count > 0) {
			lines.unshift(`隔離 (worktree) の取り残しが ${count} 件ある (自動では worktree・ref・記録を消していない)`);
			lines.push("/worktrees で一覧・回収のやり直し (collect)・破棄 (discard) ができる");
		}
	} catch (e) {
		lines.push(e instanceof WorktreeError && e.code === "timeout" ? "隔離の取り残しの照合を時間切れで省略した" : `隔離の取り残しの照合に失敗した: ${describeError(e)}`);
	}
	return lines.length > 0 ? lines.join("\n") : null;
}

function listRefIds(root: string, limits: Limits): Set<string> {
	const r = runGit(["for-each-ref", "--format=%(refname)", REF_PREFIX], { cwd: root, budget: new Budget(limits.totalMs), limits });
	const out = new Set<string>();
	if (r.status !== 0) return out;
	for (const line of String(r.stdout).split("\n")) {
		const t = line.trim();
		if (t.startsWith(REF_PREFIX)) out.add(t.slice(REF_PREFIX.length));
	}
	return out;
}

function listText(root: string, live: string[], limits: Limits): CommandResult {
	const recs = listRecords(root);
	const refs = listRefIds(root, limits);
	const issues = reconcile(root, live, limits);
	const lines: string[] = [];
	if (recs.length === 0) lines.push("記録はありません");
	else {
		lines.push("job id | 状態 | 作成 | worktree | ref | patch | note");
		for (const r of recs) {
			if ("broken" in r) {
				lines.push(`(壊れた記録) ${oneLine(basename(r.file), 80)}`);
				continue;
			}
			const hasWt = existsSync(worktreePath(root, r.jobId));
			const hasPatch = r.patch !== undefined && existsSync(r.patch.path);
			lines.push(
				[r.jobId, r.state, oneLine(r.createdAt, 40), hasWt ? "あり" : "なし", refs.has(r.jobId) ? "あり" : "なし", hasPatch ? "あり" : "なし", r.note ? oneLine(r.note) : "-"].join(" | "),
			);
		}
	}
	if (issues.length > 0) {
		lines.push("", `食い違い ${issues.length} 件:`);
		for (const i of issues) lines.push(`- ${i.jobId} ${i.issue}: ${issueText(i, root)}`);
	}
	return { level: "info", text: lines.join("\n") };
}

function showText(root: string, id: string, live: string[], limits: Limits): CommandResult {
	const rec = readRecord(root, id);
	if (!rec) return { level: "warning", text: `記録がありません: ${id}` };
	const refs = listRefIds(root, limits);
	const lines = [
		`job: ${rec.jobId}${live.includes(id) ? " (子が動いている)" : ""}`,
		`状態: ${rec.state}`,
		`作成: ${oneLine(rec.createdAt, 40)}`,
		`リポジトリ: ${oneLine(rec.repo, 300)}`,
		`worktree: ${oneLine(rec.worktree, 300)} (${existsSync(worktreePath(root, id)) ? "あり" : "なし"})`,
		`起点の commit: ${oneLine(rec.startCommit, 70)}`,
		`スナップショットの commit: ${oneLine(rec.snapshotCommit, 70)}`,
		`結果の commit: ${rec.resultCommit ? oneLine(rec.resultCommit, 70) : "-"}`,
		`ref: ${rec.ref ? oneLine(rec.ref, 120) : "-"} (${refs.has(id) ? "あり" : "なし"})`,
		`patch: ${rec.patch ? `${oneLine(rec.patch.path, 300)} (${existsSync(rec.patch.path) ? "あり" : "なし"}) sha256 ${oneLine(rec.patch.sha256, 70)}` : "-"}`,
		`note: ${rec.note ? oneLine(rec.note, 1000) : "-"}`,
	];
	for (const i of reconcile(root, live, limits)) if (i.jobId === id) lines.push(`食い違い: ${i.issue}: ${issueText(i, root)}`);
	return { level: "info", text: lines.join("\n") };
}

async function collectText(root: string, id: string, deps: WorktreesDeps, limits: Limits): Promise<CommandResult> {
	const warn = (text: string): CommandResult => ({ level: "warning", text });
	if (deps.liveJobIds.includes(id)) return warn(`${id}: 子が動いているので回収しない (終了を待つ)`);
	const rec = readRecord(root, id);
	if (!rec) return warn(`記録がありません: ${id}`);
	if (rec.state === "collected") return warn(`${id}: 回収済み。取り込みは patch を使う。不要なら /worktrees discard ${id}`);
	if (rec.state === "creating") return warn(`${id}: 作成の途中。回収できない (古ければ /worktrees discard ${id})`);
	// kept も確認する: 停止を確認できずに kept になった子が残りうる (このプロセスの job しか分からない)
	if (!deps.confirm) return warn(`${id}: 状態 ${rec.state}。別のセッションで動いているかもしれないので、確認できない環境では回収しない`);
	const unconfirmed = typeof rec.note === "string" && /終了を確認できない|not confirmed stopped/.test(rec.note);
	const body = [
		`${id} は状態 ${rec.state} です。`,
		rec.note ? `note: ${oneLine(rec.note, 300)}` : "",
		unconfirmed ? "停止を確認できていません。作業中の worktree を回収すると、子の変更が失われるおそれがあります。" : "",
		"子のプロセスが停止していることを確認しましたか。別の pi プロセスの子は、この画面から見えません。",
	]
		.filter((l) => l !== "")
		.join("\n");
	const ok = await deps.confirm("回収をやり直しますか？", body);
	if (ok !== true) return warn("中止した");
	const readDeny = deps.readDeny();
	if (readDeny.globs.length === 0) return warn("collect refused: no_read_deny_rules: read_deny_globs がありません");
	try {
		const res = collect(root, id, `${id}.patch`, readDeny, limits);
		if (!res.changed) return { level: "info", text: `unchanged: 変更なし (worktree と記録を削除した)` };
		const patch = relative(root, res.patch.path);
		const warnings = res.warnings.length > 0 ? `\nwarnings: ${res.warnings.map((w) => oneLine(w)).join(", ")}` : "";
		return { level: "info", text: `collected: ref ${res.ref}\npatch ${patch}\napply: git apply ${patch}${warnings}` };
	} catch (e) {
		return warn(`failed: ${describeError(e)}\n/worktrees show ${id} で note を確認し、原因を直して再実行する`);
	}
}

async function discardText(root: string, id: string, deps: WorktreesDeps, limits: Limits): Promise<CommandResult> {
	const warn = (text: string): CommandResult => ({ level: "warning", text });
	if (deps.liveJobIds.includes(id)) return warn(`${id}: 子が動いているので破棄しない (終了を待つ)`);
	if (!deps.confirm) return warn("確認を取れない環境 (UI が無い) では破棄しない");
	const rec: IsolationRecord | null = readRecord(root, id);
	if (!rec) return warn(`記録がありません: ${id} (記録のない worktree・ref には触らない)`);
	const body = [
		`${id} (状態 ${rec.state}) の worktree・ref・patch を消します。`,
		rec.state === "running" || rec.state === "collecting" ? "状態が実行中のままです。別のセッションで動いていないか確かめてください。" : "",
		"記録と照合できないものは消さずに残します。",
	]
		.filter((l) => l !== "")
		.join("\n");
	const ok = await deps.confirm("worktree を破棄しますか？", body);
	if (ok !== true) return warn("中止した (何も消していない)");
	try {
		const { notes } = discard(root, id, limits);
		const kept = notes.some((n) => /kept/.test(n));
		return { level: kept ? "warning" : "info", text: notes.length > 0 ? `discard: ${notes.map((n) => oneLine(n)).join("\n")}` : "破棄した" };
	} catch (e) {
		return warn(`failed: ${describeError(e)}`);
	}
}

function unlockText(root: string): CommandResult {
	const r = clearStaleLock(root);
	switch (r.reason) {
		case "stale":
			return { level: "info", text: "古いロックを解除した" };
		case "no_lock":
			return { level: "info", text: "ロックはない" };
		case "fresh":
			return { level: "warning", text: "ロックは古くない (60 秒以内に更新されている) ので消さない" };
		case "pid_alive":
			return { level: "warning", text: "ロックの持ち主のプロセスが生きているので消さない" };
		default:
			return { level: "warning", text: `ロックは消さない (${oneLine(r.reason, 40)})` };
	}
}

/** `/worktrees` の本体。例外は投げない。jobId は validateJobId に通してからでないと使わない */
export async function runWorktreesCommand(args: string, deps: WorktreesDeps): Promise<CommandResult> {
	const usage: CommandResult = { level: "warning", text: USAGE };
	const root = deps.repoRoot;
	if (root === null) return { level: "warning", text: "git リポジトリではない" };
	const limits = deps.limits ?? DEFAULT_LIMITS;
	const words = String(args ?? "").trim().split(/\s+/).filter((w) => w !== "");
	const sub = words[0] ?? "";
	try {
		if (sub === "") return listText(root, deps.liveJobIds, limits);
		if (sub === "unlock") return words.length === 1 ? unlockText(root) : usage;
		if ((sub === "show" || sub === "collect" || sub === "discard") && words.length === 2) {
			let id: string;
			try {
				id = validateJobId(words[1]);
			} catch {
				return usage;
			}
			if (sub === "show") return showText(root, id, deps.liveJobIds, limits);
			if (sub === "collect") return await collectText(root, id, deps, limits);
			return await discardText(root, id, deps, limits);
		}
		return usage;
	} catch (e) {
		return { level: "warning", text: `/worktrees ${sub} に失敗した: ${describeError(e)}` };
	}
}
