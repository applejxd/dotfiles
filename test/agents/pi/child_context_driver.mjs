// child-context.ts の表試験。結果を JSON で標準出力へ出す (照合は test_pi_child_context.py)。
//
//   node test/agents/pi/child_context_driver.mjs
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "..", "..", "..");
const mod = await import(pathToFileURL(join(ROOT, "home", "dot_config", "pi", "harness", "child-context.ts")).href);
const { resolveContext, lint } = mod;

const L = (...a) => a.join("\n");
const FENCE = "```";
const ID = "<!-- child-context: v1 -->";
const R = (text, role, mode = "extract") => resolveContext(text, role, mode);

const ok = L(ID, "# 題", "<!-- parent -->", "親の規則", "<!-- /parent -->", "<!-- child:worker -->", "子の規則", "<!-- /child -->");
const two = L(ID, "<!-- child:worker,review -->", "X", "<!-- /child -->", "<!-- child:review -->", "Y", "<!-- /child -->");
const broken = L(ID, "<!-- child:worker -->", "X");

const resolves = {
	legacy: R("ただの文\n- 箇条書き\n", "worker"),
	legacy_empty: R("", "worker"),
	legacy_heading_only: R("# 題\n", "worker"),
	basic: R(ok, "worker"),
	other_role_empty: R(ok, "review"),
	multi_review: R(two, "review"),
	multi_worker: R(two, "worker"),
	role_differs_explore: R(L(ID, "<!-- child:explore -->", "E", "<!-- /child -->", "<!-- child:review -->", "R", "<!-- /child -->"), "explore"),
	role_differs_review: R(L(ID, "<!-- child:explore -->", "E", "<!-- /child -->", "<!-- child:review -->", "R", "<!-- /child -->"), "review"),
	all_mark: R(L(ID, "<!-- child:all -->", "X", "<!-- /child -->"), "plan"),
	all_role: R(ok, "all"),
	id_blank_first: R(L("", "  ", ID, "<!-- child:worker -->", "X", "<!-- /child -->"), "worker"),
	id_not_first: R(L("# 題", ID, "<!-- child:worker -->", "X", "<!-- /child -->"), "worker"),
	id_after_text: R(L("文", ID, "<!-- child:worker -->", "X", "<!-- /child -->"), "worker"),
	id_only: R(ID, "worker"),
	id_and_headings_only: R(L(ID, "# 題", "## 節"), "worker"),
	marks_no_id: R(L("<!-- child:worker -->", "X", "<!-- /child -->"), "worker"),
	parent_no_id: R(L("<!-- parent -->", "p", "<!-- /parent -->"), "worker"),
	unclosed: R(broken, "worker"),
	unclosed_parent: R(L(ID, "<!-- child:worker -->", "X", "<!-- /child -->", "<!-- parent -->", "p"), "worker"),
	nested: R(L(ID, "<!-- child:worker -->", "<!-- parent -->", "X", "<!-- /parent -->", "<!-- /child -->"), "worker"),
	nested_child: R(L(ID, "<!-- child:worker -->", "<!-- child:review -->", "X", "<!-- /child -->", "<!-- /child -->"), "worker"),
	close_only: R(L(ID, "<!-- child:worker -->", "X", "<!-- /child -->", "<!-- /child -->"), "worker"),
	close_parent_only: R(L(ID, "<!-- child:worker -->", "X", "<!-- /child -->", "<!-- /parent -->"), "worker"),
	mismatched_close: R(L(ID, "<!-- parent -->", "p", "<!-- /child -->"), "worker"),
	unknown_role: R(L(ID, "<!-- child:worker,boss -->", "X", "<!-- /child -->"), "worker"),
	empty_role: R(L(ID, "<!-- child: -->", "X", "<!-- /child -->"), "worker"),
	unknown_version: R(L("<!-- child-context: v2 -->", "<!-- child:worker -->", "X", "<!-- /child -->"), "worker"),
	look_unclosed_tag: R(L(ID, "<!-- child:worker", "X", "<!-- /child -->"), "worker"),
	look_nospace: R(L(ID, "<!--child worker-->", "X"), "worker"),
	look_ctx_spaced: R(L("<!-- child-context: v 1 -->", "<!-- child:worker -->", "X", "<!-- /child -->"), "worker"),
	look_parent_typo: R(L(ID, "<!-- parents -->", "<!-- child:worker -->", "X", "<!-- /child -->"), "worker"),
	look_no_id: R(L("<!-- child worker -->", "文"), "worker"),
	look_in_fence_ignored: R(L(ID, "<!-- parent -->", FENCE, "<!-- child worker-->", FENCE, "<!-- /parent -->", "<!-- child:worker -->", "X", "<!-- /child -->"), "worker"),
	// 導入前 (識別子も有効な印も無い) のファイルの普通のコメントは、印に似ていても全文 (legacy)
	legacy_generated_parent: R("# Rules\n<!-- generated from parent guide -->\n- 日本語で回答する。\n", "worker"),
	legacy_children_section: R("# Rules\n<!-- see the children section -->\n- x\n", "worker"),
	legacy_parent_directory: R("# Rules\n<!-- parent directory -->\n- x\n", "worker"),
	legacy_markdownlint: R("# Rules\n<!-- markdownlint-disable MD013 -->\n- x\n", "worker"),
	legacy_lookalike_tag: R(L("<!-- child worker -->", "文"), "worker"),
	legacy_lookalike_close: R(L("文", "<!-- /parent -->x", "- y"), "worker"),
	// 導入のつもりの書き損じ (child-context で始まる有効でない行) は、導入前でも破損
	legacy_ident_no_version: R(L("# Rules", "<!-- child-context -->", "文"), "worker"),
	legacy_ident_spaced: R(L("<!-- child-context: v 1 -->", "文"), "worker"),
	legacy_ident_upper: R(L("<!-- CHILD-CONTEXT: v1 -->", "文"), "worker"),
	// 導入済み (有効な識別子・有効な印がある) では、印に似た行・普通のコメントは破損
	adopted_plain_comment_outside: R(L(ID, "<!-- child:worker -->", "X", "<!-- /child -->", "<!-- generated from parent guide -->"), "worker"),
	adopted_plain_comment_inside: R(L(ID, "<!-- child:worker -->", "<!-- generated from parent guide -->", "X", "<!-- /child -->"), "worker"),
	valid_mark_plus_lookalike_no_id: R(L("<!-- child worker -->", "<!-- child:worker -->", "X", "<!-- /child -->"), "worker"),
	// コードブロックの区切りは、文字と長さを保つ (閉じは、同じ文字で、開き以上の長さ)
	fence4_not_closed_by_3: R(L(ID, "<!-- child:worker -->", "````", FENCE, "<!-- /child -->", "````", "後", "<!-- /child -->"), "worker"),
	fence_closed_by_longer: R(L(ID, "<!-- child:worker -->", FENCE, "x", "`````", "後", "<!-- /child -->"), "worker"),
	tilde4_not_closed_by_3: R(L(ID, "<!-- child:worker -->", "~~~~", "~~~", "<!-- /child -->", "~~~~", "後", "<!-- /child -->"), "worker"),
	backtick_info_not_fence: R(L(ID, "<!-- child:worker -->", FENCE + " `x`", "後", "<!-- /child -->"), "worker"),
	fence_close_with_text_is_not_close: R(L(ID, "<!-- child:worker -->", FENCE, FENCE + "js", "<!-- /child -->", FENCE, "後", "<!-- /child -->"), "worker"),
	unclassified_text: R(L(ID, "<!-- child:worker -->", "X", "<!-- /child -->", "新しい段落"), "worker"),
	unclassified_bullet: R(L(ID, "<!-- child:worker -->", "X", "<!-- /child -->", "- 付け忘れ"), "worker"),
	unclassified_table: R(L(ID, "<!-- child:worker -->", "X", "<!-- /child -->", "| a | b |", "| - | - |"), "worker"),
	unclassified_fence: R(L(ID, "<!-- child:worker -->", "X", "<!-- /child -->", FENCE, "code", FENCE), "worker"),
	unclassified_new_section: R(L(ID, "<!-- child:worker -->", "X", "<!-- /child -->", "## 新節", "本文"), "worker"),
	headings_allowed: R(L(ID, "# 題", "## 節", "<!-- child:worker -->", "X", "<!-- /child -->", "### 小節"), "worker"),
	in_fence: R(L(ID, "<!-- parent -->", FENCE, "<!-- child:worker -->", "秘密", "<!-- /child -->", FENCE, "<!-- /parent -->", "<!-- child:worker -->", "本物", "<!-- /child -->"), "worker"),
	fence_inside_block: R(L(ID, "<!-- child:worker -->", FENCE, "<!-- /child -->", FENCE, "後", "<!-- /child -->"), "worker"),
	// ``` で開いたコードブロックは、~~~ では閉じない (中の閉じ印は無視される)
	mixed_fence_not_closed: R(L(ID, "<!-- child:worker -->", FENCE, "~~~", "<!-- /child -->", FENCE, "後", "<!-- /child -->"), "worker"),
	heading_in_fence_not_heading: R(L(ID, "<!-- parent -->", FENCE, "# x", FENCE, "<!-- /parent -->", "<!-- child:worker -->", "X", "<!-- /child -->"), "worker"),
	crlf: R(`${ID}\r\n# 題\r\n<!-- child:worker -->\r\nX\r\n<!-- /child -->\r\n`, "worker"),
	crlf_unclassified: R(`${ID}\r\n<!-- child:worker -->\r\nX\r\n<!-- /child -->\r\n文\r\n`, "worker"),
	whole_line_only: R(L(ID, "文 <!-- child:worker --> 文", "<!-- child:worker -->", "X", "<!-- /child -->"), "worker"),
	zero_blocks: R(L(ID, "<!-- parent -->", "p", "<!-- /parent -->"), "worker"),
	inherit_legacy: R("そのまま\n- 全部", "worker", "inherit"),
	inherit_ok: R(ok, "worker", "inherit"),
	inherit_broken: R(broken, "worker", "inherit"),
	inherit_unclassified: R(L(ID, "未分類"), "review", "inherit"),
	unknown_mode: R(ok, "worker", "full"),
	unknown_role_arg: R(ok, "boss"),
	unknown_role_inherit: R(ok, "boss", "inherit"),
	empty_role_arg: R(ok, ""),
};

const lints = {
	clean: lint(ok),
	legacy: lint("ただの文\n"),
	no_id_marks: lint(L("<!-- child:worker -->", "X", "<!-- /child -->")),
	id_not_first: lint(L("# 題", ID, "<!-- child:worker -->", "X", "<!-- /child -->")),
	zero_blocks: lint(L(ID, "# 題")),
	unclosed: lint(L(ID, "a", "<!-- child:worker -->", "X")),
	nested: lint(L(ID, "<!-- child:worker -->", "<!-- child:review -->", "X", "<!-- /child -->", "<!-- /child -->")),
	close_only: lint(L(ID, "<!-- child:worker -->", "X", "<!-- /child -->", "<!-- /child -->")),
	unknown_role: lint(L(ID, "<!-- child:boss -->", "X", "<!-- /child -->")),
	unknown_version: lint(L("<!-- child-context: v9 -->", "<!-- child:worker -->", "X", "<!-- /child -->")),
	lookalike: lint(L(ID, "<!--child worker-->", "<!-- child:worker -->", "X", "<!-- /child -->")),
	unclassified: lint(L(ID, "<!-- child:worker -->", "X", "<!-- /child -->", "", "新しい段落")),
	many: lint(L(ID, "未分類 A", "<!-- child:boss -->", "X", "<!-- /child -->", "未分類 B")),
	in_fence_ignored: lint(L(ID, "<!-- parent -->", FENCE, "<!-- child:boss -->", FENCE, "<!-- /parent -->", "<!-- child:worker -->", "X", "<!-- /child -->")),
};

console.log(JSON.stringify({ resolves, lints }));
