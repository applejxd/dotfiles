// 盤面 (board.ts) の入力を、読み取り専用の git で集める部品。pi に依存しない。例外は投げない (取れない項目は省く)。
// git は worktree.ts の runGit だけを使う (hook・外部 diff・fsmonitor を無効にした読み取り向け)。自前の spawn は足さない。
// 書き込み系の git は使わない。status は GIT_OPTIONAL_LOCKS=0 で、index を更新させない。
import { parseWorktreePorcelain, type BoardInput, type ChildRow, type ParsedWorktree, type PendingRow, type WorktreeState } from "./board.ts";
import { listRecords, runGit } from "./worktree.ts";
import { listOps, readAttemptAt, readOp, DEFAULT_LIMITS } from "./pending-ops.ts";
import { ownerState } from "./pending-owner.ts";
import { recordOfChain } from "./pending-approve.ts";
import { loadProfile } from "./integrate-profile-load.ts";
import { DEFAULT_SOURCE_PREFIXES, type ProfileDefaults, type ProfileResult } from "./judge/integrateprofile.ts";

export type CollectDeps = {
	now: number;
	children: ChildRow[];
	modes: BoardInput["modes"];
	/** 統合先 (既定 develop) */
	target?: string;
	/** 状態を調べる feature の最大数 (既定 12) */
	maxFeatures?: number;
	/** 全体の既定。渡すと、cwd の HEAD の pi.json から統合元の接頭辞を決める */
	profileDefaults?: ProfileDefaults;
};

const MAX_PENDING_ROWS = 50;
const READ_ENV = { GIT_OPTIONAL_LOCKS: "0" };

/** 失敗・タイムアウト・起動失敗は null (例外にしない) */
function gitOut(args: string[], cwd: string): string | null {
	try {
		const r = runGit(args, { cwd, env: READ_ENV });
		return r.status === 0 ? String(r.stdout) : null;
	} catch {
		return null;
	}
}

function worktreeState(path: string, target: string, now: number, readStatus: boolean): WorktreeState {
	const st: WorktreeState = {};
	const counts = gitOut(["rev-list", "--left-right", "--count", `${target}...HEAD`], path);
	const m = counts === null ? null : /^(\d+)\s+(\d+)\s*$/.exec(counts);
	if (m) {
		st.behind = Number(m[1]);
		st.ahead = Number(m[2]);
	}
	// status は、内容の比較で外部 filter (clean/smudge/process) を起動しうる。設定があるときは調べない (false と言い切らず、項目ごと省く)
	const status = readStatus ? gitOut(["status", "--porcelain"], path) : null;
	if (status !== null) st.dirty = status.trim() !== "";
	const ct = gitOut(["log", "-1", "--format=%ct"], path);
	const sec = ct === null ? NaN : Number(ct.trim());
	if (Number.isFinite(sec) && sec > 0) st.lastCommitAgeMs = Math.max(0, now - sec * 1000);
	return st;
}

/** 外部 filter の設定があるか。読めない・失敗は「ある」と見なす (status を実行しない側へ倒す) */
function hasExternalFilter(cwd: string): boolean {
	try {
		const r = runGit(["config", "--get-regexp", "^filter\\..*\\.(clean|smudge|process)$"], { cwd, env: READ_ENV });
		if (r.status === 1) return false; // 一致なし
		if (r.status === 0) return String(r.stdout).trim() !== "";
		return true;
	} catch {
		return true;
	}
}

function collectPending(cwd: string, now: number): { ops: PendingRow[]; legacyCount: number; broken: number } {
	const out = { ops: [] as PendingRow[], legacyCount: 0, broken: 0 };
	try {
		const { entries } = listOps(cwd);
		for (const e of entries) {
			if (e.state === "done") continue; // 決着済みは盤面に出さない
			const ageMs = e.committedAt > 0 ? Math.max(0, now - e.committedAt * 1000) : undefined;
			if (e.kind === "legacy") {
				out.legacyCount++;
				continue;
			}
			if (e.state === "pending") {
				if (e.kind !== "action") {
					out.broken++;
					continue;
				}
				const r = readOp(cwd, e.id);
				if (!r.ok) {
					out.broken++;
					continue;
				}
				const row: PendingRow = { id: e.id, state: "pending", action: r.record.action, ...(ageMs !== undefined ? { ageMs } : {}) };
				if (r.record.params?.source) row.source = r.record.params.source;
				if (out.ops.length < MAX_PENDING_ROWS) out.ops.push(row);
				continue;
			}
			// running: 実行者の生死は /pending list と同じ (試行の owner を ownerState で見る)
			const a = readAttemptAt(cwd, e.id, e.oid);
			if (!a.ok) {
				out.broken++;
				continue;
			}
			const action = recordOfChain(cwd, e.id, e.oid, DEFAULT_LIMITS)?.action;
			const row: PendingRow = { id: e.id, state: "running", owner: { state: ownerState(a.attempt.owner).state }, ...(ageMs !== undefined ? { ageMs } : {}) };
			if (action) row.action = action;
			if (out.ops.length < MAX_PENDING_ROWS) out.ops.push(row);
		}
	} catch {
		// 取れなかった保留は、空として扱う
	}
	return out;
}

/** pi.json の状態の 1 行。有効で既定と違うときと無効のときだけ (設定が無ければ何も出さない)。診断は固定のコードだけ */
function noteOf(r: ProfileResult): string | undefined {
	if (r.diagnostics.length > 0) return `pi.json: 無効 (${r.diagnostics.slice(0, 3).map((d) => d.code).join(",")})`;
	if (r.profile.source === "project" && r.overridden) return `pi.json: 有効 (統合元 ${r.profile.sourcePrefixes.join(" ")})`;
	return undefined;
}

export function collectBoardInput(cwd: string, deps: CollectDeps): BoardInput {
	const loaded = deps.profileDefaults ? loadProfile(cwd, deps.profileDefaults) : undefined;
	// 比較先は実効の統合先 (設定を読んだときは、無い・無効でも loaded.profile.target = 全体の既定か pi.json の値)。表示と判定は同じ値を使う
	const target = loaded ? loaded.profile.target : (deps.target ?? "develop");
	const projectPrefixes = loaded && loaded.profile.source === "project" ? loaded.profile.sourcePrefixes : undefined;
	const sourcePrefixes: readonly string[] = projectPrefixes ?? DEFAULT_SOURCE_PREFIXES;
	const profileNote = loaded ? noteOf(loaded) : undefined;
	const maxFeatures = Math.max(0, Math.floor(deps.maxFeatures ?? 12));
	let worktrees: ParsedWorktree[] = [];
	const listed = gitOut(["worktree", "list", "--porcelain"], cwd);
	if (listed !== null) worktrees = parseWorktreePorcelain(listed, projectPrefixes);

	const pending = collectPending(cwd, deps.now);
	const sources = new Set(pending.ops.filter((p) => p.state === "pending" && p.source).map((p) => p.source as string));

	const readStatus = !hasExternalFilter(cwd);
	const worktreeStates: Record<string, WorktreeState> = {};
	let n = 0;
	worktrees.forEach((w, i) => {
		if (i === 0 || n >= maxFeatures || w.bare || w.prunable || !w.branch) return;
		if (!sourcePrefixes.some((p) => w.branch!.startsWith(p))) return;
		n++;
		const st = worktreeState(w.path, target, deps.now, readStatus);
		const short = w.branch.slice(w.branch.indexOf("/") + 1);
		if (sources.has(w.branch) || sources.has(short)) st.hasPending = true;
		worktreeStates[w.path] = st;
	});

	let isolation: BoardInput["isolation"] = [];
	try {
		isolation = listRecords(worktrees[0]?.path ?? cwd);
	} catch {
		isolation = [];
	}

	return { now: deps.now, children: deps.children ?? [], isolation, worktrees, pending, modes: deps.modes ?? {}, worktreeStates, ...(profileNote ? { profileNote } : {}) };
}
