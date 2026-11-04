// 台帳の射影 (LedgerState) と、スケジューラ・digest の入力の間のアダプタ。純関数 (fs・pi の API・時計なし)。
// 各 feature は別々に作られたので、この境界の食い違いはここで吸収する。see docs/spec/work/ledger.md#接続と統合試験
import { aimdInit, DEFAULT_AIMD } from "./aimd.ts";
import type { ProviderState } from "./aimd.ts";
import type { DigestInput } from "./digest.ts";
import { isTaskLike, rootGoalId } from "./reduce.ts";
import type { LedgerState } from "./reduce.ts";
import { ready } from "./project.ts";
import { addMoney, durationP50, historyKey, ZERO } from "./reserve.ts";
import type { Budget, Size } from "./reserve.ts";
import type { Resources, SchedRun, SchedState, SchedTask } from "./sched.ts";
import { emptyStats } from "./strategy.ts";
import type { Stats } from "./strategy.ts";
import type { Digest, Money, Node } from "./types.ts";

export interface AdaptOptions {
	now: number;
	resources: Resources;
	/** 履歴 (省略時は完了した run の使用量から導く) */
	history?: Record<string, Money[]>;
	/** 予算 (省略時は active な goal の予算) */
	budget?: Budget;
	provider?: ProviderState;
	stats?: Stats;
}

const SIZES: readonly string[] = ["S", "M", "L"];
const DIGEST_STATUS: readonly string[] = ["done", "failed", "blocked", "limit", "aborted", "lost"];
const FAILED_RUN: readonly string[] = ["failed", "aborted", "lost"];

const str = (v: unknown, dflt: string): string => (typeof v === "string" && v.length > 0 ? v : dflt);
const num = (v: unknown): number | undefined => (typeof v === "number" && Number.isFinite(v) ? v : undefined);

const roleOf = (n: Node): string => str(n.attrs.role, "worker");
const sizeOf = (n: Node): Size => (SIZES.includes(n.attrs.size as string) ? (n.attrs.size as Size) : "M");

/** 台帳の task を SchedTask にする。種類 (ro/edit/check) は attrs.kind、無ければ check か writes の有無から決める */
const taskOf = (n: Node, failures: number): SchedTask => {
	const k = n.attrs.kind;
	const kind: SchedTask["kind"] = k === "ro" || k === "edit" || k === "check" ? k : n.kind === "check" ? "check" : n.writes.length > 0 ? "edit" : "ro";
	const t: SchedTask = {
		id: n.id,
		state: n.state as SchedTask["state"],
		kind,
		role: roleOf(n),
		size: sizeOf(n),
		writes: [...n.writes],
		after: [...n.after],
		failures,
	};
	if (n.attrs.risk === "boundary" || n.attrs.risk === "none") t.risk = n.attrs.risk;
	if (typeof n.attrs.group === "string") t.group = n.attrs.group;
	if (n.attrs.uncertain === true) t.uncertain = true;
	if (n.attrs.accept === true) t.accept = true;
	if (typeof n.attrs.contract === "string") t.contract = n.attrs.contract;
	if (n.attrs.pipeline === true) t.pipeline = true;
	const ms = num(n.attrs.estimateMs);
	if (ms !== undefined) t.estMs = ms;
	const usd = num(n.attrs.estUsd);
	if (usd !== undefined) t.costUsd = usd;
	return t;
};

/** 完了した run の使用量から導いた履歴 (役割:大きさ)。active な goal の run だけ */
const historyOf = (state: LedgerState): Record<string, Money[]> => {
	const history: Record<string, Money[]> = {};
	for (const r of state.nodes.values()) {
		if (r.kind !== "run" || r.parent === undefined || r.state !== "done") continue;
		const g = rootGoalId(state.nodes, r.id);
		if (g === undefined || state.nodes.get(g)?.state !== "active") continue;
		const t = state.nodes.get(r.parent);
		if (t) (history[historyKey(roleOf(t), sizeOf(t))] ??= []).push({ ...r.spent });
	}
	return history;
};

/**
 * project.ready をスケジューラと同じ見積り (attrs.estimateMs、無ければ役割×大きさの p50) で呼ぶ。
 * ready の順序と sched の start の順序の出所を一つにする。
 */
export function readyOf(state: LedgerState, opts: { limit?: number; bundle?: string; history?: Record<string, Money[]> } = {}): Node[] {
	const history = opts.history ?? historyOf(state);
	const estimateMs = (n: Node): number => num(n.attrs.estimateMs) ?? durationP50(roleOf(n), sizeOf(n), history);
	return ready(state, { limit: opts.limit, bundle: opts.bundle, estimateMs });
}

/**
 * 台帳の投影からスケジューラの入力を作る。対象は active な goal の task と run だけ (project.ready と同じ範囲)。
 * 履歴は完了した run の使用量 (役割:大きさ)、used は全 run の spent の合計。
 */
export function schedStateOf(state: LedgerState, opts: AdaptOptions): SchedState {
	const nodes = [...state.nodes.values()];
	const active = (n: Node): boolean => {
		const g = rootGoalId(state.nodes, n.id);
		return g !== undefined && state.nodes.get(g)?.state === "active";
	};
	const runs = nodes.filter((n) => n.kind === "run" && n.parent !== undefined && active(n));
	const failures = new Map<string, number>();
	const history: Record<string, Money[]> = {};
	let used: Money = { ...ZERO };
	for (const r of runs) {
		used = addMoney(used, r.spent);
		const t = state.nodes.get(r.parent as string);
		if (!t) continue;
		if (FAILED_RUN.includes(r.state)) failures.set(t.id, (failures.get(t.id) ?? 0) + 1);
		if (r.state === "done") (history[historyKey(roleOf(t), sizeOf(t))] ??= []).push({ ...r.spent });
	}
	const tasks = nodes.filter((n) => isTaskLike(n) && active(n)).map((n) => taskOf(n, failures.get(n.id) ?? 0));
	const schedRuns: SchedRun[] = runs.map((r) => {
		const o: SchedRun = {
			id: r.id,
			task: r.parent as string,
			state: r.state as SchedRun["state"],
			reserve: { ...r.reserved },
			spent: { ...r.spent },
		};
		const last = num(r.attrs.lastOutputAt);
		if (last !== undefined) o.lastOutputAt = last;
		if (typeof r.attrs.strategy === "string") o.strategy = r.attrs.strategy as SchedRun["strategy"];
		const sp = r.attrs.speculative as { contract?: unknown; rev?: unknown } | undefined;
		if (sp && typeof sp.contract === "string" && typeof sp.rev === "number") o.speculative = { contract: sp.contract, rev: sp.rev };
		return o;
	});
	const goal = nodes.find((n) => n.kind === "goal" && n.state === "active" && n.budget !== undefined);
	const budget = opts.budget ?? (goal?.budget ? { ...goal.budget } : undefined);
	const s: SchedState = {
		tasks,
		runs: schedRuns,
		used,
		history: opts.history ?? history,
		stats: opts.stats ?? emptyStats(),
		provider: opts.provider ?? aimdInit({ ...DEFAULT_AIMD, initial: Math.min(opts.resources.slots, DEFAULT_AIMD.max) }),
	};
	if (budget) s.budget = budget;
	return s;
}

/** 終わった run から digest の入力を作る。生きた run・run でないノード・状態が digest にできない run は null */
export function digestInputOf(state: LedgerState, runId: string): DigestInput | null {
	const r = state.nodes.get(runId);
	if (!r || r.kind !== "run" || !DIGEST_STATUS.includes(r.state)) return null;
	const t = r.parent !== undefined ? state.nodes.get(r.parent) : undefined;
	if (!t) return null;
	// 子の最終メッセージ: run に付いた注釈 (by が run:<id>) の連結。無ければ空 (digest が形式違反の警告を足す)
	const text = r.notes.map((x) => x.text).join("\n");
	const out: DigestInput = {
		id: r.id,
		node: t.id,
		role: roleOf(t),
		title: t.title,
		status: r.state as Digest["status"],
		dur: r.spent.ms,
		usd: r.spent.usd,
		text,
		resultPath: `runs/${r.id}.md`,
	};
	if (t.evidence.length > 0) out.evidencePaths = [...t.evidence];
	return out;
}
