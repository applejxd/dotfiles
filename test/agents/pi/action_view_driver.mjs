// git_commit の確認の表示 (要約・「全文を見る」・編集) を、偽の ctx (TUI 相当) で executeAction を直接動かして固定する。
// 結果を JSON で標準出力へ出す (照合は test_pi_action_view.py)。
//
//   node test/agents/pi/action_view_driver.mjs
//
// see docs/spec/guard/pi-extensions.md#guarded_action
import { execFileSync } from "node:child_process";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "..", "..", "..");
const mod = await import(pathToFileURL(resolve(ROOT, "home", "dot_config", "pi", "harness", "actions.ts")).href);
const { needsSummary, summaryBody, executeAction } = mod;

const COMMIT = {
	id: "git_commit",
	label: "コミット",
	argv: ["git", "commit", "-F", "{message_file}"],
	fields: { message: { type: "text", file: true, content: true, max_chars: 1200 }, dir: { type: "dir", optional: true } },
	replaces: ["git commit"],
	preview: "git_staged",
};
const ENV = { ...process.env, GIT_AUTHOR_NAME: "t", GIT_AUTHOR_EMAIL: "t@example.test", GIT_COMMITTER_NAME: "t", GIT_COMMITTER_EMAIL: "t@example.test" };
const git = (cwd, ...args) => execFileSync("git", args, { cwd, env: ENV, encoding: "utf8" }).trim();

function repo(files) {
	const dir = mkdtempSync(join(tmpdir(), "pi-view-"));
	git(dir, "init", "-q", "-b", "main");
	writeFileSync(join(dir, "seed.txt"), "seed\n");
	git(dir, "add", "-A");
	git(dir, "commit", "-q", "-m", "seed");
	for (let i = 0; i < files; i++) writeFileSync(join(dir, `f${i}.txt`), `${i}\n`);
	git(dir, "add", "-A");
	return dir;
}

const preview = (n) => ({
	branch: "main",
	head: "a".repeat(40),
	indexId: "x",
	stat: [...Array.from({ length: n }, (_, i) => ` f${i}.txt | 1 +`), ` ${n} files changed, ${n} insertions(+)`].join("\n"),
});
const BIG = "feat: subject line\n\n- a\n- b\n- c\n- d\n- e";

const out = {};
out.needs = {
	small: needsSummary(COMMIT, { message: "fix: x" }, preview(2)),
	lines6: needsSummary(COMMIT, { message: "a\nb\nc\nd\ne\nf" }, preview(2)),
	lines5: needsSummary(COMMIT, { message: "a\nb\nc\nd\ne" }, preview(2)),
	chars301: needsSummary(COMMIT, { message: "x".repeat(301) }, preview(2)),
	chars300: needsSummary(COMMIT, { message: "x".repeat(300) }, preview(2)),
	files6: needsSummary(COMMIT, { message: "fix: x" }, preview(6)),
	files5: needsSummary(COMMIT, { message: "fix: x" }, preview(5)),
	not_commit: needsSummary({ ...COMMIT, id: "gh_issue_comment" }, { message: BIG }, preview(9)),
	no_preview: needsSummary(COMMIT, { message: BIG }, null),
};
out.summary = summaryBody(COMMIT, { message: BIG }, preview(8), "/work/child");

async function run(files, message, answers) {
	const cwd = repo(files);
	const calls = { select: [], editor: [] };
	const ctx = {
		cwd,
		hasUI: true,
		mode: "tui",
		ui: {
			select: async (title, options) => {
				calls.select.push({ title, options });
				return answers.shift();
			},
			editor: async (title, text) => {
				calls.editor.push({ title, text });
				return typeof answers[0] === "object" ? answers.shift().text : text;
			},
			input: async () => "",
		},
	};
	const deps = {
		actions: [COMMIT],
		rules: {},
		child: false,
		env: ENV,
		redact: (s) => s,
		judge: () => null,
		dialog: (fn) => fn(),
		bell: () => {},
	};
	const before = git(cwd, "rev-parse", "HEAD");
	let result;
	try {
		const r = await executeAction(deps, { action: "git_commit", params: { message } }, undefined, ctx);
		result = { ok: true, text: r.content[0].text };
	} catch (e) {
		result = { ok: false, text: String(e.message) };
	}
	return { calls, result, advanced: git(cwd, "rev-parse", "HEAD") !== before, subject: git(cwd, "log", "-1", "--format=%s") };
}

out.small_commit = await run(2, "fix: small", ["承認して実行"]);
out.big_approve = await run(6, BIG, ["承認して実行"]);
out.big_view_then_approve = await run(6, BIG, ["全文を見る", "承認して実行"]);
out.big_view_twice_then_reject = await run(6, BIG, ["全文を見る", "全文を見る", "拒否"]);
out.big_edit = await run(6, BIG, ["編集して承認", { text: "feat: edited subject" }]);
process.stdout.write(JSON.stringify(out));
