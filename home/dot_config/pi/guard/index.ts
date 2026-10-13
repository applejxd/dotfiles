// 素の pi (ハーネス無し) 向けのガード。ツールの実行前に判定器へ通し、**deny だけ**を止める。
//   deny / 誘導 → 止める (理由はモデルへの案内になる)
//   ask         → 止めない (確認は出さない。Orca・Zed のように応える人が居ない環境でも止まらない)
// ハーネス (pis) の判定と同じ判定器・同じ規則 (rules.json の judge)。違いは ask を通す点と、役割を実装役に固定する点。
// あわせて、ハーネスと同じ伏字化 (rules.json の redact) を tool_result で掛ける: bash などの結果の秘密を伏せる。
// 保護ではなくガードレール: tool_call だけで判定し (execute() の最終判定は無い)、拡張の読み込み時の処理や
// 利用者が手で打つ `!cmd` は囲えない。実行中の途中経過の表示は伏せられない。
// ハーネス (pis) は -ne で外れるので、二重にならない。
// see docs/spec/pi-harness.md#素の-pi-のガード
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { createCallDecider, type Decision } from "../harness/judge/call.ts";
import { createRedactor, type Redactor } from "../harness/redact.ts";

const HERE = dirname(fileURLToPath(import.meta.url));
// 判定するのは、判定器が規則を持つ組み込みのツールと bg_run だけ。他の拡張・MCP のツールは対象外 (判定器は役割に無いものを deny する)
const JUDGED = new Set(["bash", "read", "edit", "write", "grep", "find", "ls", "bg_run", "bg_log", "bg_kill"]);
// 出力を伏せない道具。read などを伏せると、伏せた本文を元に edit されてファイルへ伏字が書き込まれる
const FILE_TOOLS = new Set(["read", "edit", "write", "grep", "find", "ls"]);

const baseName = (name: string): string => name.slice(name.lastIndexOf("/") + 1);

export default async function (pi: any) {
	let decide: ((tool: string, input: unknown, cwd: string) => Decision) | null = null;
	let redactor: Redactor | null = null;
	let loadError = "";
	try {
		const rules = JSON.parse(readFileSync(join(HERE, "..", "harness", "rules.json"), "utf-8"));
		if (!rules.judge?.common || !rules.judge?.tables) throw new Error("rules.json に judge が無い");
		redactor = createRedactor(rules.redact);
		// 役割は [pi] default_role で固定 (実行時には切り替えない)。無い名前なら読み込みの失敗にする
		const role = rules.default_role;
		if (typeof role !== "string" || !Object.hasOwn(rules.profile_tools ?? {}, role)) {
			throw new Error(`rules.json の default_role が役割に無い: ${JSON.stringify(role)}`);
		}
		// bypass: ask だけを allow にする (deny は効く)
		decide = createCallDecider({
			judge: rules.judge,
			profileTools: rules.profile_tools ?? {},
			role,
			bypass: true,
			boundary: false,
		});
	} catch (e) {
		loadError = (e as Error).message;
		console.error(`[guard] 判定器を読み込めなかった: ${loadError}`);
	}

	pi.on("tool_call", (event: any, ctx: any) => {
		const tool = baseName(String(event.toolName));
		if (!JUDGED.has(tool)) return undefined;
		// 読めないまま素通しにしない (ガードが黙って消えるのを避ける)
		if (!decide) {
			return { block: true, reason: `ガードの設定を読めないため実行しない: ${loadError}` };
		}
		const d = decide(tool, event.input, ctx.cwd ?? process.cwd());
		if (d.decision === "deny") return { block: true, reason: d.reason };
		// 保護対象のパスを参照するコマンドは、どこが秘密か分からないので実行しない (ハーネスは出力を伏せるだけにする)
		const hit = tool === "bash" && redactor ? redactor.deniedPathIn(String(event.input?.command ?? "")) : null;
		if (hit) return { block: true, reason: redactor?.withheld(hit).structuredContent.withheld };
		return undefined;
	});

	// ツールの結果を伏せる。tool_result の例外は無視されて生の結果が残るので、ここでは投げずに結果ごと伏せる。
	// 伏字化の設定を読めないときも、結果を出さない (read などの道具は対象外)
	pi.on("tool_result", (event: any) => {
		const tool = baseName(String(event.toolName));
		if (FILE_TOOLS.has(tool)) return undefined;
		try {
			if (!redactor) throw new Error("伏字化の設定を読めない");
			// 出力が長いと pi は全文を一時ファイルへ退避し、モデルはそれを読める。そちらも伏せる
			const spill = event.details?.fullOutputPath;
			if (typeof spill === "string") writeFileSync(spill, redactor.redactText(readFileSync(spill, "utf-8")));
			return redactor.redactResult({
				content: event.content,
				details: event.details,
				structuredContent: event.structuredContent,
			});
		} catch (e) {
			const text = `[伏字化に失敗したので結果を伏せた: ${(e as Error).message}]`;
			return { content: [{ type: "text", text }], structuredContent: { withheld: text }, isError: true };
		}
	});
}
