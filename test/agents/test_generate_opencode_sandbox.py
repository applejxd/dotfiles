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
    for key in ("runtime_path", "protected", "deny_read", "config_dir"):
        assert key in SANDBOX, f"[opencode.sandbox].{key} が無い (サブテーブルに吸われた?)"
    for key in ("permissions", "policies"):
        assert isinstance(SANDBOX.get(key), dict), f"[opencode.sandbox.{key}] が無い"


def test_deny_read_covers_windows_and_tmp():
    """``denyRead: ~`` は WSL の Windows 側とホストの /tmp を守らない。"""
    deny = SANDBOX.get("deny_read", [])
    for required in ("/mnt", "/tmp"):
        assert required in deny, f"deny_read に {required} が無い"


def test_config_dir_is_outside_any_workspace():
    """隔離版の設定を内側から書き換えられないこと。

    ワークスペースは起動ディレクトリなので、config_dir は ``~/.config`` 側の
    固定パスにして、どの起動ディレクトリからも外に出るようにする。
    """
    config_dir = gen.expand_user(str(SANDBOX["config_dir"]))
    home = gen.expand_user("~")
    assert config_dir.startswith(f"{home}/.config/"), "config_dir が ~/.config の外にある"


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
    for key in ("runtime_path", "base", "paths", "config_dir", "permissions"):
        assert key in out, f"{key} が出力に無い"
    for key in ("read", "write", "deny_read", "protected", "network"):
        assert key in out["base"], f"base に {key} が無い"
    for key in ("data_home", "db"):
        assert key in out["paths"], f"paths に {key} が無い"
    base = out["base"]
    assert out["config_dir"] not in base["write"], "config_dir が書ける"
    assert any(out["config_dir"].startswith(p) for p in base["read"]), "config_dir が読めない"


def test_model_provider_domain_allowed():
    """★モデル提供元が無いと proxy が CONNECT を 403 で落とす。

    症状が「応答が来ない」になり原因が見えにくいので、生成で固定する。
    """
    out = gen.opencode_sandbox(COMMON)
    if out is None:
        return
    domains = out["base"]["network"]["allowedDomains"]
    assert "api.githubcopilot.com" in domains, "モデル提供元が許可リストに無い"


def test_protected_includes_workspace_plugin_dir():
    """★``.opencode/plugins`` は置かれると自動ロードされる。

    境界内で動くのでホストへは出られないが、permission 評価と同じプロセス
    なのでツール層の規則を自ら無効化できる。**まだ存在しなくても**塞ぐ。
    """
    assert ".opencode" in SANDBOX.get("protected", []), "protected に .opencode が無い"


def test_protected_paths_are_not_filtered_by_existence():
    """★存在しないパスも denyWrite へ渡すこと。

    srt は存在しないパスにも denyWrite を効かせ、作成そのものを阻止する
    (実測)。存在フィルタを掛けると「まだ無いから守らない」という最も
    守りたい場面で保護が外れる。
    """
    out = gen.opencode_sandbox(COMMON)
    if out is None:
        return
    # 素材のまま (ワークスペース相対) で渡り、ランチャーが起動ディレクトリと
    # 組み合わせる。存在フィルタを掛けないこと。
    assert set(out["base"]["protected"]) == set(SANDBOX.get("protected", []))


def test_isolated_loads_guide_plugin_for_redaction():
    """境界はワークスペースの中を守らないので、伏字化が要る。

    ★段階 5 で、境界内では無意味な層 (誘導・結果フィルタ・パス参照の伏字化)
      を削り、内容の形の伏字化だけを残す予定。
    """
    out = gen.opencode_sandbox(COMMON)
    if out is None:
        return
    plugins = out.get("plugins") or []
    assert plugins, "隔離版に plugin が無い (伏字化が効かない)"
    base = out["base"]
    for path in plugins:
        assert any(path.startswith(p) for p in base["read"]), f"{path} を境界内から読めない"
        assert not any(path.startswith(p) for p in base["write"]), f"{path} を境界内から書ける"


def test_boundary_check_handles_nonexistent_protected_paths():
    """★保護対象は存在するとは限らない。

    srt は存在しないパスにも denyWrite を効かせ、作成そのものを阻止する。
    存在を前提にすると「検査できない」と誤判定し、境界は正常なのに
    起動できなくなる (実地で踏んだ)。
    """
    check = ROOT / "home" / "dot_local" / "bin" / "executable_opencode-boundary-check"
    body = check.read_text(encoding="utf-8")
    assert "保護対象を作れない" in body, "存在しない保護対象を検査していない"
    assert "保護対象が見当たらず検査できない" not in body, "存在を前提にした判定が残っている"


def test_protected_paths_may_not_exist_on_host():
    """宣言した保護対象のうち、ホストに無いものがあっても構わない。

    ``.opencode`` は「作られたら困る」対象なので、存在しない状態が正常。
    """
    out = gen.opencode_sandbox(COMMON)
    if out is None:
        return
    assert ".opencode" in out["base"]["protected"], ".opencode が保護対象から消えた"


def test_model_preference_is_declared():
    """既定モデルを宣言しておく。無いと初回に何が選ばれるか環境依存になる。

    ★provider ID とモデル ID は実在を確認してから書くこと。無いものを書くと
      起動しても応答が来ない。
    """
    out = gen.opencode_sandbox(COMMON)
    if out is None:
        return
    preference = out.get("model_preference") or []
    assert preference, "model_preference が無い"
    for entry in preference:
        assert entry["provider"] and entry["model"], f"不完全な指定: {entry}"


def test_system_prompt_mentions_enoent():
    """境界は見えないので、ENOENT の意味を伝えること。"""
    prompt = SANDBOX.get("system_prompt", "")
    assert "ENOENT" in prompt, "ENOENT の説明が無い (誤診の原因)"
