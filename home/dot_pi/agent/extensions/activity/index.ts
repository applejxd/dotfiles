// 動いている子エージェントとバックグラウンドジョブを数えて、入力欄の下 (フッター) に出す。
// 例: `🤖 2 subagents / ⚙️ 1 jobs`。0 件の側は出さず、どちらも 0 のときは何も出さない。
// ジョブは `bg_run` / `bg_kill` / `bg_log` で扱う。コマンドは出力をログへ流して切り離して動く。
// 子の一覧は、子を起動する側 (subagents / フルガード) が globalThis.__piChildren に登録する。
// ジョブは globalThis.__piJobs に入れる。
// see docs/spec/pi-guard.md#自作の拡張-todo--plan--btw
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
const killed = new Set<string>();

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

export default function (pi: ExtensionAPI) {
	let timer: ReturnType<typeof setInterval> | undefined;
	let counter = 0;
	let ui: { setStatus: (key: string, text: string | undefined) => void; notify: (m: string, t?: any) => void } | undefined;

	const refresh = () => {
		try {
			ui?.setStatus(STATUS_KEY, label());
		} catch {}
	};

	pi.on("session_start", async (_event: any, ctx: any) => {
		if (!ctx.hasUI) return;
		ui = ctx.ui;
		timer ??= setInterval(refresh, 1000);
		timer.unref?.();
		refresh();
	});

	// 終わるときは、動いているジョブも止める (切り離したままにしない)
	pi.on("session_shutdown", async () => {
		if (timer) clearInterval(timer);
		timer = undefined;
		for (const job of jobs.values()) killTree(job.pid);
		jobs.clear();
		try {
			ui?.setStatus(STATUS_KEY, undefined);
		} catch {}
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
				// LLM にも知らせる。これが無いと、ジョブ待ちで止まったターンが再開しない。
				// followUp: 作業中はそのターンが終わってから、アイドルならすぐにターンを起こす。
				// bg_kill で止めたときは LLM 自身が知っているので送らない。
				if (killed.delete(id)) return;
				try {
					pi.sendMessage(
						{
							customType: "bg-job-finished",
							content: `バックグラウンドジョブ ${id} が終わりました (exit ${exit})\nコマンド: ${params.command}\n--- ログの末尾 ${NOTIFY_TAIL} 行 ---\n${tail(log, NOTIFY_TAIL)}`,
							display: true,
							details: { id, exit },
						},
						{ triggerTurn: true, deliverAs: "followUp" },
					);
				} catch {}
			});
			return text(`started ${id} (pid ${child.pid})\nlog: ${log}`);
		},
	});

	pi.registerTool({
		name: "bg_log",
		label: "bg_log",
		promptSnippet: "Show the state and log tail of a background job by id (no id: list jobs)",
		description: "Show the state of a background job and the tail of its log. Without an id, list all jobs.",
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
			const log = job?.log ?? join(tmpdir(), "pi-jobs", `${process.pid}-${params.id}.log`);
			const state = job ? `running (${Math.floor((Date.now() - job.startedAt) / 1000)}s)` : `finished (exit ${done?.exit})`;
			return text(`${params.id}: ${state}\n--- tail ${lines} ---\n${tail(log, lines)}`);
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
