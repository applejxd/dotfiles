// 判定 1 回ぶんの文脈。Python 版ではモジュールのグローバル変数だったものを、呼び出しごとの値にする。
//
// - payloadCwd: PreToolUse の cwd (workspace のルート)。set_payload_cwd / payload_cwd の置き換え
// - literalHeredocBodies: 引用付き heredoc の本文の記録 (_LITERAL_HEREDOC_BODIES の置き換え)。
//   Python 版はプロセス内に積み残して、前の入力が後の入力の検査を緩めた。ここは判定ごとに作り直す
// - cache: 同じ判定の中だけで使う純関数の結果の記憶 (normalize など)
// - tables: tables.toml を JSON にした検査用の表 (読み取り専用)
// - common: common.toml を JSON にした設定 (読み取り専用)
//
// node の型除去でそのまま動く書き方だけを使う。
// see docs/spec/pi-decide.md#ts-版への移植
import type { Common } from "./policy.ts";

export type Tables = Record<string, Record<string, any>>;

export type Ctx = {
	readonly tables: Tables;
	readonly common: Common;
	payloadCwd: string | null;
	literalHeredocBodies: string[];
	cache: Map<string, unknown>;
};

export function newCtx(tables: Tables, common: Common, payloadCwd: string | null = null): Ctx {
	return { tables, common, payloadCwd, literalHeredocBodies: [], cache: new Map() };
}

function raw(ctx: Ctx, section: string, key: string): any {
	const value = ctx.tables[section]?.[key];
	if (value === undefined) throw new Error(`tables.toml に [${section}] ${key} がありません`);
	return value;
}

/** `tables.as_set` */
export const tableSet = (ctx: Ctx, section: string, key: string): Set<string> => new Set<string>(raw(ctx, section, key));
/** `tables.as_list` / `as_tuple` */
export const tableList = (ctx: Ctx, section: string, key: string): string[] => [...raw(ctx, section, key)];
/** `tables.as_dict` */
export const tableDict = (ctx: Ctx, section: string, key: string): Map<string, string[]> =>
	new Map<string, string[]>(Object.entries(raw(ctx, section, key)));

/** 同じ判定の中だけで純関数の結果を使い回す。 */
export function memo<T>(ctx: Ctx, key: string, compute: () => T): T {
	if (ctx.cache.has(key)) return ctx.cache.get(key) as T;
	const value = compute();
	ctx.cache.set(key, value);
	return value;
}
