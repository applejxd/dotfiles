// pending-owner.ts を実プロセスで動かし、結果を JSON で標準出力へ出す (照合は test_pi_pending_owner.py)。
//
//   node test/agents/pi/pending_owner_driver.mjs
//
// see docs/change/0055-async-approval.md
import { spawn } from "node:child_process";
import { dirname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "..", "..", "..");
const { currentOwner, ownerState, readProcessStart, parseLinuxStat } = await import(pathToFileURL(resolve(ROOT, "home", "dot_config", "pi", "harness", "pending-owner.ts")).href);

const out = {};
const me = currentOwner("s", "e");
out.self = { owner: me, state: ownerState(me) };

const child = spawn("sleep", ["30"], { stdio: "ignore" });
await new Promise((res) => child.once("spawn", res));
const start = readProcessStart(child.pid);
const owner = { sessionId: "s", runtimeEpoch: "e", pid: child.pid, processStart: start.exists ? start.start : null, host: me.host };
out.child_alive = ownerState(owner);
out.child_start_changed = ownerState({ ...owner, processStart: "0" });
out.child_start_null = ownerState({ ...owner, processStart: null });
const exited = new Promise((res) => child.once("exit", res));
child.kill();
await exited;
out.child_gone = ownerState(owner);

out.other_host = ownerState({ ...me, host: "other-host.invalid" });
out.bad_pid = Object.fromEntries([0, -1, null, 1.5, 2 ** 31 + 1].map((p) => [String(p), ownerState({ ...me, pid: p === null ? Number.NaN : p }).state]));
out.win32 = ownerState(me, { platform: "win32" });
out.parse = {
	odd_name: parseLinuxStat("123 (a b) c) S 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 424242 23 24"),
	broken: parseLinuxStat("garbage"),
	short: parseLinuxStat("1 (x) S 1 2"),
};
console.log(JSON.stringify(out));
