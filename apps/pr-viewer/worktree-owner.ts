// worktree の所有の表明（`git worktree lock` の理由欄）。規則は scripts/wt_owner.py と同じ。
// 仕様: docs/spec/orchestration.md#worktree-の所有の表明。理由欄は 1 行 `owner=<kind> id=<id> pid=<pid> started=<unix 秒>`。
// 持ち主の pid が死んでいれば残骸（解除してよい）。`owner=` で始まらない lock（人が付けたもの）は不明の lock として触らない。
// git は merge-git.ts の runGit だけで動かす（新しい実行器は作らない）。
import { realpathSync } from "node:fs";
import { runGit } from "./merge-git.ts";

export const OWNER_KINDS = ["worker", "job", "create", "train", "interactive"] as const;
export type OwnerKind = (typeof OWNER_KINDS)[number];
export type Owner = { kind: OwnerKind; id: string; pid: number; started: number };
export type OwnerState =
	| { state: "none" }
	| { state: "unknown"; reason: string } // 人が付けた lock など。自動では解除しない
	| { state: "owner"; owner: Owner; alive: boolean };
export type ClaimResult = { ok: true } | { ok: false; holder: OwnerState | null };

const REASON_RE = /^owner=(\S+) id=(\S+) pid=(\d+) started=(\d+)$/;

/** 理由欄を作る。id は空白を含まない 1 語。 */
export function formatReason(o: Owner): string {
	if (!/^\S+$/.test(o.id) || !(OWNER_KINDS as readonly string[]).includes(o.kind)) throw new Error("bad_owner");
	return `owner=${o.kind} id=${o.id} pid=${o.pid} started=${o.started}`;
}

export function parseOwner(reason: string): Owner | null {
	const m = REASON_RE.exec(reason);
	if (!m || !(OWNER_KINDS as readonly string[]).includes(m[1])) return null;
	return { kind: m[1] as OwnerKind, id: m[2], pid: Number(m[3]), started: Number(m[4]) };
}

/** pid が生きているか（kill -0。権限が無い EPERM は生きている扱い）。 */
export function isAlive(pid: number): boolean {
	if (!Number.isInteger(pid) || pid <= 0) return false;
	try {
		process.kill(pid, 0);
		return true;
	} catch (e) {
		return (e as NodeJS.ErrnoException).code === "EPERM";
	}
}

function real(p: string): string {
	try {
		return realpathSync(p);
	} catch {
		return p;
	}
}

/** worktree の path → lock の理由（lock 無しは undefined、理由なしの lock は ""）。読めなければ null。 */
async function lockReasons(gitDir: string): Promise<Map<string, string> | null> {
	const r = await runGit(["worktree", "list", "--porcelain", "-z"], { gitDir });
	if (r.code !== 0) return null;
	const res = new Map<string, string>();
	let cur: string | null = null;
	for (const tok of r.out.split("\0")) {
		if (tok === "") {
			cur = null;
		} else if (tok.startsWith("worktree ")) {
			cur = real(tok.slice("worktree ".length));
		} else if (cur !== null && (tok === "locked" || tok.startsWith("locked "))) {
			res.set(cur, tok.slice("locked".length).trim());
		}
	}
	return res;
}

/** worktree の所有の状態。git で読めなければ null。 */
export async function readOwner(gitDir: string, wt: string): Promise<OwnerState | null> {
	const m = await lockReasons(gitDir);
	if (m === null) return null;
	const reason = m.get(real(wt));
	if (reason === undefined) return { state: "none" };
	const owner = parseOwner(reason);
	if (owner === null) return { state: "unknown", reason };
	return { state: "owner", owner, alive: isAlive(owner.pid) };
}

/**
 * 所有を表明する（lock）。他の有効な owner・不明の lock があれば ok:false（holder に現状）。
 * 残骸（死んだ pid）も拒否（holder.alive=false。reap で解除してから）。同じ id の再 claim は冪等（pid・時刻は付け直さない）。
 */
export async function claim(gitDir: string, wt: string, o: { kind: OwnerKind; id: string; pid?: number }): Promise<ClaimResult> {
	const owner: Owner = { kind: o.kind, id: o.id, pid: o.pid ?? process.pid, started: Math.floor(Date.now() / 1000) };
	const reason = formatReason(owner);
	const path = real(wt);
	for (let attempt = 0; attempt < 2; attempt++) {
		const st = await readOwner(gitDir, wt);
		if (st === null) return { ok: false, holder: null };
		if (st.state === "unknown") return { ok: false, holder: st };
		if (st.state === "owner") {
			if (st.owner.id === o.id) return { ok: true };
			// 残骸も自動では奪わない（unlock→lock は原子的でなく、古い観測で他方の新しい lock を外しうる）。reap だけが解除する
			return { ok: false, holder: st };
		}
		// lock は既に locked なら失敗する（= 取り合いに負けたら再読みして拒否側へ）
		const r = await runGit(["worktree", "lock", "--reason", reason, path], { gitDir, write: true });
		if (r.code === 0) return { ok: true };
	}
	return { ok: false, holder: await readOwner(gitDir, wt) };
}

/**
 * 残骸（pid が死んだ owner の lock）だけを解除する。観測した理由欄を再読して一致する場合だけ unlock する。
 * 返り値は解除した worktree の数。
 */
export async function reap(gitDir: string): Promise<number> {
	const m = await lockReasons(gitDir);
	if (m === null) return 0;
	let n = 0;
	for (const [wt, reason] of m) {
		const o = parseOwner(reason);
		if (o === null || isAlive(o.pid)) continue;
		const again = await lockReasons(gitDir);
		if (again === null || again.get(wt) !== reason) continue;
		if ((await runGit(["worktree", "unlock", wt], { gitDir, write: true })).code === 0) n++;
	}
	return n;
}

/** 解除する。id が違う・自分の lock でないときは解除しない（false）。lock が無ければ true。 */
export async function release(gitDir: string, wt: string, id?: string): Promise<boolean> {
	const st = await readOwner(gitDir, wt);
	if (st === null) return false;
	if (st.state === "none") return true;
	if (st.state === "unknown") return false;
	if (id !== undefined && st.owner.id !== id) return false;
	return (await runGit(["worktree", "unlock", real(wt)], { gitDir, write: true })).code === 0;
}
