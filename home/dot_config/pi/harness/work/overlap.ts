// writes (glob) の重なり判定と自動直列化。純関数 (fs・pi の API なし)。
// 方針: 迷えば「重なる」と答える (偽陰性 0。偽陽性は直列になるだけで安全)。see docs/spec/work/scheduler.md#writes-の重なりと直列化

import { globsMayOverlap as coreOverlap } from "./globs.ts";

/** 波括弧の展開の上限。超えたら展開せず保守的に扱う */
const BRACE_LIMIT = 64;

/** `{a,b}` を展開する (入れ子可)。上限を超える・閉じていないときは null (呼び出し側が保守的に「重なる」とする) */
export function expandBraces(p: string): string[] | null {
	const open = p.indexOf("{");
	if (open < 0) return [p];
	let depth = 0;
	let close = -1;
	const cuts: number[] = [];
	for (let i = open; i < p.length; i++) {
		const c = p[i];
		if (c === "{") depth++;
		else if (c === "}") {
			depth--;
			if (depth === 0) {
				close = i;
				break;
			}
		} else if (c === "," && depth === 1) cuts.push(i);
	}
	if (close < 0) return null;
	const parts: string[] = [];
	let from = open + 1;
	for (const cut of cuts) {
		parts.push(p.slice(from, cut));
		from = cut + 1;
	}
	parts.push(p.slice(from, close));
	const head = p.slice(0, open);
	const tail = p.slice(close + 1);
	const out: string[] = [];
	for (const part of parts) {
		const inner = expandBraces(head + part + tail);
		if (inner === null) return null;
		out.push(...inner);
		if (out.length > BRACE_LIMIT) return null;
	}
	return out;
}

/** 前後の揺れを正規化する。末尾 `/` は配下すべて (`**`) とみなす */
export function normalizeGlob(p: string): string {
	let s = p.trim().replace(/\\/g, "/");
	while (s.startsWith("./")) s = s.slice(2);
	if (s.startsWith("/")) s = s.replace(/^\/+/, "");
	if (s === "" || s.endsWith("/")) s += "**";
	return s.replace(/\/{2,}/g, "/");
}

/** 2 つの glob が同じファイルに一致しうるか。**保守的**: 迷えば true (偽陰性 0) */
export function globsMayOverlap(a: string, b: string): boolean {
	const ea = expandBraces(normalizeGlob(a));
	const eb = expandBraces(normalizeGlob(b));
	if (ea === null || eb === null) return true;
	for (const x of ea) for (const y of eb) if (coreOverlap(normalizeGlob(x), normalizeGlob(y))) return true;
	return false;
}

/** 2 つの writes (glob の集合) が重なりうるか */
export function writesMayOverlap(a: readonly string[], b: readonly string[]): boolean {
	for (const x of a) for (const y of b) if (globsMayOverlap(x, y)) return true;
	return false;
}

/** 広すぎる宣言の検証。全体に一致する glob (`**`・`*`・`**` と `*` だけの並び・空) は拒否する */
export function validateWrites(writes: readonly string[]): { ok: boolean; reason?: string } {
	for (const w of writes) {
		const segs = normalizeGlob(w)
			.split("/")
			.filter((s) => s !== "");
		if (segs.length === 0 || segs.every((s) => s === "**" || s === "*")) {
			return { ok: false, reason: `広すぎる writes: ${JSON.stringify(w)}` };
		}
	}
	return { ok: true };
}

/**
 * writes が触れる hot glob の一覧 (hot の順を保つ)。hot の排他予約の鍵になる。
 * 「触れる」は、writes が**特定のファイルを名指す**とき (最後の区間が `**`・`*` だけでない) に限る。
 * `src/**` のような木全体の宣言まで hot 扱いにすると、ほぼ全部の task が hot (例 `**\/index.ts`) に当たって直列になるため。
 * 木全体の宣言どうしの衝突は writes の重なりで直列になる。
 */
export function hotHits(writes: readonly string[], hot: readonly string[]): string[] {
	const named = writes.filter((w) => {
		const last = normalizeGlob(w).split("/").pop() ?? "";
		return last !== "**" && last !== "*";
	});
	return hot.filter((h) => named.some((w) => globsMayOverlap(w, h)));
}

export interface SerialTask {
	id: string;
	writes: string[];
	after: string[];
	/** 小さいほど先 (省略は 0)。同じなら id の昇順 */
	rank?: number;
}

/**
 * 重なる task に決定的な順序で自動の依存を足す。順序は (rank, id)。
 * 既にどちらかの向きで (推移的に) 依存があるときは足さない (循環を作らない)。入力は変更しない。
 * 戻り値の auto[id] は足した依存 (元の after は含まない)。
 */
export function serialize(tasks: readonly SerialTask[]): { tasks: SerialTask[]; auto: Record<string, string[]> } {
	const sorted = [...tasks].sort((p, q) => (p.rank ?? 0) - (q.rank ?? 0) || (p.id < q.id ? -1 : p.id > q.id ? 1 : 0));
	const deps = new Map<string, Set<string>>();
	for (const t of tasks) deps.set(t.id, new Set(t.after));
	const reach = (from: string, to: string): boolean => {
		const seen = new Set<string>();
		const stack = [from];
		while (stack.length > 0) {
			const x = stack.pop() as string;
			if (x === to) return true;
			if (seen.has(x)) continue;
			seen.add(x);
			for (const d of deps.get(x) ?? []) stack.push(d);
		}
		return false;
	};
	const auto: Record<string, string[]> = {};
	for (let i = 0; i < sorted.length; i++) {
		for (let j = i + 1; j < sorted.length; j++) {
			const early = sorted[i];
			const late = sorted[j];
			if (early.writes.length === 0 || late.writes.length === 0) continue;
			if (!writesMayOverlap(early.writes, late.writes)) continue;
			if (reach(late.id, early.id) || reach(early.id, late.id)) continue;
			(deps.get(late.id) as Set<string>).add(early.id);
			(auto[late.id] ??= []).push(early.id);
		}
	}
	return {
		tasks: tasks.map((t) => ({ ...t, writes: [...t.writes], after: [...t.after, ...(auto[t.id] ?? [])] })),
		auto,
	};
}
