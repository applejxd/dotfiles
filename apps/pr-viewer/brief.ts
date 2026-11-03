// 起票の依頼文（brief）の検査と、表示用の形（段 B1 の S）。契約: .tmp/keep/prv-app/api-contract-create.md。
// 形・字数・制御文字・秘密らしい文字列の検査をここに集める。エラーの文には入力の本文を含めない（検出の種類だけ返す）。
// 保存の形（brief イベント）の検査は harness の review-log.ts が正本。ここはその手前で、利用者へ分かる拒否理由を返す。
import { createHash } from "node:crypto";
import { BRIEF_LIMITS, LIMITS } from "../../home/dot_config/pi/harness/review-log.ts";
import type { BriefEvent } from "../../home/dot_config/pi/harness/review-log.ts";
import { ApiError } from "./git-view.ts";

export type BriefInput = { title: string; goal: string; constraints: string; scope: string[]; acceptance: string };
export type BriefData = BriefEvent["d"];
/** GET …/review に載せる依頼文の形 */
export type BriefView = BriefInput & { rev: number; digest: string; bytes: number; at: string };

const bad = (message = "依頼文の形が正しくありません。"): ApiError => new ApiError(400, "bad_brief", message);
const tooLarge = (): ApiError => new ApiError(400, "brief_too_large", "依頼文が上限（字数・件数・サイズ）を超えています。");

// 制御文字（複数行の欄は \n と \t だけ許す）・双方向制御文字・行区切り文字
const BIDI = "\\u061c\\u200e\\u200f\\u202a-\\u202e\\u2066-\\u2069\\u2028\\u2029";
const BAD_SINGLE = new RegExp(`[\\u0000-\\u001f\\u007f-\\u009f${BIDI}]`);
const BAD_MULTI = new RegExp(`[\\u0000-\\u0008\\u000b-\\u001f\\u007f-\\u009f${BIDI}]`);
const LONE_SURROGATE = /[\ud800-\udbff](?![\udc00-\udfff])|(?<![\ud800-\udbff])[\udc00-\udfff]/;

const cpLen = (s: string): number => [...s].length;

/** 秘密らしい文字列の種類と検出式。値そのものは返さない。 */
const SECRET_PATTERNS: ReadonlyArray<readonly [string, RegExp]> = [
	["private_key", /-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----/],
	["aws_key", /\b(?:AKIA|ASIA)[0-9A-Z]{16}\b/],
	["github_token", /\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{22,})/],
	["slack_token", /\bxox[abprs]-[A-Za-z0-9-]{10,}/],
	["bearer", /\bbearer\s+[A-Za-z0-9._~+/=-]{16,}/i],
	["jwt", /\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}/],
	["url_userinfo", /\b[a-z][a-z0-9+.-]*:\/\/[^/\s:@]+:[^/\s@]+@/i],
	["password", /\b(?:password|passwd|pwd)\s*=\s*[^\s"']{4,}/i],
];

/** 秘密らしい文字列の種類（重複なし）。 */
export function detectSecrets(text: string): string[] {
	return SECRET_PATTERNS.filter(([, re]) => re.test(text)).map(([kind]) => kind);
}

function checkText(v: unknown, multiline: boolean, field: string): string {
	if (typeof v !== "string") throw bad(`${field} は文字列で指定してください。`);
	const s = multiline ? v.replace(/\r\n/g, "\n") : v;
	if ((multiline ? BAD_MULTI : BAD_SINGLE).test(s) || LONE_SURROGATE.test(s)) throw bad(`${field} に使えない文字が含まれています。`);
	return s;
}

function checkScopeItem(s: string): void {
	if (s.trim() === "" || s !== s.trim()) throw bad("担当範囲の各項目は、空・前後の空白なしで指定してください。");
	// リポジトリ内の相対パスの glob だけ（絶対パス・親への参照は断る）
	if (s.startsWith("/") || s.startsWith("\\") || /^[A-Za-z]:/.test(s) || s.split(/[\\/]/).includes("..")) {
		throw bad("担当範囲はリポジトリ内の相対パスで指定してください。");
	}
}

const BRIEF_KEYS = ["title", "goal", "constraints", "scope", "acceptance"];

/** 本文の brief を検査して正規化する（改行は \n にそろえる）。不正なら 400。 */
export function parseBrief(raw: unknown): BriefInput {
	if (typeof raw !== "object" || raw === null || Array.isArray(raw)) throw bad();
	const o = raw as Record<string, unknown>;
	for (const k of Object.keys(o)) if (!BRIEF_KEYS.includes(k)) throw bad();
	const title = checkText(o.title, false, "題名");
	const goal = checkText(o.goal, true, "目的");
	const constraints = o.constraints === undefined ? "" : checkText(o.constraints, true, "守る条件");
	const acceptance = o.acceptance === undefined ? "" : checkText(o.acceptance, true, "完了条件");
	let scope: string[] = [];
	if (o.scope !== undefined) {
		if (!Array.isArray(o.scope)) throw bad("担当範囲は文字列の配列で指定してください。");
		if (o.scope.length > BRIEF_LIMITS.scopeItems * 50) throw tooLarge(); // 巨大な配列は中身を見ずに断る
		scope = o.scope.map((s) => checkText(s, false, "担当範囲"));
	}
	if (title.trim() === "" || goal.trim() === "") throw bad("題名と目的は必須です。");
	// 件数・字数・合計の上限（コードポイント数）
	const L = BRIEF_LIMITS;
	if (scope.length > L.scopeItems || scope.some((s) => cpLen(s) > L.scopeItem)) throw tooLarge();
	for (const s of scope) checkScopeItem(s);
	const total = cpLen(title) + cpLen(goal) + cpLen(constraints) + cpLen(acceptance) + scope.reduce((n, s) => n + cpLen(s), 0);
	if (cpLen(title) > L.title || cpLen(goal) > L.goal || cpLen(constraints) > L.constraints || cpLen(acceptance) > L.acceptance || total > L.total) {
		throw tooLarge();
	}
	const input: BriefInput = { title, goal, constraints, scope, acceptance };
	// 秘密らしい文字列（種類だけ返す）
	const kinds = new Set<string>();
	for (const t of [title, goal, constraints, acceptance, ...scope]) for (const k of detectSecrets(t)) kinds.add(k);
	if (kinds.size > 0) {
		throw new ApiError(400, "secret_like", `秘密らしい文字列が含まれています（種類: ${[...kinds].join(", ")}）。取り除いてください。`);
	}
	return input;
}

/** brief イベントの d を組み立てる。バイト数の上限（15,000）を超えたら 400 brief_too_large。 */
export function buildBriefData(meta: { requestId: string; rev: number; name: string; via: string }, input: BriefInput): BriefData {
	const d: BriefData = {
		requestId: meta.requestId,
		rev: meta.rev,
		kind: "feature",
		name: meta.name,
		title: input.title,
		goal: input.goal,
		constraints: input.constraints,
		scope: input.scope,
		acceptance: input.acceptance,
		via: meta.via,
	};
	if (briefBytes(d) > LIMITS.briefBytes) throw tooLarge();
	return d;
}

/** 依頼文の内容の指紋（名前と 5 つの欄）。 */
export function briefDigest(d: BriefData): string {
	const canon = JSON.stringify([d.name, d.title, d.goal, d.constraints, d.scope, d.acceptance]);
	return createHash("sha256").update(canon).digest("hex");
}

export function briefBytes(d: BriefData): number {
	return Buffer.byteLength(JSON.stringify(d), "utf8");
}

/** 記録された brief イベントの表示用の形。 */
export function briefView(e: BriefEvent): BriefView {
	const d = e.d;
	return {
		rev: d.rev,
		title: d.title,
		goal: d.goal,
		constraints: d.constraints,
		scope: d.scope,
		acceptance: d.acceptance,
		digest: briefDigest(d),
		bytes: briefBytes(d),
		at: e.at,
	};
}
