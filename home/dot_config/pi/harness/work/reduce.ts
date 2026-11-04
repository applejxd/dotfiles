// 作業台帳の reducer。reduce(state, event) → state は純関数 (入力の state を変更しない・決定的)。fold(events) で全体を畳み込む。
// 遷移の可否は transitions.ts の表が決め、ここは副作用 (予算・依存・待ち・証拠・lease) と前提条件 (門) を実装する。
// 前提条件を満たさないイベントは例外 (ReduceError / TransitionError)。aux のイベントは seq だけ進める。仕様: docs/spec/work/ledger.md
import { isAux, validateEvent, ZERO } from "./events.ts";
import type { WaitKind } from "./events.ts";
import { globsMayOverlap } from "./globs.ts";
import { initialTaskState, next, tkindOf, variantOf } from "./transitions.ts";
import type { Facts } from "./transitions.ts";
import type { LedgerEvent, Lease, Money, Node } from "./types.ts";

export class ReduceError extends Error {
	constructor(message: string) {
		super(message);
		this.name = "ReduceError";
	}
}

export interface Rejection {
	seq: number;
	from: string;
	to: string;
	reason: string;
}
export interface Anomaly {
	seq: number;
	inv: string;
	message: string;
}
/** 解除された待ちの記録 (I5 の検査用) */
export interface Resolution {
	seq: number;
	node: string;
	ref: string;
	on: WaitKind;
	by: WaitKind;
	source: string;
}

export interface LedgerState {
	/** 最後に畳んだ seq */
	seq: number;
	nodes: ReadonlyMap<string, Node>;
	/** goal の id (作成順) */
	goals: readonly string[];
	rejections: readonly Rejection[];
	/** 拒否せず受け入れたが不変条件に触れるもの (seq の欠番など) */
	anomalies: readonly Anomaly[];
	resolutions: readonly Resolution[];
}

export const emptyState = (): LedgerState => ({ seq: 0, nodes: new Map(), goals: [], rejections: [], anomalies: [], resolutions: [] });

// ── 共通の小道具 ──
export const MONEY_KEYS = ["usd", "tokens", "ms"] as const;
export const zero = (): Money => ({ ...ZERO });
export const isTaskLike = (n: Node): boolean => n.kind === "task" || n.kind === "check" || n.kind === "integrate";
export const isLiveRun = (n: Node): boolean => n.kind === "run" && (n.state === "reserved" || n.state === "started");

export const chainOf = (nodes: ReadonlyMap<string, Node>, id: string): string[] => {
	const out: string[] = [];
	const seen = new Set<string>();
	let cur: string | undefined = id;
	while (cur !== undefined && !seen.has(cur)) {
		seen.add(cur);
		out.push(cur);
		cur = nodes.get(cur)?.parent;
	}
	return out;
};

export const rootGoalId = (nodes: ReadonlyMap<string, Node>, id: string): string | undefined => {
	const c = chainOf(nodes, id);
	const top = nodes.get(c[c.length - 1]);
	return top?.kind === "goal" ? top.id : undefined;
};

export const childrenOf = (state: LedgerState, id: string): Node[] => [...state.nodes.values()].filter((n) => n.parent === id);

/** from.after をたどって target に着けるか (from から見て target が推移的な依存か) */
export const dependsOn = (nodes: ReadonlyMap<string, Node>, from: string, target: string): boolean => {
	const seen = new Set<string>();
	const stack = [from];
	while (stack.length > 0) {
		const id = stack.pop() as string;
		if (id === target) return true;
		if (seen.has(id)) continue;
		seen.add(id);
		for (const a of nodes.get(id)?.after ?? []) stack.push(a);
	}
	return false;
};

/** from に to への依存を足すと循環になるか (自己依存・任意の長さの鎖を含む) */
export const wouldCycle = (state: LedgerState, from: string, to: string): boolean => from === to || dependsOn(state.nodes, to, from);

/**
 * 追記する前の変換: edge.added が循環を作るなら edge.rejected に差し替える (store が追記前に通す)。
 * reducer も循環の edge.added を適用せず rejection に記録するので、通さなくても状態は壊れない。
 */
export const resolveEdge = <E extends { type: string; node?: string; data: Record<string, unknown> }>(state: LedgerState, ev: E): E => {
	if (ev.type !== "edge.added") return ev;
	const { from, to } = ev.data as { from: string; to: string };
	if (!wouldCycle(state, from, to)) return ev;
	return { ...ev, type: "edge.rejected", data: { from, to, reason: "cycle" } };
};

const addTo = (a: Money, b: Money, sign = 1): void => {
	for (const k of MONEY_KEYS) a[k] += sign * b[k];
};

// ── 作業用の下書き (入力の state は変えず、触るノードだけ複製する) ──
class Draft {
	nodes: Map<string, Node>;
	goals: string[];
	rejections: Rejection[];
	anomalies: Anomaly[];
	resolutions: Resolution[];
	seq: number;
	private cloned = new Set<string>();

	constructor(s: LedgerState) {
		this.nodes = new Map(s.nodes);
		this.goals = [...s.goals];
		this.rejections = [...s.rejections];
		this.anomalies = [...s.anomalies];
		this.resolutions = [...s.resolutions];
		this.seq = s.seq;
	}

	view(): LedgerState {
		const { seq, nodes, goals, rejections, anomalies, resolutions } = this;
		return { seq, nodes, goals, rejections, anomalies, resolutions };
	}
	need(id: string, what = "ノード"): Node {
		const n = this.nodes.get(id);
		if (!n) throw new ReduceError(`${what} ${id} が無い`);
		return n;
	}
	edit(id: string): Node {
		const n = this.need(id);
		if (this.cloned.has(id)) return n;
		const c = structuredClone(n);
		this.nodes.set(id, c);
		this.cloned.add(id);
		return c;
	}
	create(n: Node): void {
		if (this.nodes.has(n.id)) throw new ReduceError(`ノード ${n.id} は既にある`);
		this.nodes.set(n.id, n);
		this.cloned.add(n.id);
	}
	goalOf(id: string): Node {
		const g = rootGoalId(this.nodes, id);
		if (!g) throw new ReduceError(`${id} の goal が無い`);
		return this.need(g);
	}
	/** goal ノードだけを受け付ける (種類の取り違えを拒否) */
	goalNode(id: string): Node {
		const n = this.need(id);
		if (n.kind !== "goal") throw new ReduceError(`${id} は goal でない (${n.kind})`);
		return n;
	}
	hasLiveRun(id: string): boolean {
		for (const n of this.nodes.values()) if (n.parent === id && isLiveRun(n)) return true;
		return false;
	}
	/** 使用量を run → task → goal へ合算する。見積りを超えた分は予約も同じだけ増やす (使用した事実は取り消せない。超過は I3 が検出) */
	charge(runId: string, usage: Money): void {
		const run = this.need(runId);
		const excess = zero();
		for (const k of MONEY_KEYS) excess[k] = Math.max(0, run.spent[k] + usage[k] - run.reserved[k]);
		for (const id of chainOf(this.nodes, runId)) {
			const n = this.edit(id);
			addTo(n.spent, usage);
			addTo(n.reserved, excess);
		}
	}
	/** run の終了: 使わなかった予約を階層から戻す (予約 = 使用量にする) */
	release(runId: string): void {
		const run = this.need(runId);
		const unused = zero();
		for (const k of MONEY_KEYS) unused[k] = Math.max(0, run.reserved[k] - run.spent[k]);
		for (const id of chainOf(this.nodes, runId)) addTo(this.edit(id).reserved, unused, -1);
	}
}

const ACTIVE_TASK = ["running", "waiting", "checking"];

const settled = (n: Node): boolean => n.state === "done" || n.state === "skipped" || n.state === "cancelled";

/** イベントが属する goal (lease の保持者の検査 I8 用) */
const eventGoal = (d: Draft, ev: LedgerEvent): string | undefined => {
	let id = ev.node;
	if (ev.type === "run.reserved") id = ev.data.task as string;
	else if (ev.type === "node.added") id = (ev.data.node as { parent: string }).parent;
	else if (ev.type === "goal.created") return undefined;
	return id === undefined ? undefined : rootGoalId(d.nodes, id);
};

const apply = (d: Draft, ev: LedgerEvent): void => {
	const id = ev.node as string;
	const data = ev.data as Record<string, any>;

	// I8: 保持者が記された追記は、その goal の lease の保持者でなければ拒否する (記さない追記は store の責任)
	if (ev.holder !== undefined && !ev.type.startsWith("lease.")) {
		const gid = eventGoal(d, ev);
		const owner = gid ? d.need(gid).owner : undefined;
		if (gid && owner?.holder !== ev.holder) throw new ReduceError(`I8: ${String(ev.holder)} は lease の保持者でない (${owner?.holder ?? "なし"})`);
	}

	switch (ev.type) {
		case "goal.created": {
			d.create({
				id,
				kind: "goal",
				title: data.title,
				state: "draft",
				after: [],
				writes: [],
				...(data.budget ? { budget: { ...data.budget } } : {}),
				reserved: zero(),
				spent: zero(),
				waits: [],
				evidence: [],
				notes: [],
				attrs: { ...(data.attrs ?? {}) },
			});
			d.goals.push(id);
			return;
		}
		case "node.added": {
			const p = data.node;
			const parent = d.need(p.parent, "親");
			if (parent.kind !== "goal" && !isTaskLike(parent)) throw new ReduceError(`親 ${p.parent} は goal か task でない`);
			const goal = d.goalOf(parent.id);
			const state = initialTaskState(goal.state as never);
			const after: string[] = [...new Set<string>(p.after ?? [])];
			for (const a of after) {
				if (!isTaskLike(d.need(a, "依存先"))) throw new ReduceError(`依存先 ${a} は task でない`);
				if (d.goalOf(a).id !== goal.id) throw new ReduceError(`依存先 ${a} は別の goal`);
			}
			d.create({
				id,
				kind: p.kind,
				parent: parent.id,
				title: p.title,
				state,
				after,
				writes: [...(p.writes ?? [])],
				...(p.budget ? { budget: { ...p.budget } } : {}),
				reserved: zero(),
				spent: zero(),
				waits: [],
				evidence: [],
				notes: [],
				attrs: { ...(p.attrs ?? {}) },
			});
			return;
		}
		case "edge.added":
		case "edge.rejected": {
			if (data.from !== id) throw new ReduceError("edge の from は node と一致しなければならない");
			const from = d.need(id);
			const to = d.need(data.to, "依存先");
			if (!isTaskLike(from) || !isTaskLike(to)) throw new ReduceError("edge は task どうしだけ");
			if (d.goalOf(from.id).id !== d.goalOf(to.id).id) throw new ReduceError("edge は同じ goal の中だけ");
			next("task", from.state, ev.type);
			if (ev.type === "edge.rejected") {
				d.rejections.push({ seq: ev.seq, from: id, to: data.to, reason: data.reason });
				return;
			}
			if (wouldCycle(d.view(), id, data.to)) {
				d.rejections.push({ seq: ev.seq, from: id, to: data.to, reason: "cycle" });
				return;
			}
			if (!from.after.includes(data.to)) d.edit(id).after.push(data.to);
			return;
		}
		case "run.reserved": {
			const task = d.need(data.task, "task");
			if (!isTaskLike(task)) throw new ReduceError(`${task.id} は task でない`);
			const goal = d.goalOf(task.id);
			if (goal.state !== "active") throw new ReduceError(`goal ${goal.id} が active でない (${goal.state})`);
			const rule = next("task", task.state, "run.reserved");
			for (const a of task.after) {
				const s = d.need(a).state;
				if (s !== "done" && s !== "skipped") throw new ReduceError(`依存 ${a} が未完了 (${s})`);
			}
			if (task.kind !== "check") {
				for (const o of d.nodes.values()) {
					if (o.id === task.id || (o.kind !== "task" && o.kind !== "integrate") || !ACTIVE_TASK.includes(o.state)) continue;
					if (task.writes.some((w) => o.writes.some((x) => globsMayOverlap(w, x)))) throw new ReduceError(`writes が実行中の ${o.id} と重なる`);
				}
			}
			const est: Money = data.est;
			for (const cid of chainOf(d.nodes, task.id)) {
				const a = d.need(cid);
				if (!a.budget) continue;
				for (const k of MONEY_KEYS) {
					if (a.reserved[k] + est[k] > a.budget[k]) throw new ReduceError(`予算超過: ${cid} の ${k} (${a.reserved[k]}+${est[k]} > ${a.budget[k]})`);
				}
			}
			d.create({
				id,
				kind: "run",
				parent: task.id,
				title: `run ${id}`,
				state: "reserved",
				after: [],
				writes: [],
				reserved: { ...est },
				spent: zero(),
				waits: [],
				evidence: [],
				notes: [],
				attrs: { ...(data.attrs ?? {}) },
			});
			for (const cid of chainOf(d.nodes, task.id)) addTo(d.edit(cid).reserved, est);
			d.edit(task.id).state = rule.to as never;
			return;
		}
		case "run.started": {
			const run = d.need(id);
			const rule = next("run", run.state, "run.started");
			const e = d.edit(id);
			e.state = rule.to as never;
			if (data.pid !== undefined) e.attrs.pid = data.pid;
			return;
		}
		case "run.usage": {
			const run = d.need(id);
			next("run", run.state, "run.usage");
			d.charge(id, data.usage);
			return;
		}
		case "run.ended": {
			const run = d.need(id);
			const rr = next("run", run.state, "run.ended", data.status);
			const task = d.need(run.parent as string);
			const tr = next("task", task.state, "run.ended", data.status);
			if (data.usage) d.charge(id, data.usage);
			d.release(id);
			const e = d.edit(id);
			e.state = rr.to as never;
			if (data.digestId) e.attrs.digestId = data.digestId;
			d.edit(task.id).state = tr.to as never;
			return;
		}
		case "check.result": {
			const n = d.need(id);
			if (!isTaskLike(n)) throw new ReduceError(`${id} は task でない`);
			const r = next("task", n.state, "check.result", variantOf(ev.type, data, { waitsRemain: false, liveRun: false }));
			const e = d.edit(id);
			e.evidence.push(`check:${ev.seq}`);
			if (data.evidenceId) e.evidence.push(data.evidenceId);
			e.state = r.to as never;
			return;
		}
		case "wait.opened": {
			const n = d.need(id);
			const r = next(tkindOf(n.kind), n.state, "wait.opened");
			const w = data.wait;
			if (n.waits.some((x) => x.on === w.on && x.ref === w.ref)) throw new ReduceError(`待ち ${w.on}:${w.ref} は既にある`);
			const e = d.edit(id);
			e.waits.push({ on: w.on, ref: w.ref, since: w.since, auto: w.auto, ...(w.prompt !== undefined ? { prompt: w.prompt } : {}) });
			e.state = r.to as never;
			return;
		}
		case "wait.resolved": {
			const n = d.need(id);
			const w = n.waits.find((x) => x.ref === data.ref);
			if (!w) throw new ReduceError(`待ち ${data.ref} が ${id} に無い`);
			// I5: 解除できるのは、その待ちの種類の事実か、利用者だけ (user 待ちは利用者だけ)
			if (w.on === "user" ? data.by !== "user" : data.by !== w.on && data.by !== "user") {
				throw new ReduceError(`I5: ${w.on} 待ちは ${data.by} では解けない`);
			}
			const facts: Facts = { waitsRemain: n.waits.length > 1, liveRun: d.hasLiveRun(id) };
			const r = next(tkindOf(n.kind), n.state, "wait.resolved", variantOf(ev.type, data, facts));
			const e = d.edit(id);
			e.waits = e.waits.filter((x) => x.ref !== data.ref);
			e.state = r.to as never;
			d.resolutions.push({ seq: ev.seq, node: id, ref: data.ref, on: w.on, by: data.by, source: String(ev.source ?? "") });
			return;
		}
		case "note.appended": {
			const n = d.need(id);
			const r = next(tkindOf(n.kind), n.state, "note.appended");
			const e = d.edit(id);
			e.notes.push({ by: data.by, at: ev.ts, text: data.text });
			e.state = r.to as never;
			return;
		}
		case "budget.adjusted": {
			const n = d.need(id);
			const r = next(tkindOf(n.kind), n.state, "budget.adjusted");
			for (const k of MONEY_KEYS) if (data.budget[k] < n.reserved[k]) throw new ReduceError(`予算 ${k} が予約 (${n.reserved[k]}) を下回る`);
			const e = d.edit(id);
			e.budget = { ...data.budget };
			e.state = r.to as never;
			return;
		}
		case "verdict": {
			const n = d.need(id);
			// I10 の拡張: goal の取り消しは利用者専用 (task の cancel はモデルでも通る)
			if (n.kind === "goal" && data.verdict === "cancel" && ev.source !== "user") {
				throw new ReduceError(`I10: goal の cancel は利用者専用 (出所が user でない: ${String(ev.source ?? "system")})`);
			}
			const r = next(tkindOf(n.kind), n.state, "verdict", data.verdict);
			const e = d.edit(id);
			if (n.kind === "goal") e.evidence.push(`verdict:${ev.seq}:${data.verdict}`);
			if (r.effect === "retry") e.attrs.attempts = ((n.attrs.attempts as number | undefined) ?? 0) + 1;
			e.state = r.to as never;
			return;
		}
		case "plan.proposed": {
			const n = d.goalNode(id);
			const r = next("goal", n.state, "plan.proposed");
			const e = d.edit(id);
			e.attrs.planHash = data.hash;
			delete e.attrs.approvedBy;
			e.state = r.to as never;
			return;
		}
		case "plan.approved": {
			const n = d.goalNode(id);
			const r = next("goal", n.state, "plan.approved");
			if (n.attrs.planHash !== data.hash) throw new ReduceError(`計画の hash が一致しない (${String(n.attrs.planHash)} ≠ ${data.hash})`);
			const e = d.edit(id);
			e.attrs.approvedBy = "user";
			e.state = r.to as never;
			for (const t of [...d.nodes.values()]) {
				if (!isTaskLike(t) || t.state !== "proposed" || rootGoalId(d.nodes, t.id) !== id) continue;
				d.edit(t.id).state = next("task", "proposed", "plan.approved").to as never;
			}
			return;
		}
		case "goal.paused":
		case "goal.resumed": {
			const n = d.goalNode(id);
			const r = next("goal", n.state, ev.type);
			const e = d.edit(id);
			if (ev.type === "goal.resumed") {
				e.attrs.resumes = ((n.attrs.resumes as number | undefined) ?? 0) + 1;
				delete e.pauseReason;
			} else e.pauseReason = data.reason;
			e.state = r.to as never;
			return;
		}
		case "goal.done": {
			const n = d.goalNode(id);
			const r = next("goal", n.state, "goal.done");
			if (!n.evidence.some((x) => /^verdict:\d+:done$/.test(x))) throw new ReduceError("I6: goal の done には verdict done が要る");
			for (const t of d.nodes.values()) {
				if (rootGoalId(d.nodes, t.id) !== id || t.id === id) continue;
				if (isTaskLike(t) && !settled(t)) throw new ReduceError(`I6: task ${t.id} が未決着 (${t.state})`);
				if (isLiveRun(t)) throw new ReduceError(`run ${t.id} がまだ走っている`);
			}
			d.edit(id).state = r.to as never;
			return;
		}
		case "lease.acquired": {
			const n = d.goalNode(id);
			next("goal", n.state, "lease.acquired");
			if (n.owner && n.owner.holder !== data.holder) throw new ReduceError(`I8: lease は ${n.owner.holder} が保持している`);
			const lease: Lease = { holder: data.holder, pid: data.pid, startedAt: n.owner?.startedAt ?? data.startedAt ?? ev.ts, heartbeat: ev.ts };
			d.edit(id).owner = lease;
			return;
		}
		case "lease.released":
		case "lease.expired": {
			const n = d.goalNode(id);
			next("goal", n.state, ev.type);
			if (n.owner?.holder !== data.holder) throw new ReduceError(`I8: ${data.holder} は lease の保持者でない`);
			delete d.edit(id).owner;
			return;
		}
		default:
			throw new ReduceError(`未対応のイベント: ${ev.type}`);
	}
};

/** 1 件を畳む。純関数 (入力を変更しない)。前提を満たさないイベントは例外 */
export const reduce = (state: LedgerState, ev: LedgerEvent): LedgerState => {
	const d = new Draft(state);
	if (ev.seq !== state.seq + 1) d.anomalies.push({ seq: ev.seq, inv: "I9", message: `seq ${ev.seq} は ${state.seq + 1} のはず (欠番か重複)` });
	d.seq = ev.seq;
	if (isAux(ev)) return d.view();
	const bad = validateEvent(ev);
	if (bad) throw new ReduceError(`seq ${ev.seq} ${ev.type}: ${bad}`);
	try {
		apply(d, ev);
	} catch (e) {
		if (e instanceof Error) e.message = `seq ${ev.seq} ${ev.type}: ${e.message}`;
		throw e;
	}
	return d.view();
};

export const fold = (events: readonly LedgerEvent[], from: LedgerState = emptyState()): LedgerState => events.reduce(reduce, from);

// ── スナップショット (JSON) ──
export const serialize = (s: LedgerState) => ({
	seq: s.seq,
	nodes: [...s.nodes.entries()],
	goals: [...s.goals],
	rejections: [...s.rejections],
	anomalies: [...s.anomalies],
	resolutions: [...s.resolutions],
});

export const deserialize = (j: ReturnType<typeof serialize>): LedgerState => ({
	seq: j.seq,
	nodes: new Map(j.nodes),
	goals: j.goals,
	rejections: j.rejections,
	anomalies: j.anomalies,
	resolutions: j.resolutions,
});
