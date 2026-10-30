// /gitflow-allow (利用者専用の逃がし口。CHG-0049) の引数の解釈と表示。純粋な関数だけ。
// モデルが呼べるツールは作らない。許可の保持と付与は index.ts (メモリだけ。セッションにも残さない)。
// see docs/spec/guard/pi-gitflow-guard.md
import type { Allowance } from "./judge/gitflow_gate.ts";

export const DEFAULT_MINUTES = 10;
export const MAX_MINUTES = 60;
export const USAGE = "/gitflow-allow [edit|commit|all] [分] | off | status";

export type AllowArgs =
	| { ok: true; action: "grant"; scope: Allowance["scope"]; minutes: number }
	| { ok: true; action: "off" | "status" }
	| { ok: false; error: string };

const SCOPES = ["edit", "commit", "all"];

/** `[edit|commit|all] [分]` か、`off` / `status`。範囲の既定は all、時間の既定は 10 分、上限は 60 分 (超えたら丸めず拒否する) */
export function parseAllowArgs(text: string): AllowArgs {
	const tokens = String(text ?? "").trim().split(/\s+/).filter(Boolean);
	if (tokens.length === 1 && (tokens[0] === "off" || tokens[0] === "status")) return { ok: true, action: tokens[0] };
	let scope: Allowance["scope"] | undefined;
	let minutes: number | undefined;
	for (const t of tokens) {
		if (SCOPES.includes(t)) {
			if (scope) return { ok: false, error: `範囲を 2 回指定している: ${USAGE}` };
			scope = t as Allowance["scope"];
		} else if (/^[0-9]+$/.test(t)) {
			if (minutes !== undefined) return { ok: false, error: `時間を 2 回指定している: ${USAGE}` };
			const n = Number(t);
			if (n < 1) return { ok: false, error: `時間は 1 分以上: ${USAGE}` };
			if (n > MAX_MINUTES) return { ok: false, error: `時間は ${MAX_MINUTES} 分まで: ${USAGE}` };
			minutes = n;
		} else {
			return { ok: false, error: `使い方: ${USAGE}` };
		}
	}
	return { ok: true, action: "grant", scope: scope ?? "all", minutes: minutes ?? DEFAULT_MINUTES };
}

const SCOPE_TEXT: Record<Allowance["scope"], string> = {
	edit: "直接の編集 (edit / write)",
	commit: "コミット (guarded_action の git_commit)",
	all: "直接の編集とコミット",
};

export function scopeText(scope: Allowance["scope"]): string {
	return SCOPE_TEXT[scope];
}

/** 残り時間つきの 1 行。期限を過ぎていれば null */
export function describeAllowance(a: Allowance | null, now: number): string | null {
	if (!a || now >= a.expires) return null;
	const left = Math.max(1, Math.ceil((a.expires - now) / 60000));
	return `${a.top} の ${a.head}: ${scopeText(a.scope)} (あと約 ${left} 分)`;
}
