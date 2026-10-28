// pi のフルガード。組み込みのツールの代わりに guarded_* のツールを登録し、判定器 (./judge) で
// 実行してよいかを決める。起動は `pi -nbt -ne -e ~/.config/pi/harness`。
// see docs/spec/guard/pi-guard.md
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
import { randomBytes } from "node:crypto";
import { existsSync, lstatSync, mkdirSync, readdirSync, readFileSync, realpathSync, statSync, unlinkSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, isAbsolute, join, relative, resolve, sep } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { Type } from "typebox";
import { BG_RUN, createCallDecider, type Decision } from "./judge/call.ts";
import { readBoundaryEnv, runCanary } from "./canary.ts";
import { Jobs, MAX_BATCH, NOT_APPROVED, WRAP_UP_MESSAGE, parseTaskInput, type Job, type RoundResult, type RoundStats } from "./children.ts";
import { createRedactor } from "./redact.ts";
import { MAX_BODY_FILE_BYTES, NO_UI_REASON, buildMustConfirmView, classifyConfirm, confirmTimeoutSeconds, outcomeReason, type BodyFileResult, type ConfirmRaw } from "./confirm-view.ts";
import { appendOperations, appendResult, decorateEditResult, guideHint, readParameters, runRead, toolText, writeParameters } from "./tools-ext.ts";
import { ACTION_TOOL, actionDescription, actionLine, executeAction, loadActions } from "./actions.ts";
import { auditConditions, auditFormat, summarizeCalls } from "./audit.ts";
import { unguardedMessage, unguardedSources } from "./unguarded.ts";
import { SessionTmp } from "./session-tmp.ts";
import { EFFORTS, catalogText, describeChoice, modelArgument, resolveChoice, roundTimeoutMs } from "./model-choice.ts";
import { ISOLATION_UNSUPPORTED, NO_BASH_NOTICE, findBash, isWindows, supportsChildTasks } from "./platform.ts";
import { loadFileGlobs, loadReadDenyExceptions } from "./judge/policy.ts";
import { DEFAULT_LIMITS, WorktreeError, collect, createIsolation, discard, markKept, runGit, validateJobId, type IsolationRecord, type ReadDeny } from "./worktree.ts";
import { STARTUP_LIMITS, findRepoRoot, isolationTraceRoot, runWorktreesCommand, startupReconcile } from "./worktrees-command.ts";
import { PENDING_PREFIX, dropPending, listPending, reconcilePending, showPending } from "./pending-store.ts";

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
// bodyFile は mustConfirm の確認で見せた --body-file の内容 (execute() で差し替えを検出する)
const decided = new Map<string, { input: string; decision: Decision; approved: boolean; bodyFile?: { path: string; text: string } }>();

// 確認は 1 件ずつ出す。TUI の confirm は 1 枠を共有し、後の確認が先の確認を置き換える
// (codemode の中で並べた呼び出しで先の確認が永久に止まった。spike の E3)
let confirmQueue: Promise<unknown> = Promise.resolve();
// 利用者が不在と分かった状態 (確認が時間切れ)。入力の世代 gen は、利用者の入力のたびに進む。see docs/change/0046-guarded-action-timeout.md
const absence = { absent: false, gen: 0 };
// TUI 以外 (RPC など) は、クライアントが確認に応えないと永久に待つので期限を付ける (期限が来たら拒否)
const CONFIRM_TIMEOUT_MS = 5 * 60 * 1000;
// timeoutMs を渡すと TUI でも期限が付く (mustConfirm)。結果は経過時間つきで返す (時間切れと拒否の区別用)
function confirmDetailed(ctx: any, title: string, body: string, timeoutMs?: number): Promise<ConfirmRaw> {
	const timeout = timeoutMs ?? (ctx.mode === "tui" ? undefined : CONFIRM_TIMEOUT_MS);
	const run = confirmQueue.then(async (): Promise<ConfirmRaw> => {
		if (ctx.signal?.aborted) return { ok: false, elapsedMs: 0, aborted: true, error: false };
		// 利用者の答えを待つ前に BEL (端末の通知)。RPC では stdout が通信なので TUI だけ
		if (ctx.mode === "tui") process.stdout.write("\x07");
		const t0 = Date.now();
		const v = await ctx.ui.confirm(title, body, { signal: ctx.signal, timeout });
		return { ok: v === true, elapsedMs: Date.now() - t0, aborted: ctx.signal?.aborted === true, error: false };
	});
	confirmQueue = run.catch(() => undefined);
	return run.catch((): ConfirmRaw => ({ ok: false, elapsedMs: 0, aborted: false, error: true }));
}
// guarded_action の対話 (select・editor・input) を、確認の枠を共有して 1 件ずつ行う
function dialogInOrder<T>(fn: () => Promise<T>): Promise<T> {
	const run = confirmQueue.then(fn);
	confirmQueue = run.catch(() => undefined);
	return run;
}
function confirmInOrder(ctx: any, title: string, body: string): Promise<boolean> {
	return confirmDetailed(ctx, title, body).then((r) => r.ok);
}

// --body-file を読む (32 KiB まで。読み取りの判定が allow のときだけ)。確認の前と execute() の両方で使う
function readBodyFile(path: string, cwd: string, tool: string): BodyFileResult {
	if (tool === BG_RUN) return { ok: false, why: "bg_run では本文のファイルを確認できない (guarded_bash を使う)" };
	if (path === "-") return { ok: false, why: "標準入力は読めない" };
	const d = decide("read", { path }, cwd);
	if (d.decision !== "allow") return { ok: false, why: `${path} は読み取りが許可されていない` };
	try {
		const abs = resolve(cwd, path);
		const st = statSync(abs);
		if (!st.isFile()) return { ok: false, why: `${path} は通常のファイルではない` };
		if (st.size > MAX_BODY_FILE_BYTES) return { ok: false, why: `${path} が ${MAX_BODY_FILE_BYTES} バイトを超える` };
		return { ok: true, text: readFileSync(abs, "utf-8") };
	} catch (e) {
		return { ok: false, why: `${path} を読めない: ${(e as Error).message}` };
	}
}

// bash の読み取り・書き込みの誘導 (deny) の理由。deny されたときの再試行を安くするため、具体的な言い換えを末尾へ足す。
// 判定 (allow / deny) は変えない。
const GUIDE_IDS = ["read-cat-head-tail", "read-sed-n", "write-cat-tee-heredoc", "write-heredoc-script"];
const GUIDE_REASONS = new Set<string>(
	((rules.judge.common?.pi?.guide as any[] | undefined) ?? []).filter((g) => !g?.scope && GUIDE_IDS.includes(g?.id)).map((g) => String(g.message)),
);
function denyReason(tool: string, input: any, d: Decision): string {
	if (tool !== "bash" || d.source !== "rule" || !GUIDE_REASONS.has(d.reason)) return d.reason;
	const hint = guideHint(String(input?.command ?? ""), PREFIX);
	return hint ? `${d.reason}\n${hint}` : d.reason;
}

function baseName(toolName: string): string {
	return toolName.startsWith(PREFIX) ? toolName.slice(PREFIX.length) : toolName;
}

// ─── 登録 ───────────────────────────────────────────────────────────

export default async function (pi: ExtensionAPI) {
	// 自作の拡張のうち実行する道具 (bg_run・task) は、この印が無いと動かない (フルガードの読み込みに失敗した起動で、判定なしに残さない)
	(globalThis as any).__PI_FULL_GUARD__ = true;
	// セッションごとの一時置き場。子 (親の TMPDIR を継承する)・pis の内側 (TMPDIR=/tmp の tmpfs)・Windows では何もしない
	const sessionTmp = new SessionTmp({ enabled: !CHILD && process.env.PI_HARNESS_BOUNDARY !== "1" && !isWindows(), harnessDir: HERE });
	await loadCommitPreview();
	// 状態の表示 (安全の根拠ではなく、いまどちらで動いているかの目印)
	const showBypass = (ctx: any) => {
		if (ctx.hasUI) ctx.ui.setStatus("bypass", bypass ? ctx.ui.theme.fg("warning", "⚡ bypass") : undefined);
	};
	// セッションの終了・切り替え・/reload で、保持している子を全部止める。
	// そのうえで、セッションごとの一時置き場 (.tmp/s/<ID>/) は quit のときだけ消す (CHG-0042)
	pi.on("session_shutdown", async (event: any) => {
		jobs.closeAll();
		try {
			await sessionTmp.teardown(String(event?.reason ?? ""));
		} catch {}
	});
	pi.on("input", (event: any) => {
		if (event?.source !== "extension") {
			absence.gen++;
			absence.absent = false;
		}
	});
	pi.on("session_start", async (event: any, ctx: any) => {
		absence.gen++;
		absence.absent = false;
		try {
			const cwd = ctx.cwd ?? process.cwd();
			sessionTmp.start(cwd, ctx.sessionManager.getSessionId());
			// 取り込み済み・重複・古い退避を片付ける (消すのはハーネスだけ。モデルは消せない)
			try {
				reconcilePending(cwd);
			} catch {}
			if (event?.reason === "startup") sessionTmp.sweep(cwd);
		} catch {}
		reconcileOnStart(ctx);
		if (!ctx.hasUI) return;
		showBypass(ctx);
		// 判定の外で動きうるもの (mcp.json のサーバ・信頼した作業先の .pi/) は、止めずに知らせる
		const outside = unguardedSources(process.env.PI_CODING_AGENT_DIR || join(homedir(), ".pi", "agent"), ctx.cwd ?? process.cwd(), process.argv);
		if (outside.length > 0) ctx.ui.notify(unguardedMessage(outside), "warning");
		if (BOUNDARY) ctx.ui.setStatus("sandbox", "🔒 sandbox");
		else if (NO_SANDBOX) ctx.ui.setStatus("sandbox", ctx.ui.theme.fg("warning", "⚠ no sandbox"));
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
	// see docs/spec/guard/pi-guard.md#bypass-の切り替え
	pi.registerCommand("bypass", {
		description: "bypass (ask を確認なしで通す。外部への送信・公開は bypass でも確認する) の切り替え: /bypass [on|off]",
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
				const body =
					(BOUNDARY
						? "ask の操作 (git commit や MCP など) を確認なしで通します。deny とサンドボックスは有効のまま。"
						: "サンドボックスが無いまま、ask の操作 (git commit や未知の shell や MCP など) を確認なしで通します。deny だけが守りです。") +
					"\n確認が要る外部への送信・公開 (gh の投稿など) は、bypass でも確認します。";
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
		if (d.decision === "deny") return { block: true, reason: denyReason(tool, event.input, d) };
		if (d.decision === "ask") {
			// bypass でも出す確認 (外部への送信・公開)。判定器は bypass でも allow にしない
			if ((d as any).mustConfirm === true) {
				const isShell = tool === "bash" || tool === BG_RUN;
				const block = (why: string) => ({ block: true, reason: `${NOT_APPROVED} ${why}` });
				// UI が無い実行 (print) と子 (RPC の確認は自動で取り消される) では、確認が要る操作は拒否する
				if (!ctx.hasUI || CHILD) return block(NO_UI_REASON);
				const text = isShell ? String(event.input?.command ?? "") : `${tool}: ${JSON.stringify(event.input)}`;
				const view = buildMustConfirmView(text, d.reason, (p) => readBodyFile(p, ctx.cwd, tool));
				if (view.kind === "block") return block(view.reason);
				const timeoutMs = confirmTimeoutSeconds(rules) * 1000;
				const outcome = classifyConfirm(await confirmDetailed(ctx, view.title, view.body, timeoutMs), timeoutMs);
				if (outcome !== "approved") return block(outcomeReason(outcome));
				decided.set(event.toolCallId, { input, decision: d, approved: true, bodyFile: view.bodyFile });
				return undefined;
			}
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

	// 1 つの応答に並んだ edit / write の数をファイルごとに数える。整形 (post_edit) は、その最後の 1 件の後に 1 回だけ行う
	// (編集の間に整形が入ると、後ろの編集の oldText が整形で変わった本文と合わず、"must match" で失敗する)
	pi.on("message_end", async (event: any, ctx: any) => {
		const message = event?.message;
		if (message?.role !== "assistant" || !Array.isArray(message.content)) return undefined;
		const counts = new Map<string, number>();
		for (const block of message.content) {
			if (block?.type !== "toolCall" || (block.name !== `${PREFIX}edit` && block.name !== `${PREFIX}write`)) continue;
			const path = block.arguments?.path;
			if (typeof path !== "string" || path === "") continue;
			const abs = isAbsolute(path) ? path : resolve(ctx.cwd, path);
			counts.set(abs, (counts.get(abs) ?? 0) + 1);
		}
		batchTotals = counts;
		pendingEdits = new Map(counts);
		return undefined;
	});

	// フルガードが持たないツール (MCP など) の結果。tool_result の例外は無視されて生の結果が残るので、
	// ここでは投げずに結果ごと伏せる
	pi.on("tool_result", async (event, ctx) => {
		// guarded_edit の失敗に次の一手のヒントを足す (引数の不正は execute の前に起きるので、ここで扱う)。
		// edit / write の整形は、同じ応答の同じファイルへの最後の 1 件の後に 1 回だけ行う
		if (event.toolName === `${PREFIX}edit` || event.toolName === `${PREFIX}write`) {
			const canRead = (p: string) => decide("read", { path: p }, ctx.cwd).decision === "allow";
			const hinted = event.toolName === `${PREFIX}edit` ? await decorateEditResult(event as any, ctx.cwd, canRead) : undefined;
			return await finishEdit(event as any, hinted, ctx.cwd, ctx);
		}
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
	// write の append: true 用。書き込みだけを追記に替えた組み込みの定義 (mutation queue・親ディレクトリの作成は組み込みのまま)
	const appendDef = createWriteToolDefinition(cwd, { operations: appendOperations() });
	// 役割に無いツールは登録しない (モデルに見せない)。判定は判定器が別に行う。
	// 役割が rules.json に無ければ何も登録しない
	const roleTools: string[] = rules.profile_tools?.[ROLE] ?? [];
	for (const tool of TOOLS) {
		if (!roleTools.includes(tool)) continue;
		const def = definitions[tool];
		pi.registerTool({
			...def,
			// 説明の上書き (組み込みの文言は ...def で入る。tools-ext.ts)。read の tail と write の append は引数を足す
			...toolText(tool, PREFIX, def),
			...(tool === "read" ? { parameters: readParameters(Type) } : tool === "write" ? { parameters: writeParameters(Type) } : {}),
			name: `${PREFIX}${tool}`,
			// 最終の判定はここ。tool_call の後に別の拡張が入力を書き換えても、ここで止まる (spike の E1)
			async execute(toolCallId: string, params: any, signal: any, onUpdate: any, ctx: any) {
				const seen = decided.get(toolCallId);
				decided.delete(toolCallId);
				const input = JSON.stringify(params);
				const d = seen && seen.input === input ? seen.decision : decide(tool, params, ctx.cwd);
				const approved = seen?.approved === true && seen.input === input;
				// 確認で見せた --body-file が、承認の後に差し替えられていないこと
				if (approved && seen?.bodyFile) {
					const now = readBodyFile(seen.bodyFile.path, ctx.cwd, tool);
					if (!now.ok || now.text !== seen.bodyFile.text) {
						throw new Error("実行前の判定で止めた: 確認した本文のファイルが承認の後に変わった (もう一度確認が要る)");
					}
				}
				if (d.decision === "deny" || (d.decision === "ask" && !approved)) {
					throw new Error(`実行前の判定で止めた: ${d.decision}: ${d.decision === "deny" ? denyReason(tool, params, d) : d.reason}`);
				}
				// edit / write の後の整形 (Claude / Copilot の PostToolUse hook と同じスクリプト) は、tool_result の側で行う
				// (同じ応答に同じファイルへの編集が並ぶとき、最後の 1 件の後に 1 回だけ。finishEdit)
				if (tool === "edit" || tool === "write") {
					return tool === "write" && params?.append === true
						? appendResult(await appendDef.execute(toolCallId, params, signal, onUpdate, ctx), params.path, String(params.content ?? "").length)
						: await def.execute(toolCallId, params, signal, onUpdate, ctx);
				}
				if (tool === "read") {
					const canRead = (p: string) => decide("read", { path: p }, ctx.cwd).decision === "allow";
					return runRead(def, toolCallId, params, signal, onUpdate, ctx, { cwd: ctx.cwd, canRead });
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

	// MCP はフルガードから登録する。フルガードが抜ければ登録も消える (spike の E3)。
	// requires_env があるサーバは、その環境変数が空の機では登録しない (認証や URL が無い機で、動かないサーバを起動し続けない)
	for (const server of rules.mcp ?? []) {
		if (typeof server.requires_env === "string" && !(process.env[server.requires_env] ?? "").trim()) continue;
		pi.registerMcpServer(server.name, server.config);
	}

	// 承認つきの操作 (git commit・gh issue comment)。役割に action があり、子でないときだけ登録する
	const actionSpecs = loadActions(rules);
	if (!CHILD && roleTools.includes(ACTION_TOOL) && actionSpecs.length > 0) {
		pi.registerTool({
			name: `${PREFIX}${ACTION_TOOL}`,
			label: "action",
			promptSnippet: "Commit and post issue comments with approval (git commit, gh issue comment). Use instead of shell commands",
			promptGuidelines: [
				`Use ${PREFIX}${ACTION_TOOL} for git commit and gh issue comment. It asks the user for approval itself, exactly once; do not ask in chat or with ask beforehand. Stage files with ${PREFIX}bash first.`,
				...actionSpecs.map((a) => `${PREFIX}${ACTION_TOOL}: ${actionLine(a)}`),
			],
			description: actionDescription(actionSpecs),
			parameters: Type.Object(
				{
					action: Type.String({ description: "the id of the operation" }),
					params: Type.Record(Type.String(), Type.Unknown(), { description: "the arguments of the operation (all required)" }),
				},
				{ additionalProperties: false },
			),
			async execute(toolCallId: string, params: any, signal: any, _onUpdate: any, ctx: any) {
				decided.delete(toolCallId);
				return executeAction(
					{
						actions: actionSpecs,
						rules,
						child: CHILD,
						env: { ...AGENT_ENV, ...process.env },
						redact: redactText,
						judge: (input, cwd) => {
							const d = decide(ACTION_TOOL, input, cwd);
							return d.decision === "allow" ? null : `${d.decision}: ${d.reason}`;
						},
						dialog: dialogInOrder,
						absence,
						bell: () => {
							if (ctx.mode === "tui") process.stdout.write("\x07");
						},
					},
					params,
					signal,
					ctx,
				);
			},
		});
	}

	const agents: Record<string, any> = rules.agents ?? {};
	if (!CHILD && supportsChildTasks() && roleTools.includes("task") && Object.keys(agents).length > 0) registerTask(pi, agents);

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
const MAX_REPLY_CHARS = 20000;
// 読み取り専用の子の役割 (プロファイル)。利用者のコマンド (`btw`) が起動できるのはこれだけで、計画モード (`/plan`) の間に
// 起動・続きの依頼ができる子もこれだけ (see docs/change/0044-plan-agent.md)
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

// ─── 隔離 (worktree) ────────────────────────────────────────────────
// 契約・順序・残る限界は docs/change/0029-worktree-isolation.md の「W1 の実装計画」

// Landlock が使えるかは、プロセスの寿命の間 1 回だけ確かめる (null: 使える。文字列: 使えない理由)
let landlockProblem: string | null | undefined;
function checkLandlock(): string | null {
	if (isWindows()) return ISOLATION_UNSUPPORTED;
	if (landlockProblem !== undefined) return landlockProblem;
	const r = spawnSync("python3", [join(HERE, "landlock_exec.py"), "--check"], { encoding: "utf-8", timeout: 10_000 });
	if (r.status === 0) landlockProblem = null;
	else {
		const first = String(r.stderr ?? "").split("\n").find((l) => l.trim() !== "");
		landlockProblem = redactText((first ?? r.error?.message ?? `exit ${r.status}`).trim());
	}
	return landlockProblem;
}

// 子の書込可に足すデバイス (存在するものだけ)。refs/pi-agent と /dev/tty は含めない (S0)
const ISOLATION_DEVICES = ["/dev/dxg", "/dev/nvidiactl", "/dev/nvidia-uvm", "/dev/nvidia-uvm-tools", ...Array.from({ length: 8 }, (_, i) => `/dev/nvidia${i}`)];

// p が base と同じか中にあれば真 (文字列の前方一致にしない)
function isWithin(base: string, p: string): boolean {
	const r = relative(base, p);
	return r === "" || (r !== ".." && !r.startsWith(`..${sep}`) && !isAbsolute(r));
}

// realpath。存在しなければ、存在する最も近い親の realpath に残りを連結する
function realApprox(p: string): string {
	let cur = resolve(p);
	const rest: string[] = [];
	for (;;) {
		try {
			return join(realpathSync(cur), ...rest);
		} catch {
			const up = dirname(cur);
			if (up === cur) return join(cur, ...rest);
			rest.unshift(cur.slice(up.length).replace(/^[\\/]+/, ""));
			cur = up;
		}
	}
}

// p がリポジトリを包含する、またはリポジトリの中にあれば真
function overlapsRepo(repoReal: string, p: string): boolean {
	const real = realApprox(p);
	return isWithin(real, repoReal) || isWithin(repoReal, real);
}

type IsolationPlan = {
	id: string;
	repoRoot: string;
	cwd: string;
	command: string;
	args: string[];
	finalize: (job: Job, stopped: boolean) => Promise<void>;
	env: Record<string, string>; // 子の環境へ上書きする値
};

// 子の停止を確認した後に呼ばれる。回収の結果を job.isolationInfo に書く (例外は投げない)
function finalizeIsolation(repoRoot: string, id: string, readDeny: ReadDeny) {
	return async (job: Job, stopped: boolean): Promise<void> => {
		if (!stopped) {
			try {
				markKept(repoRoot, id, "child process group not confirmed stopped");
			} catch {
				// 記録を更新できなくても、worktree は消していない
			}
			job.isolationInfo = { kind: "kept", reason: "終了を確認できない" };
			return;
		}
		try {
			const res = collect(repoRoot, id, `${id}.patch`, readDeny, DEFAULT_LIMITS);
			job.isolationInfo = res.changed
				? { kind: "collected", ref: res.ref, patch: relative(repoRoot, res.patch.path), resultCommit: res.resultCommit, warnings: res.warnings }
				: { kind: "unchanged" };
		} catch (e) {
			if (e instanceof WorktreeError) {
				const cause = typeof e.detail.cause === "string" ? ` (${e.detail.cause})` : "";
				job.isolationInfo = { kind: "failed", code: e.code, reason: `${e.message}${cause}` };
			} else {
				job.isolationInfo = { kind: "failed", code: "error", reason: errMsg(e) };
			}
		}
	};
}

// 起動時の取り残しの照合。git は、記録か worktree の置き場があるときだけ呼ぶ。失敗しても起動は止めない
function reconcileOnStart(ctx: any) {
	if (!supportsChildTasks()) return;
	if (process.env.PI_HARNESS_CHILD === "1") return;
	if (process.env.PI_HARNESS_ROLE && process.env.PI_HARNESS_ROLE !== rules.default_role) return; // 子 (親が役割を渡す) は親の記録を照合しない
	try {
		const candidate = isolationTraceRoot(String(ctx.cwd));
		if (candidate === null) return;
		const repoRoot = findRepoRoot(candidate, STARTUP_LIMITS);
		if (repoRoot === null) return;
		const msg = startupReconcile(repoRoot, jobs.list().map((j) => j.id), STARTUP_LIMITS);
		if (msg !== null) warnUser(ctx, redactText(msg));
	} catch (e) {
		if (e instanceof WorktreeError && e.code === "timeout") warnUser(ctx, "隔離の取り残しの照合を時間切れで省略した");
		else warnUser(ctx, `隔離の取り残しの照合に失敗した: ${errMsg(e)}`);
	}
}

function buildReadDeny(): ReadDeny {
	const common = rules.judge.common;
	return { globs: loadFileGlobs(common, "read_deny_globs"), exceptions: loadReadDenyExceptions(common) };
}

// 隔離の起動の準備: Landlock の確認 → リポジトリ根 → ReadDeny → id → worktree の作成 → 子の起動の組み立て。
// 拒否は { error } で返す (黙って共有の作業ツリーで動かさない)。WorktreeError 以外は投げ直す
function prepareIsolation(parentCwd: string, childArgs: string[]): IsolationPlan | { error: string } {
	const refuse = (why: string) => ({ error: `isolation refused: ${why}` });
	if (isWindows()) return refuse(ISOLATION_UNSUPPORTED);
	const problem = checkLandlock();
	if (problem !== null) return refuse(`landlock_unavailable: ${problem}`);
	const readDeny = buildReadDeny();
	if (readDeny.globs.length === 0) return refuse("no_read_deny_rules: [file] read_deny_globs がありません");
	let repoRoot: string;
	let rel: string;
	let id: string;
	let record: IsolationRecord;
	try {
		const found = findRepoRoot(parentCwd);
		if (found === null) return refuse("not_a_git_repository");
		repoRoot = found;
		rel = relative(repoRoot, realpathSync(parentCwd));
		if (rel === ".." || rel.startsWith(`..${sep}`) || isAbsolute(rel)) return refuse("cwd_outside_repository");
		// 書込可の候補とリポジトリの重なりは createIsolation の前に判定する (worktree と管理領域・objects は意図して中にある)
		const agentDir = process.env.PI_CODING_AGENT_DIR;
		if (agentDir && overlapsRepo(repoRoot, agentDir)) return refuse("agent_dir_overlaps_repository");
		if (overlapsRepo(repoRoot, "/tmp")) return refuse("tmp_overlaps_repository");
		id = validateJobId(`job-${randomBytes(6).toString("hex")}`);
		record = createIsolation(repoRoot, id, readDeny, DEFAULT_LIMITS);
	} catch (e) {
		if (e instanceof WorktreeError) return refuse(`${e.code}: ${e.message}`);
		throw e;
	}
	// 作成の後の失敗は、作った worktree を片付けてから返す (片付けに失敗しても記録が残り、起動時の照合が拾う)
	const abandon = () => {
		try {
			discard(repoRoot, id);
		} catch {
			// 記録は残る
		}
	};
	try {
		const wt = record.worktree;
		const cwd = join(wt, rel);
		if (!existsSync(cwd)) {
			abandon();
			return refuse("cwd_missing_in_worktree");
		}
		const g = runGit(["rev-parse", "--path-format=absolute", "--git-common-dir"], { cwd: repoRoot });
		if (g.status !== 0) {
			abandon();
			return refuse("git_common_dir_unavailable");
		}
		const gitCommon = String(g.stdout).trim();
		// TMPDIR と ~/.cache がリポジトリと重なるときは書込可に含めない。TMPDIR は子の環境で /tmp に上書きする
		const env: Record<string, string> = {};
		const tmpdir = process.env.TMPDIR;
		const cache = join(homedir(), ".cache");
		let useTmpdir = tmpdir;
		if (tmpdir && overlapsRepo(repoRoot, tmpdir)) {
			env.TMPDIR = "/tmp";
			useTmpdir = undefined;
		}
		let useCache: string | undefined = cache;
		if (overlapsRepo(repoRoot, cache)) {
			useCache = undefined;
		}
		const writes = [wt, join(gitCommon, "worktrees", `pi-agent-${id}`), join(gitCommon, "objects"), process.env.PI_CODING_AGENT_DIR, useCache, useTmpdir, "/tmp", "/dev/null"]
			.filter((p): p is string => typeof p === "string" && p !== "" && existsSync(p));
		const wrapped = [
			join(HERE, "landlock_exec.py"),
			...[...new Set(writes)].flatMap((p) => ["--write", p]),
			...ISOLATION_DEVICES.flatMap((p) => ["--write-if-exists", p]),
			"--",
			"pi",
			...childArgs,
		];
		return { id, repoRoot, cwd, command: "python3", args: wrapped, finalize: finalizeIsolation(repoRoot, id, readDeny), env };
	} catch (e) {
		abandon();
		if (e instanceof WorktreeError) return refuse(`${e.code}: ${e.message}`);
		throw e;
	}
}

function registerTask(pi: ExtensionAPI, agents: Record<string, any>) {
	const names = Object.keys(agents);
	// 計画モード (`plan` 拡張) が、動いている子に書き込みの役割があるかを知らせるための、読み取り専用の役割の一覧
	(globalThis as any).__piReadOnlyAgents = new Set(names.filter((n) => READ_ONLY_CHILD_PROFILES.has(agents[n].profile)));
	// 計画モードの間に、書き込みの権限を持つ役割 (worker・commit など) の子を起動・続行させない理由。読み取り専用の役割なら null
	const planModeRefusal = (agentName: string): string | null => {
		const agent = agents[agentName];
		if (!agent || READ_ONLY_CHILD_PROFILES.has(agent.profile)) return null;
		const allowed = names.filter((n) => READ_ONLY_CHILD_PROFILES.has(agents[n].profile)).join(", ");
		return `plan mode is on (/plan): the agent "${agentName}" can change files or run commands, so it cannot be started or continued now. Only read-only agents (${allowed}) are allowed. Ask the user to leave plan mode (/plan) first.`;
	};
	const catalog = names.map((n) => `- ${n}: ${agents[n].description}`).join("\n");
	const text = (t: string, isError = false, details: Record<string, unknown> = {}) => ({
		content: [{ type: "text", text: t }],
		details,
		isError,
	});
	// 子のモデルと effort を呼び出しごとに選べるのは、カタログ (設定のプロバイダ) ・親の完全な provider/id・役割の既定だけ (model-choice.ts。CHG-0043)

	// 子を 1 つ起動する。枠は同期で確保する (並行する起動でも上限を超えない)
	type Spawned = { job: Job; model: string } | { error: string; full?: boolean };
	const spawnChild = (agentName: string, ctx: any, owner: { cwd: string; role: string }, modelOverride?: string, isolation?: boolean, effortOverride?: string): Spawned => {
		const agent = agents[agentName];
		if (!agent) throw new Error(`unknown agent: ${agentName}`);
		const parentModel = `${ctx.model.provider}/${ctx.model.id}`;
		const choice = resolveChoice({
			parentModel,
			catalog: rules.models ?? null,
			agentDefault: agent.model ?? null,
			agentDefaults: names.map((n) => agents[n].model).filter(Boolean),
			modelArg: modelOverride,
			effortArg: effortOverride,
		});
		const model = modelArgument(choice);
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
		const plan = isolation ? prepareIsolation(ctx.cwd, args) : null;
		if (plan && "error" in plan) return { error: plan.error };
		const abandon = () => {
			try {
				if (plan) discard(plan.repoRoot, plan.id);
			} catch {
				// 記録は残る (起動時の照合と /worktrees が拾う)
			}
		};
		let job: Job | null;
		try {
			job = jobs.create(
				plan
					? { id: plan.id, agent: agentName, args: plan.args, cwd: plan.cwd, env: { ...env, ...plan.env }, owner, command: plan.command, finalize: plan.finalize }
					: { agent: agentName, args, cwd: ctx.cwd, env, owner },
			);
		} catch (e) {
			abandon();
			throw e;
		}
		if (!job) {
			abandon();
			const live = jobs.list().map((j) => `- ${j.id} (${j.agent}, ${j.state})`).join("\n");
			return { error: `too many live child jobs (max ${MAX_JOBS}). Close one with {jobId, close:true}:\n${live}`, full: true };
		}
		job.choiceLine = describeChoice(choice);
		return { job, model };
	};

	// 隔離の job の結果の行。opt-in の間は、隔離しない worker にも「none」を出して誤認を防ぐ
	const isolationLines = (job: Job): string[] => {
		if (!job.finalized) return job.agent === "worker" ? ["- isolation: none"] : [];
		const info = job.isolationInfo;
		const head = "- isolation: worktree";
		if (!info) return [head, "- worktree: kept (not finalized). recover: /worktrees"];
		switch (info.kind) {
			case "collected":
				return [
					head,
					`- worktree: ref ${info.ref}; patch ${info.patch}; apply: git apply ${info.patch}${info.warnings.length > 0 ? `; warnings: ${info.warnings.join(", ")}` : ""}`,
				];
			case "unchanged":
				return [head, "- worktree: no changes (removed)"];
			case "kept":
				return [head, `- worktree: kept (${info.reason}). recover: /worktrees`];
			default:
				return [head, `- worktree: kept (${info.code}: ${info.reason}). recover: /worktrees`];
		}
	};

	// 子の結果を、見出し・承認待ち・警告 (ツールエラー)・job・答えの本文に分けて返す。
	// 子のツールエラーは答えに混ぜない (件数を絞り、同じものは 1 つにまとめる)
	const resultText = (job: Job, r: RoundResult, alive: boolean) => {
		const label = STATUS_LABEL[r.status] ?? r.status;
		const errors = [...new Set(r.errors)];
		const shown = errors.slice(0, MAX_LIST_ERRORS);
		// 形式検査は答えがある通常の完了だけ (結果の本文は変えない)
		const missing = r.status === "done" && r.answer ? auditFormat(r.answer) : [];
		// 依頼の守る条件の番号の突き合わせ (check_conditions の役割だけ)
		const cond = r.status === "done" && r.answer && agents[job.agent]?.check_conditions ? auditConditions(job.lastTask, r.answer) : null;
		const condLines =
			cond && (cond.noSection || cond.missing.length > 0)
				? [
						`conditions check (the request numbered ${cond.requested.join(", ")}; treat the plan as incomplete until the missing ones are recovered, and note that matching the ids does not prove a condition is met):`,
						cond.noSection ? "- missing: the section that matches the conditions (heading with 守る条件)" : `- missing in the matching section: ${cond.missing.join(", ")}`,
					]
				: [];
		const parts = [
			`child ${job.agent}: ${label}${r.note ? ` (${r.note})` : ""} [${fmtStats(r.stats)}]`,
			...(job.choiceLine ? [`- ${job.choiceLine}`] : []),
			...r.blocked.map((b) => `- needs the user's approval (not run): ${b}`),
			...(shown.length > 0
				? [`warnings (tool errors during the run; the answer below already accounts for them):`, ...shown.map((b) => `- tool error: ${b}`)]
				: []),
			...(errors.length > shown.length ? [`- ... and ${errors.length - shown.length} more tool errors`] : []),
			...(missing.length > 0
				? [`format check (the answer lacks the standard sections; verify its claims yourself):`, `- missing: ${missing.join(", ")}`]
				: []),
			...condLines,
			...(r.status === "done" && r.answer ? [`- calls: ${summarizeCalls(r.toolCalls ?? [])}`] : []),
			...isolationLines(job),
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

	const TODO_REQUIRED_AGENTS = new Set(["explore", "review", "worker"]);

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
			.run(message, { timeoutMs: roundTimeoutMs(agents, job.agent), wrapUpMessage: WRAP_UP_MESSAGE })
			.then(async (r) => {
				if (!keep) job.close();
				// 隔離の job は、停止の確認と回収が終わってから結果を組み立てる
				if (job.finalized) await job.finalized;
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
			const r = await sp.job.run(task, { signal, timeoutMs: roundTimeoutMs(agents, agentName), wrapUpMessage: WRAP_UP_MESSAGE });
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
			`${PREFIX}task with agent explore / review / worker requires \`todo\` (the id of a todo item you added for this work) when the todo tool is active; without it the call fails.`,
			`For several independent tasks, use {tasks:[{agent, task}, ...]} (up to ${MAX_BATCH}); tasks beyond the live-job limit wait instead of failing.`,
			`Set \`model\` or \`effort\` on ${PREFIX}task only when the user asks for a specific model or thinking level; otherwise omit them (the role default is used). The result always states the model and effort that were used. Use only models from the list in the tool description.`,
		],
		description:
			"Run a task in a child agent. The child is a separate pi process with the same guard, and cannot see this conversation, " +
			"so put everything it needs into `task`. Forms (do not mix their fields):\n" +
			"- new: {agent, task, keep?, background?, model?, effort?, todo?, isolation?}. The child stops when it finishes unless keep=true; then it stays idle and a jobId is returned. " +
			"background=true returns at once and notifies you on completion. model and effort: see the list below (set them only when the user asks; omit them to use the role default). todo is a todo id to update when the child finishes; it is required for explore / review / worker when the todo tool is active (add a todo item first). " +
			"isolation: \"worktree\" runs the worker isolated in a git worktree (a single new worker task only; not with keep).\n" +
			"- tasks: {tasks:[{agent, task, model?, effort?}, ...], background?}. Runs them in parallel (waiting for free slots) and returns every result.\n" +
			"- follow-up: {jobId, task, background?}. Sends another request to a kept child; it remembers the earlier conversation. One request at a time per job.\n" +
			"- status: {jobId, status:true}, or list: {list:true}. State, elapsed time, last tool, calls and tokens of children.\n" +
			"- steer: {jobId, steer:\"...\"}. Sends an extra instruction to a running child (delivered after its current turn).\n" +
			"- abort: {jobId, abort:true}. Stops the child's current round; the child stays for a follow-up.\n" +
			"- close: {jobId, close:true}. Stops the kept child.\n" +
			"Follow-ups cannot change the model or effort.\n" +
			(catalogText(rules.models) ? `${catalogText(rules.models)}\n` : "") +
			"Agents:\n" +
			catalog,
		parameters: Type.Object(
			{
				// "" は埋め草 (厳格なスキーマのモデルが使わない引数を空で埋める。B1 の F5)。実際の形の判定は parseTaskInput
				agent: Type.Optional(Type.Union([...names, ""].map((n) => Type.Literal(n)), { description: "new task only" })),
				task: Type.Optional(Type.String({ description: "What the child should do, with all the context it needs" })),
				keep: Type.Optional(Type.Boolean({ description: "new task only: keep the child idle after it finishes, for follow-ups" })),
				background: Type.Optional(Type.Boolean({ description: "new / tasks / follow-up: return at once and be notified on completion" })),
				model: Type.Optional(Type.String({ description: "new task only: a model from the catalog in this description (only when the user asks), your own model, or a declared agent's model" })),
				effort: Type.Optional(Type.Union([...EFFORTS, ""].map((e) => Type.Literal(e)), { description: "new task only: thinking level (only when the user asks). \"\" means unset" })),
				todo: Type.Optional(Type.Number({ description: "new task only: a todo id to mark done (or annotate) when the child finishes" })),
				isolation: Type.Optional(Type.Union([Type.Literal("worktree"), Type.Literal("")], { description: "new worker task only: \"worktree\" runs the worker isolated in a git worktree (not with keep)" })),
				tasks: Type.Optional(
					Type.Array(
						Type.Object(
							{ agent: Type.String(), task: Type.String(), model: Type.Optional(Type.String()), effort: Type.Optional(Type.Union([...EFFORTS, ""].map((e) => Type.Literal(e)))) },
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

			// ─── 計画モード (/plan) の間は、読み取り専用の役割だけ ───
			// 起動 (単発・並列)・続きの依頼・steer が対象。状態・一覧・abort・close は止めるだけなので通す
			if ((globalThis as any).__piPlanMode === true) {
				let refused: string | null = null;
				if (input.kind === "new") refused = planModeRefusal(input.agent);
				else if (input.kind === "batch") refused = input.tasks.map((t) => planModeRefusal(t.agent)).find((r) => r !== null) ?? null;
				else if (input.kind === "followup" || input.kind === "steer") {
					const target = jobs.get(input.jobId);
					if (target && own(target)) refused = planModeRefusal(target.agent);
				}
				if (refused) return text(refused, true);
			}

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
								sp = spawnChild(it.agent, ctx, owner, it.model, undefined, it.effort);
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
							const r = await job.run(it.task, { signal: sig, timeoutMs: roundTimeoutMs(agents, job.agent), wrapUpMessage: WRAP_UP_MESSAGE });
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
				// todo ツールが有効な実行だけ、委譲に ToDo の項目を要求する (batch は対象外)
				if (TODO_REQUIRED_AGENTS.has(input.agent) && input.todo === undefined && pi.getActiveTools().some((n) => n === "todo")) {
					return text(`todo is required for ${input.agent}: add a todo item for this work and pass its id as \`todo\``, true);
				}
				const sp = spawnChild(input.agent, ctx, owner, input.model, input.isolation === "worktree", input.effort);
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
							(job.choiceLine ? `${job.choiceLine}\n` : "") +
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
				return text(`started ${job.agent} in the background as ${job.id}${job.choiceLine ? ` (${job.choiceLine})` : ""}. You will be notified when it finishes (status: {jobId, status:true}, steer: {jobId, steer:"..."}, abort: {jobId, abort:true}).`, false, {
					jobId: job.id,
					background: true,
				});
			}

			let r: RoundResult;
			try {
				r = await job.run(message, { signal, timeoutMs: roundTimeoutMs(agents, job.agent), wrapUpMessage: WRAP_UP_MESSAGE });
				// 隔離の job は、停止の確認と回収を待つ (待つ間も動いている子として見せる)。abort されたら待たない
				if (job.finalized && !signal?.aborted) await job.finalized;
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

	// 承認が取れず退避したコミット (refs/pi/pending/) の一覧・表示・破棄。利用者専用 (モデルは呼べない)。入力と同じように不在を解除する (コマンドは input イベントより先に処理される)
	pi.registerCommand("pending", {
		description: "承認が取れず退避したコミットの一覧・表示・破棄: /pending [list | show <ref> | drop <ref>]",
		handler: async (args: string, ctx: any) => {
			absence.gen++;
			absence.absent = false;
			const cwd: string = ctx.cwd ?? process.cwd();
			const [sub = "list", arg = ""] = String(args ?? "").trim().split(/\s+/);
			const full = arg.startsWith("refs/") ? arg : `${PENDING_PREFIX}${arg}`;
			let text: string;
			if (sub === "" || sub === "list") {
				const all = listPending(cwd);
				text = all.length === 0 ? "退避したコミットは無い" : all.map((e) => `${e.ref.slice(PENDING_PREFIX.length)}  ${e.oid.slice(0, 7)}  ${e.subject}  (${e.branch || "-"})`).join("\n");
			} else if (sub === "show" && arg) {
				text = showPending(cwd, full) || "見つからない (/pending list で ref を確かめる)";
			} else if (sub === "drop" && arg) {
				text = dropPending(cwd, full) ? `破棄した: ${full} (到達用の ref を外した。オブジェクトは git gc まで残る)` : "破棄できなかった (ref が無い・退避の ref ではない)";
			} else {
				text = "/pending [list | show <ref> | drop <ref>]";
			}
			ctx.ui?.notify?.(redactText(text), "info");
		},
	});
	// 隔離 (worktree) の一覧・回収のやり直し・破棄。利用者専用 (モデルは呼べない)
	pi.registerCommand("worktrees", {
		description: "隔離 (worktree) の一覧・回収のやり直し・破棄: /worktrees [show|collect|discard <jobId> | unlock]",
		handler: async (args: string, ctx: any) => {
			let repoRoot: string | null = null;
			try {
				repoRoot = findRepoRoot(ctx.cwd);
			} catch {
				repoRoot = null;
			}
			const res = await runWorktreesCommand(String(args ?? ""), {
				repoRoot,
				liveJobIds: jobs.list().map((j) => j.id),
				readDeny: buildReadDeny,
				confirm: ctx.hasUI ? (title: string, body: string) => confirmInOrder(ctx, title, body) : null,
			});
			ctx.ui?.notify?.(redactText(res.text), res.level);
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
// markdownlint が残した違反と、整形で本文が変わったことだけをモデルへ返す。失敗しても編集は成功のまま。
//
// ★編集と整形の順番: 同じ応答に同じファイルへの edit / write が並んだとき、整形は、その最後の 1 件の後に 1 回だけ。
// 編集の間に整形が入ると、後ろの編集の oldText (整形前の本文を見て作ったもの) が合わず、
// "The old text must match exactly" で失敗する (遅いマシンや承認待ちで、編集の開始がずれると起きやすい)。
// see docs/spec/guard/pi-extensions.md#整形

// 応答ごとの edit / write の数 (絶対パスごと)。batchTotals は応答の合計、pendingEdits はまだ結果が出ていない残り
let batchTotals = new Map<string, number>();
let pendingEdits = new Map<string, number>();

const FORMAT_NOTICE_MAX_BYTES = 2 * 1024 * 1024;
const SIBLING_EDIT_HINT =
	"同じ応答で同じファイルへ複数の編集を並べると、前の編集が先に適用されている (順番に 1 件ずつ)。ファイルを read し直し、" +
	"変更は 1 回の guarded_edit の edits[] にまとめる (すべて元の本文に対して照合される)";

function readSmallText(abs: string): string | null {
	try {
		if (statSync(abs).size > FORMAT_NOTICE_MAX_BYTES) return null;
		return readFileSync(abs, "utf-8");
	} catch {
		return null;
	}
}

/** 整形で変わった行の概数 (後にあって前に無い行の数)。 */
function changedLineCount(before: string, after: string): number {
	const seen = new Map<string, number>();
	for (const line of before.split("\n")) seen.set(line, (seen.get(line) ?? 0) + 1);
	let changed = 0;
	for (const line of after.split("\n")) {
		const left = seen.get(line) ?? 0;
		if (left > 0) seen.set(line, left - 1);
		else changed++;
	}
	return changed;
}

// 整形に使う bash は 1 回だけ探す。見つからなければ 1 回だけ知らせて省略する (Windows の Git Bash なし)
let postEditBash: string | null | undefined;
let bashNoticeShown = false;
function postEditBashPath(ctx: any): string | null {
	if (postEditBash === undefined) postEditBash = findBash(process.platform, process.env, existsSync);
	if (postEditBash === null && !bashNoticeShown) {
		bashNoticeShown = true;
		warnUser(ctx, NO_BASH_NOTICE);
	}
	return postEditBash;
}

/** hook を 1 つ非同期に走らせる (同期で待つと、整形の間、他の tool call の処理も止まる)。失敗・時間切れは status null。 */
function runPostEditHook(hook: any, abs: string, cwd: string, ctx?: any): Promise<{ status: number | null; stderr: string }> {
	const runner = hook.runner === "bash" ? postEditBashPath(ctx) : hook.runner;
	if (runner === null) return Promise.resolve({ status: null, stderr: "" });
	return new Promise((done) => {
		let stderr = "";
		let finished = false;
		const finish = (status: number | null) => {
			if (finished) return;
			finished = true;
			clearTimeout(timer);
			done({ status, stderr });
		};
		const child = spawn(runner, [hook.script], { cwd, stdio: ["pipe", "ignore", "pipe"] });
		const timer = setTimeout(() => {
			child.kill();
			finish(null);
		}, 30000);
		child.stderr.on("data", (chunk: Buffer) => {
			if (stderr.length < 65536) stderr += chunk.toString("utf-8");
		});
		child.on("error", () => finish(null));
		child.on("close", (code) => finish(code));
		child.stdin.on("error", () => {});
		child.stdin.end(JSON.stringify({ tool_input: { path: abs } }));
	});
}

/** abs を整形する (書き込みの順番待ちの中で)。返るのは markdownlint の警告と、整形で変わった行数。 */
async function formatFile(abs: string, cwd: string, ctx?: any): Promise<{ warnings: string[]; changed: number }> {
	const warnings: string[] = [];
	let changed = 0;
	if (!rules.post_edit?.length) return { warnings, changed };
	await withFileMutationQueue(abs, async () => {
		const before = readSmallText(abs);
		for (const hook of rules.post_edit) {
			const r = await runPostEditHook(hook, abs, cwd, ctx);
			// exit 2 は「エージェントへ警告する」(hook_emit_posttool_warn)。stderr が警告の本文
			if (r.status === 2 && r.stderr.trim()) warnings.push(r.stderr.trim());
		}
		const after = readSmallText(abs);
		if (before !== null && after !== null && before !== after) changed = changedLineCount(before, after);
	});
	return { warnings, changed };
}

/**
 * guarded_edit / guarded_write の tool_result の仕上げ。hinted は失敗のヒントを足した結果 (無ければ undefined)。
 * 同じ応答の同じファイルへの編集のうち最後の 1 件だけが整形を行い、結果へ警告と「整形で本文が変わった」を足す。
 */
async function finishEdit(event: any, hinted: { content: any[] } | undefined, cwd: string, ctx?: any): Promise<{ content: any[] } | undefined> {
	const path = event?.input?.path;
	if (typeof path !== "string" || path === "") return hinted;
	const abs = isAbsolute(path) ? path : resolve(cwd, path);
	const known = pendingEdits.has(abs);
	const remaining = (pendingEdits.get(abs) ?? 1) - 1;
	if (known) {
		if (remaining > 0) pendingEdits.set(abs, remaining);
		else pendingEdits.delete(abs);
	}
	const base: any[] = hinted?.content ?? (Array.isArray(event.content) ? event.content : []);
	if (event.isError) {
		// 同じ応答に同じファイルへの編集が並んでいて、照合に失敗したときは、並べ方の影響を示す
		const first = base.find((b: any) => b?.type === "text" && typeof b.text === "string")?.text ?? "";
		if ((batchTotals.get(abs) ?? 1) > 1 && /^(Could not find|Found \d+ occurrences)/.test(first)) {
			return { content: [...base, { type: "text", text: `\n${SIBLING_EDIT_HINT}` }] };
		}
		return hinted;
	}
	// 同じ応答の後続の編集が残っている間は整形しない (最後の 1 件が行う)
	if (remaining > 0) return hinted;
	const { warnings, changed } = await formatFile(abs, cwd, ctx);
	const notes: string[] = [];
	if (warnings.length) notes.push(redactText(warnings.join("\n")));
	if (changed > 0) {
		notes.push(`[整形] hook が ${relative(cwd, abs) || abs} を書き換えた (約 ${changed} 行)。続けて同じ箇所を編集するときは、先に read し直す`);
	}
	if (!notes.length) return hinted;
	return { content: [...base, { type: "text", text: `\n${notes.join("\n")}` }] };
}
