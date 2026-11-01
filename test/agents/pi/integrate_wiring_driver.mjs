// pending-adapters.ts (integrateWiring・integrateCfg・authorizeRecord・登録表) の試験用の実行器。標準入力の JSON を読み、結果を JSON で出す。
//   {op:"wiring", rules}                  配線の形 (enabled・specs の ID・登録された操作・exclusive・runsHere)
//   {op:"cfg", rules}                     cfg の中身 (target・protectedRefs・riskPaths)
//   {op:"capture", rules, cwd, values}    capture を呼び、rules の integrate.enabled を false にして、もう一度呼ぶ
//   {op:"authorize", rec, ctx}            authorizeRecord (ctx.specs が "integrate" なら GIT_INTEGRATE_SPEC を入れる)
//   {op:"registries"}                     PENDING_ADAPTERS・APPROVAL_ADAPTERS のキー
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "..", "..", "..");
const harness = (name) => pathToFileURL(resolve(ROOT, "home", "dot_config", "pi", "harness", name)).href;
const pa = await import(harness("pending-adapters.ts"));
const ia = await import(harness("integrate-action.ts"));

const ENV = { ...process.env, GIT_AUTHOR_NAME: "t", GIT_AUTHOR_EMAIL: "t@example.test", GIT_COMMITTER_NAME: "t", GIT_COMMITTER_EMAIL: "t@example.test" };
const req = JSON.parse(readFileSync(0, "utf8"));
const out = {};

if (req.op === "wiring") {
	const w = pa.integrateWiring(req.rules);
	const ap = w.approval.git_integrate;
	out.enabled = w.enabled;
	out.specs = w.specs.map((s) => s.id);
	out.request = Object.keys(w.request);
	out.approval = Object.keys(w.approval);
	out.exclusive = ap ? ap.exclusive : null;
	out.runsHere = ap ? typeof ap.runsHere : null;
} else if (req.op === "cfg") {
	out.cfg = pa.integrateCfg(req.rules);
} else if (req.op === "capture") {
	const w = pa.integrateWiring(req.rules);
	const call = () => w.request.git_integrate.capture({ cwd: req.cwd, values: req.values, env: ENV });
	out.before = await call();
	req.rules.judge.common.pi.integrate.enabled = false;
	out.afterIntegrateOff = await call();
	req.rules.judge.common.pi.integrate.enabled = true;
	out.restored = await call();
	req.rules.judge.common.pi.pending.enabled = false;
	out.afterPendingOff = await call();
} else if (req.op === "authorize") {
	const specs = req.ctx.specs === "integrate" ? [ia.GIT_INTEGRATE_SPEC] : [];
	out.result = pa.authorizeRecord(req.rec, { ...req.ctx, specs });
} else if (req.op === "registries") {
	out.pending = Object.keys(pa.PENDING_ADAPTERS);
	out.approval = Object.keys(pa.APPROVAL_ADAPTERS);
}
process.stdout.write(JSON.stringify(out));
