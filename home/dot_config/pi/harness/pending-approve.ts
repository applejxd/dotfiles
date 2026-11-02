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
import { acquireLock, forceRelease, lockKeyOf, readLock, releaseLock, type Holder, type LockHandle, type ProbeResult } from "./exclusive-lock.ts";
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
	readRunningStrict,
	recordOidOf,
	resolveRunning,
	resolveUnknown,
	returnToPending,
	runningOid,
	validateResultBody,
	type Attempt,
	type Decision,
	type Liveness,
	type Limits,
	type OpRecord,
	type Owner,
	type ResultBody,
} from "./pending-ops.ts";

export type ApprovalEnv = { cwd: string; env: NodeJS.ProcessEnv; rules: any };

/**
 * 実行器の戻り値。termination = 実行したプロセス (git・hook) の停止を確認できたか。"unconfirmed" なら、結果を確定しない・ロックを外さない
 * (停止の状態は結果の JSON に混ぜない)。ResultBody だけを返す旧形式も受け付ける
 */
export type ExecOutcome = { body: ResultBody; termination: "stopped" | "unconfirmed" };
export type HereCheck = { ok: true; here: boolean } | { ok: false; reason: string };

/** 検証済みの実行計画を作り、再検査し、実行する (操作ごと)。実行は、開始が保存された後にだけ呼ばれる */
export type ApprovalAdapter = {
	action: string;
	label: string;
	/** 記録から、現在の設定・役割・実行先で検証した実行計画を作る。summary は確認の画面、view は「全文を見る」 */
	plan: (rec: OpRecord, env: ApprovalEnv) => Promise<{ ok: true; plan: unknown; summary: string; view: string } | { ok: false; reason: string }>;
	/** 実行の直前の再検査 (前提・対象の期待値) */
	recheck: (plan: unknown, env: ApprovalEnv) => Promise<{ ok: true } | { ok: false; reason: string }>;
	/** 実行。結果は 4 値。例外は呼び出し側が unknown にする */
	execute: (plan: unknown, env: ApprovalEnv, signal?: AbortSignal) => Promise<ResultBody | ExecOutcome>;
	/** 承認者の cwd が、実行先の中か。中でなければ断る。観測できない (ok:false) も断る (許可に読み替えない)。省略したときは制限しない */
	runsHere?: (plan: unknown, env: ApprovalEnv) => HereCheck;
	/** true なら、リポジトリ単位の排他ロックを取ってから実行する (git・hook を起動する操作)。停止を確認できない結果は、ロックを残す */
	exclusive?: boolean;
	/** 候補の一覧に出す 1 行の要約 (記録だけから作る。git を起動しない) */
	brief?: (rec: OpRecord) => string;
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
	/** 承認側の再判定: 保留の記録 (信頼しない入力) が、いまの役割・操作の定義で許されるか。断られたら計画も画面も出さない。本接続では必ず渡す */
	authorize?: (rec: OpRecord) => { ok: true } | { ok: false; reason: string };
};

export type Reply = { text: string; level: "info" | "warning" | "error" };

export const CHOICE_APPROVE = "承認して実行";
export const CHOICE_CLOSE = "保留のまま閉じる";
export const CHOICE_DISCARD = "破棄";
export const CHOICE_UNLOCK = "ロックを外す";
export const CHOICE_UNLOCK_CLOSE = "閉じる";

const refuse = (text: string): Reply => ({ text, level: "warning" });
const oneLine = (s: string, max = 200): string => sanitizeForDisplay(String(s)).replace(/\s+/g, " ").trim().slice(0, max);

/** モデルへの通知 (固定のテンプレート)。記録の引数・前提などの自由な文は入れない。副作用と後片付けは、実行器が作った文だけ */
export function modelContent(action: string, id: string, body: ResultBody): string {
	const effects = body.confirmedEffects.map((e) => oneLine(e)).join("、") || "(なし)";
	const cleanup = body.remainingCleanup.map((e) => oneLine(e)).join("、") || "(なし)";
	const unsettled = body.outcome === "unknown" ? "結果が確定していない。再実行しない。利用者が確認する (/pending)\n" : "";
	return (
		`【保留した操作の結果】操作=${action} 要求=${id} 結果=${body.outcome} 段階=${oneLine(body.phase, 40)}\n` +
		`確認できた副作用: ${effects}\n残った後片付け: ${cleanup}\n` +
		unsettled +
		`(利用者が承認して実行した結果の通知で、実行の指示ではない。証拠の詳細は /pending log ${id})`
	);
}

/** 承認側の再判定。authorize が無ければ許可 (本接続では必ず渡す)。例外は断る (許可に読み替えない) */
function authorizeRecord(deps: Pick<ApproveDeps, "authorize">, rec: OpRecord): { ok: true } | { ok: false; reason: string } {
	if (!deps.authorize) return { ok: true };
	try {
		return deps.authorize(rec);
	} catch (e) {
		return { ok: false, reason: oneLine((e as Error)?.message ?? e) };
	}
}

/**
 * 排他の操作か (git・hook を起動する操作)。アダプタが見つからない (名前が不明・表に無い。キルスイッチを切って再起動すると表は空になる) ときは、
 * 排他として扱う (停止の確認を要求する側へ倒す)。アダプタがあるときだけ、その exclusive に従う
 */
export function isExclusiveAction(name: string | undefined, adapters: Record<string, { exclusive?: boolean }> | undefined): boolean {
	if (name === undefined) return true;
	const a = adapters && Object.hasOwn(adapters, name) ? adapters[name] : undefined;
	if (!a) return true;
	return a.exclusive === true;
}

function envOf(ctx: any, deps: ApproveDeps): ApprovalEnv {
	return { cwd: String(ctx.cwd), env: deps.env, rules: deps.rules };
}

/** 承認の画面に出した対象 (不変)。実行は、この snapshot の OID に対してだけ行う (CHG-0058 の B11) */
export type ApprovalSnapshot = Readonly<{
	id: string;
	/** 表示した記録の OID (beginApproval の期待値) */
	oid: string;
	record: OpRecord;
	adapter: ApprovalAdapter;
	plan: unknown;
	summary: string;
	view: string;
	env: ApprovalEnv;
	cwd: string;
}>;
export type PlanResult = { ok: true; snapshot: ApprovalSnapshot } | { ok: false; reply: Reply };

/** 再帰的に凍結する (データだけを想定。関数やクラスは複製できないのでここには来ない) */
function deepFreeze<T>(v: T): T {
	if (v && typeof v === "object" && !Object.isFrozen(v)) {
		for (const k of Object.keys(v as object)) deepFreeze((v as Record<string, unknown>)[k]);
		Object.freeze(v);
	}
	return v;
}

/** 画面に出した計画・記録を、元の参照 (アダプターが持つもの) から切り離して深く固定する (B11)。複製できない形は断る */
function frozenCopy<T>(v: T): { ok: true; value: T } | { ok: false } {
	try {
		return { ok: true, value: deepFreeze(structuredClone(v)) };
	} catch {
		return { ok: false };
	}
}

const BUSY_TEXT = "モデルの実行中は承認できない (承認の実行が、モデルの作業と重ならないように)。Esc で止めるか、終わってからもう一度実行する";

/** 承認の画面の前まで (ガード・記録・アダプタ・authorize・plan・hereRefusal)。副作用なし */
export async function planApproval(id: string, ctx: any, deps: ApproveDeps, _signal?: AbortSignal): Promise<PlanResult> {
	const limits = deps.limits ?? DEFAULT_LIMITS;
	const no = (reply: Reply): PlanResult => ({ ok: false, reply });
	if (!deps.enabled()) return no(refuse("保留 (非同期承認) は無効 ([pi.pending] enabled = false)。承認はできない (一覧・破棄・復旧は使える)"));
	if (ctx.mode !== "tui" || !deps.modes.includes(ctx.mode) || !ctx.hasUI) return no(refuse("承認は、対話 (TUI) の pi だけでできる"));
	if (typeof ctx.isIdle === "function" && !ctx.isIdle()) return no(refuse(BUSY_TEXT));
	const cwd = String(ctx.cwd);
	const rec = readOp(cwd, id, limits);
	if (!rec.ok) return no(refuse(`記録を読めない: ${oneLine(rec.reason)}。/pending drop で破棄できる`));
	const adapter = deps.adapters[rec.record.action];
	if (!adapter) return no(refuse(`この操作 (${rec.record.action}) は、承認に対応していない。保留は残してある`));
	if (deps.authorize) {
		const au = authorizeRecord(deps, rec.record);
		if (!au.ok) return no(refuse(`承認できない: ${oneLine(au.reason)}。保留は残してある (実行していない)`));
	}
	const env = envOf(ctx, deps);
	let planned: Awaited<ReturnType<ApprovalAdapter["plan"]>>;
	try {
		planned = await adapter.plan(rec.record, env);
	} catch (e) {
		planned = { ok: false, reason: oneLine((e as Error)?.message ?? e) };
	}
	if (!planned.ok) return no(refuse(`承認できない: ${oneLine(planned.reason)}。保留は残してある (実行していない)`));
	// 承認者の cwd が実行先の中でないときは、確認の画面を出す前に断る
	const outside = hereRefusal(adapter, planned.plan, env);
	if (outside) return no(refuse(`承認できない: ${outside}。保留は残してある (実行していない)`));
	// 表示する計画と実行する計画を同じに保つ: 記録と計画は、アダプターが持つ元の参照から切り離して深く固定した複製を snapshot に持つ
	const rc = frozenCopy(rec.record);
	const pc = frozenCopy(planned.plan);
	if (!rc.ok || !pc.ok) return no(refuse("承認できない: 計画・記録を複製して固定できない形 (データだけにする)。保留は残してある (実行していない)"));
	const snapshot: ApprovalSnapshot = Object.freeze({ id, oid: rec.oid, record: rc.value, adapter, plan: pc.value, summary: planned.summary, view: planned.view, env: Object.freeze({ ...env }), cwd });
	return { ok: true, snapshot };
}

export type ExecutionResult =
	| { kind: "refused"; reply: Reply }
	| {
			kind: "executed";
			reply: Reply;
			outcome: ResultBody["outcome"];
			termination: "stopped" | "unconfirmed";
			/** 結果を記録できたか */
			saved: boolean;
			/** 保存した結果の記録 (refs/pi/done/<id>) の OID。保存できなかったときは無い */
			doneOid?: string;
			/** 残った後片付けがあるか (実行器の報告・ロックを外せなかった) */
			cleanup: boolean;
			/** running とロックを残したか */
			kept: boolean;
	  };

/** 承認された snapshot を実行する。画面の後の確認 (モデルが起きていないか・再判定・表示した OID の取得) を通ったときだけ、runApproved の経路に入る */
export async function executeApproval(snap: ApprovalSnapshot, ctx: any, deps: ApproveDeps, signal?: AbortSignal): Promise<ExecutionResult> {
	const limits = deps.limits ?? DEFAULT_LIMITS;
	const no = (reply: Reply): ExecutionResult => ({ kind: "refused", reply });
	if (typeof ctx.isIdle === "function" && !ctx.isIdle()) return no(refuse(`${BUSY_TEXT}。保留は残してある (実行していない)`));
	// 承認された。ただし画面は期限なしで、眺めている間に役割・設定 (/reload・キルスイッチ) が変わりうる。表示した記録を、もう一度判定する
	const again = authorizeRecord(deps, snap.record);
	if (!again.ok) return no(refuse(`承認できない (画面の後の再判定): ${oneLine(again.reason)}。保留は残してある (実行していない)`));
	// 表示した記録の OID を排他的に取得する (表示した後に変わっていれば失敗する)
	const begin = beginApproval(snap.cwd, snap.id, snap.oid, deps.owner(), limits);
	if (!begin.ok) return no(refuse(`承認を始められなかった: ${oneLine(begin.reason)}。実行していない`));
	return runApprovedDetailed({ cwd: snap.cwd, id: snap.id, adapter: snap.adapter, plan: snap.plan, env: snap.env, attempt: begin.attempt, attemptOid: begin.attemptOid, deps, signal });
}

/** 保留を承認して実行する。呼べるのは、利用者の対話 (TUI) の pi だけ。planApproval → 画面 → executeApproval の合成 */
export async function approvePending(id: string, ctx: any, deps: ApproveDeps, signal?: AbortSignal): Promise<Reply> {
	const limits = deps.limits ?? DEFAULT_LIMITS;
	const pl = await planApproval(id, ctx, deps, signal);
	if (!pl.ok) return pl.reply;
	const snap = pl.snapshot;
	// 利用者に、その計画を表示する (期限なし)
	const choice = await deps.dialog(async () => {
		if (signal?.aborted) return undefined;
		deps.bell();
		const r = await presentConfirm(ctx.ui, {
			title: `${snap.adapter.label}の承認 (${id})\n\n${snap.summary}`,
			options: [CHOICE_APPROVE, VIEW_FULL, CHOICE_CLOSE, CHOICE_DISCARD],
			signal,
			viewFull: { title: `${snap.adapter.label}: 全文 (読むだけ。閉じると確認に戻る)`, text: () => snap.view },
		});
		return r.choice;
	});
	if (choice === CHOICE_DISCARD) {
		const d = discardOp(snap.cwd, id, snap.oid, limits);
		return d.ok ? { text: `破棄した: ${id} (到達用の ref を外した。オブジェクトは git gc まで残る)`, level: "info" } : refuse(d.reason);
	}
	if (choice !== CHOICE_APPROVE) return { text: `保留のまま閉じた: ${id}`, level: "info" };
	return (await executeApproval(snap, ctx, deps, signal)).reply;
}

/** ロックの保持者の試行を、保存層から厳密に読む (排他ロックの自動回復の根拠)。無い・読めない・別の試行は、回復の根拠にしない */
export function probeHolder(cwd: string, h: Holder, liveness: Liveness): ProbeResult {
	const run = readRunningStrict(cwd, h.runningId);
	if (run.state === "absent") return { attempt: "absent", owner: "unknown" };
	if (run.state === "unreadable") return { attempt: "unreadable", owner: "unknown" };
	const a = readAttemptAt(cwd, h.runningId, run.oid);
	if (!a.ok) return { attempt: "unreadable", owner: "unknown" };
	if (a.attempt.attemptId !== h.attemptId) return { attempt: "mismatch", owner: "unknown" };
	return { attempt: a.attempt.stage, owner: liveness(a.attempt.owner).state };
}

/** 承認者の cwd が実行先の中か。断る理由 (中なら null)。観測できない・例外も断る (許可に読み替えない) */
function hereRefusal(adapter: ApprovalAdapter, plan: unknown, env: ApprovalEnv): string | null {
	if (!adapter.runsHere) return null;
	let h: HereCheck;
	try {
		h = adapter.runsHere(plan, env);
	} catch (e) {
		return `承認者の位置を確認できない (${oneLine((e as Error)?.message ?? e)})。統合先の worktree の pi で承認する`;
	}
	if (!h.ok) return `承認者の位置を確認できない (${oneLine(h.reason)})。統合先の worktree の pi で承認する`;
	return h.here ? null : "この操作は、統合先の worktree の pi で承認する (いまの pi は、統合先の中ではない)";
}

function isOutcome(x: unknown): x is ExecOutcome {
	return typeof x === "object" && x !== null && "body" in x;
}

export type RunApprovedArgs = {
	cwd: string;
	id: string;
	adapter: ApprovalAdapter;
	plan: unknown;
	env: ApprovalEnv;
	/** beginApproval で作った試行 (reserved) */
	attempt: Attempt;
	attemptOid: string;
	deps: ApproveDeps;
	signal?: AbortSignal;
};

/**
 * 承認された試行 (reserved) を、排他ロック → 再検査 → 開始の保存 → 実行 → 結果の記録の順に進める。
 * 開始の前の失敗は、ロックを外して pending へ戻す (未実行)。開始の後は、結果を記録できたときだけロックを外す。
 * 停止を確認できない実行 (termination = unconfirmed、排他の操作の例外・不正な結果) と、結果を保存できなかったときは、
 * running とロックを残して、人の /pending resolve に任せる (無条件の finally で解放しない)。
 */
export async function runApproved(a: RunApprovedArgs): Promise<Reply> {
	return (await runApprovedDetailed(a)).reply;
}

type Go = { reply: Reply; keep: boolean; done?: { outcome: ResultBody["outcome"]; termination: "stopped" | "unconfirmed"; saved: boolean; cleanup: boolean; doneOid?: string } };

/** runApproved の本体。文面を解析しなくてよいように、実行したか・outcome・停止確認・保存・後片付け・残したかを構造化して返す */
export async function runApprovedDetailed(a: RunApprovedArgs): Promise<ExecutionResult> {
	const { cwd, id, adapter, plan, env, deps, signal } = a;
	let attemptOid = a.attemptOid;
	let started = false;
	const held: { lock: LockHandle | null } = { lock: null };
	const back = (why: string): Reply => {
		const r = returnToPending(cwd, id, attemptOid);
		return refuse(`${why}。${r.ok ? "保留に戻した" : `保留に戻せなかった (${oneLine(r.reason)}。/pending で確認する)`}。実行していない`);
	};
	// モデルへの通知は補助。失敗しても、記録した結果 (outcome・保存) を変えない
	const tell = (b: ResultBody) => {
		try {
			deps.tellModel(modelContent(adapter.action, id, b), { id, action: adapter.action, outcome: b.outcome });
		} catch {}
	};
	const go = async (): Promise<Go> => {
		// 承認者の cwd (画面の前にも確かめているが、試行を作った後でも確かめる)
		const outside = hereRefusal(adapter, plan, env);
		if (outside) return { reply: back(outside), keep: false };
		if (adapter.exclusive) {
			const got = acquireLock(cwd, { runningId: id, attemptId: a.attempt.attemptId }, { probe: (h) => probeHolder(cwd, h, deps.liveness), env: deps.env });
			if (!got.ok) return { reply: back(`統合の排他ロックを取れなかった [${got.code}]: ${oneLine(got.reason, 200)}`), keep: false };
			held.lock = got.handle;
		}
		// 実行の直前の再検査 (前提・対象の期待値・現在のキルスイッチ)。ロックを取ってから行う (他の承認と状態が重ならない)
		let recheck: { ok: true } | { ok: false; reason: string };
		try {
			recheck = await adapter.recheck(plan, env);
		} catch (e) {
			recheck = { ok: false, reason: oneLine((e as Error)?.message ?? e) };
		}
		if (!recheck.ok) return { reply: back(`再検査で止めた: ${oneLine(recheck.reason)}`), keep: false };
		if (!deps.enabled()) return { reply: back("実行の直前に、保留が無効にされた"), keep: false };
		// 副作用を始める意図を永続化する。これに成功するまで、副作用のあるプロセスを起動しない
		const st = markStarted(cwd, id, attemptOid);
		if (!st.ok) return { reply: back(`開始を記録できなかった: ${oneLine(st.reason)}`), keep: false };
		attemptOid = st.attemptOid;
		started = true;

		let body: ResultBody;
		let termination: "stopped" | "unconfirmed";
		try {
			const r = await adapter.execute(plan, env, signal);
			if (isOutcome(r)) {
				body = r.body;
				termination = r.termination === "stopped" ? "stopped" : "unconfirmed";
			} else {
				// 旧形式 (ResultBody だけ)。排他の操作で結果が不明なときは、停止を確かめられない扱い
				body = r;
				termination = adapter.exclusive && (r as ResultBody | undefined)?.outcome === "unknown" ? "unconfirmed" : "stopped";
			}
		} catch (e) {
			body = { outcome: "unknown", phase: "execute", confirmedEffects: [], remainingCleanup: [], evidence: [`実行中に例外が出た: ${oneLine((e as Error)?.message ?? e, 300)}`] };
			termination = adapter.exclusive ? "unconfirmed" : "stopped";
		}
		if (!validateResultBody(body)) {
			body = { outcome: "unknown", phase: "execute", confirmedEffects: [], remainingCleanup: [], evidence: ["実行器の結果の形が不正だった。副作用の有無を確定できない"] };
			if (adapter.exclusive) termination = "unconfirmed";
		}
		const summary = `${adapter.label}: ${body.outcome} (${oneLine(body.phase, 40)})`;
		const detail = [...body.confirmedEffects.map((e) => `  済: ${oneLine(e)}`), ...body.remainingCleanup.map((e) => `  残: ${oneLine(e)}`)];
		const kept = adapter.exclusive ? "running と統合ロックを残した" : "running を残した";
		if (termination === "unconfirmed") {
			tell(body);
			const text = `${summary}。git・hook の停止を確認できなかった。${kept} (結果は記録していない)。止まっていると確かめてから /pending resolve ${id} <success|failed|retry> --confirm-stopped で決着させる`;
			return { reply: { text: [text, ...detail].join("\n"), level: "error" }, keep: true, done: { outcome: body.outcome, termination, saved: false, cleanup: body.remainingCleanup.length > 0 } };
		}
		const fin = finishApproval(cwd, id, attemptOid, body);
		if (!fin.ok) {
			// 結果を保存できなかった。running (とロック) を残す (人が /pending resolve で決める)
			return { reply: { text: `${summary}。結果を保存できなかった (${oneLine(fin.reason)})。${kept}。/pending で確認する`, level: "error" }, keep: true, done: { outcome: body.outcome, termination, saved: false, cleanup: body.remainingCleanup.length > 0 } };
		}
		tell(body);
		const level = body.outcome === "success" ? "info" : body.outcome === "not_executed" ? "warning" : "error";
		return { reply: { text: [summary, ...detail].join("\n"), level }, keep: false, done: { outcome: body.outcome, termination, saved: true, cleanup: body.remainingCleanup.length > 0, doneOid: fin.doneOid } };
	};

	let r: Go;
	try {
		r = await go();
	} catch (e) {
		const why = `承認の実行中に内部エラーが出た (${oneLine((e as Error)?.message ?? e, 200)})`;
		r = started ? { reply: { text: `${why}。実行の有無を確定できない。running とロックを残した。/pending で確認する`, level: "error" }, keep: true, done: { outcome: "unknown", termination: "unconfirmed", saved: false, cleanup: false } } : { reply: back(why), keep: false };
	}
	// ロックは、決着した (結果を記録できた) ときと、開始前の失敗のときだけ外す
	if (held.lock && !r.keep) {
		const rel = releaseLock(cwd, held.lock, deps.env);
		if (!rel.ok) {
			r = { reply: { text: `${r.reply.text}\n統合ロックを外せなかった (${oneLine(rel.reason)})。/pending unlock で外す`, level: r.reply.level === "info" ? "warning" : r.reply.level }, keep: false, done: r.done ? { ...r.done, cleanup: true } : undefined };
		}
	}
	if (!r.done) return { kind: "refused", reply: r.reply };
	return { kind: "executed", reply: r.reply, ...r.done, kept: r.keep };
}

/** 試行の鎖をたどって、元の記録を読む (pending の ref が消えた後も、操作の名前と引数を見せるため) */
export function recordOfChain(cwd: string, id: string, attemptOid: string, limits: Limits): OpRecord | null {
	const root = recordOidOf(cwd, id, attemptOid);
	if (!root.ok) return null;
	const r = readOpAt(cwd, id, root.oid, limits);
	return r.ok ? r.record : null;
}

export type ResolveArgs = { kind: "success" | "failed" | "retry" | "pending" | "abandon"; confirmStopped: boolean };

/** 決着した試行が持っていた統合ロックだけを外す (保持者が一致したときだけ。無い・不正・別の保持者は触れない)。表示用の文を返す */
function releaseHolderLock(cwd: string, holder: Holder, env?: NodeJS.ProcessEnv): string {
	const k = lockKeyOf(cwd, env);
	if (!k.ok) return "";
	const l = readLock(cwd, k.key, env);
	if (l.state !== "held" || l.holder.runningId !== holder.runningId || l.holder.attemptId !== holder.attemptId) return "";
	const r = forceRelease(cwd, l.oid, env);
	return r.ok ? "。統合ロックを外した" : `。統合ロックを外せなかった (${oneLine(r.reason ?? "")})。/pending unlock で外す`;
}

/**
 * 統合ロックを、利用者が確認のうえで外す (孤児のロック専用)。実行中の試行 (running) があるロックは外さない (/pending resolve が外す)。
 * 読めない・不正なロックは、ここでは消さない (自動で消さないという fail-closed の続き)。対話 (TUI) だけ
 */
export async function unlockPending(ctx: any, deps: ApproveDeps): Promise<Reply> {
	if (ctx.mode !== "tui" || !ctx.hasUI) return refuse("ロックの解除は、対話 (TUI) の pi だけでできる");
	const cwd = String(ctx.cwd);
	const k = lockKeyOf(cwd, deps.env);
	if (!k.ok) return refuse(`リポジトリを特定できない: ${oneLine(k.reason)}`);
	const l = readLock(cwd, k.key, deps.env);
	if (l.state === "missing") return { text: "統合ロックは無い", level: "info" };
	if (l.state !== "held") return refuse(`統合ロックを読めない (${l.state}: ${oneLine(l.reason)})。自分のシェルで refs/pi/lock/ を確かめて外す`);
	const probe = probeHolder(cwd, l.holder, deps.liveness);
	if (probe.attempt === "reserved" || probe.attempt === "started") {
		return refuse(`ロックの保持者 ${l.holder.runningId} は、running (${probe.attempt}) のまま。/pending resolve ${l.holder.runningId} で決着させる (ロックは resolve が外す)`);
	}
	if (probe.attempt === "unreadable") return refuse(`ロックの保持者 ${l.holder.runningId} の試行を読めない。自分のシェルで確かめる`);
	const choice = await deps.dialog(async () => {
		deps.bell();
		const r = await presentConfirm(ctx.ui, {
			title: `統合ロックの解除\n\n保持者: ${l.holder.runningId} (試行は残っていない = 孤児)  取得: ${oneLine(l.at, 40)}\n実行中の git・hook が無いと確かめてから外す (外すと、別の統合を実行できる)`,
			options: [CHOICE_UNLOCK, CHOICE_UNLOCK_CLOSE],
		});
		return r.choice;
	});
	if (choice !== CHOICE_UNLOCK) return { text: "閉じた: 統合ロックはそのまま", level: "info" };
	const r = forceRelease(cwd, l.oid, deps.env);
	return r.ok ? { text: `統合ロックを外した (保持者 ${l.holder.runningId})`, level: "info" } : refuse(`ロックを外せなかった: ${oneLine(r.reason ?? "")}`);
}

/** 実行中かもしれない試行 (running) と、実行器が記録した unknown を、人が決着させる */
export async function resolvePending(id: string, args: ResolveArgs, ctx: any, deps: ApproveDeps): Promise<Reply> {
	const limits = deps.limits ?? DEFAULT_LIMITS;
	const cwd = String(ctx.cwd);
	const run = runningOid(cwd, id);
	if (run) {
		const att = readAttemptAt(cwd, id, run);
		const name = recordOfChain(cwd, id, run, limits)?.action;
		const exclusive = isExclusiveAction(name, deps.adapters);
		const exclusiveStarted = exclusive && att.ok && att.attempt.stage === "started";
		// git・hook を起動する操作の開始済みの試行は、実行者 (pi) が止まっていても、git・hook が止まった証拠にならない。利用者の明示が要る
		if (exclusiveStarted && att.ok && !args.confirmStopped && deps.liveness(att.attempt.owner).state !== "alive") {
			return refuse(
				`この操作は git・hook を起動する。実行者の状態だけでは、それらが止まった証拠にならない。止まっていると確かめてから、--confirm-stopped を付けて決着させる`,
			);
		}
		const evidence = exclusiveStarted ? ["利用者が、実行者と git・hook の停止を確認したと明示した (--confirm-stopped)"] : undefined;
		const decision: Decision =
			args.kind === "retry" ? { kind: "retry", ...(evidence ? { evidence } : {}) } : args.kind === "success" || args.kind === "failed" ? { kind: args.kind, ...(evidence ? { evidence } : {}) } : { kind: args.kind };
		const r = resolveRunning(cwd, id, run, decision, { liveness: deps.liveness, userConfirmedStopped: args.confirmStopped }, limits);
		if (!r.ok) return refuse(oneLine(r.reason, 400));
		const extra = "newId" in r && r.newId ? `。新しい要求 ${r.newId} を作った (再承認が要る)` : "";
		// 決着した試行のロックだけを外す (別の試行のロックと、不正なロックには触れない)
		const lockNote = exclusive && att.ok ? releaseHolderLock(cwd, { runningId: id, attemptId: att.attempt.attemptId }, deps.env) : "";
		return { text: `決着させた: ${id} (${args.kind})${extra}${lockNote}`, level: "info" };
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
	// 統合の排他ロック。あるときだけ出す (無いときの出力は従来どおり)
	const k = lockKeyOf(cwd);
	const lock = k.ok ? readLock(cwd, k.key) : null;
	if (lock?.state === "held") out.push(`統合ロック: 保持者 ${lock.holder.runningId}  外す: /pending unlock (実行中の試行があるときは /pending resolve)`);
	else if (lock && lock.state !== "missing") out.push(`統合ロック: 読めない (${lock.state})。自分のシェルで refs/pi/lock/ を確かめて外す`);
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

const PARAM_INLINE_MAX = 200;
const PARAM_BLOCK_MAX = 1300;

/** 引数 1 つの表示。1 行で短ければ 1 行、複数行・長いものは空行を除く全行を 4 スペースで (上限 PARAM_BLOCK_MAX 字。折り返しは端末に任せる) */
function paramLines(k: string, v: string): string[] {
	const text = sanitizeForDisplay(String(v));
	if (!/[\r\n]/.test(text) && text.length <= PARAM_INLINE_MAX) return [`引数 ${k}: ${text.replace(/\s+/g, " ").trim()}`];
	const rows = text.split(/\r?\n/).map((l) => l.trimEnd()).filter((l) => l.trim() !== "");
	const out: string[] = [`引数 ${k}:`];
	let used = 0;
	for (let i = 0; i < rows.length; i++) {
		const room = PARAM_BLOCK_MAX - used;
		if (rows[i].length > room) {
			const rest = rows.slice(i).reduce((n, l) => n + l.length, 0) - Math.max(room, 0);
			if (room > 0) out.push(`    ${rows[i].slice(0, room)}`);
			out.push(`    …(以下 ${rest} 字は省略)`);
			return out;
		}
		out.push(`    ${rows[i]}`);
		used += rows[i].length;
	}
	return out;
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
		for (const [k, v] of Object.entries(r.params)) lines.push(...paramLines(k, v));
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
