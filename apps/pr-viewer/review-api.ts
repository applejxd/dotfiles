// PR ビューアのレビュー API（段 2: コメントの保存・レビューの送信・レビュー状態の読み出し）。
// 契約: .tmp/keep/prv-app/api-contract-write.md。ref への書き込みは appendEvents だけで行う。
// harness から import してよいのは review-log.ts と review-git.ts だけ（試験で固定）。
import { createHash } from "node:crypto";
import { realpathSync } from "node:fs";
import { basename, resolve } from "node:path";
import { appendEvents, readPr } from "../../home/dot_config/pi/harness/review-git.ts";
import { SCHEMA, SCHEMA_BRIEF, foldState, newId, prKeyOf } from "../../home/dot_config/pi/harness/review-log.ts";
import type { Anchor, Batch, BriefEvent, CommentEvent, ReviewEvent, SubmitKind, Vs } from "../../home/dot_config/pi/harness/review-log.ts";
import { briefView } from "./brief.ts";
import type { BriefData } from "./brief.ts";
import { ApiError, git, gitAdapter, gitWrite, isOid } from "./git-view.ts";
import type { FileEntry, Repo } from "./git-view.ts";

/** 1 つの PR について、書き込みと読み出しに要る情報。 */
export type PrCtx = {
	repo: Repo;
	prKey: string;
	branch: string;
	target: string;
	sourceOid: string;
	targetOid: string;
	baseOid: string;
	files: FileEntry[];
};

const MAX_BODY_CHARS = 8000;
const MAX_BODY_BYTES = 16384;
const MAX_LINE = 10_000_000;

const sha16 = (s: string): string => createHash("sha256").update(s).digest("hex").slice(0, 16);

const bad = (code: string, message: string): ApiError => new ApiError(400, code, message);
const isObj = (x: unknown): x is Record<string, unknown> => typeof x === "object" && x !== null && !Array.isArray(x);

function currentVs(c: PrCtx): Vs {
	return { source: c.sourceOid, target: c.targetOid, base: c.baseOid };
}

// ---- 表示していた版の固定 ----

const OID_RE = /^[0-9a-f]{40}$/;

/** 省略可の expect（画面が表示していた版）を、現在の PR と照合する。違えば 409、形が違えば 400。 */
function checkExpect(c: PrCtx, raw: unknown): void {
	if (raw === undefined) return;
	const fail = (): ApiError => bad("bad_expect", "表示中の版の指定が正しくありません。");
	if (!isObj(raw)) throw fail();
	const keys = Object.keys(raw);
	if (keys.length !== 3 || !(["source", "target", "base"] as const).every((k) => keys.includes(k))) throw fail();
	const { source, target, base } = raw;
	for (const v of [source, target, base]) if (typeof v !== "string" || !OID_RE.test(v)) throw fail();
	if (source !== c.sourceOid || target !== c.targetOid || base !== c.baseOid) {
		throw new ApiError(409, "stale_view", "表示中の版から PR が更新されています。再読み込みしてから送ってください。");
	}
}

// ---- blob ----

/** そのファイルの旧・新の blob OID。追加なら oldBlob、削除なら newBlob が null。 */
export async function blobsFor(repo: Repo, c: { baseOid: string; sourceOid: string }, file: FileEntry): Promise<{ oldBlob: string | null; newBlob: string | null }> {
	const at = async (commit: string, path: string): Promise<string | null> => {
		const r = await git(repo, ["rev-parse", "--verify", "--quiet", `${commit}:${path}`], true);
		const oid = r.out.trim();
		return r.code === 0 && isOid(oid) ? oid : null;
	};
	const oldBlob = file.status === "A" ? null : await at(c.baseOid, file.oldPath ?? file.path);
	const newBlob = file.status === "D" ? null : await at(c.sourceOid, file.path);
	return { oldBlob, newBlob };
}

// ---- 作業ツリー（宛先の候補） ----

export type WorktreeInfo = { worktreeId: string; name: string; isMain: boolean };

function normalizePath(p: string): string {
	try {
		return realpathSync(resolve(p));
	} catch {
		return resolve(p);
	}
}

/** `git worktree list --porcelain` から候補を作る。パスは返さない（ID と表示名だけ）。 */
export async function listWorktrees(repo: Repo): Promise<WorktreeInfo[]> {
	const r = await gitWrite(repo, ["worktree", "list", "--porcelain"]);
	const out: WorktreeInfo[] = [];
	if (r.code !== 0) return out;
	for (const block of r.stdout.split("\n\n")) {
		const lines = block.split("\n");
		const first = lines.find((l) => l.startsWith("worktree "));
		if (!first || lines.some((l) => l.startsWith("prunable"))) continue;
		const path = first.slice("worktree ".length);
		const worktreeId = sha16(normalizePath(path));
		if (out.some((w) => w.worktreeId === worktreeId)) continue;
		out.push({ worktreeId, name: basename(path), isMain: out.length === 0 });
	}
	return out;
}

// ---- GET …/review ----

function emptyReview(worktrees: WorktreeInfo[]): Record<string, unknown> {
	return {
		schema: SCHEMA,
		readonly: false,
		bad: null,
		review: "none",
		reviewStale: false,
		stale: false,
		staleParts: { source: false, target: false, base: false },
		merged: false,
		threads: [],
		batches: [],
		summary: null,
		worktrees,
		defaultDest: { worktreeId: worktrees[0]?.worktreeId ?? "" },
		unsent: 0,
		brief: null,
	};
}

/** レビュー状態を読む。ref が無くても書かない。 */
export async function getReview(c: PrCtx): Promise<unknown> {
	const worktrees = await listWorktrees(c.repo);
	const base = emptyReview(worktrees);
	const r = await readPr(gitAdapter(c.repo), c.prKey);
	if (r.kind === "none") return base;
	if (r.kind === "readonly") return { ...base, readonly: true };
	if (r.kind === "bad") return { ...base, bad: r.reason };
	const st = foldState(r.meta, r.events, currentVs(c));
	const sent = new Set(st.batches.flatMap((b) => b.items));
	const all = st.threads.flatMap((t) => t.comments).filter((e) => e.by === "app");
	return {
		...base,
		review: st.review,
		reviewStale: st.reviewStale,
		stale: st.stale,
		staleParts: st.staleParts,
		merged: st.merge.succeeded,
		threads: st.threads.map((t) => ({
			id: t.id,
			status: t.status,
			stale: t.stale,
			comments: t.comments.map(commentView),
		})),
		batches: st.batches,
		brief: st.brief ? briefView(st.brief) : null,
		summary: st.summary ? { ...st.summary.d, at: st.summary.at, by: st.summary.by } : null,
		unsent: all.filter((e) => !sent.has(e.id)).length,
	};
}

function commentView(e: CommentEvent): { id: string; by: string; at: string; body: string; anchor: Anchor | null } {
	return { id: e.id, by: e.by, at: e.at, body: e.d.body, anchor: e.d.anchor };
}

// ---- 書き込みの共通 ----

type AppendOut = Awaited<ReturnType<typeof appendEvents>>;

/** appendEvents の結果を契約のエラーに直す。メッセージに内部の情報を含めない。 */
function failOf(res: AppendOut): ApiError | null {
	if (res.ok) return null;
	if ("error" in res) {
		if (res.error === "cas_exhausted") return new ApiError(409, "conflict", "ほかの書き込みと競合しました。もう一度お試しください。");
		return new ApiError(500, "write_failed", "保存に失敗しました。");
	}
	switch (res.refused) {
		case "merged":
			return new ApiError(409, "merged", "統合済みの PR には書き込めません。");
		case "bad":
			return new ApiError(409, "bad_state", "レビュー状態が壊れているため書き込めません。");
		case "readonly":
			return new ApiError(409, "readonly", "新しい版で作られたレビュー状態のため、読み取り専用です。");
		case "body_too_large":
		case "events_too_large":
		case "too_many_events":
		case "reserved":
		case "too_many_prs":
			return new ApiError(413, "limit", "レビュー状態の上限に達しました。");
		case "bad_thread":
			return bad("bad_thread", "スレッドが見つかりません。");
		case "bad_resend":
			return bad("bad_resend", "再送する送信が見つかりません。");
		case "nothing_to_send":
			return bad("nothing_to_send", "送るコメントがありません。");
		case "not_found":
			return new ApiError(404, "not_found", "見つかりません。");
		default:
			return new ApiError(400, "bad_request", "書き込みを受け付けられませんでした。");
	}
}

function metaOf(c: PrCtx) {
	return { schema: SCHEMA, pr: c.prKey, branch: c.branch, target: c.target, createdAt: new Date().toISOString() };
}

function baseOf(c: PrCtx): { v: 1; by: "app"; at: string; vs: Vs } {
	return { v: 1, by: "app", at: new Date().toISOString(), vs: currentVs(c) };
}

// ---- POST …/comments ----

async function checkAnchor(c: PrCtx, raw: unknown): Promise<Anchor | null> {
	if (raw === undefined || raw === null) return null;
	const fail = (): ApiError => bad("bad_anchor", "コメントの位置が正しくありません。");
	if (!isObj(raw)) throw fail();
	const { path, side, blob, line, lineEnd } = raw;
	if (typeof path !== "string" || (side !== "old" && side !== "new") || typeof blob !== "string") throw fail();
	if (!Number.isInteger(line) || !Number.isInteger(lineEnd)) throw fail();
	const a = line as number;
	const b = lineEnd as number;
	if (a < 1 || b < a || b > MAX_LINE) throw fail();
	const file = c.files.find((f) => f.path === path);
	if (!file || !/^[0-9a-f]{40}$/.test(blob)) throw fail();
	const blobs = await blobsFor(c.repo, c, file);
	const expect = side === "old" ? blobs.oldBlob : blobs.newBlob;
	if (expect === null || expect !== blob) throw fail();
	return { path, side, blob, line: a, lineEnd: b };
}

export async function postComment(c: PrCtx, input: Record<string, unknown>): Promise<unknown> {
	const { body, thread } = input;
	checkExpect(c, input.expect);
	if (typeof body !== "string" || body.trim() === "") throw bad("bad_body", "コメントの本文が空です。");
	if (body.length > MAX_BODY_CHARS || Buffer.byteLength(body, "utf8") > MAX_BODY_BYTES) {
		throw bad("bad_body", "コメントの本文が長すぎます。");
	}
	if (thread !== undefined && thread !== null && typeof thread !== "string") throw bad("bad_thread", "スレッドが見つかりません。");
	if (typeof thread === "string" && input.anchor !== undefined && input.anchor !== null) {
		throw bad("bad_anchor", "返信には位置を指定できません。");
	}
	const anchor = typeof thread === "string" ? null : await checkAnchor(c, input.anchor);
	const id = newId();
	let event: CommentEvent | null = null;
	const res = await appendEvents(
		gitAdapter(c.repo),
		c.prKey,
		metaOf(c),
		(state) => {
			if (typeof thread === "string" && !state.threads.some((t) => t.id === thread)) return { refuse: "bad_thread" };
			event = { ...baseOf(c), id, t: "comment", d: { thread: typeof thread === "string" ? thread : id, anchor, body } };
			return [event as ReviewEvent];
		},
		{ current: currentVs(c) },
	);
	const err = failOf(res);
	if (err) throw err;
	const e = event as CommentEvent | null;
	if (!e) throw new ApiError(500, "write_failed", "保存に失敗しました。");
	return { comment: { id: e.id, thread: e.d.thread, by: e.by, at: e.at, body: e.d.body, anchor: e.d.anchor } };
}

// ---- 統合の補助（表示用の読み出しと、成功の記録） ----

export type ReviewHints = { summaryMessage: string | null; summaryStale: boolean; warnings: { code: string; message: string }[] };

/**
 * 統合の承認シートに出す、レビュー記録からの表示用の情報（下書きのメッセージ・古さ・警告）。
 * 権限の根拠にはしない。記録が無い・壊れているときは、何も言わない（拒否の理由にしない）。
 */
export async function reviewHints(c: PrCtx): Promise<ReviewHints> {
	const none: ReviewHints = { summaryMessage: null, summaryStale: false, warnings: [] };
	const r = await readPr(gitAdapter(c.repo), c.prKey);
	if (r.kind !== "ok") return none;
	const st = foldState(r.meta, r.events, currentVs(c));
	const s = st.summary;
	const msg = s && typeof s.d.mergeMessage === "string" ? s.d.mergeMessage : null;
	const stale = s ? s.vs.source !== c.sourceOid || s.vs.target !== c.targetOid || s.vs.base !== c.baseOid : false;
	const warnings: { code: string; message: string }[] = [];
	if (st.review === "changes") warnings.push({ code: "review_changes", message: "変更依頼のままです。" });
	if (st.review !== "none" && st.reviewStale) warnings.push({ code: "review_stale", message: "最後のレビューの後に PR が更新されています。" });
	const sent = new Set(st.batches.flatMap((b) => b.items));
	const unsent = st.threads.flatMap((t) => t.comments).filter((e) => e.by === "app" && !sent.has(e.id)).length;
	if (unsent > 0) warnings.push({ code: "unsent_comments", message: `未送信のコメントが ${unsent} 件あります。` });
	return { summaryMessage: msg, summaryStale: stale, warnings };
}

/**
 * 成功した統合を、表示用に記録する（merge_request と merge_result を 1 回の追記で書く）。権限の根拠にはしない。
 * 書けなかったときは false（統合の成功は取り消さない）。
 */
export async function recordMerge(c: PrCtx, m: { requestId: string; message: string; cleanup: string; commit: string }): Promise<boolean> {
	const res = await appendEvents(
		gitAdapter(c.repo),
		c.prKey,
		metaOf(c),
		() => [
			{
				...baseOf(c),
				id: newId(),
				t: "merge_request",
				d: {
					requestId: m.requestId,
					sourceRef: `refs/heads/${c.branch}`,
					sourceOid: c.sourceOid,
					targetRef: `refs/heads/${c.target}`,
					targetOid: c.targetOid,
					baseOid: c.baseOid,
					message: m.message,
					cleanup: m.cleanup,
				},
			} as ReviewEvent,
			{ ...baseOf(c), id: newId(), t: "merge_result", d: { requestId: m.requestId, outcome: "success", doneOid: m.commit } } as ReviewEvent,
		],
		{ current: currentVs(c) },
	);
	return res.ok === true;
}

// ---- 起票の依頼文（brief） ----

const ZERO_OID = "0".repeat(40);

/** 起票の記録（brief）を読む。記録が無い・読めない・壊れているときは null（表示と再送の照合にだけ使う。権限の根拠にしない）。 */
export async function readBriefRecord(repo: Repo, prKey: string): Promise<{ brief: BriefEvent; baseOid: string } | null> {
	let r;
	try {
		r = await readPr(gitAdapter(repo), prKey);
	} catch {
		return null;
	}
	if (r.kind !== "ok") return null;
	const st = foldState(r.meta, r.events, { source: ZERO_OID, target: ZERO_OID, base: ZERO_OID });
	return st.brief ? { brief: st.brief, baseOid: st.brief.vs.base } : null;
}

/**
 * 起票した枝（0 コミット）の記録かを調べる。依頼文の記録があり、枝の先頭が起票時の基点のままで、統合の成功が無いときだけ true。
 * 一覧で「統合済み」と区別して「起票のみ（empty）」と見せるための表示用。
 */
export async function isUntouchedBrief(repo: Repo, prKey: string, sourceOid: string): Promise<boolean> {
	const rec = await readBriefRecord(repo, prKey);
	if (!rec || rec.brief.vs.source !== sourceOid) return false;
	let r;
	try {
		r = await readPr(gitAdapter(repo), prKey);
	} catch {
		return false;
	}
	if (r.kind !== "ok") return false;
	return !foldState(r.meta, r.events, { source: ZERO_OID, target: ZERO_OID, base: ZERO_OID }).merge.succeeded;
}

/**
 * 起票の依頼文を、新しい記録（refs/pi/review/<prKey>。meta.schema 2）の最初のイベントとして書く（CAS 新規）。
 * 記録が既にあれば何も書かない（上書きしない）。書けたときだけ true。
 */
export async function recordBrief(repo: Repo, branch: string, target: string, baseOid: string, d: BriefData): Promise<boolean> {
	const prKey = prKeyOf(branch);
	const vs: Vs = { source: baseOid, target: baseOid, base: baseOid };
	const at = new Date().toISOString();
	const res = await appendEvents(
		gitAdapter(repo),
		prKey,
		{ schema: SCHEMA_BRIEF, pr: prKey, branch, target, createdAt: at },
		(state) => (state.brief !== null || state.threads.length > 0 ? { refuse: "exists" } : [{ v: 1, id: newId(), by: "app", at, vs, t: "brief", d } as ReviewEvent]),
		{ current: vs },
	);
	return res.ok === true && !("noop" in res);
}

// ---- POST …/submit ----

export async function postSubmit(c: PrCtx, input: Record<string, unknown>): Promise<unknown> {
	const kind = input.kind;
	if (kind !== "comment" && kind !== "changes" && kind !== "approve") throw bad("bad_kind", "送信の種別が正しくありません。");
	checkExpect(c, input.expect);
	const worktrees = await listWorktrees(c.repo);
	let dest = { worktreeId: worktrees[0]?.worktreeId ?? "" };
	if (input.dest !== undefined && input.dest !== null) {
		const d = input.dest;
		if (!isObj(d) || typeof d.worktreeId !== "string" || !worktrees.some((w) => w.worktreeId === d.worktreeId)) {
			throw bad("bad_dest", "宛先が正しくありません。");
		}
		dest = { worktreeId: d.worktreeId };
	}
	if (dest.worktreeId === "") throw bad("bad_dest", "宛先の作業ツリーがありません。");
	const resendOf = input.resendOf;
	if (resendOf !== undefined && resendOf !== null && typeof resendOf !== "string") throw bad("bad_resend", "再送する送信が見つかりません。");
	let sent: { batchId: string; items: string[] } | null = null;
	const res = await appendEvents(
		gitAdapter(c.repo),
		c.prKey,
		metaOf(c),
		(state) => {
			let items: string[];
			if (typeof resendOf === "string") {
				const old: Batch | undefined = state.batches.find((b) => b.batchId === resendOf);
				if (!old) return { refuse: "bad_resend" };
				items = [...old.items];
			} else {
				// 最新の状態から、どの送信にも入っていないコメントを求める（競合して再計算されても正しい）
				const taken = new Set(state.batches.flatMap((b) => b.items));
				const all = state.threads.flatMap((t) => t.comments).filter((e) => e.by === "app" && !taken.has(e.id));
				items = all
					.map((e, i) => ({ e, i }))
					.sort((x, y) => (x.e.at < y.e.at ? -1 : x.e.at > y.e.at ? 1 : x.i - y.i))
					.map((x) => x.e.id);
			}
			if (kind === "comment" && items.length === 0) return { refuse: "nothing_to_send" };
			const batchId = newId();
			sent = { batchId, items };
			const d: { batchId: string; kind: SubmitKind; items: string[]; dest: { worktreeId: string }; resendOf?: string } = {
				batchId,
				kind,
				items,
				dest,
			};
			if (typeof resendOf === "string") d.resendOf = resendOf;
			return [{ ...baseOf(c), id: newId(), t: "submit", d } as ReviewEvent];
		},
		{ current: currentVs(c) },
	);
	const err = failOf(res);
	if (err) throw err;
	const s = sent as { batchId: string; items: string[] } | null;
	if (!s) throw new ApiError(500, "write_failed", "保存に失敗しました。");
	return { batchId: s.batchId, kind, items: s.items, dest };
}
