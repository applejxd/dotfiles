// 承認が取れなかった git commit を、表示した内容のまま退避する (CHG-0046 の試作)。
// 表示の前に tree を確定 (snapshotStaged) し、時間切れのあとは実のインデックスを読み直さずに、その tree を保存する。
// 退避は独立 (親は表示時点の HEAD。ほかの退避を親にしない)。HEAD・ブランチ・インデックス・作業ツリーに触れない。
// see docs/change/0046-guarded-action-timeout.md
import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";

export const PENDING_PREFIX = "refs/pi/pending/";

export type Snapshot = {
	treeOid: string;
	/** 表示時点の HEAD。コミットが無いリポジトリでは空 */
	baseHeadOid: string;
	/** 表示時点のブランチの ref (detached は空) */
	branchRef: string;
	indexId: string;
	message: string;
	requestId: string;
};
export type Saved = { ok: true; ref: string; short: string } | { ok: false; reason: string };
export type PendingEntry = { ref: string; oid: string; subject: string; branch: string; head: string };

type Run = { ok: boolean; out: string };

function git(cwd: string, args: string[], opts: { env?: Record<string, string>; input?: string } = {}): Run {
	const r = spawnSync("git", ["-c", "core.fsmonitor=false", "-c", "core.quotepath=false", ...args], {
		cwd,
		encoding: "utf8",
		timeout: 15000,
		input: opts.input,
		env: { ...process.env, ...opts.env, GIT_OPTIONAL_LOCKS: "0", GIT_TERMINAL_PROMPT: "0" },
	});
	return { ok: r.status === 0, out: String(r.stdout ?? "").replace(/\n+$/, "") };
}

function indexId(cwd: string): string | null {
	const r = spawnSync("git", ["ls-files", "-s", "-z"], { cwd, env: { ...process.env, GIT_OPTIONAL_LOCKS: "0" } });
	return r.status === 0 ? createHash("sha256").update(r.stdout).digest("hex") : null;
}

/** 確認の表示の前に呼ぶ。ステージ済みの内容の tree を確定する。確定の途中で状態が変わった・空なら null */
export function snapshotStaged(cwd: string, message: string, requestId: string): Snapshot | null {
	const before = indexId(cwd);
	if (!before) return null;
	const head = git(cwd, ["rev-parse", "-q", "--verify", "HEAD^{commit}"]);
	const baseTree = head.ok ? git(cwd, ["rev-parse", "HEAD^{tree}"]).out : "";
	const tree = git(cwd, ["write-tree"]);
	if (!tree.ok || !tree.out) return null;
	// ステージ済みが無い (HEAD と同じ内容)。コミットできないものは退避しない
	if (head.ok && tree.out === baseTree) return null;
	const branchRef = git(cwd, ["symbolic-ref", "-q", "HEAD"]).out;
	const headAfter = git(cwd, ["rev-parse", "-q", "--verify", "HEAD^{commit}"]);
	if (indexId(cwd) !== before || (head.ok ? head.out : "") !== (headAfter.ok ? headAfter.out : "")) return null;
	return { treeOid: tree.out, baseHeadOid: head.ok ? head.out : "", branchRef, indexId: before, message, requestId };
}

/** 確定済みの tree を、表示時点の HEAD の子として退避する。実のインデックスは読まない */
export function savePendingSnapshot(cwd: string, snap: Snapshot): Saved {
	// 確定した tree が消えていない (gc などで) ことを確かめる
	if (!git(cwd, ["cat-file", "-e", `${snap.treeOid}^{tree}`]).ok) return { ok: false, reason: "確定した tree が見つからない" };
	if (snap.baseHeadOid && !git(cwd, ["cat-file", "-e", `${snap.baseHeadOid}^{commit}`]).ok) {
		return { ok: false, reason: "表示時点の HEAD が見つからない" };
	}
	const env: Record<string, string> = {};
	if (!git(cwd, ["var", "GIT_COMMITTER_IDENT"]).ok || !git(cwd, ["var", "GIT_AUTHOR_IDENT"]).ok) {
		Object.assign(env, {
			GIT_AUTHOR_NAME: "pi pending",
			GIT_AUTHOR_EMAIL: "pi-pending@localhost",
			GIT_COMMITTER_NAME: "pi pending",
			GIT_COMMITTER_EMAIL: "pi-pending@localhost",
		});
	}
	// 出自は末尾の trailer に残す (取り込みのときに外す)
	const text =
		`${snap.message.replace(/\n+$/, "")}\n\n` +
		`Pi-Pending-Request: ${snap.requestId}\n` +
		`Pi-Pending-Branch: ${snap.branchRef || "(detached)"}\n` +
		`Pi-Pending-Head: ${snap.baseHeadOid || "(none)"}\n`;
	// 署名の設定や hook に左右されない (commit-tree は hook を呼ばない)
	const made = git(
		cwd,
		["-c", "commit.gpgsign=false", "commit-tree", snap.treeOid, ...(snap.baseHeadOid ? ["-p", snap.baseHeadOid] : []), "-F", "-"],
		{ env, input: text },
	);
	if (!made.ok || !made.out) return { ok: false, reason: "commit-tree に失敗した" };
	const base = `${PENDING_PREFIX}${String(Date.now()).padStart(15, "0")}`;
	for (let n = 0; n < 20; n++) {
		const ref = n === 0 ? base : `${base}-${String(n).padStart(2, "0")}`;
		// 空の古い値 = 無いときだけ作る (同じ時刻の ref を上書きしない)
		if (git(cwd, ["update-ref", ref, made.out, ""]).ok) return { ok: true, ref, short: made.out.slice(0, 7) };
	}
	return { ok: false, reason: "ref を作れなかった" };
}

function trailer(body: string, key: string): string {
	const m = new RegExp(`^${key}: (.*)$`, "m").exec(body);
	return m ? m[1] : "";
}

/** 新しい順 */
export function listPending(cwd: string): PendingEntry[] {
	const r = git(cwd, ["for-each-ref", "--sort=-refname", "--format=%(refname)%00%(objectname)%00%(contents:subject)", PENDING_PREFIX]);
	if (!r.ok || !r.out) return [];
	return r.out.split("\n").map((line) => {
		const [ref, oid, subject] = line.split("\0");
		const body = git(cwd, ["log", "-1", "--format=%B", oid]).out;
		return { ref, oid, subject, branch: trailer(body, "Pi-Pending-Branch"), head: trailer(body, "Pi-Pending-Head") };
	});
}

/** 退避と、その親 (表示時点の HEAD) との差。親が無ければ空の tree との差 */
export function showPending(cwd: string, ref: string): string {
	if (!ref.startsWith(PENDING_PREFIX)) return "";
	return git(cwd, ["show", "--stat", "--format=%B", ref]).out;
}

/** 退避の ref を消す (オブジェクトは git gc まで残る) */
export function dropPending(cwd: string, ref: string): boolean {
	if (!ref.startsWith(PENDING_PREFIX)) return false;
	return git(cwd, ["update-ref", "-d", ref]).ok;
}
