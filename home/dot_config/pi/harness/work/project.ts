// 作業台帳の投影 (読み取り専用の純関数): ready の取り出し・利用者待ちの一覧・予算の状況・次に要る判断。仕様: docs/spec/work/ledger.md
import { globsMayOverlap } from "./globs.ts";
import { isTaskLike, MONEY_KEYS, rootGoalId } from "./reduce.ts";
import type { LedgerState } from "./reduce.ts";
import type { Money, Node } from "./types.ts";

const ACTIVE = ["running", "waiting", "checking"];
const TERMINAL = ["done", "cancelled", "skipped"];

/** 依存が満たされているとみなす状態 (skipped は when が偽で飛ばしたものなので、後続を止めない) */
const satisfied = (n: Node | undefined): boolean => n?.state === "done" || n?.state === "skipped";

const estMs = (n: Node): number => {
	const e = n.attrs.estimateMs;
	return typeof e === "number" && e > 0 ? e : 1;
};
const estUsd = (n: Node): number => {
	const e = n.attrs.estUsd;
	return typeof e === "number" ? e : (n.budget?.usd ?? 0);
};

/** 臨界路の長さ: 自分の見積り + 後続 (自分を after に持つ未完了の task) の臨界路の最大。DAG 前提 (循環は I1 が拒否する) */
export const criticalPaths = (state: LedgerState, estimateMs: (n: Node) => number = estMs): Map<string, number> => {
	const dependents = new Map<string, string[]>();
	for (const n of state.nodes.values()) {
		if (!isTaskLike(n) || TERMINAL.includes(n.state)) continue;
		for (const a of n.after) dependents.set(a, [...(dependents.get(a) ?? []), n.id]);
	}
	const memo = new Map<string, number>();
	const visiting = new Set<string>();
	const f = (id: string): number => {
		const hit = memo.get(id);
		if (hit !== undefined) return hit;
		const n = state.nodes.get(id);
		if (!n || visiting.has(id)) return 0;
		visiting.add(id);
		let best = 0;
		for (const d of dependents.get(id) ?? []) best = Math.max(best, f(d));
		visiting.delete(id);
		const v = estimateMs(n) + best;
		memo.set(id, v);
		return v;
	};
	for (const n of state.nodes.values()) if (isTaskLike(n)) f(n.id);
	return memo;
};

export interface ReadyOptions {
	/** 返す件数の上限 (空き枠) */
	limit?: number;
	/** 今流している bundle の名前。attrs.bundle がこれに等しい task を優先する */
	bundle?: string;
	/** 臨界路の見積り (ms)。省略時は attrs.estimateMs (無ければ 1)。adapt.ts がスケジューラと同じ見積りを渡す */
	estimateMs?: (node: Node) => number;
}

/**
 * 今すぐ起動できる task を優先順位で返す。条件: goal が active・状態が ready・after が全部 done (skipped を含む)・
 * 実行中の task および先に選んだ task と writes が重ならない。順序: ①臨界路の長さの降順 ②bundle を満たすもの ③費用の昇順 ④id。
 */
export const ready = (state: LedgerState, opts: ReadyOptions = {}): Node[] => {
	const crit = criticalPaths(state, opts.estimateMs);
	const active = [...state.nodes.values()].filter((n) => (n.kind === "task" || n.kind === "integrate") && ACTIVE.includes(n.state));
	const cands = [...state.nodes.values()].filter((n) => {
		if (!isTaskLike(n) || n.state !== "ready") return false;
		const g = rootGoalId(state.nodes, n.id);
		if (!g || state.nodes.get(g)?.state !== "active") return false;
		return n.after.every((a) => satisfied(state.nodes.get(a)));
	});
	const inBundle = (n: Node): number => (opts.bundle !== undefined && n.attrs.bundle === opts.bundle ? 1 : 0);
	const cmpId = (a: Node, b: Node) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0);
	cands.sort((a, b) => (crit.get(b.id) ?? 0) - (crit.get(a.id) ?? 0) || inBundle(b) - inBundle(a) || estUsd(a) - estUsd(b) || cmpId(a, b));
	const picked: Node[] = [];
	const held = [...active];
	for (const n of cands) {
		if (opts.limit !== undefined && picked.length >= opts.limit) break;
		// check は親の writes を継ぐので、ここでは衝突を見ない
		if (n.kind !== "check" && held.some((o) => n.writes.some((w) => o.writes.some((x) => globsMayOverlap(w, x))))) continue;
		picked.push(n);
		if (n.kind !== "check") held.push(n);
	}
	return picked;
};

export interface UserWait {
	/** plan = 計画の承認待ち、blocked = 利用者へ回った task、wait = user 待ち */
	kind: "plan" | "blocked" | "wait";
	node: string;
	goal?: string;
	ref?: string;
	since?: number;
	/** 利用者へ出す 1 行 */
	prompt: string;
}

/** 利用者待ちの一覧。順序: 計画の承認 → blocked の task → user 待ち (古い順)。先頭が「次に要る判断」 */
export const waitingUser = (state: LedgerState): UserWait[] => {
	const plans: UserWait[] = [];
	const blocked: UserWait[] = [];
	const waits: UserWait[] = [];
	for (const n of state.nodes.values()) {
		const goal = rootGoalId(state.nodes, n.id);
		if (n.kind === "goal" && n.state === "planned") plans.push({ kind: "plan", node: n.id, goal: n.id, prompt: `計画の承認: ${n.title}` });
		if (isTaskLike(n) && n.state === "blocked") {
			blocked.push({ kind: "blocked", node: n.id, ...(goal ? { goal } : {}), prompt: `止まっている: ${n.title}` });
		}
		if (TERMINAL.includes(n.state)) continue;
		for (const w of n.waits) {
			if (w.on !== "user") continue;
			waits.push({ kind: "wait", node: n.id, ...(goal ? { goal } : {}), ref: w.ref, since: w.since, prompt: w.prompt ?? n.title });
		}
	}
	const byId = (a: UserWait, b: UserWait) => (a.node < b.node ? -1 : a.node > b.node ? 1 : 0);
	waits.sort((a, b) => (a.since ?? 0) - (b.since ?? 0) || byId(a, b));
	return [...plans.sort(byId), ...blocked.sort(byId), ...waits];
};

export const nextDecision = (state: LedgerState): UserWait | null => waitingUser(state)[0] ?? null;

export interface BudgetLine {
	/** null = 上限なし */
	budget: number | null;
	spent: number;
	reserved: number;
	/** budget − reserved (上限なしは null) */
	remaining: number | null;
	/** ok・warn (予約が 80% 以上)・over (予約か使用が上限を超えた) */
	level: "ok" | "warn" | "over";
}
export type BudgetStatus = Record<keyof Money, BudgetLine>;

export const budgetStatus = (node: Node): BudgetStatus => {
	const out = {} as BudgetStatus;
	for (const k of MONEY_KEYS) {
		const budget = node.budget ? node.budget[k] : null;
		const spent = node.spent[k];
		const reserved = node.reserved[k];
		let level: BudgetLine["level"] = "ok";
		if (budget !== null) {
			if (reserved > budget || spent > budget) level = "over";
			else if (budget > 0 && reserved >= budget * 0.8) level = "warn";
		}
		out[k] = { budget, spent, reserved, remaining: budget === null ? null : budget - reserved, level };
	}
	return out;
};
