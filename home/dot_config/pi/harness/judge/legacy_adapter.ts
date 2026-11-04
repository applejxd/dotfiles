// 旧の個別の検査関数を、段の所見 (`Finding`) に包むアダプタ (G2a。G7 で段ごとの新実装に置き換えて削除する)。
//
// 旧の関数 (`bash.ts` の `bashCommonDeny`・`guide`・`confirmTable`・`bashAsk`・`allSegmentsAllowed`・`skillScriptAllowed` など) の
// 内部のロジックは変えず、呼んで結果を所見に写すだけ。評価は旧と同じ順で、所見のある最初の段で止める
// (後ろの段を評価すると、旧が到達しなかった検査が例外を投げうる・遅くなるため。段の表は先頭の段しか使わない)。
//
// node の型除去でそのまま動く書き方だけを使う。
// see docs/spec/guard/pi-decide.md#bash-の評価順段の表
import { actionDenyReason } from "./actions.ts";
import { ASK_NAMES, DENY_NAMES, PATH_NAMES } from "./checks.ts";
import type { Ctx } from "./context.ts";
import { findMatch } from "./normalize.ts";
import { clip200 } from "./shared.ts";
import { localGitDestructiveReason } from "./gitdestructive.ts";
import { allSegmentsAllowed, bashAsk, bashCommonDeny, confirmTable, guide, RESTORE_DENY, skillScriptAllowed } from "./bash.ts";
import type { BashInput, Finding } from "./verdict.ts";

type Obj = Record<string, any>;

/** S2 の段内の位置: DENY_NAMES の位置、PATH_NAMES (cdVariant) はその後ろ */
function commonDenyIdx(check: string | undefined): number {
	if (check === undefined) return 0;
	const d = DENY_NAMES.indexOf(check);
	if (d >= 0) return d;
	const p = PATH_NAMES.indexOf(check);
	return DENY_NAMES.length + (p >= 0 ? p : 0);
}

/**
 * 旧のカスケードの S2〜S10 を、所見に写す。`denyCtx` は例外 (S1) で deny を外した文脈、`ctx` はそれ以外の検査の文脈。
 * `restoreOk` は `git restore --staged` の例外 (役割の shell_deny の「git restore」も外す)。
 */
export function collectLegacyFindings(a: { ctx: Ctx; denyCtx: Ctx; cmd: string; pi: Obj; profile: Obj; restoreOk: boolean }): BashInput {
	const { ctx, denyCtx, cmd, pi, profile, restoreOk } = a;
	const stop = (f: Finding): BashInput => ({ F: [f], covered: false });

	// S2: 共通の禁止 (DENY_NAMES の順 → cdVariant の PATH_NAMES)
	const deny = bashCommonDeny(denyCtx, cmd);
	if (deny) {
		const check = deny.check as string | undefined;
		return stop({ stage: "S2", idx: commonDenyIdx(check), reason: deny.reason, source: deny.source, ...(check !== undefined ? { check } : {}) });
	}
	// S3: 誘導
	const g = guide(cmd, pi);
	if (g) return stop({ stage: "S3", idx: 0, reason: g.reason, source: g.source, guide: (g.guide as string | null | undefined) ?? null });
	// S4: action ツールを持つ役割の操作表
	if (Array.isArray(profile.tools) && profile.tools.includes("action")) {
		const reason = actionDenyReason(cmd, pi);
		if (reason !== null) return stop({ stage: "S4", idx: 0, reason, source: "rule" });
	}
	// S5: 役割の shell_deny
	const roleDenyList = ((profile.shell_deny as unknown[] | undefined) ?? []).map(String).filter((p) => !(restoreOk && p === RESTORE_DENY));
	const roleDeny = findMatch(cmd, roleDenyList);
	if (roleDeny) return stop({ stage: "S5", idx: 0, reason: `\`${roleDeny}\` はこの役割の shell_deny にある`, source: "rule" });
	// S6: [pi.confirm] bash。blind (本文を確認できない形) は deny、それ以外は必須確認。段全体で集約済みの 1 件
	const confirm = confirmTable(cmd, pi);
	if (confirm) {
		return stop({ stage: "S6", idx: 0, reason: confirm.reason, source: confirm.source, ...(confirm.decision === "deny" ? { blind: true as const } : {}) });
	}
	// S7: [pi.confirm] local_git。役割で出力が変わるので、素の理由 (検出器の戻り値) を持つ
	if (pi.confirm?.local_git === true) {
		const reason = localGitDestructiveReason(cmd);
		if (reason !== null) return stop({ stage: "S7", idx: 0, reason, source: "rule", detail: clip200(cmd) });
	}
	// S8 / S9: bashAsk は [pi.confirm] checks (必須確認) を先に引き、次に ASK_NAMES の順。必須確認の ask が S8、それ以外が S9
	const ask = bashAsk(ctx, cmd, pi);
	if (ask) {
		const check = ask.check as string | undefined;
		const idx = check === undefined ? 0 : Math.max(0, ASK_NAMES.indexOf(check));
		return stop({
			stage: ask.mustConfirm ? "S8" : "S9",
			idx,
			reason: ask.reason,
			source: ask.source,
			...(check !== undefined ? { check } : {}),
		});
	}
	// S10: 全セグメントが許可 (先)、skillScript (後)。どちらも source は rule
	const own = profile.shell_allow;
	const allowList: unknown[] = own != null ? own : (pi.shell?.allow ?? []);
	const where = own != null ? "役割の shell_allow" : "[pi.shell] allow";
	const matched = allSegmentsAllowed(cmd, allowList.map(String));
	if (matched) return { F: [], covered: true, coveredReason: `\`${matched}\` は ${where} にある` };
	const script = skillScriptAllowed(cmd, pi);
	if (script) return { F: [], covered: true, coveredReason: `\`${script}\` は [pi.skill_scripts] にある` };
	return { F: [], covered: false };
}
