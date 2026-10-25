// `ask` ツール: モデルが推測せず、選択肢つきで利用者に尋ねる。1 回の呼び出しで最大 4 問。
// TUI では自前のパネル (ctx.ui.custom: 問ごとのタブ + 確認・複数選択・行内の自由記述)、それ以外 (RPC) は 1 問ずつの select / input。
// UI が無い実行 (print・子エージェント) ではツールを外す。
// see docs/spec/guard/pi-guard.md#自作の拡張-todo--plan--btw
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Editor, type EditorTheme, Key, matchesKey, truncateToWidth, visibleWidth, wrapTextWithAnsi } from "@earendil-works/pi-tui";
import { Type } from "typebox";

const MAX_QUESTIONS = 4;
const MIN_OPTIONS = 2;
const MAX_OPTIONS = 4;
// 操作が無いまま待つ上限。尽きたら未回答として返す (離席中に止まり続けない)。試験用に環境変数で変える
const TIMEOUT_MS = Number(process.env.PI_ASK_TIMEOUT_MS) > 0 ? Number(process.env.PI_ASK_TIMEOUT_MS) : 5 * 60 * 1000;
// 画面が自分で足す行。選択肢のラベルには使えない (モデルが「その他」を自作しないように)
const FREE = "Type something.";
const NEXT = "Next";
const RESERVED = new Set(["Other", FREE, NEXT]);

type Option = { label: string; description: string };
type Question = { question: string; header?: string; options: Option[]; multi?: boolean };
type Answer = { questionIndex: number; question: string; kind: "option" | "custom" | "multi"; answer: string | null; selected?: string[] };

// 表示幅 (全角は 2) で折り返す。RPC の選択肢の説明を字下げして揃えるため (端末の折り返しは行頭に戻ってしまう)
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

// 推奨の印: label の末尾の (推奨) / (recommended)。全角括弧・大文字小文字は問わない。印は label に残る
const RECOMMENDED = /\s*[(（](推奨|recommended)[)）]\s*$/i;
const isRecommended = (o: Option) => RECOMMENDED.test(o.label);

// 推奨の検査 (validate の後)。違反した質問は全部まとめて 1 つのエラーにする。コードは最初の違反のもの
function validateRecommended(qs: Question[]): { code: string; text: string } | undefined {
	let code: string | undefined;
	const lines: string[] = [];
	qs.forEach((q, i) => {
		const count = q.options.filter(isRecommended).length;
		const head = `Q${i + 1} (${[...q.question].slice(0, 20).join("")})`;
		const add = (c: string, msg: string) => {
			code ??= c;
			lines.push(`${head}: ${msg}`);
		};
		if (count === 0) add("missing_recommended", "推奨する選択肢が無い");
		else if (count > 1 && !q.multi) add("multiple_recommended", `推奨が ${count} 個ある (複数選択でなければ 1 個だけ)`);
		if (count > 0 && !isRecommended(q.options[0])) add("recommended_not_first", "推奨の選択肢が先頭にない");
	});
	if (!code) return undefined;
	return {
		code,
		text: `${lines.join(" / ")}。推奨する選択肢を 1 つ決め、先頭に置き、label の末尾に \` (推奨)\` を付けて呼び直す。決めかねるときは、最も安全な選択肢を推奨にして、description にその理由を書く`,
	};
}

// TUI のパネル。問が複数のときは、問ごとのタブと、最後の確認タブ (Tab / Shift+Tab で移動)。問が 1 つだけならタブも確認も無く、答えたらすぐ送る。
// 戻りは問ごとの回答 (未回答は undefined)。Esc・時間切れは全部 undefined。
// 自由記述は行の下でその場で書く (Enter で確定・Esc で一覧へ戻る)。複数選択はカーソルを動かさずに切り替えられる
type Picked = { selected: string[]; custom?: string };
function panel(ctx: any, qs: Question[], signal?: AbortSignal): Promise<(Picked | undefined)[]> {
	return ctx.ui.custom((tui: any, theme: any, _kb: any, done: (v: (Picked | undefined)[]) => void) => {
		const n = qs.length;
		const tabs = n > 1 ? n + 1 : 1; // 最後の 1 つは確認
		const st = qs.map(() => ({ cursor: 0, checked: new Set<number>(), custom: undefined as string | undefined, answer: undefined as Picked | undefined }));
		let tab = 0;
		let editing = false;
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
			if (finished) return;
			cache = undefined;
			tui.requestRender();
		};
		const finish = (v: (Picked | undefined)[]) => {
			if (finished) return;
			finished = true;
			clearTimeout(timer);
			signal?.removeEventListener("abort", onAbort);
			done(v);
		};
		const none = () => qs.map(() => undefined);
		const onAbort = () => finish(none());
		let timer = setTimeout(onAbort, TIMEOUT_MS);
		const touch = () => {
			clearTimeout(timer);
			timer = setTimeout(onAbort, TIMEOUT_MS);
		};
		signal?.addEventListener("abort", onAbort, { once: true });

		const multiResult = (k: number): Picked => ({
			selected: qs[k].options.map((o) => o.label).filter((_, j) => st[k].checked.has(j)),
			...(st[k].custom ? { custom: st[k].custom } : {}),
		});
		// 答えを記録したあとの移動。問が 1 つなら送信、複数なら次のタブ (最後の問の次は確認)
		const advance = () => {
			if (n === 1) return finish(st.map((s) => s.answer));
			tab = Math.min(tab + 1, tabs - 1);
		};
		const isConfirm = () => n > 1 && tab === n;
		const text = (k: number) => {
			const a = st[k].answer;
			if (!a) return undefined;
			return [...a.selected, ...(a.custom ? [`自由記述: ${a.custom}`] : [])].join(", ") || "(選択なし)";
		};

		editor.onSubmit = (value: string) => {
			const k = tab;
			const s = st[k];
			const t = value.trim();
			editing = false;
			if (!t) {
				// 空は記録しない (以前の自由記述も消す)
				s.custom = undefined;
				if (s.answer) s.answer = qs[k].multi ? multiResult(k) : undefined;
				return refresh();
			}
			// 複数選択でも、ここでチェックした選択肢と自由記述をまとめて確定する (Enter が「入力の確定」と「確定」で被らないように)
			s.custom = t;
			s.answer = qs[k].multi ? multiResult(k) : { selected: [], custom: t };
			advance();
			refresh();
		};

		const handleInput = (data: string) => {
			touch();
			if (editing) {
				if (matchesKey(data, Key.escape)) {
					editing = false;
					return refresh();
				}
				editor.handleInput(data);
				return refresh();
			}
			if (matchesKey(data, Key.escape)) return finish(none());
			if (tabs > 1 && (matchesKey(data, Key.tab) || matchesKey(data, Key.shift("tab")))) {
				// 複数選択でチェックしたままタブを離れたときは、そのとおり回答として扱う
				if (!isConfirm() && qs[tab].multi && (st[tab].checked.size > 0 || st[tab].custom)) st[tab].answer = multiResult(tab);
				tab = (tab + (matchesKey(data, Key.tab) ? 1 : tabs - 1)) % tabs;
				return refresh();
			}
			if (isConfirm()) {
				if (matchesKey(data, Key.enter)) finish(st.map((s) => s.answer));
				return;
			}
			const q = qs[tab];
			const s = st[tab];
			const freeAt = q.options.length;
			if (matchesKey(data, Key.up)) s.cursor = Math.max(0, s.cursor - 1);
			else if (matchesKey(data, Key.down)) s.cursor = Math.min(freeAt, s.cursor + 1);
			else if (/^[1-9]$/.test(data) && Number(data) <= freeAt) s.cursor = Number(data) - 1;
			else if (matchesKey(data, Key.space) && q.multi && s.cursor < freeAt) {
				if (s.checked.has(s.cursor)) s.checked.delete(s.cursor);
				else s.checked.add(s.cursor);
				if (s.answer) s.answer = multiResult(tab);
			} else if (matchesKey(data, Key.enter)) {
				if (s.cursor === freeAt) {
					editing = true;
					editor.setText(s.custom ?? "");
				} else if (!q.multi) {
					s.custom = undefined;
					s.answer = { selected: [q.options[s.cursor].label] };
					advance();
				} else {
					// 何も選んでいないときは、今の行を選んで確定する
					if (s.checked.size === 0 && !s.custom) s.checked.add(s.cursor);
					s.answer = multiResult(tab);
					advance();
				}
			}
			refresh();
		};

		const render = (width: number): string[] => {
			if (cache) return cache;
			const w = Math.max(1, width);
			const lines: string[] = [];
			const add = (prefix: string, body: string) => {
				const pad = " ".repeat(visibleWidth(prefix));
				wrapTextWithAnsi(body, Math.max(1, w - visibleWidth(prefix))).forEach((l, k) => lines.push((k === 0 ? prefix : pad) + l));
			};
			lines.push(theme.fg("accent", "─".repeat(w)));
			if (tabs > 1) {
				const items = [...qs.map((q, i) => `${st[i].answer ? "✓" : "□"} ${truncateToWidth(q.header ?? q.question, 10, "…")}`), "確認"];
				const bar = items.map((t, i) => (i === tab ? theme.bold(theme.fg("accent", `[${t}]`)) : theme.fg("muted", ` ${t} `))).join(" ");
				lines.push(truncateToWidth(` ${bar}`, w));
				lines.push("");
			}
			if (isConfirm()) {
				add(" ", theme.fg("text", "回答の確認"));
				lines.push("");
				let blank = 0;
				qs.forEach((q, i) => {
					const t = text(i);
					if (!t) blank++;
					add("  ", theme.fg(t ? "success" : "warning", `${t ? "✓" : "✗"} ${i + 1}. ${q.header ?? q.question}`));
					add("      ", theme.fg(t ? "text" : "warning", t ? `→ ${t}` : "未回答"));
				});
				lines.push("");
				if (blank > 0) add(" ", theme.fg("warning", `未回答の問が ${blank} 件あります。送信すると未回答として返ります (Tab で戻って答えられます)`));
				add(" ", theme.fg("dim", `Enter 送信 • Tab / Shift+Tab 移動 • Esc 中止 • ${Math.round(TIMEOUT_MS / 60000)} 分無操作で時間切れ`));
				lines.push(theme.fg("accent", "─".repeat(w)));
				cache = lines;
				return lines;
			}
			const q = qs[tab];
			const s = st[tab];
			const freeAt = q.options.length;
			add(" ", theme.fg("text", `${n > 1 ? `[${tab + 1}/${n}] ` : ""}${q.header ? `${q.header}: ` : ""}${q.question}`));
			for (let k = 0; k <= freeAt; k++) {
				lines.push("");
				const on = k === s.cursor;
				const isFree = k === freeAt;
				const mark = q.multi
					? (isFree ? s.custom : s.checked.has(k)) ? "[x] " : "[ ] "
					: (isFree ? s.answer?.custom : s.answer?.selected[0] === q.options[k].label) ? "(●) " : "( ) ";
				const label = isFree ? `${FREE}${editing ? " ✎" : s.custom ? `  ${s.custom}` : ""}` : `${k + 1}. ${q.options[k].label}`;
				add(on ? theme.fg("accent", "❯ ") : "  ", theme.fg(on ? "accent" : "text", mark + label));
				if (!isFree) add("      ", theme.fg("muted", q.options[k].description));
				else if (editing) for (const l of editor.render(Math.max(1, w - 6))) lines.push(`      ${l}`);
			}
			lines.push("");
			const keys = editing
				? q.multi
					? `Enter ${n > 1 ? "確定して次へ" : "送信"}（チェックとこの入力をまとめて） • Esc 一覧へ戻る`
					: `Enter ${n > 1 ? "確定して次へ" : "送信"} • Esc 一覧へ戻る`
				: `↑↓ 移動 • ${q.multi ? "Space 選択/解除 • " : ""}Enter ${q.multi ? "確定" : "選択"}${n > 1 ? "して次へ • Tab 次の問" : "して送信"} • Esc 中止`;
			add(" ", theme.fg("dim", `${keys} • ${Math.round(TIMEOUT_MS / 60000)} 分無操作で時間切れ`));
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
			"Do not use ask to get approval for a commit or a post (guarded_action asks for approval itself).",
			"Put independent questions into one ask call (up to 4). A question that depends on an earlier answer goes into the next call.",
			"Give each question 2-4 options with a one-line description of the trade-off; put the recommended option first and end its label with ' (推奨)' (or ' (recommended)'); keep labels short because labels are limited to 60 characters. A free-text row is added automatically, so do not add 'Other'.",
		],
		description:
			`利用者に選択肢つきの質問を最大 ${MAX_QUESTIONS} 問まとめて尋ねる。投稿・コミットの承認には使わない (guarded_action が承認を取る)。questions の各項目は question (質問文)・header (短い見出し。任意)・` +
			`options (${MIN_OPTIONS}〜${MAX_OPTIONS} 個。label と description)・multi (複数選択。任意)。自由記述の行 "${FREE}" は自動で足されるので、"Other" や "${NEXT}" を選択肢にしない。` +
			"各質問は推奨の選択肢をちょうど 1 つ (multi は 1 つ以上) 持ち、先頭に置き、label の末尾に ' (推奨)' を付ける (label は 60 字までなので短くする)。守られないとエラーで返る。" +
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
			const unrecommended = validateRecommended(qs);
			if (unrecommended) return fail(unrecommended.code, unrecommended.text);

			// 利用者の答えを待つ前に BEL (端末の通知)。RPC では stdout が通信なので TUI だけ
			if (ctx.mode === "tui") process.stdout.write("\x07");
			const opts = { signal, timeout: TIMEOUT_MS };
			const title = (q: Question, i: number) => `[${i + 1}/${qs.length}] ${q.header ? `${q.header}: ` : ""}${q.question}`;
			// 自由記述。空・中断なら undefined (呼び出し側が選択肢へ戻す)
			const free = async (q: Question, i: number) => {
				const text = await ctx.ui.input(title(q, i), "自由に記入", opts);
				return text?.trim() ? text.trim() : undefined;
			};
			const answers: Answer[] = [];
			if (ctx.mode === "tui") {
				const picks = await panel(ctx, qs, signal);
				picks.forEach((r, i) => {
					if (!r) return;
					const q = qs[i];
					if (q.multi) answers.push({ questionIndex: i, question: q.question, kind: "multi", answer: r.custom ?? null, selected: r.selected });
					else if (r.custom) answers.push({ questionIndex: i, question: q.question, kind: "custom", answer: r.custom });
					else answers.push({ questionIndex: i, question: q.question, kind: "option", answer: r.selected[0] });
				});
			}
			let stopped = ctx.mode === "tui"; // TUI は上のパネルで全部済んでいる
			for (let i = 0; i < qs.length && !stopped; i++) {
				const q = qs[i];
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
