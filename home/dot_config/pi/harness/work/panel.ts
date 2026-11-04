// 常設の 1 画面 (パネル) の組み立て (純関数。pi の API・fs なし。台帳の reducer の型には依存せず、入力はここで独立に定義する)。
// ≤5 行・LINE_WIDTH 以内。更新は状態が変わったときだけ (タイマー・ポーリングは呼び出し側が持たない)。作業が無いときは空配列。
// see docs/spec/work/notices.md#パネル
import { LINE_WIDTH } from "./types.ts";
import { clipCells, textWidth } from "./text-width.ts";

export const PANEL_MAX_LINES = 5;

export interface PanelWait {
	/** 利用者に出す 1 行 (例: `計画の承認 → /goal ok`) */
	prompt: string;
	/** 小さいほど優先 (同順位は入力の順) */
	rank: number;
}

export interface PanelInput {
	/** 駆動中のゴール。無ければパネルは出さない */
	goal: {
		title: string;
		usd: number;
		usdLimit?: number;
		/** 経過 (分) */
		elapsedMin: number;
		limitMin?: number;
	} | null;
	running: number;
	waitingUser: number;
	failed: number;
	done?: number;
	total?: number;
	/** user 待ち (優先順は rank で決める) */
	waits: PanelWait[];
	/** 失敗の 1 行 (新しい順) */
	failures: string[];
	/** 予算の警告など */
	warnings: string[];
}

const usdShort = (v: number): string => String(Number((Number.isFinite(v) ? v : 0).toFixed(1)));
const one = (s: string): string => String(s ?? "").replace(/[\u0000-\u001f\u007f-\u009f]+/g, " ").replace(/\s+/g, " ").trim();

/** 端末で 2 桁に描かれる ⏳ (U+23F3。text-width.ts の幅の関数は 1 と数える) を、余裕を持って 2 と数えて切る */
function fit(s: string, cap: number): string {
	const extra = [...s].filter((c) => c === "\u23f3").length;
	return clipCells(s, Math.max(0, cap - extra));
}

const counts = (p: PanelInput): string => `▶${p.running} ⏳あなた${p.waitingUser} ✗${p.failed}`;

/** パネルの行 (≤5 行、各行は min(width, LINE_WIDTH) 桁以内)。作業が無い (goal が null) ときは空 */
export function renderPanel(p: PanelInput, width: number = LINE_WIDTH): string[] {
	if (!p.goal) return [];
	const cap = Math.max(10, Math.min(width, LINE_WIDTH));
	const g = p.goal;
	const usd = `$${usdShort(g.usd)}${g.usdLimit !== undefined ? `/${usdShort(g.usdLimit)}` : ""}`;
	const min = `${Math.max(0, Math.round(g.elapsedMin))}${g.limitMin !== undefined ? `/${Math.round(g.limitMin)}` : ""}分`;
	const tail = ` ${usd} ${min}`;
	const prefix = "🎯 ";
	const room = cap - textWidth(prefix) - textWidth(tail);
	const l1 = room >= 2 ? `${prefix}${clipCells(one(g.title), room)}${tail}` : fit(`${prefix.trim()}${tail}`, cap);
	const progress = p.total !== undefined && p.total > 0 ? ` · ${p.done ?? 0}/${p.total}` : "";
	const lines = [l1, fit(`${counts(p)}${progress}`, cap)];
	const waits = p.waits.map((w, i) => ({ w, i })).sort((a, b) => a.w.rank - b.w.rank || a.i - b.i).map((x) => x.w);
	if (waits.length > 0) lines.push(fit(`次: ${one(waits[0].prompt)}`, cap));
	if (waits.length > 1) lines.push(fit(`⏳ ${one(waits[1].prompt)}`, cap));
	else if (p.failures.length > 0) lines.push(fit(`✗ ${one(p.failures[0])}`, cap));
	if (p.warnings.length > 0) {
		const more = p.warnings.length > 1 ? ` (ほか${p.warnings.length - 1}件)` : "";
		lines.push(fit(`⚠ ${one(p.warnings[0])}${more}`, cap));
	}
	return lines.slice(0, PANEL_MAX_LINES);
}

/** フッター用の 1 行 (例: `🎯 3/7 ▶2 ⏳あなた1 $2.1`)。ゴールが無ければ空文字 */
export function renderFooter(p: PanelInput): string {
	if (!p.goal) return "";
	const prog = p.total !== undefined && p.total > 0 ? ` ${p.done ?? 0}/${p.total}` : "";
	const fail = p.failed > 0 ? ` ✗${p.failed}` : "";
	return `🎯${prog} ▶${p.running} ⏳あなた${p.waitingUser}${fail} $${usdShort(p.goal.usd)}`;
}
