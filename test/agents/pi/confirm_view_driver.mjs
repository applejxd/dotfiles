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
const { sanitizeForDisplay, shellWords, parseGh, buildMustConfirmView, classifyConfirm, outcomeReason, confirmTimeoutSeconds } = mod;

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
