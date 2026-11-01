// 保留 (非同期承認) に対応する操作のアダプタの登録表 (CHG-0055)。今は空。操作ごとの feature (git_integrate など) が、ここに足す。
// 要求の側 (PENDING_ADAPTERS: 前提の取得) と、承認の側 (APPROVAL_ADAPTERS: 計画・再検査・実行) は別の型。
// 登録のない操作は、「あとで」も出さず従来どおり。
// integrateWiring は git_integrate の配線を作る純粋な関数 (index.ts が呼ぶ)。登録表そのものは空のまま。
import { ACTION_TOOL, validateCall, type ActionSpec, type PendingAdapter } from "./actions.ts";
import { freeZoneSettings } from "./freezone.ts";
import { GIT_INTEGRATE_SPEC, integrateApprovalAdapter, integrateRequestAdapter, type IntegrateCfg } from "./integrate-action.ts";
import type { ApprovalAdapter } from "./pending-approve.ts";
import type { OpRecord } from "./pending-ops.ts";

export const PENDING_ADAPTERS: Record<string, PendingAdapter> = {};
export const APPROVAL_ADAPTERS: Record<string, ApprovalAdapter> = {};

const REF_NAME = /^[A-Za-z0-9][A-Za-z0-9._\/-]*$/;
const MAX_RISK_PATHS = 200;
const MAX_RISK_PATH_CHARS = 200;

/** 設定の今の値 (呼ぶたびに rules を読む)。不正な値は既定に倒す */
export function integrateCfg(rules: any): IntegrateCfg {
	const integrate = rules?.judge?.common?.pi?.integrate;
	const t = integrate?.target;
	const risk = Array.isArray(integrate?.risk_paths) ? (integrate.risk_paths as unknown[]) : [];
	return {
		target: typeof t === "string" && REF_NAME.test(t) ? t : "develop",
		protectedRefs: freeZoneSettings(rules).protectedRefs,
		riskPaths: risk.filter((p): p is string => typeof p === "string").slice(0, MAX_RISK_PATHS).map((p) => p.slice(0, MAX_RISK_PATH_CHARS)),
		enabled: () => switchesOn(rules),
	};
}

/** `[pi.pending] enabled` と `[pi.integrate] enabled` の両方が true のときだけ true */
function switchesOn(rules: any): boolean {
	const pi = rules?.judge?.common?.pi;
	return pi?.pending?.enabled === true && pi?.integrate?.enabled === true;
}

export type IntegrateWiring = {
	enabled: boolean;
	specs: ActionSpec[];
	request: Record<string, PendingAdapter>;
	approval: Record<string, ApprovalAdapter>;
};

export function integrateWiring(rules: any): IntegrateWiring {
	if (!switchesOn(rules)) return { enabled: false, specs: [], request: {}, approval: {} };
	const cfg = () => integrateCfg(rules);
	return {
		enabled: true,
		specs: [GIT_INTEGRATE_SPEC],
		request: { git_integrate: integrateRequestAdapter(cfg) },
		approval: { git_integrate: integrateApprovalAdapter(cfg) },
	};
}

export type AuthorizeCtx = { specs: readonly ActionSpec[]; roleTools: readonly string[]; child: boolean };

/** 記録の自由な文 (未知のキー名など) を理由に載せない。1 行・制御文字なし・200 字まで */
function safeReason(error: string, params: unknown, spec: ActionSpec): string {
	let text = error;
	if (params !== null && typeof params === "object") {
		for (const key of Object.keys(params)) {
			if (!(key in spec.fields)) text = text.split(`params.${key}:`).join("params.?:");
		}
	}
	return text.replace(/[\u0000-\u001f\u007f\u2028\u2029]+/g, " ").slice(0, 200);
}

/** 承認側の再判定。保留の記録は信頼しない入力で、いまの役割・操作の定義で許されるときだけ ok。迷ったら断る */
export function authorizeRecord(
	rec: Pick<OpRecord, "action" | "params">,
	ctx: AuthorizeCtx,
): { ok: true } | { ok: false; reason: string } {
	if (ctx.child) return { ok: false, reason: "子エージェントは保留の操作を承認できない" };
	if (!ctx.roleTools.includes(ACTION_TOOL)) return { ok: false, reason: `この役割は ${ACTION_TOOL} ツールを持たない` };
	const spec = ctx.specs.find((s) => s.id === rec?.action);
	if (!spec) return { ok: false, reason: "この操作はいま登録されていない (無効か、設定が変わった)" };
	const v = validateCall(ctx.specs as ActionSpec[], { action: rec.action, params: rec.params });
	if (!v.ok) return { ok: false, reason: `引数が操作の定義に合わない: ${safeReason(v.error, rec.params, spec)}` };
	return { ok: true };
}
