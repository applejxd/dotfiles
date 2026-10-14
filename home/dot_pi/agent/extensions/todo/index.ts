// タスクリスト。`todo` ツールと `/todos` コマンド。状態はツール結果の details に持たせるので、
// セッションの分岐や再開でも、その時点の状態に戻る。
// see docs/spec/pi-guard.md#自作の拡張-todo--plan--btw
import { StringEnum } from "@earendil-works/pi-ai";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";

type Todo = { id: number; text: string; done: boolean };
type Details = { todos: Todo[]; nextId: number; error?: string };

const Params = Type.Object({
	action: StringEnum(["list", "add", "toggle", "clear"] as const),
	text: Type.Optional(Type.String({ description: "add のときの内容" })),
	id: Type.Optional(Type.Number({ description: "toggle のときの ID" })),
});

export default function (pi: ExtensionAPI) {
	let todos: Todo[] = [];
	let nextId = 1;

	const render = () => (todos.length ? todos.map((t) => `[${t.done ? "x" : " "}] #${t.id}: ${t.text}`).join("\n") : "(空)");
	const status = (ctx: ExtensionContext) => {
		if (!ctx.hasUI) return;
		const done = todos.filter((t) => t.done).length;
		ctx.ui.setStatus("todo", todos.length ? `📋 ${done}/${todos.length}` : undefined);
	};
	const rebuild = (ctx: ExtensionContext) => {
		todos = [];
		nextId = 1;
		for (const entry of ctx.sessionManager.getBranch()) {
			if (entry.type !== "message") continue;
			const msg = entry.message;
			if (msg.role !== "toolResult" || msg.toolName !== "todo") continue;
			const d = msg.details as Details | undefined;
			if (d) {
				todos = d.todos;
				nextId = d.nextId;
			}
		}
		status(ctx);
	};
	pi.on("session_start", async (_e, ctx) => rebuild(ctx));
	pi.on("session_tree", async (_e, ctx) => rebuild(ctx));

	pi.registerTool({
		name: "todo",
		label: "Todo",
		description:
			"複数の手順がある作業のタスクリストを管理する。action: list / add (text) / toggle (id: 完了と未完の切り替え) / clear。" +
			"3 手順以上の作業では、始める前に add で手順を並べ、終わるたびに toggle する。",
		parameters: Params,
		async execute(_id, params, _signal, _onUpdate, ctx) {
			let error: string | undefined;
			let message = "";
			switch (params.action) {
				case "add":
					if (!params.text) error = "add には text が要る";
					else {
						const t = { id: nextId++, text: params.text, done: false };
						todos.push(t);
						message = `追加: #${t.id} ${t.text}`;
					}
					break;
				case "toggle": {
					const t = todos.find((x) => x.id === params.id);
					if (!t) error = `#${params.id} が無い`;
					else {
						t.done = !t.done;
						message = `#${t.id} を${t.done ? "完了" : "未完"}にした`;
					}
					break;
				}
				case "clear":
					message = `${todos.length} 件を消した`;
					todos = [];
					nextId = 1;
					break;
				default:
					break;
			}
			status(ctx);
			const details: Details = { todos: todos.map((t) => ({ ...t })), nextId, ...(error ? { error } : {}) };
			return { content: [{ type: "text", text: `${error ? `エラー: ${error}` : message}\n${render()}`.trim() }], details };
		},
	});

	pi.registerCommand("todos", {
		description: "今のブランチのタスクリストを表示する",
		handler: async (_args, ctx) => {
			const done = todos.filter((t) => t.done).length;
			ctx.ui.notify(todos.length ? `${done}/${todos.length} 完了\n${render()}` : "タスクはありません", "info");
		},
	});
}
