// tools-ext.ts の表試験 (tail・読みの失敗のヒント・説明・誘導 deny の言い換え)。結果を JSON で標準出力へ出す
// (照合は test_pi_tools_ext.py)。
//
//   node test/agents/pi/tools_ext_driver.mjs
//
// see docs/spec/guard/pi-guard.md
import { mkdirSync, mkdtempSync, truncateSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { basename, dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "..", "..", "..");
const mod = await import(pathToFileURL(resolve(ROOT, "home", "dot_config", "pi", "harness", "tools-ext.ts")).href);
const { toolText, guideHint, runRead, similarNames } = mod;

const dir = mkdtempSync(join(tmpdir(), "tools-ext-"));
const files = {
	"a.txt": "1\n2\n3\n",
	"b.txt": "1\n2\n3",
	"empty.txt": "",
	"Readme.md": "x\n",
	"secret.env": "x\n",
	"other.txt": "x\n",
};
for (const [name, body] of Object.entries(files)) writeFileSync(join(dir, name), body);
writeFileSync(join(dir, "big.bin"), "");
truncateSync(join(dir, "big.bin"), 33 * 1024 * 1024);
mkdirSync(join(dir, "sub"));

const ctx = { cwd: dir };
const hooks = { cwd: dir, canRead: (p) => !basename(p).startsWith("secret") };

// 組み込みの read の代わり。受けた引数を記録し、決めた結果か例外を返す
async function run(params, behavior = {}) {
	const seen = [];
	const def = {
		execute: async (_id, p) => {
			seen.push(p);
			if (behavior.throws) throw behavior.throws;
			return { content: behavior.content ?? [{ type: "text", text: "ok" }] };
		},
	};
	try {
		await runRead(def, "id", params, undefined, undefined, ctx, hooks);
		return { passed: seen[0] };
	} catch (e) {
		return { error: e.message, passed: seen[0] ?? null };
	}
}

const tail = {
	lf: await run({ path: "a.txt", tail: 2 }),
	no_lf: await run({ path: "b.txt", tail: 2 }),
	more_than_total: await run({ path: "a.txt", tail: 10 }),
	empty: await run({ path: "empty.txt", tail: 3 }),
	absolute: await run({ path: join(dir, "a.txt"), tail: 1 }),
	with_offset: await run({ path: "a.txt", tail: 2, offset: 1 }),
	zero: await run({ path: "a.txt", tail: 0 }),
	fractional: await run({ path: "a.txt", tail: 1.5 }),
	too_big: await run({ path: "big.bin", tail: 5 }),
	image: await run({ path: "a.txt", tail: 2 }, { content: [{ type: "text", text: "Read image file" }, { type: "image", data: "", mimeType: "image/png" }] }),
	missing: await run({ path: "nope.txt", tail: 2 }),
	directory: await run({ path: "sub", tail: 2 }),
	plain: await run({ path: "a.txt", offset: 2, limit: 1 }),
};

const enoent = Object.assign(new Error("ENOENT: no such file or directory"), { code: "ENOENT" });
const hints = {
	offset: await run({ path: "a.txt", offset: 99 }, { throws: new Error("Offset 99 is beyond end of file (4 lines total)") }),
	other_error: await run({ path: "a.txt" }, { throws: new Error("boom") }),
	similar_case: await run({ path: "README.md" }, { throws: enoent }),
	// 読めない名前 (判定器が deny する) は提案しない
	similar_denied: await run({ path: "Secret.env" }, { throws: enoent }),
	no_similar: await run({ path: "zzzzzzzz.txt" }, { throws: enoent }),
	names: similarNames(["README.md", "readme.txt", "READ", "Makefile", "REDME.md", "a.py", "A.py", "xx.py"], "readme.md"),
};

const texts = {};
for (const tool of ["bash", "read", "write", "edit", "grep", "find", "ls", "nothing"]) {
	texts[tool] = toolText(tool, "guarded_", { description: "BUILTIN", promptGuidelines: ["builtin guideline"] });
}

const G = (c) => guideHint(c, "guarded_");
const hint = {
	sed_range: G("sed -n '10,20p' src/a.py"),
	sed_one: G("sed -n '7p' a.py"),
	head_n: G("head -n 5 f.txt"),
	head_dash: G("head -3 f.txt"),
	head_default: G("head f.txt"),
	tail_n: G("tail -n 20 log.txt"),
	tail_dash: G("tail -5 log.txt"),
	tail_plus: G("tail -n +30 log.txt"),
	cat: G("cat FILE.md"),
	cat_two: G("cat a.txt b.txt"),
	cat_heredoc: G("cat > out.txt <<'EOF'\nhello\nEOF"),
	cat_append: G("cat >> out.txt <<EOF\nx\nEOF"),
	tee: G("tee o.txt <<EOF\nx\nEOF"),
	tee_append: G("tee -a o.txt <<EOF\nx\nEOF"),
	python: G("python3 - <<'PY'\nprint(1)\nPY"),
	compound: G("cd /repo && head -n 3 a.py && git status"),
	after_heredoc: G("cat > f <<EOF\nx\nEOF\npython3 run.py"),
	two_reads: G("head -n 3 a.py && tail -n 3 a.py"),
	pipe: G("cat a.txt | head -n 3"),
	redirect: G("cat a b > c"),
	variable: G("sed -n '1,5p' $F"),
	glob: G("cat *.md"),
	plain: G("echo hi"),
	bare_cat: G("cat"),
	head_c: G("head -c 10 f"),
	unknown_heredoc: G("kubectl apply -f - <<EOF\nx\nEOF"),
	unbalanced: G("cat 'a"),
};

process.stdout.write(JSON.stringify({ tail, hints, texts, hint }));
