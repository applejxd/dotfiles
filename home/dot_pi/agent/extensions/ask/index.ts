// `ask` ツール: モデルが推測せず、選択肢つきで利用者に尋ねる。1 回の呼び出しで最大 4 問。
// 画面は 1 問ずつの select / input (TUI と RPC で共通)。UI が無い実行 (print・子エージェント) ではツールを外す。
// see docs/spec/pi-guard.md#自作の拡張-todo--plan--btw
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
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
				const rows = q.options.map((o) => `${o.label} — ${o.description}`);
				if (!q.multi) {
					for (;;) {
						const picked = await ctx.ui.select(title(q, i), [...rows, FREE], opts);
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
						const picked = await ctx.ui.select(`${title(q, i)} (複数選択。選び終えたら ${NEXT})`, [...marked, FREE, NEXT], opts);
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
