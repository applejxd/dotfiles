// `/goal` の中核 (すべて純関数)。pi の API には触れない。時刻・乱数・環境変数は引数で受ける。入力の状態は変更しない。
// 遷移表と判定順の正本は docs (配線の後に書く)。ここは試験 (test/agents/test_pi_goal_core.py) と対で保つ。
import type {
	Budget,
	BranchEntry,
	Claim,
	GoalCleared,
	GoalCommand,
	GoalState,
	NewGoalOpts,
	PauseReason,
	RunFacts,
	SettleConfig,
	SettleDecision,
	SettleFacts,
	Verdict,
	VerdictFacts,
} from "./goal-types.ts";

export const MAX_TEXT = 1500;
export const DEFAULT_BUDGET: Budget = { rounds: 20, minutes: 90 };
export const LIMITS = { rounds: [1, 200], minutes: [1, 1440], tokens: [1, 1_000_000_000] } as const;
export const THRESHOLDS = { noTool: 2, same: 3, unapproved: 2, sameReason: 3, evalFail: 2 } as const;
export const STATE_ENTRY = "goal-state";
const RESERVED = ["status", "pause", "resume", "clear", "draft", "budget"];

const clone = <T>(x: T): T => structuredClone(x);
const hashOf = (s: string): string => {
	let h = 0x811c9dc5;
	for (const ch of s.trim().replace(/\s+/g, " ")) {
		h ^= ch.codePointAt(0)!;
		h = Math.imul(h, 0x01000193) >>> 0;
	}
	return h.toString(16).padStart(8, "0");
};
const len = (s: string) => [...s].length;

// ---------- 引数 ----------

const parseInt10 = (name: string, v: string | undefined, [lo, hi]: readonly [number, number]): number | string => {
	if (v === undefined || v === "") return `${name} に値がありません`;
	if (!/^\d+$/.test(v)) return `${name} は整数で指定してください: ${v}`;
	const n = Number(v);
	if (n < lo || n > hi) return `${name} は ${lo}〜${hi} の範囲で指定してください: ${v}`;
	return n;
};
const parseTokens = (v: string | undefined): number | string => {
	if (v === undefined || v === "") return "--tokens に値がありません";
	const m = /^(\d+)([kKmM]?)$/.exec(v);
	if (!m) return `--tokens は N・Nk・Nm の形で指定してください: ${v}`;
	const n = Number(m[1]) * (m[2] === "" ? 1 : m[2].toLowerCase() === "k" ? 1000 : 1_000_000);
	const [lo, hi] = LIMITS.tokens;
	if (n < lo || n > hi) return `--tokens は ${lo}〜${hi} の範囲で指定してください: ${v}`;
	return n;
};

/** `/goal` の引数。未知のフラグ・不正な数値・範囲外は必ず error にする (黙って無視しない) */
export function parseGoalArgs(args: string): GoalCommand {
	const src = (args ?? "").trim();
	if (src === "") return { kind: "status" };
	const first = src.split(/\s+/)[0];
	if (RESERVED.includes(first)) {
		const rest = src.slice(first.length).trim();
		if (first === "draft") return rest === "" ? { kind: "error", message: "draft にはメモが要ります: /goal draft <メモ>" } : { kind: "draft", text: rest };
		if (first === "budget") {
			const r = parseFlags(rest, false);
			if ("kind" in r) return r;
			if (r.rest !== "") return { kind: "error", message: `budget は --rounds / --minutes / --tokens だけ取ります: ${r.rest}` };
			if (Object.keys(r.budget).length === 0) return { kind: "error", message: "budget には --rounds / --minutes / --tokens が要ります" };
			return { kind: "budget", budget: r.budget };
		}
		if (rest !== "") return { kind: "error", message: `${first} は引数を取りません (目標の先頭が予約語なら -- で区切る): ${rest}` };
		return { kind: first as "status" | "pause" | "resume" | "clear" };
	}
	const r = parseFlags(src, true);
	if ("kind" in r) return r;
	if (r.rest === "") return { kind: "error", message: "目標が空です" };
	if (!r.dashdash && RESERVED.includes(r.rest.split(/\s+/)[0])) {
		return { kind: "error", message: "目標の先頭が予約語です。-- で区切ってください: /goal -- <目標>" };
	}
	if (len(r.rest) > MAX_TEXT) return { kind: "error", message: `目標が長すぎます (${len(r.rest)} 字 > ${MAX_TEXT} 字)` };
	return { kind: "set", text: r.rest, budget: r.budget, audit: r.audit };
}

type Flags = { budget: Partial<Budget>; audit: boolean; rest: string; dashdash: boolean };

// 先頭のフラグを読み、最初のフラグでない語から後ろ (原文のまま) を rest にする
function parseFlags(src: string, allowAudit: boolean): Flags | { kind: "error"; message: string } {
	const budget: Partial<Budget> = {};
	let audit = false;
	let dashdash = false;
	let rest = src.trim();
	const seen = new Set<string>();
	const err = (message: string) => ({ kind: "error" as const, message });
	while (rest.startsWith("-")) {
		const m = /^(\S+)\s*([\s\S]*)$/.exec(rest)!;
		let tok = m[1];
		let after = m[2];
		if (tok === "--") {
			dashdash = true;
			rest = after;
			break;
		}
		if (!tok.startsWith("--")) return err(`未知のオプションです: ${tok}`);
		let value: string | undefined;
		const eq = tok.indexOf("=");
		if (eq >= 0) {
			value = tok.slice(eq + 1);
			tok = tok.slice(0, eq);
		}
		if (seen.has(tok)) return err(`${tok} が重複しています`);
		seen.add(tok);
		if (tok === "--audit") {
			if (!allowAudit) return err("--audit は目標の設定時だけ使えます");
			if (value !== undefined) return err("--audit は値を取りません");
			audit = true;
			rest = after;
			continue;
		}
		if (tok !== "--rounds" && tok !== "--minutes" && tok !== "--tokens") return err(`未知のオプションです: ${tok}`);
		if (value === undefined) {
			const vm = /^(\S+)\s*([\s\S]*)$/.exec(after);
			value = vm?.[1];
			after = vm?.[2] ?? "";
		}
		const n = tok === "--tokens" ? parseTokens(value) : parseInt10(tok, value, tok === "--rounds" ? LIMITS.rounds : LIMITS.minutes);
		if (typeof n === "string") return err(n);
		budget[tok.slice(2) as "rounds" | "minutes" | "tokens"] = n;
		rest = after;
	}
	return { budget, audit, rest: rest.trim(), dashdash };
}

// ---------- 状態の生成・操作 ----------

/** 新しい目標。上限・範囲外は {error} (parseGoalArgs と二重に検査する) */
export function newGoal(text: string, budget: Partial<Budget>, now: number, opts: NewGoalOpts = {}): GoalState | { error: string } {
	const t = (text ?? "").trim();
	if (t === "") return { error: "目標が空です" };
	if (len(t) > MAX_TEXT) return { error: `目標が長すぎます (${len(t)} 字 > ${MAX_TEXT} 字)` };
	const b = checkBudget({ ...DEFAULT_BUDGET, ...budget });
	if (typeof b === "string") return { error: b };
	return {
		v: 1,
		id: opts.id ?? `g-${Math.max(0, Math.floor(now)).toString(36)}`,
		text: t,
		status: "active",
		budget: b,
		used: { rounds: 0, runMs: 0, tokens: 0, evalCalls: 0, evalTokens: 0 },
		lifetime: { rounds: 0, tokens: 0, evalCalls: 0, evalTokens: 0, resumes: 0 },
		counters: { noTool: 0, same: 0, unapproved: 0, evalFail: 0, sameReason: 0 },
		audit: opts.audit === true,
		createdAt: now,
		updatedAt: now,
	};
}

function checkBudget(b: Budget): Budget | string {
	const inRange = (n: unknown, [lo, hi]: readonly [number, number]) => Number.isInteger(n) && (n as number) >= lo && (n as number) <= hi;
	if (!inRange(b.rounds, LIMITS.rounds)) return `回数は ${LIMITS.rounds[0]}〜${LIMITS.rounds[1]} で指定してください`;
	if (!inRange(b.minutes, LIMITS.minutes)) return `分は ${LIMITS.minutes[0]}〜${LIMITS.minutes[1]} で指定してください`;
	if (b.tokens !== undefined && !inRange(b.tokens, LIMITS.tokens)) return "トークンの上限が範囲外です";
	return b.tokens === undefined ? { rounds: b.rounds, minutes: b.minutes } : { ...b };
}

/** 一時停止 (利用者の操作・入力・中断など外部の理由) */
export function pauseGoal(s: GoalState, reason: PauseReason, now: number, detail?: string): GoalState {
	const n = clone(s);
	if (n.status === "done") return n; // 完了は戻さない
	n.status = "paused";
	n.pause = detail === undefined ? { reason } : { reason, detail };
	n.updatedAt = now;
	return n;
}

/** 再開。used・counters を 0 に戻し、resumes を +1 (lifetime は減らない) */
export function resumeGoal(s: GoalState, now: number): GoalState {
	const n = clone(s);
	if (n.status === "done") return n;
	n.status = "active";
	delete n.pause;
	n.used = { rounds: 0, runMs: 0, tokens: 0, evalCalls: 0, evalTokens: 0 };
	n.counters = { noTool: 0, same: 0, unapproved: 0, evalFail: 0, sameReason: 0 };
	delete n.lastTextHash;
	delete n.lastReasonHash;
	n.lifetime.resumes += 1;
	n.updatedAt = now;
	return n;
}

/** 予算だけ更新 (指定した軸だけ)。範囲外は {error} */
export function setBudget(s: GoalState, budget: Partial<Budget>, now: number): GoalState | { error: string } {
	const b = checkBudget({ ...s.budget, ...budget });
	if (typeof b === "string") return { error: b };
	const n = clone(s);
	n.budget = b;
	n.updatedAt = now;
	return n;
}

// ---------- 申告・集計 ----------

/** 最終の非空行の `GOAL_STATUS: complete` / `GOAL_STATUS: blocked: <理由>` だけ。コードフェンス内・途中の行・引用は無視 */
export function parseClaim(text: string): Claim | null {
	const lines = (text ?? "").split(/\r?\n/);
	let fence: string | null = null;
	let last = -1;
	let lastInFence = false;
	for (let i = 0; i < lines.length; i++) {
		const t = lines[i].trim();
		const f = /^(`{3,}|~{3,})/.exec(t);
		if (f) {
			if (fence === null) fence = f[1][0];
			else if (f[1][0] === fence) fence = null;
			if (t !== "") {
				last = i;
				lastInFence = true;
			}
			continue;
		}
		if (t !== "") {
			last = i;
			lastInFence = fence !== null;
		}
	}
	if (last < 0 || lastInFence) return null;
	const m = /^GOAL_STATUS:[ \t]*(complete|blocked)(?:[ \t]*:[ \t]*(.*))?$/i.exec(lines[last].trim());
	if (!m) return null;
	const kind = m[1].toLowerCase() as "complete" | "blocked";
	if (kind === "complete") return m[2] === undefined ? { kind, detail: "" } : null;
	return { kind, detail: (m[2] ?? "").trim() };
}

const textOf = (content: any): string => {
	if (typeof content === "string") return content;
	if (!Array.isArray(content)) return "";
	return content.filter((c) => c?.type === "text" && typeof c.text === "string").map((c) => c.text).join("\n");
};
const isBoundary = (e: BranchEntry): boolean =>
	(e?.type === "message" && e.message?.role === "user") || (e?.type === "custom_message" && String(e.customType ?? "").startsWith("goal-"));

/** 直近の境界 (user メッセージか goal-* の custom_message) 以降を集計する。branch の形は最小限の仮定 (型の注を参照) */
export function summarizeRun(branch: BranchEntry[]): RunFacts {
	let from = 0;
	for (let i = (branch?.length ?? 0) - 1; i >= 0; i--) {
		if (isBoundary(branch[i])) {
			from = i + 1;
			break;
		}
	}
	let toolCalls = 0;
	let unapproved = 0;
	let tokens = 0;
	let text = "";
	for (const e of (branch ?? []).slice(from)) {
		const m = e?.type === "message" ? e.message : undefined;
		if (!m) continue;
		if (m.role === "assistant") {
			if (Array.isArray(m.content)) toolCalls += m.content.filter((c: any) => c?.type === "toolCall").length;
			text = textOf(m.content);
			const u = m.usage ?? {};
			const n = (Number(u.input) || 0) + (Number(u.output) || 0);
			tokens += Number.isFinite(n) ? n : 0;
		} else if (m.role === "toolResult" && /^not approved:/i.test(textOf(m.content).trimStart())) {
			unapproved += 1;
		}
	}
	return { toolCalls, unapproved, text, tokens, claim: parseClaim(text) };
}

/** branch 全体に review の実施 (task 系の tool で agent が review) があるか。形は仮定 (報告に記載) */
export function detectReview(branch: BranchEntry[]): boolean {
	for (const e of branch ?? []) {
		const m = e?.type === "message" ? e.message : undefined;
		if (m?.role !== "assistant" || !Array.isArray(m.content)) continue;
		for (const c of m.content) {
			if (c?.type !== "toolCall" || !/task/i.test(String(c.name ?? ""))) continue;
			if (/"(agent|type|role|name)"\s*:\s*"review"/.test(JSON.stringify(c.arguments ?? {}))) return true;
		}
	}
	return false;
}

// ---------- 判定 ----------

const pause = (n: GoalState, reason: PauseReason, now: number, detail?: string): { decision: SettleDecision; next: GoalState } => ({
	decision: detail === undefined ? { kind: "pause", reason } : { kind: "pause", reason, detail },
	next: pauseGoal(n, reason, now, detail),
});

/** B2 の判定順 1〜9。skip のときは状態を変えない (数えない) */
export function decideSettle(s: GoalState, f: SettleFacts, cfg: SettleConfig): { decision: SettleDecision; next: GoalState } {
	const keep = (why: string) => ({ decision: { kind: "skip", why } as SettleDecision, next: clone(s) });
	// 1
	if (s.status !== "active") return keep("not-active");
	if (f.mode === "print" || f.mode === "json") return keep("non-interactive");
	// 2
	if (f.outcome === "error") return pause(s, "run-error", f.now);
	if (f.outcome === "aborted" && !f.compacting) return pause(s, "interrupted", f.now);
	// 3
	if (f.compacting) return keep("compacting");
	if (f.planMode) return keep("plan");
	if (f.pending) return keep("pending");
	if (f.bgBusy > 0) return keep("background");
	// 4
	const n = clone(s);
	const r = f.run;
	n.used.rounds += 1;
	n.used.runMs += Math.max(0, f.runMs);
	n.used.tokens += r.tokens;
	n.lifetime.rounds += 1;
	n.lifetime.tokens += r.tokens;
	n.counters.noTool = r.toolCalls === 0 ? n.counters.noTool + 1 : 0;
	n.counters.unapproved = r.unapproved > 0 ? n.counters.unapproved + 1 : 0;
	if (r.text.trim() === "") {
		n.counters.same = 0;
		delete n.lastTextHash;
	} else {
		const h = hashOf(r.text);
		n.counters.same = h === n.lastTextHash ? n.counters.same + 1 : 1;
		n.lastTextHash = h;
	}
	n.updatedAt = f.now;
	// 5
	if (n.used.rounds >= n.budget.rounds) return pause(n, "rounds", f.now, `${n.used.rounds}/${n.budget.rounds}`);
	if (n.used.runMs >= n.budget.minutes * 60_000) return pause(n, "minutes", f.now, `${Math.floor(n.used.runMs / 60_000)}/${n.budget.minutes}`);
	if (n.budget.tokens !== undefined && n.used.tokens >= n.budget.tokens) return pause(n, "tokens", f.now, `${n.used.tokens}/${n.budget.tokens}`);
	// 6
	if (n.counters.unapproved >= THRESHOLDS.unapproved) return pause(n, "unapproved", f.now, `${n.counters.unapproved} 回連続`);
	// 7
	if (r.claim || cfg.evalMode === "every") return { decision: { kind: "evaluate", why: "claim", claim: r.claim }, next: n };
	// 8
	if (n.counters.noTool >= THRESHOLDS.noTool) {
		return { decision: { kind: "evaluate", why: "stall", claim: null, detail: `ツール呼び出しなし ${n.counters.noTool} 回` }, next: n };
	}
	if (n.counters.same >= THRESHOLDS.same) {
		return { decision: { kind: "evaluate", why: "stall", claim: null, detail: `同じ内容 ${n.counters.same} 回` }, next: n };
	}
	// 9
	return { decision: { kind: "continue" }, next: n };
}

/** 評価役の結果 (null は評価の失敗) を状態へ反映する。評価の呼び出しの数・トークンも加算する */
export function applyVerdict(
	s: GoalState,
	v: Verdict | null,
	now: number,
	f: VerdictFacts,
): { decision: SettleDecision; next: GoalState } {
	const n = clone(s);
	const et = Math.max(0, f.evalTokens ?? 0);
	n.used.evalCalls += 1;
	n.used.evalTokens += et;
	n.used.tokens += et;
	n.lifetime.evalCalls += 1;
	n.lifetime.evalTokens += et;
	n.lifetime.tokens += et;
	n.updatedAt = now;
	const over = (): { decision: SettleDecision; next: GoalState } | null =>
		n.budget.tokens !== undefined && n.used.tokens >= n.budget.tokens ? pause(n, "tokens", now, `${n.used.tokens}/${n.budget.tokens}`) : null;

	if (v === null) {
		n.counters.evalFail += 1;
		if (n.counters.evalFail >= THRESHOLDS.evalFail) return pause(n, "eval-failed", now, `${n.counters.evalFail} 回連続`);
		return over() ?? { decision: { kind: "continue" }, next: n };
	}
	n.counters.evalFail = 0;
	n.lastVerdict = { verdict: v.verdict, reason: v.reason, at: now };
	if (v.verdict === "done") {
		if (n.audit && !f.auditSeen) {
			return over() ?? { decision: { kind: "continue", reason: "監査 (review) が未実施です。review を依頼してから完了を申告してください" }, next: n };
		}
		n.status = "done";
		delete n.pause;
		return { decision: { kind: "done" }, next: n };
	}
	if (v.verdict === "blocked") return pause(n, "blocked", now, v.reason);
	// continue
	if (f.why === "stall") return pause(n, "stalled", now, v.reason);
	const h = hashOf(v.reason);
	n.counters.sameReason = h === n.lastReasonHash ? n.counters.sameReason + 1 : 1;
	n.lastReasonHash = h;
	if (n.counters.sameReason >= THRESHOLDS.sameReason) return pause(n, "stalled", now, `同じ理由が ${n.counters.sameReason} 回: ${v.reason}`);
	return over() ?? { decision: { kind: "continue", reason: v.reason }, next: n };
}

// ---------- メッセージ ----------

const FORMAT_GUIDE = [
	"完了したら、条件ごとに証拠 (実行したコマンドと出力) を示し、最終行に `GOAL_STATUS: complete` と書いてください。",
	"利用者の判断・承認が要るときは、離席中のことがあるので ask で待たず、最終行に `GOAL_STATUS: blocked: <理由>` と書いてください。",
];

const remaining = (s: GoalState) => ({
	rounds: Math.max(0, s.budget.rounds - s.used.rounds),
	minutes: Math.max(0, Math.ceil((s.budget.minutes * 60_000 - s.used.runMs) / 60_000)),
});

/** 開始メッセージ (user メッセージとして送る) */
export function buildStart(s: GoalState): string {
	const r = remaining(s);
	return [
		`【目標】次の目標を、完了条件が満たされるまで自走して進めてください (上限: 回数 ${s.budget.rounds}・${s.budget.minutes} 分)。`,
		"",
		s.text,
		"",
		"最初に、手順を todo に add してください。完了条件が曖昧なら、測れる形にして todo に書いてください。",
		...FORMAT_GUIDE,
		"承認が拒否された操作は繰り返さず、別の進め方をとってください。",
		"ツール呼び出しなしの応答や同じ内容の繰り返しは、停滞として止められます。",
		`残り: あと ${r.rounds} 回・${r.minutes} 分。` + (s.audit ? " 完了の前に review (監査) を依頼してください。" : ""),
	].join("\n");
}

/** 継続メッセージ (custom_message `goal-continue`)。目標の原文を全文再掲する */
export function buildContinuation(s: GoalState, ctx: { reason?: string; wake?: string } = {}): string {
	const r = remaining(s);
	const lines = [`【目標の続行 ${s.used.rounds + 1}/${s.budget.rounds}】`, "", "目標 (原文):", s.text, ""];
	if (ctx.wake) lines.push(ctx.wake, "");
	if (ctx.reason) lines.push(`評価役の理由: ${ctx.reason}`, "");
	lines.push(
		`残り: あと ${r.rounds} 回・${r.minutes} 分。完了条件を満たすまで続けてください。`,
		...FORMAT_GUIDE,
		"承認が拒否された操作は繰り返さず、別の進め方をとってください。",
		"ツール呼び出しなしの応答や同じ内容の繰り返しは、停滞として止められます。",
		"これは利用者が設定した目標の続行であり、これまでの指示・制約は変わりません。",
	);
	if (s.audit) lines.push("完了の前に review (監査) を依頼してください。");
	return lines.join("\n");
}

// ---------- 表示 ----------

const kfmt = (n: number) => (n >= 1_000_000 ? `${(n / 1_000_000).toFixed(1)}m` : n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n));

function pauseLabel(s: GoalState): string {
	const p = s.pause;
	const d = p?.detail ? `(${p.detail})` : "";
	switch (p?.reason) {
		case "user":
			return "利用者の操作 — /goal resume";
		case "input":
			return "利用者の入力 — /goal resume";
		case "interrupted":
			return "中断 (Esc) — /goal resume";
		case "restored":
			return "セッションの復元 — /goal resume";
		case "rounds":
			return `回数の上限 ${s.used.rounds}/${s.budget.rounds} — /goal budget → resume`;
		case "minutes":
			return `時間の上限 ${Math.floor(s.used.runMs / 60_000)}/${s.budget.minutes} 分 — /goal budget → resume`;
		case "tokens":
			return `トークンの上限 ${kfmt(s.used.tokens)}/${kfmt(s.budget.tokens ?? 0)} — /goal budget → resume`;
		case "stalled":
			return `停滞${d}`;
		case "blocked":
			return `要判断${d}`;
		case "unapproved":
			return `承認の拒否が続いた${d}`;
		case "run-error":
			return "実行エラー — /goal resume";
		case "eval-failed":
			return `評価役の失敗が続いた${d}`;
		default:
			return "理由不明";
	}
}

/** フッター 1 行 */
export function renderStatus(s: GoalState, x: { waiting: number }): string {
	if (s.status === "done") return "🎯 完了 ✓";
	if (s.status === "paused") return `🎯 一時停止: ${pauseLabel(s)}`;
	const tok = s.budget.tokens !== undefined ? ` · ${kfmt(s.used.tokens)}/${kfmt(s.budget.tokens)} tok` : "";
	const wait = x.waiting > 0 ? `待機中(子${x.waiting}) ` : "";
	return `🎯 ${wait}${s.used.rounds}/${s.budget.rounds}回 · ${Math.floor(s.used.runMs / 60_000)}/${s.budget.minutes}分${tok}`;
}

/** `/goal status` の詳細 */
export function renderDetail(s: GoalState, x: { bypass: boolean }): string {
	const lines = [`🎯 目標 (${s.status}) id ${s.id}`, `目標: ${s.text}`];
	if (s.status === "paused") lines.push(`一時停止: ${pauseLabel(s)}`);
	const tokens = s.budget.tokens !== undefined ? `${kfmt(s.used.tokens)}/${kfmt(s.budget.tokens)}` : `${kfmt(s.used.tokens)} (上限なし)`;
	lines.push(`続行 ${s.used.rounds}/${s.budget.rounds} · 作業 ${Math.floor(s.used.runMs / 60_000)}/${s.budget.minutes} 分 · トークン ${tokens}`);
	const lv = s.lastVerdict ? ` · 直近: ${s.lastVerdict.verdict}「${s.lastVerdict.reason}」` : "";
	lines.push(`評価役: ${s.used.evalCalls} 回 (約 ${kfmt(s.used.evalTokens)} tok)${lv}`);
	if (s.audit) lines.push("監査: 完了の前に review が要ります");
	lines.push("上限・停滞・利用者の入力・Esc で一時停止します。止める: /goal pause · 破棄: /goal clear");
	lines.push(
		x.bypass
			? "bypass: ON (ask は確認なしで通る。外部送信・公開の confirm と deny は残る)"
			: "bypass: OFF (ask と confirm は確認が出る)",
	);
	return lines.join("\n");
}

// ---------- 復元 ----------

/** branch の最後の `goal-state` から復元する。active は paused(restored)、done・cleared は無し。書き込まず、冪等 */
export function restore(branch: BranchEntry[]): GoalState | undefined {
	let data: GoalState | GoalCleared | undefined;
	for (const e of branch ?? []) {
		if (e?.type === "custom" && e.customType === STATE_ENTRY && e.data && typeof e.data === "object") data = e.data;
	}
	if (!data || data.v !== 1 || (data as GoalCleared).cleared === true) return undefined;
	const g = data as GoalState;
	if (typeof g.id !== "string" || typeof g.text !== "string" || !g.budget || !g.used || !g.lifetime || !g.counters) return undefined;
	if (g.status === "done") return undefined;
	const n = clone(g);
	if (n.status === "active") {
		n.status = "paused";
		n.pause = { reason: "restored" };
	}
	return n;
}
