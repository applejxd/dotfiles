// 書き込み集合 (glob) の重なり判定。保守的: 迷えば重なるとみなす (偽陰性 0。偽陽性は許す)。純関数。
// 対応する記法: `*` (区切りを越えない)・`?`・`**` (0 個以上の区切り)・末尾の `/` (配下すべて)。`[..]`・`{..}` は `*` とみなす (保守側)。
// 一方がもう一方の前置 (ディレクトリかもしれない) の場合も重なるとみなす。

export type Tok = { t: "c"; c: string } | { t: "?" } | { t: "*" };

const tokenize = (seg: string): Tok[] => {
	const out: Tok[] = [];
	let i = 0;
	while (i < seg.length) {
		const ch = seg[i];
		if (ch === "*") {
			out.push({ t: "*" });
			while (seg[i] === "*") i++;
			continue;
		}
		if (ch === "?") out.push({ t: "?" });
		else if (ch === "[" || ch === "{") {
			// 対応する閉じまでを 1 つの `*` (保守側)。閉じが無ければ以降すべて
			const close = ch === "[" ? "]" : "}";
			const end = seg.indexOf(close, i + 1);
			out.push({ t: "*" });
			i = end < 0 ? seg.length : end + 1;
			continue;
		} else out.push({ t: "c", c: ch });
		i++;
	}
	return out;
};

/** 区切り (/) を含まない 2 つの断片に共通して合致する文字列が存在しうるか */
const segOverlap = (a: string, b: string): boolean => {
	const p = tokenize(a);
	const q = tokenize(b);
	const memo = new Map<number, boolean>();
	const f = (i: number, j: number): boolean => {
		const key = i * (q.length + 1) + j;
		const hit = memo.get(key);
		if (hit !== undefined) return hit;
		let r: boolean;
		if (i === p.length && j === q.length) r = true;
		else if (i < p.length && p[i].t === "*") r = f(i + 1, j) || (j < q.length && f(i, j + 1));
		else if (j < q.length && q[j].t === "*") r = f(i, j + 1) || (i < p.length && f(i + 1, j));
		else if (i === p.length || j === q.length) r = false;
		else {
			const x = p[i];
			const y = q[j];
			const ok = x.t === "?" || y.t === "?" || (x.t === "c" && y.t === "c" && x.c === y.c);
			r = ok && f(i + 1, j + 1);
		}
		memo.set(key, r);
		return r;
	};
	return f(0, 0);
};

const segments = (glob: string): string[] => {
	let g = glob.replace(/\\/g, "/");
	const dir = g.endsWith("/");
	g = g.replace(/^(\.\/)+/, "");
	const segs = g.split("/").filter((s) => s.length > 0 && s !== ".");
	// `**` を含む断片は `**` 扱い (保守側)
	const norm = segs.map((s) => (s.includes("**") ? "**" : s));
	if (dir) norm.push("**");
	// スラッシュを含まない記法は、どの階層にも合致しうる (gitignore 流) とみなす (保守側)
	if (norm.length === 1 && !dir) norm.unshift("**");
	return norm;
};

export const globsMayOverlap = (a: string, b: string): boolean => {
	const A = segments(a);
	const B = segments(b);
	const memo = new Map<number, boolean>();
	const f = (i: number, j: number): boolean => {
		// どちらかを使い切った: 前置 (ディレクトリかもしれない) なので重なるとみなす
		if (i === A.length || j === B.length) return true;
		const key = i * (B.length + 1) + j;
		const hit = memo.get(key);
		if (hit !== undefined) return hit;
		let r: boolean;
		if (A[i] === "**" || B[j] === "**") {
			r = false;
			if (A[i] === "**") r = f(i + 1, j) || f(i, j + 1);
			if (!r && B[j] === "**") r = f(i, j + 1) || f(i + 1, j);
		} else r = segOverlap(A[i], B[j]) && f(i + 1, j + 1);
		memo.set(key, r);
		return r;
	};
	return f(0, 0);
};

/** 2 つの glob の集合が重なりうるか (どれか 1 組でも重なれば真。空集合は重ならない) */
export const writeSetsMayOverlap = (xs: readonly string[], ys: readonly string[]): boolean =>
	xs.some((x) => ys.some((y) => globsMayOverlap(x, y)));
