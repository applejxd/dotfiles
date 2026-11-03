// 統合器の CLI。結果の JSON を 1 行で標準出力へ。終了コード: 成功 0・拒否 2・想定外の例外 1。
// 使い方: node apps/pr-viewer/merge-cli.ts plan|merge|recover <repo> [--source S] [--target T]
//   [--message-file F|-] [--cleanup C] [--expect-source OID] [--expect-target OID]
// メッセージはコマンドラインに載せず、ファイル（- なら標準入力）だけで受け取る。
import { readFileSync } from "node:fs";
import { executeMerge, planMerge, recoverMerge } from "./merge.ts";
import type { Cleanup, MergeInput } from "./merge.ts";

const FLAGS = new Set(["--source", "--target", "--message-file", "--cleanup", "--expect-source", "--expect-target"]);
const MAX_MESSAGE_FILE = 64 * 1024;

function emit(obj: unknown, code: number): void {
	process.stdout.write(`${JSON.stringify(obj)}\n`);
	process.exitCode = code;
}

function bad(): void {
	emit({ ok: false, code: "bad_input", reason: "入力が正しくありません。" }, 2);
}

function readMessage(path: string): string | null {
	try {
		const buf = readFileSync(path === "-" ? 0 : path);
		if (buf.length > MAX_MESSAGE_FILE) return null;
		return buf.toString("utf8");
	} catch {
		return null;
	}
}

async function main(argv: string[]): Promise<void> {
	const [cmd, repo, ...rest] = argv;
	if (!["plan", "merge", "recover"].includes(cmd ?? "") || !repo || repo.startsWith("-")) return bad();
	const flags = new Map<string, string>();
	for (let i = 0; i < rest.length; i += 2) {
		const k = rest[i];
		const v = rest[i + 1];
		if (!FLAGS.has(k) || v === undefined || flags.has(k)) return bad();
		flags.set(k, v);
	}
	if (cmd === "recover") {
		if (flags.size > 0) return bad();
		const r = await recoverMerge(repo);
		return emit(r, r.ok ? 0 : 2);
	}
	let message = "";
	const file = flags.get("--message-file");
	if (file !== undefined) {
		const m = readMessage(file);
		if (m === null) return bad();
		message = m;
	} else if (cmd === "merge") {
		return bad();
	} else {
		message = "plan"; // plan はメッセージを使わない（検査を通すための仮の値）
	}
	const source = flags.get("--source");
	if (source === undefined) return bad();
	const input: MergeInput = {
		repo,
		source,
		message,
		...(flags.has("--target") ? { target: flags.get("--target") } : {}),
		...(flags.has("--cleanup") ? { cleanup: flags.get("--cleanup") as Cleanup } : {}),
		expect: { sourceOid: flags.get("--expect-source"), targetOid: flags.get("--expect-target") },
	};
	const r = cmd === "plan" ? await planMerge(input) : await executeMerge(input);
	emit(r, r.ok ? 0 : 2);
}

main(process.argv.slice(2)).catch(() => {
	// 内部の例外の文面は出さない
	emit({ ok: false, code: "internal", reason: "想定外のエラーです。" }, 1);
});
