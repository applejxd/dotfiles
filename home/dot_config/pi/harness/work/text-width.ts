// 表示幅 (端末のセル数) の関数を 1 か所に集約したもの (純関数。pi の API・fs なし)。
// 既存の 3 実装 (quiet-notices.ts・todo/view.ts・confirm-view.ts) の置き換え先。差は docs/spec/work/notices.md#幅の関数。
// 全角 (CJK・全角記号・絵文字) は 2、結合文字・ZWJ・異体字選択子・制御文字は 0、それ以外は 1。

/** 1 文字 (コードポイント) の表示幅 */
export function cellWidth(ch: string): number {
	const c = ch.codePointAt(0) ?? 0;
	if (c < 0x20 || (c >= 0x7f && c < 0xa0) || (c >= 0x300 && c <= 0x36f) || c === 0x200d || (c >= 0xfe00 && c <= 0xfe0f)) return 0;
	if (
		(c >= 0x1100 && c <= 0x115f) ||
		(c >= 0x2e80 && c <= 0xa4cf) ||
		(c >= 0xac00 && c <= 0xd7a3) ||
		(c >= 0xf900 && c <= 0xfaff) ||
		(c >= 0xfe30 && c <= 0xfe6f) ||
		(c >= 0xff00 && c <= 0xff60) ||
		(c >= 0xffe0 && c <= 0xffe6) ||
		(c >= 0x1f300 && c <= 0x1faff) ||
		(c >= 0x20000 && c <= 0x3fffd)
	)
		return 2;
	return 1;
}

/** 文字列の表示幅 */
export function textWidth(s: string): number {
	let w = 0;
	for (const ch of s) w += cellWidth(ch);
	return w;
}

/** 表示幅 width に収める。超えるときは末尾を … にして、全体で width を超えない */
export function clipCells(s: string, width: number): string {
	if (width <= 0) return "";
	if (textWidth(s) <= width) return s;
	if (width === 1) return "…";
	let out = "";
	let w = 0;
	for (const ch of s) {
		const cw = cellWidth(ch);
		if (w + cw > width - 1) break;
		out += ch;
		w += cw;
	}
	return `${out}…`;
}

/** 表示幅が width になるまで右に空白を足す (超えていれば切らずそのまま) */
export function padCells(s: string, width: number): string {
	const w = textWidth(s);
	return w >= width ? s : s + " ".repeat(width - w);
}
