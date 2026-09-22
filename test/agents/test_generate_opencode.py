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
import re
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
    existing = {"model": "anthropic/claude-sonnet-4-5", "theme": "custom"}
    before = copy.deepcopy(existing)
    merged = gen.merge_opencode_config(existing, COMMON)

    assert merged["model"] == before["model"]
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
        if action == "shell":
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
    """
    expected = [f"{cmd} *" for cmd in COMMON["opencode"]["shell"]["allow"]]
    assert rules("shell", "allow") == expected


def test_shell_ask_and_deny_still_come_from_bash():
    for effect in ("ask", "deny"):
        expected = [f"{cmd} *" for cmd in COMMON["bash"][effect]]
        # 先頭の catch-all (既定 ask) は [bash] 由来ではないので外す
        assert [r for r in rules("shell", effect) if r != "*"] == expected


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
    """全ツールを無確認で実行するカスタムエージェント。

    ``permission = "allow"`` は OpenCode が
    ``{action:"*", resource:"*", effect:"allow"}`` へ展開する (実測)。
    V1 の ``mode`` は非推奨なので ``agent`` で出す。
    """
    agent = generated()["agent"]["bypass"]
    assert agent["permission"] == "allow"
    assert agent["description"]


def test_agents_not_declared_in_common_are_kept():
    """``/agents`` などが同じファイルへ書くので、宣言した名前だけ差し替える。"""
    existing = {"agent": {"mine": {"description": "手で足したもの"}}}
    merged = gen.merge_opencode_config(existing, COMMON)["agent"]
    assert merged["mine"] == {"description": "手で足したもの"}
    assert "bypass" in merged


def test_bypass_is_the_only_agent_from_common():
    """権限を緩めるエージェントが黙って増えないようにする。"""
    assert set(generated()["agent"]) == {"bypass"}


# 誘導の素通り判定はエージェント名で行う。effect で見ると静的 allow を含む
# 呼び出し (cd x && git log) まで素通りする。
# see docs/research/opencode/permission/hook-order.md
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
    globs = [str(g) for g in COMMON["file"]["claude_read_deny_globs"]]
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
    """
    pats = [re.compile(p) for p in gen.build_opencode_guide({}, COMMON)["read_deny"]]
    assert any(p.search(path) for p in pats), path


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
    assert gen.build_opencode_guide({}, COMMON)["bypass_agents"] == ["bypass"]


def test_only_all_allow_agents_are_treated_as_bypass():
    common = {
        "opencode": {
            "agent": {
                "loose": {"permission": "allow"},
                "tight": {"permission": "ask"},
                "plain": {"description": "権限を触らない"},
            }
        }
    }
    assert gen.build_opencode_guide({}, common)["bypass_agents"] == ["loose"]


# --- shell 出力の伏字化 (段階 2-C) ----------------------------------------
# 伏字規則は**可変長の後読み**を使うので Python の ``re`` では再現できない。
# 判定器そのものを node で動かす。
# see docs/research/opencode/permission/output-filter-and-subagents.md


@pytest.fixture(scope="module")
def guide_js(tmp_path_factory):
    node = shutil.which("node")
    if not node:
        pytest.skip("node が無い (mise.toml の [tools] に宣言してある)")
    work = tmp_path_factory.mktemp("guide-js")
    src = (ROOT / "home/dot_config/opencode/guide-plugin/index.js").read_text("utf-8")
    (work / "mod.mjs").write_text(src + "\nexport { redact, deniedPathIn }\n", "utf-8")
    (work / "rules.json").write_text(
        json.dumps(gen.build_opencode_guide({}, COMMON)), "utf-8"
    )
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
            check=True,
        )
        return json.loads(done.stdout)

    return call


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
    for cmd, hit in zip(
        DENIED_COMMANDS, guide_js("deniedPathIn", DENIED_COMMANDS), strict=True
    ):
        assert hit, cmd


def test_ordinary_commands_are_not_detected(guide_js):
    for cmd, hit in zip(
        ALLOWED_COMMANDS, guide_js("deniedPathIn", ALLOWED_COMMANDS), strict=True
    ):
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
        assert set(rule) <= {"pattern", "message", "unless"}
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
    ["ctrl+d", "ctrl+c,escape", ["ctrl+c", "escape"], False, "none",
     {"key": "ctrl+v", "preventDefault": False}],
)
def test_keybind_value_is_accepted_when_documented(binding):
    """公式 Keybinds ガイドが挙げている書き方をすべて通す。"""
    out = gen.build_opencode_keybinds({"opencode": {"keybinds": {"prompt.paste": binding}}})
    assert out["prompt.paste"] == binding


def test_keybind_leader_is_allowed_as_an_id():
    out = gen.build_opencode_keybinds({"opencode": {"keybinds": {"leader": "ctrl+space"}}})
    assert out["leader"] == "ctrl+space"


def test_allow_is_not_widened_silently():
    """allow が増えたら気付けるようにする。

    ここを更新するときは docs/change/0002-opencode-ask-by-default.md の
    「段階 1 の詳細」と、その根拠になった実測も一緒に見直すこと。
    """
    assert rules("shell", "allow") == [
        "git log *",
        "wc *",
        "grep -n *",
        "uv pip list *",
        "docker ps *",
    ]


# `.git/config` へ書けると diff.<name>.command / core.fsmonitor に任意コマンドを
# 仕込めて、git diff / git status が実行手段になる (実測)。
# see docs/research/opencode/permission/allow-list-audit.md
@pytest.mark.parametrize(
    "resource", ["*/.git/config", "*/.git/hooks/*", "~/.gitconfig"]
)
def test_git_config_is_write_denied(resource: str):
    assert resource in rules("edit", "deny")


# プロジェクト側の設定に書いた permission はグローバルの deny に勝つ (実測)。
# 書けるとエージェントが自分で権限を広げられる。
# see docs/research/opencode/permission/gaps.md
@pytest.mark.parametrize(
    "resource", ["*/.opencode/opencode.json", "*/.opencode/opencode.jsonc"]
)
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
            f"{command} が [bash] allow から消えている。"
            "OpenCode 側だけを絞るのが段階 1 の前提"
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


@pytest.mark.parametrize("key", ["claude_read_deny_globs", "claude_write_deny_globs"])
def test_every_file_deny_glob_is_converted(key: str):
    action = "read" if "read" in key else "edit"
    emitted = set(rules(action, "deny"))
    for glob in COMMON["file"][key]:
        assert set(gen.opencode_path_patterns(glob)) <= emitted, glob


def test_allow_side_file_globs_are_not_emitted():
    """OpenCode は allow が既定なので、allow の写しを増やさない。"""
    assert rules("read", "allow") == []
    assert rules("edit", "allow") == []


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
        name: opencode_entry(server) for name, server in gen.mcp_servers(common)
    }


def test_mcp_covers_stdio():
    servers = gen.merge_opencode_config({}, load_common("tester"))["mcp"]["servers"]
    assert any(entry["type"] == "local" for entry in servers.values())


def test_mcp_keeps_servers_and_secret_fields_it_does_not_own():
    name = COMMON["mcp"][0]["id"]
    existing = {
        "mcp": {
            "timeout": {"startup": 45000},
            "servers": {
                "added-by-cli": {"type": "remote", "url": "https://example.com/mcp"},
                name: {
                    "type": "remote",
                    "url": "https://stale.example.com/mcp",
                    "headers": {"Authorization": "Bearer {env:EXAMPLE_TOKEN}"},
                },
            },
        }
    }
    merged = gen.merge_opencode_config(existing, COMMON)
    servers = merged["mcp"]["servers"]

    assert merged["mcp"]["timeout"] == {"startup": 45000}
    assert servers["added-by-cli"] == existing["mcp"]["servers"]["added-by-cli"]
    assert servers[name]["headers"] == {"Authorization": "Bearer {env:EXAMPLE_TOKEN}"}
    # url は common.toml が正本
    assert servers[name]["url"] == COMMON["mcp"][0]["url"]


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
