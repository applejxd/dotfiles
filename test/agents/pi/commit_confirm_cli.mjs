// 試験用: commit-confirm の純関数を node で直接動かす。EXT に拡張のディレクトリを渡す。
//   analyze: 標準入力の JSON (コマンドの配列) → 解釈の結果の JSON
//   describe: 引数 1 = 作業ディレクトリ、標準入力 = コマンド → 確認の表示
//   pending: 引数 1 = 作業ディレクトリ、標準入力 = コマンド → 退避の結果の JSON
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

const ext = process.env.EXT;
const load = (name) => import(pathToFileURL(join(ext, name)).href);
const [mode, cwd] = process.argv.slice(2);
const input = readFileSync(0, "utf8");
const { analyze } = await load("parse.ts");

if (mode === "analyze") {
	const out = JSON.parse(input).map((command) => {
		const a = analyze(command);
		if (a.kind !== "commit" || !a.recognized) {
			return { kind: a.kind, recognized: a.kind === "commit" ? false : undefined, approx: a.approx };
		}
		return { kind: a.kind, recognized: true, steps: a.steps, dirs: a.dirs, spec: a.spec };
	});
	console.log(JSON.stringify(out));
} else {
	const a = analyze(input);
	if (a.kind !== "commit") {
		console.log(JSON.stringify({ kind: a.kind }));
	} else if (mode === "describe") {
		const { describeCommit, rawText } = await load("describe.ts");
		console.log(a.recognized ? (describeCommit(a, cwd) ?? "NULL") : rawText(input));
	} else if (mode === "pending") {
		const { pendingTarget, savePending } = await load("pending.ts");
		const t = pendingTarget(a);
		console.log(JSON.stringify(t ? { ...savePending(t.target, cwd), approx: t.approx } : { ok: false, reason: "unrecognized" }));
	}
}
