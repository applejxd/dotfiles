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
import { lstatSync, mkdirSync, readdirSync, readFileSync, unlinkSync, writeFileSync } from "node:fs";
import { dirname, isAbsolute, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { Type } from "typebox";
import { BG_RUN, createCallDecider, type Decision } from "./judge/call.ts";
import { readBoundaryEnv, runCanary } from "./canary.ts";
import { Jobs, MAX_BATCH, NOT_APPROVED, WRAP_UP_MESSAGE, parseTaskInput, type Job, type RoundResult, type RoundStats } from "./children.ts";
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
	} catch {
		// 飾りなので出さないだけ (上のコメント)
	}
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
	const run = confirmQueue.then(() => {
		if (ctx.signal?.aborted) return false;
		// 利用者の答えを待つ前に BEL (端末の通知)。RPC では stdout が通信なので TUI だけ
		if (ctx.mode === "tui") process.stdout.write("\x07");
		return ctx.ui.confirm(title, body, { signal: ctx.signal, timeout });
	});
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
	// フルガードの下では、pi がスキルの一覧をシステムプロンプトへ入れない (宣言されたツールに read / bash が無いため)。
	// 同じ形の一覧を、読むツールを guarded_* の名前にして自分で足す。bypass・サンドボックスの有無とは無関係。
	// see docs/spec/pi-upstream.md (表 B の 16)
	pi.on("before_agent_start", async (event: any) => {
		const options = event.systemPromptOptions;
		if (!options || String(event.systemPrompt ?? "").includes("<available_skills>")) return;
		const skills = (options.skills ?? []).filter((s: any) => !s.disableModelInvocation);
		if (skills.length === 0) return;
		const reader = ["guarded_read", "guarded_bash"].find((t) => (options.selectedTools ?? []).includes(t));
		const esc = (s: string) =>
			String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&apos;");
		const lines = [
			"The following skills provide specialized instructions for specific tasks.",
			reader
				? `Use the ${reader} tool to load a skill's file when the task matches its description.`
				: "Load a skill's file when the task matches its description.",
			"When a skill file references a relative path, resolve it against the skill directory (parent of SKILL.md / dirname of the path) and use that absolute path in tool commands.",
			"",
			"<available_skills>",
		];
		for (const s of skills) {
			lines.push("  <skill>", `    <name>${esc(s.name)}</name>`, `    <description>${esc(s.description)}</description>`);
			lines.push(`    <location>${esc(s.filePath)}</location>`, "  </skill>");
		}
		lines.push("</available_skills>");
		options.sections = { ...(options.sections ?? {}), skills: lines.join("\n") };
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
			// 引き継ぎの指示に、/compact の引数（利用者が指定した焦点）を合わせる。pi 既定の圧縮もこの引数を要約へ足す
			const instructions = event.customInstructions
				? `${COMPACT_INSTRUCTIONS}\n\n【利用者の指定】${event.customInstructions}`
				: COMPACT_INSTRUCTIONS;
			const run = (preparation: any, level: any = pi.getThinkingLevel()) =>
				compact(
					preparation,
					requestModel,
					auth.apiKey,
					auth.headers,
					instructions,
					event.signal,
					// pi 本体の経路と同じ、セッションの思考レベル。渡さないと「思考なし」で送られ、
					// 「thinking: disabled」を受け付けないモデル (Copilot の claude-sonnet-5.5 など) で 400 になる
					level,
					// 拡張が登録した提供元も通るよう、pi の呼び出し経路を使う (既定はグローバルな提供元の表だけを引く)
					(m: any, c: any, o: any) => ctx.modelRegistry.streamSimple(m, c, o),
					auth.env,
					// 一時的な失敗 (レート制限・5xx・切断) の再試行。pi の既定値 (設定は拡張から読めない)
					{ enabled: true, maxRetries: 3, baseDelayMs: 2000, maxAgentDelayMs: 60000 },
				);
			try {
				return { compaction: await run(event.preparation) };
			} catch (e) {
				const message = (e as Error).message;
				// 思考が「無効」の指定を受け付けないモデル (Copilot の claude-sonnet-5.5 など) は 400 を返す。pi 既定の圧縮も同じ指定で
				// 失敗するので、思考を最小にして 1 回やり直す (圧縮が全く通らなくなるのを防ぐ)
				if (pi.getThinkingLevel() === "off" && /\b400\b/.test(message) && /thinking/i.test(message) && /(disabled|between_tools)/i.test(message)) {
					return { compaction: await run(event.preparation, "minimal") };
				}
				// 要約が出力の上限で切れたときだけ、上限 (reserveTokens の 0.8 倍) を倍にして 1 回やり直す。
				// 切れた要約は pi が保存しない (getSummarizationFailure)。他の失敗は繰り返さない
				if (!/token cap/.test(message)) throw e;
				const s = event.preparation.settings;
				return { compaction: await run({ ...event.preparation, settings: { ...s, reserveTokens: s.reserveTokens * 2 } }) };
			}
		} catch (e) {
			// 既定の圧縮に任せる。理由は全文を残す (指示が効いていないことに気付けるように。端末の幅で切れないよう通知にも出す)
			const reason = `圧縮の指示を付けられなかったので既定の圧縮にする: ${(e as Error).message}`;
			console.error(`[harness] ${reason}`);
			if (ctx.hasUI) ctx.ui.notify(reason, "warning");
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
// 利用者のコマンド (`btw`) が起動できる子の役割。読み取り専用に限る
const READ_ONLY_CHILD_PROFILES = new Set(["reader", "explorer"]);
const jobs = new Jobs(MAX_JOBS);
// 異常終了でも孤児の子を残さない (stdin が閉じても止まるが、作業中の子はすぐ止める)
process.once("exit", () => jobs.closeAll(true));

// 完了した job の結果を status で引けるように残す時間と件数
const FINISHED_TTL_MS = 30 * 60 * 1000;
const MAX_FINISHED = 20;
// 通知の通番 (この pi セッション内で 1 から)
let childSeq = 0;
const FINISHED_DIR = join(".tmp", "subagents");
// 保存した結果の掃除 (新しい順にこの件数まで残し、これより古いものは消す)
const SAVED_KEEP = 50;
const SAVED_MAX_AGE_MS = 7 * 24 * 60 * 60 * 1000;
// 保存ファイル 1 件 (batch では子 1 件) の上限
const SAVED_MAX_CHARS = 20000;

// 握りつぶさず利用者に見える形で警告する (UI が無ければ stderr)
function warnUser(ctx: any, msg: string) {
	try {
		if (ctx?.hasUI && ctx.ui?.notify) {
			ctx.ui.notify(msg, "warning");
			return;
		}
	} catch {
		// 廃棄済みの ctx は stderr へ回す
	}
	console.error(`[harness] ${msg}`);
}
// 警告文に入れる例外の message は伏字化を通す
const errMsg = (e: unknown) => redactText(e instanceof Error ? e.message : String(e));
const fmtClock = (t: number) => {
	const d = new Date(t);
	const p = (n: number) => String(n).padStart(2, "0");
	return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
};

const STATUS_LABEL: Record<string, string> = { done: "completed" };
const MAX_LIST_ERRORS = 5;

const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));
const fmtTokens = (n: number) => (n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n));
const fmtSecs = (ms: number) => `${Math.max(0, Math.round(ms / 1000))}s`;
const fmtStats = (s: RoundStats) =>
	`${fmtSecs(s.durationMs)}, ${s.calls} calls, ${fmtTokens(s.tokens)} tokens${s.cost > 0 ? `, $${s.cost.toFixed(3)}` : ""}`;

function registerTask(pi: ExtensionAPI, agents: Record<string, any>) {
	const names = Object.keys(agents);
	const catalog = names.map((n) => `- ${n}: ${agents[n].description}`).join("\n");
	const text = (t: string, isError = false, details: Record<string, unknown> = {}) => ({
		content: [{ type: "text", text: t }],
		details,
		isError,
	});
	// 子のモデルを呼び出しごとに選べるのは、宣言済みの役割のモデルと、親と同じモデルだけ (階層の範囲内)
	const allowedModels = (parentModel: string) => new Set([parentModel, ...names.map((n) => agents[n].model).filter(Boolean)]);

	// 子を 1 つ起動する。枠は同期で確保する (並行する起動でも上限を超えない)
	type Spawned = { job: Job; model: string } | { error: string; full?: boolean };
	const spawnChild = (agentName: string, ctx: any, owner: { cwd: string; role: string }, modelOverride?: string): Spawned => {
		const agent = agents[agentName];
		if (!agent) throw new Error(`unknown agent: ${agentName}`);
		const parentModel = `${ctx.model.provider}/${ctx.model.id}`;
		if (modelOverride && !allowedModels(parentModel).has(modelOverride)) {
			throw new Error(`model not allowed: ${modelOverride}. Allowed: ${[...allowedModels(parentModel)].join(", ")}`);
		}
		const model = modelOverride ?? agent.model ?? parentModel;
		// 起動条件は pis と同じ (作業先の .pi/ を読まない・組み込みと拡張の自動発見を止める・MCP だけ戻す)
		const args = ["--mode", "rpc", "--no-session", "--no-approve", "-nbt", "-ne", "-e", "builtin:mcp", "-e", HERE];
		// 親の --skill (pis が足した作業先の .agents/skills) をそのまま引き継ぐ。判断は起動側 (pi.py skill_args) の 1 か所
		const argv = process.argv;
		for (let i = 0; i < argv.length - 1; i++) if (argv[i] === "--skill") args.push("--skill", argv[i + 1]);
		// 試験だけが使う (偽のモデルを子にも読ませる)
		for (const ext of (process.env.PI_HARNESS_TEST_CHILD_EXT ?? "").split(",").filter(Boolean)) args.push("-e", ext);
		args.push("--model", model, "--append-system-prompt", agent.system);
		const env: Record<string, string | undefined> = {
			...process.env,
			PI_HARNESS_CHILD: "1",
			PI_HARNESS_ROLE: agent.profile,
			PI_HARNESS_BYPASS: bypass && agent.inherit_bypass ? "1" : "",
		};
		const job = jobs.create({ agent: agentName, args, cwd: ctx.cwd, env, owner });
		if (!job) {
			const live = jobs.list().map((j) => `- ${j.id} (${j.agent}, ${j.state})`).join("\n");
			return { error: `too many live child jobs (max ${MAX_JOBS}). Close one with {jobId, close:true}:\n${live}`, full: true };
		}
		return { job, model };
	};

	// 子の結果を、見出し・承認待ち・警告 (ツールエラー)・job・答えの本文に分けて返す。
	// 子のツールエラーは答えに混ぜない (件数を絞り、同じものは 1 つにまとめる)
	const resultText = (job: Job, r: RoundResult, alive: boolean) => {
		const label = STATUS_LABEL[r.status] ?? r.status;
		const errors = [...new Set(r.errors)];
		const shown = errors.slice(0, MAX_LIST_ERRORS);
		const parts = [
			`child ${job.agent}: ${label}${r.note ? ` (${r.note})` : ""} [${fmtStats(r.stats)}]`,
			...r.blocked.map((b) => `- needs the user's approval (not run): ${b}`),
			...(shown.length > 0
				? [`warnings (tool errors during the run; the answer below already accounts for them):`, ...shown.map((b) => `- tool error: ${b}`)]
				: []),
			...(errors.length > shown.length ? [`- ... and ${errors.length - shown.length} more tool errors`] : []),
			...(alive ? [`- job: ${job.id} (idle; follow up with {jobId, task}, close with {jobId, close:true})`] : []),
			...(r.answer ? ["", "answer:", r.answer] : [""]),
		];
		// 子の出力にも伏字化を掛ける (子の bash の出力は子のフルガードが伏せているが、返答の本文は伏せていない)。
		// 切り詰めは伏字化の後 (秘密の途中で切って伏字化から漏れないように)
		return redactText(parts.join("\n"));
	};
	const clip = (s: string, max = MAX_REPLY_CHARS) => (s.length > max ? `${s.slice(0, max)}\n[truncated: reply over ${max} chars]` : s);
	const detailsOf = (job: Job, r: RoundResult, alive: boolean) => ({
		agent: job.agent,
		status: r.status,
		blocked: r.blocked.length,
		errors: r.errors.length,
		stats: r.stats,
		jobId: alive ? job.id : undefined,
	});

	// 完了した job の結果 (redact 済みの全文)。close した job の分は消す
	type Finished = { at: number; owner: { cwd: string; role: string }; agent: string; status: string; text: string };
	const finished = new Map<string, Finished>();
	// close で閉じた job の id (終わりかけの往復の完了で結果が復活しないように覚える)
	const closedByParent = new Set<string>();
	const remember = (job: Job, r: RoundResult, full: string) => {
		if (closedByParent.has(job.id)) return;
		const now = Date.now();
		for (const [k, v] of finished) if (now - v.at > FINISHED_TTL_MS) finished.delete(k);
		finished.delete(job.id);
		finished.set(job.id, { at: now, owner: job.owner, agent: job.agent, status: r.status, text: full });
		while (finished.size > MAX_FINISHED) finished.delete(finished.keys().next().value as string);
	};
	const recall = (id: string): Finished | undefined => {
		const f = finished.get(id);
		if (f && Date.now() - f.at > FINISHED_TTL_MS) {
			finished.delete(id);
			return undefined;
		}
		return f;
	};

	// 通知の見出しの追記 (通番・起動時刻・完了時刻) と、結果の全文の保存。保存できなくても通知は止めない
	const stampOf = (seq: number, startedAt: number) => `#${seq} 起動 ${fmtClock(startedAt)} / 完了 ${fmtClock(Date.now())}`;
	const saveFull = (ctx: any, cwd: string, seq: number, id: string, stamp: string, full: string): string | null => {
		const rel = join(FINISHED_DIR, `${seq}-${id}.md`);
		const dir = join(cwd, FINISHED_DIR);
		try {
			let isLink = false;
			try {
				isLink = lstatSync(dir).isSymbolicLink();
			} catch {
				// まだ無い (これから作る)
			}
			if (isLink) throw new Error(`${FINISHED_DIR} がシンボリックリンクなので書かない`);
			mkdirSync(dir, { recursive: true });
			// wx: 既存のファイル (リンク含む) には書かない
			writeFileSync(join(cwd, rel), `${stamp}\n\n${full}\n`, { encoding: "utf-8", flag: "wx" });
		} catch (e) {
			warnUser(ctx, `子の結果を ${rel} へ保存できなかった: ${errMsg(e)}`);
			return null;
		}
		pruneSaved(dir);
		return rel;
	};
	const pruneSaved = (dir: string) => {
		try {
			const now = Date.now();
			const files = readdirSync(dir)
				.filter((n) => n.endsWith(".md"))
				.flatMap((n) => {
					const st = lstatSync(join(dir, n));
					return st.isFile() ? [{ n, t: st.mtimeMs }] : [];
				})
				.sort((a, b) => b.t - a.t);
			files.forEach((f, i) => {
				if (i >= SAVED_KEEP || now - f.t > SAVED_MAX_AGE_MS) unlinkSync(join(dir, f.n));
			});
		} catch {
			// 掃除の失敗は結果の保存と通知に関係しないので警告しない
		}
	};

	// 割り当てた ToDo の項目へ結果を反映する (done なら done、そうでなければメモだけ)。todo 拡張が入口を置く
	const linkTodo = (id: number | undefined, job: Job, r: RoundResult, ctx?: any) => {
		if (id === undefined) return;
		const note = `child ${job.agent}: ${r.status} (${fmtStats(r.stats)})`;
		try {
			(globalThis as any).__piTodoUpdate?.({ id, status: r.status === "done" ? "done" : undefined, note });
		} catch (e) {
			warnUser(ctx, `ToDo #${id} へ子の結果を反映できなかった: ${errMsg(e)}`);
		}
	};

	// 待たずに走らせる。完了は followUp で親へ知らせる (ターンが再開する)
	const runInBackground = (job: Job, message: string, keep: boolean, key: string, todo: number | undefined, wake: boolean, ctx: any) => {
		const startedAt = Date.now();
		runningChildren.set(key, { agent: job.agent, model: "", task: message, pid: job.pid, startedAt });
		job
			.run(message, { timeoutMs: ROUND_TIMEOUT_MS, wrapUpMessage: WRAP_UP_MESSAGE })
			.then((r) => {
				if (!keep) job.close();
				const alive = (r.status === "done" || r.status === "aborted") && keep;
				linkTodo(todo, job, r, ctx);
				const full = resultText(job, r, alive);
				remember(job, r, full);
				const seq = ++childSeq;
				const stamp = stampOf(seq, startedAt);
				const saved = saveFull(ctx, job.owner.cwd, seq, job.id, stamp, full);
				const body = clip(full) + (saved ? `\n結果の全文: ${saved}` : "");
				try {
					pi.sendMessage(
						{
							customType: "child-finished",
							content: `バックグラウンドの子 ${job.id} (${job.agent}) が終わりました (${stamp})\n${body}`,
							display: true,
							details: detailsOf(job, r, alive),
						},
						{ triggerTurn: wake, ...(wake ? { deliverAs: "followUp" as const } : {}) },
					);
				} catch (e) {
					warnUser(ctx, `子 ${job.id} の完了通知を配信できなかった (結果は ${saved ?? "status で確認"}): ${errMsg(e)}`);
				}
			})
			.catch((e) => warnUser(ctx, `子 ${job.id} の完了処理が失敗した: ${errMsg(e)}`))
			.finally(() => runningChildren.delete(key));
	};

	// `btw` が、読み取り専用の子の答えだけを受け取る入口。利用者が起こす操作なので /agent と同じく判定は通さない。
	// 子の役割は読み取り専用だけを許し、答えには伏字化を掛ける
	(globalThis as any).__piAskReadChild = async (agentName: string, task: string, ctx: any, signal?: AbortSignal) => {
		const agent = agents[agentName];
		if (!agent || !READ_ONLY_CHILD_PROFILES.has(agent.profile)) return { ok: false, text: `not a read-only agent: ${agentName}` };
		const sp = spawnChild(agentName, ctx, { cwd: ctx.cwd, role: ROLE });
		if ("error" in sp) return { ok: false, text: sp.error };
		const key = `btw-${sp.job.id}`;
		runningChildren.set(key, { agent: agentName, model: sp.model, task, pid: sp.job.pid, startedAt: Date.now() });
		try {
			const r = await sp.job.run(task, { signal, timeoutMs: ROUND_TIMEOUT_MS, wrapUpMessage: WRAP_UP_MESSAGE });
			sp.job.close();
			// 上限での切り詰めと「省略あり」の表示は、呼び出し側 (btw) がする
			if (r.status === "done" && r.answer) return { ok: true, text: redactText(r.answer) };
			return { ok: false, text: clip(resultText(sp.job, r, false)) };
		} catch (e) {
			sp.job.close(true);
			return { ok: false, text: e instanceof Error ? e.message : String(e) };
		} finally {
			runningChildren.delete(key);
		}
	};

	pi.registerTool({
		name: `${PREFIX}task`,
		label: "task",
		// promptSnippet が無い自作ツールは system prompt の Available tools に出ず、モデルが存在に気付けない
		promptSnippet: `Run a task in a child agent (${names.join(" / ")}). Use for independent review, exploration, or parallel work`,
		promptGuidelines: [
			`Use ${PREFIX}task with agent "review" for an independent review or a second opinion. The child cannot see this conversation, but it reads files and runs read-only git itself, so do not paste the transcript or whole diffs. Write in \`task\`: (1) the goal and constraints, (2) where to look (paths, refs), (3) what you verified and what you did not, (4) options you rejected and why, (5) your tentative conclusion, last, labelled as the thing to challenge, (6) the question you want answered.`,
			`Set keep=true on ${PREFIX}task only when you expect follow-up requests to the same child. Send a follow-up with {jobId, task} using the jobId it returned, and close it with {jobId, close:true} when done. A job that is gone (closed, failed, or dropped when the bypass or session changed) must be restarted as a new task with a summary.`,
			`Use background=true on ${PREFIX}task to keep working while the child runs; you are notified when it finishes. Use {jobId, status:true} or {list:true} to look at running children, {jobId, steer:"..."} to redirect one, and {jobId, abort:true} to stop its current round (the child stays).`,
			`For several independent tasks, use {tasks:[{agent, task}, ...]} (up to ${MAX_BATCH}); tasks beyond the live-job limit wait instead of failing.`,
		],
		description:
			"Run a task in a child agent. The child is a separate pi process with the same guard, and cannot see this conversation, " +
			"so put everything it needs into `task`. Forms (do not mix their fields):\n" +
			"- new: {agent, task, keep?, background?, model?, todo?}. The child stops when it finishes unless keep=true; then it stays idle and a jobId is returned. " +
			"background=true returns at once and notifies you on completion. model must be a model already used by an agent below, or your own. todo is a todo id to update when the child finishes.\n" +
			"- tasks: {tasks:[{agent, task, model?}, ...], background?}. Runs them in parallel (waiting for free slots) and returns every result.\n" +
			"- follow-up: {jobId, task, background?}. Sends another request to a kept child; it remembers the earlier conversation. One request at a time per job.\n" +
			"- status: {jobId, status:true}, or list: {list:true}. State, elapsed time, last tool, calls and tokens of children.\n" +
			"- steer: {jobId, steer:\"...\"}. Sends an extra instruction to a running child (delivered after its current turn).\n" +
			"- abort: {jobId, abort:true}. Stops the child's current round; the child stays for a follow-up.\n" +
			"- close: {jobId, close:true}. Stops the kept child.\n" +
			"Agents:\n" +
			catalog,
		parameters: Type.Object(
			{
				// "" は埋め草 (厳格なスキーマのモデルが使わない引数を空で埋める。B1 の F5)。実際の形の判定は parseTaskInput
				agent: Type.Optional(Type.Union([...names, ""].map((n) => Type.Literal(n)), { description: "new task only" })),
				task: Type.Optional(Type.String({ description: "What the child should do, with all the context it needs" })),
				keep: Type.Optional(Type.Boolean({ description: "new task only: keep the child idle after it finishes, for follow-ups" })),
				background: Type.Optional(Type.Boolean({ description: "new / tasks / follow-up: return at once and be notified on completion" })),
				model: Type.Optional(Type.String({ description: "new task only: a model already used by a declared agent, or your own" })),
				todo: Type.Optional(Type.Number({ description: "new task only: a todo id to mark done (or annotate) when the child finishes" })),
				tasks: Type.Optional(
					Type.Array(
						Type.Object(
							{ agent: Type.String(), task: Type.String(), model: Type.Optional(Type.String()) },
							{ additionalProperties: false },
						),
						{ description: `parallel tasks (up to ${MAX_BATCH}); do not combine with other fields except background` },
					),
				),
				jobId: Type.Optional(Type.String({ description: "follow-up, status, steer, abort or close: the jobId of a kept child" })),
				close: Type.Optional(Type.Boolean({ description: "with jobId only: stop the kept child" })),
				status: Type.Optional(Type.Boolean({ description: "with jobId only: show the child's state" })),
				abort: Type.Optional(Type.Boolean({ description: "with jobId only: stop the child's current round (the child stays)" })),
				steer: Type.Optional(Type.String({ description: "with jobId only: an extra instruction for a running child" })),
				list: Type.Optional(Type.Boolean({ description: "list the children" })),
			},
			{ additionalProperties: false },
		),
		async execute(toolCallId: string, params: any, signal: any, _onUpdate: any, ctx: any) {
			// 入力の形の排他は execute() で確かめる。判定は名前と役割だけを見る
			const input = parseTaskInput(params);
			// 最終の判定 (ほかのツールと同じく execute() でも確かめる)
			const d = decide("task", params, ctx.cwd);
			if (d.decision !== "allow") throw new Error(`実行前の判定で止めた: ${d.decision}: ${d.reason}`);
			const owner = { cwd: ctx.cwd, role: ROLE };
			const own = (j: Job) => j.owner.cwd === owner.cwd && j.owner.role === owner.role;

			// ─── 一覧 ───
			if (input.kind === "list") {
				const rows = jobs
					.list()
					.filter(own)
					.map((j) => j.snapshot())
					.map(
						(s) =>
							`- ${s.id} ${s.agent} ${s.state}${s.state === "running" ? ` ${fmtSecs(s.roundMs)}` : ""} | calls ${s.calls}, ${fmtTokens(s.tokens)} tokens${s.lastTool ? `, last tool: ${s.lastTool}` : ""}`,
					);
				return text(rows.length ? rows.join("\n") : "(no live children)", false, { count: rows.length });
			}

			// ─── 並列の一括 ───
			if (input.kind === "batch") {
				for (const t of input.tasks) if (!agents[t.agent]) throw new Error(`unknown agent: ${t.agent}`);
				const slots = MAX_JOBS - jobs.size;
				if (slots <= 0) {
					const live = jobs.list().map((j) => `- ${j.id} (${j.agent}, ${j.state})`).join("\n");
					return text(`too many live child jobs (max ${MAX_JOBS}). Close one with {jobId, close:true}:\n${live}`, true);
				}
				const items = input.tasks;
				const per = Math.floor(MAX_REPLY_CHARS / items.length);
				const runAll = async (sig: AbortSignal | undefined) => {
					const sections = new Array<string>(items.length);
					const statuses = new Array<string>(items.length);
					const fulls = new Array<string>(items.length);
					let next = 0;
					const worker = async () => {
						for (;;) {
							const i = next++;
							if (i >= items.length) return;
							const it = items[i];
							let sp: Spawned = { error: "", full: true };
							// 空きが出るまで待つ (上限は維持する)
							for (let tries = 0; tries < 6000 && "error" in sp && sp.full; tries++) {
								sp = spawnChild(it.agent, ctx, owner, it.model);
								if ("error" in sp && sp.full) await sleep(100);
							}
							// 依頼文は秘密を含みうるので、伏字化してから切る
							const head = `### ${i + 1}/${items.length} ${it.agent}: ${redactText(it.task).slice(0, 60).replace(/\s+/g, " ")}`;
							if ("error" in sp) {
								sections[i] = `${head}\n${sp.error}`;
								fulls[i] = sections[i];
								statuses[i] = "failed";
								continue;
							}
							const job = sp.job;
							const r = await job.run(it.task, { signal: sig, timeoutMs: ROUND_TIMEOUT_MS, wrapUpMessage: WRAP_UP_MESSAGE });
							job.close();
							const body = resultText(job, r, false);
							sections[i] = `${head}\n${clip(body, per)}`;
							fulls[i] = `${head}\n${clip(body, SAVED_MAX_CHARS)}`;
							statuses[i] = r.status;
						}
					};
					await Promise.all(Array.from({ length: Math.min(slots, items.length) }, worker));
					return { sections, statuses, fulls };
				};
				if (input.background) {
					const key = `${toolCallId}:batch`;
					const batchStartedAt = Date.now();
					runningChildren.set(key, { agent: `${items.length} tasks`, model: "", task: "", startedAt: batchStartedAt });
					runAll(undefined)
						.then(({ sections, statuses, fulls }) => {
							const seq = ++childSeq;
							const stamp = stampOf(seq, batchStartedAt);
							const full = sections.join("\n\n");
							// id に時刻を入れる (別セッションの同じ通番と名前が重なると wx で保存できない)
							const saved = saveFull(ctx, ctx.cwd, seq, `batch-${Date.now().toString(36)}`, stamp, fulls.join("\n\n"));
							try {
								pi.sendMessage(
									{
										customType: "child-finished",
										content: `バックグラウンドの ${items.length} 件の子が終わりました (${stamp})\n\n${full}${saved ? `\n結果の全文: ${saved}` : ""}`,
										display: true,
										details: { statuses },
									},
									{ triggerTurn: true, deliverAs: "followUp" },
								);
							} catch (e) {
								warnUser(ctx, `並列の子の完了通知を配信できなかった (結果は ${saved ?? "未保存"}): ${errMsg(e)}`);
							}
						})
						.catch((e) => warnUser(ctx, `並列の子の完了処理が失敗した: ${errMsg(e)}`))
						.finally(() => runningChildren.delete(key));
					return text(`started ${items.length} tasks in the background (up to ${slots} at a time). You will be notified when they finish.`, false, { background: true, tasks: items.length });
				}
				runningChildren.set(toolCallId, { agent: `${items.length} tasks`, model: "", task: "", startedAt: Date.now() });
				let out;
				try {
					out = await runAll(signal);
				} finally {
					runningChildren.delete(toolCallId);
				}
				if (signal?.aborted) throw new Error("child aborted");
				const bad = out.statuses.some((s) => s !== "done");
				return text(clip(out.sections.join("\n\n")), bad, { statuses: out.statuses });
			}

			// ─── 既存の job への操作 ───
			let job: Job | undefined;
			let message = "";
			let keep = false;
			let background = false;
			let todo: number | undefined;
			if (input.kind === "new") {
				const sp = spawnChild(input.agent, ctx, owner, input.model);
				if ("error" in sp) return text(sp.error, true);
				job = sp.job;
				message = input.task;
				keep = input.keep;
				background = input.background;
				todo = input.todo;
				if (!background) runningChildren.set(toolCallId, { agent: input.agent, model: sp.model, task: input.task, pid: job.pid, startedAt: Date.now() });
			} else {
				job = jobs.get(input.jobId);
				if (!job) {
					const f = recall(input.jobId);
					if (input.kind === "status" && f && f.owner.cwd === owner.cwd && f.owner.role === owner.role) {
						return text(`job ${input.jobId} (${f.agent}): finished (${f.status}, ${fmtClock(f.at)}); the child is gone. Saved result:\n${clip(f.text)}`, false, { jobId: input.jobId, status: f.status, finished: true });
					}
					// 所有者が違う保持結果は消さない (存在しないのと同じ応答で、他の文脈の結果の有無を漏らさない)
					if (input.kind === "close" && f && f.owner.cwd === owner.cwd && f.owner.role === owner.role) finished.delete(input.jobId);
					if (input.kind === "close") return text(`job ${input.jobId} does not exist (already closed)`);
					return text(`job ${input.jobId} does not exist (closed, failed, or dropped). Start a new task and include a summary of the earlier work.`, true);
				}
				if (!own(job)) throw new Error(`job ${input.jobId} belongs to another context`);
				if (input.kind === "close") {
					closedByParent.add(input.jobId);
					job.close();
					finished.delete(input.jobId);
					return text(`job ${input.jobId} closed`, false, { jobId: input.jobId, status: "closed" });
				}
				if (input.kind === "status") {
					const s = job.snapshot();
					const f = s.state === "running" ? undefined : recall(job.id);
					return text(
						`job ${s.id} (${s.agent}): ${s.state}${s.state === "running" ? `, this round ${fmtSecs(s.roundMs)}` : ""}\n` +
							`age ${fmtSecs(s.ageMs)}, calls ${s.calls}, ${fmtTokens(s.tokens)} tokens${s.cost > 0 ? `, $${s.cost.toFixed(3)}` : ""}` +
							`${s.lastTool ? `, last tool: ${s.lastTool}` : ""}` +
							(f ? `\nlast result (${f.status}, ${fmtClock(f.at)}):\n${clip(f.text)}` : ""),
						false,
						{ ...s },
					);
				}
				if (input.kind === "steer") {
					const r = job.steer(input.message);
					return text(r === "queued" ? `steer queued for ${job.id} (delivered after its current turn)` : `job ${job.id} is not running; nothing to steer`, r !== "queued", { jobId: job.id, steer: r });
				}
				if (input.kind === "abort") {
					const ok = job.interrupt();
					return text(ok ? `abort sent to ${job.id}; the child stays and the running request will report "aborted"` : `job ${job.id} is not running; nothing to abort`, !ok, { jobId: job.id, abort: ok });
				}
				if (job.state === "running") return text(`job ${input.jobId} is busy with another request`, true);
				message = input.task;
				keep = true;
				background = input.background;
				if (!background) runningChildren.set(toolCallId, { agent: job.agent, model: "", task: input.task, pid: job.pid, startedAt: Date.now() });
			}

			if (background) {
				runInBackground(job, message, keep, job.id, todo, true, ctx);
				return text(`started ${job.agent} in the background as ${job.id}. You will be notified when it finishes (status: {jobId, status:true}, steer: {jobId, steer:"..."}, abort: {jobId, abort:true}).`, false, {
					jobId: job.id,
					background: true,
				});
			}

			let r: RoundResult;
			try {
				r = await job.run(message, { signal, timeoutMs: ROUND_TIMEOUT_MS, wrapUpMessage: WRAP_UP_MESSAGE });
			} finally {
				runningChildren.delete(toolCallId);
			}
			if (signal?.aborted) throw new Error("child aborted");
			// keep でなければ完了で子を止める (done と aborted 以外は job が自分で閉じる)
			if (!keep) job.close();
			const alive = (r.status === "done" || r.status === "aborted") && keep;
			linkTodo(todo, job, r, ctx);
			const full = resultText(job, r, alive);
			remember(job, r, full);
			return text(clip(full), r.status !== "done", detailsOf(job, r, alive));
		},
	});

	// 利用者専用のコマンド (モデルは呼べない)。見た目はテキストだけ
	pi.registerCommand("agents", {
		description: "動いている子エージェントの一覧 (状態・経過・最後のツール・使用量)",
		handler: async (_args: string, ctx: any) => {
			const owner = { cwd: ctx.cwd, role: ROLE };
			const rows = jobs
				.list()
				.filter((j) => j.owner.cwd === owner.cwd && j.owner.role === owner.role)
				.map((j) => j.snapshot())
				.map(
					(s) =>
						`${s.id} ${s.agent} ${s.state}${s.state === "running" ? ` ${fmtSecs(s.roundMs)}` : ""} | calls ${s.calls}, ${fmtTokens(s.tokens)} tokens${s.lastTool ? `, last tool: ${s.lastTool}` : ""}`,
				);
			ctx.ui?.notify?.(rows.length ? rows.join("\n") : "子エージェントはありません", "info");
		},
	});
	pi.registerCommand("agent", {
		description: `子を直接起動する: /agent <${names.join("|")}> <依頼>。結果はチャットに表示する (モデルは待たずに続きを進められる)`,
		handler: async (args: string, ctx: any) => {
			const m = /^(\S+)\s+([\s\S]+)$/.exec(String(args ?? "").trim());
			if (!m || !agents[m[1]]) {
				ctx.ui?.notify?.(`使い方: /agent <${names.join("|")}> <依頼>`, "warning");
				return;
			}
			const sp = spawnChild(m[1], ctx, { cwd: ctx.cwd, role: ROLE });
			if ("error" in sp) {
				ctx.ui?.notify?.(sp.error, "warning");
				return;
			}
			// 完了はチャットに表示するだけ。モデルのターンは起こさない
			runInBackground(sp.job, m[2], false, sp.job.id, undefined, false, ctx);
			ctx.ui?.notify?.(`${m[1]} を起動しました (${sp.job.id})。終わるとここに結果を表示します`, "info");
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
