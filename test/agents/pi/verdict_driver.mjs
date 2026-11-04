// 段の表 (judge/verdict.ts) の試験用の実行器。stdout に JSON を出す。
//
//   node verdict_driver.mjs abstract            # 所見の部分集合 × 役割 × モードで、段の表と旧のカスケードの仕様の評価器を突き合わせる
//   node verdict_driver.mjs judge <jsonfile>    # [{F, covered, coveredReason?, role, bypass?, boundary?}] を judgeBash に通す
//   node verdict_driver.mjs real <jsonfile>     # [コマンド] を全役割 × 全モードで、新の判定器と旧のカスケード (legacy_cascade.ts) に通す
//
// `abstract` の仕様の評価器は、legacy_cascade.ts の構造 (先に当たった段が決める) を所見の集合の関数として別に書いたもので、
// verdict.ts の OUT を呼ばない (出力の文も独立に組み立てる)。
// see docs/spec/guard/pi-decide.md#bash-の評価順段の表
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "..", "..", "..");
const GOLDEN = resolve(ROOT, "test", "agents", "golden");
const JUDGE = resolve(ROOT, "home", "dot_config", "pi", "harness", "judge");
const load = (name) => import(pathToFileURL(resolve(JUDGE, name)).href);

const { decide, setBashDecider } = await load("decide.ts");
const { makeBashDecider } = await load("bash.ts");
const { makeLegacyBashDecider } = await load("legacy_cascade.ts");
const { judgeBash } = await load("verdict.ts");
const tables = JSON.parse(readFileSync(resolve(GOLDEN, "tables.json"), "utf8"));
const common = JSON.parse(readFileSync(resolve(GOLDEN, "common.json"), "utf8"));
const profiles = common.pi.profiles;
const ROLES = Object.keys(profiles).sort();
const MODES = [{}, { bypass: true }, { boundary: true }, { bypass: true, boundary: true }];
const modeName = (m) => (m.bypass ? (m.boundary ? "bypass+boundary" : "bypass") : m.boundary ? "boundary" : "ask");

const stable = (v) =>
	JSON.stringify(v, (_k, x) =>
		x && typeof x === "object" && !Array.isArray(x) ? Object.fromEntries(Object.entries(x).sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))) : x,
	);

// ─── 仕様の評価器 (旧のカスケードの構造を、所見の集合の関数として書き写したもの) ───────────────────────────────
const MUST_LOCAL = "確認が必要な元に戻せない git 操作 (bypass でも確認する): ";
const pyq = (s) => (s.includes("'") && !s.includes('"') ? `"${s}"` : `'${s}'`);

/** present: 所見のある段の集合。blind: S6 が blind か。cov: S10 */
function spec(present, blind, cov, role, mode) {
	const prof = profiles[role];
	const deny = prof.default === "deny";
	let commonDeny = null;
	let roleRule = null;
	if (present.has("S0")) commonDeny = { decision: "deny", reason: "r0", source: "error" };
	else if (present.has("S2")) commonDeny = { decision: "deny", reason: "r2", source: "check", check: "check_x" };
	else if (present.has("S3")) roleRule = { decision: "deny", reason: "r3", source: "rule", guide: "g1" };
	else if (present.has("S4")) roleRule = { decision: "deny", reason: "r4", source: "rule" };
	else if (present.has("S5")) roleRule = { decision: "deny", reason: "r5", source: "rule" };
	else if (present.has("S6")) {
		roleRule = blind
			? { decision: "deny", reason: "blind6", source: "rule" }
			: { decision: "ask", reason: "ask6", source: "rule", mustConfirm: true };
	} else if (present.has("S7")) {
		roleRule = deny
			? { decision: "deny", reason: "raw7。この役割は shell で元に戻せない操作をしない", source: "rule" }
			: { decision: "ask", reason: `${MUST_LOCAL}raw7\n実行しようとしているコマンド: cmd7`, source: "rule", mustConfirm: true };
	} else if (present.has("S8")) {
		roleRule = { decision: "ask", reason: "pfx: r8", source: "check", check: "c8", mustConfirm: true };
	} else if (present.has("S9")) {
		roleRule = deny
			? { decision: "deny", reason: "r9\nこの役割は既定が deny なので、承認で通さない (bypass でも通さない)", source: "check", check: "c9" }
			: { decision: "ask", reason: "r9", source: "check", check: "c9" };
	} else if (cov) roleRule = { decision: "allow", reason: "cov", source: "rule" };
	if (commonDeny) return commonDeny;
	if (!prof.tools.includes("bash")) return { decision: "deny", reason: `役割 ${pyq(role)} は bash を使えない`, source: "rule" };
	const result = roleRule ?? { decision: prof.default, reason: `どの規則にも当たらない (役割 ${pyq(role)} の既定)`, source: "default" };
	if (mode.boundary && result.source === "default" && result.decision === "ask") {
		return { decision: "allow", reason: "サンドボックスの内側の日常の shell (どの規則にも当たらない)", source: "rule", sandboxed: true };
	}
	if (mode.bypass && result.decision === "ask" && !result.mustConfirm) return { ...result, decision: "allow", bypassed: true };
	return result;
}

const FINDINGS = {
	S0: { stage: "S0", idx: 0, reason: "r0", source: "error" },
	S2: { stage: "S2", idx: 3, reason: "r2", source: "check", check: "check_x" },
	S3: { stage: "S3", idx: 0, reason: "r3", source: "rule", guide: "g1" },
	S4: { stage: "S4", idx: 0, reason: "r4", source: "rule" },
	S5: { stage: "S5", idx: 0, reason: "r5", source: "rule" },
	S6: { stage: "S6", idx: 0, reason: "ask6", source: "rule" },
	S6b: { stage: "S6", idx: 0, reason: "blind6", source: "rule", blind: true },
	S7: { stage: "S7", idx: 0, reason: "raw7", source: "rule", detail: "cmd7" },
	S8: { stage: "S8", idx: 0, reason: "pfx: r8", source: "check", check: "c8" },
	S9: { stage: "S9", idx: 0, reason: "r9", source: "check", check: "c9" },
};
const SUBSET_STAGES = ["S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9"];

function abstract() {
	let total = 0;
	const mismatches = [];
	for (let bits = 0; bits < 1 << SUBSET_STAGES.length; bits++) {
		const present = new Set(SUBSET_STAGES.filter((_s, i) => bits & (1 << i)));
		const hasS6 = present.has("S6");
		for (const blind of hasS6 ? [false, true] : [false]) {
			const F = [...present].map((s) => FINDINGS[s === "S6" && blind ? "S6b" : s]);
			for (const cov of [false, true]) {
				for (const role of ROLES) {
					for (const mode of MODES) {
						total++;
						const got = judgeBash({ F, covered: cov, coveredReason: "cov" }, { role, profile: profiles[role], ...mode });
						const want = spec(present, blind, cov, role, mode);
						if (stable(got) !== stable(want) && mismatches.length < 20) {
							mismatches.push({ stages: [...present], blind, cov, role, mode: modeName(mode), got, want });
						}
					}
				}
			}
		}
	}
	return { total, mismatches };
}

// ─── judge: 任意の所見を通す ─────────────────────────────────────────────────────────────
function judge(items) {
	return items.map((it) =>
		judgeBash(
			{ F: it.F, covered: it.covered ?? false, coveredReason: it.coveredReason },
			{ role: it.role, profile: profiles[it.role], bypass: it.bypass, boundary: it.boundary },
		),
	);
}

// ─── real: 新の判定器と旧のカスケードを、実コマンドで比べる ──────────────────────────────────
function real(commands) {
	const fresh = makeBashDecider(tables);
	const legacy = makeLegacyBashDecider(tables);
	const rows = [];
	for (const command of commands) {
		for (const role of ROLES) {
			for (const mode of MODES) {
				const req = { tool: "bash", input: { command }, cwd: ROOT, role, ...mode };
				setBashDecider(fresh);
				const now = decide(req, common);
				setBashDecider(legacy);
				const old = decide(req, common);
				rows.push({ command, role, mode: modeName(mode), now, old });
			}
		}
	}
	return rows;
}

const [kind, file] = process.argv.slice(2);
const readJson = () => JSON.parse(readFileSync(file, "utf8"));
if (kind === "abstract") console.log(JSON.stringify(abstract()));
else if (kind === "judge") console.log(JSON.stringify(judge(readJson())));
else if (kind === "real") console.log(JSON.stringify(real(readJson())));
else {
	console.log("使い方: abstract | judge <json> | real <json>");
	process.exit(2);
}
