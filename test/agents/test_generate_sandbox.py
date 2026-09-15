"""Tests for sandbox settings generation in scripts/agents/generate.py.

Run with: ``uv run --with pytest --no-project pytest test/agents/`` or
``python3 -m pytest test/agents/``.
"""

from __future__ import annotations

import copy
import os
import sys
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "agents"))

import generate as gen  # noqa: E402

COMMON_PATH = ROOT / "home" / "dot_config" / "agents" / "common.toml"


def load_common() -> dict:
    with COMMON_PATH.open("rb") as f:
        return tomllib.load(f)


COMMON = load_common()

SANDBOX_KEYS = (
    "deny",
    "claude_write_deny",
    "claude_read_allow",
    "claude_write_allow",
    "copilot_read_allow",
    "copilot_write_allow",
)


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
            assert path.startswith(("~/", "/")), (
                f"[sandbox].{key} の '{path}' が '~/' でも '/' でも始まって"
                "いない。user 設定では無印パスが ~/.claude 基準になるため"
                "意図しない範囲になる。"
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
                "whitelist (claude_read_allow) の側で絞ること。"
            )


def test_read_allow_has_no_wildcards():
    # 穴を開ける側に glob を使うと意図より広く開きやすいので禁止する。
    for path in COMMON["sandbox"]["claude_read_allow"] + COMMON["sandbox"]["claude_write_allow"]:
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
    assert fs["allowRead"] == COMMON["sandbox"]["claude_read_allow"]


def test_claude_allow_write_matches_common():
    fs = gen.build_claude_sandbox(COMMON)["filesystem"]
    assert fs["allowWrite"] == COMMON["sandbox"]["claude_write_allow"]


def test_claude_deny_write_covers_deny_and_extra():
    fs = gen.build_claude_sandbox(COMMON)["filesystem"]
    deny_write = set(fs["denyWrite"])
    assert set(COMMON["sandbox"]["deny"]) <= deny_write
    assert set(COMMON["sandbox"]["claude_write_deny"]) <= deny_write
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
            "claude_write_deny": ["~/.ssh", "~/.bashrc"],
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
        "network": {"allowedDomains": []},
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
            "[sandbox].deny に入れてはいけない (write 禁止は claude_write_deny へ)"
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
    assert "/home/u/work" in fs["readwritePaths"]
    assert "/home/u/src" in fs["readonlyPaths"]
    assert "/stale/entry" not in fs["deniedPaths"], "deniedPaths は生成側が全置換する"
    assert sandbox["allowBypass"] is True
    # COMMON は copilot_allow_dev_tool_access = false を持つので上書きされる
    assert sandbox["allowDevToolAccess"] is False
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
    p = _write_local(tmp_path, '[sandbox]\nclaude_read_allow = ["/data1", "/data2"]\n')
    merged = gen.apply_local_overlay(COMMON, gen.load_local_overlay(p))
    claude_read_allow = merged["sandbox"]["claude_read_allow"]
    # 共有設定のエントリは残り、ローカル分が後ろに足される
    shared = COMMON["sandbox"]["claude_read_allow"]
    assert claude_read_allow[: len(shared)] == shared
    assert claude_read_allow[-2:] == ["/data1", "/data2"]


def test_local_overlay_reaches_generated_claude_settings(tmp_path):
    p = _write_local(tmp_path, '[sandbox]\nclaude_read_allow = ["/data1"]\n')
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
    before = list(COMMON["sandbox"]["claude_read_allow"])
    p = _write_local(tmp_path, '[sandbox]\nclaude_read_allow = ["/data1"]\n')
    gen.apply_local_overlay(COMMON, gen.load_local_overlay(p))
    assert COMMON["sandbox"]["claude_read_allow"] == before


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


# ---------------------------------------------------------------------------
# Claude が Copilot より緩くならないこと
# ---------------------------------------------------------------------------
# 運用方針: Copilot は家用で緩め、Claude は会社用で厳し目。
# claude_read_allow は Copilot の allowDevToolAccess が自動許可する範囲の代替なので、
# そこを超えて「他のリポジトリ」まで開けると方針が逆転してしまう。
# 実測した Copilot の実効ポリシーには $HOME 配下の作業ディレクトリ許可は無く、
# skill も ~/.agents/skills と ~/.claude/skills だけが read-only で出る。

# 作業中のプロジェクトは cwd として自動許可されるため、ここを開ける必要は無い。
# 恒久的に必要なら ~/.config/agents/local.toml、一時的なら --add-dir を使う。
WORKSPACE_ROOTS = ("~/src", "~/sandbox", "~/worktrees", "~/papers")


def test_read_allow_does_not_open_other_repositories():
    claude_read_allow = set(COMMON["sandbox"]["claude_read_allow"])
    for root in WORKSPACE_ROOTS:
        assert root not in claude_read_allow, (
            f"{root} を claude_read_allow に入れると、作業中でない他リポジトリまで "
            "読めてしまい Copilot より緩くなる。cwd は自動許可されるので不要。"
        )


def test_read_allow_does_not_open_whole_agent_config_dirs():
    # AI CLI の設定ディレクトリ全体を開けない (skill のサブディレクトリのみ)。
    claude_read_allow = set(COMMON["sandbox"]["claude_read_allow"])
    for d in ("~/.claude", "~/.copilot", "~/.codex", "~/.gemini", "~/.agents"):
        assert d not in claude_read_allow, (
            f"{d} 全体ではなく skill のサブディレクトリだけを許可すること"
        )


def test_secret_config_dirs_are_denied_even_though_config_is_allowed():
    # ~/.config を丸ごと開けている以上、その中の秘密は個別に塞ぐ必要がある。
    deny = set(COMMON["sandbox"]["deny"])
    assert "~/.config" in COMMON["sandbox"]["claude_read_allow"]
    for secret_path in ("~/.config/sops/age", "~/.config/gh/hosts.yml"):
        assert secret_path in deny, f"{secret_path} が deny に無い"
    assert any("Bitwarden" in p for p in deny), "Bitwarden CLI の設定が deny に無い"


# ---------------------------------------------------------------------------
# sandbox.network (Claude のみ)
# ---------------------------------------------------------------------------

def test_claude_sandbox_network_mirrors_web_allow_domains():
    network = gen.build_claude_sandbox(COMMON)["network"]
    # [web] の分は先頭に、[sandbox] claude_network_allow の分が後ろに続く
    web_domains = COMMON["web"]["allow_domains"]
    assert network["allowedDomains"][: len(web_domains)] == web_domains


def test_claude_sandbox_network_omits_empty_denied_domains():
    # 空の deniedDomains を書くと意味が無いので出さない。
    network = gen.build_claude_sandbox({"web": {"allow_domains": ["a.example"]}})[
        "network"
    ]
    assert "deniedDomains" not in network


def test_claude_sandbox_network_emits_denied_domains_when_set():
    common = {"web": {"allow_domains": ["*.example.com"], "deny_domains": ["bad.example.com"]}}
    network = gen.build_claude_sandbox(common)["network"]
    assert network["deniedDomains"] == ["bad.example.com"]


def test_web_wildcards_are_sandbox_compatible():
    # sandbox に効く wildcard は先頭の "*." と単独の "*" だけ。
    # "example.*" のような形は WebFetch には効くが sandbox 側は無視するため、
    # 気付かずに穴が開いたつもりになるのを防ぐ。
    for domain in COMMON["web"]["allow_domains"] + COMMON["web"]["deny_domains"]:
        if "*" not in domain:
            continue
        assert domain == "*" or domain.startswith("*."), (
            f"'{domain}' の wildcard は sandbox に効かない。"
            "先頭の '*.' か単独の '*' だけが有効。"
        )


def test_merge_claude_settings_includes_network():
    merged = gen.merge_claude_settings({}, COMMON)
    assert merged["sandbox"]["network"]["allowedDomains"]


def test_claude_sandbox_network_strict_allowlist_enabled():
    # claude_network_strict = true で許可外ドメインが拒否される (v2.1.219+ が必要)。
    assert COMMON["sandbox"]["claude_network_strict"] is True
    assert gen.build_claude_sandbox(COMMON)["network"]["strictAllowlist"] is True


def test_claude_sandbox_network_strict_omitted_when_false():
    network = gen.build_claude_sandbox({"sandbox": {"claude_network_strict": False}})["network"]
    assert "strictAllowlist" not in network


def test_claude_sandbox_network_merges_web_and_network_allow():
    network = gen.build_claude_sandbox(COMMON)["network"]
    allowed = network["allowedDomains"]
    for domain in COMMON["web"]["allow_domains"]:
        assert domain in allowed
    for domain in COMMON["sandbox"]["claude_network_allow"]:
        assert domain in allowed
    assert len(allowed) == len(set(allowed)), "allowedDomains に重複がある"


def test_network_allow_is_disjoint_from_web_allow_domains():
    # 役割が違う 2 つのリスト (WebFetch 用 / shell 通信用) なので、
    # 重複して書かれていたらどちらかに寄せるべきサイン。
    web = set(COMMON["web"]["allow_domains"])
    shell = set(COMMON["sandbox"]["claude_network_allow"])
    assert not (web & shell), f"両方に書かれている: {sorted(web & shell)}"


def test_network_allow_has_no_wildcards():
    # shell 通信先は具体的なホストを書く (wildcard は [web] 側で足りている)。
    for domain in COMMON["sandbox"]["claude_network_allow"]:
        assert "*" not in domain, f"claude_network_allow に wildcard: {domain}"


# ---------------------------------------------------------------------------
# sandbox.seccomp (mise 導入分への橋渡し)
# ---------------------------------------------------------------------------
# Claude は apply-seccomp を npm のグローバル領域でしか自動検出しないが、
# このリポジトリは mise で入れる (npm install -g は [bash] deny)。
# mise は独自ディレクトリへ隔離するため、公式の代替手段である
# sandbox.seccomp.applyPath でパスを直接指す。

def test_seccomp_arch_maps_known_machines():
    assert gen.seccomp_arch("x86_64") == "x64"
    assert gen.seccomp_arch("amd64") == "x64"
    assert gen.seccomp_arch("aarch64") == "arm64"
    assert gen.seccomp_arch("arm64") == "arm64"


def test_seccomp_arch_returns_none_for_unsupported():
    # 非対応アーキではパスを組み立てない (誤ったパスを設定しない)。
    assert gen.seccomp_arch("riscv64") is None
    assert gen.seccomp_arch("i686") is None


def test_common_toml_declares_seccomp_apply_path():
    template = COMMON["sandbox"]["seccomp_apply_path"]
    assert "{arch}" in template, "アーキテクチャのプレースホルダが無い"
    assert template.startswith("~/"), "ホーム相対で書くこと"
    assert template.endswith("apply-seccomp")
    # mise の latest エイリアス経由にしてバージョン更新に追従させる
    assert "/latest/" in template


def test_build_seccomp_config_returns_none_when_missing(tmp_path):
    common = {
        "sandbox": {"seccomp_apply_path": str(tmp_path / "nope" / "{arch}" / "apply-seccomp")}
    }
    assert gen.build_seccomp_config(common, machine="x86_64") is None


def test_build_seccomp_config_returns_none_for_unsupported_arch():
    assert gen.build_seccomp_config(COMMON, machine="riscv64") is None


def test_build_seccomp_config_returns_none_without_declaration():
    assert gen.build_seccomp_config({"sandbox": {}}) is None


def test_build_seccomp_config_uses_existing_binary(tmp_path):
    binary = tmp_path / "x64" / "apply-seccomp"
    binary.parent.mkdir(parents=True)
    binary.write_text("#!/bin/sh\n", encoding="utf-8")
    common = {"sandbox": {"seccomp_apply_path": str(tmp_path / "{arch}" / "apply-seccomp")}}
    assert gen.build_seccomp_config(common, machine="x86_64") == {
        "applyPath": str(binary)
    }


def test_claude_sandbox_omits_seccomp_when_unavailable(tmp_path):
    # 未導入のマシンでは seccomp キー自体を出さず、Claude の自動検出に任せる。
    common = {
        "sandbox": {"seccomp_apply_path": str(tmp_path / "{arch}" / "apply-seccomp")},
    }
    assert "seccomp" not in gen.build_claude_sandbox(common)


# ---------------------------------------------------------------------------
# キー命名の規則
# ---------------------------------------------------------------------------

def test_sandbox_keys_are_known():
    unknown = set(COMMON["sandbox"]) - gen.KNOWN_SANDBOX_KEYS
    assert not unknown, f"[sandbox] に未知のキー: {sorted(unknown)}"


def test_cli_specific_keys_are_prefixed_with_the_cli_name():
    for key in gen.CLAUDE_SANDBOX_KEYS:
        assert key.startswith("claude_"), f"Claude 専用キーに接頭辞が無い: {key}"
    for key in gen.COPILOT_SANDBOX_KEYS:
        assert key.startswith("copilot_"), f"Copilot 専用キーに接頭辞が無い: {key}"


def test_shared_keys_have_no_cli_prefix():
    for key in gen.SHARED_SANDBOX_KEYS:
        assert not key.startswith(("claude_", "copilot_"))


def test_read_write_allow_is_symmetric_between_clis():
    for suffix in ("read_allow", "write_allow"):
        assert f"claude_{suffix}" in gen.CLAUDE_SANDBOX_KEYS
        assert f"copilot_{suffix}" in gen.COPILOT_SANDBOX_KEYS


def test_validate_sandbox_keys_rejects_legacy_names():
    for legacy in ("read_allow", "write_allow", "write_deny_extra", "network_allow"):
        with pytest.raises(ValueError) as excinfo:
            gen.validate_sandbox_keys({"sandbox": {"deny": [], legacy: ["~/x"]}})
        assert legacy in str(excinfo.value)


def test_validate_sandbox_keys_accepts_the_real_config():
    gen.validate_sandbox_keys(COMMON)


def test_file_section_keys_are_all_claude_prefixed():
    for key in COMMON["file"]:
        assert key.startswith("claude_"), f"[file] の {key} に接頭辞が無い"


def test_file_section_keys_are_known():
    unknown = set(COMMON["file"]) - gen.KNOWN_FILE_KEYS
    assert not unknown, f"[file] に未知のキー: {sorted(unknown)}"


def test_validate_rejects_legacy_file_names():
    for legacy in ("read_allow", "read_deny_globs", "write_ask_globs"):
        with pytest.raises(ValueError) as excinfo:
            gen.validate_sandbox_keys({"file": {legacy: ["x"]}})
        assert legacy in str(excinfo.value)


def test_file_deny_globs_have_a_sandbox_counterpart_for_copilot():
    sandbox_deny = " ".join(COMMON["sandbox"]["deny"])
    for fragment in (".ssh", ".gnupg", "sops/age", ".netrc", ".npmrc", ".pypirc"):
        assert fragment in sandbox_deny


def test_local_overlay_keys_are_known_sandbox_keys():
    assert set(gen.LOCAL_SANDBOX_KEYS) <= gen.KNOWN_SANDBOX_KEYS


def test_absolute_sandbox_paths_stay_outside_home():
    home = os.path.expanduser("~")
    for key in SANDBOX_KEYS:
        for path in COMMON["sandbox"][key]:
            if path.startswith("/"):
                assert not path.startswith(home), f"{path} はホーム配下"


# ---------------------------------------------------------------------------
# Copilot の許可リスト
# ---------------------------------------------------------------------------

def test_copilot_sandbox_reads_only_the_copilot_keys():
    # 生成側が claude_* を誤って流用していないこと。
    #
    # ★dev-tool access を切った結果、両 CLI の許可内容は **ほぼ同じになる**
    #   (自動付与が無くなれば同じ補償が要るため)。したがって
    #   「互いに素であること」ではなく「参照するキーが正しいこと」を固定する。
    common = {
        "sandbox": {
            "deny": [],
            "claude_read_allow": ["/claude-only-ro"],
            "claude_write_allow": ["/claude-only-rw"],
            "copilot_read_allow": ["/copilot-ro"],
            "copilot_write_allow": ["/copilot-rw"],
        }
    }
    fs = gen.build_copilot_sandbox(None, common)["userPolicy"]["filesystem"]
    assert fs["readonlyPaths"] == ["/copilot-ro"]
    assert fs["readwritePaths"] == ["/copilot-rw"]

    claude_fs = gen.build_claude_sandbox(common)["filesystem"]
    assert claude_fs["allowRead"] == ["/claude-only-ro"]
    assert claude_fs["allowWrite"] == ["/claude-only-rw"]


def test_copilot_read_and_write_allow_must_not_overlap():
    # 同一パスが RO と RW の両方にあると、sandbox 実装が「最も制限的な意図」
    # として RO へ解決し write が無言で消える (github/copilot-cli#4846)。
    # 生成時に落として気付けるようにする。
    common = {
        "sandbox": {
            "deny": [],
            "copilot_read_allow": ["~/.cache", "~/.local"],
            "copilot_write_allow": ["~/.cache"],
        }
    }
    with pytest.raises(ValueError, match=r"copilot_read_allow"):
        gen.build_copilot_sandbox(None, common)


def test_copilot_parent_child_paths_are_allowed_to_coexist():
    # 親子は「より具体的なパスが勝つ」規則で解決されるので衝突ではない。
    common = {
        "sandbox": {
            "deny": [],
            "copilot_read_allow": ["~/.local"],
            "copilot_write_allow": ["~/.local/state"],
        }
    }
    fs = gen.build_copilot_sandbox(None, common)["userPolicy"]["filesystem"]
    assert fs["readonlyPaths"] == [gen.expand_user("~/.local")]
    assert fs["readwritePaths"] == [gen.expand_user("~/.local/state")]


def test_real_common_toml_has_no_copilot_allow_overlap():
    ro = set(COMMON["sandbox"]["copilot_read_allow"])
    rw = set(COMMON["sandbox"]["copilot_write_allow"])
    assert not (ro & rw)


def test_copilot_sandbox_grants_uv_paths_so_uv_run_works():
    # uv が動かないとこのリポジトリの検証コマンドが一切通らない。
    # interpreter は ~/.local 配下、キャッシュは ~/.cache 配下で賄う。
    fs = gen.build_copilot_sandbox(None, COMMON)["userPolicy"]["filesystem"]
    assert gen.expand_user("~/.cache") in fs["readwritePaths"]
    assert gen.expand_user("~/.local") in fs["readonlyPaths"]


def test_copilot_sandbox_grants_the_mise_toolchain():
    # mise 本体 (~/.local/bin) と installs はどちらも ~/.local に含まれる。
    # bind-mount は symlink を辿った実体を貼るため、PATH 上の <tool>/latest/bin
    # だけを貼ると latest 自体が消える。親ごと許可すれば素通しになる。
    fs = gen.build_copilot_sandbox(None, COMMON)["userPolicy"]["filesystem"]
    assert gen.expand_user("~/.local") in fs["readonlyPaths"]


def test_copilot_dev_tool_access_is_disabled():
    # 自動付与はユーザ指定の read-write を read-only で上書きするため切る
    # (github/copilot-cli#4846)。切った分は copilot_read_allow で明示する。
    assert gen.build_copilot_sandbox(None, COMMON)["allowDevToolAccess"] is False


def test_dev_tool_access_key_is_optional():
    # キーが無い設定では allowDevToolAccess を出力せず、既存値を温存する
    common = {"sandbox": {"deny": []}}
    assert "allowDevToolAccess" not in gen.build_copilot_sandbox(None, common)
    existing = {"allowDevToolAccess": True}
    assert gen.build_copilot_sandbox(existing, common)["allowDevToolAccess"] is True


def test_mise_installs_is_never_writable():
    # write を与えると PATH 上の全ツールを差し替えられる。
    fs = gen.build_copilot_sandbox(None, COMMON)["userPolicy"]["filesystem"]
    for path in fs.get("readwritePaths", []):
        assert "mise" not in path, f"mise 配下に write を与えている: {path}"
        assert not path.endswith("/.local"), "~/.local 全体に write を与えている"


def test_copilot_sandbox_grants_system_build_paths():
    fs = gen.build_copilot_sandbox(None, COMMON)["userPolicy"]["filesystem"]
    for path in ("/usr/include", "/usr/local", "/usr/src", "/opt"):
        assert path in fs["readonlyPaths"], f"{path} が読めない"


def test_system_build_paths_are_not_writable():
    fs = gen.build_copilot_sandbox(None, COMMON)["userPolicy"]["filesystem"]
    writable = fs.get("readwritePaths", [])
    for path in ("/usr/include", "/usr/local", "/usr/src", "/opt"):
        assert path not in writable


def test_claude_does_not_need_system_path_entries():
    fs = gen.build_claude_sandbox(COMMON)["filesystem"]
    for prefix in ("/usr", "/opt"):
        assert not any(p.startswith(prefix) for p in fs["denyRead"])
        assert not any(p.startswith(prefix) for p in fs["allowRead"])


def test_copilot_allow_lists_merge_instead_of_replacing():
    common = {
        "sandbox": {
            "deny": [],
            "copilot_read_allow": ["~/ro", "~/dup"],
            "copilot_write_allow": ["~/rw"],
        }
    }
    existing = {
        "userPolicy": {
            "filesystem": {
                "readonlyPaths": ["/manual/ro", gen.expand_user("~/dup")],
                "readwritePaths": ["/manual/rw"],
            }
        }
    }
    fs = gen.build_copilot_sandbox(existing, common)["userPolicy"]["filesystem"]
    assert "/manual/ro" in fs["readonlyPaths"]
    assert "/manual/rw" in fs["readwritePaths"]
    assert fs["readonlyPaths"].count(gen.expand_user("~/dup")) == 1


def test_copilot_allow_lists_drop_wildcards():
    common = {
        "sandbox": {
            "deny": [],
            "copilot_read_allow": ["~/ok", "~/**/bad"],
            "copilot_write_allow": ["~/w?ld"],
        }
    }
    fs = gen.build_copilot_sandbox(None, common)["userPolicy"]["filesystem"]
    assert fs["readonlyPaths"] == [gen.expand_user("~/ok")]
    assert fs.get("readwritePaths", []) == []


def test_copilot_allow_lists_absent_when_unconfigured():
    common = {"sandbox": {"deny": ["~/.ssh"]}}
    fs = gen.build_copilot_sandbox(None, common)["userPolicy"]["filesystem"]
    assert "readonlyPaths" not in fs
    assert "readwritePaths" not in fs


# ---------------------------------------------------------------------------
# local.toml の [[copilot.locations]]
# ---------------------------------------------------------------------------

def test_local_overlay_adds_a_new_location():
    common = {"copilot": {"locations": [{"path": "~/shared"}]}}
    local = {"copilot": {"locations": [
        {"path": "~/src/proj", "allowed_directories": ["/data1"]}]}}
    merged = gen.apply_local_overlay(common, local)
    assert [loc["path"] for loc in merged["copilot"]["locations"]] == [
        "~/shared", "~/src/proj"]


def test_local_overlay_merges_into_an_existing_location():
    common = {"copilot": {"locations": [{
        "path": "~/src/proj",
        "approvals": [{"kind": "write"}],
        "allowed_directories": ["/shared"],
    }]}}
    local = {"copilot": {"locations": [
        {"path": "~/src/proj", "allowed_directories": ["/data1"]}]}}
    entry = gen.apply_local_overlay(common, local)["copilot"]["locations"][0]
    assert entry["allowed_directories"] == ["/shared", "/data1"]
    assert entry["approvals"] == [{"kind": "write"}]


def test_local_overlay_does_not_mutate_shared_config():
    common = {"copilot": {"locations": [{"path": "~/src/proj"}]}}
    before = copy.deepcopy(common)
    gen.apply_local_overlay(common, {"copilot": {"locations": [
        {"path": "~/src/proj", "allowed_directories": ["/data1"]}]}})
    assert common == before


def test_local_overlay_warns_about_location_without_path(capsys):
    gen.apply_local_overlay(
        {}, {"copilot": {"locations": [{"allowed_directories": ["/data1"]}]}})
    assert "path" in capsys.readouterr().err


def test_local_overlay_warns_about_unknown_location_keys(capsys):
    gen.apply_local_overlay(
        {}, {"copilot": {"locations": [
            {"path": "~/p", "denied_directories": ["/x"]}]}})
    assert "denied_directories" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# プロジェクト単位の追加許可 (allowed_directories)
# ---------------------------------------------------------------------------

def test_allowed_directories_are_scoped_to_one_location(tmp_path):
    data = tmp_path / "data1"
    data.mkdir()
    common = {"bash": {"allow": []}, "copilot": {"locations": [
        {"path": str(tmp_path / "proj"), "allowed_directories": [str(data)]},
        {"path": str(tmp_path / "other")},
    ]}}
    locations = gen.build_copilot_locations(common)["locations"]
    assert locations[str(tmp_path / "proj")]["allowed_directories"] == [str(data)]
    assert "allowed_directories" not in locations[str(tmp_path / "other")]


def test_allowed_directories_drop_paths_that_do_not_exist(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    common = {"bash": {"allow": []}, "copilot": {"locations": [{
        "path": str(tmp_path / "proj"),
        "allowed_directories": [str(real), str(tmp_path / "missing")],
    }]}}
    locations = gen.build_copilot_locations(common)["locations"]
    assert locations[str(tmp_path / "proj")]["allowed_directories"] == [str(real)]


def test_locations_without_allowed_directories_stay_unchanged():
    locations = gen.build_copilot_locations(COMMON)["locations"]
    for entry in locations.values():
        assert "tool_approvals" in entry
        assert "allowed_directories" not in entry


# ---------------------------------------------------------------------------
# permissions-config.json は CLI 自身が書き込む
# ---------------------------------------------------------------------------

SHARED = {
    "bash": {"allow": []},
    "copilot": {"locations": [{"path": "/repo", "approvals": [{"kind": "write"}]}]},
}


def test_perms_merge_keeps_locations_the_cli_saved():
    existing = {"locations": {"/other": {
        "tool_approvals": [{"kind": "write"}],
        "allowed_directories": ["/data1/other"],
    }}}
    out = gen.merge_copilot_perms(existing, SHARED)
    assert "/other" in out["locations"]
    assert out["locations"]["/other"]["allowed_directories"] == ["/data1/other"]


def test_perms_merge_unions_approvals_in_the_same_location():
    existing = {"locations": {"/repo": {
        "tool_approvals": [{"kind": "commands", "commandIdentifiers": ["pytest"]}],
        "allowed_directories": ["/data1"],
    }}}
    out = gen.merge_copilot_perms(existing, SHARED)
    approvals = out["locations"]["/repo"]["tool_approvals"]
    assert {"kind": "commands", "commandIdentifiers": ["pytest"]} in approvals
    assert {"kind": "write"} in approvals
    assert out["locations"]["/repo"]["allowed_directories"] == ["/data1"]


def test_perms_merge_does_not_duplicate_identical_entries():
    existing = {"locations": {"/repo": {"tool_approvals": [{"kind": "write"}]}}}
    out = gen.merge_copilot_perms(existing, SHARED)
    assert out["locations"]["/repo"]["tool_approvals"].count({"kind": "write"}) == 1


def test_perms_merge_handles_a_missing_or_empty_file():
    for existing in ({}, {"locations": {}}, None):
        assert "/repo" in gen.merge_copilot_perms(existing, SHARED)["locations"]


def test_perms_merge_preserves_unknown_top_level_keys():
    existing = {"locations": {}, "someFutureKey": {"a": 1}}
    assert gen.merge_copilot_perms(existing, SHARED).get("someFutureKey") == {"a": 1}
