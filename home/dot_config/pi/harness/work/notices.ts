// 通知の選別の表 (L1。純関数・データ駆動。pi の API・fs なし)。事象 × 状態 → 利用者への見せ方とモデルの起床。
// 不変条件: user 待ち (wait.*) は必ず alert (silent にしない)。失敗・時間切れ・stall・形式違反・警告は必ず line 以上 (見落とさない)。
// 表は全セルを列挙できるデータ (NOTICE_TABLE)。select() はそれを引くだけで、表に無い組は例外 (黙って silent にしない)。
// see docs/spec/work/notices.md

export type Show = "silent" | "line" | "alert";
/** モデルの起床: true=すぐ / "batch"=まとめて 1 回 / false=しない */
export type Wake = boolean | "batch";

export type NoticeEvent =
	| "run.ok"
	| "run.failed"
	| "run.timeout"
	| "run.stall"
	| "run.format"
	| "run.warning"
	| "wait.plan-approval"
	| "wait.integrate"
	| "wait.confirm"
	| "wait.manual-check"
	| "budget.80"
	| "budget.paused"
	| "resource.429"
	| "goal.done"
	| "goal.stopped"
	| "compact.start"
	| "compact.end"
	| "autosave"
	| "autoresume";

export interface Decision {
	show: Show;
	wake: Wake;
	why: string;
}

/** 状態の文脈。どのセルを引くかを決める真偽だけ (未指定は各事象の安全側) */
export interface NoticeCtx {
	/** run.ok: 親の手順 (commit・要約など) が次に要る */
	parentStep?: boolean;
	/** 失敗・警告系: 要修正 (既定 true = 起こす) */
	needsFix?: boolean;
	/** goal.done / goal.stopped: 評価役の判定が要る */
	needsEval?: boolean;
	/** compact.*・autoresume: 進められる作業が台帳にある */
	hasWork?: boolean;
	/** autosave: LLM の仕事 (docs への反映) が残っている (機械の保存だけなら false) */
	llmStep?: boolean;
}

export interface Row extends Decision {
	event: NoticeEvent;
	/** 状態の名前 (variantOf が返す) */
	variant: string;
}

const row = (event: NoticeEvent, variant: string, show: Show, wake: Wake, why: string): Row => ({ event, variant, show, wake, why });

const FAILURES = ["run.failed", "run.timeout", "run.stall", "run.format", "run.warning"] as const;
const WAITS = ["wait.plan-approval", "wait.integrate", "wait.confirm", "wait.manual-check"] as const;

export const NOTICE_TABLE: readonly Row[] = [
	row("run.ok", "deterministic", "silent", false, "次が決定的。親は不要 (パネルと journal だけ)"),
	row("run.ok", "parent-step", "silent", "batch", "親の手順が要る。まとめて 1 回だけ起こす (パネルに ⏳親)"),
	...FAILURES.flatMap((e) => [
		row(e, "fix", "line", true, "見落とし防止。要修正なので親を起こす"),
		row(e, "info", "line", false, "見落とし防止。修正は要らないので起こさない"),
	]),
	...WAITS.map((e) => row(e, "any", "alert", false, "判断の要求。1 行 + BEL + パネルの最上段。待ちを機械で埋めない")),
	row("budget.80", "any", "line", false, "状態の通知"),
	row("budget.paused", "any", "line", false, "状態の通知"),
	row("resource.429", "any", "line", false, "一時停止の通知"),
	row("goal.done", "eval", "alert", true, "最終確認。評価が要る"),
	row("goal.done", "none", "alert", false, "最終確認"),
	row("goal.stopped", "eval", "alert", true, "停止の報告。評価が要る"),
	row("goal.stopped", "none", "alert", false, "停止の報告"),
	row("compact.start", "work", "silent", false, "圧縮中は起こさない"),
	row("compact.start", "idle", "silent", false, "圧縮中は起こさない"),
	row("compact.end", "work", "silent", true, "進められる作業があるときだけ再開する"),
	row("compact.end", "idle", "silent", false, "待ちだけなら turn を起こさない"),
	row("autosave", "llm", "line", true, "LLM の仕事が残る。指示は 3 行以内"),
	row("autosave", "mechanical", "silent", false, "機械の保存だけ。journal に残す"),
	row("autoresume", "work", "silent", true, "進められる作業があるときだけ 2 行の継続を 1 本"),
	row("autoresume", "idle", "silent", false, "待ちだけなら turn を起こさない"),
];

/** 状態の文脈から、表の状態の名前を決める */
export function variantOf(event: NoticeEvent, ctx: NoticeCtx = {}): string {
	switch (event) {
		case "run.ok":
			return ctx.parentStep ? "parent-step" : "deterministic";
		case "run.failed":
		case "run.timeout":
		case "run.stall":
		case "run.format":
		case "run.warning":
			return ctx.needsFix === false ? "info" : "fix";
		case "goal.done":
		case "goal.stopped":
			return ctx.needsEval ? "eval" : "none";
		case "compact.start":
		case "compact.end":
		case "autoresume":
			return ctx.hasWork ? "work" : "idle";
		case "autosave":
			return ctx.llmStep ? "llm" : "mechanical";
		default:
			return "any";
	}
}

/** 事象と文脈から見せ方を引く。表に無い組は例外 (黙って silent にしない) */
export function select(event: NoticeEvent, ctx: NoticeCtx = {}): Decision {
	const variant = variantOf(event, ctx);
	const r = NOTICE_TABLE.find((x) => x.event === event && x.variant === variant);
	if (!r) throw new Error(`通知の選別の表に無い組: ${event}/${variant}`);
	return { show: r.show, wake: r.wake, why: r.why };
}

/** 全事象 (表から導く) */
export function allEvents(): NoticeEvent[] {
	return [...new Set(NOTICE_TABLE.map((r) => r.event))];
}

/** 事象ごとの状態の一覧 (全セルの列挙) */
export function variantsOf(event: NoticeEvent): string[] {
	return NOTICE_TABLE.filter((r) => r.event === event).map((r) => r.variant);
}

const SHOW_RANK: Record<Show, number> = { silent: 0, line: 1, alert: 2 };
/** a が b 以上に目立つか */
export const atLeast = (a: Show, b: Show): boolean => SHOW_RANK[a] >= SHOW_RANK[b];

/** チャットに出る行数 (line・alert は 1 行。alert の BEL とパネルの最上段は行に数えない) */
export function visibleLines(show: Show): number {
	return show === "silent" ? 0 : 1;
}

/** 表が不変条件を満たすかを検査する (違反の説明の配列。空なら合格) */
export function checkInvariants(table: readonly Row[] = NOTICE_TABLE): string[] {
	const bad: string[] = [];
	for (const r of table) {
		if (r.event.startsWith("wait.") && r.show !== "alert") bad.push(`${r.event}/${r.variant}: user 待ちが alert でない`);
		if ((FAILURES as readonly string[]).includes(r.event) && !atLeast(r.show, "line")) bad.push(`${r.event}/${r.variant}: 失敗・警告が line 未満`);
		if (!r.why) bad.push(`${r.event}/${r.variant}: 理由が空`);
	}
	return bad;
}
