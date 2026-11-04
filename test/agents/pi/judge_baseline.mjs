// 判定器 (TS 版) の出力を凍結した baseline と、現行の出力の突き合わせ。
//
//   node test/agents/pi/judge_baseline.mjs --write-baseline   # golden/ts_baseline.jsonl を書き出す (意図した変更のあと)
//   node test/agents/pi/judge_baseline.mjs --check            # 現行と baseline が 1 行も違わないこと
//
// 固定の golden (Python 由来) とは別に、現行の TS 判定器の出力そのものを凍結する (自己参照を避けるため golden は上書きしない)。
// 対象: (a) decide_golden.jsonl の全入力 (b) checks_golden.jsonl の検査 id 単位の出力 (c) 役割 × モードの真理値表。
// 差の分類と意図した差の台帳は judge_diff.mjs。台帳つきの判定は judge_diff.mjs を使う。
// see docs/spec/guard/pi-decide.md#判定の退行検知baseline-と意図した差の台帳
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
export const ROOT = resolve(HERE, "..", "..", "..");
export const GOLDEN = resolve(ROOT, "test", "agents", "golden");
export const BASELINE = resolve(GOLDEN, "ts_baseline.jsonl");
export const LEDGER = resolve(GOLDEN, "intended_changes.jsonl");
const HOME = homedir();
const JUDGE = resolve(ROOT, "home", "dot_config", "pi", "harness", "judge");

const load = (name) => import(pathToFileURL(resolve(JUDGE, name)).href);
const { decide, setBashDecider } = await load("decide.ts");
const { makeBashDecider } = await load("bash.ts");
const { newCtx } = await load("context.ts");
const shared = await load("shared.ts");
const { CHECKS } = await load("checks.ts");
const tables = JSON.parse(readFileSync(resolve(GOLDEN, "tables.json"), "utf8"));
setBashDecider(makeBashDecider(tables));
export const common = JSON.parse(readFileSync(resolve(GOLDEN, "common.json"), "utf8"));

const mapStrings = (v, f) =>
	typeof v === "string"
		? f(v)
		: Array.isArray(v)
			? v.map((x) => mapStrings(x, f))
			: v && typeof v === "object"
				? Object.fromEntries(Object.entries(v).map(([k, x]) => [k, mapStrings(x, f)]))
				: v;
const expand = (v) => mapStrings(v, (s) => s.replaceAll("${ROOT}", ROOT).replaceAll("${HOME}", HOME));
const tokenize = (v) => mapStrings(v, (s) => s.replaceAll(ROOT, "${ROOT}").replaceAll(HOME, "${HOME}"));
const stable = (v) =>
	JSON.stringify(v, (_k, x) =>
		x && typeof x === "object" && !Array.isArray(x)
			? Object.fromEntries(Object.entries(x).sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0)))
			: x,
	);

/** 強さ: deny(3) > mustConfirm(2) > ask(1) > allow(0)。check は結果なし(0)・あり(2)。 */
export const strength = (row) => {
	if (row.kind === "check") return row.result === null ? 0 : 2;
	if (row.decision === "deny") return 3;
	if (row.decision === "ask") return row.mustConfirm ? 2 : 1;
	return 0;
};
export const rowKey = (row) => JSON.stringify([row.kind, row.id ?? "", row.role ?? "", row.mode ?? "", row.input]);

const modeOf = (bypass, boundary) => {
	const b = bypass === true ? "bypass" : bypass === undefined || bypass === false ? "ask" : `bypass=${JSON.stringify(bypass)}`;
	return boundary === true ? (b === "ask" ? "boundary" : `${b}+boundary`) : b;
};

const EXTRA_OK = new Set(["tool", "input", "role", "bypass", "boundary", "cwd"]);
/** 要求を baseline の (入力・役割・モード) へ。ふつうの bash は入力をコマンド文字列にする。 */
export const describe = (request) => {
	if (!request || typeof request !== "object" || Array.isArray(request)) {
		return { role: "", mode: "ask", input: `req:${stable(request)}` };
	}
	const { role, bypass, boundary, ...rest } = request;
	const plain =
		request.tool === "bash" &&
		request.cwd === "${ROOT}" &&
		typeof request.input?.command === "string" &&
		Object.keys(request.input).length === 1 &&
		Object.keys(request).every((k) => EXTRA_OK.has(k));
	return {
		role: typeof role === "string" ? role : `role=${JSON.stringify(role ?? null)}`,
		mode: modeOf(bypass, boundary),
		input: plain ? request.input.command : `req:${stable(rest)}`,
	};
};

export const judgeRow = (kind, request) => {
	const d = describe(request);
	const res = tokenize(decide(expand(request), common));
	const row = { kind, input: d.input, role: d.role, mode: d.mode, decision: res.decision, reason: res.reason, source: res.source };
	if (res.mustConfirm === true) row.mustConfirm = true;
	return row;
};

// --- (c) 真理値表 ---------------------------------------------------------------------------------------------------------
export const MODES = [{}, { bypass: true }, { boundary: true }, { bypass: true, boundary: true }];
export const TRUTH = [
	// ① 複合の厳格さ
	"git clean -fd && gh api -X POST repos/o/r/issues -f title=x",
	"git status && git branch -D x",
	"FOO=1 git clean -fd",
	"cd sub && git tag -d v1",
	// ② 許可 + 未知
	"git log; unknown_command_xyz",
	"git status && unknown_command_xyz",
	"git log | unknown_command_xyz",
	// ③ 引数が起こす書き込み
	"git log --output=x.txt",
	"git diff --output=x",
	"git log --exec-path=/tmp",
	// ④ 明示 ask と default ask の混在
	"git push",
	"git push && unknown_command_xyz",
	"git status; git push origin main",
	"gh pr create --title t --body b && unknown_command_xyz",
	"unknown_command_xyz && git commit -m x",
	"git commit -m x; git reset",
	"chezmoi apply --dry-run; git log",
	// ⑤ local_git
	"git branch -D x",
	"git tag -d v1",
	"git clean -fd",
	"git branch -fd x",
	"git checkout -B x",
	"git switch --force-create x",
	"git -C repo branch -D x",
	"git branch --list",
	"git clean -n",
	// ⑥ 例外 (deny_except) と、その厳密一致から外れる形
	"git worktree remove .tmp/worktrees/x",
	"git restore --staged a.txt",
	"git worktree remove -f .tmp/worktrees/x",
	"git worktree remove ../x",
	"git worktree remove /tmp/x",
	"git worktree remove .tmp/worktrees/x && git status",
	"sudo git worktree remove .tmp/worktrees/x",
	"ssh h git worktree remove x",
	"git restore --staged -- a.txt",
	"git restore --staged a.txt && git status",
	"git restore a.txt",
	"git restore --worktree --staged a.txt",
	// ⑦ ラッパー・入れ子
	"env git push",
	"bash -c 'git push'",
	"sudo git push",
	"ssh h 'git push'",
	"echo x | xargs git push",
	"find . -exec git push ;",
	"find . -name x -exec rm {} +",
	"xargs -I{} git branch -D {}",
	// ⑧ 非 literal
	"git $x",
	"$(echo git) push",
	"`echo git` push",
	"g=git; $g push",
	// ⑨ 引用・heredoc 内の語
	'echo "git push"',
	"cat <<EOF\ngit push\nEOF",
	'git commit -m "git push を直した"',
	"echo 'git branch -D x'",
	// ⑩ 書き込み先 (bash の書き込み範囲は対象外という現状の凍結)
	"echo x > ../other",
	"echo x | tee ../other",
	"cat > f <<EOF\nx\nEOF",
	"echo x > /tmp/y",
	"echo x >> ~/.bashrc",
];

export const truthRequests = () => {
	const roles = Object.keys(common.pi.profiles).sort();
	const out = [];
	for (const command of TRUTH) {
		for (const role of roles) {
			for (const flags of MODES) out.push({ tool: "bash", input: { command }, cwd: "${ROOT}", role, ...flags });
		}
	}
	return out;
};

// --- 全体の組み立て -------------------------------------------------------------------------------------------------------
const readLines = (name) => readFileSync(resolve(GOLDEN, name), "utf8").split("\n").filter(Boolean).map((l) => JSON.parse(l));

const attempt = (fn) => {
	try {
		return fn();
	} catch {
		return { error: "*" };
	}
};

const checkRows = () => {
	const rows = [];
	let ctx = null;
	for (const e of readLines("checks_golden.jsonl")) {
		if (e.fn === "heredoc") {
			ctx = newCtx(tables, common, ROOT);
			shared.splitHeredocBody(ctx, e.arg);
		} else if (e.fn === "check") {
			const check = CHECKS.get(e.name.split("@")[0]);
			if (!check) continue;
			const result = tokenize(attempt(() => check(ctx, e.arg) ?? null));
			rows.push({ kind: "check", id: e.name, input: e.arg, result });
		}
	}
	return rows;
};

/** 現行の判定器の出力から、baseline と同じ形の行 (決定的な順序・重複なし) を作る。 */
export const currentRows = () => {
	const rows = [];
	const seen = new Set();
	const add = (row) => {
		const k = rowKey(row);
		if (seen.has(k)) return;
		seen.add(k);
		rows.push(row);
	};
	for (const { request } of readLines("decide_golden.jsonl")) add(judgeRow("decide", request));
	for (const request of truthRequests()) add(judgeRow("truth", request));
	for (const row of checkRows()) add(row);
	return rows;
};

export const readBaseline = (path = BASELINE) =>
	new Map(
		readFileSync(path, "utf8")
			.split("\n")
			.filter(Boolean)
			.map((l) => {
				const row = JSON.parse(l);
				return [rowKey(row), row];
			}),
	);

export const serialize = (rows) => rows.map((r) => JSON.stringify(r)).join("\n") + "\n";

const isMain = process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href;
if (isMain) {
	const args = process.argv.slice(2);
	const rows = currentRows();
	const count = (kind) => rows.filter((r) => r.kind === kind).length;
	const summary = `decide ${count("decide")} / truth ${count("truth")} / check ${count("check")} (計 ${rows.length} 行)`;
	if (args.includes("--write-baseline")) {
		const text = serialize(rows);
		writeFileSync(BASELINE, text);
		console.log(`baseline を書き出した: ${summary}, ${Buffer.byteLength(text)} バイト`);
	} else if (args.includes("--check")) {
		if (!existsSync(BASELINE)) {
			console.log("baseline が無い (--write-baseline で作る)");
			process.exit(1);
		}
		const base = readBaseline();
		const cur = new Map(rows.map((r) => [rowKey(r), r]));
		let diff = 0;
		for (const [k, r] of cur) if (!base.has(k) || stable(base.get(k)) !== stable(r)) diff++;
		for (const k of base.keys()) if (!cur.has(k)) diff++;
		console.log(diff === 0 ? `baseline と一致: ${summary}` : `baseline と ${diff} 行が違う (分類は judge_diff.mjs)`);
		process.exit(diff === 0 ? 0 : 1);
	} else {
		console.log("使い方: --write-baseline | --check");
		process.exit(2);
	}
}
