// タスクリスト。`todo` ツールと `/todos` コマンド。リストは 1 つで、勝手には消さない。
// 状態は、ツール結果の details と、利用者の操作 (/todos clear・tidy) の custom エントリに持たせる。
// どちらもセッションに残るので、分岐・再開・圧縮のあとも、その時点の状態に戻る。
// see docs/spec/pi-guard.md#自作の拡張-todo--plan--btw
import { StringEnum } from "@earendil-works/pi-ai";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";

type Status = "pending" | "in_progress" | "done" | "cancelled";
type Todo = { id: number; text: string; status: Status };
type Details = { todos: Todo[]; nextId: number; error?: string };

const STATUSES = ["pending", "in_progress", "done", "cancelled"] as const;
const MARK: Record<Status, string> = { pending: "[ ]", in_progress: "[>]", done: "[x]", cancelled: "[-]" };
const STATE_ENTRY = "todo-state";

const Params = Type.Object({
	action: StringEnum(["list", "add", "set", "update", "remove", "clear"] as const),
	text: Type.Optional(Type.String({ description: "add (1 件) / update の内容" })),
	texts: Type.Optional(Type.Array(Type.String(), { description: "add で複数件を一度に足す" })),
	id: Type.Optional(Type.Number({ description: "set / update / remove の対象の ID" })),
	status: Type.Optional(StringEnum(STATUSES, { description: "set の新しい状態" })),
	all: Type.Optional(Type.Boolean({ description: "list で完了・中止も含めて全件を出す" })),
});

// 旧形式 ({ id, text, done }) の状態も読む。再開した古いセッションが壊れないように
function normalize(raw: unknown): Todo[] {
	if (!Array.isArray(raw)) return [];
	const out: Todo[] = [];
	for (const t of raw as any[]) {
		if (typeof t?.id !== "number" || typeof t?.text !== "string") continue;
		const status: Status = (STATUSES as readonly string[]).includes(t.status) ? t.status : t.done === true ? "done" : "pending";
		out.push({ id: t.id, text: t.text, status });
	}
	return out;
}

export default function (pi: ExtensionAPI) {
	let todos: Todo[] = [];
	let nextId = 1;

	const open = () => todos.filter((t) => t.status === "pending" || t.status === "in_progress");
	const line = (t: Todo) => `${MARK[t.status]} #${t.id}: ${t.text}`;
	// モデルへ返す一覧。完了・中止は件数にたたむ (足していくほど文脈を占めないように)。all なら全件
	const render = (all = false) => {
		if (todos.length === 0) return "(空)";
		const shown = all ? todos : open();
		const done = todos.filter((t) => t.status === "done").length;
		const cancelled = todos.filter((t) => t.status === "cancelled").length;
		const rest = all || (done === 0 && cancelled === 0) ? "" : `完了 ${done} 件・中止 ${cancelled} 件 (全件は list の all)`;
		return [...shown.map(line), ...(shown.length === 0 && !all ? ["(未完了なし)"] : []), ...(rest ? [rest] : [])].join("\n");
	};
	const status = (ctx: ExtensionContext) => {
		if (!ctx.hasUI) return;
		const counted = todos.filter((t) => t.status !== "cancelled");
		if (counted.length === 0) return ctx.ui.setStatus("todo", undefined);
		const done = counted.filter((t) => t.status === "done").length;
		const doing = todos.find((t) => t.status === "in_progress");
		const head = open().length === 0 ? "✅" : "📋";
		const tail = doing ? ` ▶ ${doing.text.length > 24 ? `${doing.text.slice(0, 24)}…` : doing.text}` : "";
		ctx.ui.setStatus("todo", `${head} ${done}/${counted.length}${tail}`);
	};
	// 今のブランチの、最後の状態に戻す (ツール結果の details か、利用者の操作の custom エントリ)
	const rebuild = (ctx: ExtensionContext) => {
		todos = [];
		nextId = 1;
		for (const entry of ctx.sessionManager.getBranch() as any[]) {
			let d: Partial<Details> | undefined;
			if (entry.type === "message" && entry.message?.role === "toolResult" && entry.message?.toolName === "todo") d = entry.message.details;
			else if (entry.type === "custom" && entry.customType === STATE_ENTRY) d = entry.data;
			if (!d) continue;
			todos = normalize(d.todos);
			nextId = typeof d.nextId === "number" ? d.nextId : todos.reduce((m, t) => Math.max(m, t.id), 0) + 1;
		}
		status(ctx);
	};
	pi.on("session_start", async (_e, ctx) => rebuild(ctx));
	pi.on("session_tree", async (_e, ctx) => rebuild(ctx));

	pi.registerTool({
		name: "todo",
		label: "Todo",
		// promptSnippet が無いと Available tools に出ない
		promptSnippet: "Keep the task list: add steps, mark them in_progress / done, list them",
		promptGuidelines: [
			"For work with 3 or more steps, use todo add to list the steps before starting; set the current item to in_progress (one at a time) and to done when finished.",
		],
		description:
			"作業のタスクリスト (1 つ)。action: list (all=true で完了・中止も) / add (text か texts で複数) / " +
			"set (id と status: pending・in_progress・done・cancelled。何度呼んでも同じ結果) / update (id と text) / remove (id、誤って足したものだけ) / clear。" +
			"3 手順以上の作業では、始める前に add で手順を並べる。作業中の項目は in_progress (同時に 1 件まで)、終えたら done。" +
			"同じ目標のための新しい手順は、新しいリストを作らず同じリストへ add する。やめた・置き換わったものは cancelled にする。" +
			"全部 done になってもリストは消さない (片付けは利用者の /todos tidy・clear)。",
		parameters: Params,
		async execute(_id, params, _signal, _onUpdate, ctx) {
			let error: string | undefined;
			let message = "";
			const target = () => todos.find((x) => x.id === params.id);
			switch (params.action) {
				case "add": {
					const texts = (params.texts ?? (params.text ? [params.text] : [])).map((s) => s.trim()).filter(Boolean);
					if (texts.length === 0) error = "add には text か texts が要る";
					else {
						const added = texts.map((text) => ({ id: nextId++, text, status: "pending" as Status }));
						todos.push(...added);
						message = `追加: ${added.map((t) => `#${t.id} ${t.text}`).join(" / ")}`;
					}
					break;
				}
				case "set": {
					const t = target();
					if (!params.status) error = "set には status が要る";
					else if (!t) error = `#${params.id} が無い`;
					else {
						t.status = params.status;
						message = `#${t.id} を ${t.status} にした`;
						const doing = todos.filter((x) => x.status === "in_progress");
						if (doing.length > 1) message += `\n注意: in_progress が ${doing.length} 件 (${doing.map((x) => `#${x.id}`).join(", ")})。同時に 1 件にする`;
					}
					break;
				}
				case "update": {
					const t = target();
					const text = params.text?.trim();
					if (!text) error = "update には text が要る";
					else if (!t) error = `#${params.id} が無い`;
					else {
						t.text = text;
						message = `#${t.id} の内容を直した`;
					}
					break;
				}
				case "remove": {
					const t = target();
					if (!t) error = `#${params.id} が無い`;
					else {
						todos = todos.filter((x) => x !== t);
						message = `#${t.id} を消した`;
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
			const body = render(params.action === "list" && params.all === true);
			return { content: [{ type: "text", text: `${error ? `エラー: ${error}` : message}\n${body}`.trim() }], details };
		},
	});

	// 利用者の操作。モデルへは渡さず、custom エントリで残す (再開・分岐で戻せるように)
	const persist = () => pi.appendEntry(STATE_ENTRY, { todos: todos.map((t) => ({ ...t })), nextId } satisfies Details);
	pi.registerCommand("todos", {
		description: "タスクリストの表示。/todos tidy (完了・中止を片付ける)・/todos clear (全部消す)",
		handler: async (args, ctx) => {
			const arg = String(args ?? "").trim();
			if (arg === "tidy" || arg === "clear") {
				const before = todos.length;
				if (arg === "clear") {
					todos = [];
					nextId = 1;
				} else todos = open();
				persist();
				status(ctx);
				ctx.ui.notify(`${before - todos.length} 件を片付けた (残り ${todos.length} 件)`, "info");
				return;
			}
			if (arg !== "") {
				ctx.ui.notify("使い方: /todos [tidy|clear]", "warning");
				return;
			}
			const done = todos.filter((t) => t.status === "done").length;
			ctx.ui.notify(todos.length ? `${done}/${todos.length} 完了\n${render(true)}` : "タスクはありません", "info");
		},
	});
}
