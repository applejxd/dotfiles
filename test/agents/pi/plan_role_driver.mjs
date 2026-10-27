// plan 役の部品の試験 (CHG-0044)。audit.ts の守る条件の検査と、model-choice.ts の 1 往復の上限 (model-choice.ts) を、JSON で標準出力へ出す。
//
//   node test/agents/pi/plan_role_driver.mjs
//
// see docs/change/0044-plan-agent.md
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "..", "..", "..");
const harness = (f) => pathToFileURL(join(ROOT, "home", "dot_config", "pi", "harness", f)).href;
const { requestedConditions, auditConditions } = await import(harness("audit.ts"));
const { roundTimeoutMs, DEFAULT_ROUND_MINUTES } = await import(harness("model-choice.ts"));

const task = ["目的: x", "", "# 守る条件", "- C1: 最新だけ", "- **C2**: 既定のまま", "* C3：確認画面なし", "C10: 十番目", "C1: 重複", "説明の C9: は行頭でない"].join("\n");
const out = {};
out.requested = requestedConditions(task);
out.none = auditConditions("条件の番号が無い依頼", "## 結論\nok");

const full = "## 結論\nok\n## 守る条件の突き合わせ\n- C1: 手順 1\n- C2: 手順 2\n- C3: 手順 3\n- C10: 手順 4\n## リスク\nC9 は別";
out.full = auditConditions(task, full);
out.partial = auditConditions(task, "## 結論\nok\n## 守る条件の突き合わせ\n- C1: 手順 1\n- C3: 手順 3\n## リスク\nC2 と C10 はここで触れるだけ");
out.noSection = auditConditions(task, "## 結論\nC1 C2 C3 C10 を満たす");
// C1 と C10 を取り違えない (前方一致で C10 を C1 とみなさない)
out.prefix = auditConditions("C1: a\nC10: b", "## 守る条件の突き合わせ\n- C10: ok");
// 番号つきの見出し (1. 2. …) の形の返答 (計画の標準形)
const numbered = "1. 結論\nok\n4. 守る条件の突き合わせ\n| C1 | 手順 1 |\n| C2 | 手順 2 |\n| C3 | 手順 3 |\n| C10 | 手順 4 |\n5. 根拠\nなし";
out.numbered = auditConditions(task, numbered);

const agents = { plan: { timeout_minutes: 30 }, explore: {}, odd: { timeout_minutes: "x" } };
const saved = process.env.PI_HARNESS_TEST_ROUND_MS;
delete process.env.PI_HARNESS_TEST_ROUND_MS;
out.timeouts = { plan: roundTimeoutMs(agents, "plan"), explore: roundTimeoutMs(agents, "explore"), odd: roundTimeoutMs(agents, "odd"), unknown: roundTimeoutMs(agents, "nope"), default_minutes: DEFAULT_ROUND_MINUTES };
process.env.PI_HARNESS_TEST_ROUND_MS = "1234";
out.test_override = roundTimeoutMs(agents, "plan");
if (saved === undefined) delete process.env.PI_HARNESS_TEST_ROUND_MS;
else process.env.PI_HARNESS_TEST_ROUND_MS = saved;
console.log(JSON.stringify(out));
