// tools-ext.ts の表試験 (tail・読みの失敗のヒント・説明・誘導 deny の言い換え)。結果を JSON で標準出力へ出す
// (照合は test_pi_tools_ext.py)。
//
//   node test/agents/pi/tools_ext_driver.mjs
//
// see docs/spec/guard/pi-guard.md
import { mkdirSync, mkdtempSync, rmSync, truncateSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { basename, dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "..", "..", "..");
const mod = await import(pathToFileURL(resolve(ROOT, "home", "dot_config", "pi", "harness", "tools-ext.ts")).href);
const { toolText, guideHint, runRead, similarNames, editFailureHint, nearestMatch, decorateEditResult } = mod;

const dir = mkdtempSync(join(tmpdir(), "tools-ext-"));
// 終わりに必ず消す (33 MB の big.bin を含む。消さないと実行のたびに TMPDIR に残る。CHG-0042 段 4)
process.on("exit", () => rmSync(dir, { recursive: true, force: true }));
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

// ─── edit の失敗のヒント ───
const NF = "Could not find the exact text in a.txt. The old text must match exactly including all whitespace and newlines.";
const NF_N = (i) => `Could not find edits[${i}] in a.txt. The oldText must match exactly including all whitespace and newlines.`;
const MULTI = "Found 3 occurrences of the text in a.txt. The text must be unique. Please provide more context to make it unique.";
const NOCHG = "No changes made to a.txt. The replacement produced identical content. This might indicate an issue with special characters or the text not existing as expected.";
const one = (oldText, newText = "x") => ({ path: "a.txt", edits: [{ oldText, newText }] });
const FILE = "alpha\n  beta()\ngamma\ndelta\n";
const eh = (msg, input, text) => editFailureHint(msg, input, text);
const bigLines = Array.from({ length: 9 }, (_, i) => `row ${i}\ndup`).join("\n");
const editHints = {
	ws_only: eh(NF, one("alpha\nbeta()\ngamma"), FILE),
	tab_crlf: eh(NF, one("alpha\r\n\tbeta()\r\ngamma"), FILE),
	one_line: eh(NF, one("alpha\n  beta(1)\ngamma"), FILE),
	none: eh(NF, one("zzz\nyyy"), FILE),
	indexed: eh(NF_N(1), { path: "a.txt", edits: [{ oldText: "zzz", newText: "" }, { oldText: "gamma\ndelta2", newText: "" }] }, FILE),
	long_line: eh(NF, one("alpha\n" + "q".repeat(300)), "alpha\n" + "p".repeat(300)),
	control: eh(NF, one("alpha\nbe\u0001ta"), FILE),
	no_text: eh(NF, one("alpha"), null),
	applied: eh(NOCHG, one("zzz", "gamma\ndelta"), FILE),
	not_applied: eh(NOCHG, one("zzz", "nowhere"), FILE),
	nochange_no_text: eh(NOCHG, one("a", "b"), null),
	multi: eh(MULTI, one("dup"), "head\ndup\nmid\ndup\nx\ndup\n"),
	multi_first_line: eh(MULTI, one("dup"), "dup\nx\ndup\n"),
	multi_many: eh("Found 9 occurrences of edits[0] in a.txt. Each oldText must be unique. Please provide more context to make it unique.", one("dup"), bigLines),
	invalid: eh('Invalid arguments for tool "guarded_edit": Expected \':\' after property name', {}, null),
	overlap: eh("edits[0] and edits[1] overlap in a.txt. Merge them into one edit or target disjoint regions.", one("a"), null),
	guard_deny: eh("実行前の判定で止めた: deny: x", one("a"), FILE),
	erofs: eh("EROFS: read-only file system, open 'a.txt'", one("a"), FILE),
	enoent: eh("ENOENT: no such file or directory, access 'a.txt'", one("a"), null),
};
const nearest = {
	ws: nearestMatch(FILE, "alpha\nbeta()"),
	none: nearestMatch(FILE, "zzz"),
	blank: nearestMatch(FILE, "\n\n"),
};

// 読み込みの層 (decorateEditResult)
writeFileSync(join(dir, "e.txt"), FILE);
writeFileSync(join(dir, "bin.txt"), "a\u0000b\nalpha\n");
writeFileSync(join(dir, "huge.txt"), "alpha\n".repeat(100 * 1024));
const ev = (path, text, input, isError = true) => ({ isError, input: input ?? { path, edits: [{ oldText: "alpha\nbeta(1)", newText: "" }] }, content: [{ type: "text", text }] });
const canRead = (p) => !basename(p).startsWith("secret");
const NFE = NF.replace("a.txt", "e.txt");
const deco = {
	ok: await decorateEditResult(ev("e.txt", NFE), dir, canRead),
	absolute: await decorateEditResult(ev(join(dir, "e.txt"), NFE), "/nonexistent", canRead),
	success: (await decorateEditResult(ev("e.txt", "Successfully replaced", undefined, false), dir, canRead)) ?? null,
	success_text_looks_like_error: (await decorateEditResult(ev("e.txt", NFE, undefined, false), dir, canRead)) ?? null,
	missing: (await decorateEditResult(ev("nope.txt", NFE), dir, canRead)) ?? null,
	binary: (await decorateEditResult(ev("bin.txt", NFE), dir, canRead)) ?? null,
	huge: (await decorateEditResult(ev("huge.txt", NFE), dir, canRead)) ?? null,
	unreadable: (await decorateEditResult(ev("secret.env", NFE), dir, canRead)) ?? null,
	deny: (await decorateEditResult(ev("e.txt", "実行前の判定で止めた: deny: x"), dir, canRead)) ?? null,
	invalid_without_file: await decorateEditResult(ev("", 'Invalid arguments for tool "guarded_edit": bad', {}), dir, canRead),
	no_content: (await decorateEditResult({ isError: true, input: {} }, dir, canRead)) ?? null,
};

process.stdout.write(JSON.stringify({ tail, hints, texts, hint, editHints, nearest, deco }));
