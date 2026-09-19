"""common.toml の [bash] deny / ask をコマンドに突き合わせる。

★パターンそのものは ``~/.config/agents/common.toml`` にある。ルールを足す
ときに編集するのは **このファイルではなく common.toml** のほう。
``check_policy_loaded`` は設定を読めなかったときに fail-closed で拒否する。
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from ._shared import _policy
from .rm import _rm_ask_exempt, _rm_ask_hint

# ~/.config/agents/ (chezmoi 管理) にあるポリシーモジュールを import
# AGENTS_CONFIG_DIR で差し替え可能 (テスト・コンテナから repo の実体を指すため)
_AGENTS_DIR = os.environ.get("AGENTS_CONFIG_DIR")


_POLICY_IMPORT_ERROR: str | None = None


@lru_cache(maxsize=1)
def _deny_patterns() -> list[str]:
    return _policy.load_deny()


@lru_cache(maxsize=1)
def _ask_patterns() -> list[str]:
    return _policy.load_ask()


def check_policy_loaded(cmd: str) -> str | None:
    """ポリシー設定を読めないときは fail-closed で拒否する。

    以前は import 失敗時に ``_policy = None`` として全チェックを
    素通りさせていたため、``~/.config/agents/`` の破損 (docs のトラブルシュートに
    ある ``__pycache__`` 由来の import 失敗など) で **全ガードが無言で消えて**いた。
    ここで止めることで、壊れていることが必ず表面化する。

    モジュールが読めても、期待する API やポリシーの中身が欠けていれば同様に拒否する。
    """
    if _policy is None or _POLICY_IMPORT_ERROR is not None:
        detail = f": {_POLICY_IMPORT_ERROR}" if _POLICY_IMPORT_ERROR else ""
        return (
            f"ポリシーモジュールを読み込めませんでした "
            f"({_AGENTS_DIR}/command_policy.py){detail}。\n"
            "安全のため bash コマンドを拒否しています。\n"
            "対処: `chezmoi apply ~/.config/agents` を実行し、"
            f"`{_AGENTS_DIR}/__pycache__/` が残っていれば削除してください。"
        )
    for name in ("normalize", "find_match", "load_deny", "load_ask"):
        if not callable(getattr(_policy, name, None)):
            return (
                f"ポリシーモジュールに `{name}` がありません。\n"
                "安全のため bash コマンドを拒否しています。\n"
                "対処: `chezmoi apply ~/.config/agents` を実行してください。"
            )
    if not Path(_policy.DEFAULT_COMMON_PATH).is_file():
        return (
            f"ポリシー定義が見つかりません ({_policy.DEFAULT_COMMON_PATH})。\n"
            "安全のため bash コマンドを拒否しています。\n"
            "対処: `chezmoi apply ~/.config/agents` を実行してください。"
        )
    # deny / ask が空なら、設定が壊れているか読めていない
    try:
        deny = _deny_patterns()
        ask = _ask_patterns()
    except Exception as exc:
        return (
            f"ポリシー定義を解釈できませんでした ({exc})。\n"
            "安全のため bash コマンドを拒否しています。"
        )
    if not isinstance(deny, list) or not isinstance(ask, list):
        return (
            "ポリシー定義の deny / ask がリストではありません。\n"
            "安全のため bash コマンドを拒否しています。"
        )
    if not deny:
        return (
            f"ポリシー定義に [bash] deny がありません ({_policy.DEFAULT_COMMON_PATH})。\n"
            "設定が壊れている可能性があるため、安全のため拒否しています。\n"
            "対処: `chezmoi apply ~/.config/agents` を実行してください。"
        )
    return None


def check_policy_deny(cmd: str) -> str | None:
    """common.toml の bash.deny に該当すれば block する.

    Claude Code permission リストの既知バグ (cd && bypass, git -C bypass,
    compound 命令の個別評価欠如) に対する最終防波堤。shell command を
    normalize (cd, git -C, compound 分割) してから pattern match する。
    """
    patterns = _deny_patterns()
    matched = _policy.find_match(cmd, patterns)
    if matched:
        return (
            f"`{matched}` は deny パターンに一致するためブロックされました。\n"
            "このコマンドは common.toml の [bash] deny で禁止されています。"
        )
    return None


def check_policy_ask(cmd: str) -> str | None:
    """common.toml の bash.ask に該当すればユーザー承認を要求する.

    deny と違い、ユーザーが承認すればそのまま実行される。
    deny チェックの後に評価されるので、より具体的な deny パターン
    (例: ``git reset --hard``) が一般形の ask (``git reset``) に優先する。

    ``_ASK_EXEMPTIONS`` に登録したパターンは、条件を満たすときだけ承認を
    省いて auto / assisted の判定へ委ねる。
    """
    patterns = _ask_patterns()
    matched = _policy.find_match(cmd, patterns)
    if matched:
        exemption = _ASK_EXEMPTIONS.get(matched.split()[0])
        if exemption is not None and exemption(cmd):
            return None
        hint = _rm_ask_hint(cmd) if matched.split()[0] == "rm" else ""
        return (
            f"`{matched}` は承認が必要な操作です (common.toml の [bash] ask)。\n"
            f"実行しようとしているコマンド: {cmd.strip()[:200]}\n"
            f"内容を確認して問題なければ承認してください。{hint}"
        )
    return None


# ask を省いてよい条件。パターンの先頭トークンで引く
_ASK_EXEMPTIONS = {"rm": _rm_ask_exempt}
