// 承認が取れなかった git commit を、表示した内容のまま退避する (CHG-0046)。
// 表示の前に tree を確定 (snapshotStaged) し、時間切れのあとは実のインデックスを読み直さずに、その tree を保存する。
// 退避は独立 (親は表示時点の HEAD。ほかの退避を親にしない)。HEAD・ブランチ・インデックス・作業ツリーに触れない。
// ★承認なしに動くので、git の hook は無効にする (reference-transaction などが任意のコードを動かす経路になる)。
//   tree の確定は一時のインデックスで行い、実のインデックスへ書き戻さない。
// see docs/change/0046-guarded-action-timeout.md
import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { copyFileSync, existsSync, mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { isAbsolute, join } from "node:path";

export const PENDING_PREFIX = "refs/pi/pending/";

export type Snapshot = {
	treeOid: string;
	/** 表示時点の HEAD。コミットが無いリポジトリでは空 */
	baseHeadOid: string;
	/** 表示時点のブランチの ref (detached は空) */
	branchRef: string;
	/** 実のインデックスの識別子 (`git ls-files -s -z` の sha256) */
	indexId: string;
	message: string;
	requestId: string;
};
export type Saved = { ok: true; ref: string; oid: string; short: string } | { ok: false; reason: string };
export type PendingEntry = { ref: string; oid: string; subject: string; branch: string; head: string };

type Run = { ok: boolean; out: string };

// 退避の内部の git は、hook を動かさない
const SAFE = ["-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false", "-c", "core.quotepath=false"];

function git(cwd: string, args: string[], opts: { env?: Record<string, string>; input?: string } = {}): Run {
	const r = spawnSync("git", [...SAFE, ...args], {
		cwd,
		encoding: "utf8",
		timeout: 15000,
		input: opts.input,
		env: { ...process.env, ...opts.env, GIT_OPTIONAL_LOCKS: "0", GIT_TERMINAL_PROMPT: "0" },
	});
	return { ok: r.status === 0, out: String(r.stdout ?? "").replace(/\n+$/, "") };
}

function indexId(cwd: string): string | null {
	const r = spawnSync("git", [...SAFE, "ls-files", "-s", "-z"], { cwd, env: { ...process.env, GIT_OPTIONAL_LOCKS: "0" } });
	return r.status === 0 ? createHash("sha256").update(r.stdout).digest("hex") : null;
}

/** 確認の表示の前に呼ぶ。ステージ済みの内容の tree を確定する。確定の途中で状態が変わった・空なら null */
export function snapshotStaged(cwd: string, message: string, requestId: string): Snapshot | null {
	const before = indexId(cwd);
	if (!before) return null;
	const head = git(cwd, ["rev-parse", "-q", "--verify", "HEAD^{commit}"]);
	const baseTree = head.ok ? git(cwd, ["rev-parse", "HEAD^{tree}"]).out : "";
	// 実のインデックスをコピーした一時のインデックスで tree を作る (実のインデックスは書き換えない)
	const real = git(cwd, ["rev-parse", "--path-format=absolute", "--git-path", "index"]);
	if (!real.ok) return null;
	const realPath = isAbsolute(real.out) ? real.out : join(cwd, real.out);
	if (!existsSync(realPath)) return null;
	const tmp = mkdtempSync(join(tmpdir(), "pi-snap-"));
	try {
		const idx = join(tmp, "index");
		copyFileSync(realPath, idx);
		const tree = git(cwd, ["write-tree"], { env: { GIT_INDEX_FILE: idx } });
		if (!tree.ok || !tree.out) return null;
		// ステージ済みが無い (HEAD と同じ内容)。コミットできないものは退避しない
		if (head.ok && tree.out === baseTree) return null;
		const branchRef = git(cwd, ["symbolic-ref", "-q", "HEAD"]).out;
		const headAfter = git(cwd, ["rev-parse", "-q", "--verify", "HEAD^{commit}"]);
		if (indexId(cwd) !== before || (head.ok ? head.out : "") !== (headAfter.ok ? headAfter.out : "")) return null;
		return { treeOid: tree.out, baseHeadOid: head.ok ? head.out : "", branchRef, indexId: before, message, requestId };
	} finally {
		rmSync(tmp, { recursive: true, force: true });
	}
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
	// 署名の設定に左右されない (commit-tree は hook を呼ばず、SAFE が hook の探索先も無効にする)
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
		if (git(cwd, ["update-ref", "--no-deref", ref, made.out, ""]).ok) return { ok: true, ref, oid: made.out, short: made.out.slice(0, 7) };
	}
	return { ok: false, reason: "ref を作れなかった" };
}

function trailer(body: string, key: string): string {
	const m = new RegExp(`^${key}: (.*)$`, "m").exec(body);
	return m ? m[1] : "";
}

/** 新しい順。symbolic ref は数えない */
export function listPending(cwd: string): PendingEntry[] {
	const r = git(cwd, ["for-each-ref", "--sort=-refname", "--format=%(refname)%00%(objectname)%00%(contents:subject)%00%(symref)", PENDING_PREFIX]);
	if (!r.ok || !r.out) return [];
	const out: PendingEntry[] = [];
	for (const line of r.out.split("\n")) {
		const [ref, oid, subject, symref] = line.split("\0");
		if (symref) continue;
		const body = git(cwd, ["log", "-1", "--format=%B", oid]).out;
		out.push({ ref, oid, subject, branch: trailer(body, "Pi-Pending-Branch"), head: trailer(body, "Pi-Pending-Head") });
	}
	return out;
}

/** 完全な退避の ref か (名前空間の中で、symbolic ref でなく、存在する)。oid を返す */
function resolvePending(cwd: string, ref: string): string | null {
	if (!ref.startsWith(PENDING_PREFIX) || ref.includes("..") || /[\s~^:?*[\\]/.test(ref)) return null;
	if (git(cwd, ["symbolic-ref", "-q", ref]).ok) return null;
	const oid = git(cwd, ["rev-parse", "-q", "--verify", `${ref}^{commit}`]);
	return oid.ok && oid.out ? oid.out : null;
}

/** 退避と、その親 (表示時点の HEAD) との差を、本文まで出す。親が無ければ空の tree との差 */
export function showPending(cwd: string, ref: string): string {
	if (!resolvePending(cwd, ref)) return "";
	return git(cwd, ["show", "--patch", "--stat", "--no-ext-diff", "--no-textconv", "--format=%B", ref]).out;
}

/** 退避の ref を外す (到達用の ref だけ。オブジェクトは git gc まで残る)。期待する oid が合うときだけ */
export function dropPending(cwd: string, ref: string, expectedOid?: string): boolean {
	const oid = resolvePending(cwd, ref);
	if (!oid) return false;
	if (expectedOid && expectedOid !== oid) return false;
	return git(cwd, ["update-ref", "--no-deref", "-d", ref, oid]).ok;
}

/** 片付けてよい退避を、ハーネス自身が消す (モデルは消せない)。消すのは、内容がほかに残っているか、古いもの:
 *  - 同じ tree のコミットが HEAD の履歴 (新しい側の lookback 件) にある (= 取り込まれた)
 *  - 同じ tree・同じ起点の退避が、より新しくある (再試行で増えた重複)
 *  - maxAgeDays より古い (既定 30 日)
 *  消した ref の一覧を返す。git の失敗は握りつぶさず、消さない側に倒す */
export function reconcilePending(cwd: string, opts: { maxAgeDays?: number; now?: number; lookback?: number } = {}): string[] {
	const entries = listPending(cwd);
	if (entries.length === 0) return [];
	const log = git(cwd, ["log", "--format=%T", "-n", String(opts.lookback ?? 500), "HEAD"]);
	const trees = new Set(log.ok ? log.out.split("\n").filter(Boolean) : []);
	const now = opts.now ?? Date.now();
	const maxAge = (opts.maxAgeDays ?? 30) * 86_400_000;
	const seen = new Set<string>();
	const dropped: string[] = [];
	for (const e of entries) {
		const tree = git(cwd, ["rev-parse", `${e.oid}^{tree}`]);
		if (!tree.ok || !tree.out) continue;
		const key = `${tree.out}\0${e.head}`;
		const ts = Number(/^refs\/pi\/pending\/(\d+)/.exec(e.ref)?.[1]);
		const reason = trees.has(tree.out) ? "committed" : seen.has(key) ? "duplicate" : Number.isFinite(ts) && now - ts > maxAge ? "old" : "";
		seen.add(key);
		if (reason && dropPending(cwd, e.ref, e.oid)) dropped.push(e.ref);
	}
	return dropped;
}
