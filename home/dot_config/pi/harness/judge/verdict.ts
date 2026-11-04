// bash の判定の集約を「段の表」の純関数にしたもの (G2a。旧のカスケードと挙動が同一)。
//
// 入力は、各段の所見 (`Finding`) と「全セグメントが許可に当たったか」だけ。所見の集め方 (旧の個別関数の呼び出し) は
// `legacy_adapter.ts` が持つ。ここは、段の順で最初の所見を採り、その段の出力 (`OUT`) を返すだけで、検査関数を呼ばない。
// 旧のカスケード (judge/legacy_cascade.ts。G7 で削除する oracle) と、全部分集合 × 役割 × モードで一致することを試験で縛る。
//
// node の型除去でそのまま動く書き方だけを使う。
// see docs/spec/guard/pi-decide.md#bash-の評価順段の表
import type { Response } from "./decide.ts";
import { errorResponse, pyRepr, response, toolIn } from "./decide.ts";

/** 段。S0 は解析前の失敗 (共通)、S2 は共通の禁止 (tools 検査より先に返る)。S7b (非 literal の頭) は G3 で足す。 */
export type Stage = "S0" | "S2" | "S3" | "S4" | "S5" | "S6" | "S7" | "S8" | "S9";
export const ORDER: readonly Stage[] = ["S0", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9"];

/** 段の所見。`reason` の意味は段で違う (下の OUT)。S7・S9 だけが役割で出力が変わるので、素の理由を持つ。 */
export type Finding = {
	stage: Stage;
	/** 段の中の順 (DENY_NAMES / ASK_NAMES の位置など)。小さいものが先 */
	idx: number;
	reason: string;
	source: string;
	check?: string;
	/** S3: 誘導の id (無ければ null) */
	guide?: string | null;
	/** S6: 本文を確認できない形 (deny) */
	blind?: true;
	/** S7: 実行しようとしているコマンド (clip200 済み) */
	detail?: string;
	/** G3 の 3 値照合用。出力は yes と同じ */
	match?: "yes" | "maybe";
};

/** 出力が依存する役割の側面 */
export type RoleView = { default: string; tools: string[] };

// 契約: mustConfirm の ask の理由はこの接頭辞で始める (ハーネスの確認 UI が見る。bash.ts と同じ文)
const MUST_CONFIRM_LOCAL_PREFIX = "確認が必要な元に戻せない git 操作 (bypass でも確認する): ";
const DENY_DEFAULT_SUFFIX = "\nこの役割は既定が deny なので、承認で通さない (bypass でも通さない)";

/** 段ごとの出力。理由文・source・mustConfirm・suffix は旧と同一 */
export const OUT: Record<Stage, (f: Finding, role: RoleView) => Response> = {
	S0: (f) => errorResponse(f.reason),
	S2: (f) => response("deny", f.reason, f.source, f.check !== undefined ? { check: f.check } : {}),
	S3: (f) => response("deny", f.reason, "rule", { guide: f.guide ?? null }),
	S4: (f) => response("deny", f.reason, "rule"),
	S5: (f) => response("deny", f.reason, "rule"),
	// blind は deny、それ以外は mustConfirm の ask (既定が deny の役割でも ask のまま)。理由は旧の応答の文そのもの
	S6: (f) => (f.blind ? response("deny", f.reason, "rule") : response("ask", f.reason, "rule", { mustConfirm: true })),
	S7: (f, role) =>
		role.default === "deny"
			? response("deny", `${f.reason}。この役割は shell で元に戻せない操作をしない`, "rule")
			: response("ask", `${MUST_CONFIRM_LOCAL_PREFIX}${f.reason}\n実行しようとしているコマンド: ${f.detail ?? ""}`, "rule", {
					mustConfirm: true,
				}),
	// 理由は旧の応答の文そのもの (接頭辞つき)
	S8: (f) => response("ask", f.reason, f.source, { check: f.check, mustConfirm: true }),
	S9: (f, role) =>
		role.default === "deny"
			? response("deny", `${f.reason}${DENY_DEFAULT_SUFFIX}`, f.source, f.check ? { check: f.check } : {})
			: response("ask", f.reason, f.source, f.check !== undefined ? { check: f.check } : {}),
};

/** 段の所見の入力 */
export type BashInput = {
	F: readonly Finding[];
	/** S10: 全セグメントが許可に当たった、または skillScript に当たった */
	covered: boolean;
	/** S10 の理由 (旧の戻り値の文。source は常に rule) */
	coveredReason?: string;
};

export type StageVerdict = { commonDeny: Response | null; roleRule: Response | null };

/** 段内で採る所見。S6 だけは段全体で事前集約する (blind があればそれ。旧 confirmTable は全セグメントを走査して blind を OR する)。 */
function pick(F: readonly Finding[], stage: Stage): Finding | undefined {
	const found = F.filter((x) => x.stage === stage).sort((a, b) => a.idx - b.idx);
	if (stage === "S6") return found.find((x) => x.blind) ?? found[0];
	return found[0];
}

/**
 * bash の段の表。段の順で最初に所見のある段が決める (次の段は見ない)。S10 は許可、S11 (既定) は `roleRule: null` で返し、
 * `finish` が役割の既定を足す。S0・S2 は共通の禁止 (`commonDeny`。tools 検査より先に返る)。
 */
export function verdictBash(inp: BashInput, role: RoleView): StageVerdict {
	for (const stage of ORDER) {
		const f = pick(inp.F, stage);
		if (!f) continue;
		const r = OUT[stage](f, role);
		return stage === "S0" || stage === "S2" ? { commonDeny: r, roleRule: null } : { commonDeny: null, roleRule: r };
	}
	if (inp.covered) {
		return { commonDeny: null, roleRule: response("allow", inp.coveredReason ?? "全セグメントが許可の一覧にある", "rule") };
	}
	return { commonDeny: null, roleRule: null };
}

export type Tail = {
	tool: string;
	role: string;
	profile: { tools: string[]; default: string };
	boundary?: boolean;
	bypass?: boolean;
};

/**
 * 共通の禁止 → 役割の tools → 規則 / 既定 → boundary → bypass (decide.ts の判定の後半と同じ。全ツール共通)。
 * boundary は bash だけ、既定の ask だけを allow にする。bypass は mustConfirm でない ask だけを allow にする。
 */
export function finish(t: Tail, commonDeny: Response | null, roleRule: Response | null): Response {
	if (commonDeny) return commonDeny;
	if (!toolIn(t.tool, t.profile.tools)) {
		return response("deny", `役割 ${pyRepr(t.role)} は ${t.tool} を使えない`, "rule");
	}
	const result = roleRule ?? response(t.profile.default as "allow" | "ask" | "deny", `どの規則にも当たらない (役割 ${pyRepr(t.role)} の既定)`, "default");
	if (t.boundary && t.tool === "bash" && result.source === "default" && result.decision === "ask") {
		return response("allow", "サンドボックスの内側の日常の shell (どの規則にも当たらない)", "rule", { sandboxed: true });
	}
	if (t.bypass && result.decision === "ask" && !result.mustConfirm) return { ...result, decision: "allow", bypassed: true };
	return result;
}

/** 段の表と `finish` を通した最終の応答 (試験・純関数の入口。本番は decide.ts が finish を呼ぶ) */
export function judgeBash(
	inp: BashInput,
	t: { role: string; profile: { tools: string[]; default: string }; boundary?: boolean; bypass?: boolean },
): Response {
	const v = verdictBash(inp, t.profile);
	return finish({ tool: "bash", ...t }, v.commonDeny, v.roleRule);
}
