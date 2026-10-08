// pi のハーネス。組み込みのツールの代わりに guarded_* のツールを登録し、判定 API (decide.py) で
// 実行してよいかを決める。起動は `pi -nbt -ne -e ~/.config/pi/harness`。
// see docs/spec/pi-harness.md
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
import { spawnSync } from "node:child_process";
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

type Decision = { decision: "allow" | "ask" | "deny"; reason: string; source: string };

const HERE = dirname(fileURLToPath(import.meta.url));
// 組み込みと同じ名前にしないこと。/reload でハーネスが抜けたとき、組み込みが同じ名前で戻って
// 判定なしに動く (docs/research/agents/pi-harness-spike.md の E1)
const PREFIX = "guarded_";
const TOOLS = ["bash", "read", "edit", "write", "grep", "find", "ls"] as const;
const ROLE = process.env.PI_HARNESS_ROLE || "implementer";
const BYPASS = process.env.PI_HARNESS_BYPASS === "1";
const BOUNDARY = process.env.PI_HARNESS_BOUNDARY === "1";
const DECIDE_TIMEOUT_MS = 15000;

// rules.json が読めなければ読み込みごと失敗させる。起動は止まり、/reload ではツールが無くなる
const rules = JSON.parse(readFileSync(join(HERE, "rules.json"), "utf-8"));
if (typeof rules.decide !== "string" || !rules.redact || !Array.isArray(rules.redact.rule)) {
	throw new Error("rules.json に decide / redact が無い (chezmoi apply で作り直す)");
}
const AGENT_ENV: Record<string, string> = rules.agent_env ?? {};
const REDACT_RULES = rules.redact.rule.map((r: { name: string; pattern: string }) => ({
	name: r.name,
	re: new RegExp(r.pattern, "gi"),
}));
const DENY_PATH: RegExp[] = (rules.redact.deny_path ?? []).map((p: string) => new RegExp(p));
// /g を付けない (.test の lastIndex が残る)
const DENY_PATH_UNLESS = rules.redact.deny_path_unless ? new RegExp(rules.redact.deny_path_unless) : null;

// ─── 判定 ───────────────────────────────────────────────────────────

export function decide(tool: string, input: unknown, cwd: string): Decision {
	const request = { tool, input, cwd, role: ROLE, bypass: BYPASS, boundary: BOUNDARY };
	const r = spawnSync("python3", [rules.decide], {
		input: JSON.stringify(request),
		encoding: "utf-8",
		timeout: DECIDE_TIMEOUT_MS,
	});
	if (r.error) return { decision: "deny", reason: `判定器を呼べない: ${r.error.message}`, source: "error" };
	if (r.status !== 0) return { decision: "deny", reason: `判定器が異常終了した (${r.status})`, source: "error" };
	try {
		const out = JSON.parse(r.stdout);
		if (["allow", "ask", "deny"].includes(out?.decision) && typeof out?.reason === "string") return out;
	} catch {}
	// 形の正しい応答以外は deny (空の応答を allow と読まない)
	return { decision: "deny", reason: `判定器の応答が不正: ${JSON.stringify(String(r.stdout).slice(0, 120))}`, source: "error" };
}

// tool_call で判定した入力と結果。execute() で同じ入力なら判定を使い回す (判定 1 回 0.1 秒ほど)。
// 入力が書き換わっていれば判定し直す
const decided = new Map<string, { input: string; decision: Decision; approved: boolean }>();

// 確認は 1 件ずつ出す。TUI の confirm は 1 枠を共有し、後の確認が先の確認を置き換える
// (codemode の中で並べた呼び出しで先の確認が永久に止まった。spike の E3)
let confirmQueue: Promise<unknown> = Promise.resolve();
function confirmInOrder(ctx: any, title: string, body: string): Promise<boolean> {
	const run = confirmQueue.then(() =>
		ctx.signal?.aborted ? false : ctx.ui.confirm(title, body, { signal: ctx.signal }),
	);
	confirmQueue = run.catch(() => undefined);
	return run.then((v: unknown) => v === true).catch(() => false);
}

function baseName(toolName: string): string {
	return toolName.startsWith(PREFIX) ? toolName.slice(PREFIX.length) : toolName;
}

// ─── 伏字化 ─────────────────────────────────────────────────────────

function redactText(text: string): string {
	let out = text;
	// 置換文字列にせず関数で返す ($& などを解釈させない)
	for (const r of REDACT_RULES) out = out.replace(r.re, () => `[伏字:${r.name}]`);
	return out;
}

function redactValue(v: any): any {
	if (typeof v === "string") return redactText(v);
	if (Array.isArray(v)) return v.map(redactValue);
	if (v && typeof v === "object") return Object.fromEntries(Object.entries(v).map(([k, x]) => [k, redactValue(x)]));
	return v;
}

// content・structuredContent・details の全部を伏せる。details はモデルへ送られないが、
// セッション・イベント・画面に残る (bash の details.truncation.content に生の出力。spike の E3)
function redactResult(r: any): any {
	if (!r) return r;
	return {
		...r,
		content: redactValue(r.content),
		...(r.details !== undefined ? { details: redactValue(r.details) } : {}),
		...(r.structuredContent !== undefined ? { structuredContent: redactValue(r.structuredContent) } : {}),
	};
}

// コマンドが保護対象のパスを参照していれば、どこが秘密か分からないので出力ごと伏せる
function deniedPathIn(command: string): string | null {
	if (DENY_PATH_UNLESS?.test(command)) return null;
	for (const token of command.split(/[\s;|&<>()"'`]+/)) {
		if (!token || (!/[/\\]/.test(token) && !token.startsWith("~") && !token.startsWith("."))) continue;
		const p = token.replace(/\\/g, "/");
		if (DENY_PATH.some((re) => re.test(p))) return token;
	}
	return null;
}

function withheld(hit: string): any {
	const text = `[伏字] 保護対象のパス (${hit}) を参照したため、このコマンドの出力を伏せました。`;
	return { content: [{ type: "text", text }], details: undefined, structuredContent: { withheld: text } };
}

// ─── 登録 ───────────────────────────────────────────────────────────

export default function (pi: ExtensionAPI) {
	pi.on("tool_call", async (event, ctx) => {
		const tool = baseName(event.toolName);
		const d = decide(tool, event.input, ctx.cwd);
		const input = JSON.stringify(event.input);
		if (d.decision === "deny") return { block: true, reason: d.reason };
		if (d.decision === "ask") {
			const ok =
				ctx.hasUI && (await confirmInOrder(ctx, "実行してよいですか？", `${tool}: ${input}\n理由: ${d.reason}`));
			if (!ok) return { block: true, reason: `not approved: ${d.reason}` };
			decided.set(event.toolCallId, { input, decision: d, approved: true });
			return undefined;
		}
		decided.set(event.toolCallId, { input, decision: d, approved: false });
		return undefined;
	});

	// ハーネスが持たないツール (MCP など) の結果。tool_result の例外は無視されて生の結果が残るので、
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
	for (const tool of TOOLS) {
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

	// 既定の圧縮は read / edit / write の名前でファイルの操作を拾うので、別名の分を足す。
	// preparation は既定の要約にそのまま渡る (spike の E2)
	pi.on("session_before_compact", async (event) => {
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
		return undefined;
	});
}
