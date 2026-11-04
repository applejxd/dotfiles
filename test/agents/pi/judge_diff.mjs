// 判定器の現行の出力と baseline の差を、強さで分類し、意図した差の台帳に無いものがあれば終了コード 1 にする。
//
//   node test/agents/pi/judge_diff.mjs                          # 現行 vs golden/ts_baseline.jsonl (台帳は golden/intended_changes.jsonl)
//   node test/agents/pi/judge_diff.mjs --baseline B --ledger L  # 場所を変える (試験用)
//   node test/agents/pi/judge_diff.mjs --emit-ledger            # 台帳に無い差を台帳の雛形 (JSONL) で出す
//   node test/agents/pi/judge_diff.mjs --corpus corpus.json     # 外部のコーパス (JSON の文字列配列) を役割 × モードで回し、baseline に無い入力の分布だけを出す
//
// 強さ: deny(3) > mustConfirm(2) > ask(1) > allow(0)。強さが下がる差が relax、上がる差が tighten、
// 同じ強さで理由・source だけ違う差が reason。台帳の class は relax / tighten / false-positive / neutral。
// 台帳の 1 行: {kind, input, role, mode, old, new, class, reason, approver}。old / new は label() の文字列 (差の表示に出る)。
// コーパスの中身 (コマンド文字列) は出力しない (私物の恐れ)。
// see docs/spec/guard/pi-decide.md#判定の退行検知baseline-と意図した差の台帳
import { createHash } from "node:crypto";
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { BASELINE, LEDGER, MODES, currentRows, judgeRow, readBaseline, rowKey, common, strength } from "./judge_baseline.mjs";

export const CLASSES = ["relax", "tighten", "false-positive", "neutral"];
const sha8 = (s) => createHash("sha1").update(s).digest("hex").slice(0, 8);

/** 差の表示と台帳の old / new に使う、行の短い表記。 */
export const label = (row) => {
	if (row === null) return "none";
	if (row.kind === "check") return `${row.result === null ? "null" : "hit"}/${sha8(JSON.stringify(row.result))}`;
	const d = row.decision === "ask" && row.mustConfirm ? "mustConfirm" : row.decision;
	return `${d}/${row.source}/${sha8(row.reason)}`;
};

const sameRow = (a, b) => JSON.stringify(a) === JSON.stringify(b);

/** baseline (Map) と現行の行から、差の一覧を作る。 */
export const diffRows = (base, rows) => {
	const diffs = [];
	const seen = new Set();
	for (const cur of rows) {
		const k = rowKey(cur);
		seen.add(k);
		const old = base.get(k) ?? null;
		if (old !== null && sameRow(old, cur)) continue;
		// baseline に無い行 (新しい入力) は、強さが 0 でないものを tighten 相当ではなく「新規」として分類する
		let cls = "reason";
		if (old === null) cls = "new";
		else if (strength(cur) < strength(old)) cls = "relax";
		else if (strength(cur) > strength(old)) cls = "tighten";
		diffs.push({ cls, old, cur });
	}
	for (const [k, old] of base) if (!seen.has(k)) diffs.push({ cls: "gone", old, cur: null });
	return diffs;
};

const ident = (row) => ({ kind: row.kind, input: row.input, role: row.role ?? "", mode: row.mode ?? "", id: row.id ?? "" });
const ledgerKey = (e) => JSON.stringify([e.kind, e.id ?? "", e.role ?? "", e.mode ?? "", e.input, e.old, e.new]);

export const readLedger = (path = LEDGER) =>
	existsSync(path)
		? readFileSync(path, "utf8")
				.split("\n")
				.filter(Boolean)
				.map((l) => JSON.parse(l))
		: [];

/** 台帳に載っていない差と、差の出ていない台帳の行 (古い台帳) を返す。 */
export const applyLedger = (diffs, ledger) => {
	const index = new Map(ledger.map((e) => [ledgerKey(e), e]));
	const used = new Set();
	const unlisted = [];
	for (const d of diffs) {
		const row = d.cur ?? d.old;
		const id = ident(row);
		const k = ledgerKey({ ...id, old: label(d.old), new: label(d.cur) });
		if (index.has(k)) {
			used.add(k);
			// 実際に強さが下がる差 (relax) は、台帳の class の自己申告 (neutral・false-positive など) に依らず、承認者と理由が要る
			const e = index.get(k);
			const filled = (v) => typeof v === "string" && v.trim() !== "";
			if (d.cls === "relax" && !(filled(e.approver) && filled(e.reason))) {
				unlisted.push({ ...d, rejected: "緩和 (relax) には台帳の承認者と理由が要る" });
			}
		} else unlisted.push(d);
	}
	return { unlisted, stale: ledger.filter((e) => !used.has(ledgerKey(e))) };
};

const describeDiff = (d) => {
	const row = d.cur ?? d.old;
	return JSON.stringify({
		class: d.cls,
		...(d.rejected ? { rejected: d.rejected } : {}),
		kind: row.kind,
		id: row.id,
		role: row.role,
		mode: row.mode,
		input: row.input.length > 200 ? `${row.input.slice(0, 200)}…` : row.input,
		old: label(d.old),
		new: label(d.cur),
		oldReason: d.old?.reason ?? (d.old ? JSON.stringify(d.old.result) : undefined),
		newReason: d.cur?.reason ?? (d.cur ? JSON.stringify(d.cur.result) : undefined),
	});
};

const corpusReport = (path) => {
	const items = JSON.parse(readFileSync(path, "utf8"));
	if (!Array.isArray(items)) throw new Error("コーパスは JSON の配列にする");
	const base = readBaseline(resolve(BASELINE));
	const roles = Object.keys(common.pi.profiles).sort();
	const counts = {};
	let fresh = 0;
	const commands = items.filter((c) => typeof c === "string");
	for (const command of commands) {
		let isNew = false;
		for (const role of roles) {
			for (const flags of MODES) {
				const row = judgeRow("corpus", { tool: "bash", input: { command }, cwd: "${ROOT}", role, ...flags });
				if (base.has(rowKey({ ...row, kind: "decide" })) || base.has(rowKey({ ...row, kind: "truth" }))) continue;
				isNew = true;
				const key = `${row.role}/${row.mode}/${label(row).split("/")[0]}`;
				counts[key] = (counts[key] ?? 0) + 1;
			}
		}
		if (isNew) fresh++;
	}
	console.log(`コーパス: ${items.length} 件 (文字列 ${commands.length})、baseline に無い入力 ${fresh} 件`);
	for (const [k, v] of Object.entries(counts).sort()) console.log(`  ${k.padEnd(48)} ${v}`);
};

const isMain = process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href;
if (isMain) {
	const args = process.argv.slice(2);
	const opt = (name, dflt) => (args.includes(name) ? resolve(args[args.indexOf(name) + 1]) : dflt);
	if (args.includes("--corpus")) {
		corpusReport(opt("--corpus"));
		process.exit(0);
	}
	const base = readBaseline(opt("--baseline", BASELINE));
	const diffs = diffRows(base, currentRows());
	const { unlisted, stale } = applyLedger(diffs, readLedger(opt("--ledger", LEDGER)));
	if (args.includes("--emit-ledger")) {
		// 台帳の雛形 (reason と approver は人が埋める。埋めずに載せない)
		for (const d of unlisted) {
			const row = d.cur ?? d.old;
			const cls = d.cls === "relax" || d.cls === "tighten" ? d.cls : "neutral";
			const e = { ...ident(row), old: label(d.old), new: label(d.cur), class: cls, reason: "", approver: "" };
			const { id, ...rest } = e;
			console.log(JSON.stringify(row.kind === "check" ? e : rest));
		}
		process.exit(0);
	}
	const tally = {};
	for (const d of unlisted) tally[d.cls] = (tally[d.cls] ?? 0) + 1;
	console.log(`差 ${diffs.length} 件 (台帳に無い ${unlisted.length} 件: ${JSON.stringify(tally)})`);
	for (const d of unlisted.slice(0, 20)) console.log(describeDiff(d));
	if (unlisted.length > 20) console.log(`… ほか ${unlisted.length - 20} 件`);
	for (const e of stale.slice(0, 20)) console.warn(`警告: 古い台帳の行 (差が出ていない): ${JSON.stringify([e.kind, e.role, e.mode, e.old, e.new])}`);
	process.exit(unlisted.length ? 1 : 0);
}
