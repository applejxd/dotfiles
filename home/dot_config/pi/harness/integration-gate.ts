// 保護ブランチへの統合の確認 (`[pi.confirm] integration`)。判定器の結果を、必要なら必須確認 (bypass でも省略不可) に引き上げる。
//
// 緩める方向の処理は無い: deny はそのまま、すでに必須確認のものもそのまま、それ以外を引き上げるだけ。
// bash の統合コマンドは、judge/gitintegration.ts が静的に分類する。
//   always / unknown  常に必須確認 (保護 ref を直接変える・対象が静的に決まらない)
//   head              現在のブランチを動かす (merge・cherry-pick・pull・am・reset など)。cwd が自由区 (feature の linked worktree)
//                     なら日常の操作なので判定器の結果のまま。自由区でない・判定できないときは必須確認 (deny にしない)
// git を起動するのは head のときだけ (毎回の edit / write や通常の bash では起動しない)。
// 保証の範囲は「ガードが識別する直接経路」(alias・外部スクリプト・別のプロセスの中の ref の書き込みは見ない)。
// see docs/change/0053-worktree-integration-gate.md
import { MUST_CONFIRM_INTEGRATION_PREFIX } from "./confirm-view.ts";
import { classifyFreeZone, DEFAULT_PROTECTED, type FreeZone } from "./freezone.ts";
import { classifyIntegration } from "./judge/gitintegration.ts";
import { clip200 } from "./judge/shared.ts";

type Decision = { decision: "allow" | "ask" | "deny"; reason: string; source: string; mustConfirm?: boolean };

export type IntegrationConfig = { enabled: boolean; protectedRefs: readonly string[] };

const SHELL_TOOLS = new Set(["bash", "bg_run"]);

/** rules.json の judge.common から設定を読む。`[pi.confirm] integration` が真のときだけ有効。保護 ref は `[pi.integrate] protected_refs` */
export function integrationConfig(common: any): IntegrationConfig {
	const pi = common?.pi ?? {};
	const refs = pi.integrate?.protected_refs;
	const list = Array.isArray(refs) && refs.every((r: unknown) => typeof r === "string") && refs.length > 0 ? (refs as string[]) : DEFAULT_PROTECTED;
	return { enabled: pi.confirm?.integration === true, protectedRefs: list };
}

export function tightenIntegration(
	d: Decision,
	tool: string,
	input: unknown,
	cwd: string,
	cfg: IntegrationConfig,
	deps: { classify?: (cwd: string, refs: readonly string[]) => FreeZone } = {},
): Decision {
	if (!cfg.enabled || !SHELL_TOOLS.has(tool)) return d;
	if (d.decision === "deny" || (d.decision === "ask" && d.mustConfirm === true)) return d;
	const command = String((input as any)?.command ?? "");
	const r = classifyIntegration(command, cfg.protectedRefs);
	if (r.kind === "none") return d;
	let why = r.reason;
	if (r.kind === "head") {
		const fz = (deps.classify ?? ((c, refs) => classifyFreeZone(c, refs)))(cwd, cfg.protectedRefs);
		if (fz.free) return d;
		why = `${r.reason}。feature の linked worktree の中ではない (${fz.reason})`;
	}
	return {
		decision: "ask",
		mustConfirm: true,
		source: "rule",
		reason: `${MUST_CONFIRM_INTEGRATION_PREFIX}${why}\n実行しようとしているコマンド: ${clip200(command)}`,
	};
}
