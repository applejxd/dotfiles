// `/agents`: いま動いている子エージェント (task / guarded_task) の一覧を出す。
// 子を起動する側 (subagents / ハーネス) が globalThis.__piChildren に登録し、終わると外す。
// see docs/spec/pi-harness.md#自作の拡張-todo--plan--btw
import type { ExtensionAPI, ExtensionCommandContext } from "@earendil-works/pi-coding-agent";
import { DynamicBorder, getMarkdownTheme } from "@earendil-works/pi-coding-agent";
import { Container, Markdown, matchesKey, Text } from "@earendil-works/pi-tui";

type Running = { agent: string; model: string; task: string; pid?: number; startedAt: number };

const TASK_PREVIEW = 70;

function elapsed(ms: number): string {
	const s = Math.max(0, Math.floor(ms / 1000));
	return s < 60 ? `${s}s` : `${Math.floor(s / 60)}m${String(s % 60).padStart(2, "0")}s`;
}

const cell = (s: string) => s.replace(/\s+/g, " ").replace(/\|/g, "\\|").trim();

function render(): string {
	const registry = (globalThis as { __piChildren?: Map<string, Running> }).__piChildren;
	const rows = registry ? [...registry.values()].sort((a, b) => a.startedAt - b.startedAt) : [];
	if (rows.length === 0) return "動いている子エージェントはありません。";
	const now = Date.now();
	return [
		`動いている子エージェント: ${rows.length}`,
		"",
		"| agent | model | 経過 | pid | task |",
		"| --- | --- | --- | --- | --- |",
		...rows.map((r) => {
			const task = cell(r.task);
			const preview = task.length > TASK_PREVIEW ? `${task.slice(0, TASK_PREVIEW)}…` : task;
			return `| ${cell(r.agent)} | ${cell(r.model)} | ${elapsed(now - r.startedAt)} | ${r.pid ?? "-"} | ${preview} |`;
		}),
	].join("\n");
}

async function show(body: string, ctx: ExtensionCommandContext) {
	if (ctx.mode !== "tui") {
		ctx.ui.notify(body, "info");
		return;
	}
	await ctx.ui.custom((_tui, theme, _kb, done) => {
		const container = new Container();
		const border = new DynamicBorder((s: string) => theme.fg("accent", s));
		container.addChild(border);
		container.addChild(new Markdown(body, 1, 1, getMarkdownTheme()));
		container.addChild(new Text(theme.fg("dim", "Enter / Esc で閉じる"), 1, 0));
		container.addChild(border);
		return {
			render: (width: number) => container.render(width),
			invalidate: () => container.invalidate(),
			handleInput: (data: string) => {
				if (matchesKey(data, "enter") || matchesKey(data, "escape")) done(undefined);
			},
		};
	});
}

export default function (pi: ExtensionAPI) {
	pi.registerCommand("agents", {
		description: "いま動いている子エージェントの一覧",
		handler: async (_args, ctx) => show(render(), ctx),
	});
}
