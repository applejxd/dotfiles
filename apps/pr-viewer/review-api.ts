// PR ビューアのレビュー API（レビュー状態の読み出しと、統合の補助）。
// ref への書き込みは appendEvents だけで行う（統合結果の記録のみ。コメントの送信は撤去した。docs/spec/pr-viewer.md）。
// harness から import してよいのは review-log.ts と review-git.ts だけ（試験で固定）。
import { appendEvents, readPr } from "../../home/dot_config/pi/harness/review-git.ts";
import { SCHEMA, foldState, newId } from "../../home/dot_config/pi/harness/review-log.ts";
import type { ReviewEvent, Vs } from "../../home/dot_config/pi/harness/review-log.ts";
import { gitAdapter } from "./git-view.ts";
import type { Repo } from "./git-view.ts";

/** 1 つの PR について、読み出しと統合の記録に要る情報。 */
export type PrCtx = {
	repo: Repo;
	prKey: string;
	branch: string;
	target: string;
	sourceOid: string;
	targetOid: string;
	baseOid: string;
};

function currentVs(c: PrCtx): Vs {
	return { source: c.sourceOid, target: c.targetOid, base: c.baseOid };
}

// ---- GET …/review ----

function emptyReview(): Record<string, unknown> {
	return {
		schema: SCHEMA,
		readonly: false,
		bad: null,
		stale: false,
		staleParts: { source: false, target: false, base: false },
		merged: false,
		summary: null,
	};
}

/** レビュー状態（サマリーと統合済みかどうか）を読む。ref が無くても書かない。 */
export async function getReview(c: PrCtx): Promise<unknown> {
	const base = emptyReview();
	const r = await readPr(gitAdapter(c.repo), c.prKey);
	if (r.kind === "none") return base;
	if (r.kind === "readonly") return { ...base, readonly: true };
	if (r.kind === "bad") return { ...base, bad: r.reason };
	const st = foldState(r.meta, r.events, currentVs(c));
	return {
		...base,
		stale: st.stale,
		staleParts: st.staleParts,
		merged: st.merge.succeeded,
		summary: st.summary ? { ...st.summary.d, at: st.summary.at, by: st.summary.by } : null,
	};
}

// ---- 書き込みの共通 ----

function metaOf(c: PrCtx) {
	return { schema: SCHEMA, pr: c.prKey, branch: c.branch, target: c.target, createdAt: new Date().toISOString() };
}

function baseOf(c: PrCtx): { v: 1; by: "app"; at: string; vs: Vs } {
	return { v: 1, by: "app", at: new Date().toISOString(), vs: currentVs(c) };
}

// ---- 統合の補助（表示用の読み出しと、成功の記録） ----

export type ReviewHints = { summaryMessage: string | null; summaryStale: boolean };

/**
 * 統合の承認シートに出す、レビュー記録からの表示用の情報（下書きのメッセージ・古さ）。
 * 権限の根拠にはしない。記録が無い・壊れているときは、何も言わない（拒否の理由にしない）。
 */
export async function reviewHints(c: PrCtx): Promise<ReviewHints> {
	const none: ReviewHints = { summaryMessage: null, summaryStale: false };
	const r = await readPr(gitAdapter(c.repo), c.prKey);
	if (r.kind !== "ok") return none;
	const st = foldState(r.meta, r.events, currentVs(c));
	const s = st.summary;
	const msg = s && typeof s.d.mergeMessage === "string" ? s.d.mergeMessage : null;
	const stale = s ? s.vs.source !== c.sourceOid || s.vs.target !== c.targetOid || s.vs.base !== c.baseOid : false;
	return { summaryMessage: msg, summaryStale: stale };
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
