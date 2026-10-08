// CHG-0019 段 3 の試作用ハーネス。組み込みのツールの代わりに bash / read を登録し、
// 判定 API（policy.py）の結果を tool_call と execute() の両方で確かめる。
// see docs/research/agents/pi-harness-spike.md
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import {
	createBashToolDefinition,
	createEditToolDefinition,
	createFindToolDefinition,
	createGrepToolDefinition,
	createLsToolDefinition,
	createReadToolDefinition,
	createWriteToolDefinition,
} from "@earendil-works/pi-coding-agent";
import { spawn, spawnSync } from "node:child_process";
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { Type } from "typebox";

type Decision = { decision: "allow" | "ask" | "deny"; reason: string };

const HERE = dirname(fileURLToPath(import.meta.url));
const POLICY = process.env.SPIKE_POLICY ?? join(HERE, "..", "policy.py");

export function decide(tool: string, input: unknown, cwd: string): Decision {
	const r = spawnSync("python3", [POLICY], {
		input: JSON.stringify({ tool, input, cwd }),
		encoding: "utf-8",
		timeout: 3000,
	});
	if (r.error) return { decision: "deny", reason: `policy error: ${r.error.message}` };
	if (r.status !== 0) return { decision: "deny", reason: `policy exited ${r.status}` };
	try {
		const out = JSON.parse(r.stdout);
		if (["allow", "ask", "deny"].includes(out?.decision) && typeof out?.reason === "string") return out;
	} catch {}
	return { decision: "deny", reason: `policy returned invalid output: ${JSON.stringify(r.stdout.slice(0, 80))}` };
}

const approved = new Map<string, string>();

// 確認は 1 件ずつ出す。TUI の confirm は 1 枠を共有し、後の確認が先の確認を置き換えるため。
// SPIKE_NO_QUEUE=1 で順番待ちを外す（対照）
let confirmQueue: Promise<unknown> = Promise.resolve();
function confirmInOrder(ctx: any, title: string, body: string): Promise<boolean> {
	if (process.env.SPIKE_NO_QUEUE === "1") return ctx.ui.confirm(title, body, { signal: ctx.signal });
	const run = confirmQueue.then(() =>
		ctx.signal?.aborted ? false : ctx.ui.confirm(title, body, { signal: ctx.signal }),
	);
	confirmQueue = run.catch(() => undefined);
	return run.then((v: unknown) => v === true).catch(() => false);
}

// 伏字化。SPIKE_REDACT_FAULT=1 で伏字化が例外を投げる（失敗時の倒れ方を見る）
const RULES: [RegExp, string][] = [
	[/(?<=SPIKE_TOKEN=)\S+/gi, "[伏字:token]"],
	[/ghp_[A-Za-z0-9]{20,}/g, "[伏字:github]"],
];
function redactText(text: string): string {
	if (process.env.SPIKE_REDACT_FAULT === "1") throw new Error("redaction fault (spike)");
	return RULES.reduce((t, [re, to]) => t.replace(re, to), text);
}
function redactValue(v: any): any {
	if (typeof v === "string") return redactText(v);
	if (Array.isArray(v)) return v.map(redactValue);
	if (v && typeof v === "object") return Object.fromEntries(Object.entries(v).map(([k, x]) => [k, redactValue(x)]));
	return v;
}
function redactResult(r: any): any {
	if (!r) return r;
	return {
		...r,
		content: redactValue(r.content),
		// details はモデルへ送られないが、セッション・イベント・画面には残る（truncation.content に生の出力）
		...(r.details !== undefined ? { details: redactValue(r.details) } : {}),
		...(r.structuredContent !== undefined ? { structuredContent: redactValue(r.structuredContent) } : {}),
	};
}
function redactSpillFile(path: unknown) {
	if (typeof path !== "string") return;
	writeFileSync(path, redactText(readFileSync(path, "utf-8")));
}

export default function (pi: ExtensionAPI) {
	pi.on("tool_call", async (event, ctx) => {
		const d = decide(event.toolName.replace(/^guarded_/, ""), event.input, ctx.cwd);
		if (d.decision === "deny") return { block: true, reason: d.reason };
		if (d.decision === "ask" && process.env.SPIKE_BYPASS === "1") {
			approved.set(event.toolCallId, JSON.stringify(event.input));
			return undefined;
		}
		if (d.decision === "ask") {
			const ok = ctx.hasUI && (await confirmInOrder(ctx, "Allow?", `${event.toolName}: ${JSON.stringify(event.input)}`));
			if (!ok) return { block: true, reason: `not approved: ${d.reason}` };
			approved.set(event.toolCallId, JSON.stringify(event.input));
		}
		return undefined;
	});

	// 組み込みと同じ名前で登録すると、/reload でハーネスが抜けたときに組み込みが同じ名前で戻る
	// （試作の結果 1d）。SPIKE_RENAME=1 で別名にする
	const rename = process.env.SPIKE_RENAME === "1";
	const guard = (name: string, def: any) => {
		pi.registerTool({
			...def,
			name: rename ? `guarded_${name}` : name,
			async execute(toolCallId: string, params: any, signal: any, onUpdate: any, ctx: any) {
				const d = decide(name, params, ctx.cwd);
				const wasApproved = approved.get(toolCallId) === JSON.stringify(params);
				approved.delete(toolCallId);
				if (d.decision === "deny" || (d.decision === "ask" && !wasApproved)) {
					throw new Error(`harness execute-check rejected: ${d.decision}: ${d.reason}`);
				}
				// read などに掛けると、伏せた本文を元に edit されてファイルへ伏字が書き込まれる（今の OpenCode と同じ判断）
				if (name !== "bash") return def.execute(toolCallId, params, signal, onUpdate, ctx);
				// 途中経過・最終結果・退避ファイルの全部に伏字化を掛ける。伏字化が例外を投げたら
				// execute() ごと失敗させ、生の出力を返さない
				const safeUpdate = onUpdate && ((partial: any) => onUpdate(redactResult(partial)));
				const result = await def.execute(toolCallId, params, signal, safeUpdate, ctx);
				redactSpillFile(result?.details?.fullOutputPath);
				return redactResult(result);
			},
		});
	};
	const cwd = process.cwd();
	guard("bash", createBashToolDefinition(cwd));
	guard("read", createReadToolDefinition(cwd));
	guard("edit", createEditToolDefinition(cwd));
	guard("write", createWriteToolDefinition(cwd));
	guard("grep", createGrepToolDefinition(cwd));
	guard("find", createFindToolDefinition(cwd));
	guard("ls", createLsToolDefinition(cwd));

	// 子エージェント。子は同じハーネスで別の pi プロセスとして動き、親のモード（bypass）を環境変数で受け取る。
	// 子に UI は無いので、子の ask は拒否になる。拒否があれば「承認待ちで未完了」として親へ返す
	if (process.env.SPIKE_CHILD !== "1") {
		pi.registerTool({
			name: rename ? "guarded_task" : "task",
			label: "task",
			description: "Run a sub-task in a child agent with the same guard. Returns its final answer.",
			parameters: Type.Object({ task: Type.String({ description: "What the child should do" }) }),
			async execute(_toolCallId: string, params: any, signal: any, _onUpdate: any, ctx: any) {
				const args = ["--mode", "json", "-p", "--no-session", "-nbt", "-ne", "-e", HERE];
				for (const ext of (process.env.SPIKE_CHILD_EXTRA_EXT ?? "").split(",").filter(Boolean)) args.push("-e", ext);
				args.push("--model", `${ctx.model.provider}/${ctx.model.id}`, params.task);
				const env = { ...process.env, SPIKE_CHILD: "1", FAUX_TOOL_CALLS: process.env.SPIKE_CHILD_CALLS ?? "[]" };
				const child = spawn("pi", args, { cwd: ctx.cwd, env, detached: true, stdio: ["ignore", "pipe", "pipe"] });
				const kill = () => {
					try {
						process.kill(-child.pid!, "SIGTERM");
					} catch {}
				};
				signal?.addEventListener("abort", kill, { once: true });
				let out = "";
				child.stdout.on("data", (b: Buffer) => (out += b.toString()));
				const code: number = await new Promise((resolve) => child.on("close", (c: number) => resolve(c ?? -1)));
				signal?.removeEventListener("abort", kill);
				if (signal?.aborted) throw new Error("child aborted");
				const blocked: string[] = [];
				const errors: string[] = [];
				let answer = "";
				for (const line of out.split("\n")) {
					let e: any;
					try {
						e = JSON.parse(line);
					} catch {
						continue;
					}
					if (e.type === "tool_execution_end" && e.isError) {
						const text = (e.result?.content ?? []).map((c: any) => c.text ?? "").join("");
						(text.startsWith("not approved:") ? blocked : errors).push(`${e.toolName}: ${text.slice(0, 200)}`);
					}
					if (e.type === "message_end" && e.message?.role === "assistant") {
						answer = (e.message.content ?? []).filter((c: any) => c.type === "text").map((c: any) => c.text).join("");
					}
				}
				const status = code !== 0 ? "failed" : blocked.length > 0 ? "blocked" : "completed";
				const lines = [
					`child status: ${status} (exit ${code})`,
					...blocked.map((b) => `- not approved (needs the user): ${b}`),
					...errors.map((b) => `- tool error: ${b}`),
					answer,
				];
				return { content: [{ type: "text", text: lines.join("\n") }], details: { status, blocked, errors }, isError: status !== "completed" };
			},
		});
	}

	// MCP はハーネスから登録する。ハーネスが抜ければ登録も消える（登録は保存されない。docs/extensions.md）
	if (process.env.SPIKE_MCP_SERVER) {
		pi.registerMcpServer("spike", { command: "python3", args: [process.env.SPIKE_MCP_SERVER], exposure: "direct" } as any);
	}

	// ハーネスが持たないツール（MCP・codemode など）の結果。tool_result の例外は無視されて
	// 生の結果が残るので、ここでは投げずに結果ごと伏せる
	pi.on("tool_result", async (event) => {
		if (event.toolName.startsWith("guarded_")) return undefined;
		try {
			return redactResult({ content: event.content, details: event.details, structuredContent: event.structuredContent });
		} catch (e) {
			const text = `[伏字化に失敗したので結果を伏せた: ${(e as Error).message}]`;
			return { content: [{ type: "text", text }], structuredContent: { withheld: text }, isError: true };
		}
	});

	// 既定の圧縮は read / edit / write の名前でファイルの操作を拾うので、別名の分を足す。
	// preparation は既定の要約にそのまま渡る（dist/core/agent-session.js の compact()）
	if (rename) {
		pi.on("session_before_compact", async (event) => {
			const ops = event.preparation.fileOps;
			const target: Record<string, Set<string>> = {
				guarded_read: ops.read,
				guarded_edit: ops.edited,
				guarded_write: ops.written,
			};
			const messages = [...event.preparation.messagesToSummarize, ...event.preparation.turnPrefixMessages];
			for (const m of messages as any[]) {
				if (m?.role !== "assistant" || !Array.isArray(m.content)) continue;
				for (const b of m.content) {
					const set = b?.type === "toolCall" ? target[b.name] : undefined;
					if (set && typeof b.arguments?.path === "string") set.add(b.arguments.path);
				}
			}
			return undefined;
		});
	}
}
