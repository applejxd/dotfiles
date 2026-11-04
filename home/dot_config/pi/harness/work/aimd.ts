// provider (429) の観測から生存数の上限を動かす AIMD と、指数バックオフ。純関数・状態はイベントの畳み込みで導く (永続できる)。
// 乱数は呼び出し側が注入し、イベントに残す (畳み込みの再生で同じ結果になる)。see docs/spec/work/scheduler.md#429-と-aimd

export interface AimdConfig {
	/** 初期の生存数の上限 */
	initial: number;
	/** 上限 (仮) */
	max: number;
	/** 連続成功がこの回数で +1 */
	k: number;
	/** バックオフの基準 (ms) */
	baseMs: number;
	/** バックオフの上限 (ms) */
	capMs: number;
	/** ジッターの幅 (±比率) */
	jitter: number;
	/** 429 の連続がこの回数で goal を pause する */
	pauseAfter: number;
}

export const DEFAULT_AIMD: AimdConfig = {
	initial: 6,
	max: 10,
	k: 5,
	baseMs: 60_000,
	capMs: 15 * 60_000,
	jitter: 0.2,
	pauseAfter: 5,
};

export interface ProviderState {
	/** 生存数の上限 (1 以上 max 以下) */
	limit: number;
	/** 429 の後の連続成功の数 */
	streak: number;
	/** 429 の連続回数 (成功で 0) */
	strikes: number;
	/** この時刻まで新規の起動を止める (0 = 止めない) */
	pausedUntil: number;
	/** strikes が pauseAfter に達した (goal を pause して利用者へ) */
	exhausted: boolean;
}

/** 畳み込むイベント。429 は注入した乱数 (0 以上 1 未満) を持つ。成功は run の正常終了 */
export type ProviderEvent = { t: "429"; ts: number; rand: number } | { t: "success"; ts: number } | { t: "reset"; ts: number };

export function aimdInit(cfg: AimdConfig = DEFAULT_AIMD): ProviderState {
	return { limit: clamp(cfg.initial, 1, cfg.max), streak: 0, strikes: 0, pausedUntil: 0, exhausted: false };
}

const clamp = (n: number, lo: number, hi: number): number => Math.max(lo, Math.min(hi, n));

/** n 回目 (1 始まり) の 429 の待ち時間。base×2^(n-1) に ±jitter を掛け、上限で切る (rand は 0 以上 1 未満) */
export function backoffMs(strikes: number, rand: number, cfg: AimdConfig = DEFAULT_AIMD): number {
	const n = Math.max(1, Math.floor(strikes));
	const raw = Math.min(cfg.capMs, cfg.baseMs * 2 ** (n - 1));
	const factor = 1 + (clamp(rand, 0, 1) * 2 - 1) * cfg.jitter;
	return Math.min(cfg.capMs, Math.max(0, Math.round(raw * factor)));
}

/** 1 イベントを畳み込む (入力は変更しない) */
export function aimdStep(s: ProviderState, ev: ProviderEvent, cfg: AimdConfig = DEFAULT_AIMD): ProviderState {
	if (ev.t === "429") {
		const strikes = s.strikes + 1;
		return {
			limit: Math.max(1, Math.floor(s.limit / 2)),
			streak: 0,
			strikes,
			pausedUntil: ev.ts + backoffMs(strikes, ev.rand, cfg),
			exhausted: s.exhausted || strikes >= cfg.pauseAfter,
		};
	}
	if (ev.t === "reset") return { ...s, strikes: 0, pausedUntil: 0, exhausted: false };
	const streak = s.streak + 1;
	if (streak >= cfg.k) return { ...s, limit: Math.min(cfg.max, s.limit + 1), streak: 0, strikes: 0 };
	return { ...s, streak, strikes: 0 };
}

export function foldAimd(events: readonly ProviderEvent[], cfg: AimdConfig = DEFAULT_AIMD): ProviderState {
	return events.reduce((s, e) => aimdStep(s, e, cfg), aimdInit(cfg));
}

/** 起動を止めているか */
export const isPaused = (s: ProviderState, now: number): boolean => now < s.pausedUntil;

/** 429 (利用上限) のエラー文か */
export const is429 = (text: string): boolean => /rate[ -]?limit|usage limit|too many requests|\b429\b/i.test(text);
