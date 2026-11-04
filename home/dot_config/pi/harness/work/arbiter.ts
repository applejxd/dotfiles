// 継続の調停 (settle arbiter。純関数。pi の API・fs・index.ts なし)。agent_before_settle の判断を 1 か所にまとめる。
// 提案者 (checkpoint・todo・goal・children) は副作用もハンドラも持たず、事実 (Facts) から Proposal を返すだけ。
// arbitrate が優先順位表 (上から最初に当たる行が勝つ) で 1 つに決める。entries は常に 0 または 1 件。wake は effects の中だけ。
// 迷ったら継続しない (失敗は閉じる)。see docs/spec/work/arbiter.md
import { select } from "./notices.ts";
import type { NoticeCtx, NoticeEvent, Show } from "./notices.ts";

export type Phase = "idle" | "saving" | "compacting" | "goal" | "plan";
/** settle: agent_before_settle の時点 / resume: 圧縮の完了後 (turn の外。継続は wake で起こす) */
export type Trigger = "settle" | "resume";
export type Outcome = "completed" | "aborted" | "error";

/** その時点の事実。台帳の投影・各拡張の状態を、呼び出し側が写して渡す */
export interface Facts {
	trigger: Trigger;
	mode: "interactive" | "print" | "json";
	child: boolean;
	outcome: Outcome;
	phase: Phase;
	/** 圧縮の実行中 */
	compacting: boolean;
	/** 利用者の入力 (hasPendingMessages) がある */
	userInput: boolean;
	/** 直近の連続継続の回数と上限 */
	streak: number;
	maxStreak: number;
	/** ゴールの予算が尽きた */
	budgetExhausted: boolean;
	checkpoint: { percent: number | null; threshold: number; cooldown: boolean; llmStep: boolean; disabled: boolean; prompt: string };
	/** ラベルは「#1 文面」の短い形 */
	todo: { disabled: boolean; doing: string[]; blocked: string[]; queued: string[]; nudged: boolean; nudgedWaiting: boolean };
	goal: { active: boolean; claim: boolean; stall: boolean; unapproved: number };
	children: { failed: number; parentStep: boolean; newUserWait: boolean };
}

/** 提案者が返す効果。wake と、select を通した notify の見せ方は arbitrate だけが作る */
export type ProposedEffect =
	| { kind: "notify"; event: NoticeEvent; ctx?: NoticeCtx; text: string }
	| { kind: "append_event"; name: string; data?: Record<string, unknown> }
	| { kind: "checkpoint"; action: "compact" | "cancel" };

export type Effect =
	| { kind: "wake"; content: string; customType: string; why: string }
	| { kind: "notify"; event: NoticeEvent; show: Show; text: string; why: string }
	| { kind: "append_event"; name: string; data?: Record<string, unknown> }
	| { kind: "checkpoint"; action: "compact" | "cancel" };

export interface ProposedEntry {
	customType: string;
	content: string;
	details?: Record<string, unknown>;
}

export interface Proposal {
	by: "checkpoint" | "todo" | "goal" | "children";
	/** continue: entry を添えて続ける / stay: 続けない (効果は有効) / alert: 続けない・利用者へ知らせる (効果は有効) */
	want: "continue" | "stay" | "alert";
	/** 優先順位表の行 (4〜9。小さいほど先) */
	priority: number;
	entry?: ProposedEntry;
	effects: ProposedEffect[];
	reason: string;
}

export interface Entry {
	type: "custom_message";
	customType: string;
	content: string;
	display: true;
	details?: Record<string, unknown>;
}

export interface Decision {
	continue: boolean;
	entries: Entry[];
	effects: Effect[];
	why: string;
	/** 当たった優先順位表の行 (0〜9。3 は安全側の停止: 利用者の入力・エラー・連続上限) */
	row: number;
}

export const MERGE_MAX = 600;
export const PROVIDERS = ["checkpoint", "todo", "goal", "children"] as const;
const UNAPPROVED_LIMIT = 2;

const stay = (by: Proposal["by"], priority: number, reason: string, effects: ProposedEffect[] = []): Proposal => ({
	by,
	want: "stay",
	priority,
	effects,
	reason,
});
const clip = (s: string, n: number): string => (s.length > n ? `${s.slice(0, n - 1)}…` : s);
/** 保存中に見送る (圧縮中・利用者の入力) ときは、古い保存周期を後続ターンへ持ち越さないよう取りやめる */
const staleSaving = (f: Facts): Effect[] => (f.phase === "saving" ? [{ kind: "checkpoint", action: "cancel" }] : []);

/** 文脈使用率の保存 (autocheckpoint.ts の idle / saving 相当)。閾値超えで LLM の指示つき、機械だけなら直接圧縮 */
export function proposeCheckpoint(f: Facts): Proposal {
	const c = f.checkpoint;
	if (c.disabled || f.trigger !== "settle") return stay("checkpoint", 4, "無効、または settle ではない");
	if (f.phase === "saving") {
		// 保存の継続が終わった。エラーで終わっても圧縮は進める (中断は arbitrate の行 1 が周期ごと取りやめる)
		return stay("checkpoint", 4, "保存が終わったので圧縮を起動する", [{ kind: "checkpoint", action: "compact" }]);
	}
	if (f.phase !== "idle" || f.outcome !== "completed" || c.cooldown) return stay("checkpoint", 4, "保存の条件外");
	if (typeof c.percent !== "number" || c.percent < c.threshold) return stay("checkpoint", 4, "閾値未満");
	const note: ProposedEffect = { kind: "notify", event: "autosave", ctx: { llmStep: c.llmStep }, text: `文脈 ${Math.round(c.percent)}%` };
	if (!c.llmStep) return stay("checkpoint", 4, "機械の保存だけ。直接圧縮する", [{ kind: "checkpoint", action: "compact" }, note]);
	return {
		by: "checkpoint",
		want: "continue",
		priority: 4,
		entry: { customType: "autocheckpoint", content: c.prompt, details: { percent: c.percent } },
		effects: [{ kind: "append_event", name: "checkpoint.saving" }, note],
		reason: "閾値超え。保存を指示する",
	};
}

/** todo のリマインド (todo/index.ts の before_settle 相当)。作業中のまま終わる・待ちと未着手が併存 */
export function proposeTodo(f: Facts): Proposal {
	const t = f.todo;
	if (t.disabled || f.trigger !== "settle" || f.outcome !== "completed") return stay("todo", 7, "無効、または completed の settle ではない");
	let content: string;
	let flag: string;
	if (t.doing.length > 0) {
		if (t.nudged) return stay("todo", 7, "作業中の注意は済み");
		flag = "todo.nudged";
		content = `作業中 (in_progress) のまま終わろうとしています: ${t.doing.join(" / ")}。実際に終わっていれば done にして、続きがあれば作業を続けてください。`;
	} else {
		if (t.nudgedWaiting || t.blocked.length === 0 || t.queued.length === 0) return stay("todo", 7, "リマインドは不要");
		flag = "todo.nudgedWaiting";
		content =
			`待ち (blocked) の項目があり、着手できる未着手 (pending) も残っています。待ち: ${t.blocked.slice(0, 3).join(" / ")}。` +
			`未着手: ${t.queued.slice(0, 5).join(" / ")}。承認や確認の待ちは止まる理由ではありません。依存しない未着手を続けてください。`;
	}
	return {
		by: "todo",
		want: "continue",
		priority: 7,
		entry: { customType: "todo-reminder", content, details: { open: t.doing.length + t.blocked.length + t.queued.length } },
		effects: [{ kind: "append_event", name: flag }],
		reason: "todo のリマインド",
	};
}

/** /goal の継続判定 (goal-core.ts の decideSettle の順 5〜9 相当): 予算は完了の申告があれば先に評価、承認の連続失敗は triage */
export function proposeGoal(f: Facts): Proposal {
	const g = f.goal;
	if (!g.active) return stay("goal", 7, "ゴールなし");
	const ev = (c: string): ProposedEntry => ({ customType: "goal", content: c });
	if (f.budgetExhausted) {
		if (g.claim) return { by: "goal", want: "continue", priority: 5, entry: ev("予算は尽きましたが、完了の申告があるので先に評価します。"), effects: [], reason: "予算超過でも申告を先に評価" };
		return { ...stay("goal", 5, "予算が尽きた"), want: "alert", effects: [{ kind: "notify", event: "budget.paused", text: "予算が尽きた" }] };
	}
	if (g.unapproved >= UNAPPROVED_LIMIT) {
		return { by: "goal", want: "continue", priority: 6, entry: ev("承認されない操作が続いています。方針を見直してください。"), effects: [], reason: "承認の連続失敗 (triage)" };
	}
	if (g.claim || g.stall) {
		return { by: "goal", want: "continue", priority: 8, entry: ev(g.claim ? "完了の申告を評価します。" : "停滞しています。評価します。"), effects: [], reason: "申告・停滞の評価" };
	}
	return { by: "goal", want: "continue", priority: 7, entry: ev("ゴールの続きを進めてください。"), effects: [], reason: "ゴールの継続" };
}

/** 子の完了: 失敗は triage (P6)、親の手順が要る完了は P7、新しい user 待ちは起こさず alert (P9) */
export function proposeChildren(f: Facts): Proposal {
	const c = f.children;
	if (c.failed > 0) {
		return {
			by: "children",
			want: "continue",
			priority: 6,
			entry: { customType: "children", content: `子の失敗が ${c.failed} 件あります。原因を確認して対応を判断してください。` },
			effects: [{ kind: "notify", event: "run.failed", ctx: { needsFix: true }, text: `子の失敗 ${c.failed} 件` }],
			reason: "子の失敗 (triage)",
		};
	}
	if (c.newUserWait) {
		return { ...stay("children", 9, "利用者の判断待ち"), want: "alert", effects: [{ kind: "notify", event: "wait.confirm", text: "利用者の判断待ち" }] };
	}
	if (c.parentStep) {
		return {
			by: "children",
			want: "continue",
			priority: 7,
			entry: { customType: "children", content: "子が完了しました。親の手順 (確認・コミット・要約) を進めてください。" },
			effects: [],
			reason: "親の手順が要る",
		};
	}
	return stay("children", 9, "子の通知なし");
}

export function propose(f: Facts): Proposal[] {
	return [proposeCheckpoint(f), proposeGoal(f), proposeChildren(f), proposeTodo(f)];
}

const none = (row: number, why: string, effects: Effect[] = []): Decision => ({ continue: false, entries: [], effects, why, row });
/** 通知は select を必ず通す (通さない通知を出さない)。表に無い組は例外 → 呼び出し側 (arbitrate) が閉じる */
const toNotify = (e: Extract<ProposedEffect, { kind: "notify" }>): Effect => {
	const d = select(e.event, e.ctx ?? {});
	return { kind: "notify", event: e.event, show: d.show, text: e.text, why: d.why };
};
/** 提案者の効果を出力の型へ。wake は提案者からは受け取らない (arbitrate だけが作る) */
const sanitize = (e: ProposedEffect): Effect | null => {
	if (!e || typeof e !== "object") return null;
	if (e.kind === "notify") return toNotify(e);
	if (e.kind === "append_event") return typeof e.name === "string" ? { kind: "append_event", name: e.name, ...(e.data ? { data: { ...e.data } } : {}) } : null;
	if (e.kind === "checkpoint") return e.action === "compact" || e.action === "cancel" ? { kind: "checkpoint", action: e.action } : null;
	return null;
};
const uniq = (xs: Effect[]): Effect[] => {
	const seen = new Set<string>();
	return xs.filter((x) => (seen.has(JSON.stringify(x)) ? false : (seen.add(JSON.stringify(x)), true)));
};
const effectsOf = (ps: Proposal[]): Effect[] =>
	uniq(ps.flatMap((p) => (Array.isArray(p.effects) ? p.effects : []).map(sanitize).filter((x): x is Effect => x !== null)));

const validFacts = (f: any): boolean =>
	!!f &&
	typeof f === "object" &&
	(f.trigger === "settle" || f.trigger === "resume") &&
	["interactive", "print", "json"].includes(f.mode) &&
	["completed", "aborted", "error"].includes(f.outcome) &&
	["idle", "saving", "compacting", "goal", "plan"].includes(f.phase) &&
	Number.isFinite(f.streak) &&
	Number.isFinite(f.maxStreak);

/**
 * 優先順位表。上から最初に当たる行が勝つ。純関数 (入力を変えない・決定的)。entries は 0 または 1 件。
 * 0 子/print/json → なし / 1 中断 → なし (保存周期の取りやめ・goal の pause) / 2 圧縮中・保存→圧縮・計画中 → なし /
 * 3 利用者の入力・エラー応答・連続上限 → なし / 4 保存 (compact は直接) / 5 予算超過で申告 → 先に評価 / 6 失敗の triage /
 * 7 LLM の仕事が ready / 8 申告・停滞の評価 / 9 待ちだけ → turn を起こさない
 */
export function arbitrate(facts: Facts, proposals: Proposal[]): Decision {
	try {
		return decide(facts, proposals);
	} catch (e: any) {
		return none(3, `調停に失敗したので継続しない: ${e?.message ?? e}`);
	}
}

function decide(f: Facts, proposals: Proposal[]): Decision {
	if (!validFacts(f) || !Array.isArray(proposals)) return none(3, "事実が不正なので継続しない");
	if (f.child || f.mode !== "interactive") return none(0, "子・print・json は継続しない");
	if (f.outcome === "aborted") {
		const fx: Effect[] = [];
		if (f.phase === "saving") fx.push({ kind: "checkpoint", action: "cancel" });
		if (f.goal?.active) fx.push({ kind: "append_event", name: "goal.paused", data: { reason: "aborted" } });
		return none(1, "中断 (Esc)。継続しない", fx);
	}
	if (f.compacting || f.phase === "compacting" || f.phase === "plan") return none(2, "圧縮中・計画中は継続しない", staleSaving(f));
	if (f.userInput) return none(3, "利用者の入力を優先する", staleSaving(f));
	if (f.outcome === "error") {
		const fx: Effect[] = [toNotify({ kind: "notify", event: "run.failed", ctx: { needsFix: true }, text: "エラー応答" })];
		if (f.phase === "saving" && f.trigger === "settle") fx.push({ kind: "checkpoint", action: "compact" });
		return none(3, "エラー応答。継続しない", fx);
	}
	if (f.streak >= f.maxStreak) {
		return none(3, "連続継続の上限", [toNotify({ kind: "notify", event: "goal.stopped", ctx: { needsEval: false }, text: "連続継続の上限" })]);
	}
	const alerts = proposals.filter((p) => p?.want === "alert");
	const stays = proposals.filter((p) => p?.want === "stay");
	const aEffects = effectsOf(alerts);
	// compact (直接の圧縮) は継続と両立しない。保存の続き・機械の保存はここで終える
	const compactFx = effectsOf(stays).filter((e) => e.kind === "checkpoint" && e.action === "compact");
	if (compactFx.length > 0) return none(4, "保存→圧縮。継続しない", uniq([...effectsOf(stays), ...aEffects]));
	let cands = proposals
		.map((p, i) => ({ p, i }))
		.filter(({ p }) => p?.want === "continue" && p.entry && typeof p.entry.content === "string" && Number.isFinite(p.priority));
	if (f.trigger === "resume") cands = cands.filter(({ p }) => p.priority >= 5 && p.priority <= 8);
	if (f.budgetExhausted) cands = cands.filter(({ p }) => p.priority === 4 || p.priority === 5);
	cands.sort((a, b) => a.p.priority - b.p.priority || a.i - b.i);
	const base = [...effectsOf(stays), ...aEffects];
	if (cands.length === 0) return none(9, "続ける仕事がない。turn を起こさない", uniq(base));
	const win = cands[0].p;
	const row = Math.max(4, Math.min(9, Math.trunc(win.priority)));
	// P5〜P8 は 1 件にまとめる (置換で上書きされない)。P4 (保存) は単独
	const used = row <= 4 ? [win] : cands.filter(({ p }) => p.priority >= 5 && p.priority <= 8).map(({ p }) => p);
	const content = row <= 4 ? win.entry!.content : clip(used.map((p) => p.entry!.content).join("\n"), MERGE_MAX);
	const customType = win.entry!.customType;
	const fx = uniq([...base, ...effectsOf(used)]);
	if (f.trigger === "resume") {
		fx.push({ kind: "wake", content, customType, why: win.reason });
		return { continue: false, entries: [], effects: fx, why: `行 ${row}: ${win.by} (再開の wake)`, row };
	}
	const entry: Entry = { type: "custom_message", customType, content, display: true, ...(win.entry!.details ? { details: { ...win.entry!.details } } : {}) };
	return { continue: true, entries: [entry], effects: fx, why: `行 ${row}: ${win.by}: ${win.reason}`, row };
}

/** 提案者を全部呼んで調停する (配線の入口) */
export function settle(facts: Facts): Decision {
	try {
		return arbitrate(facts, propose(facts));
	} catch (e: any) {
		return none(3, `提案に失敗したので継続しない: ${e?.message ?? e}`);
	}
}
