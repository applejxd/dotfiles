// 判定器を「ツールの呼び出し」に当てる口 (フルガードが使う)。
//
// ツール名と入力から、判定器の要求を組んで決定を返す。例外は投げず、異常は deny にする。
// - bg_run (拡張 activity): 起動するコマンドを bash と同じ判定に通す
// - bg_log / bg_kill: ジョブの確認と停止だけなので、bash を使える役割には allow
//
// node の型除去でそのまま動く書き方だけを使う。
// see docs/spec/guard/pi-decide.md, docs/spec/guard/pi-guard.md
import type { Tables } from "./context.ts";
import { decide as judge, setBashDecider } from "./decide.ts";
import { makeBashDecider } from "./bash.ts";
import type { Common } from "./policy.ts";
import { pyRegex } from "./pystr.ts";
import type { GateResult } from "./gitflow_gate.ts";

export type Decision = {
	decision: "allow" | "ask" | "deny";
	reason: string;
	source: string;
	/** "ask" のときだけ真になりうる。bypass でも必ず確認する */
	mustConfirm?: boolean;
	/** gitflow 規約の確認 (CHG-0049) で承認した状態の識別子。execute() で取り直したものと違う承認は使わない */
	gateKey?: string;
};

/**
 * 規約の強制 (gitflow_gate) の結果を、基本の判定に重ねる。緩めない: base の deny はそのまま、規約の deny は常に勝つ。
 * confirm (状態を読めなかった) は bypass でも出す確認 (mustConfirm) にする。
 */
export function tighten(base: Decision, g: GateResult): Decision {
	if (g.kind === "pass" || base.decision === "deny") return base;
	if (g.kind === "deny") return { decision: "deny", reason: g.reason, source: "gitflow-gate" };
	return { decision: "ask", reason: g.reason, source: "gitflow-gate", mustConfirm: true, gateKey: g.key };
}

export const BG_RUN = "bg_run";
const BG_OTHERS = ["bg_log", "bg_kill"];

export type CallDeciderOptions = {
	judge: { common: Common; tables: Tables };
	/** 役割ごとに登録するツール (rules.json の profile_tools) */
	profileTools: Record<string, string[]>;
	/** 役割。関数なら呼び出しごとに評価する (起動後に orchestrator へ切り替えるため) */
	role: string | (() => string);
	/** true なら ask を allow にする (deny と誘導は効く)。関数なら呼び出しごとに評価する (起動後に切り替えるため) */
	bypass: boolean | (() => boolean);
	/** サンドボックスの内側と証明できているか (緩和が効く)。env の自己申告ではなく、カナリアの結果を渡す */
	boundary: boolean;
	/** サンドボックスが開けた場所。boundary のときの、作業ツリーの外の判定に使う */
	allowed?: { read: string[]; write: string[] };
	/** gitflow 規約の強制 (CHG-0049)。基本の判定が deny でないときだけ呼ぶ。例外は呼び出し側で捨てず、調べられないときは確認にする */
	restrict?: (tool: string, input: unknown, cwd: string) => GateResult;
};

export function createCallDecider(o: CallDeciderOptions): (tool: string, input: unknown, cwd: string) => Decision {
	// 判定器は呼び出しごとに文脈を作り直す。ここで持つのは読み込んだ設定だけ
	setBashDecider(makeBashDecider(o.judge.tables));
	// scope = "foreground" の誘導は、bash (guarded_bash) だけに当てる。bg_run の中身 (待つコマンドそのもの) には当てない
	const foreground = (((o.judge.common as any)?.pi?.guide as any[] | undefined) ?? []).filter((g) => g?.scope === "foreground");
	return (tool, input, cwd) => {
		const role = typeof o.role === "function" ? o.role() : o.role;
		if (tool === "bash" && foreground.length > 0) {
			const command = String((input as any)?.command ?? "");
			for (const g of foreground) {
				if (pyRegex(g.pattern).test(command) && !(g.unless && pyRegex(g.unless).test(command))) {
					return { decision: "deny", reason: g.message, source: "rule" };
				}
			}
		}
		if (BG_OTHERS.includes(tool)) {
			if ((o.profileTools[role] ?? []).includes("bash")) {
				return { decision: "allow", reason: "ジョブの確認と停止だけ (bash を使える役割)", source: "rule" };
			}
			return { decision: "deny", reason: `役割 ${JSON.stringify(role)} は ${tool} を使えない`, source: "rule" };
		}
		const asBash = tool === BG_RUN;
		const request = {
			tool: asBash ? "bash" : tool,
			input: asBash ? { command: (input as any)?.command } : input,
			cwd,
			role,
			bypass: typeof o.bypass === "function" ? o.bypass() : o.bypass,
			boundary: o.boundary,
			...(o.boundary && o.allowed ? { allowed: o.allowed } : {}),
		};
		// judge() は例外を投げず、異常は source: error の deny にする。念のため形も確かめる
		try {
			const out = judge(request, o.judge.common) as Decision;
			if (["allow", "ask", "deny"].includes(out?.decision) && typeof out?.reason === "string") {
				return out.decision === "deny" || !o.restrict ? out : tighten(out, o.restrict(tool, input, cwd));
			}
			return { decision: "deny", reason: `判定器の応答が不正: ${JSON.stringify(out).slice(0, 120)}`, source: "error" };
		} catch (e) {
			// 形の正しい応答以外は deny (空の応答を allow と読まない)
			return { decision: "deny", reason: `判定器が失敗した: ${(e as Error).message}`, source: "error" };
		}
	};
}
