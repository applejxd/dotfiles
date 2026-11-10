// 確認画面の本文 (work/goal-run.ts の approveBody) と pendingApproval (work/goal.ts) の単体試験用 driver。照合は test_work_approve_body.py。
//
//   echo '{"mode":"direct","goal":"...","total":N,"titles":[...],"ids":[...]}' | node ... 本文 (body) を JSON 1 行で出す
//   echo '{"mode":"ledger","goal":"...","titles":[...]}' | node ...   台帳へ reducer 直通で task を足し、pendingApproval → approveBody の結果を出す
// work ツールを通らない経路なので、題が拒否されて試験が空振りすることはない。see docs/spec/work/goal-run.md
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const WORK = join(resolve(HERE, "..", "..", ".."), "home", "dot_config", "pi", "harness", "work");
const load = (f) => import(pathToFileURL(join(WORK, f)).href);
const [gr, goal, rt, ev] = await Promise.all(["goal-run.ts", "goal.ts", "runtime.ts", "events.ts"].map(load));

const input = JSON.parse(readFileSync(0, "utf-8"));
let out;
if (input.mode === "direct") {
	out = { body: gr.approveBody(input.goal, input.total === undefined ? undefined : { total: input.total, titles: input.titles, ids: input.ids }) };
} else {
	const dir = mkdtempSync(join(tmpdir(), "approve-body-"));
	const H = "holder-A";
	const runtime = rt.createRuntime({ cwd: dir, sessionId: "s", holder: H, pid: process.pid, root: join(dir, ".tmp", "work"), timers: { setInterval: () => 0, clearInterval: () => {} }, env: {} });
	await runtime.start();
	const E = (type, node, data, source = "system") => ev.makeEvent(type, node, data, source, { holder: H });
	const evs = [E("goal.created", "G", { title: input.goal, budget: { usd: 100, tokens: 1e7, ms: 1e10 } }), E("plan.proposed", "G", { hash: "h1" }, "model"), E("plan.approved", "G", { hash: "h1" }, "user")];
	const rs = await runtime.submit(evs);
	const adds = [];
	for (const [i, t] of input.titles.entries()) {
		const r = await runtime.submit([E("node.added", `t${i}`, { node: { kind: "task", parent: "G", title: t, writes: [], after: [], attrs: {} } }, "model")]);
		adds.push(r.ok);
	}
	const p = goal.pendingApproval(runtime.state());
	out = { setup: rs.ok, adds, pending: { total: p.total, titles: p.titles, ids: p.ids }, body: gr.approveBody(input.goal, p) };
	await runtime.close().catch(() => {});
	rmSync(dir, { recursive: true, force: true });
}
process.stdout.write(`${JSON.stringify(out)}\n`);
process.exit(0);
