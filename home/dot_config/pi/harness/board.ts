// オーケストレーターの盤面 (/board) の核。「いま実際にある事実」だけを、呼び出し側が集めた入力から純関数で並べる。
// 読み取り専用の表示で、承認・操作の入口は持たない。pi・fs・git・時計・環境を読まない。
import { cellWidth, clipCells, sanitizeForDisplay } from "./confirm-view.ts";
import type { JobSnapshot } from "./children.ts";
import type { BrokenRecord, IsolationRecord } from "./worktree.ts";

export type ParsedWorktree = {
	path: string;
	head?: string;
	branch?: string;
	featureName?: string;
	bare: boolean;
	detached: boolean;
	locked: boolean;
	lockedReason?: string;
	prunable: boolean;
};

/** `git worktree list --porcelain` を解析する。不正な行は無視する */
export function parseWorktreePorcelain(text: string, featurePrefixes: readonly string[] = ["feature/"]): ParsedWorktree[] {
	const out: ParsedWorktree[] = [];
	let cur: ParsedWorktree | null = null;
	const flush = () => {
		if (cur) out.push(cur);
		cur = null;
	};
	for (const raw of String(text ?? "").split(/\r?\n/)) {
		const line = raw.trimEnd();
		if (line === "") {
			flush();
			continue;
		}
		const sp = line.indexOf(" ");
		const key = sp < 0 ? line : line.slice(0, sp);
		const val = sp < 0 ? "" : line.slice(sp + 1);
		if (key === "worktree") {
			flush();
			if (val === "") continue;
			cur = { path: val, bare: false, detached: false, locked: false, prunable: false };
			continue;
		}
		if (!cur) continue;
		const c: ParsedWorktree = cur;
		if (key === "HEAD" && val) c.head = val;
		else if (key === "branch" && val) {
			c.branch = val.startsWith("refs/heads/") ? val.slice("refs/heads/".length) : val;
			const p = featurePrefixes.find((x) => c.branch!.startsWith(x) && c.branch!.length > x.length);
			if (p !== undefined) c.featureName = c.branch.slice(p.length);
		} else if (key === "bare") c.bare = true;
		else if (key === "detached") c.detached = true;
		else if (key === "locked") {
			c.locked = true;
			if (val) c.lockedReason = val;
		} else if (key === "prunable") c.prunable = true;
	}
	flush();
	return out;
}

/** feature を置いている worktree の状態。無い項目は表示しない */
export type WorktreeState = { ahead?: number; behind?: number; dirty?: boolean; lastCommitAgeMs?: number };

export type ChildRow = Partial<Pick<JobSnapshot, "roundMs" | "lastTool" | "calls" | "tokens" | "cost">> & Pick<JobSnapshot, "id" | "agent" | "state" | "ageMs">;

export type BoardInput = {
	now: number;
	children: ChildRow[];
	isolation: (IsolationRecord | BrokenRecord)[];
	worktrees: ParsedWorktree[];
	/** 旧形式の退避 (承認が取れず退避した git commit) の件数 */
	pending: { legacyCount: number };
	modes: { bypass?: boolean; orchestrate?: boolean; sandbox?: "fence" | "none" | "unknown" };
	/** 無いときは bg の行を出さない (ハーネスは bg ジョブを見られない。「0 件」と言い切らない) */
	bgJobs?: { running: number; finished: number };
	/** キーは worktree のパス */
	worktreeStates?: Record<string, WorktreeState>;
	/** pi.json の状態を示す 1 行 (有効で既定と違う・無効のときだけ。無効は診断コードだけ) */
	profileNote?: string;
	limits?: { maxRows?: number };
};

/** tail は行末の「欠けてはいけない部分」。text は常に `<head> <tail>`。幅が足りないときは head の方を先に切る */
export type BoardRow = { text: string; broken?: boolean; tail?: string };
export type BoardSection = {
	key: "children" | "isolation" | "features" | "pending" | "modes";
	title: string;
	count: number;
	rows: BoardRow[];
	omitted: number;
};
export type BoardSnapshot = { v: 1; now: number; sections: BoardSection[] };

export const DEFAULT_MAX_ROWS = 12;

/** 短い経過時間 (3m12s・1h05m・2d3h) */
export function fmtDuration(ms: number): string {
	if (!Number.isFinite(ms) || ms < 0) return "?";
	const s = Math.floor(ms / 1000);
	if (s < 60) return `${s}s`;
	const m = Math.floor(s / 60);
	if (m < 60) return `${m}m${String(s % 60).padStart(2, "0")}s`;
	const h = Math.floor(m / 60);
	if (h < 24) return `${h}h${String(m % 60).padStart(2, "0")}m`;
	return `${Math.floor(h / 24)}d${h % 24}h`;
}

const baseName = (p: string): string => {
	const parts = String(p).split(/[\\/]+/).filter(Boolean);
	return parts.length ? parts[parts.length - 1] : String(p);
};

const cap = (rows: BoardRow[], max: number): { rows: BoardRow[]; omitted: number } =>
	rows.length <= max ? { rows, omitted: 0 } : { rows: rows.slice(0, max), omitted: rows.length - max };

const isBroken = (r: IsolationRecord | BrokenRecord): r is BrokenRecord => (r as BrokenRecord).broken === true;

const row = (head: string, tail: string): BoardRow => (tail ? { text: `${head} ${tail}`, tail } : { text: head });

function stateTail(s: WorktreeState | undefined): string {
	if (!s) return "";
	const bits: string[] = [];
	if (s.ahead !== undefined) bits.push(`↑${s.ahead}`);
	if (s.behind !== undefined) bits.push(`↓${s.behind}`);
	if (s.dirty) bits.push("dirty");
	if (s.lastCommitAgeMs !== undefined) bits.push(fmtDuration(s.lastCommitAgeMs));
	return bits.join(" ");
}

export function buildBoard(input: BoardInput): BoardSnapshot {
	const max = Math.max(1, Math.floor(input.limits?.maxRows ?? DEFAULT_MAX_ROWS));
	const children = input.children ?? [];
	const isolation = input.isolation ?? [];
	const worktrees = input.worktrees ?? [];
	const pending = input.pending ?? { legacyCount: 0 };
	const sections: BoardSection[] = [];


	// feature ⇄ worktree
	const fRows: BoardRow[] = worktrees.map((w, i) => {
		const name = baseName(w.path);
		let kind: string;
		if (i === 0) kind = "主";
		else if (name.startsWith("pi-agent-")) kind = `隔離 ${name.slice("pi-agent-".length)}`;
		else kind = w.featureName !== undefined ? `feature ${w.featureName}` : "他";
		const st = i > 0 && w.featureName !== undefined && !name.startsWith("pi-agent-") ? stateTail(input.worktreeStates?.[w.path]) : "";
		if (st) return row(kind, st);
		const br = w.bare ? "(bare)" : w.detached ? "(detached)" : (w.branch ?? "(branch なし)");
		const flags = [w.locked ? "locked" : "", w.prunable ? "prunable" : ""].filter(Boolean).join(",");
		return { text: `${kind} ${br} ${name}${flags ? ` [${flags}]` : ""}` };
	});
	sections.push({ key: "features", title: "feature ⇄ worktree", count: fRows.length, ...cap(fRows, max) });

	// 保留 (旧形式の退避の件数だけ)
	const pRows: BoardRow[] = [];
	if (pending.legacyCount > 0) pRows.push({ text: `旧形式の退避 ${pending.legacyCount} 件` });
	pRows.push({ text: "確認は /pending list" });
	sections.push({ key: "pending", title: "保留", count: pending.legacyCount, ...cap(pRows, max + 1) });

	// 子
	const cRows: BoardRow[] = children.map((c) => {
		const bits = [`${c.id} ${c.agent} ${c.state} ${fmtDuration(c.ageMs)}`];
		if (c.state === "running" && c.roundMs !== undefined) bits.push(`今回${fmtDuration(c.roundMs)}`);
		if (c.calls !== undefined) bits.push(`呼出${c.calls}`);
		if (c.tokens !== undefined) bits.push(`tok${c.tokens}`);
		if (c.cost !== undefined) bits.push(`$${c.cost.toFixed(2)}`);
		if (c.lastTool) bits.push(`最後:${c.lastTool}`);
		return { text: bits.join(" ") };
	});
	sections.push({ key: "children", title: "子", count: cRows.length, ...cap(cRows, max) });

	// 隔離 worker (壊れた記録は broken 行)
	const iRows: BoardRow[] = isolation.map((r) =>
		isBroken(r)
			? { text: `broken 壊れた記録: ${r.file}`, broken: true }
			: { text: `${r.jobId} ${r.state} ${baseName(r.worktree)}${r.note ? ` (${r.note})` : ""}` },
	);
	sections.push({ key: "isolation", title: "隔離 worker", count: iRows.length, ...cap(iRows, max) });

	// モード・bg ジョブ
	const m = input.modes ?? {};
	const onOff = (v?: boolean) => (v === undefined ? "?" : v ? "on" : "off");
	const mRows: BoardRow[] = [{ text: `bypass ${onOff(m.bypass)} / orchestrate ${onOff(m.orchestrate)} / sandbox ${m.sandbox ?? "unknown"}` }];
	if (input.bgJobs) mRows.push({ text: `bg ジョブ 実行中${input.bgJobs.running} 完了${input.bgJobs.finished}` });
	if (input.profileNote) mRows.push({ text: input.profileNote });
	sections.push({ key: "modes", title: "モード・bg", count: mRows.length, rows: mRows, omitted: 0 });

	return { v: 1, now: input.now, sections };
}

const oneLine = (s: string): string => sanitizeForDisplay(s).replace(/[\r\n\t]+/g, " ");

/** 全角を 2 桁で数えて、各行を width 桁以内にして返す */
export function renderBoard(snap: BoardSnapshot, opts: { width: number; now?: number }): string[] {
	const width = Math.max(10, Math.floor(opts.width));
	const out: string[] = [];
	const push = (s: string) => {
		out.push(clipCells(oneLine(s), width));
	};
	push(`盤面 (読み取り専用)`);
	for (const sec of snap.sections) {
		push(`■ ${sec.title} (${sec.count})`);
		if (sec.rows.length === 0) push("  なし");
		for (const r of sec.rows) {
			const prefix = "  ";
			const room = width - prefix.length;
			const text = oneLine(r.text);
			if (cellWidth(text) <= room) {
				out.push(prefix + text);
				continue;
			}
			// 状態 (tail) を欠かさず、先頭の名前の方を先に短くする。名前に 3 桁も残せないときだけ行全体を切る
			if (r.tail) {
				const tail = oneLine(r.tail);
				const head = text.slice(0, Math.max(0, text.length - tail.length - 1));
				const headRoom = room - cellWidth(tail) - 1;
				if (text.endsWith(` ${tail}`) && headRoom >= 3) {
					out.push(`${prefix}${clipCells(head, headRoom)} ${tail}`);
					continue;
				}
			}
			// 折り返さずに切る。全角は 2 桁
			out.push(prefix + clipCells(text, room));
		}
		if (sec.omitted > 0) push(`  … ${sec.omitted} 件省略`);
	}
	return out;
}
