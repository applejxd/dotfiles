// `/goal` を作業台帳の上に載せる接着 (純関数。pi の API・fs・index.ts なし)。目標の状態の唯一の出所は台帳の goal.* の fold で、
// goal-core.ts の GoalState はここから導出する (写しを 2 つにしない)。コマンド → 利用者専用イベントの変換、導出、arbiter の Facts の写し。
// 仕様: docs/spec/work/goal.md
import { DEFAULT_BUDGET, LIMITS, newGoal, renderDetail, setBudget, THRESHOLDS } from "../goal-core.ts";
import type { Budget, GoalCommand, GoalState, PauseReason } from "../goal-types.ts";
import { EventError, makeEvent } from "./events.ts";
import { isTaskLike, rootGoalId } from "./reduce.ts";
import type { LedgerState } from "./reduce.ts";
import type { NewEvent, Node } from "./types.ts";

/** 台帳の goal ノードの budget。Money に rounds を足した形 (reducer は budget を丸ごと写すので、余分な軸も残る) */
export interface GoalBudgetMoney {
	usd: number;
	tokens: number;
	ms: number;
	rounds: number;
}

/** トークン (と usd) に上限が無いときの値。Money は有限でなければならないので、上限の外の有限値で表す */
export const UNLIMITED = Number.MAX_SAFE_INTEGER;

export interface GoalResult {
	ok: boolean;
	events: NewEvent[];
	text?: string;
	error?: string;
	/** draft のメモ (台帳には書かない。LLM に下書きさせる配線が使う) */
	draft?: string;
	/** approve のとき、承認の対象 (確認画面に出す) */
	approval?: { total: number; titles: string[] };
}

/** 台帳に載らない実行中の値 (resume で 0 に戻るもの・停止の理由)。配線が持ち、導出に重ねる */
export interface GoalRuntime {
	used?: GoalState["used"];
	lifetime?: Partial<GoalState["lifetime"]>;
	counters?: GoalState["counters"];
	pause?: GoalState["pause"];
	lastTextHash?: string;
	lastReasonHash?: string;
	lastVerdict?: GoalState["lastVerdict"];
	updatedAt?: number;
}

const LIVE = ["draft", "planned", "active", "paused"];

/** `/goal approve` (goal-core.ts の解析には載せない。配線が直接渡す) */
export interface GoalApproveCommand {
	kind: "approve";
}

/** active / paused の goal の、まだ承認されていない非終端の task (承認後に足されたもの)。title は最大 10 件、total は総件数 */
export function pendingApproval(state: LedgerState): { total: number; titles: string[] } {
	const cur = currentGoal(state);
	if (!cur) return { total: 0, titles: [] };
	const out: string[] = [];
	for (const t of state.nodes.values()) {
		if (!isTaskLike(t) || rootGoalId(state.nodes, t.id) !== cur.id) continue;
		if (t.state === "done" || t.state === "cancelled" || t.state === "skipped" || t.approved === true) continue;
		out.push(t.title);
	}
	return { total: out.length, titles: out.slice(0, 10) };
}

const hashOf = (s: string): string => {
	let h = 0x811c9dc5;
	for (const ch of s.trim().replace(/\s+/g, " ")) {
		h ^= ch.codePointAt(0)!;
		h = Math.imul(h, 0x01000193) >>> 0;
	}
	return h.toString(16).padStart(8, "0");
};

const toMoney = (b: Budget): GoalBudgetMoney => ({
	usd: UNLIMITED,
	tokens: b.tokens ?? UNLIMITED,
	ms: b.minutes * 60_000,
	rounds: b.rounds,
});

const fromMoney = (m: Partial<GoalBudgetMoney> | undefined): Budget => {
	const rounds = Number.isInteger(m?.rounds) ? (m!.rounds as number) : DEFAULT_BUDGET.rounds;
	const minutes = typeof m?.ms === "number" && m.ms > 0 ? Math.round(m.ms / 60_000) : DEFAULT_BUDGET.minutes;
	const t = m?.tokens;
	return typeof t === "number" && t >= LIMITS.tokens[0] && t <= LIMITS.tokens[1] ? { rounds, minutes, tokens: t } : { rounds, minutes };
};

/** 台帳に保存された停止理由 (goal.paused の reason)。無ければ user */
const pauseReasonOf = (n: Node): PauseReason => (n.pauseReason ?? "user") as PauseReason;

/** いまの目標のノード (最後の goal。cancelled は破棄済みなので無し) */
const currentGoal = (state: LedgerState): Node | null => {
	const id = state.goals[state.goals.length - 1];
	const n = id === undefined ? undefined : state.nodes.get(id);
	return n && n.state !== "cancelled" ? n : null;
};

/** 台帳の投影から GoalState を導く。目標が無い・計画の承認前 (draft / planned)・破棄済みは null。rt があれば台帳に無い実行中の値を重ねる */
export function goalStateOf(state: LedgerState, rt: GoalRuntime = {}): GoalState | null {
	const n = currentGoal(state);
	if (!n || (n.state !== "active" && n.state !== "paused" && n.state !== "done")) return null;
	const createdAt = typeof n.attrs.createdAt === "number" ? n.attrs.createdAt : 0;
	const resumes = typeof n.attrs.resumes === "number" ? n.attrs.resumes : 0;
	const g: GoalState = {
		v: 1,
		id: n.id,
		text: n.title,
		status: n.state,
		budget: fromMoney(n.budget as Partial<GoalBudgetMoney> | undefined),
		used: rt.used ? { ...rt.used } : { rounds: 0, runMs: 0, tokens: 0, evalCalls: 0, evalTokens: 0 },
		lifetime: { rounds: 0, tokens: 0, evalCalls: 0, evalTokens: 0, ...rt.lifetime, resumes },
		counters: rt.counters ? { ...rt.counters } : { noTool: 0, same: 0, unapproved: 0, evalFail: 0, sameReason: 0 },
		audit: n.attrs.audit === true,
		createdAt,
		updatedAt: rt.updatedAt ?? createdAt,
	};
	if (n.state === "paused") g.pause = rt.pause ? { ...rt.pause } : { reason: pauseReasonOf(n) };
	if (rt.lastTextHash !== undefined) g.lastTextHash = rt.lastTextHash;
	if (rt.lastReasonHash !== undefined) g.lastReasonHash = rt.lastReasonHash;
	if (rt.lastVerdict !== undefined) g.lastVerdict = { ...rt.lastVerdict };
	return g;
};

const fail = (error: string): GoalResult => ({ ok: false, events: [], error });
const noop = (text: string): GoalResult => ({ ok: true, events: [], text });

/** `/goal` のコマンドを、利用者専用イベント (出所は常に user) へ変換する。入力を変更せず決定的。status・draft・何も変わらない操作は events が空 */
export function goalCommandToEvents(cmd: GoalCommand | GoalApproveCommand, state: LedgerState, now: number): GoalResult {
	try {
		return convert(cmd, state, now);
	} catch (e) {
		if (e instanceof EventError) return fail(e.message);
		throw e;
	}
}

function convert(cmd: GoalCommand | GoalApproveCommand, state: LedgerState, now: number): GoalResult {
	const cur = currentGoal(state);
	const live = cur !== null && LIVE.includes(cur.state);
	const U = "user" as const;
	switch (cmd.kind) {
		case "error":
			return fail(cmd.message);
		case "approve": {
			if (!cur || !live) return fail("承認待ちの計画はありません");
			const hash = cur.attrs.planHash;
			if (cur.state === "draft" || cur.state === "planned") {
				if (typeof hash !== "string") return fail("計画がまだ提案されていません");
				return { ok: true, events: [makeEvent("plan.approved", cur.id, { hash }, U)] };
			}
			// active / paused: 承認後に足された task の再承認 (goal の状態は変わらない)
			const p = pendingApproval(state);
			if (p.total === 0 || typeof hash !== "string") return fail("承認待ちの計画はありません");
			return { ok: true, events: [makeEvent("plan.approved", cur.id, { hash }, U)], approval: p };
		}
		case "status": {
			const g = goalStateOf(state);
			if (g) return noop(renderDetail(g, { bypass: false }));
			return noop(live ? `🎯 目標は計画の承認待ちです: ${cur!.title}` : "目標はありません。/goal <目標> で設定します");
		}
		case "draft":
			return { ok: true, events: [], draft: cmd.text };
		case "set": {
			if (live) return fail("既に目標があります。/goal clear で破棄してから設定してください");
			const g = newGoal(cmd.text, cmd.budget, now, { audit: cmd.audit });
			if ("error" in g) return fail(g.error);
			if (state.nodes.has(g.id)) return fail(`目標の id が重複しています: ${g.id}`);
			const hash = hashOf(g.text);
			return {
				ok: true,
				events: [
					makeEvent("goal.created", g.id, { title: g.text, budget: toMoney(g.budget), attrs: { audit: g.audit, createdAt: now } }, U),
					makeEvent("plan.proposed", g.id, { hash }, U),
					makeEvent("plan.approved", g.id, { hash }, U),
				],
			};
		}
		case "pause": {
			if (!cur || !live) return fail("目標がありません");
			if (cur.state === "paused") return noop("既に一時停止中です");
			if (cur.state !== "active") return fail("計画の承認前の目標は一時停止できません");
			return { ok: true, events: [makeEvent("goal.paused", cur.id, { reason: "user" }, U)] };
		}
		case "resume": {
			if (!cur || !live) return fail("目標がありません");
			if (cur.state === "active") return noop("既に実行中です");
			if (cur.state !== "paused") return fail("計画の承認前の目標は再開できません");
			return { ok: true, events: [makeEvent("goal.resumed", cur.id, {}, U)] };
		}
		case "budget": {
			const g = goalStateOf(state);
			if (!cur || !g || cur.state === "done") return fail(cur?.state === "done" ? "完了した目標の予算は変えられません" : "目標がありません");
			const s = setBudget(g, cmd.budget, now);
			if ("error" in s) return fail(s.error);
			const b = toMoney(s.budget);
			if (b.tokens < cur.reserved.tokens || b.ms < cur.reserved.ms) return fail("予算が、子の実行で予約済みの量を下回ります");
			return { ok: true, events: [makeEvent("budget.adjusted", cur.id, { budget: b }, U)] };
		}
		case "clear": {
			if (!cur || !live) return noop("破棄する目標はありません");
			return { ok: true, events: [makeEvent("verdict", cur.id, { verdict: "cancel", reason: "goal clear" }, U)] };
		}
		default:
			return fail(`未知のコマンドです: ${String((cmd as { kind?: unknown })?.kind)}`);
	}
}

export interface GoalRuntimeFacts {
	/** 直近の run の最終行に完了・要判断の申告があるか */
	claim: boolean;
	/** 省略時は counters (noTool・same) から導く */
	stall?: boolean;
	/** 省略時は counters.unapproved */
	unapproved?: number;
	/** 台帳に無い実行中の値 */
	rt?: GoalRuntime;
}

/** arbiter の Facts の goal 部分 (と budgetExhausted)。目標が active でなければ active:false */
export function settleFactsOfGoal(
	state: LedgerState,
	f: GoalRuntimeFacts,
): { goal: { active: boolean; claim: boolean; stall: boolean; unapproved: number }; budgetExhausted: boolean } {
	const g = goalStateOf(state, f.rt ?? {});
	if (!g || g.status !== "active") return { goal: { active: false, claim: false, stall: false, unapproved: 0 }, budgetExhausted: false };
	const stall = f.stall ?? (g.counters.noTool >= THRESHOLDS.noTool || g.counters.same >= THRESHOLDS.same);
	const exhausted =
		g.used.rounds >= g.budget.rounds ||
		g.used.runMs >= g.budget.minutes * 60_000 ||
		(g.budget.tokens !== undefined && g.used.tokens >= g.budget.tokens);
	return {
		goal: { active: true, claim: f.claim === true, stall, unapproved: f.unapproved ?? g.counters.unapproved },
		budgetExhausted: exhausted,
	};
}
