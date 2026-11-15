"""pi-sandbox-toggle (囲いと YOLO を実行中に切り替える /sandbox) を、node で実際に動かして確かめる。

pi 本体の ``@earendil-works/pi-coding-agent`` は、最小の代役に差し替える (``createLocalBashOperations`` は、起動時の
``process.env.PIB_SANDBOX`` を見て、囲いの内側の印を返すかを決める。pi が起動のたびに環境変数を読む挙動の写し)。
実際の pi・bwrap・TUI は通らない (未検証。実機の確認は docs/spec/sandbox/pi-sandbox-runner.md#実行中の切り替え)。
node が無い・TypeScript の型の除去 (--experimental-strip-types) を使えない環境と、Linux 以外では skip する (skip は通過ではない)。
see docs/spec/sandbox/pi-sandbox-runner.md#実行中の切り替え
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "home" / "dot_pi" / "agent" / "local-packages" / "pi-sandbox-toggle"
SOURCE = PACKAGE / "src" / "index.ts"
# プロジェクトの設定の置き場 (permission-system が読む 2 か所)
CFG = ".pi/extensions/pi-permission-system/config.json"
LEGACY = ".pi/agent/pi-permissions.jsonc"
# 実際に配る方針 (permission)。YOLO を入れてよい設定の見本として使う
POLICY = json.loads((ROOT / "home" / ".chezmoitemplates" / "pi-permission-policy.json").read_text(encoding="utf-8"))["permission"]
# 拡張が、YOLO を入れる前に permission-system へ問い合わせる、囲いと権限の設定を守るパス (PROTECTED_PATHS)
PROTECTED = re.findall(
    r'"([^"]+)"', re.search(r"const PROTECTED_PATHS = \[(.*?)\];", SOURCE.read_text(encoding="utf-8"), re.S).group(1)
)

STUB = """
export const getAgentDir = () => process.env.PI_AGENT_DIR;
export const createLocalBashOperations = ({ shellPath } = {}) => ({
  exec: async (command, cwd, { onData, timeout }) => {
    const s = globalThis.__stub;
    const sandbox = process.env.PIB_SANDBOX ?? null;  // 起動した時点の値 (起動後に親が変えても、子の環境は変わらない)
    s.calls.push({ shellPath, command, cwd, timeout, sandbox });
    if (s.gate) await s.gate;
    const inside = s.inside && sandbox;
    onData(Buffer.from(`PIB-PROBE:${inside ? '/tmp/pib-mise-state' : ''}\\n`));
    return { exitCode: s.exit ?? 0 };
  },
});
"""

# どの場面も、この前置きの後ろに書く。pi の代役 (registerTool を持たない = 道具を登録すると落ちる) と、画面の記録を作る
PRELUDE = """
import fs from 'node:fs';
import path from 'node:path';
const mod = await import('./index.ts');
const agentDir = process.env.PI_AGENT_DIR;
const cfgPath = path.join(agentDir, 'extensions', 'pi-permission-system', 'config.json');
const pibShell = `${process.env.HOME}/.local/bin/pib-shell`;
const projectDir = path.join(path.dirname(agentDir), 'project');
const POLICY = __POLICY__;
const PROTECTED = __PROTECTED__;
const SERVICES_KEY = Symbol.for('@gotgenes/pi-permission-system:session-services');
function installService(kind, weak, fallback) {
  const map = new Map();
  globalThis[SERVICES_KEY] = map;
  const service = {
    calls: [],
    checkPermission(surface, value) {
      this.calls.push([surface, value]);
      if (kind === 'throws') throw new Error('x');
      const rel = value.replace(process.env.HOME, '~');
      if (fallback.includes(rel)) return { state: 'deny' };  // 規則が無く、既定の deny が答えた (matchedPattern が無い)
      return weak.includes(rel) ? { state: 'ask', matchedPattern: 'x/*' } : { state: 'deny', matchedPattern: 'x/*' };
    },
  };
  if (kind !== 'missing') map.set('sid', service);
  return { map, service };
}
function setup({ env = {}, config, settings, hasUI = true, confirm = true, inside = true, exit = 0, trusted = true,
                 project, service = 'ok', weak = [], fallback = [] } = {}) {
  const svc = installService(service, weak, fallback);
  for (const k of ['PIB_SANDBOX', 'PIB_ORIG_PATH']) delete process.env[k];
  Object.assign(process.env, env);
  fs.rmSync(path.join(agentDir, 'extensions'), { recursive: true, force: true });
  if (config !== undefined) {
    fs.mkdirSync(path.dirname(cfgPath), { recursive: true });
    fs.writeFileSync(cfgPath, typeof config === 'string' ? config : JSON.stringify(config));
  }
  fs.rmSync(projectDir, { recursive: true, force: true });
  fs.mkdirSync(projectDir, { recursive: true });
  for (const [rel, text] of Object.entries(project ?? {})) {
    fs.mkdirSync(path.dirname(path.join(projectDir, rel)), { recursive: true });
    fs.writeFileSync(path.join(projectDir, rel), text);
  }
  globalThis.__stub = { inside, exit, calls: [] };
  const commands = {}, handlers = {}, events = {}, notes = [], status = {}, order = [], confirms = [];
  const pi = {
    registerCommand: (n, d) => { commands[n] = d; },
    on: (n, h) => { handlers[n] = h; },
    events: { on: (n, h) => { events[n] = h; return () => { delete events[n]; }; } },
    getSettings: () => settings ?? { shellPath: pibShell },
  };
  const ctx = {
    hasUI, cwd: projectDir, isProjectTrusted: () => trusted, sessionManager: { getSessionId: () => 'sid' },
    ui: {
      notify: (m, l) => notes.push([l, m]),
      setStatus: (k, v) => { status[k] = v; },
      confirm: async (t, m) => { confirms.push([t, m]); return confirm; },
    },
    waitForIdle: async () => { order.push(`idle:${process.env.PIB_SANDBOX ?? ''}`); },
  };
  mod.default(pi);
  return { pi, ctx, commands, handlers, events, notes, status, order, confirms, svc };
}
const readCfg = () => (fs.existsSync(cfgPath) ? JSON.parse(fs.readFileSync(cfgPath, 'utf8')) : null);
const run = (t, args = '') => t.commands.sandbox.handler(args, t.ctx);
const tick = () => new Promise((r) => setTimeout(r, 30));
const cfgDir = path.dirname(cfgPath);
const tmpFiles = () => (fs.existsSync(cfgDir) ? fs.readdirSync(cfgDir).filter((f) => f.endsWith('.tmp')) : []);
const out = (o) => console.log(JSON.stringify(o));
"""


def run_node(tmp_path: Path, scenario: str, *, home: str | None = None):
    if not sys.platform.startswith("linux"):
        pytest.skip("Linux 専用 (囲い = bwrap)")
    node = shutil.which("node")
    if node is None:
        pytest.skip("node が無い")
    work = tmp_path / "work"
    pkg = work / "node_modules" / "@earendil-works" / "pi-coding-agent"
    pkg.mkdir(parents=True)
    (pkg / "package.json").write_text(
        json.dumps({"name": "@earendil-works/pi-coding-agent", "type": "module", "exports": "./index.js"}),
        encoding="utf-8",
    )
    (pkg / "index.js").write_text(STUB, encoding="utf-8")
    shutil.copy(SOURCE, work / "index.ts")
    (work / "package.json").write_text('{"type": "module"}', encoding="utf-8")
    prelude = PRELUDE.replace("__POLICY__", json.dumps(POLICY)).replace("__PROTECTED__", json.dumps(PROTECTED))
    (work / "main.mjs").write_text(prelude + scenario, encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if not k.startswith("NODE_") and k not in ("PIB_SANDBOX", "PIB_ORIG_PATH")}
    env["PI_AGENT_DIR"] = str(tmp_path / "agent")
    env["HOME"] = home if home is not None else str(tmp_path / "home")
    probe = subprocess.run(
        [node, "--experimental-strip-types", "--no-warnings", "-e", "0"],
        env=env, capture_output=True, text=True, encoding="utf-8", timeout=60,
    )
    if probe.returncode != 0:
        pytest.skip("この node は TypeScript の型の除去 (--experimental-strip-types) を使えない")
    proc = subprocess.run(
        [node, "--experimental-strip-types", "--no-warnings", "main.mjs"],
        cwd=work, env=env, capture_output=True, text=True, encoding="utf-8", timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_enable_from_a_plain_pi_sets_the_env_before_the_probe_and_turns_yolo_on(tmp_path):
    """素の pi から on。試し実行は、環境変数を書き換えた後に、pi の bash と同じ shellPath で走る。YOLO は他の項目を保って入る。"""
    got = run_node(tmp_path, """
const t = setup({ config: { debugLog: true, permission: POLICY } });
await run(t, 'on');
out({ env: process.env.PIB_SANDBOX, calls: globalThis.__stub.calls, cfg: readCfg(), status: t.status, notes: t.notes,
      tools: typeof t.pi.registerTool, cwd: projectDir, tmp: tmpFiles() });
""")
    assert got["env"] == "1"
    (call,) = got["calls"]
    assert call["sandbox"] == "1" and call["cwd"] == got["cwd"] and call["timeout"] == 15
    assert call["shellPath"].endswith("/.local/bin/pib-shell")
    assert got["cfg"] == {"debugLog": True, "permission": POLICY, "yoloMode": True}
    assert got["tmp"] == []  # 一時ファイルは残さない
    assert got["status"] == {"sandbox": "sandbox: on"}
    assert any("素の pi" in message for _, message in got["notes"])  # pib の起動時の検査を通っていない旨
    assert got["tools"] == "undefined"  # モデルが呼べる道具は登録しない


def test_enable_in_a_pib_session_does_not_warn_about_the_plain_pi(tmp_path):
    got = run_node(tmp_path, """
const t = setup({ env: { PIB_ORIG_PATH: '/usr/bin' } });
await run(t, 'on');
out({ notes: t.notes });
""")
    assert not any("素の pi" in message for _, message in got["notes"])


def test_yolo_never_creates_a_config_file_that_holds_only_yolo(tmp_path):
    """設定ファイルが無いとき、YOLO だけのファイルを作らない (囲いは入る)。方針の無いファイルを増やさない。"""
    got = run_node(tmp_path, """
const t = setup();
await run(t, 'on');
out({ env: process.env.PIB_SANDBOX, cfg: readCfg(), last: t.notes.at(-1) });
""")
    assert got["env"] == "1" and got["cfg"] is None
    assert got["last"][0] == "warning" and "YOLO を入れなかった" in got["last"][1]


def test_the_protected_paths_are_denied_by_the_repository_policy_table():
    """拡張が問い合わせるパスは、リポジトリの方針でも deny になっていなければならない (でないと、正規の設定でも YOLO が入らない)。
    判定表 (permission_cases.json) は、本物の判定エンジンで評価される (test_pi_permission_decisions.py)。"""
    # 囲いの起動・設定・切り替えの拡張 (本体と、pi.extensions の向き先)・権限の設定。減らすと、YOLO を入れる前提が弱くなる
    must = {
        "~/.local/bin/pi-sandbox-runner", "~/.local/bin/pib-shell", "~/.local/bin/pib",
        "~/.config/pi-sandbox/runner.toml", "~/.config/pi-sandbox/runner.local.toml",
        "~/.pi/agent/settings.json", "~/.pi/agent/local-packages/pi-sandbox-toggle/src/index.ts",
        "~/.pi/agent/local-packages/pi-sandbox-toggle/package.json", "~/.pi/agent/extensions/pi-permission-system/config.json",
    }
    assert must <= set(PROTECTED), must - set(PROTECTED)
    cases = json.loads((ROOT / "test" / "agents" / "pi_stock" / "permission_cases.json").read_text(encoding="utf-8"))
    denied = {c[1] for c in _all_cases(cases) if c[0] == "path_write" and c[2] == "deny"}
    for path in PROTECTED:
        assert path.replace("~", "$HOME", 1) in denied, path


def _all_cases(node):
    """判定表の中の、["面", "対象", "期待"] の形の行をすべて集める。"""
    found = []
    if isinstance(node, list):
        if len(node) == 3 and all(isinstance(x, str) for x in node):
            found.append(node)
        for item in node:
            found.extend(_all_cases(item))
    elif isinstance(node, dict):
        for value in node.values():
            found.extend(_all_cases(value))
    return found


def test_yolo_is_decided_by_asking_permission_system_about_every_protected_path(tmp_path):
    """規則の評価は再現しない。write・edit のゲートと同じ判定 (checkPermission の path_write) に、保護するパスを 1 つずつ問う。"""
    got = run_node(tmp_path, """
const t = setup({ config: { permission: POLICY } });
await run(t, 'on');
out({ calls: t.svc.service.calls, home: process.env.HOME, yolo: readCfg().yoloMode });
""")
    assert got["yolo"] is True
    assert got["calls"] == [["path_write", p.replace("~", got["home"], 1)] for p in PROTECTED]


@pytest.mark.parametrize(
    "weak", ["service-throws", "service-missing", *PROTECTED, *[f"fallback:{p}" for p in PROTECTED]]
)
def test_yolo_is_not_turned_on_unless_permission_system_confirms_the_protected_paths_are_denied(tmp_path, weak):
    """保護するパスの 1 つでも deny と確かめられなければ (ask・allow、判定 API が例外、まだ公開されていない)、YOLO を入れない。
    global・信頼済みプロジェクト・agent が重なった実効の方針を、permission-system 自身に確かめる。囲いは入る。
    前回の YOLO や手動の YOLO が残っていても、確かめられない保護のまま残さず、切る。"""
    if weak == "service-throws":
        options = "service: 'throws'"
    elif weak == "service-missing":
        options = "service: 'missing'"
    elif weak.startswith("fallback:"):
        # deny でも、明示の規則ではなく既定の deny が答えたもの (write・edit の path ゲートは、これを見て何もしない)
        options = f"fallback: [{json.dumps(weak.removeprefix('fallback:'))}]"
    else:
        options = f"weak: [{json.dumps(weak)}]"
    got = run_node(tmp_path, f"""
const t = setup({{ config: {{ permission: POLICY, yoloMode: true }}, {options} }});
await run(t, 'on');
const onYolo = readCfg().yoloMode;
const u = setup({{ env: {{ PIB_SANDBOX: '1' }}, config: {{ permission: POLICY, yoloMode: true }}, {options} }});
await u.handlers.session_start({{ reason: 'startup' }}, u.ctx);
out({{ env: process.env.PIB_SANDBOX, onYolo, startupYolo: readCfg().yoloMode, last: t.notes.at(-1) }});
""")
    assert got["env"] == "1" and got["onYolo"] is False and got["startupYolo"] is False
    assert got["last"][0] == "warning" and "YOLO を入れなかった" in got["last"][1]


def test_a_leftover_yolo_that_cannot_be_turned_off_is_reported(tmp_path):
    """保護を確かめられず、残っている YOLO も切れない (プロジェクトの設定が yoloMode を on にしている) ときは、そう知らせる。"""
    got = run_node(tmp_path, """
const t = setup({ config: { permission: POLICY, yoloMode: true }, weak: [PROTECTED[0]],
                  project: { '.pi/extensions/pi-permission-system/config.json': '{"yoloMode": true}' } });
await run(t, 'on');
out({ env: process.env.PIB_SANDBOX, last: t.notes.at(-1) });
""")
    assert got["env"] == "1"
    assert got["last"][0] == "warning" and "YOLO を入れなかった" in got["last"][1] and "残っている YOLO も切れなかった" in got["last"][1]


def test_startup_retries_when_permission_system_publishes_its_service_after_the_extension_started(tmp_path):
    """拡張の読み込み順で、起動時の同期が permission-system の公開より前になることがある。
    公開を知らせる permissions:ready で、もう一度確かめる (別のノードの通知では再試行しない)。公開待ちの間は、エラーを出さない。"""
    got = run_node(tmp_path, """
const t = setup({ env: { PIB_SANDBOX: '1' }, config: { permission: POLICY, yoloMode: true }, service: 'missing' });
await t.handlers.session_start({ reason: 'startup' }, t.ctx);
const waiting = { yolo: readCfg().yoloMode, errors: t.notes.filter(([l]) => l !== 'info').length };
t.svc.map.set('sid', t.svc.service);
t.events['permissions:ready']({ sessionId: 'other-node' });
await tick();
const other = readCfg().yoloMode;
t.events['permissions:ready']({ sessionId: 'sid' });
await tick();
out({ waiting, other, yolo: readCfg().yoloMode });
""")
    assert got["waiting"] == {"yolo": False, "errors": 0}  # 前回の YOLO が true でも、確かめられるまでは切っておく
    assert got["other"] is False  # 別のノードの通知では、再試行しない
    assert got["yolo"] is True  # 自分のノードの通知で、YOLO を入れる


def test_the_retry_is_dropped_when_the_session_ends_before_permission_system_publishes(tmp_path):
    """/new・/resume・/reload・終了で、拡張の世代は終わる。公開待ちの保留と購読を捨て、古い ctx を、あとで使わない。"""
    got = run_node(tmp_path, """
const t = setup({ env: { PIB_SANDBOX: '1' }, config: { permission: POLICY, yoloMode: false }, service: 'missing' });
await t.handlers.session_start({ reason: 'startup' }, t.ctx);
await t.handlers.session_shutdown({ reason: 'new' });
const subscribed = typeof t.events['permissions:ready'];
t.svc.map.set('sid', t.svc.service);
if (t.events['permissions:ready']) t.events['permissions:ready']({ sessionId: 'sid' });
await tick();
out({ subscribed, yolo: readCfg().yoloMode });
""")
    assert got == {"subscribed": "undefined", "yolo": False}


def test_a_retry_that_finds_the_context_unusable_does_not_crash_and_frees_the_lock(tmp_path):
    """再試行は、確認の最中に /new・/reload で、古い ctx (UI へのアクセスが例外になる) になりうる。
    未処理の例外 (node では、プロセスが落ちる) にせず、枠を解放する (次の /sandbox を受け付ける)。"""
    got = run_node(tmp_path, """
const t = setup({ env: { PIB_SANDBOX: '1' }, config: { permission: POLICY, yoloMode: false }, service: 'missing' });
await t.handlers.session_start({ reason: 'startup' }, t.ctx);
t.svc.map.set('sid', t.svc.service);
Object.defineProperty(t.ctx, 'hasUI', { get() { throw new Error('stale context'); } });
t.events['permissions:ready']({ sessionId: 'sid' });
await tick();
const fresh = setup({ env: { PIB_SANDBOX: '1' }, config: { permission: POLICY, yoloMode: false } });
await run(fresh, 'status');
out({ rejected: fresh.notes.filter(([, m]) => m.includes('実行中')).length, ran: fresh.notes.at(-1)[1].includes('確認した') });
""")
    assert got == {"rejected": 0, "ran": True}


def test_the_startup_check_waits_for_a_command_that_started_first_instead_of_being_skipped(tmp_path):
    """起動の途中に打たれた /sandbox が先に枠を取っていても、起動時の同期は捨てない。先行の on が失敗して囲いなしに戻ったとき、
    前回の YOLO が残ると、囲いなしの YOLO になる。"""
    got = run_node(tmp_path, """
const t = setup({ inside: false, config: { permission: POLICY, yoloMode: true } });
let open;
globalThis.__stub.gate = new Promise((r) => { open = r; });
const first = run(t, 'on');
await tick();
const startup = t.handlers.session_start({ reason: 'startup' }, t.ctx);
await tick();
const during = { yolo: readCfg().yoloMode, env: process.env.PIB_SANDBOX ?? null };
open();
await first;
await startup;
out({ during, env: process.env.PIB_SANDBOX ?? null, yolo: readCfg().yoloMode });
""")
    assert got["during"] == {"yolo": True, "env": "1"}  # 先行の on が試し実行を待つ間は、起動時の同期も待つ
    assert got["env"] is None and got["yolo"] is False  # on が失敗 → 囲いなし。起動時の同期が、前回の YOLO を切る


def test_the_stub_probe_keeps_the_environment_it_was_started_with(tmp_path):
    """本物は、子を起動した時点の環境のコピーを子へ渡す。代役もそれに合わせる (起動後に親が変えても、出力は変わらない)。"""
    got = run_node(tmp_path, """
const stub = await import('@earendil-works/pi-coding-agent');
globalThis.__stub = { inside: true, exit: 0, calls: [] };
process.env.PIB_SANDBOX = '1';
let open;
globalThis.__stub.gate = new Promise((r) => { open = r; });
const chunks = [];
const pending = stub.createLocalBashOperations({}).exec('x', '/', { onData: (d) => chunks.push(d), timeout: 1 });
delete process.env.PIB_SANDBOX;
open();
await pending;
out({ text: Buffer.concat(chunks).toString() });
""")
    assert "PIB-PROBE:/tmp/pib-mise-state" in got["text"]


def test_no_argument_toggles_and_turning_off_clears_yolo_before_the_sandbox(tmp_path):
    """引数なしは off → on → off。外すときは確認を出し、ターンの切れ目で、YOLO を切ってから囲いを外す。"""
    got = run_node(tmp_path, """
const t = setup({ config: { permission: POLICY } });
await run(t, '');
const mid = { env: process.env.PIB_SANDBOX, yolo: readCfg().yoloMode };
await run(t, '');
out({ mid, env: process.env.PIB_SANDBOX ?? null, cfg: readCfg(), order: t.order, confirms: t.confirms.length,
      status: t.status, last: t.notes.at(-1) });
""")
    assert got["mid"] == {"env": "1", "yolo": True}
    assert got["env"] is None and got["cfg"] == {"permission": POLICY, "yoloMode": False}
    assert got["order"] == ["idle:1"]  # 待つのは、囲いが残っているうち
    assert got["confirms"] == 1
    assert got["status"] == {"sandbox": "sandbox: off"}
    assert got["last"][0] == "warning"


def test_turning_off_waits_for_the_running_turn_before_anything_changes(tmp_path):
    """実行中のターンは YOLO が入ったまま続く。ターンが終わる (idle) まで、囲いも YOLO も変えない。"""
    got = run_node(tmp_path, """
const t = setup({ env: { PIB_SANDBOX: '1' }, config: { permission: POLICY, yoloMode: true } });
let release;
t.ctx.waitForIdle = () => new Promise((r) => { release = r; });
const pending = run(t, 'off');
await tick();
const during = { env: process.env.PIB_SANDBOX, yolo: readCfg().yoloMode };
release();
await pending;
out({ during, env: process.env.PIB_SANDBOX ?? null, yolo: readCfg().yoloMode });
""")
    assert got["during"] == {"env": "1", "yolo": True}
    assert got["env"] is None and got["yolo"] is False


def test_declining_the_confirmation_keeps_the_sandbox_and_yolo(tmp_path):
    got = run_node(tmp_path, """
const t = setup({ env: { PIB_SANDBOX: '1' }, config: { yoloMode: true }, confirm: false });
await run(t, 'off');
out({ env: process.env.PIB_SANDBOX, cfg: readCfg(), order: t.order });
""")
    assert got == {"env": "1", "cfg": {"yoloMode": True}, "order": []}


def test_the_sandbox_stays_on_when_yolo_cannot_be_turned_off(tmp_path):
    """YOLO を切れないまま囲いを外すと、囲いなしの YOLO になる。設定ファイルが壊れていれば、囲いを外さない。"""
    got = run_node(tmp_path, """
const t = setup({ env: { PIB_SANDBOX: '1' }, config: '{broken' });
await run(t, 'off');
out({ env: process.env.PIB_SANDBOX, last: t.notes.at(-1) });
""")
    assert got["env"] == "1"
    assert got["last"][0] == "error" and "囲いを外さなかった" in got["last"][1]


@pytest.mark.parametrize(
    "project",
    [
        {CFG: '{"yoloMode": true}'},
        {CFG: '{\n  "yoloMode":   true\n}'},
        {CFG: '{"yolo\\u004dode": true}'},  # キーの \u エスケープ (文字列の検索ではすり抜ける)
        {CFG: '/* 注 */ {\n  // 注\n  "yoloMode": true // 注\n}'},
        {CFG: "{\"permission\": {\"a\": \"// not a comment\"}, \"yoloMode\": true}"},  # 文字列の中の // は、コメントではない
        {LEGACY: '// 旧い置き場 (JSONC)\n{ "yoloMode": true }'},
        {CFG: '{ broken'},  # 読めないものは、YOLO が off と確かめられない
        {CFG: '{"yoloMode": false}', LEGACY: '{ "yoloMode": true }'},  # 2 か所のうち、1 か所でも on
    ],
)
def test_a_trusted_project_that_turns_yolo_on_blocks_removing_the_sandbox(tmp_path, project):
    """permission-system は、信頼済みのプロジェクトの設定を global の後に重ねる。project の yoloMode: true は、
    global の false に勝つので、global を false にしても、囲いなしの YOLO を防げない。囲いを外さない。
    上流と同じ解釈 (コメントを除いて JSON として読む) で判定する。"""
    got = run_node(tmp_path, f"""
const t = setup({{ env: {{ PIB_SANDBOX: '1' }}, config: {{ permission: POLICY, yoloMode: true }}, project: {json.dumps(project)} }});
await run(t, 'off');
const trusted = {{ env: process.env.PIB_SANDBOX, cfg: readCfg(), last: t.notes.at(-1) }};
const u = setup({{ env: {{ PIB_SANDBOX: '1' }}, config: {{ permission: POLICY, yoloMode: true }}, project: {json.dumps(project)},
                  trusted: false }});
await run(u, 'off');
out({{ trusted, untrustedEnv: process.env.PIB_SANDBOX ?? null }});
""")
    assert got["trusted"]["env"] == "1" and got["trusted"]["cfg"]["yoloMode"] is True  # 何も変えない
    assert got["trusted"]["last"][0] == "error" and "プロジェクト" in got["trusted"]["last"][1]
    assert got["untrustedEnv"] is None  # 信頼していないプロジェクトは読まれないので、外せる


@pytest.mark.parametrize(
    "project",
    [
        {CFG: '{"yoloMode": false}'},
        {CFG: '{"permission": {}}'},  # 項目が無い
        {CFG: '{\n  // "yoloMode": true\n  "yoloMode": false\n}'},  # コメントの中の記述は、設定ではない
        {CFG: '{"yoloMode": "true"}'},  # 上流は === true だけを on にする
        {CFG: '{"yoloMode": true, "yoloMode": false}'},  # 同じキーは、最後が勝つ (JSON.parse)
        {},
    ],
)
def test_a_project_config_that_does_not_turn_yolo_on_does_not_block(tmp_path, project):
    got = run_node(tmp_path, f"""
const t = setup({{ env: {{ PIB_SANDBOX: '1' }}, config: {{ permission: POLICY, yoloMode: true }}, project: {json.dumps(project)} }});
await run(t, 'off');
out({{ env: process.env.PIB_SANDBOX ?? null, yolo: readCfg().yoloMode }});
""")
    assert got == {"env": None, "yolo": False}


def test_turning_yolo_off_writes_an_explicit_false_even_when_the_key_is_missing(tmp_path):
    """global より前に読まれる旧い設定の yoloMode: true に勝つため、項目が無いときも、明示の false を書く。"""
    got = run_node(tmp_path, """
const t = setup({ config: { permission: POLICY } });
await run(t, 'off');
out({ cfg: readCfg() });
""")
    assert got["cfg"] == {"permission": POLICY, "yoloMode": False}


def test_a_switch_in_progress_blocks_another_one(tmp_path):
    """試し実行の最中に、別の /sandbox (off・status) が割り込むと、off のあとに YOLO が入る。1 つずつにする。"""
    got = run_node(tmp_path, """
const t = setup({ config: { permission: POLICY } });
let open;
globalThis.__stub.gate = new Promise((r) => { open = r; });
const first = run(t, 'on');
await tick();
await run(t, 'off');
await run(t, 'status');
const rejected = t.notes.filter(([, m]) => m.includes('実行中')).length;
open();
await first;
const again = run(t, 'status');
await again;
out({ env: process.env.PIB_SANDBOX ?? null, cfg: readCfg(), rejected, confirms: t.confirms.length,
      statusRan: t.notes.at(-1)[1].includes('確認した') });
""")
    assert got["rejected"] == 2 and got["confirms"] == 0
    assert got["env"] == "1" and got["cfg"]["yoloMode"] is True  # 割り込みは何も変えない
    assert got["statusRan"] is True  # 終われば、次の /sandbox を受け付ける


def test_a_failed_probe_restores_the_previous_mode_and_leaves_yolo_alone(tmp_path):
    """囲いが効かない (runner が無い・作業ディレクトリが広すぎる、など) とき、効いていない囲いを残さず、YOLO も入れない。"""
    got = run_node(tmp_path, """
const t = setup({ inside: false, config: { permission: POLICY, yoloMode: false } });
await run(t, 'on');
out({ env: process.env.PIB_SANDBOX ?? null, cfg: readCfg(), status: t.status, last: t.notes.at(-1) });
""")
    assert got["env"] is None and got["cfg"]["yoloMode"] is False
    assert got["status"] == {"sandbox": "sandbox: off"}
    assert got["last"][0] == "error" and "効かない" in got["last"][1]


def test_a_failed_probe_while_sandboxed_keeps_the_previous_sandboxed_mode(tmp_path):
    got = run_node(tmp_path, """
const t = setup({ env: { PIB_SANDBOX: '1' }, inside: false, exit: 2 });
await run(t, 'offline');
out({ env: process.env.PIB_SANDBOX });
""")
    assert got["env"] == "1"


def test_offline_mode_and_toggling_out_of_it(tmp_path):
    got = run_node(tmp_path, """
const t = setup({ config: { permission: POLICY } });
await run(t, 'offline');
const mid = { env: process.env.PIB_SANDBOX, status: t.status.sandbox };
await run(t, '');
out({ mid, env: process.env.PIB_SANDBOX ?? null });
""")
    assert got["mid"] == {"env": "offline", "status": "sandbox: offline"}
    assert got["env"] is None


@pytest.mark.parametrize(
    "scenario",
    [
        "setup({ settings: { shellPath: '/bin/bash' } })",  # shellPath が pib-shell でない
        "setup({ settings: {} })",  # 未設定
    ],
)
def test_it_refuses_when_the_shell_is_not_pib_shell(tmp_path, scenario):
    got = run_node(tmp_path, f"""
const t = {scenario};
await run(t, 'on');
out({{ env: process.env.PIB_SANDBOX ?? null, calls: globalThis.__stub.calls.length, cfg: readCfg(), last: t.notes.at(-1) }});
""")
    assert got["env"] is None and got["calls"] == 0 and got["cfg"] is None
    assert got["last"][0] == "error"


def test_the_tilde_form_of_the_shell_path_is_accepted_like_pib(tmp_path):
    got = run_node(tmp_path, """
const t = setup({ settings: { shellPath: '~/.local/bin/pib-shell' } });
await run(t, 'on');
out({ env: process.env.PIB_SANDBOX });
""")
    assert got["env"] == "1"


@pytest.mark.parametrize("name", ["home-dot", "home-slash", "home-double"])
def test_it_refuses_a_home_that_is_not_in_canonical_form(tmp_path, name):
    """pib と同じく、HOME は食い違いようのない表記だけを受け付ける (pi の解釈と OS の解釈がずれうるため)。"""
    home = {"home-dot": "/tmp/./h", "home-slash": "/tmp/h/", "home-double": "/tmp//h"}[name]
    got = run_node(tmp_path, """
const t = setup({ settings: { shellPath: '/tmp/./h/.local/bin/pib-shell' } });
await run(t, 'on');
out({ env: process.env.PIB_SANDBOX ?? null, calls: globalThis.__stub.calls.length });
""", home=home)
    assert got == {"env": None, "calls": 0}


def test_off_when_already_off_clears_a_leftover_yolo(tmp_path):
    got = run_node(tmp_path, """
const t = setup({ config: { yoloMode: true } });
await run(t, 'off');
out({ cfg: readCfg(), confirms: t.confirms.length });
""")
    assert got == {"cfg": {"yoloMode": False}, "confirms": 0}


def test_turning_off_needs_a_ui_to_confirm(tmp_path):
    got = run_node(tmp_path, """
const t = setup({ env: { PIB_SANDBOX: '1' }, config: { yoloMode: true }, hasUI: false });
await run(t, 'off');
out({ env: process.env.PIB_SANDBOX, cfg: readCfg() });
""")
    assert got == {"env": "1", "cfg": {"yoloMode": True}}


@pytest.mark.parametrize(
    ("env", "config", "reason", "expected"),
    [
        ({"PIB_SANDBOX": "1"}, {"permission": POLICY, "yoloMode": False}, "startup", True),  # pib の起動: YOLO が入る
        ({"PIB_SANDBOX": "offline"}, {"permission": POLICY}, "startup", True),
        ({}, {"yoloMode": True}, "startup", False),  # 素の pi の起動: 前回の YOLO を持ち越さない
        ({}, {"yoloMode": True}, "reload", True),  # /reload・/new・/resume では、利用者が選んだ値を戻さない
        ({}, {"yoloMode": True}, "new", True),
    ],
)
def test_startup_aligns_yolo_with_the_sandbox_state(tmp_path, env, config, reason, expected):
    got = run_node(tmp_path, f"""
const t = setup({{ env: {json.dumps(env)}, config: {json.dumps(config)} }});
await t.handlers.session_start({{ reason: {json.dumps(reason)} }}, t.ctx);
out({{ cfg: readCfg(), status: t.status }});
""")
    assert (got["cfg"] or {}).get("yoloMode", False) is expected
    assert got["status"]["sandbox"].startswith("sandbox: ")


@pytest.mark.parametrize(
    "scenario",
    [
        "inside: false",  # 試し実行で、囲いの内側の印が見えない
        "inside: true, settings: { shellPath: '/bin/bash' }",  # 実効の shellPath が pib-shell でない
    ],
)
def test_startup_does_not_turn_yolo_on_for_an_unverified_sandbox(tmp_path, scenario):
    """PIB_SANDBOX が立っているだけでは、囲いが効いているとは限らない。確かめられなければ、YOLO を入れず、前回の YOLO も切る。"""
    got = run_node(tmp_path, f"""
const t = setup({{ env: {{ PIB_SANDBOX: '1' }}, config: {{ permission: POLICY, yoloMode: true }}, {scenario} }});
await t.handlers.session_start({{ reason: 'startup' }}, t.ctx);
out({{ yolo: readCfg().yoloMode, status: t.status.sandbox, errors: t.notes.filter(([l]) => l === 'error').length }});
""")
    assert got["yolo"] is False and got["errors"] == 1
    assert "効いていない" in got["status"]  # フッターにも出す


def test_a_sandbox_command_during_the_startup_check_is_refused(tmp_path):
    """pi は、起動の途中 (session_start の完了前) から入力を受け付ける。起動時の確認の最中に /sandbox off が通ると、
    off のあとに YOLO が入る。起動時の確認も 1 つの枠を取り、その間の /sandbox は断る。"""
    got = run_node(tmp_path, """
const t = setup({ env: { PIB_SANDBOX: '1' }, config: { permission: POLICY, yoloMode: false } });
let open;
globalThis.__stub.gate = new Promise((r) => { open = r; });
const startup = t.handlers.session_start({ reason: 'startup' }, t.ctx);
await tick();
await run(t, 'off');
const during = { env: process.env.PIB_SANDBOX, confirms: t.confirms.length,
                 rejected: t.notes.filter(([, m]) => m.includes('実行中')).length };
open();
await startup;
await run(t, 'status');
out({ during, env: process.env.PIB_SANDBOX ?? null, yolo: readCfg().yoloMode, again: t.notes.at(-1)[1].includes('確認した') });
""")
    assert got["during"] == {"env": "1", "confirms": 0, "rejected": 1}
    assert got["env"] == "1" and got["yolo"] is True  # 囲いも YOLO も、起動時の状態のまま (食い違わない)
    assert got["again"] is True  # 終われば、次の /sandbox を受け付ける


def test_startup_does_not_create_a_config_file_just_to_say_off(tmp_path):
    got = run_node(tmp_path, """
const t = setup();
await t.handlers.session_start({ reason: 'startup' }, t.ctx);
out({ cfg: readCfg() });
""")
    assert got == {"cfg": None}


def test_status_reports_the_probe_and_warns_about_yolo_without_a_sandbox(tmp_path):
    got = run_node(tmp_path, """
const a = setup({ env: { PIB_SANDBOX: '1' }, config: { yoloMode: true } });
await run(a, 'status');
const b = setup({ config: { yoloMode: true } });
await run(b, 'status');
const c = setup({ env: { PIB_SANDBOX: '1' }, inside: false });
await run(c, 'status');
const d = setup({ config: { yoloMode: false }, project: { '.pi/extensions/pi-permission-system/config.json': '{"yoloMode": true}' } });
await run(d, 'status');
out({ a: a.notes.at(-1), b: b.notes.at(-1), c: c.notes.at(-1), d: d.notes.at(-1) });
""")
    assert got["a"][0] == "info" and "確認した" in got["a"][1] and "YOLO（設定ファイルの値。次のターンから効く）: on" in got["a"][1]
    assert got["b"][0] == "warning"  # 囲いなしの YOLO
    assert got["c"][0] == "error" and "効いていない" in got["c"][1]
    assert got["d"][0] == "warning" and "プロジェクト" in got["d"][1]  # global は off でも、プロジェクトが on


def test_unknown_argument_and_completions(tmp_path):
    got = run_node(tmp_path, """
const t = setup();
await run(t, 'bogus');
out({ last: t.notes.at(-1), env: process.env.PIB_SANDBOX ?? null,
      all: t.commands.sandbox.getArgumentCompletions('').map((i) => i.value),
      pre: t.commands.sandbox.getArgumentCompletions('of').map((i) => i.value),
      none: t.commands.sandbox.getArgumentCompletions('zz') });
""")
    assert got["last"][0] == "warning" and got["env"] is None
    assert got["all"] == ["on", "offline", "off", "status"]
    assert got["pre"] == ["offline", "off"] and got["none"] is None


def test_it_registers_nothing_outside_linux(tmp_path):
    got = run_node(tmp_path, """
Object.defineProperty(process, 'platform', { value: 'darwin' });
const t = setup();
out({ commands: Object.keys(t.commands), handlers: Object.keys(t.handlers), events: Object.keys(t.events) });
""")
    assert got == {"commands": [], "handlers": [], "events": []}


def test_the_package_is_a_pi_package_with_no_bundled_dependencies():
    meta = json.loads((PACKAGE / "package.json").read_text(encoding="utf-8"))
    assert meta["pi"]["extensions"] == ["./src/index.ts"]
    assert "dependencies" not in meta  # 本体が提供するものを同梱しない (pi の docs)
