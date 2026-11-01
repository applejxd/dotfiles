// integrate-action.ts の試験用の実行器。標準入力の JSON を読み、結果を JSON で標準出力へ出す。
//   {op:"capture", cwd, values, cfg}
//   {op:"flow", requestCwd, approverCwd, values, cfg, beforePlan?: string[][], beforeRecheck?: string[][], execute?: bool}
//       capture → (git を実行) → plan → (git を実行) → recheck → execute の順に、要求側の cwd と承認側の cwd を分けて動かす
//       saved?: [{values, finish?: bool}]  plan の前に、要求側の cwd で保留を保存する (finish: 承認済み (done) にする)
//   {op:"double", cwd, values, cfg}   保留を保存し、approvePending を 2 回並べて呼ぶ
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "..", "..", "..");
const harness = (name) => pathToFileURL(resolve(ROOT, "home", "dot_config", "pi", "harness", name)).href;
const ia = await import(harness("integrate-action.ts"));
const ops = await import(harness("pending-ops.ts"));
const ap = await import(harness("pending-approve.ts"));

const ENV = { ...process.env, GIT_AUTHOR_NAME: "t", GIT_AUTHOR_EMAIL: "t@example.test", GIT_COMMITTER_NAME: "t", GIT_COMMITTER_EMAIL: "t@example.test" };
const git = (cwd, args) => execFileSync("git", args, { cwd, env: ENV, encoding: "utf8" }).trim();
const req = JSON.parse(readFileSync(0, "utf8"));
const out = {};

if (req.op === "capture") {
	out.capture = await ia.integrateRequestAdapter(req.cfg).capture({ cwd: req.cwd, values: req.values, env: ENV });
	out.spec = ia.GIT_INTEGRATE_SPEC;
} else if (req.op === "flow") {
	const cap = await ia.integrateRequestAdapter(req.cfg).capture({ cwd: req.requestCwd, values: req.values, env: ENV });
	out.capture = cap;
	for (const s of req.saved ?? []) {
		const c = await ia.integrateRequestAdapter(req.cfg).capture({ cwd: req.requestCwd, values: s.values, env: ENV });
		if (!c.ok) throw new Error(`capture failed: ${c.reason}`);
		const sv = ops.saveOp(req.requestCwd, {
			action: "git_integrate",
			params: s.values,
			premise: c.premise,
			reason: "timeout",
			request: { id: "r-saved", sessionId: "s", cwd: req.requestCwd },
			createdAt: new Date().toISOString(),
			worktree: c.worktree,
		});
		if (!sv.ok) throw new Error(`save failed: ${sv.reason}`);
		(out.savedIds ??= []).push(sv.id);
		if (s.finish) {
			const owner = { sessionId: "s", runtimeEpoch: "e", pid: process.pid, processStart: "100", host: "h" };
			const b = ops.beginApproval(req.requestCwd, sv.id, sv.oid, owner);
			if (!b.ok) throw new Error(`begin failed: ${b.reason}`);
			const f = ops.finishApproval(req.requestCwd, sv.id, b.attemptOid, { outcome: "success", phase: "done", confirmedEffects: [], remainingCleanup: [], evidence: [] });
			if (!f.ok) throw new Error(`finish failed: ${f.reason}`);
		}
	}
	for (const a of req.beforePlan ?? []) git(req.requestCwd, a);
	const rec = { action: "git_integrate", params: req.values, premise: cap.premise ?? {}, request: { id: "x", sessionId: "s", cwd: req.requestCwd } };
	const ad = ia.integrateApprovalAdapter(req.cfg);
	const env = { cwd: req.approverCwd, env: ENV, rules: {} };
	const planned = await ad.plan(rec, env);
	out.plan = planned.ok ? { ok: true, summary: planned.summary, view: planned.view } : planned;
	if (planned.ok) {
		for (const a of req.beforeRecheck ?? []) git(req.requestCwd, a);
		out.recheck = await ad.recheck(planned.plan, env);
		if (req.execute && out.recheck.ok) {
			const x = await ad.execute(planned.plan, env);
			out.execOutcome = x;
			out.exec = x && typeof x === "object" && "body" in x ? x.body : x;
		}
	}
} else if (req.op === "adapter") {
	const ad = ia.integrateApprovalAdapter(req.cfg);
	out.exclusive = ad.exclusive;
	const plan = req.targetWorktree === null ? { targetWorktree: undefined } : { targetWorktree: req.targetWorktree };
	out.here = ad.runsHere ? ad.runsHere({ plan, cleanup: "none" }, { cwd: req.cwd, env: ENV, rules: {} }) : "missing";
} else if (req.op === "double") {
	const cap = await ia.integrateRequestAdapter(req.cfg).capture({ cwd: req.cwd, values: req.values, env: ENV });
	const saved = ops.saveOp(req.cwd, {
		action: "git_integrate",
		params: req.values,
		premise: cap.premise,
		reason: "timeout",
		request: { id: "r1", sessionId: "s-req", cwd: req.cwd },
		createdAt: new Date().toISOString(),
		worktree: cap.worktree,
	});
	if (!saved.ok) throw new Error(`save failed: ${saved.reason}`);
	const sent = [];
	const run = () =>
		ap.approvePending(
			saved.id,
			{ cwd: req.cwd, mode: "tui", hasUI: true, isIdle: () => true, ui: { select: async () => "承認して実行", editor: async () => undefined } },
			{
				adapters: { git_integrate: ia.integrateApprovalAdapter(req.cfg) },
				enabled: () => true,
				modes: ["tui"],
				rules: {},
				env: ENV,
				dialog: (fn) => fn(),
				bell: () => {},
				owner: () => ({ sessionId: "s-appr", runtimeEpoch: "e", pid: process.pid, processStart: "100", host: "h" }),
				notify: () => {},
				tellModel: (content, details) => sent.push(details),
				liveness: () => ({ state: "gone", reason: "止まっている" }),
			},
		);
	const rs = await Promise.all([run(), run()]);
	out.replies = rs.map((r) => ({ level: r.level, text: r.text }));
	out.sent = sent;
	out.commits = Number(git(req.cwd, ["rev-list", "--count", `${req.before}..develop`]));
}
process.stdout.write(JSON.stringify(out));
