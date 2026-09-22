"""隔離版 OpenCode (CHG-0004) の設定生成に関するテスト。

Run with: ``uv run --with pytest --no-project pytest test/agents/`` or
``python3 -m pytest test/agents/``.

★ここで守りたいのは「緩和が隔離版だけに閉じ込められていること」と
  「境界が守らないものを permission から捨てていないこと」。
  後者を誤って捨てると、保護が静かに消える。
see docs/change/0004-opencode-sandbox.md
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "agents"))

import generate as gen  # noqa: E402
from agents_common import load_common  # noqa: E402

COMMON = load_common()
SANDBOX = COMMON.get("opencode", {}).get("sandbox", {})


# ---------------------------------------------------------------------------
# common.toml 側の構造
# ---------------------------------------------------------------------------

def test_sandbox_bare_keys_not_swallowed_by_subtable():
    """★ベアキーがサブテーブルに吸われていないこと。

    TOML はサブテーブル以降のベアキーをそのサブテーブルへ入れる。
    ``protected`` が ``[opencode.sandbox.permissions]`` に落ちると
    ``denyWrite`` が空になり、保護が黙って消える (実際に一度作り込んだ)。
    """
    for key in ("workspace", "runtime_path", "protected", "deny_read", "config_dir"):
        assert key in SANDBOX, f"[opencode.sandbox].{key} が無い (サブテーブルに吸われた?)"
    for key in ("permissions", "policies"):
        assert isinstance(SANDBOX.get(key), dict), f"[opencode.sandbox.{key}] が無い"


def test_deny_read_covers_windows_and_tmp():
    """``denyRead: ~`` は WSL の Windows 側とホストの /tmp を守らない。"""
    deny = SANDBOX.get("deny_read", [])
    for required in ("/mnt", "/tmp"):
        assert required in deny, f"deny_read に {required} が無い"


def test_config_dir_is_outside_workspace():
    """隔離版の設定を内側から書き換えられないこと。"""
    workspace = gen.expand_user(str(SANDBOX["workspace"]))
    config_dir = gen.expand_user(str(SANDBOX["config_dir"]))
    assert not config_dir.startswith(workspace), "config_dir がワークスペース内にある"


def test_data_home_is_inside_workspace():
    """snapshot の保存先が永続領域であること。

    既定のままだと境界内では隠れて消える領域に書かれ、捕捉は成功したように
    見えるのに復元できない。
    """
    assert SANDBOX.get("data_home"), "data_home が無い (安全網が消える)"


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

def test_sandbox_output_shape():
    out = gen.opencode_sandbox(COMMON)
    if out is None:  # srt が無いマシンでは出力しない (macOS / Windows / 初回前)
        return
    for key in ("runtime_path", "workspace", "data_home", "db", "config_dir", "permissions"):
        assert key in out, f"{key} が出力に無い"
    filesystem = out["config"]["filesystem"]
    assert out["config_dir"] not in filesystem["allowWrite"], "config_dir が書ける"
    assert any(
        out["config_dir"].startswith(p) for p in filesystem["allowRead"]
    ), "config_dir が読めない"


def test_model_provider_domain_allowed():
    """★モデル提供元が無いと proxy が CONNECT を 403 で落とす。

    症状が「応答が来ない」になり原因が見えにくいので、生成で固定する。
    """
    out = gen.opencode_sandbox(COMMON)
    if out is None:
        return
    domains = out["config"]["network"]["allowedDomains"]
    assert "api.githubcopilot.com" in domains, "モデル提供元が許可リストに無い"


def test_system_prompt_mentions_enoent():
    """境界は見えないので、ENOENT の意味を伝えること。"""
    prompt = SANDBOX.get("system_prompt", "")
    assert "ENOENT" in prompt, "ENOENT の説明が無い (誤診の原因)"
