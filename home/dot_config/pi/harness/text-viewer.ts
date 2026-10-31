// 読み取り専用の全文ビューア (先頭から表示する)。see docs/spec/guard/pi-extensions.md#guarded_action
//
// pi 本体の `ctx.ui.editor` は、開いたときにカーソルを末尾に置くので、長い本文が末尾から見える (開始位置の指定は無い)。
// 確認画面の「全文を見る」は、先頭から読みたいので、`ctx.ui.custom` で作る。pi に依存するのは `showTextViewer` だけで、
// 折り返し・スクロールは純関数 (node の型除去でそのまま動く書き方だけを使う)。
import { cellWidth, clipCells } from "./confirm-view.ts";

// 画面の行数から、見出し・案内・余白を引いた、本文の表示行数 (最小 3)
const CHROME_ROWS = 5;

/** 幅 (セル数) で折り返す。改行は保ち、空行も 1 行として数える。全角は 2 桁 */
export function wrapCells(text: string, width: number): string[] {
	const max = Math.max(4, width);
	const out: string[] = [];
	for (const raw of text.replace(/\r\n?/g, "\n").split("\n")) {
		const line = raw.replace(/\t/g, "  ");
		if (line === "") {
			out.push("");
			continue;
		}
		let cur = "";
		let w = 0;
		for (const ch of line) {
			const cw = cellWidth(ch);
			if (w + cw > max && cur !== "") {
				out.push(cur);
				cur = "";
				w = 0;
			}
			cur += ch;
			w += cw;
		}
		out.push(cur);
	}
	return out;
}

export function viewportHeight(rows: number): number {
	return Math.max(3, Math.floor(rows) - CHROME_ROWS);
}

export function clampTop(top: number, total: number, height: number): number {
	return Math.max(0, Math.min(top, Math.max(0, total - height)));
}

export type ScrollKey = "up" | "down" | "pageUp" | "pageDown" | "home" | "end";

/** スクロールのキーで、先頭行の位置をずらす (範囲の外へは出ない) */
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

/** vi / less 風の j / k / g / G / Space / b を、スクロールのキーへ読み替える */
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

/** 窓 (先頭 top から height 行) と案内の行を描く。常に先頭から (top = 0) 始める */
export function renderViewer(title: string, lines: string[], top: number, height: number, width: number, dim: (s: string) => string = (s) => s, accent: (s: string) => string = (s) => s): string[] {
	const scrollable = lines.length > height;
	const hint = scrollable ? `${positionLabel(top, lines.length, height)} · ↑↓ Space/b g/G · q 閉じる` : "Enter / Esc / q で閉じる";
	return [accent(clipCells(title, width)), ...(scrollable ? lines.slice(top, top + height) : lines), dim(clipCells(hint, width))];
}

type CustomUi = { custom: (factory: (tui: any, theme: any, kb: any, done: (v?: undefined) => void) => unknown, options?: unknown) => Promise<unknown> };

/** 先頭から読む全文ビューア。閉じると戻る (読むだけ。変更は反映されない) */
export async function showTextViewer(ui: CustomUi, title: string, body: string): Promise<void> {
	await ui.custom((tui, theme, kb, done) => {
		let top = 0;
		let total = 0;
		let height = 3;
		return {
			render: (width: number) => {
				const lines = wrapCells(body, width - 2).map((l) => ` ${l}`);
				height = viewportHeight(tui.terminal?.rows ?? 24);
				total = lines.length;
				top = clampTop(top, total, height);
				return renderViewer(title, lines, top, height, width, (s) => theme.fg("dim", s), (s) => theme.fg("accent", s));
			},
			invalidate: () => {},
			handleInput: (data: string) => {
				if (kb.matches(data, "tui.select.cancel") || kb.matches(data, "tui.select.confirm") || data === "q") {
					done(undefined);
					return;
				}
				const key: ScrollKey | null = kb.matches(data, "tui.select.up") ? "up" : kb.matches(data, "tui.select.down") ? "down" : kb.matches(data, "tui.select.pageUp") ? "pageUp" : kb.matches(data, "tui.select.pageDown") ? "pageDown" : keyFromChar(data);
				if (key) {
					top = scrolled(key, top, total, height);
					tui.requestRender();
				}
			},
		};
	});
}
