// pi-permission-system (package) の判定エンジンを直接呼び、(コマンド → 判定) の表を照合するための駆動。
// 引数は JSON ファイルのパス 1 つ。中身: { pkg, jiti, aliasRoot, policy, project?, bash: [cmd...], surface: [[surface, value]...] }
//   pkg        @gotgenes/pi-permission-system のディレクトリ
//   jiti       jiti のディレクトリ (拡張の TypeScript を読む)
//   aliasRoot  @earendil-works/* を含む node_modules (pi 本体の install)
//   policy     config.json の中身 (permission / commandEffects / shellTools)。yoloMode は常に false で評価する
//   project    作業ツリーの .pi/extensions/pi-permission-system/config.json の中身 (任意)
// 標準出力へ JSON: { bash: [{state, pattern}...], surface: [{action, pattern}...] }
// bash は、実際のゲートと同じく複合コマンドを分解し、ラッパーの床 (opaque / indirection / unparsed) も含めて判定する。
// path / external_directory のゲート (bash のトークンの投影) は含めない。surface の照合は規則の評価だけ。
// see docs/spec/agent-config-generation.md#permission-system-の設定stock
import { createRequire } from "node:module";
import { mkdirSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const input = JSON.parse(readFileSync(process.argv[2], "utf-8"));
const require = createRequire(join(input.pkg, "package.json"));
const { createJiti } = require(input.jiti);
const alias = {};
for (const n of ["pi-coding-agent", "pi-tui", "pi-ai", "pi-agent-core"]) alias[`@earendil-works/${n}`] = join(input.aliasRoot, "@earendil-works", n);
const jiti = createJiti(`${input.pkg}/`, { interopDefault: true, alias });
const load = (p) => jiti.import(join(input.pkg, p));

const { PermissionManager } = await load("src/policy/permission-manager.ts");
const { PermissionResolver } = await load("src/policy/permission-resolver.ts");
const { PathNormalizer } = await load("src/path/path-normalizer.ts");
const { BashProgram } = await load("src/access-intent/bash/program.ts");
const { warmBashParser } = await load("src/access-intent/bash/parser.ts");
const { resolveBashAdvisoryCheck } = await load("src/service/bash-advisory-check.ts");
const { evaluate } = await load("src/policy/rule.ts");
const { posixPathFlavor } = await load("src/path/path-flavor.ts");

const agentDir = mkdtempSync(join(tmpdir(), "perm-agent-"));
mkdirSync(join(agentDir, "extensions/pi-permission-system"), { recursive: true });
writeFileSync(join(agentDir, "extensions/pi-permission-system/config.json"), JSON.stringify({ ...input.policy, yoloMode: false }));
const cwd = mkdtempSync(join(tmpdir(), "perm-proj-"));
if (input.project) {
  mkdirSync(join(cwd, ".pi/extensions/pi-permission-system"), { recursive: true });
  writeFileSync(join(cwd, ".pi/extensions/pi-permission-system/config.json"), JSON.stringify(input.project));
}
const manager = new PermissionManager({ agentDir, isYoloEnabled: () => false, flavor: posixPathFlavor });
manager.configureForCwd(cwd);
const resolver = new PermissionResolver(manager, { getRuleset: () => [] });
const normalizer = new PathNormalizer(posixPathFlavor, cwd);
await warmBashParser();
if (!BashProgram.parseSync("true", normalizer)) {
  console.error("bash のパーサーが温まらない");
  process.exit(2);
}

const rules = manager.getComposedConfigRules();
const out = { bash: [], surface: [] };
for (const cmd of input.bash ?? []) {
  const r = resolveBashAdvisoryCheck(cmd, undefined, resolver, normalizer);
  out.bash.push({ state: r.state, pattern: r.matchedPattern ?? null });
}
for (const [surface, value] of input.surface ?? []) {
  const r = evaluate(surface, value, rules, posixPathFlavor);
  out.surface.push({ action: r.action, pattern: r.pattern });
}
console.log(JSON.stringify(out));
