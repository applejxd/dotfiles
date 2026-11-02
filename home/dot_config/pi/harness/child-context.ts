// 子向けの印の解決 (`resolveContext`) と検査 (`lint`)。純粋関数 (I/O なし)。契約: docs/change/closed/0059-child-context.md §4.1
//
// 記法 (行全体がその 1 つのコメントのときだけ印。コードブロック ``` / ~~~ の中の印は無視):
//   <!-- child-context: v1 -->                    導入済みの識別子 (コードブロックの外の最初の空でない行)
//   <!-- child:worker,review --> 〜 <!-- /child -->  子向け (役割: explore / review / plan / worker / all)
//   <!-- parent --> 〜 <!-- /parent -->            親だけ
// 見出し行はブロックの外にあってよい。それ以外の空でない行がブロックの外にあれば未分類。
// 入れ子・閉じ忘れ・開き無しの閉じ・未知の役割・未知の版・印に似た行は破損 (印に似た行 = `<!--` の直後の語が child / parent の行)。
// 導入前 (有効な識別子も印も無い) のファイルは、印に似た行・普通のコメントを無視して全文 (legacy)。ただし child-context の綴り違いは常に破損。

export const CHILD_ROLES = ["explore", "review", "plan", "worker"];
export const CONTEXT_VERSION = "v1";

export type Resolved =
	| { kind: "full"; why: "inherit" | "legacy"; text: string }
	| { kind: "extract"; text: string; blocks: number }
	| { kind: "error"; reason: string };
export type LintResult = { ok: boolean; problems: string[] };

type Block = { roles: string[]; start: number; lines: string[] };
type Scan = {
	blocks: Block[]; // 閉じた子向けブロック
	problems: string[]; // 破損・未分類 (行番号つき)
	hasIdent: boolean;
	hasMarks: boolean; // 有効な識別子・有効な印・識別子の書き損じのどれかがある (導入済み)。印に似ただけの行は含まない
};

const IDENT = /^\s*<!--\s*child-context:\s*(v\d+)\s*-->\s*$/;
const CHILD_OPEN = /^\s*<!--\s*child:([^>]*?)\s*-->\s*$/;
const CHILD_CLOSE = /^\s*<!--\s*\/child\s*-->\s*$/;
const PARENT_OPEN = /^\s*<!--\s*parent\s*-->\s*$/;
const PARENT_CLOSE = /^\s*<!--\s*\/parent\s*-->\s*$/;
const BAD_IDENT = /^\s*<!--\s*child-context\b/i; // child-context で始まるが IDENT でない行 = 導入のつもりの書き損じ (常に破損)
const LOOKALIKE = /^\s*<!--\s*\/?\s*(?:child|parent)(?![\w-])/i; // <!-- の直後の語が child / parent の行だけ (中の語は見ない)
const HEADING = /^#{1,6}(?:\s|$)/;
const FENCE = /^\s*(`{3,}|~{3,})(.*)$/;

function parseRoles(raw: string): { roles: string[]; bad: string[] } {
	const roles: string[] = [];
	const bad: string[] = [];
	for (const r of raw.split(",").map((s) => s.trim())) {
		if (r === "all") roles.push(...CHILD_ROLES);
		else if (CHILD_ROLES.includes(r)) roles.push(r);
		else bad.push(r);
	}
	return { roles, bad };
}

function scan(text: string): Scan {
	const lines = text.split(/\r?\n/);
	const blocks: Block[] = [];
	const problems: string[] = [];
	const err = (no: number, msg: string) => problems.push(`${no} 行目: ${msg}`);
	let open: { type: "child" | "parent"; start: number; block: Block | null } | null = null;
	let fence: string | null = null;
	let seenNonEmpty = false;
	let hasIdent = false;
	let hasMarks = false;
	for (let i = 0; i < lines.length; i++) {
		const line = lines[i];
		const no = i + 1;
		const blank = line.trim() === "";
		const f = FENCE.exec(line);
		if (f || fence !== null) {
			if (f) {
				if (fence === null) {
					if (!(f[1][0] === "`" && f[2].includes("`"))) {
						fence = f[1];
						if (!open) err(no, "未分類: ブロックの外のコードブロック (子向けか親だけの印で囲む)");
					}
				} else if (f[1][0] === fence[0] && f[1].length >= fence.length && f[2].trim() === "") fence = null;
			}
			seenNonEmpty = true;
			if (open?.block) open.block.lines.push(line);
			continue;
		}
		if (blank) {
			if (open?.block) open.block.lines.push(line);
			continue;
		}
		const first = !seenNonEmpty;
		seenNonEmpty = true;
		const id = IDENT.exec(line);
		if (id) {
			hasMarks = true;
			if (id[1] !== CONTEXT_VERSION) err(no, `未知の版 ${JSON.stringify(id[1])} (使えるのは ${CONTEXT_VERSION})`);
			else if (!first || open) err(no, "識別子 <!-- child-context: v1 --> がファイルの最初の空でない行に無い");
			else hasIdent = true;
			continue;
		}
		const co = CHILD_OPEN.exec(line);
		if (co) {
			hasMarks = true;
			const { roles, bad } = parseRoles(co[1]);
			if (bad.length > 0) err(no, `未知の役割 ${bad.map((b) => JSON.stringify(b) || '"" (役割が空)').join(", ")} (使えるのは ${CHILD_ROLES.join(" / ")} / all)`);
			if (open) {
				err(no, `子向けの印が入れ子 (${open.start} 行目の ${open.type} がまだ閉じていない)`);
				continue;
			}
			open = { type: "child", start: no, block: { roles: bad.length > 0 ? [] : roles, start: no, lines: [] } };
			continue;
		}
		if (PARENT_OPEN.test(line)) {
			hasMarks = true;
			if (open) err(no, `親だけの印が入れ子 (${open.start} 行目の ${open.type} がまだ閉じていない)`);
			else open = { type: "parent", start: no, block: null };
			continue;
		}
		const cc = CHILD_CLOSE.test(line);
		if (cc || PARENT_CLOSE.test(line)) {
			hasMarks = true;
			const want = cc ? "child" : "parent";
			if (!open) err(no, `閉じ印 <!-- /${want} --> だけがある (開きが無い)`);
			else if (open.type !== want) err(no, `閉じ印 <!-- /${want} --> が ${open.start} 行目の ${open.type} に対応しない`);
			else {
				if (open.block) blocks.push(open.block);
				open = null;
			}
			continue;
		}
		if (BAD_IDENT.test(line)) {
			hasMarks = true;
			err(no, `識別子の書式が違う行 (${line.trim()})。正しくは ${"<!-- child-context: v1 -->"}`);
			continue;
		}
		if (LOOKALIKE.test(line)) {
			// 導入前のファイルでは無視される (resolveContext)。導入済みでは破損
			err(no, `印に似ているが書式が違う行 (${line.trim()})`);
			continue;
		}
		if (open) {
			if (open.block) open.block.lines.push(line);
			continue;
		}
		if (!HEADING.test(line)) err(no, `未分類: ブロックの外に子向け・親だけの印の無い行がある (${line.trim().slice(0, 40)})`);
	}
	if (open) err(open.start, `${open.type === "child" ? "子向け" : "親だけ"}の印が閉じていない (<!-- /${open.type} --> が無い)`);
	return { blocks, problems, hasIdent, hasMarks };
}

function trimBlank(lines: string[]): string[] {
	let s = 0;
	let e = lines.length;
	while (s < e && lines[s].trim() === "") s++;
	while (e > s && lines[e - 1].trim() === "") e--;
	return lines.slice(s, e);
}

const NO_IDENT = "識別子 <!-- child-context: v1 --> が無い";
const NO_BLOCKS = "子向けブロック <!-- child:... --> が 1 つも無い";

export function resolveContext(text: string, role: string, mode: string): Resolved {
	if (mode !== "extract" && mode !== "inherit") return { kind: "error", reason: `未知の mode ${JSON.stringify(mode)} (extract / inherit)` };
	if (!CHILD_ROLES.includes(role)) return { kind: "error", reason: `未知の役割 ${JSON.stringify(role)} (使えるのは ${CHILD_ROLES.join(" / ")})` };
	if (mode === "inherit") return { kind: "full", why: "inherit", text };
	const s = scan(text);
	if (!s.hasMarks) return { kind: "full", why: "legacy", text }; // 導入前: 印に似た行・普通のコメントは無視して全文
	if (!s.hasIdent) return { kind: "error", reason: [NO_IDENT, ...s.problems].join("; ") };
	if (s.problems.length > 0) return { kind: "error", reason: s.problems.join("; ") };
	if (s.blocks.length === 0) return { kind: "error", reason: NO_BLOCKS };
	const picked = s.blocks.filter((b) => b.roles.includes(role));
	const parts = picked.map((b) => trimBlank(b.lines).join("\n")).filter((p) => p !== "");
	return { kind: "extract", text: parts.join("\n\n"), blocks: picked.length };
}

export function lint(text: string): LintResult {
	const s = scan(text);
	const problems = [...s.problems];
	if (!s.hasIdent) problems.unshift(NO_IDENT);
	if (s.blocks.length === 0 && !s.problems.some((p) => p.includes("閉じていない"))) problems.push(NO_BLOCKS);
	return { ok: problems.length === 0, problems };
}
