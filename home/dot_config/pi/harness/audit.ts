// 子の完了結果の形式検査 (純粋関数。依存なし)。結果の本文は変えず、警告と事実行の材料だけを作る。
// 標準形は 結論 / 根拠 / 未確認 / 次の候補。

// 見出し名と、行頭 (記号を除いた後) がこれらで始まれば見出しとみなす語
const SECTIONS: { name: string; heads: string[] }[] = [
	{ name: "結論", heads: ["結論"] },
	{ name: "根拠", heads: ["根拠"] },
	{ name: "未確認", heads: ["未確認"] },
	{ name: "次の候補", heads: ["次の"] },
];

// 行頭の装飾 (見出しの #、強調の * _、箇条書きの -、引用の >、空白)
const LEAD = /^[\s#*_\->]+/;

// 答えの中に無い標準見出しの名前を、標準の並びで返す
export function auditFormat(answer: string): string[] {
	const lines = String(answer ?? "")
		.split(/\r?\n/)
		.map((l) => l.replace(LEAD, ""));
	return SECTIONS.filter((s) => !lines.some((l) => s.heads.some((h) => l.startsWith(h)))).map((s) => s.name);
}

// ツール名ごとの件数を `bash×2 read×5` の形に。多い順、同数は名前順。先頭の guarded_ は除く
export function summarizeCalls(names: string[]): string {
	const counts = new Map<string, number>();
	for (const n of names) {
		const name = String(n).replace(/^guarded_/, "");
		counts.set(name, (counts.get(name) ?? 0) + 1);
	}
	if (counts.size === 0) return "none";
	return [...counts.entries()]
		.sort((a, b) => b[1] - a[1] || (a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0))
		.map(([n, c]) => `${n}×${c}`)
		.join(" ");
}

// 依頼文の「守る条件」の番号 (C1・C2 …) を、行頭の `C1:` `- C1:` `**C1**:` の形で取り出す。重複は 1 つにする
const REQUESTED = /^[\s>*_\-]*\**\s*(C\d+)\s*\**\s*[:：]/;
export function requestedConditions(task: string): string[] {
	const out: string[] = [];
	for (const line of String(task ?? "").split(/\r?\n/)) {
		const m = REQUESTED.exec(line);
		if (m && !out.includes(m[1])) out.push(m[1]);
	}
	return out;
}

// 返答の「守る条件の突き合わせ」の節に、依頼の番号が全部あるかを調べる。
// 依頼に番号が無ければ検査しない (null)。節が無ければ noSection、欠けた番号は missing。
// 番号の一致は条件を満たす証明ではない (内容の確認は読み手に残る)
export type ConditionAudit = { requested: string[]; noSection: boolean; missing: string[] };
export function auditConditions(task: string, answer: string): ConditionAudit | null {
	const requested = requestedConditions(task);
	if (requested.length === 0) return null;
	const lines = String(answer ?? "").split(/\r?\n/);
	const isHeading = (l: string) => /^\s*#{1,6}\s/.test(l) || /^\s*\**\d+[.)]\s/.test(l);
	const start = lines.findIndex((l) => isHeading(l) && l.includes("守る条件"));
	if (start < 0) return { requested, noSection: true, missing: requested };
	let end = lines.length;
	for (let i = start + 1; i < lines.length; i++) {
		if (isHeading(lines[i])) {
			end = i;
			break;
		}
	}
	const section = lines.slice(start, end).join("\n");
	const missing = requested.filter((id) => !new RegExp(`(?<![A-Za-z0-9])${id}(?!\\d)`).test(section));
	return { requested, noSection: false, missing };
}
