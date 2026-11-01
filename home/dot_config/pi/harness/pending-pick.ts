// `/pending` の ID の省略 (TUI で選ぶ)・Tab 補完・resolve の対話。選ぶのは ID だけで、承認・破棄・決着の確認は既存の経路 (approvePending・resolvePending) が行う。
// 利用者専用のスラッシュコマンドの部品で、モデルから呼べる経路は作らない。see docs/change/0055-async-approval.md
import { cellWidth, clipCells, sanitizeForDisplay } from "./confirm-view.ts";
import { recordOfChain, resolvePending, type ApproveDeps, type Reply, type ResolveArgs } from "./pending-approve.ts";
import { DEFAULT_LIMITS, doneOid, listOps, readAttemptAt, readOp, readResultAt, runningOid, type OpRecord } from "./pending-ops.ts";

export type PickKind = "approve" | "show" | "drop" | "resolve";
export type Candidate = { id: string; label: string };
type PickDeps = Pick<ApproveDeps, "adapters" | "limits">;

/** 候補 1 行の表示幅の上限 (端末のセル数。狭い画面でも折り返さない) */
export const LABEL_CELLS = 44;
export const CHOICE_CANCEL = "やめる";
export const SUBCOMMANDS = [
	["list", "一覧を出す"],
	["show", "保留・実行中・結果を表示する"],
	["approve", "保留を承認して実行する"],
	["resolve", "実行中・結果不明の操作を決着させる"],
	["drop", "保留を破棄する"],
	["unlock", "孤児の統合ロックを外す"],
	["log", "結果の記録を出す"],
] as const;
const ID_SUBCOMMANDS: readonly string[] = ["show", "approve", "drop", "resolve"];
const info = (text: string): Reply => ({ text, level: "info" });
const refuse = (text: string): Reply => ({ text, level: "warning" });

function agoText(sec: number, now: number): string {
	const d = Math.max(0, now / 1000 - sec);
	return d < 90 ? "たった今" : d < 5400 ? `${Math.round(d / 60)} 分前` : d < 129600 ? `${Math.round(d / 3600)} 時間前` : `${Math.round(d / 86400)} 日前`;
}

/** 1 行目だけ・制御文字なし */
function firstLine(s: unknown): string {
	const line = String(s ?? "").split(/\r\n|\r|\n/)[0] ?? "";
	// eslint-disable-next-line no-control-regex
	return sanitizeForDisplay(line.replace(/[\u0000-\u0008\u000b-\u001f\u007f-\u009f\u200b-\u200f\u202a-\u202e\u2060-\u2064\u2066-\u2069\ufeff]/g, "")).replace(/\s+/g, " ").trim();
}

function briefOf(rec: OpRecord | null, deps: PickDeps): string {
	if (!rec) return "";
	try {
		const b = deps.adapters[rec.action]?.brief?.(rec);
		if (typeof b === "string" && b) return firstLine(b);
	} catch {}
	return firstLine(Object.values(rec.params ?? {})[0]);
}

/** `<操作名> <経過> <要約>`。操作名と経過は削らず、要約を切る。tail があれば末尾に ` …<ID の末尾 4 桁>` を添える (同じ表示の候補の区別用) */
function labelOf(name: string, ago: string, summary: string, tail = ""): string {
	const head = `${firstLine(name)} ${ago}`;
	const suffix = tail ? ` …${tail}` : "";
	const room = LABEL_CELLS - cellWidth(head) - cellWidth(suffix) - 1;
	return clipCells(`${summary && room >= 2 ? `${head} ${clipCells(summary, room)}` : head}${suffix}`, LABEL_CELLS);
}

/** 種類ごとの候補 (新しい順)。git の読み取りだけ */
export function pickCandidates(cwd: string, kind: PickKind, deps: PickDeps, now: number = Date.now()): Candidate[] {
	const limits = deps.limits ?? DEFAULT_LIMITS;
	const raw: { id: string; name: string; ago: string; summary: string }[] = [];
	const entries = [...listOps(cwd, limits).entries].sort((a, b) => b.committedAt - a.committedAt || (a.id < b.id ? 1 : a.id > b.id ? -1 : 0));
	for (const e of entries) {
		let rec: OpRecord | null = null;
		let unknownByExecutor = false;
		if (e.state === "pending") {
			if (e.kind === "action") rec = readRecord(cwd, e.id, limits);
		} else if (e.state === "running") {
			rec = recordOfChain(cwd, e.id, e.oid, limits);
		} else {
			const r = readResultAt(cwd, e.id, e.oid);
			if (r.ok) {
				rec = recordOfChain(cwd, e.id, r.parent, limits);
				unknownByExecutor = r.result.outcome === "unknown" && r.result.resolvedBy === "executor";
			}
		}
		if (kind === "approve" && !(e.state === "pending" && e.kind === "action" && rec && deps.adapters[rec.action])) continue;
		if (kind === "drop" && !(e.state === "pending" && e.kind === "action")) continue;
		if (kind === "resolve" && !(e.state === "running" || (e.state === "done" && unknownByExecutor))) continue;
		const name = rec?.action ?? (e.kind === "legacy" ? "退避" : "不明");
		raw.push({ id: e.id, name, ago: agoText(e.committedAt, now), summary: briefOf(rec, deps) });
	}
	const base = raw.map((r) => labelOf(r.name, r.ago, r.summary));
	return raw.map((r, i) => ({ id: r.id, label: base.indexOf(base[i]) !== base.lastIndexOf(base[i]) ? labelOf(r.name, r.ago, r.summary, r.id.slice(-4)) : base[i] }));
}

function readRecord(cwd: string, id: string, limits: NonNullable<ApproveDeps["limits"]>): OpRecord | null {
	const r = readOp(cwd, id, limits);
	return r.ok ? r.record : null;
}

const TITLES: Record<PickKind, string> = {
	approve: "承認する保留を選ぶ",
	show: "表示する対象を選ぶ",
	drop: "破棄する保留を選ぶ (元に戻せない)",
	resolve: "決着させる対象を選ぶ",
};

export type Chosen = { ok: true; id: string } | { ok: false; reply: Reply };

/** 候補から ID を決める。0 件は「無い」、approve・show の 1 件はそのまま、drop・resolve は 1 件でも選ばせる。何も選ばれなければ何もしない */
export async function chooseId(ctx: any, deps: Pick<ApproveDeps, "dialog">, kind: PickKind, candidates: Candidate[]): Promise<Chosen> {
	if (candidates.length === 0) return { ok: false, reply: info("対象が無い (/pending list で確かめる)") };
	if (candidates.length === 1 && (kind === "approve" || kind === "show")) return { ok: true, id: candidates[0].id };
	const labels = candidates.map((c) => c.label);
	const options = candidates.length === 1 ? [labels[0], CHOICE_CANCEL] : labels;
	const choice = await deps.dialog(async () => ctx.ui.select(TITLES[kind], options));
	const i = labels.indexOf(choice as string); // 選んだ行の順番で ID に対応づける (ラベルは表示だけ)
	return i < 0 ? { ok: false, reply: info("選ばなかった: 何もしていない") } : { ok: true, id: candidates[i].id };
}

/** 数字だけで 15 桁未満の指定を、その kind の候補の ID の末尾一致で解決する。複数なら、その候補だけで選ばせる (TUI のとき) */
export async function resolveShortId(ctx: any, deps: ApproveDeps, kind: PickKind, token: string): Promise<Chosen> {
	if (token.length < 3) return { ok: false, reply: refuse("短すぎる: 末尾の指定は 3 桁以上にする") };
	const cands = pickCandidates(String(ctx.cwd), kind, deps).filter((c) => c.id.endsWith(token));
	if (cands.length === 0) return { ok: false, reply: info("見つからない (/pending list で確認する)") };
	if (cands.length === 1) return { ok: true, id: cands[0].id };
	if (ctx.mode !== "tui" || !ctx.hasUI) return { ok: false, reply: refuse("一意でない。桁を増やす") };
	return chooseId(ctx, deps, kind, cands);
}

const KIND_TEXT: Record<ResolveArgs["kind"], string> = {
	pending: "保留に戻す (まだ実行していない。もう一度承認できる)",
	abandon: "放棄する (実行しなかったことにして閉じる)",
	success: "成功として記録する (操作は完了したと確かめた)",
	failed: "失敗として記録する (操作は完了していないと確かめた)",
	retry: "やり直す (新しい要求を作る。再承認が要る)",
};
const STOPPED_YES = "確かめた (実行者と git・hook は止まっている)";
const STOPPED_NO = "確かめていない (決着させない)";

/** resolve の対話: ID (省略時) → 結果の種類 (その段階で有効なものだけ) → 止まった確認 (排他の操作の started だけ) → resolvePending */
export async function resolveInteractive(idIn: string | undefined, ctx: any, deps: ApproveDeps): Promise<Reply> {
	if (ctx.mode !== "tui" || !ctx.hasUI) return refuse("resolve の対話は、対話 (TUI) の pi だけでできる (resolve <id> <結果> なら指定できる)");
	const cwd = String(ctx.cwd);
	const limits = deps.limits ?? DEFAULT_LIMITS;
	let id = idIn;
	if (!id) {
		const c = await chooseId(ctx, deps, "resolve", pickCandidates(cwd, "resolve", deps));
		if (!c.ok) return c.reply;
		id = c.id;
	}
	let kinds: ResolveArgs["kind"][];
	let exclusiveStarted = false;
	const run = runningOid(cwd, id);
	if (run) {
		const att = readAttemptAt(cwd, id, run);
		if (!att.ok) return refuse("試行の記録を読めない。自分のシェルで確かめる");
		const started = att.attempt.stage === "started";
		kinds = started ? ["success", "failed", "retry"] : ["pending", "abandon"];
		const name = recordOfChain(cwd, id, run, limits)?.action;
		exclusiveStarted = started && name !== undefined && deps.adapters?.[name]?.exclusive === true;
	} else {
		const done = doneOid(cwd, id);
		const r = done ? readResultAt(cwd, id, done) : null;
		if (!r?.ok || r.result.outcome !== "unknown" || r.result.resolvedBy !== "executor") return refuse("決着させる対象が無い (running か、実行器が記録した unknown だけ)");
		kinds = ["success", "failed"];
	}
	const options = kinds.map((k) => `${k} — ${KIND_TEXT[k]}`);
	const picked = await deps.dialog(async () => ctx.ui.select(`決着の種類を選ぶ (${id})`, options));
	const k = options.indexOf(picked as string);
	if (k < 0) return info("選ばなかった: 何もしていない");
	let confirmStopped = false;
	if (exclusiveStarted) {
		const sure = await deps.dialog(async () => ctx.ui.select(`実行者と git・hook が止まったことを確かめましたか (${id})`, [STOPPED_YES, STOPPED_NO]));
		if (sure === undefined) return info("選ばなかった: 何もしていない");
		confirmStopped = sure === STOPPED_YES;
	}
	return resolvePending(id, { kind: kinds[k], confirmStopped }, ctx, deps);
}

/** pi の getArgumentCompletions 用。prefix はコマンド名の後ろの全体 (空白を含む) で、返す value がそれを置き換える */
export function completeArgs(prefix: string, cwd: string, deps: PickDeps): { value: string; label: string; description?: string }[] | null {
	const m = /^(\S*)(\s+)(\S*)$/.exec(prefix);
	if (!m) {
		if (/\s/.test(prefix)) return null;
		const subs = SUBCOMMANDS.filter(([s]) => s.startsWith(prefix)).map(([s, d]) => ({ value: s, label: s, description: d }));
		return subs.length ? subs : null;
	}
	const [, sub, , typed] = m;
	if (!ID_SUBCOMMANDS.includes(sub)) return null;
	const items = pickCandidates(cwd, sub as PickKind, deps)
		.filter((c) => c.id.startsWith(typed))
		.map((c) => ({ value: `${sub} ${c.id}`, label: c.label }));
	return items.length ? items : null;
}
