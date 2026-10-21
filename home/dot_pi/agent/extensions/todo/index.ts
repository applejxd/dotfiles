// タスクリスト。`todo` ツールと `/todos` コマンド。リストは 1 つで、勝手には消さない。
// 状態は、ツール結果の details と、利用者の操作 (/todos clear・tidy) の custom エントリに持たせる。
// どちらもセッションに残るので、分岐・再開・圧縮のあとも、その時点の状態に戻る。
// 操作は 1 回の呼び出しに複数まとめられる (batch)。途中で失敗したら全体を適用しない。
// see docs/spec/pi-guard.md#自作の拡張-todo--plan--btw
import { StringEnum } from "@earendil-works/pi-ai";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";

type Status = "pending" | "in_progress" | "blocked" | "done" | "cancelled";
type Todo = { id: number; text: string; status: Status; note?: string };
type Details = { todos: Todo[]; nextId: number; error?: string };

const STATUSES = ["pending", "in_progress", "blocked", "done", "cancelled"] as const;
const MARK: Record<Status, string> = { pending: "[ ]", in_progress: "[>]", blocked: "[~]", done: "[x]", cancelled: "[-]" };
const STATE_ENTRY = "todo-state";
// 戻り値に出す未完了の先頭件数と、メモの最大文字数
const SUMMARY_OPEN = 3;
const NOTE_MAX = 80;

const OpFields = {
	text: Type.Optional(Type.String({ description: "add (1 件) / update の内容" })),
	texts: Type.Optional(Type.Array(Type.String(), { description: "add で複数件を一度に足す" })),
	id: Type.Optional(Type.Number({ description: "set / update / remove の対象の ID" })),
	status: Type.Optional(StringEnum(STATUSES, { description: "set の新しい状態" })),
	note: Type.Optional(Type.String({ description: "メモ (完了の根拠・引き継ぎ)。add / set / update で付ける。空文字で消す" })),
};
const OpShape = { action: StringEnum(["add", "set", "update", "remove"] as const), ...OpFields };

const Params = Type.Object({
	action: StringEnum(["list", "add", "set", "update", "remove", "clear", "batch", "replace"] as const),
	...OpFields,
	all: Type.Optional(Type.Boolean({ description: "list で完了・中止も含めて全件を出す" })),
	ops: Type.Optional(
		Type.Array(Type.Object(OpShape), { description: "batch: 操作を順に適用する。1 件でも失敗したら全体を適用しない" }),
	),
	items: Type.Optional(
		Type.Array(
			Type.Object({
				text: Type.String(),
				status: Type.Optional(StringEnum(STATUSES)),
				id: Type.Optional(Type.Number({ description: "既存の項目を引き継ぐときの ID" })),
				note: Type.Optional(Type.String()),
			}),
			{ description: "replace: リスト全体をこの内容に置き換える (載せない既存の項目は消える)" },
		),
	),
});

type Op = { action: string; text?: string; texts?: string[]; id?: number; status?: Status; note?: string };
type Work = { todos: Todo[]; nextId: number };

// 旧形式 ({ id, text, done }) の状態も読む。再開した古いセッションが壊れないように
function normalize(raw: unknown): Todo[] {
	if (!Array.isArray(raw)) return [];
	const out: Todo[] = [];
	for (const t of raw as any[]) {
		if (typeof t?.id !== "number" || typeof t?.text !== "string") continue;
		const status: Status = (STATUSES as readonly string[]).includes(t.status) ? t.status : t.done === true ? "done" : "pending";
		out.push({ id: t.id, text: t.text, status, ...(typeof t.note === "string" && t.note ? { note: t.note } : {}) });
	}
	return out;
}

const clip = (s: string, n: number) => (s.length > n ? `${s.slice(0, n)}…` : s);

// 1 件の操作を作業用の状態へ適用する。失敗なら理由を返す (状態は呼び出し側が捨てる)
function applyOp(w: Work, op: Op): { message?: string; error?: string } {
	const find = () => w.todos.find((x) => x.id === op.id);
	const setNote = (t: Todo) => {
		if (op.note === undefined) return;
		const note = op.note.trim();
		if (note) t.note = note;
		else delete t.note;
	};
	switch (op.action) {
		case "add": {
			const texts = (op.texts ?? (op.text ? [op.text] : [])).map((s) => s.trim()).filter(Boolean);
			if (texts.length === 0) return { error: "add には text か texts が要る" };
			const added = texts.map((text) => ({ id: w.nextId++, text, status: "pending" as Status }) as Todo);
			if (op.note !== undefined && added.length === 1) setNote(added[0]);
			w.todos.push(...added);
			return { message: `追加: ${added.map((t) => `#${t.id} ${t.text}`).join(" / ")}` };
		}
		case "set": {
			const t = find();
			if (!op.status) return { error: "set には status が要る" };
			if (!t) return { error: `#${op.id} が無い` };
			t.status = op.status;
			setNote(t);
			const warn = t.status === "blocked" && !t.note ? "。注意: 待ち先 (ジョブ ID など) を note に書いてください" : "";
			return { message: `#${t.id} を ${t.status} にした${warn}` };
		}
		case "update": {
			const t = find();
			const text = op.text?.trim();
			if (!text && op.note === undefined) return { error: "update には text か note が要る" };
			if (!t) return { error: `#${op.id} が無い` };
			if (text) t.text = text;
			setNote(t);
			return { message: `#${t.id} を直した` };
		}
		case "remove": {
			const t = find();
			if (!t) return { error: `#${op.id} が無い` };
			w.todos = w.todos.filter((x) => x !== t);
			return { message: `#${t.id} を消した` };
		}
		default:
			return { error: `未対応の操作: ${op.action}` };
	}
}

export default function (pi: ExtensionAPI) {
	let todos: Todo[] = [];
	let nextId = 1;

	const open = () => todos.filter((t) => t.status === "pending" || t.status === "in_progress" || t.status === "blocked");
	const line = (t: Todo) => `${MARK[t.status]} #${t.id}: ${t.text}${t.note ? ` — ${clip(t.note, NOTE_MAX)}` : ""}`;
	const counts = () => {
		const done = todos.filter((t) => t.status === "done").length;
		const cancelled = todos.filter((t) => t.status === "cancelled").length;
		return { done, cancelled };
	};
	// list の本文。完了・中止は件数にたたむ (足していくほど文脈を占めないように)。all なら全件
	const render = (all = false) => {
		if (todos.length === 0) return "(空)";
		const shown = all ? todos : open();
		const { done, cancelled } = counts();
		const rest = all || (done === 0 && cancelled === 0) ? "" : `完了 ${done} 件・中止 ${cancelled} 件 (全件は list の all)`;
		return [...shown.map(line), ...(shown.length === 0 && !all ? ["(未完了なし)"] : []), ...(rest ? [rest] : [])].join("\n");
	};
	// 変更の結果に添える要約。未完了の件数と先頭の数件だけ (全件は list)
	const summary = () => {
		if (todos.length === 0) return "(空)";
		const o = open();
		const { done, cancelled } = counts();
		const head = o.slice(0, SUMMARY_OPEN).map(line);
		const more = o.length > SUMMARY_OPEN ? [`… 他 ${o.length - SUMMARY_OPEN} 件`] : [];
		const tail = `未完了 ${o.length} 件・完了 ${done} 件・中止 ${cancelled} 件 (全件は list)`;
		return [...head, ...more, tail].join("\n");
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
	let lastCtx: ExtensionContext | undefined;
	let nudged = false;
	pi.on("session_start", async (_e, ctx) => {
		lastCtx = ctx;
		rebuild(ctx);
	});
	pi.on("session_tree", async (_e, ctx) => {
		lastCtx = ctx;
		rebuild(ctx);
	});

	// 操作の列を作業用の状態に順に適用し、全部成功したときだけ反映する
	const run = (ops: Op[], label: (i: number) => string) => {
		const w: Work = { todos: todos.map((t) => ({ ...t })), nextId };
		const messages: string[] = [];
		for (let i = 0; i < ops.length; i++) {
			const r = applyOp(w, ops[i]);
			if (r.error) return { error: `${label(i)}${r.error}`, messages: [] as string[] };
			if (r.message) messages.push(r.message);
		}
		todos = w.todos;
		nextId = w.nextId;
		return { error: undefined as string | undefined, messages };
	};

	pi.on("before_agent_start", async (event: any) => {
		// 利用者の発言ごとに、リマインドを 1 回だけ出せるようにする (続行がループしないように)
		if (event?.messageType === "user") nudged = false;
	});
	// in_progress が残ったまま応答を終えようとしたとき、完了の確認か続きの作業を促す (利用者の発言ごとに 1 回だけ)。
	// 中断・エラーで終わったときや、続けられないときは出さない。続行は最大 1 回 (無条件の続行はループする)
	pi.on("agent_before_settle", async (event: any) => {
		if (nudged || event?.outcome !== "completed" || process.env.PI_TODO_NO_REMINDER === "1") return;
		const doing = todos.filter((t) => t.status === "in_progress");
		if (doing.length === 0) return;
		nudged = true;
		const list = doing.map((t) => `#${t.id} ${t.text}`).join(" / ");
		return {
			entries: [
				{
					type: "custom_message" as const,
					customType: "todo-reminder",
					content: `作業中 (in_progress) のまま終わろうとしています: ${list}。実際に終わっていれば done にして、続きがあれば作業を続けてください。終えられない理由があるときは note に書いてください。`,
					display: true,
				},
			],
			continue: true,
		};
	});

	pi.registerTool({
		name: "todo",
		label: "Todo",
		// promptSnippet が無いと Available tools に出ない
		promptSnippet: "Keep the task list: add steps, mark them in_progress / blocked / done, list them",
		promptGuidelines: [
			"For work with 3 or more steps, use todo add to list the steps before starting; set the current item to in_progress (one at a time) and to done when finished.",
			"Set an item to blocked (not in_progress) while it only waits on something external, such as a background job, a child agent, or the user's reply; write what it waits for (e.g. the job ID) in note.",
			"Use todo batch (ops) to change several items in one call, and todo replace (items) to rewrite the whole list at once.",
		],
		description:
			"作業のタスクリスト (1 つ)。action: list (all=true で完了・中止も) / add (text か texts で複数) / " +
			"set (id と status: pending・in_progress・blocked・done・cancelled。何度呼んでも同じ結果) / update (id と text か note) / remove (id、誤って足したものだけ) / clear / " +
			"batch (ops に操作の配列。順に適用し、1 件でも失敗したら全体を適用しない。複数の項目を 1 回で変えるときに使う) / " +
			"replace (items にリスト全体を渡して置き換える。載せない項目は消える。id を付ければ既存の項目を引き継ぐ)。" +
			"note は完了の根拠や引き継ぎのメモ。3 手順以上の作業では、始める前に add で手順を並べる。作業中の項目は in_progress (同時に 1 件まで)、終えたら done。ジョブ・子・利用者の返答など外部の完了待ちは blocked にし、note に待ち先 (ジョブ ID など) を書く (同時 1 件の数に入れない)。" +
			"同じ目標のための新しい手順は、新しいリストを作らず同じリストへ add する。やめた・置き換わったものは cancelled にする。" +
			"全部 done になってもリストは消さない (片付けは利用者の /todos tidy・clear)。変更の結果は、未完了の先頭数件と件数だけ返す (全件は list)。",
		parameters: Params,
		async execute(_id, params, _signal, _onUpdate, ctx) {
			let error: string | undefined;
			let messages: string[] = [];
			const single = { action: params.action, text: params.text, texts: params.texts, id: params.id, status: params.status, note: params.note } as Op;
			switch (params.action) {
				case "list":
					break;
				case "add":
				case "set":
				case "update":
				case "remove": {
					const r = run([single], () => "");
					error = r.error;
					messages = r.messages;
					break;
				}
				case "batch": {
					if (!params.ops || params.ops.length === 0) error = "batch には ops (1 件以上) が要る";
					else {
						const r = run(params.ops as Op[], (i) => `ops[${i}]: `);
						error = r.error;
						messages = r.messages;
					}
					break;
				}
				case "replace": {
					if (!params.items) {
						error = "replace には items が要る";
						break;
					}
					const texts = params.items.map((i) => i.text.trim());
					if (texts.some((t) => !t)) {
						error = "replace の items の text は空にできない";
						break;
					}
					const ids = params.items.filter((i) => i.id !== undefined).map((i) => i.id as number);
					if (new Set(ids).size !== ids.length) {
						error = "replace の items の id が重複している";
						break;
					}
					const next = nextId;
					let n = next;
					const old = new Map(todos.map((t) => [t.id, t] as const));
					const replaced: Todo[] = params.items.map((it) => {
						const known = it.id !== undefined ? old.get(it.id) : undefined;
						const id = it.id !== undefined && known ? it.id : n++;
						const note = it.note !== undefined ? it.note.trim() : known?.note;
						return { id, text: it.text.trim(), status: it.status ?? known?.status ?? "pending", ...(note ? { note } : {}) } as Todo;
					});
					const removed = todos.filter((t) => !replaced.some((r) => r.id === t.id)).length;
					todos = replaced;
					nextId = n;
					messages = [`置き換えた: ${replaced.length} 件 (消えた既存の項目 ${removed} 件)`];
					break;
				}
				case "clear":
					messages = [`${todos.length} 件を消した`];
					todos = [];
					nextId = 1;
					break;
				default:
					break;
			}
			const doing = todos.filter((x) => x.status === "in_progress");
			if (!error && doing.length > 1) messages.push(`注意: in_progress が ${doing.length} 件 (${doing.map((x) => `#${x.id}`).join(", ")})。同時に 1 件にする`);
			status(ctx);
			const details: Details = { todos: todos.map((t) => ({ ...t })), nextId, ...(error ? { error } : {}) };
			const body = params.action === "list" ? render(params.all === true) : summary();
			const head = error ? `エラー: ${error}` : messages.join("\n");
			return { content: [{ type: "text", text: `${head}\n${body}`.trim() }], details };
		},
	});

	// 利用者の操作。モデルへは渡さず、custom エントリで残す (再開・分岐で戻せるように)
	const persist = () => pi.appendEntry(STATE_ENTRY, { todos: todos.map((t) => ({ ...t })), nextId } satisfies Details);
	// 子エージェントの結果を、割り当てた項目へ反映する入口 (harness の guarded_task が呼ぶ)。status が無ければメモだけ
	(globalThis as any).__piTodoUpdate = (u: { id: number; status?: Status; note?: string }) => {
		const t = todos.find((x) => x.id === u.id);
		if (!t) return false;
		if (u.status) t.status = u.status;
		if (u.note) t.note = u.note.trim();
		persist();
		if (lastCtx) status(lastCtx);
		return true;
	};
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
