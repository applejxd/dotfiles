// btw の表示用の部品。pi に依存しない (試験で単体に動かせるよう、index.ts から分けてある)。
// see docs/spec/guard/pi-guard.md#自作の拡張-todo--plan--btw

// 表示する返信の上限 (文字数)。どの経路 (子・--plain・非 TUI) でも同じ値で切る
export const MAX_ANSWER_CHARS = 20000;

// 画面の行数から、枠・見出し・案内・エディタ側の余白を引いた、本文の表示行数 (最小 3)
export const CHROME_ROWS = 8;

export function clipAnswer(text: string, max = MAX_ANSWER_CHARS): string {
	if (text.length <= max) return text;
	return `${text.slice(0, max)}\n\n…(長いので省略: 全 ${text.length} 文字のうち先頭 ${max} 文字まで)`;
}

export function viewportHeight(rows: number): number {
	return Math.max(3, Math.floor(rows) - CHROME_ROWS);
}

export function clampTop(top: number, total: number, height: number): number {
	return Math.max(0, Math.min(top, Math.max(0, total - height)));
}

export type ScrollKey = "up" | "down" | "pageUp" | "pageDown" | "home" | "end";

/** スクロールのキーで、先頭行の位置をずらす (範囲の外へは出ない)。 */
export function scrolled(key: ScrollKey, top: number, total: number, height: number): number {
	const next =
		key === "up" ? top - 1
		: key === "down" ? top + 1
		: key === "pageUp" ? top - (height - 1)
		: key === "pageDown" ? top + (height - 1)
		: key === "home" ? 0
		: total;
	return clampTop(next, total, height);
}

/** vi / less 風の j / k / g / G / Space / b を、スクロールのキーへ読み替える (PgUp / PgDn は pi 本体が先に取る端末がある)。 */
export function keyFromChar(data: string): ScrollKey | null {
	if (data === "j") return "down";
	if (data === "k") return "up";
	if (data === " ") return "pageDown";
	if (data === "b") return "pageUp";
	if (data === "g") return "home";
	if (data === "G") return "end";
	return null;
}

export function positionLabel(top: number, total: number, height: number): string {
	return `${top + 1}-${Math.min(top + height, total)} / ${total} 行`;
}
