// 動いている子エージェントとバックグラウンドジョブを数えて、入力欄の下 (フッター) に出す。
// 例: `🤖 2 subagents / ⚙️ 1 jobs`。0 件の側は出さず、どちらも 0 のときは何も出さない。
// ジョブは `bg_run` / `bg_kill` / `bg_log` で扱う。コマンドは出力をログへ流して切り離して動く。
// 子の一覧は、子を起動する側 (subagents / フルガード) が globalThis.__piChildren に登録する。
// ジョブは globalThis.__piJobs に入れる。
// see docs/spec/guard/pi-guard.md#自作の拡張-todo--plan--btw
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { spawn } from "node:child_process";
import { closeSync, mkdirSync, openSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { Type } from "typebox";

type Job = { id: string; command: string; pid?: number; startedAt: number; log: string };
type Finished = { exit: number | string; endedAt: number };

const g = globalThis as { __piChildren?: Map<string, unknown>; __piJobs?: Map<string, Job> };
const jobs = (g.__piJobs ??= new Map<string, Job>());
const finished = new Map<string, Finished>();
const children = () => g.__piChildren ?? new Map<string, unknown>();

const STATUS_KEY = "activity";
const TAIL_DEFAULT = 40;
const TAIL_MAX = 200;
const NOTIFY_TAIL = 20;
const NOTIFY_TAIL_MANY = 5; // まとめて届けるときの、ジョブ 1 件あたりの末尾の行数
const NOTIFY_MAX_JOBS = 30;
const COALESCE_MS = 2500; // この間に終わったジョブは 1 通にまとめる (B1 の F3)
const killed = new Set<string>();
// 終了を LLM に知らせる前のジョブと、終了後に LLM が bg_log で読んだジョブ (読み済みは通知しない。B1 の F2)
type Done = { id: string; exit: number | string; command: string; log: string };
const pending: Done[] = [];
const seen = new Set<string>();

const secs = (ms: number) => `${Math.max(0, Math.round(ms / 1000))}s`;

// 動いている子が 3 件以下なら名前と経過時間、それより多ければ件数 (1 行に収める)
function label(): string | undefined {
	const list = [...children().values()] as { agent?: string; startedAt?: number }[];
	const j = jobs.size;
	const parts: string[] = [];
	if (list.length > 0) {
		const named = list.length <= 3 && list.every((x) => typeof x.agent === "string" && typeof x.startedAt === "number");
		parts.push(named ? `🤖 ${list.map((x) => `${x.agent} ${secs(Date.now() - (x.startedAt as number))}`).join(", ")}` : `🤖 ${list.length} subagents`);
	}
	if (j > 0) parts.push(`⚙️ ${j} jobs`);
	return parts.length ? parts.join(" / ") : undefined;
}

function killTree(pid: number | undefined): void {
	if (!pid) return;
	if (process.platform === "win32") {
		spawn("taskkill", ["/pid", String(pid), "/T", "/F"], { stdio: "ignore", windowsHide: true });
	} else {
		try {
			process.kill(-pid, "SIGTERM"); // 切り離して起動したので、プロセスグループごと止める
		} catch {
			try {
				process.kill(pid, "SIGTERM");
			} catch {}
		}
	}
}

function tail(path: string, lines: number): string {
	try {
		const all = readFileSync(path, "utf-8").split("\n");
		if (all[all.length - 1] === "") all.pop();
		return all.slice(-lines).join("\n");
	} catch {
		return "";
	}
}

const text = (t: string, isError = false) => ({ content: [{ type: "text", text: t }], details: {}, isError });

// ログの末尾と総行数 (bg_log 用)。一度の読み取りから作る (見出しと本文が別時点にならない)
function tailWithCount(path: string, lines: number): { total: number; text: string } {
	try {
		const all = readFileSync(path, "utf-8").split("\n");
		if (all[all.length - 1] === "") all.pop();
		return { total: all.length, text: all.slice(-lines).join("\n") };
	} catch {
		return { total: 0, text: "" };
	}
}

export default function (pi: ExtensionAPI) {
	let timer: ReturnType<typeof setInterval> | undefined;
	let counter = 0;
	let ui: { setStatus: (key: string, text: string | undefined) => void; notify: (m: string, t?: any) => void } | undefined;

	let last: string | undefined | null = null; // 表示が変わったときだけ出す (何も無い間も毎秒出さない。B1 の F1)
	let busy = false; // 親が作業中か (作業中は通知を溜め、終わってから読み済みを除いて届ける)
	let flushTimer: ReturnType<typeof setTimeout> | undefined;

	const compose = (batch: Done[]): string => {
		if (batch.length === 1) {
			const b = batch[0];
			return `バックグラウンドジョブ ${b.id} が終わりました (exit ${b.exit})\nコマンド: ${b.command}\n--- ログの末尾 ${NOTIFY_TAIL} 行 ---\n${tail(b.log, NOTIFY_TAIL)}`;
		}
		const shown = batch.slice(0, NOTIFY_MAX_JOBS).map((b) => {
			const out = tail(b.log, NOTIFY_TAIL_MANY).split("\n").map((l) => `    ${l}`).join("\n");
			return `- ${b.id} (exit ${b.exit}): ${b.command.slice(0, 80)}\n${out}`;
		});
		const more = batch.length > NOTIFY_MAX_JOBS ? `\n…ほか ${batch.length - NOTIFY_MAX_JOBS} 件` : "";
		return `バックグラウンドジョブ ${batch.length} 件が終わりました (各ログの末尾 ${NOTIFY_TAIL_MANY} 行。全部は bg_log)\n${shown.join("\n")}${more}`;
	};

	// LLM に知らせる。これが無いと、ジョブ待ちで止まったターンが再開しない。
	// followUp: 作業中はそのターンが終わってから、アイドルならすぐにターンを起こす。
	// 終了後に bg_log で読んだジョブは、LLM がもう知っているので除く (全部読み済みならターンを起こさない)。
	const flush = () => {
		flushTimer = undefined;
		if (busy) return; // 作業中は agent_settled まで溜める (そこで窓はもう閉じている)
		const batch = pending.splice(0).filter((p) => !seen.delete(p.id));
		if (batch.length === 0) return;
		try {
			pi.sendMessage(
				{
					customType: "bg-job-finished",
					content: compose(batch),
					display: true,
					details: { id: batch[0].id, exit: batch[0].exit, ids: batch.map((b) => b.id) },
				},
				{ triggerTurn: true, deliverAs: "followUp" },
			);
		} catch {}
	};
	const schedule = () => {
		flushTimer ??= setTimeout(flush, COALESCE_MS);
		flushTimer.unref?.();
	};
	pi.on("agent_start", async () => {
		busy = true;
	});
	// 作業中の終わりは agent_end ではなく agent_settled (自動再試行・圧縮・続行が agent_end の後に続くことがある)。
	// まとめる窓がまだ開いていれば (タイマーが残っていれば) タイマーに任せ、窓と settled の両方を満たしてから送る。
	pi.on("agent_settled", async () => {
		busy = false;
		if (pending.length > 0 && !flushTimer) flush();
	});

	const refresh = () => {
		try {
			const now = label();
			if (now === last) return;
			last = now;
			ui?.setStatus(STATUS_KEY, now);
		} catch {}
	};

	pi.on("session_start", async (_event: any, ctx: any) => {
		ui = undefined;
		last = null;
		busy = false;
		if (!ctx.hasUI) return;
		ui = ctx.ui;
		timer ??= setInterval(refresh, 1000);
		timer.unref?.();
		refresh();
	});

	// 終わるときは、動いているジョブも止める (切り離したままにしない)
	pi.on("session_shutdown", async () => {
		if (flushTimer) clearTimeout(flushTimer);
		flushTimer = undefined;
		pending.length = 0;
		seen.clear();
		if (timer) clearInterval(timer);
		timer = undefined;
		for (const job of jobs.values()) killTree(job.pid);
		jobs.clear();
		try {
			ui?.setStatus(STATUS_KEY, undefined);
		} catch {}
		ui = undefined; // 停止後に遅れて来るコールバックが古い UI へ書かないようにする
		last = null;
	});

	pi.registerTool({
		name: "bg_run",
		label: "bg_run",
		// promptSnippet が無いと Available tools に出ない
		promptSnippet: "Start a long-running or waiting command (server, watcher, build) in the background and get a job id",
		promptGuidelines: ["Use bg_run instead of bash for commands that run long or wait; check them with bg_log and stop them with bg_kill."],
		description:
			"Start a shell command in the background and return immediately with a job id. " +
			"Output goes to a log file. Use bg_log to read it and bg_kill to stop it. " +
			"Use for long-running commands (servers, watchers, builds); not for quick commands.",
		parameters: Type.Object({
			command: Type.String({ description: "Shell command to run" }),
		}),
		async execute(_id: string, params: any, _signal: any, _onUpdate: any, ctx: any) {
			const id = `j${++counter}`;
			const dir = join(tmpdir(), "pi-jobs");
			mkdirSync(dir, { recursive: true });
			const log = join(dir, `${process.pid}-${id}.log`);
			const fd = openSync(log, "a");
			const child = spawn(params.command, {
				cwd: ctx.cwd,
				shell: true,
				detached: process.platform !== "win32",
				stdio: ["ignore", fd, fd],
				windowsHide: true,
			});
			closeSync(fd);
			const job: Job = { id, command: params.command, pid: child.pid, startedAt: Date.now(), log };
			jobs.set(id, job);
			refresh();
			child.on("error", (e: Error) => {
				jobs.delete(id);
				finished.set(id, { exit: `error: ${e.message}`, endedAt: Date.now() });
				refresh();
			});
			child.on("close", (code: number | null, signal: string | null) => {
				if (!jobs.delete(id)) return;
				const exit = code ?? signal ?? -1;
				finished.set(id, { exit, endedAt: Date.now() });
				refresh();
				try {
					ui?.notify(`job ${id} 終了 (exit ${exit}): ${params.command.slice(0, 60)}`, code === 0 ? "info" : "warning");
				} catch {}
				// bg_kill で止めたときは LLM 自身が知っているので通知しない。それ以外は、短い間に終わった分をまとめて届ける (flush)
				if (killed.delete(id)) return;
				pending.push({ id, exit, command: params.command, log });
				schedule();
			});
			return text(`started ${id} (pid ${child.pid})\nread its output with bg_log (the log file itself is not readable by other tools)`);
		},
	});

	pi.registerTool({
		name: "bg_log",
		label: "bg_log",
		promptSnippet: "Show the state and log tail of a background job by id (no id: list jobs)",
		description: "Show the state of a background job and the tail of its log (the log file itself cannot be read with read or bash; use this). Without an id, list all jobs.",
		parameters: Type.Object({
			id: Type.Optional(Type.String({ description: "Job id returned by bg_run" })),
			lines: Type.Optional(Type.Number({ description: `Tail lines (default ${TAIL_DEFAULT}, max ${TAIL_MAX})` })),
		}),
		async execute(_id: string, params: any) {
			if (!params.id) {
				const rows = [
					...[...jobs.values()].map((j) => `${j.id}\trunning\t${j.command.slice(0, 80)}`),
					...[...finished.entries()].map(([id, f]) => `${id}\texit ${f.exit}`),
				];
				return text(rows.length ? rows.join("\n") : "no jobs");
			}
			const lines = Math.min(Math.max(Math.floor(params.lines ?? TAIL_DEFAULT), 1), TAIL_MAX);
			const job = jobs.get(params.id);
			const done = finished.get(params.id);
			if (!job && !done) return text(`unknown job: ${params.id}`, true);
			if (!job && pending.some((p) => p.id === params.id)) seen.add(params.id); // 通知待ちのジョブを終了後に読んだ (通知はもう要らない)
			const log = job?.log ?? join(tmpdir(), "pi-jobs", `${process.pid}-${params.id}.log`);
			const state = job ? `running (${Math.floor((Date.now() - job.startedAt) / 1000)}s)` : `finished (exit ${done?.exit})`;
			const snapshot = tailWithCount(log, lines);
			return text(`${params.id}: ${state}\n--- tail ${lines} of ${snapshot.total} lines ---\n${snapshot.text}`);
		},
	});

	pi.registerTool({
		name: "bg_kill",
		label: "bg_kill",
		promptSnippet: "Stop a background job by id",
		description: "Stop a running background job (kills its process tree).",
		parameters: Type.Object({ id: Type.String({ description: "Job id returned by bg_run" }) }),
		async execute(_id: string, params: any) {
			const job = jobs.get(params.id);
			if (!job) return text(`not running: ${params.id}`, true);
			killTree(job.pid);
			killed.add(params.id);
			return text(`stop requested: ${params.id}`);
		},
	});
}
