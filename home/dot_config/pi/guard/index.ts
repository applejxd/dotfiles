// 素の pi (ハーネス無し) 向けのガード。ツールの実行前に判定器へ通し、**deny だけ**を止める。
//   deny / 誘導 → 止める (理由はモデルへの案内になる)
//   ask         → 止めない (確認は出さない。Orca・Zed のように応える人が居ない環境でも止まらない)
// ハーネス (pis) の判定と同じ判定器・同じ規則 (rules.json の judge)。違いは ask を通す点と、役割を実装役に固定する点。
// 保護ではなくガードレール: tool_call だけで判定し (execute() の最終判定は無い)、拡張の読み込み時の処理や
// 利用者が手で打つ `!cmd` は囲えない。ハーネス (pis) は -ne で外れるので、二重にならない。
// see docs/spec/pi-harness.md#素の-pi-のガード
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { createCallDecider, type Decision } from "../harness/judge/call.ts";

const HERE = dirname(fileURLToPath(import.meta.url));
// 判定するのは、判定器が規則を持つ組み込みのツールと bg_run だけ。他の拡張・MCP のツールは対象外 (判定器は役割に無いものを deny する)
const JUDGED = new Set(["bash", "read", "edit", "write", "grep", "find", "ls", "bg_run", "bg_log", "bg_kill"]);
const ROLE = "implementer";

const baseName = (name: string): string => name.slice(name.lastIndexOf("/") + 1);

export default async function (pi: any) {
	let decide: ((tool: string, input: unknown, cwd: string) => Decision) | null = null;
	let loadError = "";
	try {
		const rules = JSON.parse(readFileSync(join(HERE, "..", "harness", "rules.json"), "utf-8"));
		if (!rules.judge?.common || !rules.judge?.tables) throw new Error("rules.json に judge が無い");
		// bypass: ask だけを allow にする (deny は効く)
		decide = createCallDecider({
			judge: rules.judge,
			profileTools: rules.profile_tools ?? {},
			role: ROLE,
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
		return undefined;
	});
}
