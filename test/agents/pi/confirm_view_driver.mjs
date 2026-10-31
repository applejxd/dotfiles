// confirm-view.ts の表試験 (確認の本文・gh の解析・結果の分類)。結果を JSON で標準出力へ出す
// (照合は test_pi_confirm_view.py)。
//
//   node test/agents/pi/confirm_view_driver.mjs
//
// see docs/spec/guard/pi-guard.md
import { dirname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "..", "..", "..");
const mod = await import(pathToFileURL(resolve(ROOT, "home", "dot_config", "pi", "harness", "confirm-view.ts")).href);
const { sanitizeForDisplay, shellWords, parseGh, buildMustConfirmView, classifyConfirm, outcomeReason, confirmTimeoutSeconds, parseFinishTarget, extractSquashMessage, parseNumstat } = mod;

const files = { "body.md": "本文の 1 行目\n2 行目", "big.md": "x".repeat(9000) };
const reader = (p) => (p in files ? { ok: true, text: files[p] } : { ok: false, why: `${p} を読めない` });

const out = {};
out.sanitize = {
	ansi: sanitizeForDisplay("a\x1b[31mred\x1b[0m"),
	keep: sanitizeForDisplay("a\tb\nc"),
	ctl: sanitizeForDisplay("a\x00b\x07c\rd\x7fe\u202ef\u200b"),
};
out.words = {
	plain: shellWords("gh pr create --title 'a b' -b \"c d\""),
	escape: shellWords('a\\ b "x\\"y"'),
	continuation: shellWords("a \\\nb"),
	subst: shellWords("a $(b)"),
	dquote_dollar: shellWords('a "$HOME"'),
	pipe: shellWords("a | b"),
	open: shellWords("a 'b"),
};
const p = (c) => parseGh(c);
out.gh = {
	create: p("gh pr create --title T --body B -R o/r"),
	short_attached: p("gh pr create -tT -b=B --base main -H feat"),
	eq: p("gh issue create --title=T --body=B --label bug"),
	multiline: p("gh issue comment 12 --body 'line1\nline2'"),
	bundle: p("gh pr create -dw -t T"),
	review: p("gh pr review 5 -a -b ok"),
	close_comment: p("gh pr close 7 -c bye"),
	merge: p("gh pr merge 3 -s -d"),
	positional_dashdash: p("gh pr edit -- 9"),
	body_file: p("gh pr create -F body.md -t T"),
	unknown_flag: p("gh pr create --nope x"),
	missing_value: p("gh pr create --title"),
	chained: p("gh pr create -t T && echo x"),
	subst: p("gh pr create -b \"$(cat f)\""),
	not_gh: p("git pr create"),
	other_action: p("gh pr list"),
	bool_with_value: p("gh pr create --draft=true"),
};
const reason = "確認が必要な外部への送信・公開 (bypass でも確認する): gh pr create";
const view = (c) => buildMustConfirmView(c, reason, reader);
out.integration_view = buildMustConfirmView("git flow feature finish x", "確認が必要な保護ブランチへの統合 (bypass でも確認する): git flow feature finish (保護ブランチへ統合・削除する)", reader);
out.view = {
	basic: view("gh pr create --title T --body B -R o/r"),
	full_command: view(`echo ${"z".repeat(20000)} | gh pr create`),
	ansi: view("gh pr create --title T --body '\x1b[31mred'"),
	body_file: view("gh pr create -t T -F body.md"),
	body_file_missing: view("gh pr create -t T -F nope.md"),
	body_file_stdin: view("gh pr create -t T -F -"),
	body_file_big: view("gh pr create -t T -F big.md"),
	long_inline: view(`gh pr create --title T --body '${"y".repeat(5000)}' -R o/r`),
	long_over: view(`gh pr create --title T --body '${"y".repeat(8001)}'`),
	unparsed: view("gh pr create --body \"$(cat f)\""),
};

// git flow finish: 統合の内容と squash メッセージ
const intReason = "確認が必要な保護ブランチへの統合 (bypass でも確認する): git flow feature finish (保護ブランチへ統合・削除する)";
const finishFiles = { "msg.txt": "docs: 件名\n\n本文の 1 行目\n\n", "long.txt": "y".repeat(5000) };
const finishReader = (p) => (p in finishFiles ? { ok: true, text: finishFiles[p] } : { ok: false, why: `${p} を読めない` });
const facts = {
	ok: true,
	branch: "feature/x",
	target: "develop",
	commitCount: 7,
	commits: ["aaa1111 件名 1", "bbb2222 件名 2", "ccc3333 件名 3", "ddd4444 件名 4", "eee5555 件名 5", "fff6666 件名 6"],
	files: parseNumstat(
		[1, 2, 3, 4, 5, 6, 7, 8, 9, 10].map((i) => `${i}\t${i % 2}\tdocs/f${i}.md`).join("\n") + "\n-\t-\timg/a.png\n",
	),
};
const finishView = (c, f = facts, r = finishReader) => buildMustConfirmView(c, intReason, r, f);
out.finish = {
	target_plain: parseFinishTarget("git flow feature finish x --squash"),
	target_prefixed: parseFinishTarget("git flow bugfix finish bugfix/y"),
	target_other: parseFinishTarget("git flow release finish 1.0"),
	target_chained: parseFinishTarget("cd /x && git flow feature finish x"),
	target_flag_first: parseFinishTarget("git flow feature finish --squash x"),
	msg_none: extractSquashMessage("git flow feature finish x --squash"),
	msg_eq_dq: extractSquashMessage('git flow feature finish x --squash-message="a b\nc" --keepremote'),
	msg_space_sq: extractSquashMessage("git flow feature finish x --squash-message 'a $b' --keepremote"),
	msg_bare: extractSquashMessage("git flow feature finish x --squash-message=docs:one"),
	msg_file: extractSquashMessage('git flow feature finish x --squash-message="$(cat msg.txt)" --keepremote'),
	msg_file_unquoted: extractSquashMessage("git flow feature finish x --squash-message=$(cat dir/msg.txt)"),
	msg_file_option_like: extractSquashMessage('git flow feature finish x --squash-message="$(cat -n msg.txt)"'),
	msg_other_subst: extractSquashMessage('git flow feature finish x --squash-message="$(git log -1)"'),
	msg_var: extractSquashMessage('git flow feature finish x --squash-message="$MSG"'),
	numstat: parseNumstat("3\t1\ta.md\n-\t-\tb.png\nnot a line\n"),
	view_literal: finishView('git flow feature finish x --squash --squash-message="docs: 件名\n\n本文"'),
	view_file: finishView('git flow feature finish x --squash --squash-message="$(cat msg.txt)" --keepremote'),
	view_file_missing: finishView('git flow feature finish x --squash --squash-message="$(cat nope.txt)"'),
	view_file_long: finishView('git flow feature finish x --squash-message="$(cat long.txt)"'),
	view_unresolved: finishView('git flow feature finish x --squash --squash-message="$(git log -1)"'),
	view_no_message: finishView("git flow feature finish x --squash"),
	view_no_squash: finishView("git flow feature finish x"),
	view_facts_failed: finishView("git flow feature finish x --squash", { ok: false, branch: "feature/x", target: "develop", why: "git が失敗した (終了コード 128)" }),
	view_no_facts: finishView('git flow feature finish x --squash --squash-message="abc"', null),
	view_not_finish: finishView("git merge x"),
	view_other_reason: buildMustConfirmView('git flow feature finish x --squash-message="abc"', "確認が必要な外部への送信・公開 (bypass でも確認する): x", finishReader, facts),
	view_ansi: finishView('git flow feature finish x --squash-message="a\x1b[31mred"'),
};
out.classify = {
	approved: classifyConfirm({ ok: true, elapsedMs: 1, aborted: false, error: false }, 1000),
	denied: classifyConfirm({ ok: false, elapsedMs: 100, aborted: false, error: false }, 1000),
	timeout: classifyConfirm({ ok: false, elapsedMs: 1005, aborted: false, error: false }, 1000),
	aborted: classifyConfirm({ ok: false, elapsedMs: 5000, aborted: true, error: false }, 1000),
	error: classifyConfirm({ ok: false, elapsedMs: 0, aborted: false, error: true }, 1000),
};
out.reasons = Object.fromEntries(["denied", "timeout", "aborted", "error", "approved"].map((k) => [k, outcomeReason(k)]));
const rules = (v) => ({ judge: { common: { pi: { confirm: v === undefined ? {} : { timeout_seconds: v } } } } });
out.timeout = {
	default: confirmTimeoutSeconds({}),
	set: confirmTimeoutSeconds(rules(7)),
	zero: confirmTimeoutSeconds(rules(0)),
	float: confirmTimeoutSeconds(rules(1.5)),
	string: confirmTimeoutSeconds(rules("9")),
	missing: confirmTimeoutSeconds(rules(undefined)),
};
process.stdout.write(JSON.stringify(out));
