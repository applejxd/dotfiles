// PR ビューアの起票 API（段 B1 の S）。人がブラウザで押した「起票」の POST で、新しい feature の枝と worktree を作り、依頼文を記録する。
// 契約: .tmp/keep/prv-app/api-contract-create.md。LLM・pis は呼ばない。
// 起票の権限は live の HTTP リクエスト（Origin・ヘッダー・expect を満たす POST）だけ。ref・記録・ファイルの内容は権限として読まない。
// ここは git を直接動かさない（git は feature-create.ts、記録の読み書きは review-api.ts を通す）。
import type { IncomingHttpHeaders } from "node:http";
import { briefBytes, briefDigest, buildBriefData, parseBrief } from "./brief.ts";
import { createFeature, featureBranchExists, nameProblem } from "./feature-create.ts";
import type { CreateEnv } from "./feature-create.ts";
import { ApiError, prKeyOf } from "./git-view.ts";
import type { Repo } from "./git-view.ts";
import { strictOriginOk } from "./merge-api.ts";
import type { PostResult } from "./merge-api.ts";
import { readBriefRecord, recordBrief } from "./review-api.ts";

export type { CreateEnv };

const OID40 = /^[0-9a-f]{40}$/;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const KEYS = ["kind", "name", "requestId", "expect", "brief"];

const bad = (code: string, message: string): ApiError => new ApiError(400, code, message);

/** 起票の POST の入口の検査。無効・Funnel・Origin の順に断る。通れば null。 */
export function createRequestError(headers: IncomingHttpHeaders, allowCreate: boolean): ApiError | null {
	if (!allowCreate) return new ApiError(403, "create_disabled", "この画面からは起票できません（サーバが起票を許可していません）。");
	if (headers["tailscale-funnel-request"] !== undefined) return new ApiError(403, "forbidden_funnel", "公開（Funnel）経由では起票できません。");
	if (!strictOriginOk(headers.origin, headers.host)) return new ApiError(403, "forbidden_origin", "この Origin は許可されていません。");
	return null;
}

// ---- 停止・排他 ----

let stopping = false;
/** 停止の開始。以後、新しい起票は始めない（実行中のものは server.ts が完了を待つ）。 */
export function stopCreates(): void {
	stopping = true;
}

const gates = new Set<string>();

/** リポジトリ単位の「待たない」排他。取れなければ 409 busy。 */
async function gated<T>(repo: Repo, fn: () => Promise<T>): Promise<T> {
	if (stopping) throw new ApiError(503, "shutting_down", "サーバを停止しています。");
	if (gates.has(repo.repoId)) throw new ApiError(409, "busy", "別の起票の処理が実行中です。しばらくして再試行してください。");
	gates.add(repo.repoId);
	try {
		return await fn();
	} finally {
		gates.delete(repo.repoId);
	}
}

/** 診断ログ（標準エラーに 1 行の JSON）。本文・パスは出さない。 */
function diag(entry: Record<string, unknown>): void {
	try {
		process.stderr.write(`${JSON.stringify({ t: "create", ...entry })}\n`);
	} catch {
		// 出せなくても起票の結果は変えない
	}
}

// ---- 本文の検査 ----

type CreateBody = { name: string; requestId: string; expectTarget: string; brief: ReturnType<typeof parseBrief> };

function parseBody(body: Record<string, unknown>): CreateBody {
	for (const k of Object.keys(body)) if (!KEYS.includes(k)) throw bad("bad_request", "リクエストの形が正しくありません。");
	if (body.kind !== "feature") throw bad("bad_kind", "種類は feature だけです。");
	if (typeof body.name !== "string" || nameProblem(body.name)) throw bad("bad_name", "名前が正しくありません（小文字・数字・. _ - の 64 字まで）。");
	if (typeof body.requestId !== "string" || !UUID.test(body.requestId)) throw bad("bad_request_id", "requestId が正しくありません。");
	const e = body.expect;
	const keys = typeof e === "object" && e !== null && !Array.isArray(e) ? Object.keys(e) : [];
	const target = keys.length === 1 && keys[0] === "target" ? (e as Record<string, unknown>).target : undefined;
	if (typeof target !== "string" || !OID40.test(target)) throw bad("bad_expect", "表示中の版の指定が正しくありません。");
	return { name: body.name, requestId: body.requestId, expectTarget: target, brief: parseBrief(body.brief) };
}

type FeatureOut = {
	feature: {
		branch: string;
		prKey: string;
		id: string;
		base: { branch: string; oid: string };
		worktree: { name: string; rel: string };
		brief: { rev: number; digest: string; bytes: number };
		recorded: boolean;
		replay: boolean;
		warnings: string[];
	};
};

function respond(repo: Repo, name: string, base: string, d: { rev: number; digest: string; bytes: number }, replay: boolean): FeatureOut {
	const branch = `feature/${name}`;
	const prKey = prKeyOf(branch);
	return {
		feature: {
			branch,
			prKey,
			id: `${repo.repoId}/${prKey}`,
			base: { branch: "develop", oid: base },
			worktree: { name, rel: `.tmp/worktrees/${name}` },
			brief: d,
			recorded: true,
			replay,
			warnings: [],
		},
	};
}

// ---- POST /api/repos/<repoId>/features ----

export async function createFeatureRoute(repo: Repo, body: Record<string, unknown>, env: CreateEnv): Promise<PostResult> {
	const input = parseBody(body);
	const branch = `feature/${input.name}`;
	const prKey = prKeyOf(branch);
	const who = { req: input.requestId, repo: repo.repoId, pr: prKey };
	const d = buildBriefData({ requestId: input.requestId, rev: 1, name: input.name, via: "viewer" }, input.brief);
	const info = { rev: 1, digest: briefDigest(d), bytes: briefBytes(d) };
	// 再送: 枝があり、記録の requestId と内容が一致するなら、作らずに同じ結果を返す（応答を取り損ねた再送を救う）
	if (await featureBranchExists(repo.gitDir, input.name)) {
		const rec = await readBriefRecord(repo, prKey);
		if (rec && rec.brief.d.requestId === input.requestId && rec.brief.d.name === input.name && briefDigest(rec.brief.d) === info.digest) {
			diag({ ...who, result: "replay", recorded: true });
			return { status: 200, body: respond(repo, input.name, rec.baseOid, { rev: rec.brief.d.rev, digest: info.digest, bytes: briefBytes(rec.brief.d) }, true) };
		}
	}
	return await gated(repo, async () => {
		try {
			const made = await createFeature({ gitDir: repo.gitDir, name: input.name, expectTarget: input.expectTarget, env }, (baseOid) =>
				recordBrief(repo, branch, "develop", baseOid, d),
			);
			diag({ ...who, result: "ok", recorded: true });
			return { status: 201, body: respond(repo, input.name, made.baseOid, info, false) };
		} catch (e) {
			diag({ ...who, result: e instanceof ApiError ? e.code : "error", recorded: false });
			throw e;
		}
	});
}
