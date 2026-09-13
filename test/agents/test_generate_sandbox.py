"""Tests for sandbox settings generation in scripts/agents/generate.py.

Run with: ``uv run --with pytest --no-project pytest test/agents/`` or
``python3 -m pytest test/agents/``.
"""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "agents"))

import generate as gen  # noqa: E402

COMMON_PATH = ROOT / "home" / "dot_config" / "agents" / "common.toml"


def load_common() -> dict:
    with COMMON_PATH.open("rb") as f:
        return tomllib.load(f)


COMMON = load_common()

SANDBOX_KEYS = ("deny", "write_deny_extra", "read_allow", "write_allow")


# ---------------------------------------------------------------------------
# common.toml 側の健全性
# ---------------------------------------------------------------------------

def test_sandbox_section_exists():
    assert "sandbox" in COMMON
    for key in SANDBOX_KEYS:
        assert COMMON["sandbox"][key], f"[sandbox].{key} が空"


def test_sandbox_paths_use_home_prefix():
    # sandbox の記法は permission の glob 記法と異なり、user 設定では無印/`./`
    # が ~/.claude 基準になる。ホーム全体に効かせるパスは必ず `~/` で始める
    # ことをここで固定しておく (書き忘れの防止)。
    sandbox = COMMON["sandbox"]
    for key in SANDBOX_KEYS:
        for path in sandbox[key]:
            assert path.startswith("~/"), (
                f"[sandbox].{key} の '{path}' は '~/' から始まっていない。"
                "user 設定では無印パスが ~/.claude 基準になるため意図しない"
                "範囲になる可能性がある。"
            )


# Claude の Linux sandbox は deny 対象の各パスに /dev/null を bind-mount する
# ため、ホーム全体に広がる名前マッチを deny に置くと数千件に展開されて
# 実用にならない (実測 3239 件)。whitelist 化した以上これらは不要。
FORBIDDEN_DENY_SUBSTRINGS = ("*secret*", "*credential*", "*password*", "*.pem", "*.key")


def test_deny_has_no_broad_name_globs():
    for path in COMMON["sandbox"]["deny"]:
        for bad in FORBIDDEN_DENY_SUBSTRINGS:
            assert bad not in path, (
                f"deny の '{path}' は広い名前マッチ。Claude の sandbox は "
                "deny 1 件につき 1 個の bind-mount を作るため展開が爆発する。"
                "whitelist (read_allow) の側で絞ること。"
            )


def test_read_allow_has_no_wildcards():
    # 穴を開ける側に glob を使うと意図より広く開きやすいので禁止する。
    for path in COMMON["sandbox"]["read_allow"] + COMMON["sandbox"]["write_allow"]:
        assert "*" not in path, f"allow 側に glob は使わない: {path}"


# ---------------------------------------------------------------------------
# build_claude_sandbox() — whitelist (deny-by-default)
# ---------------------------------------------------------------------------

def test_build_claude_sandbox_enabled():
    assert gen.build_claude_sandbox(COMMON)["enabled"] is True


def test_claude_deny_read_starts_with_home_to_be_whitelist():
    # ホーム全体を塞いでから allowRead で穴を開ける構成であること。
    fs = gen.build_claude_sandbox(COMMON)["filesystem"]
    assert fs["denyRead"][0] == "~/", (
        "denyRead の先頭が '~/' でない = whitelist になっていない"
    )


def test_claude_deny_read_contains_common_deny():
    fs = gen.build_claude_sandbox(COMMON)["filesystem"]
    assert set(COMMON["sandbox"]["deny"]) <= set(fs["denyRead"])


def test_claude_allow_read_matches_common():
    fs = gen.build_claude_sandbox(COMMON)["filesystem"]
    assert fs["allowRead"] == COMMON["sandbox"]["read_allow"]


def test_claude_allow_write_matches_common():
    fs = gen.build_claude_sandbox(COMMON)["filesystem"]
    assert fs["allowWrite"] == COMMON["sandbox"]["write_allow"]


def test_claude_deny_write_covers_deny_and_extra():
    fs = gen.build_claude_sandbox(COMMON)["filesystem"]
    deny_write = set(fs["denyWrite"])
    assert set(COMMON["sandbox"]["deny"]) <= deny_write
    assert set(COMMON["sandbox"]["write_deny_extra"]) <= deny_write
    assert len(fs["denyWrite"]) == len(deny_write), "denyWrite に重複がある"


def test_claude_deny_write_does_not_block_home_wholesale():
    # 書き込みは元から whitelist (cwd + temp + allowWrite) なので、
    # denyWrite にホーム全体を入れると allowWrite ごと潰しかねない。
    fs = gen.build_claude_sandbox(COMMON)["filesystem"]
    assert "~/" not in fs["denyWrite"]


def test_build_claude_sandbox_dedupes_overlap():
    common = {
        "sandbox": {
            "deny": ["~/.ssh", "~/.env"],
            "write_deny_extra": ["~/.ssh", "~/.bashrc"],
        }
    }
    fs = gen.build_claude_sandbox(common)["filesystem"]
    assert fs["denyWrite"] == ["~/.ssh", "~/.env", "~/.bashrc"]
    assert fs["denyRead"] == ["~/", "~/.ssh", "~/.env"]


def test_build_claude_sandbox_empty_section():
    assert gen.build_claude_sandbox({}) == {
        "enabled": True,
        "filesystem": {
            "denyRead": ["~/"],
            "allowRead": [],
            "denyWrite": [],
            "allowWrite": [],
        },
    }


# ---------------------------------------------------------------------------
# merge_claude_settings() への統合
# ---------------------------------------------------------------------------

def test_merge_claude_settings_includes_sandbox():
    merged = gen.merge_claude_settings({}, COMMON)
    assert merged["sandbox"]["enabled"] is True
    assert merged["sandbox"]["filesystem"]["allowRead"]


def test_merge_claude_settings_preserves_other_keys():
    existing = {"someOtherUserKey": "keep-me", "sandbox": {"enabled": False}}
    merged = gen.merge_claude_settings(existing, COMMON)
    assert merged["someOtherUserKey"] == "keep-me"
    # sandbox は common.toml 由来で常に全置換される (enabled=True を強制)
    assert merged["sandbox"]["enabled"] is True


# ---------------------------------------------------------------------------
# Copilot sandbox (userPolicy.filesystem.deniedPaths)
# ---------------------------------------------------------------------------

# Copilot の deniedPaths は read/write の区別が無く完全遮断になるため、
# 通常の開発で「読む」必要があるファイルを入れてはいけない。
# 入れると git / hook / シェル起動が壊れる (common.toml のコメント参照)。
COPILOT_DENY_FORBIDDEN = (
    "~/.gitconfig",
    "~/.copilot/hooks",
    "~/.copilot/permissions-config.json",
    "~/.config/agents",
    "~/.bashrc",
    "~/.zshrc",
    "~/.zshenv",
)


def test_copilot_deny_excludes_read_required_files():
    paths = set(COMMON["sandbox"]["deny"])
    for forbidden in COPILOT_DENY_FORBIDDEN:
        assert forbidden not in paths, (
            f"{forbidden} は Copilot では read も遮断され通常操作が壊れるため "
            "[sandbox].deny に入れてはいけない (write 禁止は write_deny_extra へ)"
        )


def test_copilot_sandbox_expands_to_absolute_paths():
    fs = gen.build_copilot_sandbox(None, COMMON)["userPolicy"]["filesystem"]
    denied = fs["deniedPaths"]
    assert denied, "deniedPaths が空"
    for path in denied:
        assert path.startswith("/"), f"絶対パスでない: {path}"
        assert "~" not in path, f"チルダが残っている: {path}"
        assert "*" not in path, f"Copilot はワイルドカード非対応: {path}"


def test_copilot_sandbox_drops_wildcard_entries():
    # deny に wildcard を書いても Copilot 側からは落とされること。
    common = {"sandbox": {"deny": ["~/.ssh", "~/**/.env", "~/.netrc"]}}
    fs = gen.build_copilot_sandbox(None, common)["userPolicy"]["filesystem"]
    assert len(fs["deniedPaths"]) == 2
    assert not any(".env" in p for p in fs["deniedPaths"])


def test_copilot_sandbox_does_not_receive_claude_allow_lists():
    # read_allow / write_allow は Claude への dev-tool 補償であり、
    # deny-by-default の Copilot に渡すと防御を弱めてしまう。
    fs = gen.build_copilot_sandbox(None, COMMON)["userPolicy"]["filesystem"]
    assert fs.get("readonlyPaths", []) == []
    assert fs.get("readwritePaths", []) == []


def test_copilot_sandbox_enables_and_dedupes():
    common = {"sandbox": {"deny": ["~/.ssh", "~/.ssh", "~/.netrc"]}}
    sandbox = gen.build_copilot_sandbox(None, common)
    assert sandbox["enabled"] is True
    assert len(sandbox["userPolicy"]["filesystem"]["deniedPaths"]) == 2


def test_copilot_sandbox_preserves_allow_lists_and_behavior_keys():
    # readwritePaths / readonlyPaths は /sandbox config の TUI から手で足す
    # 許可リストなので生成側で消さない。network 等の挙動設定にも触れない。
    existing = {
        "allowBypass": True,
        "allowDevToolAccess": True,
        "auth": {"git": True, "gh": True},
        "userPolicy": {
            "filesystem": {
                "readwritePaths": ["/home/u/work"],
                "readonlyPaths": ["/home/u/src"],
                "deniedPaths": ["/stale/entry"],
            },
            "network": {"allowOutbound": True, "allowLocalNetwork": False},
        },
    }
    sandbox = gen.build_copilot_sandbox(existing, COMMON)
    fs = sandbox["userPolicy"]["filesystem"]
    assert fs["readwritePaths"] == ["/home/u/work"]
    assert fs["readonlyPaths"] == ["/home/u/src"]
    assert "/stale/entry" not in fs["deniedPaths"], "deniedPaths は生成側が全置換する"
    assert sandbox["allowBypass"] is True
    assert sandbox["allowDevToolAccess"] is True
    assert sandbox["auth"] == {"git": True, "gh": True}
    assert sandbox["userPolicy"]["network"] == {
        "allowOutbound": True,
        "allowLocalNetwork": False,
    }


def test_merge_copilot_settings_includes_sandbox():
    merged = gen.merge_copilot_settings({}, COMMON)
    assert merged["sandbox"]["enabled"] is True
    assert merged["sandbox"]["userPolicy"]["filesystem"]["deniedPaths"]


# ---------------------------------------------------------------------------
# 両 CLI の整合 (whitelist モデルで揃っていること)
# ---------------------------------------------------------------------------

def test_both_clis_share_the_same_deny_source():
    # deny は共通。Copilot 側は wildcard を落とすだけの関係であること。
    claude = set(gen.build_claude_sandbox(COMMON)["filesystem"]["denyRead"])
    copilot = gen.build_copilot_sandbox(None, COMMON)["userPolicy"]["filesystem"]
    home = str(Path.home())
    for path in copilot["deniedPaths"]:
        assert path.replace(home, "~", 1) in claude, (
            f"Copilot で deny しているのに Claude 側に無い: {path}"
        )


# ---------------------------------------------------------------------------
# ローカル上書き (~/.config/agents/local.toml) — chezmoi 管理外
# ---------------------------------------------------------------------------

def _write_local(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "local.toml"
    p.write_text(body, encoding="utf-8")
    return p


def test_local_overlay_missing_file_is_ignored(tmp_path):
    assert gen.load_local_overlay(tmp_path / "nope.toml") == {}


def test_local_overlay_broken_file_is_ignored(tmp_path, capsys):
    # 壊れたローカル設定で chezmoi apply 全体を落とさないこと。
    p = _write_local(tmp_path, "this is not = valid = toml\n")
    assert gen.load_local_overlay(p) == {}
    assert "warning" in capsys.readouterr().err


def test_local_overlay_appends_read_allow(tmp_path):
    p = _write_local(tmp_path, '[sandbox]\nread_allow = ["/data1", "/data2"]\n')
    merged = gen.apply_local_overlay(COMMON, gen.load_local_overlay(p))
    read_allow = merged["sandbox"]["read_allow"]
    # 共有設定のエントリは残り、ローカル分が後ろに足される
    assert read_allow[: len(COMMON["sandbox"]["read_allow"])] == COMMON["sandbox"]["read_allow"]
    assert read_allow[-2:] == ["/data1", "/data2"]


def test_local_overlay_reaches_generated_claude_settings(tmp_path):
    p = _write_local(tmp_path, '[sandbox]\nread_allow = ["/data1"]\n')
    merged = gen.apply_local_overlay(COMMON, gen.load_local_overlay(p))
    fs = gen.build_claude_sandbox(merged)["filesystem"]
    assert "/data1" in fs["allowRead"]
    # whitelist の骨格は壊れていないこと
    assert fs["denyRead"][0] == "~/"


def test_local_overlay_can_add_deny_but_not_remove(tmp_path):
    p = _write_local(tmp_path, '[sandbox]\ndeny = ["/data1/private"]\n')
    merged = gen.apply_local_overlay(COMMON, gen.load_local_overlay(p))
    deny = merged["sandbox"]["deny"]
    assert "/data1/private" in deny
    # 共有設定の deny が消えていないこと (追記のみ)
    assert set(COMMON["sandbox"]["deny"]) <= set(deny)


def test_local_overlay_does_not_mutate_shared_common(tmp_path):
    before = list(COMMON["sandbox"]["read_allow"])
    p = _write_local(tmp_path, '[sandbox]\nread_allow = ["/data1"]\n')
    gen.apply_local_overlay(COMMON, gen.load_local_overlay(p))
    assert COMMON["sandbox"]["read_allow"] == before


def test_local_overlay_ignores_unknown_keys(tmp_path):
    # 想定外のキーで権限を広げられないこと (許可キーは LOCAL_SANDBOX_KEYS のみ)。
    p = _write_local(
        tmp_path, '[sandbox]\nenabled = false\ncopilot_deny_paths = ["/x"]\n'
    )
    merged = gen.apply_local_overlay(COMMON, gen.load_local_overlay(p))
    assert "enabled" not in merged["sandbox"]
    assert "copilot_deny_paths" not in merged["sandbox"]
    assert gen.build_claude_sandbox(merged)["enabled"] is True


def test_local_overlay_path_respects_env(monkeypatch, tmp_path):
    monkeypatch.setenv(gen.LOCAL_OVERLAY_ENV, str(tmp_path / "custom.toml"))
    assert gen.local_overlay_path() == tmp_path / "custom.toml"


def test_local_overlay_default_path_is_outside_chezmoi_source(monkeypatch):
    # chezmoi のソースツリーではなく実ホーム側を見ること
    # (ソース内に置くと chezmoi 管理対象になってしまう)。
    monkeypatch.delenv(gen.LOCAL_OVERLAY_ENV, raising=False)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    path = gen.local_overlay_path()
    assert path.name == "local.toml"
    assert path.parent.name == "agents"
    assert ROOT not in path.parents
