// gitstate.ts の試験用 driver (CHG-0049)。引数の JSON を受けて createProbe を動かし、結果を JSON で標準出力へ出す。
//
//   node test/agents/pi/gitstate_driver.mjs '{"ceiling":[...],"steps":[...]}'
//
// options: { ceiling, fake }   fake = "failed" (時間切れ相当) | "lines" (出力が想定外の行数)
// steps (順に実行し、結果を配列で返す。同じ probe を使う):
//   { fn: "owner", path }      -> probe.ownerOf(probe.realPath(path))
//   { fn: "model", path }      -> 上の owner の commonDir で probe.modelOf
//   { fn: "ready", path }      -> probe.actionReady(path)
//   { fn: "git", cwd, args }   -> 試験の途中で git を動かす (probe の外。キャッシュの確認用)
//   { fn: "newProbe" }         -> probe を作り直す
// see docs/spec/guard/pi-gitflow-guard.md
import { spawnSync } from "node:child_process";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "..", "..", "..");
const { createProbe } = await import(pathToFileURL(join(ROOT, "home", "dot_config", "pi", "harness", "gitstate.ts")).href);

const arg = JSON.parse(process.argv[2] ?? "{}");
const options = { ceiling: arg.ceiling ?? [] };
if (arg.fake === "failed") options.run = () => ({ ok: false, status: -1, out: "", failed: true });
if (arg.fake === "lines") options.run = () => ({ ok: true, status: 0, out: "a\nb\nc", failed: false });

let probe = createProbe(options);
const results = [];
for (const s of arg.steps ?? []) {
	if (s.fn === "owner") results.push(probe.ownerOf(probe.realPath(s.path)));
	else if (s.fn === "model") {
		const o = probe.ownerOf(probe.realPath(s.path));
		results.push(o.commonDir === undefined ? { noCommonDir: o.kind } : probe.modelOf(o.commonDir));
	} else if (s.fn === "ready") results.push(probe.actionReady(s.path));
	else if (s.fn === "git") {
		const r = spawnSync("git", s.args, { cwd: s.cwd, encoding: "utf8" });
		results.push({ status: r.status, out: r.stdout });
	} else if (s.fn === "newProbe") {
		probe = createProbe(options);
		results.push(null);
	} else throw new Error(`unknown step: ${s.fn}`);
}
console.log(JSON.stringify(results));
