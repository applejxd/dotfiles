// todo の表示用の部品 (純関数)。pi・pi-tui に依存しない (試験で単体に動かせるよう、index.ts から分けてある)。
// 色は Paint で注入する (実機は theme、試験は恒等か印を付ける関数)。
// see docs/spec/guard/pi-extensions.md#todo-の別表示

export type Status = "pending" | "in_progress" | "blocked" | "done" | "cancelled";
export type Todo = { id: number; text: string; status: Status; note?: string };

export type Paint = {
	fg: (color: string, s: string) => string;
	bold: (s: string) => string;
	strike: (s: string) => string;
};
export const identityPaint: Paint = { fg: (_c, s) => s, bold: (s) => s, strike: (s) => s };

// 状態の表示順・見出し・アイコン・色
export const ORDER: Status[] = ["in_progress", "blocked", "pending", "done", "cancelled"];
export const LABEL: Record<Status, string> = { in_progress: "進行中", blocked: "待ち", pending: "未着手", done: "完了", cancelled: "中止" };
export const ICON: Record<Status, string> = { in_progress: "▶", blocked: "◇", pending: "○", done: "✓", cancelled: "✗" };
export const COLOR: Record<Status, string> = { in_progress: "accent", blocked: "warning", pending: "text", done: "success", cancelled: "dim" };
const CLOSED: Status[] = ["done", "cancelled"];
export const NOTE_LINES = 2;

// ---- 表示幅 (全角 2・結合文字 0) ----
function cellWidth(cp: number): number {
	if (cp === 0 || cp < 32 || (cp >= 0x7f && cp < 0xa0)) return 0;
	if ((cp >= 0x300 && cp <= 0x36f) || cp === 0x200d || (cp >= 0xfe00 && cp <= 0xfe0f)) return 0;
	if (
		(cp >= 0x1100 && cp <= 0x115f) ||
		(cp >= 0x2e80 && cp <= 0xa4cf) ||
		(cp >= 0xac00 && cp <= 0xd7a3) ||
		(cp >= 0xf900 && cp <= 0xfaff) ||
		(cp >= 0xfe30 && cp <= 0xfe6f) ||
		(cp >= 0xff00 && cp <= 0xff60) ||
		(cp >= 0xffe0 && cp <= 0xffe6) ||
		(cp >= 0x1f300 && cp <= 0x1faff) ||
		(cp >= 0x20000 && cp <= 0x3fffd)
	)
		return 2;
	return 1;
}
export function textWidth(s: string): number {
	let w = 0;
	for (const ch of s) w += cellWidth(ch.codePointAt(0) as number);
	return w;
}
/** 表示幅 max に収まるよう切る (切ったら末尾に … を付け、全体で max を超えない)。 */
export function clipWidth(s: string, max: number): string {
	if (max <= 0) return "";
	if (textWidth(s) <= max) return s;
	if (max === 1) return "…";
	let out = "";
	let w = 0;
	for (const ch of s) {
		const cw = cellWidth(ch.codePointAt(0) as number);
		if (w + cw > max - 1) break;
		out += ch;
		w += cw;
	}
	return `${out}…`;
}
/** 表示幅 width で折り返す (文字単位)。 */
export function wrapWidth(s: string, width: number): string[] {
	const w = Math.max(1, width);
	const rows: string[] = [];
	let cur = "";
	let cw = 0;
	for (const ch of s) {
		const c = cellWidth(ch.codePointAt(0) as number);
		if (cw + c > w && cur) {
			rows.push(cur);
			cur = "";
			cw = 0;
		}
		cur += ch;
		cw += c;
	}
	if (cur) rows.push(cur);
	return rows;
}
/** note を空白で 1 行にし、幅で折り返して最大 maxLines 行にする (超えたら最後の行を … で終える)。 */
export function foldNote(note: string, width: number, maxLines = NOTE_LINES): string[] {
	const flat = note.replace(/\s+/g, " ").trim();
	if (!flat) return [];
	const rows = wrapWidth(flat, width);
	if (rows.length <= maxLines) return rows;
	const kept = rows.slice(0, maxLines);
	kept[maxLines - 1] = clipWidth(`${kept[maxLines - 1]}${rows[maxLines]}`, Math.max(1, width));
	if (!kept[maxLines - 1].endsWith("…")) kept[maxLines - 1] = clipWidth(`${kept[maxLines - 1]}…`, Math.max(1, width));
	return kept;
}

// ---- overlay の本文 ----
export type ViewState = { top: number; showClosed: boolean };

function itemLines(t: Todo, width: number, paint: Paint): string[] {
	const head = clipWidth(`${ICON[t.status]} #${t.id} ${t.text}`, width);
	let first: string;
	if (t.status === "in_progress") first = paint.fg("accent", paint.bold(head));
	else if (t.status === "cancelled") first = paint.fg("dim", paint.strike(head));
	else if (t.status === "pending") first = head;
	else first = paint.fg(COLOR[t.status], head);
	const indent = width > 8 ? "    " : "";
	const notes = t.note ? foldNote(t.note, width - indent.length) : [];
	return [first, ...notes.map((n) => paint.fg("dim", `${indent}${n}`))];
}

/** スクロール前の全行 (見出し・項目・note)。各行は width 以内。 */
export function bodyLines(todos: Todo[], showClosed: boolean, width: number, paint: Paint): string[] {
	const w = Math.max(1, width);
	if (todos.length === 0) return [paint.fg("dim", clipWidth("(タスクなし)", w))];
	const out: string[] = [];
	for (const st of ORDER) {
		if (!showClosed && CLOSED.includes(st)) continue;
		const items = todos.filter((t) => t.status === st);
		if (items.length === 0) continue;
		if (out.length > 0) out.push("");
		out.push(paint.fg(COLOR[st] === "text" ? "muted" : COLOR[st], paint.bold(clipWidth(`── ${LABEL[st]} (${items.length}) ──`, w))));
		for (const t of items) out.push(...itemLines(t, w, paint));
	}
	if (out.length === 0) out.push(paint.fg("dim", clipWidth("(未完了なし)", w)));
	if (!showClosed) {
		const d = todos.filter((t) => t.status === "done").length;
		const c = todos.filter((t) => t.status === "cancelled").length;
		if (d + c > 0) out.push("", paint.fg("dim", clipWidth(`完了 ${d} 件・中止 ${c} 件 (a で表示)`, w)));
	}
	return out;
}

export const CHROME_ROWS = 2; // ヘッダ + フッタ
export const MARGIN_ROWS = 4; // 端末の行数から引く余白 (枠・入力欄)

/** overlay の総高さ: 内容 (ヘッダ + 本文 + フッタ) と (端末の行数 − 余白) の小さい方。最小 3。 */
export function overlayHeight(contentRows: number, termRows: number): number {
	return Math.max(3, Math.min(contentRows + CHROME_ROWS, Math.floor(termRows) - MARGIN_ROWS));
}

export function clampTop(top: number, total: number, height: number): number {
	return Math.max(0, Math.min(top, Math.max(0, total - height)));
}

export type Frame = { lines: string[]; top: number; maxTop: number; bodyHeight: number; total: number };

/** overlay 1 枚ぶんの描画。lines は width 以内・overlayHeight 以内。 */
export function renderOverlay(todos: Todo[], state: ViewState, width: number, termRows: number, paint: Paint = identityPaint): Frame {
	const w = Math.max(1, Math.floor(width));
	const all = bodyLines(todos, state.showClosed, w, paint);
	const height = overlayHeight(all.length, termRows);
	const bodyHeight = Math.max(1, height - CHROME_ROWS);
	const maxTop = Math.max(0, all.length - bodyHeight);
	const top = clampTop(state.top, all.length, bodyHeight);
	const done = todos.filter((t) => t.status === "done").length;
	const header = paint.fg("accent", paint.bold(clipWidth(`📌 todo ${done}/${todos.length} 完了${state.showClosed ? " (完了・中止も表示)" : ""}`, w)));
	const pos = all.length > bodyHeight ? ` ${top + 1}-${Math.min(top + bodyHeight, all.length)}/${all.length}` : "";
	const footer = paint.fg("dim", clipWidth(`↑↓/jk 1行 PgUp/PgDn g/G a 完了表示 Esc/q 閉じる${pos}`, w));
	const lines = [header, ...all.slice(top, top + bodyHeight), footer].slice(0, height);
	return { lines, top, maxTop, bodyHeight, total: all.length };
}

// ---- キー入力 ----
export type Key = "up" | "down" | "pageUp" | "pageDown" | "home" | "end" | "toggleClosed" | "close";

/** 1 文字入力を Key に読み替える (特殊キーは index.ts が matchesKey で名前にする)。 */
export function keyFromChar(data: string): Key | null {
	const map: Record<string, Key> = { j: "down", k: "up", g: "home", G: "end", a: "toggleClosed", q: "close" };
	return map[data] ?? null;
}

/** キー → 次の状態。close のときは closed: true。 */
export function step(state: ViewState, key: Key, total: number, bodyHeight: number): ViewState & { closed: boolean } {
	if (key === "close") return { ...state, closed: true };
	if (key === "toggleClosed") return { top: 0, showClosed: !state.showClosed, closed: false };
	const page = Math.max(1, bodyHeight - 1);
	const next =
		key === "up" ? state.top - 1
		: key === "down" ? state.top + 1
		: key === "pageUp" ? state.top - page
		: key === "pageDown" ? state.top + page
		: key === "home" ? 0
		: total;
	return { ...state, top: clampTop(next, total, bodyHeight), closed: false };
}

// ---- チャットの畳んだ表示 ----
export function callLabel(args: any): string {
	const a = String(args?.action ?? "");
	const id = args?.id !== undefined ? ` #${args.id}` : "";
	const st = args?.status ? ` → ${args.status}` : "";
	if (a === "batch") return `📌 todo batch (${Array.isArray(args?.ops) ? args.ops.length : 0} 件)`;
	if (a === "replace") return `📌 todo replace (${Array.isArray(args?.items) ? args.items.length : 0} 件)`;
	if (a === "add") {
		const n = Array.isArray(args?.texts) ? args.texts.length : args?.text ? 1 : 0;
		return `📌 todo add (${n} 件)`;
	}
	return `📌 todo ${a}${id}${st}`;
}

export function resultLabel(details: { todos?: Todo[]; error?: string } | undefined): string {
	if (!details) return "";
	if (details.error) return `エラー: ${details.error}`;
	const todos = details.todos ?? [];
	if (todos.length === 0) return "(空)";
	const open = todos.filter((t) => !CLOSED.includes(t.status)).length;
	const done = todos.filter((t) => t.status === "done").length;
	return `未完了 ${open} 件・完了 ${done} 件`;
}

const MARK_COLOR: Record<string, Status> = { "[>]": "in_progress", "[~]": "blocked", "[ ]": "pending", "[x]": "done", "[-]": "cancelled" };
/** 展開時の本文 (モデルへ返す text) を、行頭の印で色づけする。文字は変えない。 */
export function paintContentLine(line: string, paint: Paint): string {
	const st = MARK_COLOR[line.slice(0, 3)];
	if (!st) return line.startsWith("エラー") ? paint.fg("error", line) : line;
	if (st === "pending") return line;
	if (st === "cancelled") return paint.fg("dim", paint.strike(line));
	return paint.fg(COLOR[st], st === "in_progress" ? paint.bold(line) : line);
}
