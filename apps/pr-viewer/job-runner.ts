// ジョブの実行器（設計の「pi の起動」「状態機械」）。pis を 1 回だけ起動し、終了後に検査と commit（job-git.ts）を行う。
// 仕組み・判断基準は docs/spec/pr-viewer.md（ジョブ）が正本。ここには編集時に要る注記だけを書く。
// アプリは pis の出力を実行も解釈もしない。ログへ流すだけで、commit するのは finalizeJob を通った tree だけ。
// Linux 専用（/proc の走査を使う）。HTTP・旗・排他の取得は呼び出し側（job-api.ts）の担当。
import { type ChildProcess, spawn } from "node:child_process";
import { mkdirSync } from "node:fs";
import { isAbsolute, join } from "node:path";
import { type FinalizeDeps, type Pre, type Snapshot, finalizeJob } from "./job-git.ts";
import { type JobPatch, type JobRecord, type Store, appendLog, readJob, releaseLock, signalByJobId, updateJob } from "./job-store.ts";

export const OUTPUT_LIMIT_BYTES = 8 * 1024 * 1024;
export const KILL_GRACE_MS = 15_000;
// 先頭は英数字（`-x/y` が pis の旗に見えるのを断つ）
const MODEL_RE = /^[A-Za-z0-9][A-Za-z0-9._-]*\/[A-Za-z0-9._:-]+$/;

/** pis へ渡す環境変数の許可リスト。GIT_*・PIS_EXTRA_* などは名前で落とす（許可した名前だけを通す）。 */
const ENV_ALLOW = [/^(?:PATH|HOME|USER|LANG|SSL_CERT_FILE|PI_CODING_AGENT_DIR)$/, /^LC_/, /^XDG_/, /_PROXY$/i];

export function buildEnv(src: NodeJS.ProcessEnv, jobId: string): Record<string, string> {
	const env: Record<string, string> = {};
	for (const [k, v] of Object.entries(src)) {
		if (typeof v === "string" && ENV_ALLOW.some((re) => re.test(k))) env[k] = v;
	}
	env.PR_VIEWER_JOB_ID = jobId; // 取り残しプロセスを /proc から探す印
	env.TERM = "dumb";
	env.NO_COLOR = "1";
	return env;
}

/** 固定の argv（pisCommand 自身は含まない）。model は検査し、通らなければ null。 */
export function buildArgv(prompt: string, model?: string | null): string[] | null {
	if (typeof prompt !== "string" || prompt === "" || prompt.includes("\0") || prompt.startsWith("-")) return null;
	const argv = ["--role", "worker", "--allowlist", "-p"];
	if (model !== undefined && model !== null) {
		if (!MODEL_RE.test(model)) return null;
		argv.push("--model", model);
	}
	argv.push(prompt);
	return argv;
}

export type RunDeps = {
	/** 環境変数の元（既定は process.env）。 */
	env?: NodeJS.ProcessEnv;
	/** SIGTERM から SIGKILL までの待ち（既定 15 秒。試験で短縮する）。 */
	graceMs?: number;
	/** 終了後、出力の pipe が閉じるのを待つ時間（既定 1 秒）。 */
	drainMs?: number;
	/** /proc の場所（試験用）。 */
	procRoot?: string;
	/** finalizeJob の差し込み口（試験用）。 */
	finalize?: FinalizeDeps;
};

export type RunOptions = {
	store: Store;
	/** createJob で作り、acquireLock と writePrompt を済ませたジョブ。 */
	job: JobRecord;
	pre: Pre;
	record: Snapshot;
	/** 絶対パスの実行ファイル。 */
	pisCommand: string;
	/** プロンプトと `--model` の値。argv の形はこのモジュールが固定する。 */
	argvTail: { prompt: string; model?: string | null };
	timeoutMs: number;
	outputLimitBytes?: number;
	riskPaths: RegExp[] | null;
	deps?: RunDeps;
};

export type RunHandle = {
	id: string;
	/** 終端の記録で解決する。reject しない。 */
	done: Promise<JobRecord>;
	/** 停止を求める。finalizing 以降は false（止めない）。 */
	cancel(): boolean;
};

type StopReason = "timed_out" | "cancelled" | "interrupted" | "output_limit";
type Phase = "running" | "finalizing" | "done";
type Active = { handle: RunHandle; stop: (r: StopReason) => boolean };
const active = new Set<Active>();

const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

function killGroup(pid: number, sig: NodeJS.Signals): void {
	try {
		process.kill(-pid, sig);
	} catch {
		// 既に無い
	}
}

/** PR_VIEWER_JOB_ID を持つプロセスを SIGKILL する（setsid で抜けた子孫の掃除）。kill した数を返す。探索と送信は回復側と共通（job-store.ts）。 */
export function killByJobId(jobId: string, procRoot = "/proc"): number {
	return signalByJobId(jobId, "SIGKILL", procRoot);
}

/**
 * アプリインスタンスの排他（state root ごと）。OS の advisory lock（flock）を、アプリと同寿命の補助プロセスに持たせる。
 * 補助の stdin はアプリへの pipe で、アプリが（SIGKILL を含めて）消えると EOF で補助も終わり、ロックが外れる。
 * 取れなければ ok:false（生きている先発がいる）。flock が使えない環境も ok:false（reason: unavailable）。
 */
export function acquireInstanceLock(stateDir: string): Promise<{ ok: true } | { ok: false; reason: "held" | "unavailable" }> {
	const script = 'umask 077; exec 3>>"$1" || exit 8; flock -n 3 || exit 9; echo ok; cat >/dev/null';
	return new Promise((resolve) => {
		let child: ChildProcess;
		try {
			mkdirSync(stateDir, { recursive: true, mode: 0o700 });
			child = spawn("sh", ["-c", script, "sh", join(stateDir, "instance.lock")], { stdio: ["pipe", "pipe", "ignore"] });
		} catch {
			return resolve({ ok: false, reason: "unavailable" });
		}
		let done = false;
		const finish = (r: { ok: true } | { ok: false; reason: "held" | "unavailable" }): void => {
			if (!done) {
				done = true;
				resolve(r);
			}
		};
		child.stdin?.on("error", () => {});
		child.stdout?.once("data", () => finish({ ok: true }));
		child.once("error", () => finish({ ok: false, reason: "unavailable" }));
		child.once("exit", (code) => finish({ ok: false, reason: code === 9 ? "held" : "unavailable" }));
	});
}

const STOP_MAP: Record<StopReason, JobPatch> = {
	timed_out: { state: "timed_out", reasons: ["timeout"] },
	cancelled: { state: "cancelled", reasons: ["cancelled"] },
	interrupted: { state: "interrupted", reasons: ["shutdown"] },
	output_limit: { state: "failed", reasons: ["output_limit"] },
};

/** pis を起動して終端まで運ぶ。起動は同期的で、結果は handle.done で受ける。 */
export function runJob(o: RunOptions): RunHandle {
	const { store, job, pre } = o;
	const deps = o.deps ?? {};
	const graceMs = deps.graceMs ?? KILL_GRACE_MS;
	const drainMs = deps.drainMs ?? 1000;
	const limit = o.outputLimitBytes ?? OUTPUT_LIMIT_BYTES;
	const procRoot = deps.procRoot ?? "/proc";
	let phase: Phase = "running";
	let stopReason: StopReason | null = null;
	let graceTimer: NodeJS.Timeout | null = null;
	let pgid: number | null = null;

	const requestStop = (r: StopReason): boolean => {
		if (phase !== "running") return false;
		if (stopReason !== null) return true; // 最初の理由を残す
		stopReason = r;
		if (pgid !== null) {
			killGroup(pgid, "SIGTERM");
			graceTimer = setTimeout(() => {
				if (pgid !== null) killGroup(pgid, "SIGKILL");
				killByJobId(job.id, procRoot);
			}, graceMs);
		}
		return true;
	};

	const conclude = (patch: JobPatch): JobRecord => {
		phase = "done";
		try {
			updateJob(store, job.id, patch);
		} catch {
			// 回復処理などが先に終端へ進めていた
		}
		try {
			releaseLock(store, job.branch, job.id);
		} catch {
			// 排他の解除に失敗しても結果は返す
		}
		return readJob(store, job.id) ?? job;
	};

	const exec = async (): Promise<JobRecord> => {
		const argv = buildArgv(o.argvTail.prompt, o.argvTail.model);
		if (argv === null) return conclude({ state: "failed", reasons: ["bad_argv"] });
		if (!isAbsolute(o.pisCommand) || o.pisCommand.includes("\0")) return conclude({ state: "failed", reasons: ["spawn_failed"] });

		type Exit = { code: number | null; error: boolean };
		let child: ChildProcess;
		try {
			child = spawn(o.pisCommand, argv, {
				cwd: pre.worktree,
				env: buildEnv(deps.env ?? process.env, job.id),
				stdio: ["ignore", "pipe", "pipe"], // stdin は /dev/null
				detached: true, // 新しいプロセスグループ
			});
		} catch {
			return conclude({ state: "failed", reasons: ["spawn_failed"] });
		}
		const exited = new Promise<Exit>((resolve) => {
			child.once("error", () => resolve({ code: null, error: true }));
			child.once("exit", (code) => resolve({ code, error: false }));
		});
		const closed = new Promise<void>((resolve) => child.once("close", () => resolve()));
		if (child.pid === undefined) {
			await exited;
			return conclude({ state: "failed", reasons: ["spawn_failed"] });
		}
		pgid = child.pid;
		try {
			updateJob(store, job.id, { state: "running", pid: child.pid });
		} catch {
			// 続行する（終端の書き込みで整える）
		}

		let total = 0;
		let overLimit = false;
		const onData = (chunk: Buffer) => {
			total += chunk.length;
			if (total > limit) {
				if (!overLimit) {
					overLimit = true;
					requestStop("output_limit");
				}
				return; // 超えた分は保存しない
			}
			try {
				appendLog(store, job.id, chunk);
			} catch {
				// ログの失敗でジョブは止めない
			}
		};
		child.stdout?.on("data", onData);
		child.stderr?.on("data", onData);
		child.stdout?.on("error", () => {});
		child.stderr?.on("error", () => {});
		const timer = setTimeout(() => requestStop("timed_out"), o.timeoutMs);

		const ex = await exited;
		clearTimeout(timer);
		// 正常終了でも、残った子孫がワークツリーを書き換えうる。検査の前に、グループと印つきの残りを必ず掃除する
		await Promise.race([closed, sleep(drainMs)]);
		killGroup(pgid, "SIGKILL");
		killByJobId(job.id, procRoot);
		await Promise.race([closed, sleep(2000)]);
		if (graceTimer) clearTimeout(graceTimer);
		child.stdout?.destroy();
		child.stderr?.destroy();

		if (ex.error) return conclude({ state: "failed", reasons: ["spawn_failed"] });
		if (stopReason !== null) return conclude({ ...STOP_MAP[stopReason], exitCode: ex.code });
		if (ex.code !== 0) return conclude({ state: "failed", reasons: ["exit_nonzero"], exitCode: ex.code });

		phase = "finalizing"; // これ以降は kill しない
		try {
			updateJob(store, job.id, { state: "finalizing", exitCode: 0 });
		} catch {
			// 続行する
		}
		const res = await finalizeJob(pre, o.record, { jobId: job.id, batchIds: job.batchIds, riskPaths: o.riskPaths }, deps.finalize);
		const base = { exitCode: 0, resultOid: res.resultOid ?? null };
		switch (res.state) {
			case "committed":
				return conclude({ ...base, state: "succeeded", reasons: res.reasons, files: res.files });
			case "no_change":
				return conclude({ ...base, state: "no_change", reasons: [] });
			case "needs_review":
				return conclude({ ...base, state: "needs_review", reasons: res.reasons, files: res.files });
			default: // tampered・failed。commit していない
				return conclude({ ...base, state: "failed", reasons: res.reasons });
		}
	};

	const handle: RunHandle = { id: job.id, done: Promise.resolve(job), cancel: () => requestStop("cancelled") };
	const entry: Active = { handle, stop: requestStop };
	active.add(entry);
	handle.done = exec()
		.catch(() => conclude({ state: "failed", reasons: ["exception"] }))
		.finally(() => {
			phase = "done";
			active.delete(entry);
		});
	return handle;
}

/**
 * アプリの停止。実行中のジョブは止めて interrupted にし、finalizing のものだけ終わるのを待つ。
 * 終端への書き込みと排他の解除まで済んでから解決する。
 */
export async function shutdown(): Promise<void> {
	const list = [...active];
	for (const a of list) a.stop("interrupted");
	await Promise.all(list.map((a) => a.handle.done));
}
