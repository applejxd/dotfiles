// 伏字化 (フルガードが使う)。
//
// 設定は rules.json の `redact` (common.toml の [pi.redact] から生成)。
// - redactText / redactValue / redactResult: 内容の形で伏せる (秘密鍵・トークンなど)
// - deniedPathIn: コマンドが保護対象のパスを参照していれば、どこが秘密か分からないので出力ごと伏せる
// - withheld: 出力ごと伏せたときの結果
//
// node の型除去でそのまま動く書き方だけを使う。
// see docs/spec/guard/pi-guard.md#しくみ

export type RedactConfig = {
	rule: { name: string; pattern: string }[];
	deny_path?: string[];
	deny_path_unless?: string;
};

export type Redactor = {
	redactText(text: string): string;
	redactValue(v: any): any;
	redactResult(r: any): any;
	deniedPathIn(command: string): string | null;
	withheld(hit: string): any;
};

export function createRedactor(config: RedactConfig): Redactor {
	if (!config || !Array.isArray(config.rule)) throw new Error("rules.json に redact が無い");
	const rules = config.rule.map((r) => ({ name: r.name, re: new RegExp(r.pattern, "gi") }));
	const denyPath = (config.deny_path ?? []).map((p) => new RegExp(p));
	// /g を付けない (.test の lastIndex が残る)
	const denyPathUnless = config.deny_path_unless ? new RegExp(config.deny_path_unless) : null;

	function redactText(text: string): string {
		let out = text;
		// 置換文字列にせず関数で返す ($& などを解釈させない)
		for (const r of rules) out = out.replace(r.re, () => `[伏字:${r.name}]`);
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

	function deniedPathIn(command: string): string | null {
		if (denyPathUnless?.test(command)) return null;
		for (const token of command.split(/[\s;|&<>()"'`]+/)) {
			if (!token || (!/[/\\]/.test(token) && !token.startsWith("~") && !token.startsWith("."))) continue;
			const p = token.replace(/\\/g, "/");
			if (denyPath.some((re) => re.test(p))) return token;
		}
		return null;
	}

	function withheld(hit: string): any {
		const text = `[伏字] 保護対象のパス (${hit}) を参照したため、このコマンドの出力を伏せました。`;
		return { content: [{ type: "text", text }], details: undefined, structuredContent: { withheld: text } };
	}

	return { redactText, redactValue, redactResult, deniedPathIn, withheld };
}
