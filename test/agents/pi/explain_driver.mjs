// explain.ts と confirm-view.ts の手順の一覧の表試験。結果を JSON で標準出力へ出す (照合は test_pi_explain.py)。
//
//   node test/agents/pi/explain_driver.mjs
//
// see docs/spec/guard/pi-extensions.md#確認画面の手順の一覧
import { dirname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "..", "..", "..");
const H = resolve(ROOT, "home", "dot_config", "pi", "harness");
const ex = await import(pathToFileURL(resolve(H, "explain.ts")).href);
const view = await import(pathToFileURL(resolve(H, "confirm-view.ts")).href);

const E = (c, hit) => ex.explainCommand(c, hit);
const texts = (c, hit) => E(c, hit).steps.map((s) => s.text);

// mvdan-sh を読み込めないときの動作 (PI_EXPLAIN_VENDOR で読み込み先を壊して呼ぶ)
if (process.argv[2] === "--fallback") {
	const cmds = ["ls -la", "cd /x && git push", "echo 日本語 && ls", ""];
	console.log(JSON.stringify(Object.fromEntries(cmds.map((c) => [c, E(c)]))));
	process.exit(0);
}

// 名前 → コマンド。ケースの名前は test_pi_explain.py が参照する
const CASES = {
	pipe_write: "cd /abs && git log --oneline | head -3 > /tmp/o",
	rm_push: "rm -rf x && git push",
	semi: "a; b",
	or: "a || b",
	redir: "cmd 2>&1 >> /tmp/l < in.txt",
	env: "env A=b cmd",
	bashc: "bash -c 'x; y'",
	subst_assign: "cd /abs && x=$(git rev-parse HEAD) && echo $x",
	subst_arg: "echo $(date +%s)",
	backtick: "echo `whoami`",
	nested3: "echo $(echo $(echo $(echo $(echo deep))))",
	for_loop: "for f in a b; do rm $f; done",
	for_subst: "for f in $(ls); do echo $f; done",
	while_loop: "while read l; do echo $l; done < list.txt",
	if_else: "if test -f a; then rm a; else touch a; fi",
	subshell: "(cd /tmp && ls)",
	brace: "{ echo a; echo b; } > /tmp/o",
	heredoc_py: "python3 - <<'EOF'\nimport os\nos.remove('x')\nprint(1)\nprint(2)\nprint(3)\nEOF",
	heredoc_cat: "cat > f <<EOF\nhello\nworld\nEOF",
	heredoc_sh: "bash <<'EOF'\nrm -rf /tmp/x\ncurl http://a\nEOF",
	herestring: "grep x <<< 'abc'",
	find_exec: "find . -name x -exec rm {} \\;",
	xargs_a: "xargs -a list git worktree remove",
	xargs_pipe: "git ls-files | xargs rm",
	time_nohup: "time nohup sleep 1 &",
	sudo: "sudo apt install x",
	quoted_sep: "echo 'a; b && c' \"d | e\"",
	// 原文に倒れる形
	procsub: "diff <(ls a) <(ls b)",
	funcdef: "f() { echo hi; }; f",
	case_esac: "case $x in a) echo a;; esac",
	eval_: "eval \"$cmd\"",
	arith: "(( x = 1 ))",
	// 異常な入力
	empty: "",
	open_quote: "echo 'abc",
	ctl: "echo a\u001b[31mb\u202ec",
	multiline: "echo a\necho b",
	quoted_nl: 'echo "a\nb\rc"; rm x',
	simple: "ls -la",
	long: "echo " + "x".repeat(5000),
	many: Array.from({ length: 30 }, (_, i) => `echo ${i}`).join(" && "),
	deep_for: "for a in 1; do for b in 2; do for c in 3; do for d in 4; do rm x; done; done; done; done",
	// 日本語を含む原文 (Offset は UTF-8 のバイト位置。切り出しがずれないこと)
	jp_and: "echo 日本語 && ls",
	jp_grep: "grep 'こんにちは' f | head",
	jp_heredoc: "python3 - <<'EOF'\nprint('日本語')\nimport os\nos.remove('あ')\nEOF",
	jp_subst: "echo 日本語 $(echo 漢字 | wc -c) && echo 終",
	jp_bashc: "bash -c 'echo 日; ls'",
	jp_emoji: "echo 😀 && rm 𠮷野家",
};

const out = { cases: {}, hit: {}, view: {}, ratio: {} };
for (const [k, c] of Object.entries(CASES)) out.cases[k] = { cmd: c, ...E(c) };
out.hit.push = E("cd /x && git push origin main", ["git push"]);
out.hit.none = E("cd /x && git push origin main");
out.hit.sub = E("echo $(git push)", ["git push"]);
out.misc = { nul: E(null), undef: E(undefined), num: E(5) };

// 表示側
out.view.lines_simple = view.explainSection("ls -la");
out.view.lines_pipe = view.explainSection("cd /x && git log | head -3");
out.view.lines_bad = view.explainSection("diff <(ls a) <(ls b)");
out.view.lines_hit = view.explainSection("git status && git push", ["git push"]);
const TEN = "echo 1 && echo 2 && echo 3 && echo 4 && git push && echo 6 && echo 7 && echo 8 && echo 9 && echo 10";
out.view.fold_hit = view.explainSection(TEN, ["git push"]);
out.view.fold_nohit = view.explainSection(TEN);
out.view.fold_marks = view.explainSection(
	"echo 1 && git push && echo 3 && echo 4 && echo 5 && echo 6 && echo 7 && echo 8 && git status",
	["git status"],
);
out.view.fold_few = view.explainSection("echo 1 && echo 2 && git push && echo 4", ["git push"]);
out.view.must_simple = view.buildMustConfirmView("git push", "公開", () => ({ ok: false, why: "x" }), undefined, { explain: true });
out.view.must_multi = view.buildMustConfirmView("cd /x && git push", "公開", () => ({ ok: false, why: "x" }), undefined, { explain: true });
out.view.must_noexplain = view.buildMustConfirmView("cd /x && git push", "公開", () => ({ ok: false, why: "x" }));
out.view.must_nonbash = view.buildMustConfirmView("cd /x && git push", "公開", () => ({ ok: false, why: "x" }), undefined, { explain: false });

// 代表 30 件 (実際の使われ方に近い形)。原文に倒れる割合の指標
const REP = [
	"git status",
	"cd /home/u/repo && git log --oneline | head -5",
	"git diff HEAD~1 | grep -n foo",
	"cd /abs && uv run pytest test/x.py -q 2>&1 | tail -20",
	"ls -la /tmp && cat /tmp/a.txt",
	"rm -rf .tmp/x && mkdir -p .tmp/x",
	"git add -A && git commit -m 'feat: x'",
	"for f in a.txt b.txt; do echo $f; done",
	"for f in $(git ls-files '*.sh'); do shellcheck $f; done",
	"x=$(git rev-parse HEAD) && echo $x",
	"cd /abs && echo \"$(pwd)\" > /tmp/o",
	"python3 - <<'EOF'\nimport json\nprint(json.dumps({}))\nEOF",
	"cat > /tmp/f.md <<'EOF'\n# title\nbody\nEOF",
	"find . -name '*.pyc' -exec rm {} \\;",
	"find . -name '*.log' | xargs rm -f",
	"git ls-files | xargs -n1 wc -l",
	"bash -c 'cd /x; make'",
	"env FOO=1 node script.js",
	"if [ -f x ]; then cat x; fi",
	"while read l; do echo $l; done < list.txt",
	"(cd /x && make) 2>&1 | tail",
	"{ echo a; echo b; } > /tmp/o",
	"curl -s https://example.com/x.json | python3 -m json.tool",
	"gh pr list --json number | head",
	"git push origin feature/x && echo done",
	"sleep 5; echo `date`",
	"timeout 60 mise run verify > /tmp/log 2>&1",
	"cd /abs && git worktree remove foo || true",
	"diff <(sort a) <(sort b)",
	"case $1 in a) echo a;; *) echo b;; esac",
];
const fallbackCount = REP.filter((c) => !E(c).complete).length;
out.ratio = { total: REP.length, fallback: fallbackCount, list: REP.filter((c) => !E(c).complete) };
console.log(JSON.stringify(out));
