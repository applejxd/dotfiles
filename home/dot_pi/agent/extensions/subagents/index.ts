// ハーネス無しの素の pi (Windows) 用の子エージェント `task`。
// 子は読み取りツールだけ (read / grep / find / ls) の別プロセスで、shell も編集も持たない。
// 宣言は agents.json (common.toml の [pi.agents] から生成)。
// see docs/spec/pi-harness.md#windows-の子エージェント
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { spawn } from "node:child_process";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { Type } from "typebox";

const HERE = dirname(fileURLToPath(import.meta.url));
const MAX_TASK = 30000; // Windows の引数長の上限 (32767) に収める
const TIMEOUT_MS = 10 * 60 * 1000;

type Agent = { description: string; system: string; model: string | null };

function readAnswer(stdout: string): string {
	let answer = "";
	for (const line of stdout.split("\n")) {
		try {
			const e = JSON.parse(line);
			if (e.type === "message_end" && e.message?.role === "assistant") {
				answer = (e.message.content ?? []).filter((c: any) => c.type === "text").map((c: any) => c.text).join("");
			}
		} catch {}
	}
	return answer;
}

export default function (pi: ExtensionAPI) {
	// 子では登録しない (-ne で読まれないが、念のため入れ子を防ぐ)
	if (process.env.PI_SUBAGENT_CHILD === "1") return;
	const agents: Record<string, Agent> = JSON.parse(readFileSync(join(HERE, "agents.json"), "utf-8")).agents ?? {};
	const names = Object.keys(agents);
	if (names.length === 0) return;
	const catalog = names.map((n) => `- ${n}: ${agents[n].description}`).join("\n");

	pi.registerTool({
		name: "task",
		label: "task",
		description:
			"Run a read-only task in a child agent (separate pi process; tools: read, grep, find, ls only). " +
			"The child cannot see this conversation, so put everything it needs into `task`. Agents:\n" +
			catalog,
		parameters: Type.Object({
			agent: Type.Union(names.map((n) => Type.Literal(n))),
			task: Type.String({ description: "What the child should do, with all the context it needs" }),
		}),
		async execute(_id: string, params: any, signal: any, _onUpdate: any, ctx: any) {
			const agent = agents[params.agent];
			if (!agent) throw new Error(`unknown agent: ${params.agent}`);
			if (params.task.length > MAX_TASK) throw new Error(`task is too long (${params.task.length} > ${MAX_TASK})`);
			const model = agent.model ?? `${ctx.model.provider}/${ctx.model.id}`;
			// 実行中の pi と同じ cli を node で直接起動する (pi.cmd 経由のシェルを使わず、引数を壊さない)
			const args = [
				process.argv[1], "--mode", "json", "-p", "--no-session", "-ne",
				"--tools", "read,grep,find,ls", "--model", model,
				"--append-system-prompt", agent.system, params.task,
			];
			const child = spawn(process.execPath, args, {
				cwd: ctx.cwd,
				env: { ...process.env, PI_SUBAGENT_CHILD: "1" },
				stdio: ["ignore", "pipe", "pipe"],
				windowsHide: true,
			});
			const kill = () => {
				if (process.platform === "win32") spawn("taskkill", ["/pid", String(child.pid), "/T", "/F"], { stdio: "ignore" });
				else child.kill("SIGTERM");
			};
			const timer = setTimeout(kill, TIMEOUT_MS);
			signal?.addEventListener("abort", kill, { once: true });
			let out = "";
			let err = "";
			child.stdout.on("data", (b: Buffer) => (out += b.toString()));
			child.stderr.on("data", (b: Buffer) => (err = (err + b.toString()).slice(-2000)));
			const code: number = await new Promise((resolve) => {
				child.on("error", () => resolve(-1));
				child.on("close", (c: number | null) => resolve(c ?? -1));
			});
			clearTimeout(timer);
			signal?.removeEventListener("abort", kill);
			if (signal?.aborted) throw new Error("child aborted");
			const answer = readAnswer(out);
			const failed = code !== 0 || !answer;
			const text = `child ${params.agent}: ${failed ? "failed" : "completed"} (exit ${code})\n\n${answer || err}`;
			return { content: [{ type: "text", text }], details: { agent: params.agent, model }, isError: failed };
		},
	});
}
