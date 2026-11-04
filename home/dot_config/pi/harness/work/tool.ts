// モデル向けのツール `work` の純関数 (pi の API・fs・index.ts に依存しない)。既存のツール `todo` の置き換え先。
// 操作は add / set / note / list / plan / cancel だけ。spawn・承認・予算変更・resume は持たない (利用者専用。I10)。
// 状態は台帳 (reducer) だけが持ち、ここは引数を検査して台帳のイベント列を作り、reducer を通して有効なものだけを返す。
// 仕様: docs/spec/work/tool.md
import { makeEvent, NOTE_MAX, ZERO } from "./events.ts";
import type { Payloads } from "./events.ts";
import { emptyState, isLiveRun, isTaskLike, reduce, resolveEdge, rootGoalId, wouldCycle } from "./reduce.ts";
import type { LedgerState } from "./reduce.ts";
import { clipCells } from "./text-width.ts";
import type { EventType, LedgerEvent, NewEvent, Node } from "./types.ts";

export const TITLE_MAX = 200;
export const NOTE_TEXT_MAX = NOTE_MAX;
export const TEXT_MAX = 1500;
export const LIST_MAX = 10;
export const PLAN_TASKS_MAX = 30;
const LIST_LINE_WIDTH = 60;
const TRUNC_SUFFIX = "…（全文は /work）";

export const OPS = ["add", "set", "note", "list", "plan", "cancel"] as const;
export type Op = (typeof OPS)[number];
/** set でモデルが指定してよい状態 */
export const SET_STATUSES = ["pending", "in_progress", "blocked", "done", "cancelled"] as const;
export type SetStatus = (typeof SET_STATUSES)[number];
const LIST_FILTERS = ["ready", "running", "waiting", "done"] as const;
const WAIT_ONS = ["user", "time", "job", "merge"] as const;
const KINDS = ["task", "check", "integrate"] as const;

export interface WorkCtx {
	now: number;
	holder: string;
}
export interface WorkResult {
	ok: boolean;
	/** 台帳へ追記するイベント (seq・ts は store が付ける)。ok が偽なら空 */
	events: NewEvent[];
	/** モデルの文脈に入る本文 (上限 TEXT_MAX 字) */
	text: string;
	details: Record<string, unknown>;
}

const ID_RE = /^[A-Za-z][A-Za-z0-9_.-]{0,39}$/;
// biome-ignore lint/suspicious/noControlCharactersInRegex: 制御文字の拒否が目的
const CTRL_RE = /[\u0000-\u001f\u007f]/;

const str = { type: "string" };
const idList = { type: "array", items: { type: "string", pattern: ID_RE.source }, maxItems: 20 };
const idProp = { type: "string", pattern: ID_RE.source };
const titleProp = { type: "string", minLength: 1, maxLength: TITLE_MAX };
const waitProp = {
	type: "object",
	additionalProperties: false,
	required: ["on", "ref"],
	properties: { on: { enum: [...WAIT_ONS] }, ref: { type: "string", minLength: 1, maxLength: 100 }, prompt: { ...str, maxLength: 23 } },
};

/** 引数の JSON Schema (oneOf の op ごと。余計なキーは不可) */
export const WORK_TOOL_SCHEMA = {
	type: "object",
	oneOf: [
		{
			type: "object",
			additionalProperties: false,
			required: ["op", "title"],
			properties: {
				op: { const: "add" },
				title: titleProp,
				kind: { enum: [...KINDS] },
				parent: idProp,
				writes: { type: "array", items: { type: "string", minLength: 1, maxLength: 200 }, maxItems: 20 },
				deps: idList,
				wait: waitProp,
			},
		},
		{
			type: "object",
			additionalProperties: false,
			required: ["op", "id"],
			properties: { op: { const: "set" }, id: idProp, status: { enum: [...SET_STATUSES] }, deps: idList },
		},
		{
			type: "object",
			additionalProperties: false,
			required: ["op", "id", "text"],
			properties: { op: { const: "note" }, id: idProp, text: { type: "string", minLength: 1, maxLength: NOTE_TEXT_MAX } },
		},
		{
			type: "object",
			additionalProperties: false,
			required: ["op"],
			properties: { op: { const: "list" }, filter: { enum: [...LIST_FILTERS] } },
		},
		{
			type: "object",
			additionalProperties: false,
			required: ["op", "goal", "tasks"],
			properties: {
				op: { const: "plan" },
				goal: titleProp,
				tasks: {
					type: "array",
					minItems: 1,
					maxItems: PLAN_TASKS_MAX,
					items: {
						type: "object",
						additionalProperties: false,
						required: ["title"],
						properties: {
							title: titleProp,
							kind: { enum: [...KINDS] },
							writes: { type: "array", items: { type: "string", minLength: 1, maxLength: 200 }, maxItems: 20 },
							deps: { type: "array", items: { type: "integer", minimum: 0 }, maxItems: 20 },
						},
					},
				},
			},
		},
		{
			type: "object",
			additionalProperties: false,
			required: ["op", "id", "reason"],
			properties: { op: { const: "cancel" }, id: idProp, reason: { type: "string", minLength: 1, maxLength: TITLE_MAX } },
		},
	],
};

// ── 引数の検査 (厳格) ──
const isObj = (x: unknown): x is Record<string, unknown> => typeof x === "object" && x !== null && !Array.isArray(x);

const ALLOWED: Record<Op, readonly string[]> = {
	add: ["op", "title", "kind", "parent", "writes", "deps", "wait"],
	set: ["op", "id", "status", "deps"],
	note: ["op", "id", "text"],
	list: ["op", "filter"],
	plan: ["op", "goal", "tasks"],
	cancel: ["op", "id", "reason"],
};

class ArgError extends Error {}
const bad = (m: string): never => {
	throw new ArgError(m);
};

const checkKeys = (o: Record<string, unknown>, allowed: readonly string[], where: string): void => {
	for (const k of Object.keys(o)) if (!allowed.includes(k)) bad(`${where}: 余計なキー ${JSON.stringify(k).slice(0, 40)}`);
};
const reqStr = (o: Record<string, unknown>, k: string, max: number): string => {
	const v = o[k];
	if (typeof v !== "string" || v.length === 0) return bad(`${k} は空でない文字列`);
	if (v.length > max) return bad(`${k} は ${max} 字以内`);
	return v;
};
const oneLine = (o: Record<string, unknown>, k: string, max: number): string => {
	const v = reqStr(o, k, max);
	if (CTRL_RE.test(v)) bad(`${k} に制御文字・改行は使えない`);
	return v;
};
const reqId = (v: unknown, k: string): string => {
	if (typeof v !== "string" || !ID_RE.test(v)) return bad(`${k} の id の形式が不正`);
	return v;
};
const idArr = (o: Record<string, unknown>, k: string): string[] | undefined => {
	const v = o[k];
	if (v === undefined) return undefined;
	if (!Array.isArray(v) || v.length > 20) return bad(`${k} は 20 件以内の配列`);
	return v.map((x) => reqId(x, k));
};
const optEnum = <T extends string>(o: Record<string, unknown>, k: string, set: readonly T[]): T | undefined => {
	const v = o[k];
	if (v === undefined) return undefined;
	if (typeof v !== "string" || !set.includes(v as T)) return bad(`${k} は ${set.join("|")}`);
	return v as T;
};
const globs = (o: Record<string, unknown>): string[] | undefined => {
	const v = o.writes;
	if (v === undefined) return undefined;
	if (!Array.isArray(v) || v.length > 20) return bad("writes は 20 件以内の配列");
	return v.map((x) => {
		if (typeof x !== "string" || x.length === 0 || x.length > 200 || CTRL_RE.test(x)) return bad("writes の要素が不正");
		return x;
	});
};

interface WaitArg {
	on: (typeof WAIT_ONS)[number];
	ref: string;
	prompt?: string;
}
type Args =
	| { op: "add"; title: string; kind: (typeof KINDS)[number]; parent?: string; writes?: string[]; deps?: string[]; wait?: WaitArg }
	| { op: "set"; id: string; status?: SetStatus; deps?: string[] }
	| { op: "note"; id: string; text: string }
	| { op: "list"; filter?: (typeof LIST_FILTERS)[number] }
	| { op: "plan"; goal: string; tasks: { title: string; kind: (typeof KINDS)[number]; writes?: string[]; deps: number[] }[] }
	| { op: "cancel"; id: string; reason: string };

const parseArgs = (raw: unknown): Args => {
	if (!isObj(raw)) return bad("引数がオブジェクトでない");
	const op = raw.op;
	if (typeof op !== "string" || !(OPS as readonly string[]).includes(op)) {
		return bad(`op は ${OPS.join("|")} のどれか (spawn・承認・予算変更・resume は利用者専用で、このツールには無い)`);
	}
	checkKeys(raw, ALLOWED[op as Op], op);
	switch (op as Op) {
		case "add": {
			let wait: WaitArg | undefined;
			if (raw.wait !== undefined) {
				const w = raw.wait;
				if (!isObj(w)) return bad("wait はオブジェクト");
				checkKeys(w, ["on", "ref", "prompt"], "wait");
				const on = optEnum(w, "on", WAIT_ONS);
				if (!on) return bad("wait.on が必要");
				const ref = oneLine(w, "ref", 100);
				const prompt = w.prompt === undefined ? undefined : oneLine(w, "prompt", 23);
				if (on === "user" && prompt === undefined) return bad("user 待ちには prompt が必要");
				wait = { on, ref, ...(prompt !== undefined ? { prompt } : {}) };
			}
			return {
				op: "add",
				title: oneLine(raw, "title", TITLE_MAX),
				kind: optEnum(raw, "kind", KINDS) ?? "task",
				...(raw.parent !== undefined ? { parent: reqId(raw.parent, "parent") } : {}),
				...(raw.writes !== undefined ? { writes: globs(raw) } : {}),
				...(raw.deps !== undefined ? { deps: idArr(raw, "deps") } : {}),
				...(wait ? { wait } : {}),
			} as Args;
		}
		case "set": {
			const status = optEnum(raw, "status", SET_STATUSES);
			const deps = idArr(raw, "deps");
			if (status === undefined && deps === undefined) return bad("set には status か deps が要る");
			return { op: "set", id: reqId(raw.id, "id"), ...(status ? { status } : {}), ...(deps ? { deps } : {}) };
		}
		case "note":
			return { op: "note", id: reqId(raw.id, "id"), text: reqStr(raw, "text", NOTE_TEXT_MAX) };
		case "list":
			return { op: "list", ...(raw.filter !== undefined ? { filter: optEnum(raw, "filter", LIST_FILTERS) } : {}) } as Args;
		case "plan": {
			const goal = oneLine(raw, "goal", TITLE_MAX);
			const ts = raw.tasks;
			if (!Array.isArray(ts) || ts.length === 0 || ts.length > PLAN_TASKS_MAX) return bad(`tasks は 1〜${PLAN_TASKS_MAX} 件の配列`);
			const tasks = ts.map((t, i) => {
				if (!isObj(t)) return bad(`tasks[${i}] がオブジェクトでない`);
				checkKeys(t, ["title", "kind", "writes", "deps"], `tasks[${i}]`);
				const deps = t.deps === undefined ? [] : t.deps;
				if (!Array.isArray(deps) || deps.length > 20) return bad(`tasks[${i}].deps は 20 件以内の配列`);
				for (const d of deps) if (!Number.isInteger(d) || (d as number) < 0 || (d as number) >= i) bad(`tasks[${i}].deps は前の task の番号`);
				return {
					title: oneLine(t, "title", TITLE_MAX),
					kind: optEnum(t, "kind", KINDS) ?? "task",
					...(t.writes !== undefined ? { writes: globs(t) } : {}),
					deps: deps as number[],
				};
			});
			return { op: "plan", goal, tasks } as Args;
		}
		case "cancel":
			return { op: "cancel", id: reqId(raw.id, "id"), reason: oneLine(raw, "reason", TITLE_MAX) };
	}
	return bad("op が不正");
};

// ── 表示 ──
const STATE_JA: Record<string, string> = {
	proposed: "提案",
	ready: "待機",
	running: "実行",
	waiting: "待ち",
	checking: "検査",
	done: "完了",
	failed: "失敗",
	blocked: "停止",
	cancelled: "取消",
	skipped: "省略",
};
const clean = (s: string): string => s.replace(/[\u0000-\u001f\u007f]/g, " ");

const capText = (s: string): string => {
	if (s.length <= TEXT_MAX) return s;
	return `${s.slice(0, TEXT_MAX - TRUNC_SUFFIX.length)}${TRUNC_SUFFIX}`;
};

const GROUPS: Record<(typeof LIST_FILTERS)[number], readonly string[]> = {
	ready: ["ready", "proposed"],
	running: ["running", "checking"],
	waiting: ["waiting", "blocked", "failed"],
	done: ["done", "skipped"],
};

const line = (n: Node): string => `${n.id} [${STATE_JA[n.state] ?? n.state}] ${clipCells(clean(n.title), LIST_LINE_WIDTH)}`;

const listText = (state: LedgerState, filter?: (typeof LIST_FILTERS)[number]): { text: string; counts: Record<string, number> } => {
	const tasks = [...state.nodes.values()].filter(isTaskLike);
	const counts: Record<string, number> = {};
	const out: string[] = [];
	const names = filter ? [filter] : (Object.keys(GROUPS) as (keyof typeof GROUPS)[]);
	const head = (Object.keys(GROUPS) as (keyof typeof GROUPS)[]).map((g) => {
		const n = tasks.filter((t) => GROUPS[g].includes(t.state)).length;
		counts[g] = n;
		return `${g} ${n}`;
	});
	const cancelled = tasks.filter((t) => t.state === "cancelled").length;
	counts.cancelled = cancelled;
	out.push(`${head.join(" · ")}${cancelled ? ` · 取消 ${cancelled}` : ""}`);
	for (const g of names) {
		const items = tasks.filter((t) => GROUPS[g].includes(t.state)).sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));
		if (items.length === 0) continue;
		out.push(`# ${g}`);
		for (const n of items.slice(0, LIST_MAX)) out.push(line(n));
		if (items.length > LIST_MAX) out.push(`…ほか ${items.length - LIST_MAX} 件`);
	}
	return { text: out.join("\n"), counts };
};

// ── イベントの組み立て ──
class Fail extends Error {}
const fail = (m: string): never => {
	throw new Fail(m);
};

/** 作業用の状態。イベントを足すたびに reducer を通す (拒否されたら Fail)。入力の state は変えない */
class Work {
	events: NewEvent[] = [];
	state: LedgerState;
	readonly ctx: WorkCtx;
	constructor(base: LedgerState, ctx: WorkCtx) {
		this.state = base;
		this.ctx = ctx;
	}
	private ownerOf(node: string | undefined, type: EventType): { holder: string } | Record<string, never> {
		// 台帳が lease の保持者を持ち、それが自分なら holder を記す (別の保持者のときは store が拒否する)
		void type;
		let id = node;
		while (id !== undefined) {
			const n = this.state.nodes.get(id);
			if (!n) break;
			if (n.kind === "goal") return n.owner?.holder === this.ctx.holder ? { holder: this.ctx.holder } : {};
			id = n.parent;
		}
		return {};
	}
	push<T extends keyof Payloads>(type: T, node: string, data: Payloads[T], parent?: string): void {
		const ev = makeEvent(type, node, data, "model", this.ownerOf(parent ?? node, type));
		const full: LedgerEvent = { ...ev, ts: this.ctx.now, seq: this.state.seq + 1 };
		try {
			this.state = reduce(this.state, full);
		} catch (e) {
			return fail(e instanceof Error ? e.message.replace(/^seq \d+ /, "") : String(e));
		}
		this.events.push(ev);
	}
	nextNum(): number {
		let m = 0;
		for (const id of this.state.nodes.keys()) {
			const k = /(\d+)$/.exec(id);
			if (k) m = Math.max(m, Number(k[1]));
		}
		return m + 1;
	}
	node(id: string): Node {
		const n = this.state.nodes.get(id);
		if (!n) return fail(`${id} が無い`);
		return n;
	}
	task(id: string): Node {
		const n = this.node(id);
		if (!isTaskLike(n)) return fail(`${id} は task でない (${n.kind})`);
		return n;
	}
	liveRuns(id: string): Node[] {
		return [...this.state.nodes.values()].filter((n) => n.parent === id && isLiveRun(n));
	}
	/** ready の task に、利用者の起動を待たない手動の run を付けて running にする */
	start(id: string): string {
		const t = this.task(id);
		if (t.state === "proposed") return fail(`${id} は計画が未承認のため開始できない (承認は利用者だけ)`);
		if (t.state !== "ready") {
			return fail(`${id} は ${t.state} のため開始できない`);
		}
		const rid = `r${this.nextNum()}`;
		this.push("run.reserved", rid, { task: id, est: { ...ZERO }, attrs: { manual: true } });
		this.push("run.started", rid, {});
		return rid;
	}
	/** どの状態からでも running (走っている run つき) へ持っていく。無理なら Fail */
	toRunning(id: string): string {
		let t = this.task(id);
		if (t.state === "failed" || t.state === "blocked") {
			this.push("verdict", id, { verdict: "retry", reason: "モデルが再開" });
			t = this.task(id);
		}
		if (t.state === "ready") return this.start(id);
		if (t.state === "proposed") return fail(`${id} は計画が未承認のため開始できない (承認は利用者だけ)`);
		if (t.state === "running") {
			const run = this.liveRuns(id)[0];
			if (!run) return fail(`${id} は running だが走っている run が無い`);
			if (run.state === "reserved") this.push("run.started", run.id, {});
			return run.id;
		}
		return fail(`${id} は ${t.state} のため、この操作はできない`);
	}
	/** 走っている run を終える (状態は reducer が決める) */
	endRuns(id: string, status: "done" | "blocked" | "aborted"): void {
		for (const r of this.liveRuns(id)) {
			if (this.node(r.id).state === "reserved") this.push("run.started", r.id, {});
			this.push("run.ended", r.id, { status });
		}
	}
	addEdges(id: string, deps: string[]): void {
		const t = this.task(id);
		for (const d of deps) {
			this.task(d);
			if (id === d) fail(`循環: ${id} は自分に依存できない`);
			if (wouldCycle(this.state, id, d)) {
				const r = resolveEdge(this.state, { type: "edge.added", node: id, data: { from: id, to: d } });
				fail(`循環: ${id} → ${d} は ${r.type === "edge.rejected" ? "依存の輪になる" : "拒否"}`);
			}
			if (t.after.includes(d)) continue;
			this.push("edge.added", id, { from: id, to: d });
		}
	}
}

/** add の親 (省略時は、利用者が動かしている goal を優先して、いちばん新しい生きた goal。無ければ作る) */
const pickParent = (w: Work, explicit?: string): string => {
	if (explicit) {
		const p = w.node(explicit);
		if (p.kind !== "goal" && !isTaskLike(p)) fail(`${explicit} は goal か task でない`);
		return explicit;
	}
	const goals = w.state.goals.map((g) => w.node(g));
	const live = goals.filter((g) => ["active", "planned", "draft", "paused"].includes(g.state));
	const pick = [...live].reverse().find((g) => g.state === "active") ?? live[live.length - 1];
	if (pick) return pick.id;
	const gid = `g${w.nextNum()}`;
	w.push("goal.created", gid, { title: "作業", attrs: { origin: "model" } });
	return gid;
};

/** 計画の内容の hash (FNV-1a。決定的) */
const hashOf = (x: unknown): string => {
	let h = 0x811c9dc5;
	for (const ch of JSON.stringify(x)) {
		h ^= ch.codePointAt(0) ?? 0;
		h = Math.imul(h, 0x01000193) >>> 0;
	}
	return h.toString(16).padStart(8, "0");
};

const run = (state: LedgerState, a: Args, ctx: WorkCtx): { w: Work; text: string; details: Record<string, unknown> } => {
	const w = new Work(state, ctx);
	switch (a.op) {
		case "add": {
			const parent = pickParent(w, a.parent);
			const id = `n${w.nextNum()}`;
			for (const d of a.deps ?? []) w.task(d);
			w.push(
				"node.added",
				id,
				{ node: { kind: a.kind, parent, title: a.title, after: a.deps ?? [], writes: a.writes ?? [], attrs: { origin: "model" } } },
				parent,
			);
			if (a.wait) {
				w.toRunning(id);
				const on = a.wait.on;
				w.push("wait.opened", id, {
					wait: { on, ref: a.wait.ref, since: ctx.now, auto: on !== "user", ...(a.wait.prompt ? { prompt: a.wait.prompt } : {}) },
				});
			}
			const n = w.node(id);
			// 承認の後に追加した task はスケジューラが自動起動しない (approved が立つのは plan.approved の時点の task だけ)
			const g = rootGoalId(w.state.nodes, id);
			const pending = n.approved !== true && g !== undefined && w.state.nodes.get(g)?.state === "active";
			const note = pending ? "\n承認待ち（スケジューラは起動しない。/goal approve で承認）" : "";
			return {
				w,
				text: `追加 ${id} [${STATE_JA[n.state]}] ${clipCells(clean(n.title), LIST_LINE_WIDTH)}${note}`,
				details: { op: "add", id, state: n.state },
			};
		}
		case "set": {
			const t = w.task(a.id);
			if (a.deps) w.addEdges(a.id, a.deps);
			const st = a.status;
			if (st === "pending") {
				if (t.state === "failed" || t.state === "blocked") w.push("verdict", a.id, { verdict: "retry", reason: "モデルが保留へ戻した" });
				else if (t.state !== "ready" && t.state !== "proposed") fail(`${a.id} は ${t.state} から pending にできない`);
			} else if (st === "in_progress") {
				if (t.state !== "running") w.toRunning(a.id);
			} else if (st === "blocked") {
				if (t.state === "blocked") return { w, text: `${a.id} は既に停止`, details: { op: "set", id: a.id, state: t.state } };
				w.toRunning(a.id);
				w.endRuns(a.id, "blocked");
			} else if (st === "done") {
				if (t.state === "checking") w.push("check.result", a.id, { name: "model", ok: true });
				else {
					w.toRunning(a.id);
					w.endRuns(a.id, "done");
					w.push("check.result", a.id, { name: "model", ok: true });
				}
			} else if (st === "cancelled") {
				cancel(w, a.id, "モデルが取り消した");
			}
			const n = w.node(a.id);
			return { w, text: `${a.id} [${STATE_JA[n.state]}] ${clipCells(clean(n.title), LIST_LINE_WIDTH)}`, details: { op: "set", id: a.id, state: n.state } };
		}
		case "note": {
			w.node(a.id);
			w.push("note.appended", a.id, { by: "llm", text: a.text });
			return { w, text: `注釈を追記 ${a.id}`, details: { op: "note", id: a.id } };
		}
		case "cancel": {
			w.task(a.id);
			cancel(w, a.id, a.reason);
			return { w, text: `取消 ${a.id}`, details: { op: "cancel", id: a.id } };
		}
		case "list": {
			const l = listText(state, a.filter);
			return { w, text: l.text, details: { op: "list", counts: l.counts } };
		}
		case "plan": {
			const gid = `g${w.nextNum()}`;
			w.push("goal.created", gid, { title: a.goal, attrs: { origin: "model" } });
			let n = w.nextNum();
			const ids: string[] = [];
			for (const t of a.tasks) {
				const id = `n${n++}`;
				w.push("node.added", id, {
					node: { kind: t.kind, parent: gid, title: t.title, after: t.deps.map((i) => ids[i]), writes: t.writes ?? [], attrs: { origin: "model" } },
				});
				ids.push(id);
			}
			const hash = hashOf({ goal: a.goal, tasks: a.tasks });
			w.push("plan.proposed", gid, { hash });
			return {
				w,
				text: `計画を提案 ${gid} (task ${ids.length} 件)。承認は利用者だけが行う`,
				details: { op: "plan", goal: gid, tasks: ids, hash },
			};
		}
	}
};

/** 取り消し: 走っている run を中止してから verdict cancel。goal は取り消せない (利用者の操作) */
const cancel = (w: Work, id: string, reason: string): void => {
	const t = w.task(id);
	if (t.state === "cancelled" || t.state === "done" || t.state === "skipped") fail(`${id} は既に ${t.state}`);
	w.endRuns(id, "aborted");
	w.push("verdict", id, { verdict: "cancel", reason });
};

/**
 * `work` ツールの本体。入力の state は変更しない。events は reducer を通った有効なものだけ (操作は全部成功か、全部なしか)。
 * 無効な操作は ok:false と理由を返す。text は上限 TEXT_MAX 字 (title・状態・id だけ。注釈の本文は出さない)。
 */
export const handleWork = (state: LedgerState, args: unknown, ctx: WorkCtx): WorkResult => {
	let msg: string;
	try {
		const a = parseArgs(args);
		const r = run(state, a, ctx);
		return { ok: true, events: r.w.events, text: capText(r.text), details: r.details };
	} catch (e) {
		if (!(e instanceof ArgError || e instanceof Fail || e instanceof Error)) throw e;
		msg = e.message;
	}
	return { ok: false, events: [], text: capText(`拒否: ${clean(msg)}`), details: { error: clean(msg).slice(0, 300) } };
};

/** 空の台帳に対する呼び出しの補助 (試験用) */
export const emptyWorkState = (): LedgerState => emptyState();
