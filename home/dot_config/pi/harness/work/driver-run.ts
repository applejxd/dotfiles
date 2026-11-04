// ドライバ (driver.ts の純関数) を pi の実際の子の起動 (index.ts の spawnChild と Jobs) へ繋ぐ薄い接着層。
// 既定は無効: PI_WORK_SCHEDULER=1 のときだけ登録する。PI_WORK=0 で一括無効。子 (child) では動かさない。
// 子の起動は注入された spawnChild の 1 本だけを通す (argv・env・役割・書き込み範囲は既存のまま。新しい権限の経路は作らない)。
// 子には work ツールを渡さない (子では registerWork が登録しない)。see docs/spec/work/driver-run.md
import { aimdInit, DEFAULT_AIMD } from "./aimd.ts";
import type { ProviderState } from "./aimd.ts";
import { emptyMemo, onFinished, onOutput, onSpawned, onUsage, reconcile, tick } from "./driver.ts";
import type { Memo, RunResult, SpawnSpec, Spawner } from "./driver.ts";
import type { Journal } from "./journal.ts";
import type { Runtime, RuntimeTimers } from "./runtime.ts";
import type { EventType, NewEvent } from "./types.ts";

/** 子 (Job) のうち、ここが使う操作だけ (children.ts の Job が満たす) */
export interface JobLike {
	readonly id: string;
	readonly pid?: number;
	calls: number;
	tokens: number;
	cost: number;
	run(message: string, opts: { timeoutMs: number }): Promise<{ status: string; answer: string; errors: string[]; note?: string; blocked: string[] }>;
	steer(message: string): string;
	close(force?: boolean): void;
}

/** index.ts の spawnChild の署名 (isolation だけ使う。それ以外は既定のまま) */
export type SpawnChildFn = (
	agent: string,
	ctx: any,
	owner: { cwd: string; role: string },
	model?: string,
	isolation?: boolean,
) => { job: JobLike; model: string } | { error: string; full?: boolean };

/** Jobs (children.ts) のうち、同時数の計算に使う分だけ */
export interface JobsLike {
	readonly max: number;
	readonly size: number;
}

/** runtime と holder の取得 (まだ開いていなければ null。null の間は何もしない) */
export type RuntimeSource = () => { runtime: Runtime; holder: string } | null;

/** 台帳の runtime を共有する最小の登録簿 (register.ts が将来ここへ置く。無ければ driver-run は何もしない) */
export const WORK_REGISTRY_KEY = "__piWork";
export const registryRuntime: RuntimeSource = () => {
	const r = (globalThis as any)[WORK_REGISTRY_KEY];
	return r && r.runtime && typeof r.holder === "string" ? r : null;
};

export interface DriverRunOptions {
	child: boolean;
	env?: Record<string, string | undefined>;
	runtime: RuntimeSource;
	spawnChild: SpawnChildFn;
	jobs: JobsLike;
	journal?: Pick<Journal, "emit">;
	now?: () => number;
	timers?: RuntimeTimers;
	/** 起動の間隔 (ms)。既定 2000 */
	pollMs?: number;
	/** 子 1 往復の時間切れ (ms)。既定 30 分 */
	timeoutMs?: number;
	/** 子の owner.role (index.ts の ROLE) */
	ownerRole?: string;
	hot?: string[];
	/** 完了した task の検査 (省略時は checking のまま。settle など別の経路が check.result を入れる) */
	check?: (task: string, answer: string) => { name: string; ok: boolean; detail?: string } | Promise<{ name: string; ok: boolean; detail?: string }>;
	rand?: () => number;
}

export interface DriverRun {
	/** 1 回回す (タイマーも呼ぶ。試験からも呼べる) */
	kick(): Promise<void>;
	/** いま走らせている run の id */
	live(): string[];
}

export const driverRunEnabled = (env: Record<string, string | undefined>, child: boolean): boolean =>
	!child && !env.PI_HARNESS_CHILD && env.PI_WORK !== "0" && env.PI_WORK_SCHEDULER === "1";

interface Handle {
	job: JobLike;
	startedAt: number;
	sent: { usd: number; tokens: number; ms: number };
	activity: number;
	aborted: boolean;
}

const POLL_MS = 2000;
const TIMEOUT_MS = 30 * 60_000;

export function registerDriverRun(pi: any, opts: DriverRunOptions): DriverRun | null {
	const env = opts.env ?? process.env;
	if (!driverRunEnabled(env, opts.child)) return null;
	const now = opts.now ?? (() => Date.now());
	const timers: RuntimeTimers = opts.timers ?? {
		setInterval: (fn, ms) => {
			const h = setInterval(fn, ms);
			(h as { unref?: () => void }).unref?.();
			return h;
		},
		clearInterval: (h) => clearInterval(h as ReturnType<typeof setInterval>),
	};
	const handles = new Map<string, Handle>();
	let ctx: any = null;
	let timer: unknown = null;
	let stopped = false;
	let reconciled = false;
	let aimd: ProviderState = aimdInit(DEFAULT_AIMD);
	let memo: Memo = emptyMemo();
	let busy: Promise<void> | null = null;
	let again = false;

	const emit = (type: EventType, data: Record<string, unknown>) => {
		try {
			opts.journal?.emit(type, data);
		} catch {
			/* 観測の失敗で本体を止めない */
		}
	};

	// Spawner: 子の起動は spawnChild の 1 本。steer・abort は既存の Job の操作
	const spawner: Spawner = {
		spawn(spec: SpawnSpec) {
			const sp = opts.spawnChild(spec.role, ctx, { cwd: ctx.cwd, role: opts.ownerRole ?? "worker" }, undefined, spec.isolation === "worktree");
			if ("error" in sp) throw new Error(sp.error);
			const h: Handle = { job: sp.job, startedAt: now(), sent: { usd: 0, tokens: 0, ms: 0 }, activity: 0, aborted: false };
			handles.set(spec.runId, h);
			void sp.job
				.run(spec.prompt, { timeoutMs: opts.timeoutMs ?? TIMEOUT_MS })
				.then(
					(r) => finished(spec.runId, h, r),
					(e) => finished(spec.runId, h, { status: "failed", answer: "", errors: [String(e?.message ?? e)], blocked: [] }),
				);
			return { runId: spec.runId, pid: sp.job.pid ?? 0 };
		},
		steer(runId, text) {
			handles.get(runId)?.job.steer(text);
		},
		abort(runId, reason) {
			const h = handles.get(runId);
			if (!h) return;
			h.aborted = true;
			emit("notice", { kind: "driver-run.abort", run: runId, reason });
			h.job.close(true);
		},
	};

	const submit = async (events: NewEvent[]): Promise<boolean> => {
		const rt = opts.runtime();
		if (events.length === 0) return true;
		if (!rt) return false;
		return (await rt.runtime.submit(events)).ok;
	};

	const toResult = (h: Handle, r: { status: string; answer: string; errors: string[]; note?: string; blocked: string[] }): RunResult => {
		const usage = { usd: h.job.cost, tokens: h.job.tokens, ms: Math.max(0, now() - h.startedAt) };
		const err = [...r.errors, ...(r.note ? [r.note] : [])].join("; ");
		if (r.status === "done") return { status: "done", answer: r.answer, usage };
		// 子の "limit" は時間切れ。ドライバの "limit" は 429 の意味なので使わず、失敗として返す (429 の文言は onFinished が見る)
		if (r.status === "closed" || r.status === "aborted") return { status: "aborted", usage, error: err || "中断" };
		if (r.status === "blocked") return { status: "failed", usage, error: `承認されなかった呼び出し: ${r.blocked.join("; ") || "不明"}` };
		return { status: "failed", usage, error: err || `status=${r.status}` };
	};

	const finished = async (runId: string, h: Handle, r: Parameters<typeof toResult>[1]): Promise<void> => {
		const rt = opts.runtime();
		handles.delete(runId);
		if (!rt) return;
		try {
			const res = toResult(h, r);
			if (res.status === "done" && opts.check) {
				const taskId = rt.runtime.state().nodes.get(runId)?.parent;
				if (taskId) res.check = await opts.check(taskId, r.answer);
			}
			const f = onFinished(rt.runtime.state(), runId, res, { now: now(), aimd, rand: (opts.rand ?? Math.random)(), holder: rt.holder });
			aimd = f.aimd;
			await submit(f.events);
			emit("run.ended", { run: runId, status: r.status, rateLimited: f.rateLimited });
		} catch {
			/* 終了後 (shutdown など) の書き込み失敗は握る。次の起動時の reconcile が lost で閉じる */
		}
		await kick();
	};

	/** 生きた子の使用量の増分と出力の有無を台帳へ (予算の steer / abort のもと) */
	const poll = async (rt: { runtime: Runtime; holder: string }): Promise<void> => {
		for (const [id, h] of [...handles]) {
			const st = rt.runtime.state();
			const u = { usd: h.job.cost, tokens: h.job.tokens, ms: Math.max(0, now() - h.startedAt) };
			const d = { usd: u.usd - h.sent.usd, tokens: u.tokens - h.sent.tokens, ms: u.ms - h.sent.ms };
			const ev = onUsage(st, id, d, rt.holder);
			if (ev.length > 0 && (await submit(ev))) h.sent = u;
			const act = h.job.calls + h.job.tokens;
			if (act !== h.activity) {
				h.activity = act;
				const o = onOutput(rt.runtime.state(), id, now(), memo);
				memo = o.memo;
				await submit(o.events);
			}
		}
	};

	const loop = async (): Promise<void> => {
		const rt = opts.runtime();
		if (stopped || !rt || !ctx || rt.runtime.mode !== "driver") return;
		if (!reconciled) {
			reconciled = true;
			await submit(reconcile(rt.runtime.state(), { live: [...handles.keys()] }, rt.holder));
		}
		await poll(rt);
		// 同時数: aimd の上限と、index.ts の子の同時数の上限 (他の子を含む枠の残り) の小さい方
		const others = Math.max(0, opts.jobs.size - handles.size);
		const slots = Math.max(0, Math.min(DEFAULT_AIMD.max, opts.jobs.max - others));
		const r = tick(rt.runtime.state(), {
			now: now(),
			res: { slots, hot: opts.hot ?? [] },
			spawner: { live: [...handles.keys()] },
			aimd,
			memo,
			holder: rt.holder,
		});
		memo = r.memo;
		// 台帳の予約が通らなければ子は起動しない (台帳に無い子を作らない)
		if (!(await submit(r.events))) return;
		for (const e of r.effects) {
			if (e.kind === "steer") spawner.steer(e.run, e.text);
			else if (e.kind === "abort") spawner.abort(e.run, e.reason);
			else if (e.kind === "spawn") {
				emit("strategy", { run: e.runId, task: e.task, strategy: e.strategy, isolation: e.isolation });
				try {
					const s = await spawner.spawn(e);
					emit("run.started", { run: e.runId, role: e.role });
					await submit(onSpawned(rt.runtime.state(), e.runId, s.pid, rt.holder));
				} catch (err) {
					const f = onFinished(rt.runtime.state(), e.runId, { status: "failed", usage: { usd: 0, tokens: 0, ms: 0 }, error: String((err as Error)?.message ?? err) }, {
						now: now(),
						aimd,
						holder: rt.holder,
					});
					await submit(f.events);
				}
			}
		}
	};

	const kick = async (): Promise<void> => {
		if (busy) {
			again = true;
			return busy;
		}
		busy = (async () => {
			try {
				do {
					again = false;
					try {
						await loop();
					} catch (e) {
						emit("notice", { kind: "driver-run.error", error: String((e as Error)?.message ?? e).slice(0, 100) });
					}
				} while (again && !stopped);
			} finally {
				busy = null;
			}
		})();
		return busy;
	};

	pi.on("session_start", async (_e: any, c: any) => {
		ctx = c;
		stopped = false;
		if (timer === null) timer = timers.setInterval(() => void kick(), opts.pollMs ?? POLL_MS);
		return undefined;
	});
	pi.on("session_shutdown", async () => {
		stopped = true;
		if (timer !== null) timers.clearInterval(timer);
		timer = null;
		for (const [id] of [...handles]) spawner.abort(id, "session_shutdown");
		return undefined;
	});

	return { kick, live: () => [...handles.keys()] };
}
