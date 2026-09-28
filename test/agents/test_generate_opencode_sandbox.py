"""隔離版 OpenCode (ocs) の設定生成に関するテスト。

Run with: ``uv run --with pytest --no-project pytest test/agents/`` or
``python3 -m pytest test/agents/``.

★ここで守りたいのは「緩和が隔離版だけに閉じ込められていること」と
  「境界が守らないものを permission から捨てていないこと」。
  後者を誤って捨てると、保護が静かに消える。
see docs/spec/opencode-sandbox.md
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "agents"))

import generate as gen  # noqa: E402
from agents_common import load_common  # noqa: E402

COMMON = load_common()
SANDBOX = COMMON.get("opencode", {}).get("sandbox", {})


def _out(tmp_path: Path) -> dict:
    """Fence の無い機械でも生成結果を得るため、runtime だけダミーに差し替える。"""
    runtime = tmp_path / "fence"
    runtime.write_text("", "utf-8")
    common = {
        **COMMON,
        "opencode": {**COMMON["opencode"], "sandbox": {**SANDBOX, "runtime_path": str(runtime)}},
    }
    out = gen.opencode_sandbox(common)
    assert out is not None, "境界の設定が生成されない"
    return out


# ---------------------------------------------------------------------------
# common.toml 側の構造
# ---------------------------------------------------------------------------

def test_sandbox_bare_keys_not_swallowed_by_subtable():
    """★ベアキーがサブテーブルに吸われていないこと。

    TOML はサブテーブル以降のベアキーをそのサブテーブルへ入れる。
    ``protected`` が ``[opencode.sandbox.permissions]`` に落ちると
    ``denyWrite`` が空になり、保護が黙って消える (実際に一度作り込んだ)。
    """
    for key in (
        "runtime_path", "read", "work_read", "protected", "deny_read", "unsafe_workspace",
        "config_dir",
    ):
        assert key in SANDBOX, f"[opencode.sandbox].{key} が無い (サブテーブルに吸われた?)"
    for key in ("permissions", "policies"):
        assert isinstance(SANDBOX.get(key), dict), f"[opencode.sandbox.{key}] が無い"


def test_unsafe_workspace_covers_home_windows_and_tmp():
    """起動ディレクトリは書けるので、ホーム・WSL の Windows 側・/tmp では起動しない。"""
    unsafe = SANDBOX.get("unsafe_workspace", [])
    for required in ("~", "/mnt", "/tmp"):
        assert required in unsafe, f"unsafe_workspace に {required} が無い"


def test_runtime_is_fence():
    """境界の道具は Fence (CHG-0009 段 0)。srt は Claude Code だけが使う。"""
    assert SANDBOX["runtime_path"].endswith("/github-fencesandbox-fence/latest/fence")


def test_global_opencode_config_is_not_opened_wholesale(tmp_path):
    """★``~/.config/opencode`` を丸ごと開けないこと。

    境界内で要るのは plugin の実体だけで、隔離版の設定は ``config_dir``
    (``~/.config/opencode-sandbox``) 側にある。丸ごと開けると
    ``service.json`` (常駐サービスの認証情報) まで読めてしまう。
    """
    out = _out(tmp_path)
    read = out["base"]["read"]
    home = str(Path.home())
    assert f"{home}/.config/opencode" not in read, "global config を丸ごと開けている"
    assert f"{home}/.config/opencode/guide-plugin" in read, "plugin が読めない"


def test_config_dir_is_outside_any_workspace():
    """隔離版の設定を内側から書き換えられないこと。

    ワークスペースは起動ディレクトリなので、config_dir は ``~/.config`` 側の
    固定パスにして、どの起動ディレクトリからも外に出るようにする。
    """
    config_dir = gen.expand_user(str(SANDBOX["config_dir"]))
    home = gen.expand_user("~")
    assert config_dir.startswith(f"{home}/.config/"), "config_dir が ~/.config の外にある"


def test_isolated_db_keys_are_gone():
    """★DB はホストと共有する。隔離用 DB とデータ領域の差し替えは持たない (CHG-0009 段 2)。

    ``XDG_DATA_HOME`` を起動ディレクトリへ向けると、境界の内側の mise が導入済みの
    道具を見つけられず入れ直していた。
    """
    for key in ("data_home", "db"):
        assert key not in SANDBOX, f"[opencode.sandbox].{key} が残っている"


# ---------------------------------------------------------------------------
# 隔離版の permission
# ---------------------------------------------------------------------------

def _isolated() -> list[dict[str, str]]:
    return gen.build_opencode_sandbox_permissions(COMMON)


def test_isolated_flips_default_shell_to_allow():
    rules = [r for r in _isolated() if r["action"] == "shell" and r["resource"] == "*"]
    assert rules, "既定の shell 規則が無い"
    assert rules[0]["effect"] == "allow", "境界内でも既定が allow になっていない"


def test_normal_variant_keeps_ask_default():
    """★緩和が通常版へ波及していないこと。"""
    rules = [
        r for r in gen.build_opencode_permissions(COMMON)
        if r["action"] == "shell" and r["resource"] == "*"
    ]
    assert rules[0]["effect"] == "ask", "通常版の既定まで緩んでいる"


def test_isolated_keeps_workspace_relative_secrets():
    """★境界はワークスペースを守らない。相対 glob の秘密を捨てないこと。

    部分一致で見ると、``*secret*`` が消えても ``secrets/*`` が残るだけで
    通ってしまう。**完全一致**で個別に確かめる。
    """
    resources = {r["resource"] for r in _isolated() if r["action"] in ("read", "edit")}
    for required in ("*secret*", "*credential*", "*_token", "*password*", "*/.ssh/*"):
        assert required in resources, f"{required} の規則が消えた"


def test_isolated_keeps_host_executed_code():
    """★審査前にホストで動くコードの規則を捨てないこと。"""
    resources = {r["resource"] for r in _isolated()}
    for required in (".git/hooks/*", "*/.git/hooks/*", "mise.toml"):
        assert required in resources, f"{required} の規則が消えた"


def test_isolated_drops_unreachable_host_paths():
    """境界が到達させないホスト絶対パスは捨てること。"""
    dropped = [
        r for r in _isolated()
        if r["action"] in ("read", "edit") and r["resource"].startswith(("~/", "/etc/", "/home/"))
    ]
    assert not dropped, f"到達できない規則が残っている: {dropped[:3]}"


def test_isolated_is_smaller_but_not_empty():
    normal = gen.build_opencode_permissions(COMMON)
    isolated = _isolated()
    assert len(isolated) < len(normal), "隔離版が縮んでいない"
    assert len(isolated) > 100, "削りすぎ (境界が守らないものまで捨てた疑い)"


# ---------------------------------------------------------------------------
# policies
# ---------------------------------------------------------------------------

def test_policies_are_permission_denies():
    policies = gen.opencode_sandbox_policies(COMMON)
    assert policies, "policies が空"
    for statement in policies:
        assert statement["action"] == "permission"
        assert statement["effect"] == "deny", "policy の allow は許可を与えない"
        assert ":" in statement["resource"], "resource は <action>:<value> の形"


def test_policies_cover_apply_and_push():
    resources = [p["resource"] for p in gen.opencode_sandbox_policies(COMMON)]
    for needle in ("git push", "chezmoi apply"):
        assert any(needle in r for r in resources), f"{needle} が policies に無い"


# ---------------------------------------------------------------------------
# 出力全体
# ---------------------------------------------------------------------------

def test_sandbox_output_shape(tmp_path):
    out = _out(tmp_path)
    for key in ("runtime_path", "base", "config_dir", "permissions"):
        assert key in out, f"{key} が出力に無い"
    assert "paths" not in out, "隔離用 DB の置き場が残っている"
    for key in (
        "read", "work_read", "write", "deny_read", "unsafe_workspace", "protected", "network",
    ):
        assert key in out["base"], f"base に {key} が無い"
    base = out["base"]
    assert out["config_dir"] not in base["write"], "config_dir が書ける"
    assert any(out["config_dir"].startswith(p) for p in base["read"]), "config_dir が読めない"


def test_output_without_fence(tmp_path):
    """Fence の実体が無くても境界の設定を出す (ランチャーが起動を断る)。

    実体があるときだけ出すと、Fence を入れる 125_mise.sh が設定の生成より後に走るので、
    初回の apply が 2 回要る。
    """
    missing = tmp_path / "missing"
    common = {
        **COMMON,
        "opencode": {
            **COMMON["opencode"],
            "sandbox": {**SANDBOX, "runtime_path": str(missing)},
        },
    }
    out = gen.opencode_sandbox(common)
    assert out is not None
    assert out["runtime_path"] == str(missing)


def test_no_output_when_disabled(tmp_path):
    """enabled=false なら境界の設定を出さない。"""
    common = {
        **COMMON,
        "opencode": {
            **COMMON["opencode"],
            "sandbox": {**SANDBOX, "enabled": False},
        },
    }
    assert gen.opencode_sandbox(common) is None


def test_model_provider_domain_allowed(tmp_path):
    """★モデル提供元が無いと proxy が CONNECT を 403 で落とす。

    症状が「応答が来ない」になり原因が見えにくいので、生成で固定する。
    """
    out = _out(tmp_path)
    domains = out["base"]["network"]["allowedDomains"]
    assert "api.githubcopilot.com" in domains, "モデル提供元が許可リストに無い"


def test_provider_domains_come_from_the_provider_layer():
    """★モデル API の接続先はハーネスではなく [provider.*] に置く。

    ハーネス側に書くと、同じプロバイダを使う別ハーネスを足すたびに
    同じドメインを書き直すことになる (ハーネス × プロバイダで増殖する)。
    """
    harness_own = COMMON["opencode"]["sandbox"].get("network_allow", [])
    for domain in ("api.githubcopilot.com", "api.anthropic.com", "api.openai.com"):
        assert domain not in harness_own, f"{domain} がハーネス側に残っている"
    declared = COMMON["opencode"]["sandbox"].get("providers", [])
    assert declared, "providers の宣言が無い"
    assert set(declared) <= set(COMMON["provider"]), "未定義の provider を参照している"


def test_unknown_provider_is_rejected_instead_of_ignored():
    """★綴り間違いを黙って無視しない (fail-closed)。

    ``.get(name, {})`` で空を返すと、誤りは「境界内からモデルへ到達できない」
    という形でしか現れない。proxy が 403 を返すだけなので原因に辿り着けない。
    """
    with pytest.raises(ValueError) as excinfo:
        gen.provider_domains(COMMON, ["githubcopilot"])  # 正しくは github-copilot
    assert "githubcopilot" in str(excinfo.value)


def test_provider_layer_is_shared_not_harness_specific():
    """[provider.*] はハーネス名を含まない。プロバイダ名だけで引けること。"""
    for name in COMMON["provider"]:
        assert "opencode" not in name, f"provider 名にハーネス名が混じっている: {name}"
        assert COMMON["provider"][name].get("network_allow"), (
            f"[provider.{name}] に network_allow が無い"
        )


def test_protected_includes_workspace_plugin_dir():
    """★``.opencode/plugins`` は置かれると自動ロードされる。

    境界内で動くのでホストへは出られないが、permission 評価と同じプロセス
    なのでツール層の規則を自ら無効化できる。**まだ存在しなくても**塞ぐ
    (ランチャーが空のディレクトリを先に作る)。
    """
    assert ".opencode" in SANDBOX.get("protected", []), "protected に .opencode が無い"


def test_protected_paths_are_not_filtered_by_existence(tmp_path):
    """★生成の時点では存在で絞らない。

    ワークスペースは起動ディレクトリなので、有無は起動時にしか分からない。
    ランチャーが起動ディレクトリと合わせ、無いものを作るか落とす。
    """
    out = _out(tmp_path)
    assert set(out["base"]["protected"]) == set(SANDBOX.get("protected", []))


def test_isolated_loads_guide_plugin_for_redaction(tmp_path):
    """境界はワークスペースの中を守らないので、伏字化が要る。

    """
    out = _out(tmp_path)
    plugins = out.get("plugins") or []
    assert plugins, "隔離版に plugin が無い (伏字化が効かない)"
    base = out["base"]
    for path in plugins:
        assert any(path.startswith(p) for p in base["read"]), f"{path} を境界内から読めない"
        assert not any(path.startswith(p) for p in base["write"]), f"{path} を境界内から書ける"


# guide plugin の役割を 1 つだけ有効にした隔離版。通常版と同じ判定関数を通す。
# ★ask_description は数えない。ocs は cli.json を渡さず tui.ts が読まれないので、
#   説明を生成しても表示されない。
# see docs/spec/agent-config-generation.md#plugin-層-guide-plugin
ISOLATED_GUIDE_ROLES = {
    "guide": ({"opencode": {"shell": {"guide": [{"pattern": "^cat ", "message": "m"}]}}}, True),
    "read_filter": ({"file": {"read_deny_globs": ["**/.env"]}}, True),
    "redact": ({"opencode": {"redact": {"enabled": True, "rule": []}}}, True),
    "ask_description": (
        {"opencode": {"ask_description": {"enabled": True, "models": ["p/m"]}}},
        False,
    ),
}


@pytest.mark.parametrize("role", sorted(ISOLATED_GUIDE_ROLES))
def test_isolated_guide_plugin_follows_the_shared_condition(tmp_path, role):
    runtime = tmp_path / "fence"
    runtime.write_text("", "utf-8")
    common, expected = ISOLATED_GUIDE_ROLES[role]
    common = {**common, "opencode": {
        **common.get("opencode", {}),
        "sandbox": {"enabled": True, "runtime_path": str(runtime)},
    }}
    out = gen.opencode_sandbox(common)
    assert (gen.opencode_guide_plugin_path() in out["plugins"]) is expected
    assert out["plugins"][-1] == gen.opencode_checkpoint_plugin_path()


def test_boundary_check_handles_nonexistent_protected_paths():
    """★保護対象は存在するとは限らない。

    存在を前提にすると「検査できない」と誤判定し、境界は正常なのに
    合格できなくなる (実地で踏んだ)。無ければ「作れないこと」を確かめる。
    """
    check = ROOT / "home" / "dot_local" / "bin" / "executable_ocs-boundary-check"
    body = check.read_text(encoding="utf-8")
    assert "保護対象を作れない" in body, "存在しない保護対象を検査していない"
    assert "保護対象が見当たらず検査できない" not in body, "存在を前提にした判定が残っている"


def test_boundary_check_detects_writable_regular_file():
    """★保護対象が「書ける通常ファイル」のとき合格にしないこと。

    ``-d`` でないと ``mkdir -p`` へ落ちるが、通常ファイルが存在すれば
    mkdir は必ず失敗する。それを「作れない＝合格」と読むと、**書けるのに
    合格**する。検査したいのは「書けないこと」であって
    「ディレクトリを作れないこと」ではない。
    """
    check = ROOT / "home" / "dot_local" / "bin" / "executable_ocs-boundary-check"
    body = check.read_text(encoding="utf-8")
    assert 'elif [ -e "$p" ]; then' in body, "通常ファイルの分岐が無い"
    # ★`>` だと中身を切り詰める。検査で保護対象を壊してはいけない。
    assert '( : >> "$p" )' in body, "追記で書き込み可否を見ていない"
    assert '( : > "$p" )' not in body, "保護対象を切り詰める書き方が入っている"


def test_protected_paths_may_not_exist_on_host(tmp_path):
    """宣言した保護対象のうち、ホストに無いものがあっても構わない。"""
    out = _out(tmp_path)
    assert ".opencode" in out["base"]["protected"], ".opencode が保護対象から消えた"


def test_model_preference_is_declared(tmp_path):
    """既定モデルを宣言しておく。無いと初回に何が選ばれるか環境依存になる。

    ★provider ID とモデル ID は実在を確認してから書くこと。無いものを書くと
      起動しても応答が来ない。
    """
    out = _out(tmp_path)
    preference = out.get("model_preference") or []
    assert preference, "model_preference が無い"
    for entry in preference:
        assert entry["provider"] and entry["model"], f"不完全な指定: {entry}"


def test_system_prompt_mentions_enoent():
    """境界は見えないので、ENOENT の意味を伝えること。"""
    prompt = SANDBOX.get("system_prompt", "")
    assert "ENOENT" in prompt, "ENOENT の説明が無い (誤診の原因)"


# ---------------------------------------------------------------------------
# エージェント・コマンド (CHG-0010)
# ---------------------------------------------------------------------------

def _with_provider(tmp_path: Path, provider: str) -> dict:
    """この PC のプロバイダだけを差し替えた common で、隔離版の素材を作る。"""
    runtime = tmp_path / "fence"
    runtime.write_text("", "utf-8")
    opencode = COMMON["opencode"]
    common = {
        **COMMON,
        "opencode": {
            **opencode,
            "model": {**opencode["model"], "provider": provider},
            "sandbox": {**SANDBOX, "runtime_path": str(runtime)},
        },
    }
    out = gen.opencode_sandbox(common)
    assert out is not None
    return out


def test_isolated_gets_the_same_agents_and_commands_as_common(tmp_path):
    """★common.toml のエージェント・コマンドが、通常版と同じ関数で隔離版にも出ること。"""
    out = _out(tmp_path)
    assert out["agent"] == gen.merge_opencode_agents({}, COMMON)
    assert {"bypass", "bypass-worker"} <= set(out["agent"])
    assert out["agent"]["bypass"]["permission"] == "allow"
    assert set(out["agents"]) == set(gen.opencode_v2_agents(COMMON))
    for name, agent in gen.opencode_v2_agents(COMMON).items():
        for key, value in agent.items():
            assert out["agents"][name][key] == value, f"agents.{name}.{key} が違う"
    assert out["commands"] == gen.merge_opencode_commands({}, COMMON)
    assert "fleet" in out["commands"]


def test_isolated_agents_are_not_taken_from_the_normal_config():
    """通常版の opencode.json (手で足したエージェント) を素材にしないこと。

    生成器は rules.json の既存しか受け取らない。既存の ``sandbox`` 節に何が
    残っていても、common.toml から作り直す。
    """
    stale = {"sandbox": {
        "agent": {"handmade": {"permission": "allow"}},
        "agents": {"handmade": {"description": "x"}},
        "commands": {"handmade": {"template": "x"}},
    }}
    out = gen.build_opencode_guide(stale, COMMON)["sandbox"]
    for key in ("agent", "agents", "commands"):
        assert "handmade" not in out[key], f"{key} に宣言外のエントリが入った"


def test_isolated_assigns_models_when_the_provider_is_reachable(tmp_path):
    out = _with_provider(tmp_path, "github-copilot")
    models = gen.opencode_models(
        {**COMMON, "opencode": {**COMMON["opencode"], "model": {
            **COMMON["opencode"]["model"], "provider": "github-copilot",
        }}}
    )
    assert models is not None
    for name, model in models["agents"].items():
        assert out["agents"][name]["model"] == model
    assert "providers" not in out, "Copilot に接続設定は無い"


def test_isolated_skips_models_of_an_unreachable_provider(tmp_path):
    """★境界の内から届かないプロバイダのモデルを子エージェントに割り当てないこと。

    Bedrock は ``ocs`` では使えない。割り当てると子エージェントが応答しない。
    割り当てが無ければ親のモデルで動く。
    see docs/spec/agent-config-generation.md#隔離起動ocs
    """
    assert "amazon-bedrock" not in SANDBOX.get("providers", [])
    out = _with_provider(tmp_path, "amazon-bedrock")
    for name, agent in out["agents"].items():
        assert "model" not in agent, f"agents.{name} に届かないモデルがある"
    assert "providers" not in out, "届かないプロバイダの接続設定が出た"


def test_isolated_writes_provider_settings_when_reachable(tmp_path):
    """接続設定が要るプロバイダが届くなら、通常版と同じ設定を出す。"""
    runtime = tmp_path / "fence"
    runtime.write_text("", "utf-8")
    opencode = COMMON["opencode"]
    common = {
        **COMMON,
        "opencode": {
            **opencode,
            "model": {**opencode["model"], "provider": "amazon-bedrock"},
            "sandbox": {
                **SANDBOX,
                "runtime_path": str(runtime),
                "providers": [*SANDBOX["providers"], "amazon-bedrock"],
            },
        },
    }
    out = gen.opencode_sandbox(common)
    assert out is not None
    assert out["providers"]["amazon-bedrock"]["settings"]["profile"] == "default"
    assert all("model" in out["agents"][n] for n in opencode["model"]["agents"])


def test_isolated_denies_the_guarded_subagent_outside_bypass(tmp_path):
    """★隔離版でも ``bypass-worker`` は ``bypass`` からだけ起動できること。

    全体の deny (permissions) と、guide plugin の起動元の検査 (rules.json の
    guarded_subagents / bypass_agents) の両方が隔離版に効く。
    """
    out = _out(tmp_path)
    assert {"action": "subagent", "resource": "bypass-worker", "effect": "deny"} in (
        out["permissions"]
    )
    rules = gen.build_opencode_guide({}, COMMON)
    assert "bypass-worker" in rules["guarded_subagents"]
    assert "bypass" in rules["bypass_agents"]
    assert gen.opencode_guide_plugin_path() in out["plugins"]
