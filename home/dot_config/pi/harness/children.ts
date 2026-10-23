// 子エージェントの RPC 保持。`pi --mode rpc` の子を job として持ち、完了後も idle で生かして
// 同じ履歴へ追加依頼できるようにする。pi の API は使わない (index.ts が呼ぶ)。
// see docs/spec/pi-guard.md#子エージェント
import { spawn, type ChildProcess } from "node:child_process";
import { randomBytes } from "node:crypto";

// 承認されなかった呼び出しの理由の先頭。子の結果から「承認待ちで未完了」を見分けるのに使う
export const NOT_APPROVED = "not approved:";

// aborted: 親が abort で今の往復だけを止めた (子は残る。履歴は途中までで、完了とは見なさない)
export type RoundStatus = "done" | "blocked" | "failed" | "limit" | "closed" | "aborted";
// 1 往復の使用量 (子の assistant メッセージの usage の合計)
export type RoundStats = { durationMs: number; calls: number; tokens: number; cost: number };
export type RoundResult = { status: RoundStatus; blocked: string[]; errors: string[]; toolCalls: string[]; answer: string; note?: string; stats: RoundStats };
// 往復ごとに記録するツール名の上限 (名前のみ。引数・出力は秘密が入りうるので持たない)
export const MAX_TOOL_CALLS = 500;

// 1 往復の最終状態。優先順: 親の停止・中断・時間切れ → 親の abort → 承認されなかった呼び出し → 最後の assistant の stopReason
export type RoundFacts = {
	closed: boolean;
	timedOut: boolean;
	interrupted?: boolean; // 親が abort を送った
	aborted: boolean; // agent_settled.aborted
	blocked: number;
	last: { stopReason?: string; errorMessage?: string } | null;
};
export function classify(f: RoundFacts): { status: RoundStatus; note?: string } {
	if (f.closed) return { status: "closed", note: "closed while running" };
	if (f.timedOut) return { status: "limit", note: "time limit" };
	if (f.interrupted) return { status: "aborted", note: "interrupted by the parent (partial work)" };
	if (f.aborted) return { status: "failed", note: "aborted" };
	if (f.blocked > 0) return { status: "blocked" };
	if (!f.last) return { status: "failed", note: "no assistant message" };
	const reason = f.last.stopReason;
	if (reason === "stop" || reason === "toolUse") return { status: "done" };
	if (reason === "length") return { status: "failed", note: "output truncated (length)" };
	if (reason === "error") return { status: "failed", note: f.last.errorMessage ?? "error" };
	if (reason === "aborted") return { status: "failed", note: "aborted" };
	return { status: "failed", note: `unknown stopReason: ${reason}` };
}

// ─── 入力 ───────────────────────────────────────────────────────────

export type BatchItem = { agent: string; task: string; model?: string };
export type TaskInput =
	| { kind: "new"; agent: string; task: string; keep: boolean; background: boolean; model?: string; todo?: number; isolation?: "worktree" }
	| { kind: "batch"; tasks: BatchItem[]; background: boolean }
	| { kind: "followup"; jobId: string; task: string; background: boolean }
	| { kind: "close"; jobId: string }
	| { kind: "status"; jobId: string }
	| { kind: "steer"; jobId: string; message: string }
	| { kind: "abort"; jobId: string }
	| { kind: "list" };

export const MAX_BATCH = 12;

// 形の排他を決める。スキーマはモデルへの説明のために 1 つの平らな object で、排他はここで確かめる
// (tool の parameters の最上位に anyOf を置くと拒む提供元がある)
export function parseTaskInput(p: any): TaskInput {
	// 指定ありとみなすのは、実質の値があるときだけ。厳格なスキーマのモデル (gpt-6-sol など) は、使わない省略可能な引数も
	// false / "" / [] / 0 で埋めて送る (B1 の F5)。それらは「指定なし」として扱う (todo の id は 1 からで、数値の 0 も埋め草と見る)
	const has = (k: string) => {
		const v = p?.[k];
		return v !== undefined && v !== null && v !== false && v !== "" && v !== 0 && !(Array.isArray(v) && v.length === 0);
	};
	const fail = (msg: string): never => {
		throw new Error(`invalid guarded_task input: ${msg}`);
	};
	const only = (allowed: string[], form: string) => {
		for (const k of Object.keys(p ?? {})) if (has(k) && !allowed.includes(k)) fail(`\`${k}\` cannot be used with ${form}`);
	};
	const bool = (k: string) => {
		if (p?.[k] !== undefined && typeof p[k] !== "boolean") fail(`\`${k}\` must be boolean`);
		return p?.[k] === true;
	};
	if (has("list")) {
		if (p.list !== true) fail("`list` must be true");
		only(["list"], "`list`");
		return { kind: "list" };
	}
	if (has("tasks")) {
		only(["tasks", "background"], "`tasks`");
		if (!Array.isArray(p.tasks) || p.tasks.length === 0) fail("`tasks` must be a non-empty array");
		if (p.tasks.length > MAX_BATCH) fail(`\`tasks\` can have at most ${MAX_BATCH} items`);
		const tasks: BatchItem[] = p.tasks.map((t: any, i: number) => {
			if (typeof t?.agent !== "string" || t.agent === "") fail(`tasks[${i}] needs \`agent\``);
			if (typeof t?.task !== "string" || t.task === "") fail(`tasks[${i}] needs \`task\``);
			if (t.model !== undefined && typeof t.model !== "string") fail(`tasks[${i}].model must be a string`);
			for (const k of Object.keys(t)) if (!["agent", "task", "model"].includes(k)) fail(`tasks[${i}] has unknown \`${k}\``);
			return { agent: t.agent, task: t.task, ...(t.model ? { model: t.model } : {}) };
		});
		return { kind: "batch", tasks, background: bool("background") };
	}
	if (has("jobId")) {
		if (typeof p.jobId !== "string" || p.jobId === "") fail("`jobId` must be a string");
		const modes = ["close", "status", "steer", "abort", "task"].filter(has);
		if (modes.length !== 1) fail(`with \`jobId\`, give exactly one of close / status / steer / abort / task (got ${modes.length === 0 ? "none" : modes.join(", ")})`);
		const mode = modes[0];
		if (mode === "close" || mode === "status" || mode === "abort") {
			if (p[mode] !== true) fail(`\`${mode}\` must be true`);
			only(["jobId", mode], `\`${mode}\``);
			return { kind: mode, jobId: p.jobId } as TaskInput;
		}
		if (mode === "steer") {
			if (typeof p.steer !== "string" || p.steer === "") fail("`steer` must be a non-empty string");
			only(["jobId", "steer"], "`steer`");
			return { kind: "steer", jobId: p.jobId, message: p.steer };
		}
		if (typeof p.task !== "string" || p.task === "") fail("follow-up needs `task`");
		only(["jobId", "task", "background"], "a follow-up");
		return { kind: "followup", jobId: p.jobId, task: p.task, background: bool("background") };
	}
	for (const k of ["close", "status", "steer", "abort"]) if (has(k)) fail(`\`${k}\` needs \`jobId\``);
	if (typeof p?.agent !== "string" || p.agent === "") fail("new task needs `agent`");
	if (typeof p?.task !== "string" || p.task === "") fail("new task needs `task`");
	if (p.keep !== undefined && typeof p.keep !== "boolean") fail("`keep` must be boolean");
	if (p.model !== undefined && typeof p.model !== "string") fail("`model` must be a string");
	if (has("todo") && (typeof p.todo !== "number" || !Number.isInteger(p.todo))) fail("`todo` must be an integer id");
	if (has("isolation")) {
		if (p.isolation !== "worktree") fail('`isolation` must be "worktree"');
		// 隔離の job は 1 往復で終わり、回収は 1 回
		if (p.keep === true) fail("`isolation` cannot be used with `keep` (an isolated job has one round and is collected once)");
		if (p.agent !== "worker") fail("`isolation` is for worker only");
	}
	return {
		kind: "new",
		agent: p.agent,
		task: p.task,
		keep: p.keep === true,
		background: bool("background"),
		...(p.model ? { model: p.model } : {}),
		...(has("todo") ? { todo: p.todo } : {}),
		...(has("isolation") ? { isolation: "worktree" as const } : {}),
	};
}

// ─── job ────────────────────────────────────────────────────────────

const UI_REQUESTS_TO_CANCEL = new Set(["confirm", "select", "input", "editor"]);
const MAX_LINE = 4 * 1024 * 1024; // 1 行の上限 (これを超える 1 行は捨てる。メモリを守る)
// 時間切れの前に子へ送る「まとめに入れ」の割合と文面
const WRAP_UP_RATIO = 0.8;
export const WRAP_UP_MESSAGE =
	"時間の上限が近づいています。いまの作業を切り上げ、ここまでに分かったことと未完了の点を、途中でもよいので返答にまとめてください。";

type Round = {
	id: string;
	blocked: string[];
	errors: string[];
	toolCalls: string[];
	last: RoundFacts["last"];
	answer: string;
	resolve: (r: RoundResult) => void;
	timer?: NodeJS.Timeout;
	warn?: NodeJS.Timeout;
	timedOut: boolean;
	aborted: boolean;
	interrupted: boolean;
	closed: boolean;
	started: boolean;
	startedAt: number;
	base: { calls: number; tokens: number; cost: number };
};

export type JobOptions = {
	id: string;
	agent: string;
	args: string[];
	cwd: string;
	env: Record<string, string | undefined>;
	// 同じ job を使ってよい持ち主か (起動時の cwd と役割)
	owner: { cwd: string; role: string };
	command?: string;
};

export type JobSnapshot = {
	id: string;
	agent: string;
	state: "idle" | "running" | "closed";
	ageMs: number;
	roundMs: number;
	lastTool: string;
	calls: number;
	tokens: number;
	cost: number;
};

export class Job {
	readonly id: string;
	readonly agent: string;
	readonly owner: { cwd: string; role: string };
	state: "idle" | "running" | "closed" = "idle";
	readonly proc: ChildProcess;
	// 子の使用量 (assistant メッセージの usage の合計) と、最後に使ったツール
	readonly createdAt = Date.now();
	lastTool = "";
	calls = 0;
	tokens = 0;
	cost = 0;
	private round: Round | null = null;
	private buf = "";
	private dropping = false;
	private seq = 0;
	private exited = false;
	private closing = false;
	private stderrTail = "";
	// 子が終了した (停止を含む) ときに呼ばれる。追加の後始末は addOnExit で足す (onExitLast は Jobs が使う。最後に呼ぶ)
	private onExitHooks: Array<() => void> = [];
	onExitLast: (() => void) | null = null;
	addOnExit(fn: () => void) {
		this.onExitHooks.push(fn);
	}
	onExit() {
		for (const fn of [...this.onExitHooks, ...(this.onExitLast ? [this.onExitLast] : [])]) {
			try {
				fn();
			} catch {}
		}
	}

	constructor(o: JobOptions) {
		this.id = o.id;
		this.agent = o.agent;
		this.owner = o.owner;
		this.proc = spawn(o.command ?? "pi", o.args, { cwd: o.cwd, env: o.env, detached: true, stdio: ["pipe", "pipe", "pipe"] });
		this.proc.stdout!.on("data", (b: Buffer) => this.feed(b.toString("utf-8")));
		this.proc.stderr!.on("data", (b: Buffer) => (this.stderrTail = (this.stderrTail + b.toString("utf-8")).slice(-2000)));
		this.proc.stdin!.on("error", () => {});
		this.proc.on("error", (e) => {
			// 起動できなかった。close が来ない場合があるので、ここで後始末まで済ませる
			this.exited = true;
			this.finish(this.round, "failed", `spawn failed: ${e.message}`);
			this.state = "closed";
			this.onExit();
		});
		this.proc.on("close", (code) => {
			this.exited = true;
			this.state = "closed";
			const note = `process exited (${code ?? "signal"})${this.stderrTail.trim() ? `: ${this.stderrTail.trim().slice(-300)}` : ""}`;
			this.finish(this.round, this.round?.closed ? "closed" : "failed", note);
			this.onExit();
		});
	}

	get pid() {
		return this.proc.pid;
	}

	snapshot(): JobSnapshot {
		const now = Date.now();
		return {
			id: this.id,
			agent: this.agent,
			state: this.state,
			ageMs: now - this.createdAt,
			roundMs: this.round ? now - this.round.startedAt : 0,
			lastTool: this.lastTool,
			calls: this.calls,
			tokens: this.tokens,
			cost: this.cost,
		};
	}

	private send(obj: unknown) {
		if (this.exited || !this.proc.stdin || this.proc.stdin.destroyed) return;
		this.proc.stdin.write(`${JSON.stringify(obj)}\n`);
	}

	// stdout は LF だけで区切る (readline は U+2028 でも切る)。壊れた行は捨てる
	private feed(chunk: string) {
		this.buf += chunk;
		let i: number;
		while ((i = this.buf.indexOf("\n")) >= 0) {
			const line = this.buf.slice(0, i);
			this.buf = this.buf.slice(i + 1);
			if (this.dropping) this.dropping = false;
			else this.onLine(line.endsWith("\r") ? line.slice(0, -1) : line);
		}
		if (this.buf.length > MAX_LINE) {
			this.buf = "";
			this.dropping = true;
		}
	}

	private onLine(line: string) {
		let e: any;
		try {
			e = JSON.parse(line);
		} catch {
			return;
		}
		// 子の UI 要求。親モデルは承認できないので、応答を要するものは全部取り消す (ask は not approved: になる)
		if (e.type === "extension_ui_request") {
			if (UI_REQUESTS_TO_CANCEL.has(e.method)) this.send({ type: "extension_ui_response", id: e.id, cancelled: true });
			return;
		}
		// 状態の集計 (往復の外でも数える)
		if (e.type === "tool_execution_start") this.lastTool = String(e.toolName ?? "");
		else if (e.type === "message_end" && e.message?.role === "assistant") {
			this.calls++;
			const u = e.message.usage;
			if (u) {
				this.tokens += Number(u.totalTokens ?? Number(u.input ?? 0) + Number(u.output ?? 0)) || 0;
				this.cost += Number(u.cost?.total ?? 0) || 0;
			}
		}
		const r = this.round;
		if (!r) return;
		if (e.type === "tool_execution_start" && r.toolCalls.length < MAX_TOOL_CALLS) r.toolCalls.push(String(e.toolName ?? ""));
		if (e.type === "response" && e.id === r.id) {
			if (e.success === false) this.finish(r, "failed", `prompt rejected: ${e.error ?? "unknown"}`);
			else if (e.data?.disposition && e.data.disposition !== "started") this.finish(r, "failed", `prompt not started (${e.data.disposition})`);
			else r.started = true;
		} else if (e.type === "tool_execution_end" && e.isError) {
			const text = (e.result?.content ?? []).map((c: any) => c.text ?? "").join("");
			(text.startsWith(NOT_APPROVED) ? r.blocked : r.errors).push(`${e.toolName}: ${text.slice(0, 300)}`);
		} else if (e.type === "message_end" && e.message?.role === "assistant") {
			r.last = { stopReason: e.message.stopReason, errorMessage: e.message.errorMessage };
			r.answer = (e.message.content ?? []).filter((c: any) => c.type === "text").map((c: any) => c.text).join("");
		} else if (e.type === "agent_settled" && r.started) {
			r.aborted = e.aborted === true;
			this.finish(r, null);
		}
	}

	private statsOf(r: Round): RoundStats {
		return {
			durationMs: Date.now() - r.startedAt,
			calls: this.calls - r.base.calls,
			tokens: this.tokens - r.base.tokens,
			cost: this.cost - r.base.cost,
		};
	}

	// 往復を 1 つ終える。status が null なら事実から判定する。done と aborted 以外は job も閉じる
	private finish(r: Round | null, status: RoundStatus | null, note?: string) {
		if (!r || this.round !== r) return;
		this.round = null;
		if (r.timer) clearTimeout(r.timer);
		if (r.warn) clearTimeout(r.warn);
		let result: { status: RoundStatus; note?: string };
		if (status === null) {
			result = classify({ closed: r.closed, timedOut: r.timedOut, interrupted: r.interrupted, aborted: r.aborted, blocked: r.blocked.length, last: r.last });
		} else {
			result = { status: r.timedOut ? "limit" : r.closed ? "closed" : status, note };
		}
		if (this.state !== "closed") this.state = "idle";
		// 時間切れ・中断は子が作業中のまま。それ以外の done でない往復は子が idle なので、stdin を閉じれば済む。
		// 親の abort は、子が止まって idle になっているので、子は残す (追加依頼で続けられる)
		if (result.status !== "done" && result.status !== "aborted") this.close(result.status === "limit" || result.status === "closed");
		r.resolve({ ...result, blocked: r.blocked, errors: r.errors, toolCalls: r.toolCalls, answer: r.answer, stats: this.statsOf(r) });
	}

	// 1 往復を実行する。呼び出しの前に state を同期で running にする (並行する呼び出しは busy)
	run(message: string, opts: { signal?: AbortSignal; timeoutMs: number; wrapUpMessage?: string }): Promise<RoundResult> {
		if (this.state === "closed") return Promise.reject(new Error("job is closed"));
		if (this.state === "running") return Promise.reject(new Error("job is busy"));
		this.state = "running";
		const id = `r${++this.seq}`;
		return new Promise<RoundResult>((resolve) => {
			const r: Round = {
				id,
				blocked: [],
				errors: [],
				toolCalls: [],
				last: null,
				answer: "",
				resolve,
				timedOut: false,
				aborted: false,
				interrupted: false,
				closed: false,
				started: false,
				startedAt: Date.now(),
				base: { calls: this.calls, tokens: this.tokens, cost: this.cost },
			};
			this.round = r;
			r.timer = setTimeout(() => {
				r.timedOut = true;
				this.finish(r, "limit", "time limit");
			}, opts.timeoutMs);
			// 上限の手前で、まとめに入るよう子へ促す (途中の結果が失われないように)
			if (opts.wrapUpMessage) {
				r.warn = setTimeout(() => {
					if (this.round === r && r.started) this.send({ type: "steer", message: opts.wrapUpMessage });
				}, Math.floor(opts.timeoutMs * WRAP_UP_RATIO));
			}
			const onAbort = () => {
				this.send({ type: "abort" });
				r.closed = true;
				this.finish(r, "closed", "aborted by the parent");
			};
			if (opts.signal?.aborted) return onAbort();
			opts.signal?.addEventListener("abort", onAbort, { once: true });
			const origResolve = r.resolve;
			r.resolve = (x) => {
				opts.signal?.removeEventListener("abort", onAbort);
				origResolve(x);
			};
			this.send({ id, type: "prompt", message });
		});
	}

	// 作業中の子へ追加の指示を送る (今のターンのツール呼び出しが終わってから、次の LLM 呼び出しの前に届く)
	steer(message: string): "queued" | "not-running" {
		if (this.state !== "running" || !this.round) return "not-running";
		this.send({ type: "steer", message });
		return "queued";
	}

	// 今の往復だけを止める。子は残り、追加依頼で続けられる。待っている run() には aborted を返す
	interrupt(): boolean {
		const r = this.round;
		if (!r || this.state !== "running") return false;
		r.interrupted = true;
		this.send({ type: "abort" });
		return true;
	}

	// 停止 (冪等)。待機中の往復には closed を返す。stdin を閉じ、3 秒で終わらなければ強制終了する。
	// force か、待機中の往復があったときは、すぐ SIGTERM を送る
	close(force = false) {
		if (this.closing || this.exited) return;
		this.closing = true;
		const wasRunning = this.round !== null;
		if (this.round) this.round.closed = true;
		this.state = "closed";
		if (wasRunning) this.finish(this.round, "closed", "closed while running");
		try {
			this.proc.stdin?.end();
		} catch {
			// stdin が既に壊れている (終了済み)
		}
		const kill = (sig: NodeJS.Signals) => {
			try {
				process.kill(-this.proc.pid!, sig);
			} catch {
				// プロセスグループが既に無い (終了済み)
			}
		};
		if (wasRunning || force) kill("SIGTERM");
		const t = setTimeout(() => !this.exited && kill("SIGKILL"), 3000);
		t.unref();
	}
}

// ─── job の一覧 ─────────────────────────────────────────────────────

export class Jobs {
	private map = new Map<string, Job>();
	constructor(readonly max: number) {}

	get size() {
		return this.map.size;
	}

	list(): Job[] {
		return [...this.map.values()];
	}

	// 上限を超えるなら null。枠は同期で確保する (並行する起動でも上限を超えない)
	// id が渡されたら使う (形式の検査は呼び出し側)。同じ id の job が既にあれば null
	create(o: Omit<JobOptions, "id"> & { id?: string }): Job | null {
		if (this.map.size >= this.max) return null;
		if (o.id !== undefined && this.map.has(o.id)) return null;
		const id = o.id ?? `job-${randomBytes(8).toString("hex")}`;
		const job = new Job({ ...o, id });
		this.map.set(id, job);
		job.onExitLast = () => {
			this.map.delete(id);
		};
		return job;
	}

	get(id: string): Job | undefined {
		return this.map.get(id);
	}

	closeAll(force = false) {
		for (const j of this.list()) j.close(force);
	}
}
