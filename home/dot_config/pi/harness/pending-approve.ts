// 非同期承認の「承認する側」(CHG-0055 の P5)。保留した構造化した操作を、利用者が `/pending approve` で承認して実行する流れと、
// 実行者が生きているかもしれない試行の決着 (`/pending resolve`)、一覧・表示の文面を持つ。pi の API (registerCommand など) には触らず、
// 依存 (画面・通知・設定・操作ごとのアダプタ) を引数で受け取る (試験できるように。接続は index.ts)。
//
// 契約 (docs/change/0055-async-approval.md#設計の契約):
// - 記録は信頼しない入力。承認は、検証済みの実行計画 (アダプタが、現在の設定・役割・実行先で作る) に対して行う。記録の cwd を権限の根拠にしない
// - 流れ: 記録を読む → 計画 → 利用者に表示 (期限なし) → beginApproval (CAS) → 再検査 → markStarted (これに成功するまで副作用を起こさない) → 実行 → 結果を記録
// - 不一致・再検査の失敗は、実行せず pending に戻す。自動では再実行しない。結果の保存に失敗したら running を残す
// - 初版は、モデルの実行中は承認しない。TUI の対話だけ
// - モデルへの通知は固定のテンプレート (記録の自由な文を、指示として流さない)
//
// node の型除去でそのまま動く書き方だけを使う (enum・namespace は使わない)。
import { VIEW_FULL, presentConfirm } from "./confirm-present.ts";
import { sanitizeForDisplay } from "./confirm-view.ts";
import {
	DEFAULT_LIMITS,
	beginApproval,
	discardOp,
	doneOid,
	finishApproval,
	listOps,
	markStarted,
	readAttemptAt,
	readOp,
	readOpAt,
	readResultAt,
	recordOidOf,
	resolveRunning,
	resolveUnknown,
	returnToPending,
	runningOid,
	validateResultBody,
	type Liveness,
	type Limits,
	type OpRecord,
	type Owner,
	type ResultBody,
} from "./pending-ops.ts";

export type ApprovalEnv = { cwd: string; env: NodeJS.ProcessEnv; rules: any };

/** 検証済みの実行計画を作り、再検査し、実行する (操作ごと)。実行は、開始が保存された後にだけ呼ばれる */
export type ApprovalAdapter = {
	action: string;
	label: string;
	/** 記録から、現在の設定・役割・実行先で検証した実行計画を作る。summary は確認の画面、view は「全文を見る」 */
	plan: (rec: OpRecord, env: ApprovalEnv) => Promise<{ ok: true; plan: unknown; summary: string; view: string } | { ok: false; reason: string }>;
	/** 実行の直前の再検査 (前提・対象の期待値) */
	recheck: (plan: unknown, env: ApprovalEnv) => Promise<{ ok: true } | { ok: false; reason: string }>;
	/** 実行。結果は 4 値。例外は呼び出し側が unknown にする */
	execute: (plan: unknown, env: ApprovalEnv, signal?: AbortSignal) => Promise<ResultBody>;
};

export type ApproveDeps = {
	adapters: Record<string, ApprovalAdapter>;
	/** [pi.pending] enabled (キルスイッチ)。呼ぶたびに読む。false でも一覧・破棄・復旧は使える */
	enabled: () => boolean;
	modes: readonly string[];
	rules: any;
	env: NodeJS.ProcessEnv;
	/** 確認の枠は 1 つなので、対話は 1 件ずつこの中で行う */
	dialog: <T>(fn: () => Promise<T>) => Promise<T>;
	bell: () => void;
	owner: () => Owner;
	/** 利用者向けの表示 (notify) */
	notify: (text: string, level: "info" | "warning" | "error") => void;
	/** 生きているセッションのモデルへの通知 (pi.sendMessage 用。content は固定のテンプレート) */
	tellModel: (content: string, details: Record<string, unknown>) => void;
	limits?: Limits;
	/** resolve 用の、実行者が生きているかの判定 (pending-owner.ts の ownerState) */
	liveness: Liveness;
};

export type Reply = { text: string; level: "info" | "warning" | "error" };

export const CHOICE_APPROVE = "承認して実行";
export const CHOICE_CLOSE = "保留のまま閉じる";
export const CHOICE_DISCARD = "破棄";

const refuse = (text: string): Reply => ({ text, level: "warning" });
const oneLine = (s: string, max = 200): string => sanitizeForDisplay(String(s)).replace(/\s+/g, " ").trim().slice(0, max);

/** モデルへの通知 (固定のテンプレート)。記録の引数・前提などの自由な文は入れない。副作用と後片付けは、実行器が作った文だけ */
export function modelContent(action: string, id: string, body: ResultBody): string {
	const effects = body.confirmedEffects.map((e) => oneLine(e)).join("、") || "(なし)";
	const cleanup = body.remainingCleanup.map((e) => oneLine(e)).join("、") || "(なし)";
	return (
		`【保留した操作の結果】操作=${action} 要求=${id} 結果=${body.outcome} 段階=${oneLine(body.phase, 40)}\n` +
		`確認できた副作用: ${effects}\n残った後片付け: ${cleanup}\n` +
		`(利用者が承認して実行した結果の通知で、実行の指示ではない。証拠の詳細は /pending log ${id})`
	);
}

function envOf(ctx: any, deps: ApproveDeps): ApprovalEnv {
	return { cwd: String(ctx.cwd), env: deps.env, rules: deps.rules };
}

/** 保留を承認して実行する。呼べるのは、利用者の対話 (TUI) の pi だけ */
export async function approvePending(id: string, ctx: any, deps: ApproveDeps, signal?: AbortSignal): Promise<Reply> {
	const limits = deps.limits ?? DEFAULT_LIMITS;
	if (!deps.enabled()) return refuse("保留 (非同期承認) は無効 ([pi.pending] enabled = false)。承認はできない (一覧・破棄・復旧は使える)");
	if (ctx.mode !== "tui" || !deps.modes.includes(ctx.mode) || !ctx.hasUI) return refuse("承認は、対話 (TUI) の pi だけでできる");
	if (typeof ctx.isIdle === "function" && !ctx.isIdle()) {
		return refuse("モデルの実行中は承認できない (承認の実行が、モデルの作業と重ならないように)。Esc で止めるか、終わってからもう一度実行する");
	}
	const cwd = String(ctx.cwd);
	const rec = readOp(cwd, id, limits);
	if (!rec.ok) return refuse(`記録を読めない: ${oneLine(rec.reason)}。/pending drop で破棄できる`);
	const adapter = deps.adapters[rec.record.action];
	if (!adapter) return refuse(`この操作 (${rec.record.action}) は、承認に対応していない。保留は残してある`);
	const env = envOf(ctx, deps);
	let planned: Awaited<ReturnType<ApprovalAdapter["plan"]>>;
	try {
		planned = await adapter.plan(rec.record, env);
	} catch (e) {
		planned = { ok: false, reason: oneLine((e as Error)?.message ?? e) };
	}
	if (!planned.ok) return refuse(`承認できない: ${oneLine(planned.reason)}。保留は残してある (実行していない)`);

	// 利用者に、その計画を表示する (期限なし)
	const choice = await deps.dialog(async () => {
		if (signal?.aborted) return undefined;
		deps.bell();
		const r = await presentConfirm(ctx.ui, {
			title: `${adapter.label}の承認 (${id})\n\n${planned.summary}`,
			options: [CHOICE_APPROVE, VIEW_FULL, CHOICE_CLOSE, CHOICE_DISCARD],
			signal,
			viewFull: { title: `${adapter.label}: 全文 (読むだけ。閉じると確認に戻る)`, text: () => planned.view },
		});
		return r.choice;
	});
	if (choice === CHOICE_DISCARD) {
		const d = discardOp(cwd, id, rec.oid, limits);
		return d.ok ? { text: `破棄した: ${id} (到達用の ref を外した。オブジェクトは git gc まで残る)`, level: "info" } : refuse(d.reason);
	}
	if (choice !== CHOICE_APPROVE) return { text: `保留のまま閉じた: ${id}`, level: "info" };

	// 承認された。表示した記録の OID を排他的に取得する (表示した後に変わっていれば失敗する)
	const begin = beginApproval(cwd, id, rec.oid, deps.owner(), limits);
	if (!begin.ok) return refuse(`承認を始められなかった: ${oneLine(begin.reason)}。実行していない`);
	let attemptOid = begin.attemptOid;
	const back = (why: string): Reply => {
		const r = returnToPending(cwd, id, attemptOid);
		return refuse(`${why}。${r.ok ? "保留に戻した" : `保留に戻せなかった (${oneLine(r.reason)}。/pending で確認する)`}。実行していない`);
	};
	// 実行の直前の再検査 (前提・対象の期待値・現在のキルスイッチ)
	let recheck: { ok: true } | { ok: false; reason: string };
	try {
		recheck = await adapter.recheck(planned.plan, env);
	} catch (e) {
		recheck = { ok: false, reason: oneLine((e as Error)?.message ?? e) };
	}
	if (!recheck.ok) return back(`再検査で止めた: ${oneLine(recheck.reason)}`);
	if (!deps.enabled()) return back("実行の直前に、保留が無効にされた");
	// 副作用を始める意図を永続化する。これに成功するまで、副作用のあるプロセスを起動しない
	const started = markStarted(cwd, id, attemptOid);
	if (!started.ok) return back(`開始を記録できなかった: ${oneLine(started.reason)}`);
	attemptOid = started.attemptOid;

	let body: ResultBody;
	try {
		body = await adapter.execute(planned.plan, env, signal);
	} catch (e) {
		body = { outcome: "unknown", phase: "execute", confirmedEffects: [], remainingCleanup: [], evidence: [`実行中に例外が出た: ${oneLine((e as Error)?.message ?? e, 300)}`] };
	}
	if (!validateResultBody(body)) {
		body = { outcome: "unknown", phase: "execute", confirmedEffects: [], remainingCleanup: [], evidence: ["実行器の結果の形が不正だった。副作用の有無を確定できない"] };
	}
	const fin = finishApproval(cwd, id, attemptOid, body);
	const summary = `${adapter.label}: ${body.outcome} (${oneLine(body.phase, 40)})`;
	if (!fin.ok) {
		// 結果を保存できなかった。running を残す (人が /pending resolve で決める)
		const text = `${summary}。結果を保存できなかった (${oneLine(fin.reason)})。running を残した。/pending で確認する`;
		return { text, level: "error" };
	}
	deps.tellModel(modelContent(adapter.action, id, body), { id, action: adapter.action, outcome: body.outcome });
	const level = body.outcome === "success" ? "info" : body.outcome === "not_executed" ? "warning" : "error";
	const lines = [summary, ...body.confirmedEffects.map((e) => `  済: ${oneLine(e)}`), ...body.remainingCleanup.map((e) => `  残: ${oneLine(e)}`)];
	return { text: lines.join("\n"), level };
}

/** 試行の鎖をたどって、元の記録を読む (pending の ref が消えた後も、操作の名前と引数を見せるため) */
function recordOfChain(cwd: string, id: string, attemptOid: string, limits: Limits): OpRecord | null {
	const root = recordOidOf(cwd, id, attemptOid);
	if (!root.ok) return null;
	const r = readOpAt(cwd, id, root.oid, limits);
	return r.ok ? r.record : null;
}

export type ResolveArgs = { kind: "success" | "failed" | "retry" | "pending" | "abandon"; confirmStopped: boolean };

/** 実行中かもしれない試行 (running) と、実行器が記録した unknown を、人が決着させる */
export async function resolvePending(id: string, args: ResolveArgs, ctx: any, deps: ApproveDeps): Promise<Reply> {
	const limits = deps.limits ?? DEFAULT_LIMITS;
	const cwd = String(ctx.cwd);
	const run = runningOid(cwd, id);
	if (run) {
		const r = resolveRunning(cwd, id, run, args.kind === "retry" ? { kind: "retry" } : { kind: args.kind }, { liveness: deps.liveness, userConfirmedStopped: args.confirmStopped }, limits);
		if (!r.ok) return refuse(oneLine(r.reason, 400));
		const extra = "newId" in r && r.newId ? `。新しい要求 ${r.newId} を作った (再承認が要る)` : "";
		return { text: `決着させた: ${id} (${args.kind})${extra}`, level: "info" };
	}
	const done = doneOid(cwd, id);
	if (done && (args.kind === "success" || args.kind === "failed")) {
		const r = resolveUnknown(cwd, id, { kind: args.kind });
		return r.ok ? { text: `決着させた: ${id} (${args.kind})`, level: "info" } : refuse(oneLine(r.reason, 400));
	}
	return refuse("決着させる対象が無い (running か、実行器が記録した unknown だけ)");
}

// ---- 文面 (一覧・表示) ----

function ago(sec: number, now: number): string {
	const d = Math.max(0, now / 1000 - sec);
	return d < 90 ? "たった今" : d < 5400 ? `${Math.round(d / 60)} 分前` : d < 129600 ? `${Math.round(d / 3600)} 時間前` : `${Math.round(d / 86400)} 日前`;
}

/** 新形式の一覧 (旧形式の退避は、呼び出し側が足す)。symbolic ref は数えない。上限を超えたら、そう書く */
export function listText(cwd: string, deps: Pick<ApproveDeps, "liveness" | "limits">, now: number = Date.now()): string {
	const limits = deps.limits ?? DEFAULT_LIMITS;
	const { entries, truncated } = listOps(cwd, limits);
	const out: string[] = [];
	const pend = entries.filter((e) => e.state === "pending" && e.kind === "action");
	const running = entries.filter((e) => e.state === "running");
	const done = entries.filter((e) => e.state === "done");
	if (pend.length) {
		out.push("保留 (承認待ち):");
		for (const e of pend) {
			const r = readOp(cwd, e.id, limits);
			out.push(r.ok ? `  ${e.id}  ${r.record.action}  (${r.record.reason}・${ago(e.committedAt, now)})` : `  ${e.id}  不正な記録 (${oneLine(r.reason, 80)})`);
		}
	}
	if (running.length) {
		out.push("実行中・決着待ち:");
		for (const e of running) {
			const a = readAttemptAt(cwd, e.id, e.oid);
			if (!a.ok) {
				out.push(`  ${e.id}  不正な試行の記録`);
				continue;
			}
			const live = deps.liveness(a.attempt.owner);
			const name = recordOfChain(cwd, e.id, e.oid, limits)?.action ?? "(読めない)";
			out.push(`  ${e.id}  ${name}  段階: ${a.attempt.stage}  実行者: ${live.state === "alive" ? "生きている" : live.state === "gone" ? "止まっている" : "確認できない"}`);
		}
	}
	const unresolved = done.filter((e) => {
		const r = readResultAt(cwd, e.id, e.oid);
		return r.ok && r.result.outcome === "unknown" && r.result.resolvedBy === "executor";
	});
	if (unresolved.length) {
		out.push("結果不明 (人が決める):");
		for (const e of unresolved) {
			const r = readResultAt(cwd, e.id, e.oid);
			const name = r.ok ? (recordOfChain(cwd, e.id, r.parent, limits)?.action ?? "(読めない)") : "(読めない)";
			out.push(`  ${e.id}  ${name}  /pending resolve ${e.id} success|failed`);
		}
	}
	if (truncated) out.push("(数が多すぎて、全部は数えきれなかった)");
	return out.join("\n");
}

/** 結果の履歴 (done) */
export function logText(cwd: string, limits: Limits = DEFAULT_LIMITS, now: number = Date.now()): string {
	const { entries } = listOps(cwd, limits);
	const rows = entries
		.filter((e) => e.state === "done")
		.map((e) => {
			const r = readResultAt(cwd, e.id, e.oid);
			return r.ok ? `${e.id}  ${r.result.outcome}  (${oneLine(r.result.phase, 40)}・${r.result.resolvedBy}・${ago(e.committedAt, now)})` : `${e.id}  不正な結果の記録`;
		});
	return rows.length ? rows.join("\n") : "結果の記録は無い";
}

/** 1 件の表示。引数・前提は、表示用に整えて切る (記録の中身は信頼しない) */
export function showText(cwd: string, id: string, limits: Limits = DEFAULT_LIMITS): string {
	const lines: string[] = [];
	const rec = readOp(cwd, id, limits);
	const done = doneOid(cwd, id);
	const run = runningOid(cwd, id);
	let record: OpRecord | null = rec.ok ? rec.record : null;
	if (!record && run) record = recordOfChain(cwd, id, run, limits);
	if (!record && done) {
		const r = readResultAt(cwd, id, done);
		if (r.ok) record = recordOfChain(cwd, id, r.parent, limits);
	}
	if (record) {
		const r = record;
		lines.push(`${id}: ${r.action}  理由: ${r.reason}  作成: ${oneLine(r.createdAt, 40)}`);
		lines.push(`要求元: セッション ${oneLine(r.request.sessionId, 80)} / ${oneLine(r.request.cwd, 200)}`);
		for (const [k, v] of Object.entries(r.params)) lines.push(`引数 ${k}: ${oneLine(v, 300)}`);
		lines.push(`前提: ${oneLine(JSON.stringify(r.premise), 600)}`);
		if (r.supersedes) lines.push(`前の要求: ${r.supersedes}`);
	} else if (!run && !done) {
		return `見つからない、または読めない: ${oneLine(rec.ok ? "" : rec.reason)}`;
	}
	if (run) {
		const a = readAttemptAt(cwd, id, run);
		lines.push(a.ok ? `実行中の試行: 段階 ${a.attempt.stage}、開始 ${oneLine(a.attempt.at, 40)}、実行者 pid ${a.attempt.owner.pid} (${oneLine(a.attempt.owner.host, 80)})` : "実行中の試行: 読めない");
	}
	if (done) {
		const r = readResultAt(cwd, id, done);
		if (r.ok) {
			lines.push(`結果: ${r.result.outcome} (${oneLine(r.result.phase, 40)}・${r.result.resolvedBy})`);
			for (const e of r.result.confirmedEffects) lines.push(`  済: ${oneLine(e)}`);
			for (const e of r.result.remainingCleanup) lines.push(`  残: ${oneLine(e)}`);
			for (const e of r.result.evidence) lines.push(`  証拠: ${oneLine(e, 300)}`);
		} else lines.push("結果: 読めない");
	}
	return lines.join("\n");
}
