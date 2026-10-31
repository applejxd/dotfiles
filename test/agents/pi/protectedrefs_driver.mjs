// judge/protectedrefs.ts の試験用の実行器。引数の JSON `{fn, ref, patterns}` を読み、真偽を JSON で出す。
//
//   node test/agents/pi/protectedrefs_driver.mjs '{"fn":"protected","ref":"develop","patterns":["develop"]}'
//
// see docs/change/0053-worktree-integration-gate.md
import { dirname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "..", "..", "..");
const P = await import(
	pathToFileURL(resolve(ROOT, "home", "dot_config", "pi", "harness", "judge", "protectedrefs.ts")).href
);

const args = JSON.parse(process.argv[2] ?? "{}");
const result =
	args.fn === "feature" ? P.isFeatureSourceRef(args.ref) : P.isProtectedRef(args.ref, args.patterns ?? []);
process.stdout.write(JSON.stringify(result));
