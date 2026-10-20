// `ask` ツール: モデルが推測せず、選択肢つきで利用者に尋ねる。1 回の呼び出しで最大 4 問。
// TUI では自前のパネル (ctx.ui.custom: 選択肢・複数選択・行内の自由記述)、それ以外 (RPC) は 1 問ずつの select / input。
// UI が無い実行 (print・子エージェント) ではツールを外す。
// see docs/spec/pi-guard.md#自作の拡張-todo--plan--btw
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Editor, type EditorTheme, Key, matchesKey, visibleWidth, wrapTextWithAnsi } from "@earendil-works/pi-tui";
import { Type } from "typebox";

const MAX_QUESTIONS = 4;
const MIN_OPTIONS = 2;
const MAX_OPTIONS = 4;
// 1 回の画面が答えを待つ上限。尽きたら未回答として返す (離席中に止まり続けない)。試験用に環境変数で変える
const TIMEOUT_MS = Number(process.env.PI_ASK_TIMEOUT_MS) > 0 ? Number(process.env.PI_ASK_TIMEOUT_MS) : 5 * 60 * 1000;
// 画面が自分で足す行。選択肢のラベルには使えない (モデルが「その他」を自作しないように)
const FREE = "Type something.";
const NEXT = "Next";
const RESERVED = new Set(["Other", FREE, NEXT]);

type Option = { label: string; description: string };
type Question = { question: string; header?: string; options: Option[]; multi?: boolean };
type Answer = { questionIndex: number; question: string; kind: "option" | "custom" | "multi"; answer: string | null; selected?: string[] };

// 表示幅 (全角は 2) で折り返す。選択肢の説明を字下げして揃えるため (端末の折り返しは行頭に戻ってしまう)
const WRAP_COLS = 64;
const INDENT = "       ";
const cols = (ch: string) => (/[\u1100-\u115f\u2e80-\ua4cf\uac00-\ud7a3\uf900-\ufaff\ufe30-\ufe6f\uff00-\uff60\uffe0-\uffe6]/.test(ch) ? 2 : 1);
function wrap(text: string): string[] {
	const out: string[] = [];
	let line = "";
	let width = 0;
	for (const ch of text.replace(/\s+/g, " ").trim()) {
		if (width + cols(ch) > WRAP_COLS) {
			const sp = line.lastIndexOf(" ");
			if (sp > 0 && ch !== " ") {
				// 英単語の途中で切らない
				out.push(line.slice(0, sp));
				line = line.slice(sp + 1);
			} else {
				out.push(line);
				line = "";
			}
			width = [...line].reduce((n, c) => n + cols(c), 0);
		}
		line += ch;
		width += cols(ch);
	}
	if (line) out.push(line);
	return out;
}

function validate(qs: Question[]): string | undefined {
	if (qs.length === 0) return "no_questions";
	if (qs.length > MAX_QUESTIONS) return "too_many_questions";
	const seen = new Set<string>();
	for (const q of qs) {
		if (seen.has(q.question)) return "duplicate_question";
		seen.add(q.question);
		if (q.options.length < MIN_OPTIONS) return "empty_options";
		if (q.options.some((o) => RESERVED.has(o.label))) return "reserved_label";
		if (new Set(q.options.map((o) => o.label)).size !== q.options.length) return "duplicate_option_label";
	}
	return undefined;
}

// TUI のパネル。戻りは選んだラベルと自由記述。中断・時間切れは null。
// 自由記述は行の下でその場で書く (Enter で確定・Esc で一覧へ戻る)。複数選択はカーソルを動かさずに切り替えられる
type Picked = { selected: string[]; custom?: string } | null;
function panel(ctx: any, q: Question, index: number, total: number, signal?: AbortSignal): Promise<Picked> {
	return ctx.ui.custom((tui: any, theme: any, _kb: any, done: (v: Picked) => void) => {
		const freeAt = q.options.length;
		const checked = new Set<number>();
		let cursor = 0;
		let editing = false;
		let custom: string | undefined;
		let finished = false;
		let cache: string[] | undefined;
		const editorTheme: EditorTheme = {
			borderColor: (s) => theme.fg("accent", s),
			selectList: {
				selectedPrefix: (t) => theme.fg("accent", t),
				selectedText: (t) => theme.fg("accent", t),
				description: (t) => theme.fg("muted", t),
				scrollInfo: (t) => theme.fg("dim", t),
				noMatch: (t) => theme.fg("warning", t),
			},
		};
		const editor = new Editor(tui, editorTheme);
		const refresh = () => {
			cache = undefined;
			tui.requestRender();
		};
		const finish = (v: Picked) => {
			if (finished) return;
			finished = true;
			clearTimeout(timer);
			signal?.removeEventListener("abort", onAbort);
			done(v);
		};
		const onAbort = () => finish(null);
		const timer = setTimeout(() => finish(null), TIMEOUT_MS);
		signal?.addEventListener("abort", onAbort, { once: true });
		const result = (): Picked => ({ selected: q.options.map((o) => o.label).filter((_, k) => checked.has(k)), ...(custom ? { custom } : {}) });

		editor.onSubmit = (value: string) => {
			const text = value.trim();
			if (!text) {
				editing = false; // 空は記録せず一覧へ戻る
				return refresh();
			}
			if (q.multi) {
				custom = text;
				editing = false;
				return refresh();
			}
			finish({ selected: [], custom: text });
		};

		const handleInput = (data: string) => {
			if (editing) {
				if (matchesKey(data, Key.escape)) {
					editing = false;
					return refresh();
				}
				editor.handleInput(data);
				return refresh();
			}
			if (matchesKey(data, Key.up)) cursor = Math.max(0, cursor - 1);
			else if (matchesKey(data, Key.down)) cursor = Math.min(freeAt, cursor + 1);
			else if (/^[1-9]$/.test(data) && Number(data) <= freeAt) cursor = Number(data) - 1;
			else if (matchesKey(data, Key.space) && q.multi && cursor < freeAt) {
				if (checked.has(cursor)) checked.delete(cursor);
				else checked.add(cursor);
			} else if (matchesKey(data, Key.enter)) {
				if (cursor === freeAt) {
					editing = true;
					editor.setText(custom ?? "");
				} else if (!q.multi) {
					return finish({ selected: [q.options[cursor].label] });
				} else {
					// 何も選んでいないときは、今の行を選んで確定する
					if (checked.size === 0 && !custom) checked.add(cursor);
					return finish(result());
				}
			} else if (matchesKey(data, Key.escape)) return finish(null);
			refresh();
		};

		const render = (width: number): string[] => {
			if (cache) return cache;
			const w = Math.max(1, width);
			const lines: string[] = [];
			const add = (prefix: string, text: string) => {
				const pad = " ".repeat(visibleWidth(prefix));
				wrapTextWithAnsi(text, Math.max(1, w - visibleWidth(prefix))).forEach((l, k) => lines.push((k === 0 ? prefix : pad) + l));
			};
			lines.push(theme.fg("accent", "─".repeat(w)));
			add(" ", theme.fg("text", `[${index + 1}/${total}] ${q.header ? `${q.header}: ` : ""}${q.question}`));
			for (let k = 0; k <= freeAt; k++) {
				lines.push("");
				const on = k === cursor;
				const mark = q.multi ? (k === freeAt ? (custom ? "[x] " : "[ ] ") : checked.has(k) ? "[x] " : "[ ] ") : "";
				const label = k === freeAt ? `${FREE}${editing ? " ✎" : custom ? `  ${custom}` : ""}` : `${k + 1}. ${q.options[k].label}`;
				add(on ? theme.fg("accent", "❯ ") : "  ", theme.fg(on ? "accent" : "text", mark + label));
				if (k < freeAt) add("      ", theme.fg("muted", q.options[k].description));
				else if (editing) for (const l of editor.render(Math.max(1, w - 6))) lines.push(`      ${l}`);
			}
			lines.push("");
			const keys = editing
				? "Enter 確定 • Esc 一覧へ戻る"
				: q.multi
					? "↑↓ 移動 • Space 選択/解除 • Enter 確定 • Esc 中止"
					: "↑↓ 移動 • Enter 選択 • Esc 中止";
			add(" ", theme.fg("dim", `${keys} • ${Math.round(TIMEOUT_MS / 60000)} 分で時間切れ`));
			lines.push(theme.fg("accent", "─".repeat(w)));
			cache = lines;
			return lines;
		};

		return {
			render,
			handleInput,
			invalidate: () => {
				cache = undefined;
			},
			// IME の候補窓の位置のため、フォーカスをエディタへ渡す
			get focused() {
				return editor.focused;
			},
			set focused(v: boolean) {
				editor.focused = v;
			},
		};
	});
}

export default function (pi: ExtensionAPI) {
	// UI が無い実行では、使えないツールをモデルに見せない (毎ターン確かめる)
	pi.on("before_agent_start", async (_event: any, ctx: any) => {
		if (ctx.hasUI) return;
		const active = pi.getActiveTools();
		if (active.includes("ask")) pi.setActiveTools(active.filter((n) => n !== "ask"));
	});

	pi.registerTool({
		name: "ask",
		label: "Ask",
		// promptSnippet が無いと Available tools に出ない
		promptSnippet: "Ask the user 1-4 multiple-choice questions at once instead of guessing",
		promptGuidelines: [
			"Use ask only when an unresolved choice would change the result and you cannot decide from the code or docs; do not ask for things you can check yourself.",
			"Put independent questions into one ask call (up to 4). A question that depends on an earlier answer goes into the next call.",
			"Give each question 2-4 options with a one-line description of the trade-off; put the recommended option first. A free-text row is added automatically, so do not add 'Other'.",
		],
		description:
			`利用者に選択肢つきの質問を最大 ${MAX_QUESTIONS} 問まとめて尋ねる。questions の各項目は question (質問文)・header (短い見出し。任意)・` +
			`options (${MIN_OPTIONS}〜${MAX_OPTIONS} 個。label と description)・multi (複数選択。任意)。自由記述の行 "${FREE}" は自動で足されるので、"Other" や "${NEXT}" を選択肢にしない。` +
			"戻りは answers (答えた問)・unanswered (答えなかった問の番号。0 始まり)・cancelled。" +
			"中断・時間切れ・UI が無いときは未回答として返るので、その場合は推測で進めず、地の文で尋ね直すか安全側に進める。",
		parameters: Type.Object({
			questions: Type.Array(
				Type.Object({
					question: Type.String({ description: "質問文" }),
					header: Type.Optional(Type.String({ maxLength: 16, description: "短い見出し" })),
					options: Type.Array(
						Type.Object({
							label: Type.String({ maxLength: 60, description: "選択肢 (1〜5 語)" }),
							description: Type.String({ description: "意味と、選ぶとどうなるか" }),
						}),
						{ minItems: MIN_OPTIONS, maxItems: MAX_OPTIONS },
					),
					multi: Type.Optional(Type.Boolean({ description: "複数選択 (既定 false)" })),
				}),
				{ minItems: 1, maxItems: MAX_QUESTIONS },
			),
		}),
		async execute(_id, params, signal, _onUpdate, ctx) {
			const qs = params.questions as Question[];
			const fail = (error: string, text: string) => ({
				content: [{ type: "text" as const, text: `エラー (${error}): ${text}` }],
				details: { answers: [] as Answer[], cancelled: true, unanswered: qs.map((_, i) => i), error },
			});
			if (!ctx.hasUI) return fail("no_ui", "UI が無く、利用者には尋ねられなかった。質問は地の文で書くか、安全側に進める");
			const invalid = validate(qs);
			if (invalid) return fail(invalid, "質問の形が不正。直して呼び直す");

			const opts = { signal, timeout: TIMEOUT_MS };
			const title = (q: Question, i: number) => `[${i + 1}/${qs.length}] ${q.header ? `${q.header}: ` : ""}${q.question}`;
			// 自由記述。空・中断なら undefined (呼び出し側が選択肢へ戻す)
			const free = async (q: Question, i: number) => {
				const text = await ctx.ui.input(title(q, i), "自由に記入", opts);
				return text?.trim() ? text.trim() : undefined;
			};
			const answers: Answer[] = [];
			let stopped = false;
			for (let i = 0; i < qs.length && !stopped; i++) {
				const q = qs[i];
				if (ctx.mode === "tui") {
					const r = await panel(ctx, q, i, qs.length, signal);
					if (r === null) {
						stopped = true;
						break;
					}
					if (q.multi) answers.push({ questionIndex: i, question: q.question, kind: "multi", answer: r.custom ?? null, selected: r.selected });
					else if (r.custom) answers.push({ questionIndex: i, question: q.question, kind: "custom", answer: r.custom });
					else answers.push({ questionIndex: i, question: q.question, kind: "option", answer: r.selected[0] });
					continue;
				}
				// 行はラベルだけ (1 行で収まり、カーソルの位置が分かる)。説明は質問文の下に番号つきの一覧で出す
				const rows = q.options.map((o, k) => `${k + 1}. ${o.label}`);
				const detail = `${title(q, i)}\n\n${q.options.map((o, k) => `  ${k + 1}. ${o.label}\n${wrap(o.description).map((l) => INDENT + l).join("\n")}`).join("\n\n")}\n\n`;
				if (!q.multi) {
					for (;;) {
						const picked = await ctx.ui.select(detail, [...rows, FREE], opts);
						if (picked === undefined) {
							stopped = true;
							break;
						}
						if (picked === FREE) {
							const text = await free(q, i);
							if (text === undefined) continue; // 空・中断は選択肢へ戻す
							answers.push({ questionIndex: i, question: q.question, kind: "custom", answer: text });
						} else {
							answers.push({ questionIndex: i, question: q.question, kind: "option", answer: q.options[rows.indexOf(picked)].label });
						}
						break;
					}
				} else {
					const chosen = new Set<string>();
					let custom: string | undefined;
					for (;;) {
						const marked = q.options.map((o, k) => `${chosen.has(o.label) ? "[x]" : "[ ]"} ${rows[k]}`);
						const picked = await ctx.ui.select(`${detail}(複数選択。選び終えたら ${NEXT})`, [...marked, FREE, NEXT], opts);
						if (picked === undefined) {
							stopped = true;
							break;
						}
						if (picked === NEXT) {
							answers.push({
								questionIndex: i,
								question: q.question,
								kind: "multi",
								answer: custom ?? null,
								selected: q.options.map((o) => o.label).filter((l) => chosen.has(l)),
							});
							break;
						}
						if (picked === FREE) {
							custom = (await free(q, i)) ?? custom;
							continue;
						}
						const label = q.options[marked.indexOf(picked)].label;
						if (chosen.has(label)) chosen.delete(label);
						else chosen.add(label);
					}
				}
			}
			const answered = new Set(answers.map((a) => a.questionIndex));
			const unanswered = qs.map((_, i) => i).filter((i) => !answered.has(i));
			const cancelled = answers.length === 0;
			const lines = answers.map((a) => {
				const body = a.kind === "multi" ? [...(a.selected ?? []), ...(a.answer ? [`自由記述: ${a.answer}`] : [])].join(", ") || "(選択なし)" : a.answer;
				return `Q${a.questionIndex + 1} ${a.question}\n  → ${body}`;
			});
			const head = cancelled
				? "利用者は答えなかった (中断または時間切れ)。推測で進めず、地の文で尋ね直すか安全側に進める。"
				: unanswered.length
					? `一部だけ回答。未回答の問: ${unanswered.map((i) => `Q${i + 1}`).join(", ")} (推測で埋めない)`
					: "回答:";
			return {
				content: [{ type: "text" as const, text: [head, ...lines].join("\n") }],
				details: { answers, cancelled, unanswered },
			};
		},
	});
}
