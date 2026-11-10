// 並列化の方式の選択表 (7 方式)。表を上から評価して決める。LLM は使わない。純関数。
// 誤選択の検出と学習 (有界・畳み込み) もここ。see docs/spec/work/scheduler.md#並列化の方式

export type Method = "fanout" | "shared" | "worktree" | "serial" | "speculative" | "race" | "pipeline";
export const METHODS: readonly Method[] = ["fanout", "shared", "worktree", "serial", "speculative", "race", "pipeline"];

export type Level = "low" | "mid" | "high";
export type Isolation = "none" | "shared" | "worktree";

export interface StrategyInput {
	kind: "ro" | "edit" | "check";
	/** writes が実行中 (または先に起動する) task と重なる */
	overlap: boolean;
	size: "S" | "M" | "L";
	/** 依存の状態: none = 全部 done / running = 上流が実行中 / pending = 上流が未着手 */
	upstream: "none" | "running" | "pending";
	/** 境界パスに触れる */
	risk: "none" | "boundary";
	/** hot file に触れる */
	hot: boolean;
	/** 空き枠 (子の数) */
	free: number;
	/** ready の task 数 (読み取り fan-out の上限) */
	ready: number;
	/** 予算の余裕 */
	budget: "ample" | "tight";
	/** 既定方式 (worktree) の直近の失敗率の段階 */
	fail: Level;
	/** 同じ group で writes が互いに素 */
	group?: boolean;
	/** 契約 (I/F) の task が done */
	contract?: boolean;
	/** uncertain の宣言、または同じ task の失敗が 2 回以上 */
	uncertain?: boolean;
	/** 受け入れが機械判定できる */
	accept?: boolean;
	/** foreach × 段 (調査 → 要約 → 検証) */
	pipeline?: boolean;
	/** 学習で無効にした方式 */
	disabled?: readonly Method[];
}

export interface StrategyChoice {
	method: Method;
	/** 並列度 (0 = 今は起動しない) */
	degree: number;
	isolation: Isolation;
	/** 検証の置き方 */
	verify: string;
	/** 適用した表の行 (R1 など) */
	rule: string;
	/** 選択の根拠 (1 行) */
	why: string;
}

/** 共有 worktree の並列編集の上限 */
export const SHARED_MAX = 3;

const half = (n: number): number => Math.max(1, Math.ceil(n / 2));

/** 表を上から評価して最初に当たった行を返す */
export function select(i: StrategyInput): StrategyChoice {
	const off = (m: Method): boolean => (i.disabled ?? []).includes(m);
	const free = Math.max(0, i.free);
	const adj = (n: number): number => (i.fail === "mid" ? half(n) : n);
	const mk = (method: Method, degree: number, isolation: Isolation, verify: string, rule: string, why: string): StrategyChoice => ({
		method,
		degree,
		isolation,
		verify,
		rule,
		why,
	});
	// R1 検査: 全件検査は排他の資源 (flock)。1 本ずつ
	if (i.kind === "check") return mk("serial", Math.min(1, free), "none", "exclusive-lock", "R1", "検査は排他 (全件検査は 1 本ずつ)");
	// R2 読み取り: 隔離なしで広げる。foreach × 段なら pipeline
	if (i.kind === "ro") {
		if (i.pipeline) return mk("pipeline", Math.min(free, Math.max(1, i.ready)), "none", "digest-format", "R2a", "foreach × 段: 壁なしで次段へ");
		return mk("fanout", Math.min(free, Math.max(1, i.ready)), "none", "digest-format", "R2b", "読み取りだけ: 隔離なしで fan-out");
	}
	// 以降は編集 (kind=edit)
	if (i.upstream === "pending") return mk("serial", 0, "none", "-", "R3", "上流が未着手: 依存の完了を待つ");
	if (i.overlap || i.hot || i.risk === "boundary") {
		const why = i.overlap ? "writes が重なる" : i.hot ? "hot file に触れる" : "境界に触れる";
		const verify = i.risk === "boundary" ? "independent-review" : "targeted";
		return mk("serial", Math.min(1, free), "worktree", verify, "R4", `${why}: 直列`);
	}
	if (i.upstream === "running") {
		const can = !!i.contract && i.budget === "ample" && i.fail !== "high" && !off("speculative") && free >= 1;
		if (can) return mk("speculative", 1, "worktree", "excluded-from-bundle-until-upstream", "R5", "契約が確定: 上流の完了を待たず見込みで着手");
		return mk("serial", 0, "none", "-", "R5x", "上流が実行中: 見込みの条件を満たさず完了を待つ");
	}
	if (i.uncertain && i.accept && i.budget === "ample" && i.size !== "L" && i.fail !== "high" && !off("race") && free >= 2) {
		return mk("race", Math.min(3, free), "worktree", "all-checks-then-min-diff", "R6", "不確かで機械判定できる: 競争 (best-of-N)");
	}
	if (i.group && i.size === "S" && i.fail !== "high" && !off("shared") && free >= 2) {
		return mk("shared", adj(Math.min(SHARED_MAX, free)), "shared", "group-join", "R7", "同じ group・writes が素・小さい: 共有 worktree");
	}
	if (i.size === "L" && i.budget === "tight") return mk("serial", Math.min(1, free), "worktree", "targeted", "R8", "予算が逼迫: 大きい編集は並列にしない");
	if (i.fail === "high") return mk("serial", Math.min(1, free), "worktree", "targeted", "R9", "既定方式の失敗率が高い: 直列へ戻す");
	return mk("worktree", adj(free), "worktree", "targeted-then-bundle", "R10", "writes が素: feature ごとの worktree (既定)");
}

// ── 誤選択の検出と学習 (有界・畳み込み) ───────────────────────────

export interface Observation {
	scopeViolation?: boolean;
	/** numstat の急減 (編集が消えた疑い) */
	numstatDrop?: boolean;
	/** bundle の衝突 (終了コード 3) */
	bundleConflict?: boolean;
	/** 見込みの破棄率 (直近の窓) */
	discardRate?: number;
	/** fan-out の結果の hash の重複率 */
	duplicateRate?: number;
}

export const DISCARD_LIMIT = 0.4;
export const WINDOW = 10;
/** 破棄率を見る最小の件数 (これ未満は判定しない。仮定) */
export const MIN_WINDOW = 5;
/** 無効化の冷却期間 (ms)。過ぎたら窓を空にして再び試す */
export const COOLDOWN_MS = 24 * 3_600_000;
/** 学んだ重なりの組の保持上限 (古いものから捨てる) */
export const PAIRS_MAX = 50;

/** 誤選択の理由と、次に取る手 (表の「調整」の列) */
export function detectMisselection(method: Method, o: Observation): { reasons: string[]; action: string | null } {
	const reasons: string[] = [];
	let action: string | null = null;
	if (method === "shared" && (o.scopeViolation || o.numstatDrop)) {
		reasons.push(o.scopeViolation ? "scope 違反" : "numstat の急減");
		action = "dismantle-to-worktree";
	}
	if (method === "worktree" && o.bundleConflict) {
		reasons.push("bundle の衝突");
		action = "learn-overlap-and-serialize";
	}
	if (method === "speculative" && (o.discardRate ?? 0) > DISCARD_LIMIT) {
		reasons.push("破棄率 > 40%");
		action = "disable";
	}
	if (method === "fanout" && (o.duplicateRate ?? 0) >= 0.5) {
		reasons.push("結果の重複 ≥ 50%");
		action = "reduce-count";
	}
	if ((method === "worktree" || method === "shared") && o.scopeViolation && action === null) {
		reasons.push("scope 違反");
		action = "learn-overlap-and-serialize";
	}
	return { reasons, action };
}

export interface MethodStats {
	/** 直近 WINDOW 件の成否 (true = 成功。見込みでは「破棄されなかった」) */
	recent: boolean[];
	total: number;
	/** 無効化した時刻 (冷却期間の後に自動で戻る) */
	disabledAt?: number;
}

export interface Stats {
	byMethod: Partial<Record<Method, MethodStats>>;
	/** bundle の衝突などで学んだ重なりの組 (id の昇順の組。最大 PAIRS_MAX) */
	pairs: [string, string][];
}

export type StatsEvent =
	| { type: "outcome"; ts: number; method: Method; ok: boolean }
	| { type: "conflict"; ts: number; a: string; b: string }
	| { type: "reset"; ts: number; method: Method };

export const emptyStats = (): Stats => ({ byMethod: {}, pairs: [] });

/** 直近の窓での失敗 (破棄) の率。件数が MIN_WINDOW 未満なら null */
export function failRate(s: Stats, m: Method): number | null {
	const r = s.byMethod[m]?.recent ?? [];
	if (r.length < MIN_WINDOW) return null;
	return r.filter((x) => !x).length / r.length;
}

/** 1 イベントを畳み込む (入力は変更しない)。人手で編集しない。無効化は有界で、冷却期間か reset で戻る */
export function foldStats(s: Stats, ev: StatsEvent): Stats {
	if (ev.type === "conflict") {
		const pair: [string, string] = ev.a <= ev.b ? [ev.a, ev.b] : [ev.b, ev.a];
		if (s.pairs.some((p) => p[0] === pair[0] && p[1] === pair[1])) return s;
		return { ...s, pairs: [...s.pairs, pair].slice(-PAIRS_MAX) };
	}
	const cur = s.byMethod[ev.method] ?? { recent: [], total: 0 };
	if (ev.type === "reset") return { ...s, byMethod: { ...s.byMethod, [ev.method]: { recent: [], total: cur.total } } };
	let recent = cur.recent;
	let disabledAt = cur.disabledAt;
	if (disabledAt !== undefined && ev.ts - disabledAt >= COOLDOWN_MS) {
		recent = [];
		disabledAt = undefined;
	}
	recent = [...recent, ev.ok].slice(-WINDOW);
	const next: MethodStats = { recent, total: cur.total + 1 };
	if (disabledAt !== undefined) next.disabledAt = disabledAt;
	else {
		const rate = recent.length >= MIN_WINDOW ? recent.filter((x) => !x).length / recent.length : 0;
		if (rate > DISCARD_LIMIT) next.disabledAt = ev.ts;
	}
	return { ...s, byMethod: { ...s.byMethod, [ev.method]: next } };
}

export const foldAllStats = (events: readonly StatsEvent[]): Stats => events.reduce(foldStats, emptyStats());

/** 方式が無効か (無効化から冷却期間が過ぎるまで) */
export function isDisabled(s: Stats, m: Method, now: number): boolean {
	const d = s.byMethod[m]?.disabledAt;
	return d !== undefined && now - d < COOLDOWN_MS;
}

/** 無効の方式の一覧 (METHODS の順) */
export const disabledMethods = (s: Stats, now: number): Method[] => METHODS.filter((m) => isDisabled(s, m, now));

/** 失敗率の段階 (件数が足りなければ low) */
export function failLevel(s: Stats, m: Method): Level {
	const r = failRate(s, m);
	if (r === null || r < 0.2) return "low";
	return r > DISCARD_LIMIT ? "high" : "mid";
}

/** 学んだ重なりの組か (id の順序は問わない) */
export const learnedOverlap = (s: Stats, a: string, b: string): boolean => s.pairs.some((p) => (p[0] === a && p[1] === b) || (p[0] === b && p[1] === a));
