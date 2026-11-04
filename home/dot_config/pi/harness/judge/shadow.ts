// shadow (観測): bash の判定の後で、新しい解析 (plan.ts の analyze) を「観測だけ」に使い、1 行の記録を残す。
//
// - 旧の判定の応答は一切変えない。analyze の例外・記録の失敗は握りつぶす (判定に影響させない)
// - コマンドの全文・引用文字列・値は記録しない (秘密の混入を避ける)。残すのは長さ・種別・先頭の語の名前 (安全な字種だけ)
// - 目的: analyze が実際のコマンドでどれだけ失敗するか (旧が allow/ask なのに新が ok:false = would_tighten) を実測する
//
// node の型除去でそのまま動く書き方だけを使う。
// see docs/spec/guard/pi-decide.md#shadow観測
import { appendFileSync, mkdirSync, statSync } from "node:fs";
import { dirname, join } from "node:path";
import { analyze as realAnalyze, type Plan } from "./plan.ts";

/** 1 ファイルの上限 (超えたら記録を止める) */
export const MAX_SHADOW_BYTES = 5 * 1024 * 1024;
/** analyze 1 回の時間の上限。超えたら以降の呼び出しを止める (同期処理なので止められないが、次から呼ばない) */
export const BUDGET_MS = 200;
/** 記録する cmd 名の最大件数 */
export const MAX_CMDS = 8;

/** 記録に入れてよい語 (コマンド名として安全な字種)。それ以外 (引用・値・パス・代入) は "?" */
const SAFE_NAME = /^[A-Za-z0-9._+-]{1,40}$/;
const safeName = (s: unknown): string => (typeof s === "string" && SAFE_NAME.test(s) ? s : "?");

/** 原文の先頭の語 (空白まで) を安全な名前にする。代入 (`A=1`) や引用で始まれば "?" */
export const headWord = (cmd: string): string => safeName(String(cmd).trimStart().split(/\s/, 1)[0] ?? "");

const VENDOR_FAILS = new Set(["load", "sha", "eval"]);

export type ShadowInput = {
	role: string;
	mode: string;
	tool: string;
	cmd: string;
	response: { decision: string; source?: string };
	plan?: Plan;
	/** analyze が投げた例外 (名前だけ記録する) */
	error?: unknown;
	ms: number;
	/** 時刻 (試験用の注入。省略時は現在) */
	now?: Date;
};

export type ShadowRecord = {
	t: string;
	role: string;
	mode: string;
	tool: string;
	old: { decision: string; source: string };
	len: number;
	head: string;
	/** true / false。analyze が例外を投げたら null */
	ok: boolean | null;
	why: string | null;
	sites: number | null;
	cmds: string[];
	ms: number;
	would_tighten: boolean;
	vendor_missing: boolean;
	error: string | null;
};

/** 観測の 1 行を作る (純関数)。コマンドの全文は入れない */
export function shadowRecord(i: ShadowInput): ShadowRecord {
	const plan = i.plan;
	const ok = plan ? plan.ok : null;
	const why = plan && !plan.ok ? plan.why : null;
	const decision = String(i.response?.decision ?? "");
	const cmds = plan && plan.ok ? plan.sites.slice(0, MAX_CMDS).map((s) => safeName(s.cmd)) : [];
	return {
		t: (i.now ?? new Date()).toISOString(),
		role: String(i.role),
		mode: String(i.mode),
		tool: String(i.tool),
		old: { decision, source: String(i.response?.source ?? "") },
		len: String(i.cmd).length,
		head: headWord(i.cmd),
		ok,
		why,
		sites: plan && plan.ok ? plan.sites.length : null,
		cmds,
		ms: Math.round(i.ms * 100) / 100,
		would_tighten: ok === false && decision !== "deny",
		vendor_missing: why !== null && VENDOR_FAILS.has(why),
		error: i.error === undefined ? null : safeName((i.error as any)?.name ?? "Error"),
	};
}

/** 1 行を追記する。失敗しても例外を出さない。上限を超えるときは書かない。書けたら true */
export function appendShadow(file: string, record: ShadowRecord, maxBytes: number = MAX_SHADOW_BYTES): boolean {
	try {
		let size = 0;
		try {
			size = statSync(file).size;
		} catch {
			// まだ無い
		}
		const line = JSON.stringify(record) + "\n";
		if (size + Buffer.byteLength(line) > maxBytes) return false;
		mkdirSync(dirname(file), { recursive: true });
		appendFileSync(file, line);
		return true;
	} catch {
		return false;
	}
}

/** 記録の置き場 `<cwd>/.tmp/work/shadow/<session>.jsonl` */
export const shadowPath = (cwd: string, session: string): string =>
	join(cwd, ".tmp", "work", "shadow", `${String(session).replace(/[^A-Za-z0-9_-]/g, "_") || "session"}.jsonl`);

export type ShadowOptions = {
	env?: Record<string, string | undefined>;
	role: () => string;
	mode: () => string;
	sshTargets?: () => readonly string[];
	/** 試験用の注入 */
	analyze?: (cmd: string, o: { sshTargets: readonly string[] }) => Plan;
	clock?: () => number;
	budgetMs?: number;
	maxBytes?: number;
};

/** 判定の後に呼ぶ観測器を作る。観測しないとき・失敗したときは何もしない (戻り値なし) */
export function createShadow(o: ShadowOptions) {
	const env = o.env ?? process.env;
	const analyze = o.analyze ?? realAnalyze;
	const clock = o.clock ?? (() => performance.now());
	const budget = o.budgetMs ?? BUDGET_MS;
	let tripped = false;
	let calls = 0;
	return {
		get tripped() {
			return tripped;
		},
		observe(tool: string, cmd: unknown, response: { decision: string; source?: string }, cwd: string, session: string): void {
			try {
				if (env.PI_SHADOW === "0" || env.PI_HARNESS_CHILD === "1" || tripped) return;
				if (tool !== "bash" && tool !== "bg_run") return;
				if (typeof cmd !== "string") return;
				const first = calls++ === 0;
				const t0 = clock();
				let plan: Plan | undefined;
				let error: unknown;
				try {
					plan = analyze(cmd, { sshTargets: o.sshTargets?.() ?? [] });
				} catch (e) {
					error = e ?? new Error("throw");
				}
				const ms = clock() - t0;
				// 最初の 1 回は vendor の読み込みを含むので、ブレーカーの対象にしない
				if (!first && ms > budget) tripped = true;
				const rec = shadowRecord({ role: o.role(), mode: o.mode(), tool, cmd, response, plan, error, ms });
				appendShadow(shadowPath(cwd, session), rec, o.maxBytes);
			} catch {
				// 観測は判定に影響させない
			}
		},
	};
}
