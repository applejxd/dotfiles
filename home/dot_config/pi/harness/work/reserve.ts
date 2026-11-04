// 起動前の予約と、実行中の使用量の監視。純関数。see docs/spec/work/scheduler.md#予約
import type { Money } from "./types.ts";

export type Size = "S" | "M" | "L";

/** 予算。省略した項目は無制限 (0 は「使えない」) */
export type Budget = Partial<Money>;

export const ZERO: Money = { usd: 0, tokens: 0, ms: 0 };

/** 履歴が無いときの既定の見積り (役割 × 大きさ)。実測で置き換える前の仮の値 */
export const DEFAULT_ESTIMATES: Record<string, Record<Size, Money>> = {
	explore: {
		S: { usd: 0.2, tokens: 60_000, ms: 3 * 60_000 },
		M: { usd: 0.5, tokens: 150_000, ms: 8 * 60_000 },
		L: { usd: 1.2, tokens: 400_000, ms: 20 * 60_000 },
	},
	review: {
		S: { usd: 0.3, tokens: 80_000, ms: 4 * 60_000 },
		M: { usd: 0.8, tokens: 200_000, ms: 10 * 60_000 },
		L: { usd: 2, tokens: 500_000, ms: 25 * 60_000 },
	},
	worker: {
		S: { usd: 0.5, tokens: 150_000, ms: 8 * 60_000 },
		M: { usd: 1.5, tokens: 450_000, ms: 20 * 60_000 },
		L: { usd: 4, tokens: 1_200_000, ms: 50 * 60_000 },
	},
	check: {
		S: { usd: 0, tokens: 0, ms: 8 * 60_000 },
		M: { usd: 0, tokens: 0, ms: 8 * 60_000 },
		L: { usd: 0, tokens: 0, ms: 12 * 60_000 },
	},
};
/** 役割が表に無いときの既定 (worker と同じ) */
const FALLBACK_ROLE = "worker";
/** 履歴を使うのに要る最小の件数 (これ未満は既定表) */
export const MIN_SAMPLES = 3;
/** wrap-up の steer と abort の倍率 */
export const STEER_RATIO = 1.5;
export const ABORT_RATIO = 2;

/** 履歴の鍵 (役割 × 大きさ) */
export const historyKey = (role: string, size: Size): string => `${role}:${size}`;

export const addMoney = (a: Money, b: Money): Money => ({ usd: a.usd + b.usd, tokens: a.tokens + b.tokens, ms: a.ms + b.ms });

/** 最近接順位法の百分位 (0 < q ≤ 1)。空は 0 */
export function percentile(xs: readonly number[], q: number): number {
	if (xs.length === 0) return 0;
	const s = [...xs].sort((a, b) => a - b);
	return s[Math.min(s.length - 1, Math.max(0, Math.ceil(q * s.length) - 1))];
}

/** 見積り: 履歴 (件数 ≥ MIN_SAMPLES) の項目ごとの p75、無ければ既定表 */
export function estimate(role: string, size: Size, history: Readonly<Record<string, readonly Money[]>>): Money {
	const samples = history[historyKey(role, size)] ?? [];
	if (samples.length >= MIN_SAMPLES) {
		return {
			usd: percentile(
				samples.map((m) => m.usd),
				0.75,
			),
			tokens: percentile(
				samples.map((m) => m.tokens),
				0.75,
			),
			ms: percentile(
				samples.map((m) => m.ms),
				0.75,
			),
		};
	}
	const row = DEFAULT_ESTIMATES[role] ?? DEFAULT_ESTIMATES[FALLBACK_ROLE];
	return { ...row[size] };
}

/** 履歴の所要時間の p50 (ms)。履歴が足りなければ既定表の時間 */
export function durationP50(role: string, size: Size, history: Readonly<Record<string, readonly Money[]>>): number {
	const samples = history[historyKey(role, size)] ?? [];
	if (samples.length >= MIN_SAMPLES) {
		return percentile(
			samples.map((m) => m.ms),
			0.5,
		);
	}
	return (DEFAULT_ESTIMATES[role] ?? DEFAULT_ESTIMATES[FALLBACK_ROLE])[size].ms;
}

/** 「使用済み + 予約 + 見積り > 予算」なら起動しない。予算の無い項目は見ない */
export function canReserve(budget: Budget | undefined, used: Money, reserved: Money, est: Money): boolean {
	if (!budget) return true;
	for (const k of ["usd", "tokens", "ms"] as const) {
		const cap = budget[k];
		if (cap !== undefined && used[k] + reserved[k] + est[k] > cap) return false;
	}
	return true;
}

export interface WatchRun {
	/** 予約した見積り */
	reserve: Money;
	/** 子の使用量 */
	spent: Money;
	/** 評価役の使用量 (合算する) */
	evalSpent?: Money;
	/** wrap-up の steer を出し済み */
	steered?: boolean;
}

/** 使用量 / 見積りの最大の比 (見積りが 0 の項目は見ない) */
export function usageRatio(run: WatchRun): number {
	const total = addMoney(run.spent, run.evalSpent ?? ZERO);
	let r = 0;
	for (const k of ["usd", "tokens", "ms"] as const) if (run.reserve[k] > 0) r = Math.max(r, total[k] / run.reserve[k]);
	return r;
}

/** 実行中の監視: 2 倍で abort、1.5 倍で (未送信なら) steer。柔らかい門にしない */
export function watch(run: WatchRun): "abort" | "steer" | "ok" {
	const r = usageRatio(run);
	if (r >= ABORT_RATIO) return "abort";
	if (r >= STEER_RATIO && !run.steered) return "steer";
	return "ok";
}
