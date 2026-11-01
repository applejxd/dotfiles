// 要求側の保存 (CHG-0055 の P8c)。前提を取って、保留 (refs/pi/pending/) に保存するだけで、実行しない。
// 承認・実行側 (pending-approve・integrate-exec・exclusive-lock・integrate-action) は import しない (試験で固定)。
import { randomUUID } from "node:crypto";
import type { PendingAdapter } from "./actions.ts";
import { saveOp, type Json, type Limits, type Reason, type SaveInput, type SaveResult } from "./pending-ops.ts";

export type RequestInput = { action: string; cwd: string; sessionId: string; values: Record<string, string> };
export type RequestDeps = {
	adapters: Record<string, PendingAdapter>;
	enabled: boolean;
	modes: readonly string[];
	mode: string;
	child: boolean;
	save?: typeof saveOp;
	limits?: Limits;
	env: NodeJS.ProcessEnv;
	signal?: AbortSignal;
};
export type RequestResult =
	| { ok: true; id: string; ref: string; duplicate: boolean; action: string }
	| { ok: false; code: "child" | "disabled" | "mode" | "unsupported" | "premise" | "save_failed" | "aborted"; reason: string };

type Captured = { premise: Record<string, Json>; worktree?: string; host?: string };

/** 取った前提から SaveInput を組んで保存する。repoCwd = 保存先のリポジトリ、requestCwd = 要求した cwd */
export function saveRequest(a: {
	action: string;
	values: Record<string, string>;
	captured: Captured;
	reason: Reason;
	sessionId: string;
	repoCwd: string;
	requestCwd: string;
	save?: typeof saveOp;
	limits?: Limits;
}): SaveResult {
	const input: SaveInput = {
		action: a.action,
		params: { ...a.values },
		premise: a.captured.premise,
		reason: a.reason,
		request: { id: randomUUID(), sessionId: a.sessionId, cwd: a.requestCwd },
		createdAt: new Date().toISOString(),
		...(a.captured.worktree ? { worktree: a.captured.worktree } : {}),
		...(a.captured.host ? { host: a.captured.host } : {}),
	};
	return (a.save ?? saveOp)(a.repoCwd, input, a.limits);
}

export async function requestApproval(i: RequestInput, d: RequestDeps): Promise<RequestResult> {
	if (d.child) return { ok: false, code: "child", reason: "子エージェントは要求できない" };
	if (!d.enabled) return { ok: false, code: "disabled", reason: "保留が無効" };
	if (!d.modes.includes(d.mode)) return { ok: false, code: "mode", reason: `今のモード (${d.mode}) は保留の対象外` };
	const adapter = d.adapters[i.action];
	if (!adapter) return { ok: false, code: "unsupported", reason: `${i.action} は保留に対応していない` };
	if (d.signal?.aborted) return { ok: false, code: "aborted", reason: "中断された" };
	const cap = await adapter.capture({ cwd: i.cwd, values: i.values, env: d.env }).catch((e: unknown) => ({ ok: false as const, reason: String((e as Error)?.message ?? e) }));
	if (!cap.ok) return { ok: false, code: "premise", reason: cap.reason };
	const saved = saveRequest({
		action: i.action,
		values: i.values,
		captured: cap,
		reason: "request",
		sessionId: i.sessionId,
		repoCwd: i.cwd,
		requestCwd: i.cwd,
		save: d.save,
		limits: d.limits,
	});
	if (!saved.ok) return { ok: false, code: "save_failed", reason: saved.reason };
	return { ok: true, id: saved.id, ref: saved.ref, duplicate: saved.duplicate, action: i.action };
}
