// pi のフルガード。組み込みのツールの代わりに guarded_* のツールを登録し、判定器 (./judge) で
// 実行してよいかを決める。起動は `pi -nbt -ne -e ~/.config/pi/harness`。
// see docs/spec/pi-guard.md
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import {
	compact,
	createBashToolDefinition,
	createEditToolDefinition,
	createFindToolDefinition,
	createGrepToolDefinition,
	createLsToolDefinition,
	createReadToolDefinition,
	createWriteToolDefinition,
	withFileMutationQueue,
} from "@earendil-works/pi-coding-agent";
import { spawn, spawnSync } from "node:child_process";
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, isAbsolute, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { Type } from "typebox";
import { BG_RUN, createCallDecider, type Decision } from "./judge/call.ts";
import { readBoundaryEnv, runCanary } from "./canary.ts";
import { Jobs, NOT_APPROVED, parseTaskInput, type Job } from "./children.ts";
import { createRedactor } from "./redact.ts";

const HERE = dirname(fileURLToPath(import.meta.url));
// 組み込みと同じ名前にしないこと。/reload でフルガードが抜けたとき、組み込みが同じ名前で戻って
// 判定なしに動く (docs/research/agents/pi-harness-spike.md の E1)
const PREFIX = "guarded_";
const TOOLS = ["bash", "read", "edit", "write", "grep", "find", "ls"] as const;
// 起動時の値は pis の --bypass。起動後は /bypass (利用者の入力欄からだけ。ツールは作らない) で切り替える
let bypass = process.env.PI_HARNESS_BYPASS === "1";
// サンドボックスの内側と期待されているか (PI_HARNESS_BOUNDARY=1)。これは期待にすぎない。
// 期待されているときは、カナリアで実測し、効いていなければ起動を止める。緩和 (BOUNDARY) は実測が通ったときだけ。
const BOUNDARY_ENV = readBoundaryEnv(process.env);
const NO_SANDBOX = process.env.PI_HARNESS_NO_SANDBOX === "1";
// 子エージェントとして起動されたか。子では guarded_task を登録しない (入れ子にしない)
const CHILD = process.env.PI_HARNESS_CHILD === "1";

// rules.json が読めなければ読み込みごと失敗させる。起動は止まり、/reload ではツールが無くなる
const rules = JSON.parse(readFileSync(join(HERE, "rules.json"), "utf-8"));
if (!rules.judge?.common || !rules.judge?.tables || !rules.redact || !Array.isArray(rules.redact.rule)) {
	throw new Error("rules.json に judge / redact が無い (chezmoi apply で作り直す)");
}
const AGENT_ENV: Record<string, string> = rules.agent_env ?? {};
// 役割。pis の --role / PI_HARNESS_ROLE が優先し、無ければ [pi] default_role
if (typeof rules.default_role !== "string") throw new Error("rules.json に default_role が無い (chezmoi apply で作り直す)");
const ROLE: string = process.env.PI_HARNESS_ROLE || rules.default_role;

let BOUNDARY = false;
if (BOUNDARY_ENV) {
	const canary = runCanary(BOUNDARY_ENV.spec);
	if (!canary.ok) throw new Error(`サンドボックスを確認できないので起動しない: ${canary.reason}`);
	BOUNDARY = true;
}

// 伏字化 (redact.ts)
const { redactText, redactResult, deniedPathIn, withheld } = createRedactor(rules.redact);

// ─── 確認画面の補助 ─────────────────────────────────────────────────

// git commit の件名と本文を、確認画面へ出す。同じ置き場の純関数 (commit-message.js) を使う。
// 飾りなので、読み込めなくてもフルガードは止めない (出さないだけ)。
let commitPreview: ((command: string, opts?: unknown) => any) | null = null;
async function loadCommitPreview() {
	if (!rules.commit_preview) return;
	try {
		const url = pathToFileURL(join(HERE, "commit-message.js")).href;
		commitPreview = (await import(url)).commitPreview;
	} catch {}
}

function describeCall(tool: string, input: any): string {
	let text = tool === "bash" ? String(input?.command ?? "") : `${tool}: ${JSON.stringify(input)}`;
	const p = tool === "bash" && commitPreview ? commitPreview(text, rules.commit_preview) : null;
	if (p) {
		const lines = [`件名: ${p.subject}`, ...p.body.map((l: string) => `  ${l}`)];
		if (p.extra) lines.push(p.extra);
		if (p.added) lines.push(p.added);
		text = `${text}\n\n${lines.join("\n")}`;
	}
	return text;
}

// ─── 圧縮の指示 ─────────────────────────────────────────────────────

// pi の既定の要約 (Goal / Constraints / Progress / Key Decisions / Next Steps / Critical Context) に、
// 引き継ぎで外すと復帰できなくなる点を足す (旧 checkpoint の雛形の要点)。
const COMPACT_INSTRUCTIONS = [
	"【圧縮の指示】この要約は、前任者の会話を持たない読み手が作業を再開するために使う。",
	"- Next Steps は「何を」だけでなく「どうやって」まで書く (手順と合格条件)。",
	"- 略語・独自の用語は展開するか、参照先 (パス・文書名) を示す。",
	"- 未作成の文書を参照に挙げるときは「未作成」と明記する。",
	"- 利用者が指定した制約と、却下済みの方針を 1 行ずつ残す。",
].join("\n");

// ─── 判定 ───────────────────────────────────────────────────────────

// 判定器を呼ぶ口 (bg_run は bash と同じ判定、bg_log / bg_kill は allow。judge/call.ts)。
// 判定器は呼び出しごとに文脈を作り直す。ここで持つのは読み込んだ設定だけ
const callDecider = createCallDecider({
	judge: rules.judge,
	profileTools: rules.profile_tools ?? {},
	role: ROLE,
	bypass: () => bypass,
	boundary: BOUNDARY,
	allowed: BOUNDARY_ENV?.allowed,
});

export function decide(tool: string, input: unknown, cwd: string): Decision {
	return callDecider(tool, input, cwd);
}

// tool_call で判定した入力と結果。execute() で同じ入力なら判定を使い回す (判定 1 回 0.1 秒ほど)。
// 入力が書き換わっていれば判定し直す
const decided = new Map<string, { input: string; decision: Decision; approved: boolean }>();

// 確認は 1 件ずつ出す。TUI の confirm は 1 枠を共有し、後の確認が先の確認を置き換える
// (codemode の中で並べた呼び出しで先の確認が永久に止まった。spike の E3)
let confirmQueue: Promise<unknown> = Promise.resolve();
// TUI 以外 (RPC など) は、クライアントが確認に応えないと永久に待つので期限を付ける (期限が来たら拒否)
const CONFIRM_TIMEOUT_MS = 5 * 60 * 1000;
function confirmInOrder(ctx: any, title: string, body: string): Promise<boolean> {
	const timeout = ctx.mode === "tui" ? undefined : CONFIRM_TIMEOUT_MS;
	const run = confirmQueue.then(() =>
		ctx.signal?.aborted ? false : ctx.ui.confirm(title, body, { signal: ctx.signal, timeout }),
	);
	confirmQueue = run.catch(() => undefined);
	return run.then((v: unknown) => v === true).catch(() => false);
}

function baseName(toolName: string): string {
	return toolName.startsWith(PREFIX) ? toolName.slice(PREFIX.length) : toolName;
}

// ─── 登録 ───────────────────────────────────────────────────────────

export default async function (pi: ExtensionAPI) {
	await loadCommitPreview();
	// 状態の表示 (安全の根拠ではなく、いまどちらで動いているかの目印)
	const showBypass = (ctx: any) => {
		if (ctx.hasUI) ctx.ui.setStatus("bypass", bypass ? ctx.ui.theme.fg("warning", "⚡ bypass") : undefined);
	};
	// セッションの終了・切り替え・/reload で、保持している子を全部止める
	pi.on("session_shutdown", async () => jobs.closeAll());
	pi.on("session_start", async (_event, ctx) => {
		if (!ctx.hasUI) return;
		showBypass(ctx);
		if (BOUNDARY) ctx.ui.setStatus("sandbox", "🔒 サンドボックス");
		else if (NO_SANDBOX) ctx.ui.setStatus("sandbox", "⚠ サンドボックス無し");
	});
	// 利用者専用の bypass 切り替え。モデルが呼べるツールは作らない。セッションには残さない
	// see docs/spec/pi-guard.md#bypass-の切り替え
	pi.registerCommand("bypass", {
		description: "bypass (ask を確認なしで通す) の切り替え: /bypass [on|off]",
		handler: async (args: string, ctx: any) => {
			const arg = String(args ?? "").trim();
			if (arg !== "" && arg !== "on" && arg !== "off") {
				ctx.ui?.notify?.("使い方: /bypass [on|off]", "warning");
				return;
			}
			const want = arg === "on" ? true : arg === "off" ? false : !bypass;
			if (want === bypass) {
				ctx.ui?.notify?.(`bypass はすでに ${bypass ? "ON" : "OFF"}`, "info");
				return;
			}
			if (want) {
				// ON にできるのは確認を出せるときだけ
				if (!ctx.hasUI) return;
				const body = BOUNDARY
					? "ask の操作 (git commit や MCP など) を確認なしで通します。deny とサンドボックスは有効のまま。"
					: "サンドボックスが無いまま、ask の操作 (git commit や未知の shell や MCP など) を確認なしで通します。deny だけが守りです。";
				if ((await ctx.ui.confirm("bypass を有効にしますか？", body)) !== true) return;
			}
			bypass = want;
			// 前の設定で下した判定を execute() で使い回さない
			decided.clear();
			// 起動時の bypass を持つ子に、権限を持ち越させない
			jobs.closeAll();
			showBypass(ctx);
			ctx.ui?.notify?.(`bypass を ${bypass ? "ON" : "OFF"} にした`, bypass ? "warning" : "info");
		},
	});
	pi.on("tool_call", async (event, ctx) => {
		const tool = baseName(event.toolName);
		const d = decide(tool, event.input, ctx.cwd);
		const input = JSON.stringify(event.input);
		if (d.decision === "deny") return { block: true, reason: d.reason };
		if (d.decision === "ask") {
			const ok =
				ctx.hasUI &&
				(await confirmInOrder(ctx, "実行してよいですか？", `${tool === BG_RUN ? "バックグラウンドで実行:\n" : ""}${describeCall(tool === BG_RUN ? "bash" : tool, event.input)}\n\n理由: ${d.reason}`));
			if (!ok) return { block: true, reason: `${NOT_APPROVED} ${d.reason}` };
			decided.set(event.toolCallId, { input, decision: d, approved: true });
			return undefined;
		}
		decided.set(event.toolCallId, { input, decision: d, approved: false });
		return undefined;
	});

	// フルガードが持たないツール (MCP など) の結果。tool_result の例外は無視されて生の結果が残るので、
	// ここでは投げずに結果ごと伏せる
	pi.on("tool_result", async (event) => {
		if (event.toolName.startsWith(PREFIX)) return undefined;
		try {
			return redactResult({ content: event.content, details: event.details, structuredContent: event.structuredContent });
		} catch (e) {
			const text = `[伏字化に失敗したので結果を伏せた: ${(e as Error).message}]`;
			return { content: [{ type: "text", text }], structuredContent: { withheld: text }, isError: true };
		}
	});

	const cwd = process.cwd();
	const definitions: Record<(typeof TOOLS)[number], any> = {
		bash: createBashToolDefinition(cwd, {
			spawnHook: (spawn: any) => ({ ...spawn, env: { ...AGENT_ENV, ...spawn.env } }),
		}),
		read: createReadToolDefinition(cwd),
		edit: createEditToolDefinition(cwd),
		write: createWriteToolDefinition(cwd),
		grep: createGrepToolDefinition(cwd),
		find: createFindToolDefinition(cwd),
		ls: createLsToolDefinition(cwd),
	};
	// 役割に無いツールは登録しない (モデルに見せない)。判定は判定器が別に行う。
	// 役割が rules.json に無ければ何も登録しない
	const roleTools: string[] = rules.profile_tools?.[ROLE] ?? [];
	for (const tool of TOOLS) {
		if (!roleTools.includes(tool)) continue;
		const def = definitions[tool];
		pi.registerTool({
			...def,
			name: `${PREFIX}${tool}`,
			// 最終の判定はここ。tool_call の後に別の拡張が入力を書き換えても、ここで止まる (spike の E1)
			async execute(toolCallId: string, params: any, signal: any, onUpdate: any, ctx: any) {
				const seen = decided.get(toolCallId);
				decided.delete(toolCallId);
				const input = JSON.stringify(params);
				const d = seen && seen.input === input ? seen.decision : decide(tool, params, ctx.cwd);
				const approved = seen?.approved === true && seen.input === input;
				if (d.decision === "deny" || (d.decision === "ask" && !approved)) {
					throw new Error(`実行前の判定で止めた: ${d.decision}: ${d.reason}`);
				}
				// edit / write の後に整形する (Claude / Copilot の PostToolUse hook と同じスクリプト)
				if (tool === "edit" || tool === "write") {
					const result = await def.execute(toolCallId, params, signal, onUpdate, ctx);
					return await formatAfterEdit(result, params?.path, ctx.cwd);
				}
				// read などに伏字化を掛けると、伏せた本文を元に edit されてファイルへ伏字が書き込まれる
				if (tool !== "bash") return def.execute(toolCallId, params, signal, onUpdate, ctx);
				const hit = deniedPathIn(String(params?.command ?? ""));
				if (hit) return withheld(hit);
				// 途中経過・最終結果・退避ファイルを伏せる。伏字化が例外を投げたら execute() ごと失敗させる
				const safeUpdate = onUpdate && ((partial: any) => onUpdate(redactResult(partial)));
				const result = await def.execute(toolCallId, params, signal, safeUpdate, ctx);
				const spill = result?.details?.fullOutputPath;
				if (typeof spill === "string") writeFileSync(spill, redactText(readFileSync(spill, "utf-8")));
				return redactResult(result);
			},
		});
	}

	// MCP はフルガードから登録する。フルガードが抜ければ登録も消える (spike の E3)
	for (const server of rules.mcp ?? []) pi.registerMcpServer(server.name, server.config);

	const agents: Record<string, any> = rules.agents ?? {};
	if (!CHILD && roleTools.includes("task") && Object.keys(agents).length > 0) registerTask(pi, agents);

	// 既定の圧縮は read / edit / write の名前でファイルの操作を拾うので、別名の分を足す。
	// preparation は既定の要約にそのまま渡る (spike の E2)
	pi.on("session_before_compact", async (event, ctx) => {
		const ops = event.preparation.fileOps;
		const target: Record<string, Set<string>> = {
			[`${PREFIX}read`]: ops.read,
			[`${PREFIX}edit`]: ops.edited,
			[`${PREFIX}write`]: ops.written,
		};
		const messages = [...event.preparation.messagesToSummarize, ...event.preparation.turnPrefixMessages];
		for (const m of messages as any[]) {
			if (m?.role !== "assistant" || !Array.isArray(m.content)) continue;
			for (const b of m.content) {
				const set = b?.type === "toolCall" ? target[b.name] : undefined;
				if (set && typeof b.arguments?.path === "string") set.add(b.arguments.path);
			}
		}
		// 要約には引き継ぎの指示を足す。失敗したら既定の圧縮に任せる (指示は補助で、圧縮は止めない)
		try {
			const model = ctx.model;
			if (!model) throw new Error("ctx.model が無い");
			const auth = await ctx.modelRegistry.getApiKeyAndHeaders(model);
			if (!auth.ok) throw new Error(`認証を解決できない: ${auth.error}`);
			// 認証の解決結果の baseUrl をモデルへ反映する (Copilot はトークンごとに違う。pi 自身も同じ)
			const requestModel = auth.baseUrl ? { ...model, baseUrl: auth.baseUrl } : model;
			const compaction = await compact(
				event.preparation,
				requestModel,
				auth.apiKey,
				auth.headers,
				COMPACT_INSTRUCTIONS,
				event.signal,
				undefined,
				// 拡張が登録した提供元も通るよう、pi の呼び出し経路を使う (既定はグローバルな提供元の表だけを引く)
				(m: any, c: any, o: any) => ctx.modelRegistry.streamSimple(m, c, o),
				auth.env,
			);
			return { compaction };
		} catch (e) {
			// 既定の圧縮に任せる。理由は残す (指示が効いていないことに気付けるように)
			console.error(`[harness] 圧縮の指示を付けられなかったので既定の圧縮にする: ${(e as Error).message}`);
			return undefined;
		}
	});
}

// ─── 子エージェント ─────────────────────────────────────────────────

// 動いている子の一覧 (`activity` 拡張が数えて表示する)。プロセス内で共有する
type RunningChild = { agent: string; model: string; task: string; pid?: number; startedAt: number };
const runningChildren = ((globalThis as any).__piChildren ??= new Map<string, RunningChild>()) as Map<string, RunningChild>;

// 生かしておく子 (job) の上限と、1 往復の待機の上限、返却の上限
const MAX_JOBS = 4;
const ROUND_TIMEOUT_MS = Number(process.env.PI_HARNESS_TEST_ROUND_MS) || 15 * 60 * 1000;
const MAX_REPLY_CHARS = 20000;
const jobs = new Jobs(MAX_JOBS);
// 異常終了でも孤児の子を残さない (stdin が閉じても止まるが、作業中の子はすぐ止める)
process.once("exit", () => jobs.closeAll(true));

const STATUS_LABEL: Record<string, string> = { done: "completed" };

function registerTask(pi: ExtensionAPI, agents: Record<string, any>) {
	const names = Object.keys(agents);
	const catalog = names.map((n) => `- ${n}: ${agents[n].description}`).join("\n");
	const text = (t: string, isError = false, details: Record<string, unknown> = {}) => ({
		content: [{ type: "text", text: t }],
		details,
		isError,
	});
	pi.registerTool({
		name: `${PREFIX}task`,
		label: "task",
		// promptSnippet が無い自作ツールは system prompt の Available tools に出ず、モデルが存在に気付けない
		promptSnippet: `Run a task in a child agent (${names.join(" / ")}). Use for independent review, exploration, or parallel work`,
		promptGuidelines: [
			`Use ${PREFIX}task with agent "review" for an independent review or a second opinion. The child cannot see this conversation, so put everything it needs in \`task\`.`,
			`Set keep=true on ${PREFIX}task only when you expect follow-up requests to the same child. Send a follow-up with {jobId, task} using the jobId it returned, and close it with {jobId, close:true} when done. A job that is gone (closed, failed, or dropped when the bypass or session changed) must be restarted as a new task with a summary.`,
		],
		description:
			"Run a task in a child agent. The child is a separate pi process with the same guard, and cannot see this conversation, " +
			"so put everything it needs into `task`. Three forms (do not mix their fields):\n" +
			"- new: {agent, task, keep?}. The child stops when it finishes unless keep=true; then it stays idle and a jobId is returned.\n" +
			"- follow-up: {jobId, task}. Sends another request to a kept child; it remembers the earlier conversation. One request at a time per job.\n" +
			"- close: {jobId, close:true}. Stops the kept child.\n" +
			"Agents:\n" +
			catalog,
		parameters: Type.Object(
			{
				agent: Type.Optional(Type.Union(names.map((n) => Type.Literal(n)), { description: "new task only" })),
				task: Type.Optional(Type.String({ description: "What the child should do, with all the context it needs" })),
				keep: Type.Optional(Type.Boolean({ description: "new task only: keep the child idle after it finishes, for follow-ups" })),
				jobId: Type.Optional(Type.String({ description: "follow-up or close: the jobId of a kept child" })),
				close: Type.Optional(Type.Boolean({ description: "with jobId only: stop the kept child" })),
			},
			{ additionalProperties: false },
		),
		async execute(toolCallId: string, params: any, signal: any, _onUpdate: any, ctx: any) {
			// 入力の形 (3 形式の排他) は execute() で確かめる。判定は名前と役割だけを見る
			const input = parseTaskInput(params);
			// 最終の判定 (ほかのツールと同じく execute() でも確かめる)
			const d = decide("task", params, ctx.cwd);
			if (d.decision !== "allow") throw new Error(`実行前の判定で止めた: ${d.decision}: ${d.reason}`);
			const owner = { cwd: ctx.cwd, role: ROLE };

			let job: Job | undefined;
			let message: string;
			let keep: boolean;
			if (input.kind === "new") {
				const agent = agents[input.agent];
				if (!agent) throw new Error(`unknown agent: ${input.agent}`);
				const model = agent.model ?? `${ctx.model.provider}/${ctx.model.id}`;
				// 起動条件は pis と同じ (作業先の .pi/ を読まない・組み込みと拡張の自動発見を止める・MCP だけ戻す)
				const args = ["--mode", "rpc", "--no-session", "--no-approve", "-nbt", "-ne", "-e", "builtin:mcp", "-e", HERE];
				// 試験だけが使う (偽のモデルを子にも読ませる)
				for (const ext of (process.env.PI_HARNESS_TEST_CHILD_EXT ?? "").split(",").filter(Boolean)) args.push("-e", ext);
				args.push("--model", model, "--append-system-prompt", agent.system);
				const env: Record<string, string | undefined> = {
					...process.env,
					PI_HARNESS_CHILD: "1",
					PI_HARNESS_ROLE: agent.profile,
					PI_HARNESS_BYPASS: bypass && agent.inherit_bypass ? "1" : "",
				};
				// 枠は spawn の前に同期で確保される (並行する起動でも上限を超えない)
				job = jobs.create({ agent: input.agent, args, cwd: ctx.cwd, env, owner });
				if (!job) {
					const live = jobs.list().map((j) => `- ${j.id} (${j.agent}, ${j.state})`).join("\n");
					return text(`too many live child jobs (max ${MAX_JOBS}). Close one with {jobId, close:true}:\n${live}`, true);
				}
				message = input.task;
				keep = input.keep;
				runningChildren.set(toolCallId, { agent: input.agent, model, task: input.task, pid: job.pid, startedAt: Date.now() });
			} else {
				job = jobs.get(input.jobId);
				if (!job) {
					if (input.kind === "close") return text(`job ${input.jobId} does not exist (already closed)`);
					return text(`job ${input.jobId} does not exist (closed, failed, or dropped). Start a new task and include a summary of the earlier work.`, true);
				}
				if (job.owner.cwd !== owner.cwd || job.owner.role !== owner.role) throw new Error(`job ${input.jobId} belongs to another context`);
				if (input.kind === "close") {
					job.close();
					return text(`job ${input.jobId} closed`, false, { jobId: input.jobId, status: "closed" });
				}
				if (job.state === "running") return text(`job ${input.jobId} is busy with another request`, true);
				message = input.task;
				keep = true;
				runningChildren.set(toolCallId, { agent: job.agent, model: "", task: input.task, pid: job.pid, startedAt: Date.now() });
			}

			let r;
			try {
				r = await job.run(message, { signal, timeoutMs: ROUND_TIMEOUT_MS });
			} finally {
				runningChildren.delete(toolCallId);
			}
			if (signal?.aborted) throw new Error("child aborted");
			// keep でなければ完了で子を止める (done 以外は job が自分で閉じる)
			if (!keep) job.close();
			const alive = r.status === "done" && keep;
			const label = STATUS_LABEL[r.status] ?? r.status;
			const body = [
				`child ${job.agent}: ${label}${r.note ? ` (${r.note})` : ""}`,
				...r.blocked.map((b) => `- needs the user's approval (not run): ${b}`),
				...r.errors.map((b) => `- tool error: ${b}`),
				...(alive ? [`- job: ${job.id} (idle; follow up with {jobId, task}, close with {jobId, close:true})`] : []),
				"",
				r.answer,
			].join("\n");
			// 子の出力にも伏字化を掛ける (子の bash の出力は子のフルガードが伏せているが、返答の本文は伏せていない)。
			// 切り詰めは伏字化の後 (秘密の途中で切って伏字化から漏れないように)
			let out = redactText(body);
			if (out.length > MAX_REPLY_CHARS) out = `${out.slice(0, MAX_REPLY_CHARS)}\n[truncated: reply over ${MAX_REPLY_CHARS} chars]`;
			return text(out, r.status !== "done", {
				agent: job.agent,
				status: r.status,
				blocked: r.blocked.length,
				errors: r.errors.length,
				jobId: alive ? job.id : undefined,
			});
		},
	});
}

// ─── 編集の後の整形 ─────────────────────────────────────────────────

// rules.json の post_edit (PostToolUse の hook) を宣言順に呼ぶ。整形は黙って済ませ、
// markdownlint が残した違反だけを結果の末尾に足してモデルへ返す。失敗しても編集は成功のまま。
async function formatAfterEdit(result: any, path: unknown, cwd: string): Promise<any> {
	if (typeof path !== "string" || !rules.post_edit?.length) return result;
	const abs = isAbsolute(path) ? path : resolve(cwd, path);
	const warnings: string[] = [];
	await withFileMutationQueue(abs, async () => {
		for (const hook of rules.post_edit) {
			const r = spawnSync(hook.runner, [hook.script], {
				input: JSON.stringify({ tool_input: { path: abs } }),
				encoding: "utf-8",
				timeout: 30000,
				cwd,
			});
			// exit 2 は「エージェントへ警告する」(hook_emit_posttool_warn)。stderr が警告の本文
			if (r.status === 2 && r.stderr?.trim()) warnings.push(r.stderr.trim());
		}
	});
	if (!warnings.length) return result;
	const content = [...(result.content ?? []), { type: "text", text: `\n${redactText(warnings.join("\n"))}` }];
	return { ...result, content };
}
