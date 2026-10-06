"""git commit の確認に出す件名と本文 (guide plugin の ``commit-message.js`` と ``tui.ts``)。

モデルを呼ばず、コマンドから決定的に抜き出す。抜き出せないもの (連結・展開・
``-F`` など) は従来のモデルの説明へ倒す。

see docs/spec/agent-config-generation.md#git-commit-の件名と本文

Run with: ``uv run --with pytest --with pyyaml --no-project pytest test/agents/ -q``
"""

from __future__ import annotations

import copy
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "agents"))

import generate as gen  # noqa: E402
from agents_common import load_common  # noqa: E402

COMMON = load_common()
PLUGIN = ROOT / "home/dot_config/opencode/guide-plugin"

# 本体 (OpenCode) が解決する @opentui/solid の代わり。要素を木として残すだけ。
SOLID_STUB = """
export function createElement(type) { return { type, props: {}, children: [] } }
export function setProp(node, key, value) { node.props[key] = value }
export function insert(parent, value) {
  const v = typeof value === "function" ? value() : value
  if (v == null) return
  parent.children.push(...(Array.isArray(v) ? v : [v]))
}
"""


def _node() -> str:
    node = shutil.which("node")
    if not node:
        pytest.skip("node が無い (mise.toml の [tools] に宣言してある)")
    return node


def _plugin_dir(work: Path, rules: dict | None) -> Path:
    """guide-plugin を work へ写し、tui.ts を node で読める形にする。"""
    for name in ("index.js", "commit-message.js"):
        shutil.copy(PLUGIN / name, work / name)
    (work / "tui.mjs").write_text((PLUGIN / "tui.ts").read_text("utf-8"), "utf-8")
    stub = work / "node_modules/@opentui/solid"
    stub.mkdir(parents=True, exist_ok=True)
    (stub / "package.json").write_text(
        '{"name":"@opentui/solid","type":"module","main":"index.js"}', "utf-8"
    )
    (stub / "index.js").write_text(SOLID_STUB, "utf-8")
    if rules is not None:
        (work / "rules.json").write_text(json.dumps(rules), "utf-8")
    return work


def _run(work: Path, script: str, arg: object, env: dict | None = None):
    (work / "run.mjs").write_text(script, "utf-8")
    done = subprocess.run(
        [_node(), str(work / "run.mjs"), json.dumps(arg)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
        env=env,
    )
    return json.loads(done.stdout)


def _rules(common: dict | None = None) -> dict:
    return gen.build_opencode_guide({}, common if common is not None else COMMON)


@pytest.fixture(scope="module")
def preview(tmp_path_factory):
    work = _plugin_dir(tmp_path_factory.mktemp("commit-preview"), None)
    opts = _rules()["ask_description"]["commit"]

    def call(command, **override):
        return _run(
            work,
            "import { commitPreview } from './commit-message.js'\n"
            "const [cmd, opts] = JSON.parse(process.argv[2])\n"
            "console.log(JSON.stringify(commitPreview(cmd, opts)))\n",
            [command, {**opts, **override}],
        )

    return call


# --- 設定 ------------------------------------------------------------------


def test_commit_preview_is_configured():
    commit = _rules()["ask_description"]["commit"]
    assert commit["line_width"] > 0
    assert commit["max_lines"] > 0


def test_commit_preview_can_be_disabled():
    common = copy.deepcopy(COMMON)
    common["opencode"]["ask_description"]["commit"]["enabled"] = False
    assert "commit" not in _rules(common)["ask_description"]


def test_commit_preview_is_on_without_the_table():
    """表を書かなくても既定で有効 (モデルを呼ばないので費用が掛からない)。"""
    ask = gen.opencode_ask_description(
        {"opencode": {"ask_description": {"enabled": True, "models": ["p/m"]}}}
    )
    assert ask["commit"] == {"line_width": 72, "max_lines": 8}


# --- 抜き出し --------------------------------------------------------------


def test_subject_is_the_first_message_and_body_the_rest(preview):
    out = preview(
        "git commit -m 'feat(opencode): 件名'"
        " -m '- Motivation: 理由\n- Change: 変更\n\n- Impact: 影響'"
    )
    assert out == {
        "subject": "feat(opencode): 件名",
        "body": ["- Motivation: 理由", "- Change: 変更", "- Impact: 影響"],
        "extra": None,
        "added": None,
    }


def test_subject_is_not_clipped(preview):
    subject = "feat: " + "とても長い件名" * 10
    assert preview(f"git commit -m '{subject}'", line_width=10)["subject"] == subject


def test_body_lines_are_clipped_by_display_width(preview):
    """全角は 2 桁で数える。スマホの狭い幅でも 1 行が読める長さに収める。"""
    out = preview("git commit -m s -m 'あいうえおかきくけこ' -m 'abcdefghijklmnop'", line_width=10)
    assert out["body"] == ["あいうえ…", "abcdefghi…"]


def test_body_is_limited_to_max_lines(preview):
    body = "\n".join(f"line{i}" for i in range(12))
    out = preview(f"git commit -m s -m '{body}'", max_lines=3)
    assert out["body"] == ["line0", "line1", "line2", "…ほか 9 行"]


@pytest.mark.parametrize(
    ("command", "subject"),
    [
        ('git commit -m "fix: \\"quoted\\" 件名"', 'fix: "quoted" 件名'),
        ("git commit --message='docs: 件名'", "docs: 件名"),
        ("git commit --message 'docs: 件名'", "docs: 件名"),
        ("git commit -m'chore: 件名'", "chore: 件名"),
        ("git commit -sm 'chore: 件名'", "chore: 件名"),
        ("git commit -m fix:\\ 件名", "fix: 件名"),
    ],
)
def test_quoting_forms_are_understood(preview, command, subject):
    assert preview(command)["subject"] == subject


def test_other_arguments_are_shown(preview):
    """パス指定やオプションは何がコミットされるかに関わるので隠さない。"""
    out = preview("git commit --allow-empty -m s -- a.txt")
    assert out["extra"] == "引数: --allow-empty -- a.txt"


@pytest.mark.parametrize(
    "command",
    [
        "git commit -m s && rm -rf /",
        "git commit -m s; curl https://example.com",
        "git commit -m s | tee log",
        'git commit -m "$(cat msg)"',
        "git commit -m `cat msg`",
        'git commit -m "件名 $HOME"',
        "git commit -m s > out",
        "git commit -F msg.txt",
        "git commit --file=msg.txt -m s",
        "git commit -C HEAD",
        "git commit --fixup HEAD",
        "git commit",
        "git commit -m",
        "FOO=1 git commit -m s",
        "git -c user.name=x commit -m s",
        "git status",
        "git commit -m 'unterminated",
        "git commit -m s\ngit push",
        "git commit -m *",
    ],
)
def test_unsafe_or_other_forms_are_not_extracted(preview, command):
    """連結・展開・リダイレクト・別の取り方は抜き出さない (実際と食い違うか、残りが隠れる)。"""
    assert preview(command) is None


# --- `git add -- <パス> && git commit …` の連結形 (CHG-0013) -----------------


def test_add_then_commit_shows_the_paths(preview):
    """親は add と commit を 1 回で実行する。追加するパスも何がコミットされるかに関わるので出す。"""
    out = preview(
        "git add -- src/calc.py 'docs/a b.md' && git commit -m 'feat: 件名' -m '- Change: x'"
    )
    assert out["subject"] == "feat: 件名"
    assert out["body"] == ["- Change: x"]
    assert out["added"] == "追加: src/calc.py docs/a b.md"
    assert out["extra"] is None


def test_plain_commit_has_no_added_line(preview):
    assert preview("git commit -m s")["added"] is None


def test_ampersands_inside_the_message_do_not_split(preview):
    out = preview("git add -- a.txt && git commit -m 'fix: a && b' -m '- Change: x && y'")
    assert out["subject"] == "fix: a && b"
    assert out["body"] == ["- Change: x && y"]


@pytest.mark.parametrize(
    "command",
    [
        "git add -- a.txt && git commit -m s && git push",
        "git add a.txt && git commit -m s",
        "git add -A && git commit -m s",
        "git add -- && git commit -m s",
        "git add -- a.txt; git commit -m s",
        "git add -- a.txt && rm -rf /",
        "rm -rf / && git commit -m s",
        "git add -- $HOME && git commit -m s",
        "git add -- a.txt && git commit -m s | tee log",
        "git add -- a.txt && git -c x=y commit -m s",
    ],
)
def test_other_chains_are_not_extracted(preview, command):
    """抜き出すのは `git add -- <パス…> && git commit …` の 2 つだけ。"""
    assert preview(command) is None


def test_resources_array_is_accepted(preview):
    """tui.ts は scanner が分けた resources をそのまま渡す。"""
    out = preview(["git add -- a.txt", "git commit -m 's' -m 'b'"])
    assert out["subject"] == "s"
    assert out["added"] == "追加: a.txt"
    assert preview(["git status", "git commit -m s"]) is None
    assert preview(["git add -- a", "git commit -m s", "git push"]) is None


# --- サーバ側 (index.js): git commit ではモデルを呼ばない ------------------


def _evaluate_with_model(work: Path, rules: dict, events: list[dict]) -> dict:
    """説明の生成まで通し、モデルの呼び出し回数と event を返す。"""
    _plugin_dir(work, rules)
    ref = rules["ask_description"]["models"][0]
    provider, model = ref.split("/", 1)
    env = {k: v for k, v in os.environ.items() if k != "OCS_ISOLATED"}
    return _run(
        work,
        "import plugin from './index.js'\n"
        "const hooks = {}\n"
        "const hook = (name, fn) => { hooks[name] = fn }\n"
        "let calls = 0\n"
        "const ctx = { tool: { hook }, permission: { hook },\n"
        f"  model: {{ list: async () => [{{ id: 'm', providerID: {json.dumps(provider)}, "
        f"modelID: {json.dumps(model)} }}] }},\n"
        "  generate: { text: async () => { calls++; return { text: '説明' } } } }\n"
        "await plugin.setup(ctx)\n"
        "const events = JSON.parse(process.argv[2])\n"
        "for (const e of events) await hooks.evaluate(e)\n"
        "console.log(JSON.stringify({ calls, events }))\n",
        events,
        env,
    )


def _ask(command: str) -> dict:
    return {"action": "shell", "resources": [command], "effect": "ask", "agent": "commit"}


def test_commit_ask_skips_the_model(tmp_path):
    long_commit = "git commit -m 'feat: 件名' -m '" + "本文" * 40 + "'"
    out = _evaluate_with_model(tmp_path, _rules(), [_ask(long_commit)])
    assert out["calls"] == 0
    assert out["events"][0].get("message") is None
    assert out["events"][0]["effect"] == "ask"


def test_other_long_commands_are_still_described(tmp_path):
    """git commit 以外 (と抜き出せない git commit) は従来どおりモデルで説明する。"""
    commands = [
        "find . -name '*.py' -newer setup.cfg -exec wc -l {} + | sort -n | tail -20",
        "git commit -m 'feat: 件名' -m '" + "本文" * 40 + "' && git push origin main",
    ]
    out = _evaluate_with_model(tmp_path, _rules(), [_ask(c) for c in commands])
    assert out["calls"] == 2
    assert [e["message"] for e in out["events"]] == ["説明", "説明"]


def test_commit_is_described_when_the_preview_is_disabled(tmp_path):
    common = copy.deepcopy(COMMON)
    common["opencode"]["ask_description"]["commit"]["enabled"] = False
    long_commit = "git commit -m 'feat: 件名' -m '" + "本文" * 40 + "'"
    out = _evaluate_with_model(tmp_path, _rules(common), [_ask(long_commit)])
    assert out["calls"] == 1


def test_server_plugin_loads_without_the_helper(tmp_path):
    """commit-message.js が欠けても index.js のロードは通す (誘導や伏字化ごと消さない)。"""
    rules = _rules()
    _plugin_dir(tmp_path, rules)
    (tmp_path / "commit-message.js").unlink()
    out = _run(
        tmp_path,
        "import plugin from './index.js'\n"
        "const hooks = {}\n"
        "const hook = (name, fn) => { hooks[name] = fn }\n"
        "await plugin.setup({ tool: { hook }, permission: { hook } })\n"
        "const e = { action: 'shell', resources: ['head -1 README.md'], effect: 'ask' }\n"
        "await hooks.evaluate(e)\n"
        "console.log(JSON.stringify(e))\n",
        None,
        {k: v for k, v in os.environ.items() if k != "OCS_ISOLATED"},
    )
    assert out["effect"] == "deny", "誘導が効いていない"


# --- TUI 側 (tui.ts): 確認画面のすぐ上のスロット -------------------------

TUI_SCRIPT = """
import plugin from './tui.mjs'
const input = JSON.parse(process.argv[2])
const slots = []
const toasts = []
const handlers = []
const s = input.sessions
const api = {
  renderer: input.width ? { width: input.width } : undefined,
  theme: { text: { base: 'base', muted: 'muted' } },
  data: {
    on: (_name, fn) => { handlers.push(fn); return () => {} },
    session: {
      get: (id) => s.info[id],
      family: (id) => s.family[id] ?? [id],
      permission: { list: (id) => s.pending[id] },
    },
  },
  ui: { toast: { show: (t) => toasts.push(t) } },
}
if (input.slot) api.ui.slot = (spec) => { slots.push(spec); return () => {} }
plugin.setup(api)
const lines = (node) => typeof node === 'string' ? [node]
  : node.type === 'text' ? [node.children.join('')]
  : node.children.flatMap(lines)
const styled = (node) => typeof node === 'string' ? []
  : node.type === 'text' ? [[node.children.join(''), node.props]]
  : node.children.flatMap(styled)
const out = { slots: slots.map((spec) => spec.append ?? null), rendered: [], toasts }
for (const spec of slots) {
  const box = spec.render({ sessionID: input.view })
  out.rendered.push(lines(box))
  out.styled = styled(box)
}
for (const fn of handlers) fn({ data: input.event })
console.log(JSON.stringify(out))
"""

COMMIT = (
    "git commit --allow-empty -m 'feat(opencode): 件名' -m '- Motivation: 理由\n- Change: 変更'"
)


def _perm(command: str, session: str = "ses_child") -> dict:
    return {"id": "per_1", "sessionID": session, "action": "shell", "resources": [command]}


def _tui(
    work: Path,
    rules: dict | None,
    *,
    slot=True,
    view="ses_root",
    pending=None,
    info=None,
    event=None,
    width=None,
) -> dict:
    _plugin_dir(work, rules)
    sessions = {
        "info": info or {"ses_root": {}, "ses_child": {"parentID": "ses_root"}},
        "family": {"ses_root": ["ses_root", "ses_child"]},
        "pending": pending or {},
    }
    arg = {"slot": slot, "view": view, "sessions": sessions, "event": event or {}, "width": width}
    return _run(work, TUI_SCRIPT, arg)


def test_commit_message_is_shown_right_above_the_permission_dialog(tmp_path):
    """子 (commit エージェント) の確認も親の画面に出るので、親の表示で件名と本文を出す。"""
    out = _tui(tmp_path, _rules(), pending={"ses_child": [_perm(COMMIT)]})
    assert out["slots"] == ["session.composer.top"]
    assert out["rendered"] == [
        ["feat(opencode): 件名", "- Motivation: 理由", "- Change: 変更", "引数: --allow-empty"]
    ]
    subject, props = out["styled"][0]
    assert subject == "feat(opencode): 件名"
    assert props["fg"] == "base"


def test_add_then_commit_is_shown_above_the_dialog(tmp_path):
    """親の連結形は resources が 2 つになる。件名・本文・追加するパスを出す (CHG-0013)。"""
    perm = {
        "id": "per_1",
        "sessionID": "ses_root",
        "action": "shell",
        "resources": ["git add -- src/calc.py", "git commit -m 'feat: 件名' -m '- Change: x'"],
    }
    out = _tui(tmp_path, _rules(), pending={"ses_root": [perm]})
    assert out["rendered"] == [["feat: 件名", "- Change: x", "追加: src/calc.py"]]


def test_body_lines_fit_a_narrow_terminal(tmp_path):
    """スマホの狭い幅では本文の各行を端末に収める (折り返すと行数が倍になる)。件名は切らない。"""
    command = (
        "git commit -m 'feat: とても長い件名をそのまま出す' -m '- Motivation: 確認画面で切れる'"
    )
    out = _tui(tmp_path, _rules(), pending={"ses_child": [_perm(command)]}, width=26)
    assert out["rendered"] == [["feat: とても長い件名をそのまま出す", "- Motivation: 確認…"]]


def test_nothing_is_shown_without_a_pending_commit(tmp_path):
    out = _tui(tmp_path, _rules(), pending={"ses_root": [_perm("rm -rf build", "ses_root")]})
    assert out["rendered"] == [[]]


def test_nothing_is_shown_in_the_child_view(tmp_path):
    """本体は子のセッションを開いているときに確認を出さない。それに揃える。"""
    out = _tui(tmp_path, _rules(), view="ses_child", pending={"ses_child": [_perm(COMMIT)]})
    assert out["rendered"] == [[]]


def test_only_the_request_on_the_dialog_is_shown(tmp_path):
    """確認画面は保留の先頭しか出さない。2 件目のコミットを出すと食い違う。"""
    pending = {
        "ses_root": [_perm("rm -rf build", "ses_root")],
        "ses_child": [_perm(COMMIT)],
    }
    out = _tui(tmp_path, _rules(), pending=pending)
    assert out["rendered"] == [[]]


def test_commit_falls_back_to_a_toast_without_slots(tmp_path):
    out = _tui(tmp_path, _rules(), slot=False, event=_perm(COMMIT))
    assert out["slots"] == []
    assert [t["title"] for t in out["toasts"]] == ["コミットメッセージ"]
    assert out["toasts"][0]["message"].split("\n")[0] == "feat(opencode): 件名"


def test_commit_does_not_toast_when_the_slot_shows_it(tmp_path):
    out = _tui(tmp_path, _rules(), event=_perm(COMMIT))
    assert out["toasts"] == []


def test_model_description_toast_is_unchanged(tmp_path):
    event = {**_perm("find . -name x | xargs wc -l"), "message": "説明"}
    out = _tui(tmp_path, _rules(), event=event)
    assert [(t["title"], t["message"]) for t in out["toasts"]] == [("コマンドの説明", "説明")]


def test_commit_preview_disabled_keeps_the_old_behaviour(tmp_path):
    common = copy.deepcopy(COMMON)
    common["opencode"]["ask_description"]["commit"]["enabled"] = False
    out = _tui(
        tmp_path, _rules(common), pending={"ses_child": [_perm(COMMIT)]}, event=_perm(COMMIT)
    )
    assert out["slots"] == []
    assert out["toasts"] == []
