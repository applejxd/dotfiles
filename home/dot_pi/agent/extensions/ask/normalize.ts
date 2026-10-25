// `ask` の引数の正規化 (pi の prepareArguments から、スキーマ検証の前に呼ばれる純関数)。
// モデルが間違えやすい形だけを救う。値の意味を変える補完 (推奨の自動付与・選択肢の追加) はしない。
// 救えなければ元の引数をそのまま返し、既存の検証に任せる。直す必要が無ければ同一の参照を返す。

const isObj = (v: unknown): v is Record<string, any> => typeof v === "object" && v !== null && !Array.isArray(v);

function fixOption(o: unknown): { value: unknown; changed: boolean } {
	if (typeof o === "string") return { value: { label: o, description: o }, changed: true }; // (iv)
	if (isObj(o) && typeof o.label === "string" && o.description === undefined) return { value: { ...o, description: o.label }, changed: true }; // (vii)
	return { value: o, changed: false };
}

function fixQuestion(q: unknown): { value: unknown; changed: boolean } {
	if (!isObj(q)) return { value: q, changed: false };
	let out: Record<string, any> = q;
	let changed = false;
	const set = (k: string, v: unknown) => {
		if (out === q) out = { ...q };
		out[k] = v;
		changed = true;
	};
	if (typeof out.question !== "string" && typeof out.header === "string") set("question", out.header); // (iii)
	if (Array.isArray(out.options)) {
		const fixed = out.options.map(fixOption);
		if (fixed.some((f) => f.changed)) set("options", fixed.map((f) => f.value));
	}
	if (out.multi === "true" || out.multi === "false") set("multi", out.multi === "true"); // (vi)
	return { value: out, changed };
}

export function normalizeAskArgs(args: unknown): any {
	if (!isObj(args)) return args;
	let changed = false;
	let rest: Record<string, any> = { ...args };
	let qs: unknown = rest.questions;

	if (typeof qs === "string") {
		// (v)
		try {
			const parsed = JSON.parse(qs);
			if (Array.isArray(parsed)) {
				qs = parsed;
				changed = true;
			}
		} catch {
			// 解析できなければそのまま (検証に任せる)
		}
	}

	if ((qs === undefined || qs === null) && typeof rest.question === "string" && rest.options !== undefined) {
		// (i) トップレベルに question・options
		const q: Record<string, any> = { question: rest.question, options: rest.options };
		if (rest.header !== undefined) q.header = rest.header;
		if (rest.multi !== undefined) q.multi = rest.multi;
		for (const k of ["question", "header", "options", "multi"]) delete rest[k];
		qs = [q];
		changed = true;
	}

	if (!Array.isArray(qs)) return changed ? { ...rest, questions: qs } : args;

	let list: unknown[] = qs;
	// (ii) 要素に question が無く、トップレベルに question がある → 最初の question の無い要素へ移す
	if (typeof rest.question === "string") {
		const i = list.findIndex((q) => isObj(q) && typeof q.question !== "string");
		if (i >= 0) {
			const target = list[i] as Record<string, any>;
			const moved: Record<string, any> = { ...target, question: rest.question };
			if (target.options === undefined && rest.options !== undefined) moved.options = rest.options;
			list = list.map((q, k) => (k === i ? moved : q));
			delete rest.question;
			if (moved.options !== target.options) delete rest.options;
			changed = true;
		}
	}
	const fixed = list.map(fixQuestion);
	if (fixed.some((f) => f.changed)) {
		list = fixed.map((f) => f.value);
		changed = true;
	}
	return changed ? { ...rest, questions: list } : args;
}
