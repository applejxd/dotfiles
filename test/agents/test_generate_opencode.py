"""OpenCode の global config (``~/.config/opencode/opencode.json``) 生成の test.

OpenCode には hook 機構も sandbox も無く、3 層のうち permission 層しか使えない。
つまり ``common.toml`` の意図が **permission リストだけで** 表現できているか、
そして OpenCode 固有の照合規則 (後勝ち・``**`` 記法が無い) に合わせた変換が
できているかが、そのまま防御の有無になる。

Run with: ``uv run --with pytest --no-project pytest test/agents/ -q``
"""

from __future__ import annotations

import copy
import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "agents"))

import generate as gen  # noqa: E402
from agents_common import load_common  # noqa: E402

COMMON = load_common()
MODIFIER = ROOT / "home/dot_config/opencode/modify_opencode.json.py.tmpl"
INSTRUCTIONS = ROOT / "home/dot_config/opencode/AGENTS.md.tmpl"
SHARED_INSTRUCTIONS = ROOT / "home/.chezmoitemplates/agent-instructions.md"


def generated(common: dict | None = None) -> dict:
    return gen.merge_opencode_config({}, common if common is not None else COMMON)


def rules(action: str, effect: str, config: dict | None = None) -> list[str]:
    config = config or generated()
    return [
        rule["resource"]
        for rule in config["permissions"]
        if rule["action"] == action and rule["effect"] == effect
    ]


# ---------------------------------------------------------------------------
# 配線 (chezmoi 側)
# ---------------------------------------------------------------------------


def test_target_is_registered_and_wired():
    assert gen.TARGETS["opencode-config"] is gen.merge_opencode_config
    source = MODIFIER.read_text(encoding="utf-8")
    assert '"target" "opencode-config"' in source
    assert 'includeTemplate "dot_config/agents/common.toml.tmpl"' in source
    # 生成物を source state に置かない (置くと単一ソースが二重化する)
    assert not (ROOT / "home/dot_config/opencode/opencode.json").exists()


def test_global_instructions_reuse_the_shared_template():
    """Claude / Codex / Copilot と同じ本文を配る (指示を CLI ごとに写さない)。

    OpenCode V2 が読む global 指示は ``~/.config/opencode/AGENTS.md`` だけで、
    ``CLAUDE.md`` へのフォールバックは無い (公式 Instructions ガイド)。
    """
    source = INSTRUCTIONS.read_text(encoding="utf-8")
    assert 'includeTemplate "agent-instructions.md"' in source
    # 本文をここに写していないこと
    assert "## 検証" not in source
    assert SHARED_INSTRUCTIONS.is_file()


# ---------------------------------------------------------------------------
# 形 (公式スキーマ)
# ---------------------------------------------------------------------------


def test_schema_and_update_policy():
    config = generated()
    assert config["$schema"] == gen.OPENCODE_SCHEMA
    assert next(iter(config)) == "$schema", "エディタ補完のため先頭に置く"
    # CLI 本体は公式インストーラーで入れるので自動更新はしない
    assert config["update"] == "disable"


def test_rules_use_only_the_three_required_fields():
    for rule in generated()["permissions"]:
        assert set(rule) == {"action", "resource", "effect"}
        assert rule["effect"] in {"allow", "deny", "ask"}


def test_unmanaged_keys_survive():
    existing = {"small_model": "anthropic/claude-haiku-4-5", "theme": "custom"}
    before = copy.deepcopy(existing)
    merged = gen.merge_opencode_config(existing, COMMON)

    assert merged["small_model"] == before["small_model"]
    assert merged["theme"] == before["theme"]
    assert existing == before, "入力を破壊しない"
    assert gen.merge_opencode_config(merged, COMMON) == merged


# ---------------------------------------------------------------------------
# 後勝ち (OpenCode 固有の照合規則)
# ---------------------------------------------------------------------------


def test_default_is_ask_and_the_catch_all_comes_first():
    """未掲載のコマンドを無条件許可にしない。

    OpenCode に classifier は無いので、``[bash]`` の「未掲載は auto / assisted
    へ委ねる」設計がそのままだと無条件実行になる。``*`` は最も一般的な規則
    なので **先頭**に無ければならない。後ろにあると全部を ask で塗り潰す。
    """
    shell = [r for r in generated()["permissions"] if r["action"] == "shell"]
    assert shell[0] == {"action": "shell", "resource": "*", "effect": "ask"}
    assert [r["resource"] for r in shell[1:]].count("*") == 0


def test_effects_are_ordered_allow_then_ask_then_deny():
    """OpenCode は **最後に一致した規則** が勝つ。

    Claude の deny > ask > allow と逆なので、並び順が優先順位そのものになる。
    崩れると ``git reset --hard`` の deny を ``git reset`` の ask が上書きする。

    shell だけは先頭の ``*`` (既定 ask) を除いてから見る。これは最も一般的な
    規則で、allow より前に来るのが正しい。
    """
    order = {"allow": 0, "ask": 1, "deny": 2}
    for action in ("shell", "read", "edit"):
        found = [r for r in generated()["permissions"] if r["action"] == action]
        # deny の例外 (allow) は対の deny の直後に置くのが正しい (別のテストで固定)。
        # 例外と交差する ask (作業ツリー外の edit の確認) も、その直後に戻してある
        if action != "shell":
            first_deny = next(i for i, r in enumerate(found) if r["effect"] == "deny")
            found = [
                r
                for i, r in enumerate(found)
                if r["effect"] != "allow" and not (r["effect"] == "ask" and i > first_deny)
            ]
        else:
            found = found[1:]
        seen = [order[r["effect"]] for r in found]
        assert seen == sorted(seen), f"{action} の effect 並びが崩れている"


@pytest.mark.parametrize(
    ("general", "specific"),
    [("git reset *", "git reset --hard *"), ("git config *", "git config --global *")],
)
def test_specific_deny_comes_after_the_general_ask(general: str, specific: str):
    resources = [rule["resource"] for rule in generated()["permissions"]]
    assert resources.index(specific) > resources.index(general)


# ---------------------------------------------------------------------------
# shell
# ---------------------------------------------------------------------------


def test_shell_allow_comes_from_the_opencode_section():
    """allow だけ ``[opencode.shell]`` から取る (``[bash]`` と共有しない)。

    ``[bash] allow`` は Claude / Copilot と共有しており、未掲載を classifier
    へ委ねる前提で組まれている。OpenCode は既定 ask なので前提が違う。
    スキルのスクリプトの allow は ``[opencode.skill_scripts]`` から足す。
    """
    expected = [f"{cmd} *" for cmd in COMMON["opencode"]["shell"]["allow"]]
    expected += gen.opencode_skill_script_rules(COMMON)[0]
    assert rules("shell", "allow") == expected


def test_shell_ask_and_deny_still_come_from_bash():
    skill = {r for group in gen.opencode_skill_script_rules(COMMON) for r in group}
    for effect in ("ask", "deny"):
        expected = [f"{cmd} *" for cmd in COMMON["bash"][effect]]
        # 先頭の catch-all (既定 ask) とスキルのスクリプトの例外は [bash] 由来ではないので外す
        found = [r for r in rules("shell", effect) if r != "*" and r not in skill]
        assert found == expected


# 実行するコードを呼び出し側が決められるもの。allow に載ると、そのコマンドが
# 無確認で任意コード実行の入口になる。
# - find     -exec / -delete / -fprintf
# - gcc/g++  -B や specs ファイルで任意プログラムを起動できる
# - cmake    CMakeLists.txt がそのまま実行される
# - uv sync  依存のビルドフックが走る
# - mise run タスク定義が走る
ARBITRARY_CODE_EXECUTION = ("find", "gcc", "g++", "cmake", "uv sync", "mise run")


@pytest.mark.parametrize("command", ARBITRARY_CODE_EXECUTION)
def test_allow_has_no_arbitrary_code_execution(command: str):
    """段階 1 の受入条件。

    これらは実測で ``find`` 以外のヒットが 0 件だった。確認を増やさずに
    落とせるので、allow に戻す理由があるなら測り直してからにする。
    """
    for resource in rules("shell", "allow"):
        assert not resource.startswith(command), f"{resource} は任意コード実行を含む"


def test_bypass_agent_is_declared():
    """通常と同じ permission のまま、guide-plugin が ask を allow にするエージェント。

    ``"*" = "allow"`` を置くと、deny の後ろに付いて静的 deny まで上書きするので置かない。
    V1 の ``mode`` は非推奨なので ``agent`` で出す。``bypass`` の印は opencode.json に出さない。
    see docs/adr/0014-bypass-as-ask-upgrade.md
    """
    agent = generated()["agent"]["bypass"]
    assert "*" not in agent["permission"]
    assert "bypass" not in agent
    assert agent["description"]


def test_bypass_agents_have_no_allow_everything():
    """★bypass 系の生成物に全 allow が無い (あると通常で deny のものまで通る)。"""
    config = generated()
    for name, agent in config["agent"].items():
        permission = agent["permission"]
        assert permission != "allow" and "*" not in permission, name
    for name, agent in config["agents"].items():
        for rule in agent.get("permissions", []):
            assert not (rule["action"] == "*" and rule["effect"] == "allow"), name
            assert "bypass" not in agent, name
    assert generated()["agents"]["bypass-fleet-worker"]["permissions"][0]["effect"] == "deny"


def test_bypass_cannot_launch_approval_based_workers():
    """★承認制の子は bypass の中でも確認で止まる。bypass 用の作業役へ寄せる。

    実測で拒否され、subagent ツールの一覧からも消える。
    see docs/spec/agent-config-generation.md#bypass-から呼べる子エージェント
    """
    task = generated()["agent"]["bypass"]["permission"]["task"]
    assert task["*"] == "allow"
    assert task["general"] == "deny"
    assert task["fleet-worker"] == "deny"
    for name in ("bypass-worker", "bypass-fleet-worker", "explore", "review", "commit"):
        assert task.get(name, task["*"]) == "allow", name


def test_agents_not_declared_in_common_are_kept():
    """``/agents`` などが同じファイルへ書くので、宣言した名前だけ差し替える。"""
    existing = {"agent": {"mine": {"description": "手で足したもの"}}}
    merged = gen.merge_opencode_config(existing, COMMON)["agent"]
    assert merged["mine"] == {"description": "手で足したもの"}
    assert "bypass" in merged


def test_only_the_bypass_agents_come_from_common():
    """権限を緩めるエージェントが黙って増えないようにする。"""
    assert set(generated()["agent"]) == {"bypass", "bypass-worker"}


def test_bypass_worker_cannot_launch_further_subagents():
    """bypass から呼ぶ子。ask は allow になるが、子からさらに子は起動できない (task = subagent)。"""
    agent = generated()["agent"]["bypass-worker"]
    assert agent["mode"] == "subagent"
    assert agent["permission"] == {"task": "deny"}


def test_only_bypass_can_launch_the_bypass_worker():
    """★全体の permission で起動を deny し、bypass の task ``*`` allow だけがそれを上書きする。

    エージェントの規則は全体の後ろに付き、最後に一致した規則が勝つ (実測。
    build からは Permission denied、bypass からは起動できた)。
    """
    rules = generated()["permissions"]
    guard = {"action": "subagent", "resource": "bypass-worker", "effect": "deny"}
    assert guard in rules
    # primary の bypass 自体は、ほかから子として呼ばれることが無いので塞がない
    assert {"action": "subagent", "resource": "bypass", "effect": "deny"} not in rules
    assert rules.index(guard) == len(rules) - 1, "全体の規則の最後に置く"


@pytest.mark.parametrize(
    ("agent", "guarded"),
    [
        ({"bypass": True, "mode": "subagent"}, True),
        ({"bypass": True, "mode": "all"}, True),
        ({"bypass": True}, False),
        ({"bypass": True, "mode": "primary"}, False),
        ({"bypass": False, "mode": "subagent"}, False),
        ({"bypass": "yes", "mode": "subagent"}, False),
        # 全 allow を書いても印ではない (自動判定はしない)
        ({"permission": "allow", "mode": "subagent"}, False),
        ({"permission": {"*": "allow"}, "mode": "all"}, False),
        ({"mode": "subagent"}, False),
    ],
    ids=[
        "印のある子",
        "印のある両用",
        "印のある mode 無し",
        "印のある primary",
        "印が偽",
        "印が真偽値でない",
        "全 allow だけの子",
        "全 allow だけの両用",
        "印の無い子",
    ],
)
def test_subagent_guard_covers_only_marked_subagents(agent, guarded):
    common = {"opencode": {"agent": {"x": agent}}}
    assert bool(gen.opencode_subagent_guards(common)) is guarded
    assert (gen.build_opencode_guide({}, common)["guarded_subagents"] == ["x"]) is guarded


def test_guarded_subagents_are_named_in_the_rules():
    """plugin が起動元を検査する子の一覧。全体の deny と同じ名前を出す。"""
    guide = gen.build_opencode_guide({}, COMMON)
    assert guide["guarded_subagents"] == ["bypass-fleet-worker", "bypass-worker"]
    denied = [r["resource"] for r in gen.opencode_subagent_guards(COMMON)]
    assert guide["guarded_subagents"] == denied


@pytest.mark.parametrize(
    ("bypass", "mark"),
    [(True, True), (False, False), (None, False)],
    ids=["印あり", "印が偽", "印なし"],
)
def test_v2_agents_are_marked_by_bypass_only(bypass, mark):
    """V2 の ``agents`` も印だけで見分ける。印は opencode.json の agents に出ない。"""
    agent = {"description": "x", "mode": "subagent"}
    if bypass is not None:
        agent["bypass"] = bypass
    common = {"opencode": {"agents": {"x": agent}}}
    assert (gen.opencode_guarded_subagents(common) == ["x"]) is mark
    assert (gen.opencode_bypass_agents(common) == ["x"]) is mark
    assert "bypass" not in gen.merge_opencode_v2_agents({}, common)["x"]


def test_v2_bypass_mark_must_be_a_boolean():
    common = {"opencode": {"agents": {"x": {"description": "x", "bypass": "yes"}}}}
    with pytest.raises(ValueError, match="bypass"):
        gen.opencode_v2_agents(common)


@pytest.mark.parametrize("mode", ["all", "subagent"])
def test_bypass_stays_primary_over_existing_mode(mode):
    """★bypass を子として起動できると、モデルが自分で ask の確認を外せる。

    既存設定の ``mode`` は common.toml が宣言しないと残るので、``primary`` を明示して上書きする。
    """
    existing = {"agent": {"bypass": {"mode": mode}}}
    merged = gen.merge_opencode_config(existing, COMMON)
    assert merged["agent"]["bypass"]["mode"] == "primary"
    guards = [r for r in merged["permissions"] if r["action"] == "subagent"]
    assert {"action": "subagent", "resource": "bypass", "effect": "deny"} not in guards


def test_bypass_agents_in_common_declare_their_mode():
    """bypass のエージェントは mode を必ず宣言する。

    宣言しないと既存設定の mode が残り、子として起動できるかを common.toml だけで決められない。
    """
    declared = {**COMMON["opencode"]["agent"], **COMMON["opencode"]["agents"]}
    for name, agent in declared.items():
        if agent.get("bypass") is True:
            assert agent.get("mode") in ("primary", "subagent", "all"), name


def test_guide_plugin_is_registered_for_guarded_subagents_alone():
    """子の起動元の検査だけでも index.js が要る (隔離版も同じ)。"""
    common = {"opencode": {"agent": {"w": {"bypass": True, "mode": "subagent"}}}}
    assert gen.opencode_guide_server_needed(common, tui=True)
    assert gen.opencode_guide_server_needed(common, tui=False)
    assert gen.opencode_guide_plugin_path() in gen.merge_opencode_config({}, common)["plugins"]


# grep / glob は read の deny を迂回するので、結果を plugin 側で濾す。
# 判定パターンは read の deny glob から生成して単一ソースを保つ。
# see docs/research/opencode/permission/gaps.md
@pytest.mark.parametrize(
    ("path", "blocked"),
    [
        ("/home/u/.ssh/id_ed25519", True),
        ("/home/u/.aws/credentials", True),
        ("/srv/app/certs/server.pem", True),
        ("/home/u/proj/.env", True),
        ("/home/u/proj/id_rsa.bak", True),
        ("/home/u/.gnupg/x/y/z.gpg", True),
        ("/home/u/proj/README.md", False),
        ("/home/u/proj/environment.yml", False),
        ("/home/u/sshconfig", False),
    ],
)
def test_read_deny_regexes_match_absolute_paths(path, blocked):
    pats = [re.compile(p) for p in gen.build_opencode_guide({}, COMMON)["read_deny"]]
    assert any(p.search(path) for p in pats) is blocked, path


def test_read_deny_regexes_cover_every_glob():
    """``~/`` 始まりだけ 2 本になる (``~`` のままと展開済みの絶対パス)。"""
    globs = [str(g) for g in COMMON["file"]["read_deny_globs"]]
    expected = len(globs) + sum(1 for g in globs if g.startswith("~/"))
    assert len(gen.build_opencode_guide({}, COMMON)["read_deny"]) == expected


@pytest.mark.parametrize(
    "path",
    [
        "~/.claude.json",
        str(Path("~/.claude.json").expanduser()),
        str(Path("~/.config/opencode/service.json").expanduser()),
    ],
)
def test_read_deny_covers_expanded_home_paths(path):
    """``grep`` / ``glob`` の結果には**展開済みの絶対パス**しか載らない。

    ``~`` のままの正規表現だけだと一度も当たらず、保護が丸ごと抜ける。
    plugin は照合の前に ``\\`` を ``/`` へ揃えるので、ここでも揃える。
    """
    pats = [re.compile(p) for p in gen.build_opencode_guide({}, COMMON)["read_deny"]]
    normalized = path.replace("\\", "/")
    assert any(p.search(normalized) for p in pats), path


WINDOWS_GREP = "\n".join(
    [
        "Found 5 matches",
        "C:\\Users\\tester\\.ssh\\id_ed25519:",
        "  Line 1: secret",
        "C:/Users/tester/.claude.json:",
        "  Line 2: secret",
        "C:\\USERS\\TESTER\\.SSH\\config:",
        "  Line 3: secret",
        "\\\\server\\share\\.ssh\\known_hosts:",
        "  Line 4: secret",
        "C:\\Users\\tester\\proj\\README.md:",
        "  Line 5: ok",
    ]
)


def test_windows_grep_results_drop_protected_files(guide_js_windows):
    """Windows の grep は ``C:\\...`` の見出しで返る。区切り・大小文字・UNC を問わず伏せる。"""
    [out] = guide_js_windows("filterGrep", [WINDOWS_GREP])
    assert out["count"] == 1, out
    assert "secret" not in out["text"], out["text"]
    assert "README.md" in out["text"]
    assert out["text"].startswith("Found 1 matches")


def test_windows_glob_results_drop_protected_files(guide_js_windows):
    listing = "\n".join(
        [
            "C:\\Users\\tester\\.ssh\\id_rsa",
            "C:\\Users\\tester\\.claude.json",
            "C:\\Users\\tester\\proj\\certs\\server.key",
            "C:\\Users\\tester\\proj\\src\\main.py",
        ]
    )
    [out] = guide_js_windows("filterGlob", [listing])
    assert out["count"] == 1, out
    assert out["text"].strip() == "C:\\Users\\tester\\proj\\src\\main.py"


@pytest.mark.parametrize(
    "command",
    [
        "type C:\\Users\\tester\\.ssh\\id_ed25519",
        "Get-Content C:/Users/tester/.claude.json",
        "cat .ssh\\id_rsa",
    ],
)
def test_windows_commands_touching_protected_paths_are_detected(guide_js_windows, command):
    [token] = guide_js_windows("deniedPathIn", [command])
    assert token, command


def test_windows_ordinary_paths_are_left_alone(guide_js_windows):
    commands = ["type C:\\Users\\tester\\proj\\README.md", "dir src\\lib"]
    assert guide_js_windows("deniedPathIn", commands) == [None, None]


@pytest.mark.parametrize(
    ("glob", "matches", "misses"),
    [
        ("**/.ssh/**", ["/a/b/.ssh/c/d"], ["/a/b/ssh/c"]),
        ("**/*.pem", ["/a/b/c.pem"], ["/a/b/pem"]),
        (".env", ["/a/b/.env"], ["/a/b/.env.sample"]),
        ("**/id_rsa*", ["/a/id_rsa", "/a/id_rsa.pub"], ["/a/myid_rsa"]),
    ],
)
def test_glob_to_regex_keeps_slash_boundaries(glob, matches, misses):
    """``*`` は ``/`` を跨がない。跨ぐと無関係なパスまで落として作業が止まる。"""
    pat = re.compile(gen.glob_to_regex(glob))
    for path in matches:
        assert pat.search(path), f"{glob} が {path} に当たらない"
    for path in misses:
        assert not pat.search(path), f"{glob} が {path} に当たってしまう"


def test_bypass_agents_are_named_in_the_rules():
    assert gen.build_opencode_guide({}, COMMON)["bypass_agents"] == [
        "bypass",
        "bypass-fleet-worker",
        "bypass-worker",
    ]


def test_only_marked_agents_are_treated_as_bypass():
    """全 allow でも印が無ければ bypass 扱いにしない (印は ``bypass = true`` だけ)。"""
    common = {
        "opencode": {
            "agent": {
                "loose": {"permission": "allow"},
                "worker": {"bypass": True, "permission": {"task": "deny"}},
                "tight": {"permission": "ask"},
                "plain": {"description": "権限を触らない"},
            }
        }
    }
    assert gen.build_opencode_guide({}, common)["bypass_agents"] == ["worker"]


def test_bypass_mark_is_not_written_to_opencode_json():
    config = generated()
    for name in ("bypass", "bypass-worker"):
        assert "bypass" not in config["agent"][name]
    assert "bypass" not in config["agents"]["bypass-fleet-worker"]


# --- shell 出力の伏字化 (段階 2-C) ----------------------------------------
# 伏字規則は**可変長の後読み**を使うので Python の ``re`` では再現できない。
# 判定器そのものを node で動かす。
# see docs/research/opencode/permission/output-filter-and-subagents.md


def _copy_guide_helpers(work: Path) -> None:
    """index.js / tui.ts が相対 import する同じディレクトリのモジュールを写す。"""
    shutil.copy(ROOT / "home/dot_config/opencode/guide-plugin/commit-message.js", work)


def _load_guide_js(work: Path, rules: dict, *, windows: bool = False):
    """guide plugin を node で読み込み、内部の関数を呼べるようにする。

    ``windows=True`` なら ``process.platform`` を ``win32`` に差し替えてから読む
    (plugin は読み込み時に OS を見る)。
    """
    node = shutil.which("node")
    if not node:
        pytest.skip("node が無い (mise.toml の [tools] に宣言してある)")
    src = (ROOT / "home/dot_config/opencode/guide-plugin/index.js").read_text("utf-8")
    _copy_guide_helpers(work)
    prelude = 'Object.defineProperty(process, "platform", { value: "win32" })\n' if windows else ""
    exports = "\nexport { redact, deniedPathIn, filterGrep, filterGlob }\n"
    (work / "mod.mjs").write_text(prelude + src + exports, "utf-8")
    (work / "rules.json").write_text(json.dumps(rules), "utf-8")
    (work / "run.mjs").write_text(
        "import * as m from './mod.mjs'\n"
        "const [fn, args] = JSON.parse(process.argv[2])\n"
        "console.log(JSON.stringify(args.map((a) => m[fn](a))))\n",
        "utf-8",
    )

    def call(fn: str, args: list[str]) -> list:
        done = subprocess.run(
            [node, str(work / "run.mjs"), json.dumps([fn, args])],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True,
        )
        return json.loads(done.stdout)

    return call


@pytest.mark.parametrize(("isolated", "expected"), [(False, True), (True, False)])
def test_isolated_session_does_not_build_the_describer(tmp_path, isolated, expected):
    """隔離版 (OCS_ISOLATED=1) は説明の生成 (モデルの呼び出し) を止める。"""
    node = shutil.which("node")
    if not node:
        pytest.skip("node が無い (mise.toml の [tools] に宣言してある)")
    src = (ROOT / "home/dot_config/opencode/guide-plugin/index.js").read_text("utf-8")
    _copy_guide_helpers(tmp_path)
    (tmp_path / "mod.mjs").write_text(src + "\nexport { describer }\n", "utf-8")
    rules = gen.build_opencode_guide({}, COMMON)
    assert rules.get("ask_description"), "前提: 説明の生成が有効"
    (tmp_path / "rules.json").write_text(json.dumps(rules), "utf-8")
    (tmp_path / "run.mjs").write_text(
        "import { describer } from './mod.mjs'\n"
        "console.log(JSON.stringify(describer({}) !== null))\n",
        "utf-8",
    )
    env = {k: v for k, v in os.environ.items() if k != "OCS_ISOLATED"}
    if isolated:
        env["OCS_ISOLATED"] = "1"
    done = subprocess.run(
        [node, str(tmp_path / "run.mjs")],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        check=True,
    )
    assert json.loads(done.stdout) is expected


@pytest.fixture(scope="module")
def guide_js(tmp_path_factory):
    work = tmp_path_factory.mktemp("guide-js")
    return _load_guide_js(work, gen.build_opencode_guide({}, COMMON))


def _run_hooks(work: Path, rules: dict | str | None, calls: list[list]) -> list[dict]:
    """plugin の ``setup`` を偽の ctx で走らせ、``[hook 名, event]`` を順に渡して event を返す。

    ``rules`` が文字列ならそのまま ``rules.json`` に書き、None なら置かない。
    """
    node = shutil.which("node")
    if not node:
        pytest.skip("node が無い (mise.toml の [tools] に宣言してある)")
    src = (ROOT / "home/dot_config/opencode/guide-plugin/index.js").read_text("utf-8")
    _copy_guide_helpers(work)
    (work / "mod.mjs").write_text(src, "utf-8")
    if rules is not None:
        text = rules if isinstance(rules, str) else json.dumps(rules)
        (work / "rules.json").write_text(text, "utf-8")
    (work / "run.mjs").write_text(
        "import plugin from './mod.mjs'\n"
        "const hooks = {}\n"
        "const hook = (name, fn) => { hooks[name] = fn }\n"
        "await plugin.setup({ tool: { hook }, permission: { hook } })\n"
        "const out = []\n"
        "for (const [name, e] of JSON.parse(process.argv[2])) {\n"
        "  await hooks[name](e)\n"
        "  out.push(e)\n"
        "}\n"
        "console.log(JSON.stringify(out))\n",
        "utf-8",
    )
    env = {k: v for k, v in os.environ.items() if k != "OCS_ISOLATED"}
    done = subprocess.run(
        [node, str(work / "run.mjs"), json.dumps(calls)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        check=True,
    )
    return json.loads(done.stdout)


def _evaluate(work: Path, rules: dict | str | None, events: list[dict]) -> list[dict]:
    """``permission.evaluate`` へ events を順に渡し、effect と message を返す。"""
    out = _run_hooks(work, rules, [["evaluate", e] for e in events])
    return [{"effect": e["effect"], "message": e.get("message")} for e in out]


def _launch(agent: str | None, child: str, effect: str) -> dict:
    event = {"action": "subagent", "resources": [child], "effect": effect}
    if agent is not None:
        event["agent"] = agent
    return event


# ★全体の deny はエージェント個別の allow (task = "allow" など) に上書きされる。
# そのとき OpenCode が plugin へ渡す effect は allow になるので、allow / ask の両方で見る。
@pytest.mark.parametrize("effect", ["allow", "ask"])
@pytest.mark.parametrize("agent", ["build", "mine", None], ids=["build", "手で足した", "名前無し"])
def test_plugin_denies_the_bypass_worker_outside_bypass(tmp_path, agent, effect):
    rules = gen.build_opencode_guide({}, COMMON)
    [out] = _evaluate(tmp_path, rules, [_launch(agent, "bypass-worker", effect)])
    assert out["effect"] == "deny"
    assert "bypass-worker" in out["message"]


def test_plugin_lets_bypass_launch_the_bypass_worker(tmp_path):
    rules = gen.build_opencode_guide({}, COMMON)
    [out] = _evaluate(tmp_path, rules, [_launch("bypass", "bypass-worker", "allow")])
    assert out == {"effect": "allow", "message": None}


@pytest.mark.parametrize("effect", ["allow", "ask"])
def test_plugin_leaves_other_subagents_alone(tmp_path, effect):
    rules = gen.build_opencode_guide({}, COMMON)
    [out] = _evaluate(tmp_path, rules, [_launch("build", "explore", effect)])
    assert out == {"effect": effect, "message": None}


def _without(key: str) -> dict:
    rules = gen.build_opencode_guide({}, COMMON)
    del rules[key]
    return rules


def _broken_guide() -> dict:
    rules = gen.build_opencode_guide({}, COMMON)
    rules["guide"] = [{"pattern": "(", "message": "壊れた正規表現"}]
    return rules


# ★plugin のロードに失敗すると起動元の検査ごと消える (上流は fail-open)。
# see docs/spec/agent-config-generation.md#rulesjson-が使えないとき
@pytest.mark.parametrize(
    "rules",
    [None, "{not json", "[]", _without("guarded_subagents"), _without("bypass_agents")],
    ids=["無い", "JSON でない", "配列", "guarded_subagents が無い", "bypass_agents が無い"],
)
def test_plugin_leaves_subagents_alone_when_rules_are_unusable(tmp_path, rules):
    """一覧が読めなくても plugin はロードでき、起動の effect は変えない (止めずに警告する)。"""
    events = [
        _launch("build", "bypass-worker", "allow"),
        _launch("bypass", "bypass-worker", "allow"),
        _launch("build", "explore", "ask"),
    ]
    out = _evaluate(tmp_path, rules, events)
    assert out == [{"effect": e["effect"], "message": None} for e in events]


def test_broken_guide_rules_do_not_take_the_subagent_guard_down(tmp_path):
    out = _evaluate(
        tmp_path,
        _broken_guide(),
        [_launch("build", "bypass-worker", "allow"), _launch("bypass", "bypass-worker", "allow")],
    )
    assert [o["effect"] for o in out] == ["deny", "allow"]


def _grep(agent: str = "build") -> dict:
    text = "Found 1 matches\n/home/u/proj/README.md:\n  Line 1: ok"
    return {"tool": "grep", "agent": agent, "result": {"content": [{"type": "text", "text": text}]}}


def _glob(agent: str = "build") -> dict:
    text = "/home/u/proj/README.md"
    return {"tool": "glob", "agent": agent, "result": {"content": [{"type": "text", "text": text}]}}


_MISSING = object()


def _with_read_deny(value) -> dict:
    rules = gen.build_opencode_guide({}, COMMON)
    if value is _MISSING:
        del rules["read_deny"]
    else:
        rules["read_deny"] = value
    return rules


@pytest.mark.parametrize("tool", [_grep, _glob], ids=["grep", "glob"])
@pytest.mark.parametrize(
    "value",
    [_MISSING, None, "(?:^|/)\\.env$", {"x": 1}, [1], [None], ["(?:^|/)\\.env$", 2]],
    ids=["無い", "null", "文字列", "オブジェクト", "数値の要素", "null の要素", "混在"],
)
def test_malformed_read_deny_withholds_results(tmp_path, tool, value):
    """★生成側は read_deny を必ず出す。形が違えば壊れた rules として結果を伏せる。"""
    [e] = _run_hooks(tmp_path, _with_read_deny(value), [["execute.after", tool()]])
    text = e["result"]["content"][0]["text"]
    assert "README.md" not in text
    assert "rules.json" in text
    assert "opencode service restart" in text


@pytest.mark.parametrize("tool", [_grep, _glob], ids=["grep", "glob"])
def test_empty_read_deny_keeps_results(tmp_path, tool):
    """明示的な空の配列は「濾すものが無い」で、壊れた扱いにしない。"""
    [e] = _run_hooks(tmp_path, _with_read_deny([]), [["execute.after", tool()]])
    assert "README.md" in e["result"]["content"][0]["text"]


def test_grep_results_are_withheld_when_the_read_filter_is_broken(tmp_path):
    """結果フィルタは grep / glob で唯一の保護なので、組めなければ結果を伏せる。"""
    rules = gen.build_opencode_guide({}, COMMON)
    rules["read_deny"] = ["("]
    [e] = _run_hooks(tmp_path, rules, [["execute.after", _grep()]])
    text = e["result"]["content"][0]["text"]
    assert "README.md" not in text
    assert "rules.json" in text


@pytest.mark.parametrize(
    "rules", [_broken_guide(), None], ids=["誘導が壊れている", "rules.json が無い"]
)
def test_unrelated_broken_sections_leave_the_read_filter_alone(tmp_path, rules):
    """誘導が壊れても結果フィルタは組める。rules.json ごと読めなければ結果を伏せる。"""
    [e] = _run_hooks(tmp_path, rules, [["execute.after", _grep()]])
    kept = "README.md" in e["result"]["content"][0]["text"]
    assert kept is (rules is not None)


def _result(tool: str, agent: str, text: str, id_: str = "1") -> dict:
    return {"tool": tool, "agent": agent, "id": id_, "result": {"content": [{"text": text}]}}


@pytest.mark.parametrize("agent", ["build", "bypass", "bypass-worker", "bypass-fleet-worker"])
def test_read_filter_applies_to_bypass_agents_too(tmp_path, agent):
    """★bypass でも grep / glob の結果から保護対象を落とす (素通りさせない)。"""
    grep = "Found 2 matches\n/home/u/p/.env:\n  Line 1: SECRET=x\n/home/u/p/a.py:\n  Line 2: ok"
    glob = "/home/u/p/.env.local\n/home/u/p/a.py"
    rules = gen.build_opencode_guide({}, COMMON)
    out = _run_hooks(
        tmp_path,
        rules,
        [
            ["execute.after", _result("grep", agent, grep)],
            ["execute.after", _result("glob", agent, glob)],
        ],
    )
    grep_text = out[0]["result"]["content"][0]["text"]
    glob_text = out[1]["result"]["content"][0]["text"]
    assert "SECRET" not in grep_text and "a.py" in grep_text
    assert ".env" not in glob_text and "a.py" in glob_text


def test_read_filter_keeps_dotenv_examples(tmp_path):
    """``.env.example`` などは `.env.*` の deny の例外。別の deny に当たるものは伏せる。"""
    glob = "\n".join(
        [
            "/home/u/p/.env.example",
            "/home/u/p/.env.local",
            "/home/u/.ssh/.env.example",
            "/home/u/p/secrets/.env.sample",
        ]
    )
    rules = gen.build_opencode_guide({}, COMMON)
    [out] = _run_hooks(tmp_path, rules, [["execute.after", _result("glob", "bypass", glob)]])
    assert out["result"]["content"][0]["text"].strip() == "/home/u/p/.env.example"


@pytest.mark.parametrize("agent", ["build", "bypass"])
def test_shell_output_is_redacted_for_bypass_too(tmp_path, agent):
    """★bypass でも shell 出力の伏字化 (秘密の形・保護パスを触ったコマンドの出力) が効く。"""
    rules = gen.build_opencode_guide({}, COMMON)
    before = {"tool": "shell", "agent": agent, "id": "1", "input": {"command": "env"}}
    out = _run_hooks(
        tmp_path,
        rules,
        [
            ["execute.before", before],
            ["execute.after", _result("shell", agent, "GITHUB_TOKEN=abcdefghijklmnopqrstuvwx")],
            [
                "execute.before",
                {**before, "id": "2", "input": {"command": "sed p ~/.aws/credentials"}},
            ],
            ["execute.after", _result("shell", agent, "line", "2")],
        ],
    )
    assert "[伏字:" in out[1]["result"]["content"][0]["text"]
    assert "保護対象のパス" in out[3]["result"]["content"][0]["text"]


def test_shell_output_for_dotenv_example_is_not_withheld(tmp_path):
    rules = gen.build_opencode_guide({}, COMMON)
    cases = [
        ("wc -l app/.env.example", "3 .env.example", True),
        ("wc -l ~/.ssh/.env.example", "3 .env.example", False),
        ("wc -l app/.env.local", "3 .env.local", False),
    ]
    calls = []
    for i, (cmd, text, _) in enumerate(cases):
        before = {"tool": "shell", "agent": "bypass", "id": str(i), "input": {"command": cmd}}
        calls += [
            ["execute.before", before],
            ["execute.after", _result("shell", "bypass", text, str(i))],
        ]
    out = _run_hooks(tmp_path, rules, calls)
    for i, (cmd, text, kept) in enumerate(cases):
        got = out[2 * i + 1]["result"]["content"][0]["text"]
        assert (got == text) is kept, cmd


WINDOWS_HOME = "C:\\Users\\tester"


@pytest.fixture(scope="module")
def guide_js_windows(tmp_path_factory):
    """Windows の機械で生成・実行したときの plugin。ホームは C:\\Users\\tester。"""
    work = tmp_path_factory.mktemp("guide-js-win")
    with mock.patch.object(gen, "expand_user", lambda p: p.replace("~", WINDOWS_HOME, 1)):
        rules = gen.build_opencode_guide({}, COMMON)
    return _load_guide_js(work, rules, windows=True)


SECRET_SHAPES = [
    "-----BEGIN OPENSSH PRIVATE KEY-----\nb3Blb\n-----END OPENSSH PRIVATE KEY-----",
    "AKIAIOSFODNN7EXAMPLE",
    "ghp_" + "a" * 36,
    "xoxb-1234567890-abcdefgh",
    "sk-" + "A1b2C3d4" * 4,
    "GITHUB_TOKEN=abcdefghijklmnopqrstuvwx",
    "password: 'hunter2000'",
    # ★高エントロピーな値を直書きしない。gitleaks が拾う。
    "aws_secret_access_key = " + "SAMPLE" * 4,
]

# ★ここを誤爆させると、shell 経由で読んだ**コード**が読めなくなる。
# 代入形の規則を緩めたら必ずここへ例を足す。
INNOCENT_TEXT = [
    "const token = getToken()",
    'api_key = os.environ["API_KEY"]',
    "grep -rn token src/",
    "commit abc1234 fix: トークン更新の失敗を直す",
    "password = None",
]


def test_secret_shapes_are_redacted(guide_js):
    for text, out in zip(SECRET_SHAPES, guide_js("redact", SECRET_SHAPES), strict=True):
        assert "[伏字:" in out, text


def test_ordinary_text_is_left_alone(guide_js):
    for text, out in zip(INNOCENT_TEXT, guide_js("redact", INNOCENT_TEXT), strict=True):
        assert out == text


# 出力全体を伏せる判定。コマンド中の「パスらしい語」だけを見る。
HOME = str(Path("~").expanduser())
DENIED_COMMANDS = [
    "sed -n 1p ~/.aws/credentials",
    "awk 'NR==1' /home/u/.ssh/id_ed25519",
    f"python3 -c 'print(open(\"{HOME}/.config/opencode/service.json\").read())'",
    "cat /home/u/proj/.env",
]
# ★検索語としての secret / password を巻き込まないこと。巻き込むと
# 無関係なコマンドの出力が丸ごと消える。
ALLOWED_COMMANDS = [
    "grep -rn secret docs/",
    "git log -- docs/spec/secret-handling.md",
    "wc -l README.md",
    # 保護パス名を「文章として」書いた形。実地で踏んだ誤爆。
    "git commit -m 'docs: ~/.claude.json を read deny に足す' 2>&1 | grep -E x",
]


def test_commands_touching_protected_paths_are_detected(guide_js):
    for cmd, hit in zip(DENIED_COMMANDS, guide_js("deniedPathIn", DENIED_COMMANDS), strict=True):
        assert hit, cmd


def test_ordinary_commands_are_not_detected(guide_js):
    for cmd, hit in zip(ALLOWED_COMMANDS, guide_js("deniedPathIn", ALLOWED_COMMANDS), strict=True):
        assert hit is None, f"{cmd} -> {hit}"


def test_the_unless_hole_is_known(guide_js):
    """除外規則はコマンド全体に当たるので、連結すると素通りする。

    伏字化は境界ではない。この形は誘導 (``cat`` の deny) が受け持つ。
    """
    cmd = "git commit -m 'x' && cat ~/.aws/credentials"
    assert guide_js("deniedPathIn", [cmd])[0] is None
    assert _guided(cmd), "誘導で止まらないなら穴が二重になる"


def test_substring_globs_are_excluded_from_path_matching():
    """``**/*secret*`` のような部分一致は出力全体を伏せる判定に使わない。"""
    deny = gen.build_opencode_guide({}, COMMON)["redact"]["deny_path"]
    assert all(not re.search(p, "docs/spec/secret-handling.md") for p in deny)
    assert any(re.search(p, "/home/u/.ssh/id_ed25519") for p in deny)


# --- 誘導 plugin ---------------------------------------------------------
# 明示指定は絶対パスのディレクトリでないと解決されない。相対でも ``~`` でも
# 単一ファイルでも、OpenCode は**黙って無視する**。
# see docs/research/opencode/plugin/loading.md


def test_guide_plugin_is_registered_as_absolute_directory():
    entries = generated()["plugins"]
    assert gen.opencode_guide_plugin_path() in entries
    for entry in entries:
        assert not entry.startswith("~"), f"{entry}: ~ は展開されない"


def test_guide_plugin_directory_name_is_not_auto_discovered():
    """``plugin`` / ``plugins`` は設定ディレクトリ直下で自動探索される。

    その名前にすると明示指定と合わせて二重にロードされる。
    """
    assert Path(gen.OPENCODE_GUIDE_PLUGIN).name not in {"plugin", "plugins"}


def test_guide_plugin_files_exist():
    source = ROOT / "home/dot_config/opencode/guide-plugin"
    assert (source / "index.js").is_file()
    assert (source / "commit-message.js").is_file()
    assert (source / "modify_rules.json.py.tmpl").is_file()


def test_plugins_not_declared_in_common_are_kept():
    existing = {"plugins": ["opencode-acme-plugin"]}
    merged = gen.merge_opencode_config(existing, COMMON)["plugins"]
    assert merged[0] == "opencode-acme-plugin"
    assert gen.opencode_guide_plugin_path() in merged


def test_guide_plugin_is_not_registered_twice():
    existing = {"plugins": [gen.opencode_guide_plugin_path()]}
    merged = gen.merge_opencode_config(existing, COMMON)["plugins"]
    assert merged.count(gen.opencode_guide_plugin_path()) == 1


def test_checkpoint_plugin_is_always_registered():
    """★圧縮は設定と無関係に起きるので、常に読み込む。

    2026-09-25 に checkpoint を OpenCode 専用へ寄せた。圧縮の捕捉は
    ``session.hook("compaction")``、復帰注入は ``session.hook("context")``
    で、どちらもこの plugin が担う。載っていないと**圧縮を跨いだ時点で
    文脈が失われる**。

    see docs/change/closed/0001-compaction-context-handover.md
    """
    merged = gen.merge_opencode_config({}, COMMON)["plugins"]
    assert gen.opencode_checkpoint_plugin_path() in merged


def test_checkpoint_plugin_is_not_registered_twice():
    existing = {"plugins": [gen.opencode_checkpoint_plugin_path()]}
    merged = gen.merge_opencode_config(existing, COMMON)["plugins"]
    assert merged.count(gen.opencode_checkpoint_plugin_path()) == 1


def test_the_skills_directory_is_always_registered():
    """★明示しないと skill が 1 つも読まれない。

    公式ドキュメントは ``~/.config/opencode/skills`` を Global の探索先として
    挙げるが、v2.0.14 は**そこを走査しない**（実測。監視対象は
    ``~/.opencode/skills`` 側で、``~/.config/opencode/skills`` に置いた skill は
    ``/api/skill`` に現れない）。``skills`` 設定で名指しすると登録される。

    see docs/change/closed/0001-compaction-context-handover.md
    """
    merged = gen.merge_opencode_config({}, COMMON)["skills"]
    assert gen.opencode_skills_path() in merged


def test_the_skills_directory_is_not_registered_twice():
    existing = {"skills": [gen.opencode_skills_path()]}
    merged = gen.merge_opencode_config(existing, COMMON)["skills"]
    assert merged.count(gen.opencode_skills_path()) == 1


def test_skills_not_declared_in_common_are_kept():
    existing = {"skills": ["~/shared/opencode-skills"]}
    merged = gen.merge_opencode_config(existing, COMMON)["skills"]
    assert merged[0] == "~/shared/opencode-skills"
    assert gen.opencode_skills_path() in merged


@pytest.mark.skipif(sys.platform != "linux", reason="ocs の境界は Linux 専用")
def test_checkpoint_plugin_is_readable_inside_the_boundary(tmp_path):
    """★隔離版でも圧縮は起きる。

    ``ocs`` は ``~/.config/opencode`` を丸ごとは開けない (``service.json`` がある)。
    plugin 本体とスキルの CLI を名指しで開けていないと、**境界の内側でだけ**
    checkpoint が動かない。
    """
    runtime = tmp_path / "fence"
    runtime.write_text("", "utf-8")
    common = {
        **COMMON,
        "opencode": {
            **COMMON["opencode"],
            "sandbox": {**COMMON["opencode"]["sandbox"], "runtime_path": str(runtime)},
        },
    }
    sandbox = gen.opencode_sandbox(common)
    assert gen.opencode_checkpoint_plugin_path() in sandbox["plugins"]

    readable = sandbox["base"]["read"]
    for needed in (
        gen.opencode_checkpoint_plugin_path(),
        os.path.expanduser("~/.config/opencode/skills"),
    ):
        assert needed in readable, f"{needed} が境界内から読めない"


def _guided(command: str) -> dict[str, str] | None:
    """plugin と同じ判定。先に当たった規則が勝ち、``unless`` は見送る。

    see home/dot_config/opencode/guide-plugin/index.js
    """
    for rule in gen.build_opencode_guide({}, COMMON)["guide"]:
        if not re.search(rule["pattern"], command):
            continue
        if rule.get("unless") and re.search(rule["unless"], command):
            continue
        return rule
    return None


def test_guide_rules_are_generated():
    rules_json = gen.build_opencode_guide({}, COMMON)["guide"]
    assert rules_json, "誘導規則が 1 件も無い"
    for rule in rules_json:
        assert set(rule) <= {"pattern", "message", "unless", "early"}
        re.compile(rule["pattern"])
        if "unless" in rule:
            re.compile(rule["unless"])


def test_cd_is_guided_to_workdir():
    """最も件数の多い誘導。実機で deny とメッセージの到達を確認済み。

    区切りの後ろの ``cd`` も見る。先頭だけを見る形では実履歴で 15 件
    取りこぼした。
    see docs/change/0002-opencode-ask-by-default.md
    """
    for command in ("cd sub && cat x", 'ls -la; echo "---"; cd /tmp && ls'):
        hit = _guided(command)
        assert hit is not None, command
        assert "workdir" in hit["message"], command


# 読み取りは read ツールへ寄せる。deny が効かない経路から効く経路へ移すのが
# 目的で、確認回数は副次効果。
# see docs/change/0002-opencode-ask-by-default.md 「段階 2」
@pytest.mark.parametrize(
    "command",
    ["cat foo.txt", "head -20 a.py", "tail -n 5 log", "sed -n '1,20p' f.md"],
)
def test_reads_are_guided_to_the_read_tool(command):
    hit = _guided(command)
    assert hit is not None, command
    assert "read" in hit["message"], command


# read で代替できない形まで止めると作業が止まるだけになる。
@pytest.mark.parametrize(
    "command",
    [
        "cat a.txt | wc -l",  # パイプの途中
        "cat a b > c",  # 結合してリダイレクト
        "head -c 100 bin",  # バイト数指定
        "tail -f app.log",  # 追尾
        "sed -i 's/a/b/' f",  # 置換 (読み取りではない)
        "grep -n foo *.py",  # 別の規則の領分
    ],
)
def test_reads_that_have_no_tool_equivalent_are_left_alone(command):
    assert _guided(command) is None, command


# ヒアドキュメントは write ツールへ寄せる。目的は確認 1 回あたりの負担で、
# 実履歴ではヒアドキュメント付きが 177 件・総文字数の 46.9% を占めていた。
# 保護にもなる: python3 - <<PY で書く経路には edit の deny が効かない。
# see docs/change/0002-opencode-ask-by-default.md 「段階 3」
@pytest.mark.parametrize(
    "command",
    [
        "python3 - <<'PY'\nprint(1)\nPY",
        "mise exec -- python3 - <<PY\nimport os\nPY",
        "cat > a.txt <<'EOF'\nx\nEOF",
        "tee -a log <<EOF\nx\nEOF",
        "sqlite3 db.sqlite <<-SQL\nselect 1;\nSQL",
    ],
)
def test_heredocs_are_guided_to_the_write_tool(command):
    hit = _guided(command)
    assert hit is not None, command
    assert "write" in hit["message"], command


# ★`<<<` は here-string で 1 行。終端行も本文も無いので write の出番がない。
# ★末尾の改行を要求しないと、クォート内の `<<` まで当たる。
@pytest.mark.parametrize(
    "command",
    [
        "grep -f - <<< 'pattern'",
        "wc -l < README.md",
        "echo 'a << b'",
        "git log --oneline -3",
    ],
)
def test_here_strings_and_quoted_markers_are_left_alone(command):
    assert _guided(command) is None, command


def test_heredocs_written_as_prose_are_left_alone():
    """保護対象の綴りを**文章として**書いたときの誤爆を外す。

    実地で踏んだ。コミットメッセージにヒアドキュメントの例を書いただけで
    deny され、コミットできなくなった。伏字化の ``deny_path_unless`` と
    同じ型・同じ割り切りで、連結した形は素通りする。
    """
    prose = "git commit -m 'feat: python3 - <<PY をやめる\n\n- 理由\n'"
    assert _guided(prose) is None
    # 連結すると素通りする。これは承知の穴。
    assert _guided("git commit -m x && cat > f <<EOF\ny\nEOF") is None


def test_separator_echo_is_not_guided():
    """区切り用途の ``echo`` は誘導しない。

    確認が 1 件も減らないうえ、deny は 1 往復を捨てさせるので差し引き
    マイナスだった（実履歴 466 呼び出しで実測）。
    see docs/change/0002-opencode-ask-by-default.md 「誘導（優先度を下げる）」
    """
    rules_json = gen.build_opencode_guide({}, COMMON)["guide"]
    assert not [r for r in rules_json if re.search(r["pattern"], 'echo "--- env ---"')]


@pytest.mark.parametrize("broken", [{"pattern": "x"}, {"message": "y"}, {}])
def test_guide_rule_without_pattern_or_message_is_rejected(broken: dict):
    common = copy.deepcopy(COMMON)
    common["opencode"]["shell"]["guide"] = [broken]
    with pytest.raises(SystemExit):
        gen.build_opencode_guide({}, common)


def test_guide_target_is_fully_generated():
    """壊れた rules.json でも apply でやり直せるようにする。"""
    assert "opencode-guide" in gen.TARGETS
    assert "opencode-guide" in gen.FULL_GENERATION_TARGETS


# --- 確認画面の説明 (CHG-0003) -------------------------------------------
# 表示は TUI plugin の toast。権限ダイアログには出せない。
# see docs/research/opencode/plugin/ask-description.md


def test_ask_description_is_generated():
    ask = gen.build_opencode_guide({}, COMMON)["ask_description"]
    assert ask["models"], "モデル候補が空"
    assert ask["min_command_length"] > 0
    assert ask["timeout_ms"] > 0
    assert ask["duration_ms"] > 0


def test_ask_description_is_not_locked_to_one_backend():
    """Bedrock と GitHub Copilot の両方を予定しているので決め打ちしない。"""
    models = gen.build_opencode_guide({}, COMMON)["ask_description"]["models"]
    providers = {ref.split("/", 1)[0] for ref in models}
    assert len(providers) >= 2, f"provider が 1 つしかない: {providers}"


def test_ask_description_can_be_disabled():
    common = copy.deepcopy(COMMON)
    common["opencode"]["ask_description"]["enabled"] = False
    assert "ask_description" not in gen.build_opencode_guide({}, common)


def test_ask_description_without_models_is_rejected():
    common = copy.deepcopy(COMMON)
    common["opencode"]["ask_description"]["models"] = []
    with pytest.raises(SystemExit):
        gen.build_opencode_guide({}, common)


def test_tui_plugin_file_exists():
    """表示側。これが無いと説明は生成されても誰も見ない。"""
    assert (ROOT / "home/dot_config/opencode/guide-plugin/tui.ts").is_file()


# TUI 側 plugin は cli.json からしか読まれない (opencode.json の plugins は
# サーバ側だけ)。実測で package.json の exports を足しても変わらなかった。
# see docs/research/opencode/plugin/loading.md
def test_cli_json_registers_the_plugin():
    cli = gen.merge_opencode_cli({}, COMMON)
    assert gen.opencode_guide_plugin_path() in cli["plugins"]


def test_cli_json_keeps_user_settings():
    existing = {"attention": {"enabled": True}, "plugins": ["opencode-acme"]}
    cli = gen.merge_opencode_cli(existing, COMMON)
    assert cli["attention"] == {"enabled": True}
    assert cli["plugins"][0] == "opencode-acme"
    assert cli["plugins"].count(gen.opencode_guide_plugin_path()) == 1


def test_cli_json_is_not_registered_twice():
    existing = {"plugins": [gen.opencode_guide_plugin_path()]}
    cli = gen.merge_opencode_cli(existing, COMMON)
    assert cli["plugins"].count(gen.opencode_guide_plugin_path()) == 1


# Windows と WSL の常駐サービスが同じポートだと 127.0.0.1 で衝突し、
# 後から起動した側が「Timed out waiting for the background service」で止まる。
# see docs/spec/agent-config-generation.md#常駐サービスのポート
SERVICE_MODIFIER = ROOT / "home/dot_config/opencode/modify_private_service.json.py.tmpl"


def test_service_target_is_registered_and_wired():
    assert gen.TARGETS["opencode-service"] is gen.merge_opencode_service
    source = SERVICE_MODIFIER.read_text(encoding="utf-8")
    assert '"target" "opencode-service"' in source


def test_service_sets_only_the_port_and_keeps_the_password():
    existing = {"password": "secret", "hostname": "127.0.0.1"}
    common = {"opencode": {"service": {"port": 4098}}}
    assert gen.merge_opencode_service(existing, common) == {
        "password": "secret",
        "hostname": "127.0.0.1",
        "port": 4098,
    }


def test_service_is_left_alone_without_a_declaration():
    existing = {"password": "secret", "port": 4097}
    common = copy.deepcopy(COMMON)
    common["opencode"].pop("service", None)  # Windows 描画では宣言が入る
    assert gen.merge_opencode_service(existing, common) == existing


@pytest.mark.parametrize("port", [0, 65536, "4098", True])
def test_service_rejects_an_invalid_port(port):
    with pytest.raises(ValueError, match="port"):
        gen.merge_opencode_service({}, {"opencode": {"service": {"port": port}}})


def test_service_rejects_unknown_keys():
    with pytest.raises(ValueError, match="未知のキー"):
        gen.merge_opencode_service({}, {"opencode": {"service": {"prot": 4098}}})


def _render_common_for_os(os_name: str) -> dict:
    """OS を明示して common.toml を描画する (実行 OS に依存しない)。"""
    chezmoi = shutil.which("chezmoi")
    if chezmoi is None:
        pytest.skip("chezmoi is not installed")
    context = json.dumps(json.dumps({"chezmoi": {"os": os_name, "username": "applejxd"}}))
    template = (
        f"{{{{ with {context} | fromJson }}}}"
        '{{ includeTemplate "dot_config/agents/common.toml.tmpl" . }}{{ end }}'
    )
    result = subprocess.run(
        [chezmoi, "--source", str(ROOT), "execute-template", template],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return tomllib.loads(result.stdout)


def test_service_port_differs_from_wsl_only_on_windows():
    assert _render_common_for_os("windows")["opencode"]["service"]["port"] == 4098
    assert "service" not in _render_common_for_os("linux")["opencode"]


# guide plugin の各役割を 1 つだけ有効にした common。
# index.js はどれか 1 つでも有効なら要り、tui.ts は説明の toast (ask_description) にだけ要る。
# see docs/spec/agent-config-generation.md#plugin-層-guide-plugin
GUIDE_FEATURES = {
    "guide": {"opencode": {"shell": {"guide": [{"pattern": "^cat ", "message": "read へ"}]}}},
    "read_filter": {"file": {"read_deny_globs": ["**/.env"]}},
    "redact": {
        "opencode": {"redact": {"enabled": True, "rule": [{"name": "k", "pattern": "AKIA"}]}}
    },
    "ask_description": {"opencode": {"ask_description": {"enabled": True, "models": ["p/m"]}}},
}


def test_guide_plugin_is_not_registered_without_any_role():
    config = gen.merge_opencode_config({}, {})
    cli = gen.merge_opencode_cli({}, {})
    assert gen.opencode_guide_plugin_path() not in config["plugins"]
    assert "plugins" not in cli


@pytest.mark.parametrize("feature", sorted(GUIDE_FEATURES))
def test_guide_plugin_is_registered_for_each_role(feature):
    """どの役割を 1 つだけ有効にしても index.js は読まれる (redact だけでも伏字化が要る)。"""
    common = GUIDE_FEATURES[feature]
    assert gen.opencode_guide_plugin_path() in gen.merge_opencode_config({}, common)["plugins"]


@pytest.mark.parametrize("feature", sorted(GUIDE_FEATURES))
def test_tui_plugin_is_registered_only_for_the_toast(feature):
    """tui.ts の役割は説明の toast だけ。他の役割で cli.json へ載せても何もしない。"""
    plugins = gen.merge_opencode_cli({}, GUIDE_FEATURES[feature]).get("plugins") or []
    registered = gen.opencode_guide_plugin_path() in plugins
    assert registered is (feature == "ask_description")


def test_tui_plugin_is_unregistered_when_the_toast_is_disabled():
    common = copy.deepcopy(COMMON)
    common["opencode"]["ask_description"]["enabled"] = False
    existing = {"plugins": ["opencode-acme", gen.opencode_guide_plugin_path()]}
    assert gen.merge_opencode_cli(existing, common)["plugins"] == ["opencode-acme"]


def _tui_toasts(work: Path, rules: dict | None) -> list[dict]:
    """tui.ts を node で読み込み、説明付きの ``permission.asked`` で出た toast を返す。"""
    node = shutil.which("node")
    if not node:
        pytest.skip("node が無い (mise.toml の [tools] に宣言してある)")
    src = (ROOT / "home/dot_config/opencode/guide-plugin/tui.ts").read_text("utf-8")
    (work / "tui.mjs").write_text(src, "utf-8")
    _copy_guide_helpers(work)
    # @opentui/solid は本体が解決する。toast だけを見るので中身は空でよい。
    stub = work / "node_modules/@opentui/solid"
    stub.mkdir(parents=True, exist_ok=True)
    (stub / "package.json").write_text(
        '{"name":"@opentui/solid","type":"module","main":"index.js"}', "utf-8"
    )
    (stub / "index.js").write_text(
        "export const createElement = () => ({})\n"
        "export const setProp = () => {}\n"
        "export const insert = () => {}\n",
        "utf-8",
    )
    if rules is not None:
        (work / "rules.json").write_text(json.dumps(rules), "utf-8")
    (work / "run.mjs").write_text(
        "import plugin from './tui.mjs'\n"
        "const toasts = []\n"
        "const handlers = []\n"
        "const api = {\n"
        "  data: { on: (_name, fn) => handlers.push(fn) },\n"
        "  ui: { toast: { show: (t) => toasts.push(t) } },\n"
        "}\n"
        "plugin.setup(api)\n"
        "for (const fn of handlers) fn({ data: { message: 'x' } })\n"
        "console.log(JSON.stringify(toasts))\n",
        "utf-8",
    )
    done = subprocess.run(
        [node, str(work / "run.mjs")],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return json.loads(done.stdout)


def test_tui_toast_duration_comes_from_common(tmp_path):
    """表示時間は ``[opencode.ask_description] duration_ms`` に従う (tui.ts に固定しない)。"""
    common = copy.deepcopy(COMMON)
    common["opencode"]["ask_description"]["duration_ms"] = 12345
    toasts = _tui_toasts(tmp_path, gen.build_opencode_guide({}, common))
    assert [t["duration"] for t in toasts] == [12345]


@pytest.mark.parametrize("rules", [None, {"guide": []}])
def test_tui_toast_falls_back_when_duration_is_unavailable(tmp_path, rules):
    """rules.json が読めなくても toast は出す。既定値は generate.py と揃える。"""
    toasts = _tui_toasts(tmp_path, rules)
    default = gen.opencode_ask_description(
        {"opencode": {"ask_description": {"enabled": True, "models": ["p/m"]}}}
    )["duration_ms"]
    assert [t["duration"] for t in toasts] == [default]


# キーバインドは cli.json 側にしか無い。opencode.json へ書いても読まれず、
# 誤配置に気付けないので出力先を固定する。
def test_keybinds_go_to_cli_json_only():
    cli = gen.merge_opencode_cli({}, COMMON)
    assert cli["keybinds"]["service.restart"] == "<leader>v"
    assert "keybinds" not in gen.merge_opencode_config({}, COMMON)


# ctrl+c を session.interrupt へ渡すには app.exit から外すのが必須。
# app.exit の既定は "ctrl+c,ctrl+d,<leader>q" なので、残すと Ctrl+C が
# 中断ではなくアプリ終了になる。
def test_ctrl_c_interrupts_instead_of_exiting():
    keybinds = gen.merge_opencode_cli({}, COMMON)["keybinds"]
    assert "ctrl+c" in keybinds["session.interrupt"].split(",")
    assert "ctrl+c" not in keybinds["app.exit"].split(",")
    assert "ctrl+d" in keybinds["app.exit"].split(",")


def test_keybinds_replace_the_whole_table():
    """宣言した以上は common.toml の持ち物。消した分が配備先に残らない。"""
    existing = {"keybinds": {"app.debug": "ctrl+g"}, "attention": {"enabled": True}}
    cli = gen.merge_opencode_cli(existing, COMMON)
    assert "app.debug" not in cli["keybinds"]
    assert cli["attention"] == {"enabled": True}


def test_keybinds_are_left_alone_when_undeclared():
    existing = {"keybinds": {"app.debug": "ctrl+g"}}
    cli = gen.merge_opencode_cli(existing, {"opencode": {}})
    assert cli["keybinds"] == {"app.debug": "ctrl+g"}


def test_keybinds_declared_empty_clear_the_existing_table():
    """空テーブルでも宣言は宣言。未宣言 (触らない) と取り違えると残骸が残る。"""
    existing = {"keybinds": {"app.debug": "ctrl+g"}}
    cli = gen.merge_opencode_cli(existing, {"opencode": {"keybinds": {}}})
    assert cli["keybinds"] == {}
    assert gen.build_opencode_keybinds({"opencode": {}}) is None


@pytest.mark.parametrize(
    "binding",
    ["", True, [], ["ctrl+a", ""], 1, {"preventDefault": False}, {"key": ""}],
)
def test_keybind_value_is_rejected_when_malformed(binding):
    with pytest.raises(ValueError):
        gen.build_opencode_keybinds({"opencode": {"keybinds": {"app.exit": binding}}})


@pytest.mark.parametrize("command", ["App.Exit", "app exit", "appexit", ""])
def test_keybind_id_is_rejected_when_not_an_id(command):
    with pytest.raises(ValueError):
        gen.build_opencode_keybinds({"opencode": {"keybinds": {command: "ctrl+d"}}})


@pytest.mark.parametrize(
    "binding",
    [
        "ctrl+d",
        "ctrl+c,escape",
        ["ctrl+c", "escape"],
        False,
        "none",
        {"key": "ctrl+v", "preventDefault": False},
    ],
)
def test_keybind_value_is_accepted_when_documented(binding):
    """公式 Keybinds ガイドが挙げている書き方をすべて通す。"""
    out = gen.build_opencode_keybinds({"opencode": {"keybinds": {"prompt.paste": binding}}})
    assert out["prompt.paste"] == binding


def test_keybind_leader_is_allowed_as_an_id():
    out = gen.build_opencode_keybinds({"opencode": {"keybinds": {"leader": "ctrl+space"}}})
    assert out["leader"] == "ctrl+space"


def test_redirect_guard_covers_every_allowed_command():
    """★allow に載せたコマンドは、書き込み形が塞がれていること。

    allow は**前方一致**で、リダイレクトは resource に残る。つまり
    ``git log`` を allow に載せた時点で ``git log > ~/.bashrc`` が
    **無確認で通る**。guide 規則は effect が allow でも走るので、そこで
    書き込み形だけ deny する。

    **allow を増やしたらこのテストが落ちる。** 歯止めも一緒に足すこと。
    """
    guards = [
        g
        for g in gen.opencode_guide_rules(COMMON)
        if "リダイレクト" in g["message"] and "allow" in g["message"]
    ]
    assert len(guards) == 1, "リダイレクトの歯止めが 1 件でない"
    assert "unless" not in guards[0], (
        "unless はコマンド全体に当たり、本物の書き込みと併記すると素通りする"
    )
    pattern = re.compile(guards[0]["pattern"])

    for command in COMMON["opencode"]["shell"]["allow"]:
        probe = f"{command} > /home/u/.bashrc"
        assert pattern.search(probe), f"allow の {command!r} が書き込み形で素通りする"


def test_redirect_guard_is_not_bypassed_by_harmless_redirects():
    """無害なリダイレクトを併記しても、本物の書き込みは止まること。"""
    guards = [
        g
        for g in gen.opencode_guide_rules(COMMON)
        if "リダイレクト" in g["message"] and "allow" in g["message"]
    ]
    pattern = re.compile(guards[0]["pattern"])

    for probe in (
        "wc f 2>&1 > /home/u/.bashrc",
        "git log >/dev/null > /home/u/.bashrc",
        "git log >&2 >> /home/u/.bashrc",
        "git log 2>/dev/null 2> /home/u/.bashrc",
        "git log >/dev/nullx",
        "git log >&1x",
        "git log &> /home/u/.bashrc",
        "git log >| /home/u/.bashrc",
    ):
        assert pattern.search(probe), f"{probe!r} が素通りする"


def test_redirect_guard_lets_through_reads_and_stderr():
    """★止めるのは書き込みだけ。読み取りと stderr の付け替えは通す。

    ここを広げると作業が止まる。`2>/dev/null` や `2>&1` は日常的に使う。
    """
    guards = [
        g
        for g in gen.opencode_guide_rules(COMMON)
        if "リダイレクト" in g["message"] and "allow" in g["message"]
    ]
    pattern = re.compile(guards[0]["pattern"])

    for probe in (
        "git log --oneline -5",
        "git log 2>&1 | head",
        "wc -l a.txt 2>/dev/null",
        "wc -l a.txt >>/dev/null 2>&1",
        "git log >&2",
        "git log 2>&-",
        "git log | wc -l",
    ):
        assert not pattern.search(probe), f"{probe!r} を止めてしまう"


def test_allow_is_not_widened_silently():
    """allow が増えたら気付けるようにする。

    ここを更新するときは docs/change/0002-opencode-ask-by-default.md の
    「段階 1 の詳細」と、その根拠になった実測も一緒に見直すこと。
    スキルのスクリプトは test_opencode_external_read.py が固定する。
    """
    skill = set(gen.opencode_skill_script_rules(COMMON)[0])
    assert [r for r in rules("shell", "allow") if r not in skill] == [
        "git log *",
        "wc *",
        "grep -n *",
        "uv pip list *",
        "docker ps *",
    ]


# `.git/config` へ書けると diff.<name>.command / core.fsmonitor に任意コマンドを
# 仕込めて、git diff / git status が実行手段になる (実測)。
# see docs/research/opencode/permission/allow-list-audit.md
@pytest.mark.parametrize("resource", ["*/.git/config", "*/.git/hooks/*", "~/.gitconfig"])
def test_git_config_is_write_denied(resource: str):
    assert resource in rules("edit", "deny")


# プロジェクト側の設定に書いた permission はグローバルの deny に勝つ (実測)。
# 書けるとエージェントが自分で権限を広げられる。
# see docs/research/opencode/permission/gaps.md
@pytest.mark.parametrize("resource", ["*/.opencode/opencode.json", "*/.opencode/opencode.jsonc"])
def test_project_config_is_write_denied(resource: str):
    assert resource in rules("edit", "deny")


@pytest.mark.parametrize("command", ["git diff", "git status"])
def test_git_commands_that_execute_are_not_allowed(command: str):
    """`git diff` は外部 diff、`git status` は fsmonitor で任意コマンドを起動する。

    どちらも実測済み。`.git/config` を write deny にしても、shell の
    リダイレクトはその deny を通らないので、allow に戻してはいけない。
    """
    for resource in rules("shell", "allow"):
        assert not resource.startswith(command), f"{resource} は任意コード実行を含む"


def test_bash_allow_is_untouched_so_other_clis_do_not_move():
    """``[bash] allow`` は Claude / Copilot 用に残す (段階 1 の非目的)。

    ここが縮むと他 CLI の確認回数が変わり、OpenCode 側の効果を切り分け
    られなくなる。撤退も ``[opencode.shell]`` の削除だけでは済まなくなる。
    """
    bash_allow = COMMON["bash"]["allow"]
    for command in ARBITRARY_CODE_EXECUTION:
        assert any(cmd.startswith(command) for cmd in bash_allow), (
            f"{command} が [bash] allow から消えている。OpenCode 側だけを絞るのが段階 1 の前提"
        )


def test_dropping_them_from_opencode_does_not_reach_copilot():
    """Copilot の commandIdentifiers は ``[bash] allow`` 由来のまま。

    段階 1 の受入条件「他 CLI の生成物に diff が出ない」の機械的な固定。
    """
    approvals = gen.build_copilot_locations(COMMON)["locations"]
    names = {
        command
        for location in approvals.values()
        for approval in location["tool_approvals"]
        if approval.get("kind") == "commands"
        for command in approval["commandIdentifiers"]
    }
    assert {"find", "gcc", "cmake"} <= names
    # OpenCode 専用の allow は Copilot へ漏れない
    assert "docker" in names or "docker ps" not in names


def test_hook_owned_ask_is_still_emitted():
    """``ask_hook_owned`` は OpenCode では除外しない。

    Claude では静的 ask を出すと hook の exemption が無効化されるので外すが、
    OpenCode に hook は無い。除外すると委譲先が無いまま素通りになる。
    """
    hook_owned = COMMON["bash"]["ask_hook_owned"]
    assert hook_owned, "前提: hook に委ねる ask がある"
    for cmd in hook_owned:
        assert f"{cmd} *" in rules("shell", "ask")
    # Claude 側では従来どおり外れていること (非対称が意図であることの固定)
    assert f"Bash({hook_owned[0]}:*)" not in gen.build_claude_permissions(COMMON)["ask"]


# ---------------------------------------------------------------------------
# glob の記法差
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("glob", "expected"),
    [
        # `**/` は「0 段以上」なので、ルート直下と入れ子の 2 本に割る
        ("**/.netrc", [".netrc", "*/.netrc"]),
        ("**/.ssh/**", [".ssh/*", "*/.ssh/*"]),
        ("**/secrets/**", ["secrets/*", "*/secrets/*"]),
        ("**/id_rsa*", ["id_rsa*", "*/id_rsa*"]),
        # `*` は `/` も跨ぐので、`*` 始まりなら入れ子側は要らない
        ("**/*.pem", ["*.pem"]),
        ("**/*secret*", ["*secret*"]),
        # `**` を含まないものはそのまま
        (".env", [".env"]),
        (".env.*", [".env.*"]),
        ("~/.claude.json", ["~/.claude.json"]),
    ],
)
def test_glob_conversion(glob: str, expected: list[str]):
    assert gen.opencode_path_patterns(glob) == expected


def test_no_double_star_reaches_the_generated_rules():
    """``**`` を渡すと ``*`` 2 つとして読まれ、意図より広く当たる。"""
    for rule in generated()["permissions"]:
        assert "**" not in rule["resource"], rule


@pytest.mark.parametrize("key", ["read_deny_globs", "write_deny_globs"])
def test_every_file_deny_glob_is_converted(key: str):
    action = "read" if "read" in key else "edit"
    emitted = set(rules(action, "deny"))
    for glob in COMMON["file"][key]:
        assert set(gen.opencode_path_patterns(glob)) <= emitted, glob


def test_allow_side_file_globs_are_not_emitted():
    """OpenCode は allow が既定なので、allow の写しを増やさない。

    出す allow は ``[[file.deny_exceptions]]`` の例外だけ (read / edit とも同じ)。
    """
    expected = [
        p
        for e in COMMON["file"]["deny_exceptions"]
        for g in e["except"]
        for p in gen.opencode_path_patterns(g)
    ]
    assert rules("read", "allow") == expected
    assert rules("edit", "allow") == expected


def test_deny_exceptions_sit_right_after_their_paired_deny():
    """★後勝ちなので、例外の allow は対の deny の直後、ほかの deny より前に置く。

    前だと対の deny に負け、後ろ (全 deny の後) だと `.ssh/**` などの deny まで上書きする。
    """
    for action in ("read", "edit"):
        found = [r for r in generated()["permissions"] if r["action"] == action]
        for entry in COMMON["file"]["deny_exceptions"]:
            deny = gen.opencode_path_patterns(entry["deny"])
            allow = [p for g in entry["except"] for p in gen.opencode_path_patterns(g)]
            at = [r["resource"] for r in found if r["effect"] != "ask"]
            start = at.index(deny[0])
            assert at[start : start + len(deny) + len(allow)] == deny + allow, action
            # 例外の allow より後ろは deny だけ (別の deny が例外の後に勝つ)
            tail = [r for r in found if r["effect"] != "ask"][start + len(deny) + len(allow) :]
            assert tail and all(r["effect"] == "deny" for r in tail), action


def _last_match(action: str, path: str) -> str | None:
    import fnmatch

    result = None
    for rule in generated()["permissions"]:
        if rule["action"] == action and fnmatch.fnmatchcase(path, rule["resource"]):
            result = rule["effect"]
    return result


@pytest.mark.parametrize(
    ("path", "effect"),
    [
        ("/p/.env", "deny"),
        ("/p/.env.local", "deny"),
        ("/p/app/.env.local", "deny"),
        ("/p/.env.production", "deny"),
        (".env.local", "deny"),
        ("/p/.env.example", "allow"),
        ("/p/app/.env.example", "allow"),
        ("/p/.env.sample", "allow"),
        ("/p/.env.template", "allow"),
        (".env.example", "allow"),
        ("/p/.env.example.bak", "deny"),
        # 例外は `.env.*` の deny にだけ効く。別の deny に当たるものは deny のまま
        ("/home/u/.ssh/.env.example", "deny"),
        (".ssh/.env.example", "deny"),
        ("/p/secrets/.env.example", "deny"),
        ("/p/.gnupg/.env.sample", "deny"),
        ("/p/.env.secret.example", "deny"),
    ],
)
@pytest.mark.parametrize("action", ["read", "edit"])
def test_dotenv_variants_are_denied_except_examples(action, path, effect):
    """OpenCode の後勝ちで評価して、`.env.*` は deny、サンプルだけ allow になる。"""
    assert _last_match(action, path) == effect


def test_deny_exception_must_name_an_existing_deny():
    common = copy.deepcopy(COMMON)
    common["file"]["deny_exceptions"].append({"deny": "**/nothing", "except": ["**/x"]})
    with pytest.raises(ValueError, match="deny の一覧に無い"):
        gen.build_opencode_permissions(common)


def test_deny_exceptions_reach_the_rules_json():
    guide = gen.build_opencode_guide({}, COMMON)
    [entry] = guide["read_deny_except"]
    assert set(entry["deny"]) <= set(guide["read_deny"])
    assert set(entry["deny"]) <= set(guide["redact"]["deny_path"])


# ---------------------------------------------------------------------------
# 整形 (formatter)
# ---------------------------------------------------------------------------


def test_formatter_is_generated_from_common():
    """PostToolUse hook (format-file.sh / markdownlint.sh) の代替。"""
    formatter = generated()["formatter"]
    assert formatter == COMMON["opencode"]["formatter"]


def test_markdown_is_covered_because_it_has_no_builtin():
    """組み込みに markdownlint は無いので、ここが唯一の .md 整形経路。"""
    markdown = generated()["formatter"]["markdownlint"]
    assert markdown["command"][0] == "markdownlint-cli2"
    assert "$FILE" in markdown["command"]
    assert set(markdown["extensions"]) == {".md", ".markdown"}


@pytest.mark.parametrize("name", ["ruff", "clang-format", "prettier", "shfmt"])
def test_builtin_covered_formatters_are_not_redeclared(name: str):
    """組み込みがあるものを書くと、更新が二重管理になる。

    テーブルを 1 つでも書けば組み込みは全部有効になる (公式 Formatters
    ガイド) ので、``format-file.sh`` が呼んでいた ruff / clang-format /
    prettier は宣言せずに済む。
    """
    assert name in gen.OPENCODE_BUILTIN_FORMATTERS
    assert name not in COMMON["opencode"]["formatter"]


def test_formatter_is_omitted_when_common_has_none():
    """キーが無ければ既存値に触らない (auto_update と同じ約束)。"""
    assert "formatter" not in gen.merge_opencode_config({}, {})
    kept = gen.merge_opencode_config({"formatter": {"mine": {}}}, {})
    assert kept["formatter"] == {"mine": {}}


def test_formatter_declared_empty_replaces_the_existing_table():
    """空テーブルでも宣言は宣言。未宣言 (触らない) と取り違えると残骸が残る。"""
    existing = {"formatter": {"stale": {"command": ["x", "$FILE"], "extensions": [".x"]}}}
    out = gen.merge_opencode_config(existing, {"opencode": {"formatter": {}}})
    assert out["formatter"] == {}
    assert gen.build_opencode_formatter({"opencode": {}}) is None


@pytest.mark.parametrize(
    "entry",
    [
        # 組み込みに無い名前は command と extensions の両方が要る
        {"command": ["x", "$FILE"]},
        {"extensions": [".x"]},
        {},
        # 綴り間違い
        {"command": ["x"], "extensions": [".x"], "exts": [".y"]},
        # argv 配列でないもの (シェル文字列と取り違えた形)
        {"command": "x --fix $FILE", "extensions": [".x"]},
        {"command": [], "extensions": [".x"]},
        {"command": ["x", 1], "extensions": [".x"]},
        # 先頭のドットが無い拡張子は一致しない
        {"command": ["x"], "extensions": ["md"]},
        {"command": ["x"], "extensions": "md"},
    ],
)
def test_broken_formatter_declaration_stops_generation(entry: dict):
    """整形されないだけで表に出ないので、apply を止める。"""
    with pytest.raises(ValueError):
        gen.build_opencode_formatter({"opencode": {"formatter": {"custom": entry}}})


def test_builtin_entry_may_omit_command_and_extensions():
    """組み込みの上書きは省略した値を継承する。"""
    common = {"opencode": {"formatter": {"prettier": {"extensions": [".ts"]}}}}
    assert gen.build_opencode_formatter(common) == {"prettier": {"extensions": [".ts"]}}


def test_disabling_a_custom_entry_needs_nothing_else():
    common = {"opencode": {"formatter": {"custom": {"disabled": True}}}}
    assert gen.build_opencode_formatter(common) == {"custom": {"disabled": True}}


# ---------------------------------------------------------------------------
# 自分の設定を書き換えられないこと
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path", ["~/.config/opencode/opencode.json", "~/.config/opencode/service.json"]
)
def test_opencode_cannot_rewrite_its_own_runtime_config(path: str):
    """permission の正本を自分で緩められると、他の層が無い分そのまま穴になる。"""
    assert path in rules("edit", "deny")


def test_service_credentials_are_not_readable():
    """service.json には background service の password が平文で入る。"""
    assert "~/.config/opencode/service.json" in rules("read", "deny")
    assert "~/.config/opencode/service.json" in COMMON["sandbox"]["deny"]


# ---------------------------------------------------------------------------
# OpenCode へ渡さないもの (意図的な非対称)
# ---------------------------------------------------------------------------


def test_web_domains_are_not_translated_into_webfetch_rules():
    """ドメイン許可は OpenCode の資源表現 (URL) では正しく書けない。

    ``*`` が ``/`` を跨ぐため ``*://*.example.com/*`` は
    ``https://evil.test/x.example.com/y`` にも当たる。過大な allowlist を
    出すくらいなら出さない、という判断を固定する。
    """
    assert COMMON["web"]["allow_domains"], "前提: 許可ドメインがある"
    assert [r for r in generated()["permissions"] if r["action"] == "webfetch"] == []


def test_claude_mcp_deny_names_are_not_copied():
    """``mcp__<server>__<tool>`` は OpenCode の ``<server>_<tool>`` と別体系。"""
    for name in COMMON["claude"]["mcp_deny"]:
        assert name not in json.dumps(generated(), ensure_ascii=False)


# ---------------------------------------------------------------------------
# MCP
# ---------------------------------------------------------------------------


def opencode_entry(server: dict) -> dict:
    if server["transport"] == "http":
        return {"type": "remote", "url": server["url"]}
    return {"type": "local", "command": [server["command"], *server["args"]]}


@pytest.mark.parametrize("username", ["applejxd", "tester"])
def test_mcp_servers_come_from_common(username: str):
    common = load_common(username)
    merged = gen.merge_opencode_config({}, common)
    assert merged["mcp"]["servers"] == {
        name: opencode_entry(server) for name, server in gen.mcp_servers(common, "opencode")
    }


def test_mcp_covers_stdio():
    # 宣言済みの stdio サーバは claude 限定になったので、合成した定義で確かめる。
    stdio = {"id": "x", "transport": "stdio", "command": "uvx", "args": ["demo"]}
    servers = gen.merge_opencode_config({}, {"mcp": [stdio]})["mcp"]["servers"]
    assert any(entry["type"] == "local" for entry in servers.values())


def test_mcp_keeps_servers_and_secret_fields_it_does_not_own():
    # 宣言済みの remote サーバが 0 件になったので、合成した定義で確かめる。
    http = {"id": "x", "transport": "http", "url": "https://example.com/mcp"}
    common = {"mcp": [http]}
    name = http["id"]
    existing = {
        "mcp": {
            "timeout": {"startup": 45000},
            "servers": {
                "added-by-cli": {"type": "remote", "url": "https://other.test/mcp"},
                name: {
                    "type": "remote",
                    "url": "https://stale.example.com/mcp",
                    "headers": {"Authorization": "Bearer {env:EXAMPLE_TOKEN}"},
                },
            },
        }
    }
    merged = gen.merge_opencode_config(existing, common)
    servers = merged["mcp"]["servers"]

    assert merged["mcp"]["timeout"] == {"startup": 45000}
    assert servers["added-by-cli"] == existing["mcp"]["servers"]["added-by-cli"]
    assert servers[name]["headers"] == {"Authorization": "Bearer {env:EXAMPLE_TOKEN}"}
    # url は common.toml が正本
    assert servers[name]["url"] == http["url"]


def test_mcp_drops_keys_of_the_previous_transport():
    existing = {"mcp": {"servers": {"x": {"type": "remote", "url": "https://old.test/mcp"}}}}
    stdio = {"id": "x", "transport": "stdio", "command": "uvx", "args": ["demo"]}
    merged = gen.merge_opencode_config(existing, {"mcp": [stdio]})
    assert merged["mcp"]["servers"]["x"] == opencode_entry(stdio)


def test_source_does_not_hardcode_servers_or_users():
    source = MODIFIER.read_text(encoding="utf-8")
    for server in load_common("tester")["mcp"]:
        for value in (server.get("url"), server.get("command"), server["id"]):
            assert value is None or value not in source
    assert "applejxd" not in source
