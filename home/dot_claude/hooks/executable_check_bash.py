#!/usr/bin/env python3
"""
Agent (Claude Code / Copilot CLI) PreToolUse hook: Bash コマンドの安全性チェック

危険なパターンを検出して deny (拒否) または ask (ユーザー承認を要求) を返す。

  - deny: 承認の余地なく拒否する。センシティブ情報の露出や壊滅的な削除など
  - ask : エージェントが提案し、ユーザーが承認すればそのまま実行される。
          ファイル削除のような「危険だが承認すれば妥当」な操作に使う

判定の主軸は common.toml の [bash] deny / ask。同じリストから Claude の
permission も生成されるので、ルールは 1 箇所に書けばよい。
permission リストは Claude にしか効かないが、この hook は Copilot にも効く。

出力規約は ``agent_compat.emit_pretool_deny`` / ``emit_pretool_ask`` に委譲する
(両ツール対応)。

fail-closed: ポリシー設定を読めない場合は素通りさせず deny する。

★このファイルには入出力とループだけを置く。判定ルールは lib/bashrules/ にある。
  ルールを足したいときの入口は lib/bashrules/__init__.py を参照。
  コマンド名の前方一致で足りるものは common.toml の [bash] に 1 行書けばよい。
"""
from __future__ import annotations

import contextlib
import signal
import sys
from pathlib import Path

# 検査の上限。これを超えるコマンドは内容を確認できないので拒否する
_MAX_COMMAND_LEN = 10000
# 自前のタイムアウト秒。hook の timeout (30s) より十分手前で打ち切る
_SELF_TIMEOUT_SEC = 10

# 同一ディレクトリの lib/ にあるヘルパを import
sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
from agent_compat import (  # noqa: E402
    emit_pretool_ask,
    emit_pretool_deny,
    get_command,
    normalize_tool_kind,
    read_input,
)

# 判定ルールの読み込み。tables.toml の書式ミスなどで失敗しうるので、ここで
# 落とさず main() へ伝える。import 例外のまま終了すると stdout が空・exit 1 と
# なり、CLI 側は「hook 失敗」として**素通り**してしまう (agent_compat の
# Pattern C)。fail-closed を保つため、必ず deny を出力してから終わる。
_RULES_IMPORT_ERROR: str | None = None
try:
    from bashrules import ASK_CHECKS, DENY_CHECKS, PATH_CHECKS
    from bashrules._shared import (
        expand_cd_targets,
        set_payload_cwd,
        split_heredoc_body,
    )

    # 後方互換の再エクスポート (テストがこの名前で参照する)
    from bashrules.policy import _ASK_EXEMPTIONS  # noqa: F401
    from bashrules.rm import _is_catastrophic_rm_target  # noqa: F401
except Exception as _exc:  # pragma: no cover - 構文エラー・TOML 破損なども拾う
    _RULES_IMPORT_ERROR = f"{type(_exc).__name__}: {_exc}"


def main() -> None:
    # ルールを読めなかったら検査できない。素通りさせずに拒否する
    if _RULES_IMPORT_ERROR:
        emit_pretool_deny(
            "[hook blocked] 検査ルールを読み込めませんでした "
            f"({_RULES_IMPORT_ERROR})。\n"
            "検査できない以上、安全のため拒否しています。\n"
            "~/.claude/hooks/lib/bashrules/ の tables.toml や *.py を確認してください。"
        )

    # ── 自前のタイムアウト ─────────────────────────────────────────
    # hook の実行が設定の timeout を超えると CLI 側は hook をスキップする
    # (= 素通り)。異常に長いコマンドや病的な入力でそうならないよう、
    # 余裕をもって自分で打ち切り、安全側 (deny) に倒す。
    def _on_timeout(signum: int, frame: object) -> None:  # pragma: no cover
        emit_pretool_deny(
            "[hook blocked] コマンドの検査が時間内に終わりませんでした。\n"
            "検査できない以上、安全のため拒否しています。\n"
            "コマンドを短く分割して実行してください。"
        )

    try:
        signal.signal(signal.SIGALRM, _on_timeout)
        signal.alarm(_SELF_TIMEOUT_SEC)
    except (AttributeError, ValueError):  # pragma: no cover - Windows など
        pass

    data = read_input()
    if not isinstance(data, dict):
        # 想定外のペイロードでも落とさない (CLI 側が hook 失敗を素通り扱いに
        # することがあるため、例外で終わらせない)
        sys.exit(0)

    tool_name = data.get("tool_name")
    if not isinstance(tool_name, str):
        sys.exit(0)
    if normalize_tool_kind(tool_name) != "bash":
        sys.exit(0)

    tool_input = data.get("tool_input")
    if not isinstance(tool_input, dict):
        sys.exit(0)
    # workspace の位置。`rm` の承認免除の判定に使う
    payload_cwd = data.get("cwd")
    if isinstance(payload_cwd, str) and payload_cwd:
        set_payload_cwd(payload_cwd)
    cmd = get_command(tool_input)
    if not isinstance(cmd, str) or not cmd:
        sys.exit(0)

    # 長すぎるコマンドは検査コストが跳ね上がる。内容を確認できないので拒否する
    if len(cmd) > _MAX_COMMAND_LEN:
        emit_pretool_deny(
            f"[hook blocked] コマンドが長すぎます ({len(cmd)} 文字)。\n"
            f"{_MAX_COMMAND_LEN} 文字以内に収めるか、スクリプトファイルに書いて"
            "内容を確認できる形にしてください。"
        )

    # heredoc 本文のうち、ファイルに書かれるだけで実行されない部分を外す。
    # ドキュメントに書いた危険なコマンド例で誤検知しないようにするため。
    with contextlib.suppress(Exception):  # 解析できないときは元の文字列で検査
        cmd = split_heredoc_body(cmd)

    for check in DENY_CHECKS:
        try:
            reason = check(cmd)
        except Exception as exc:  # pragma: no cover - 判定不能なら安全側へ
            emit_pretool_deny(
                f"[hook blocked] コマンドの検査に失敗しました ({check.__name__}: {exc})。\n"
                "検査できない以上、安全のため拒否しています。"
            )
        if reason:
            emit_pretool_deny(f"[hook blocked] {reason}")

    # `cd <dir> && cat <relpath>` のように、作業ディレクトリ経由で相対参照する形。
    # パスを結合した変種を作り、パスを見るチェックだけ改めて適用する。
    try:
        cd_variant = expand_cd_targets(cmd)
    except Exception:  # pragma: no cover
        cd_variant = ""
    if cd_variant:
        for check in PATH_CHECKS:
            try:
                reason = check(cd_variant)
            except Exception:  # pragma: no cover
                continue
            if reason:
                emit_pretool_deny(f"[hook blocked] {reason}")

    for check in ASK_CHECKS:
        try:
            reason = check(cmd)
        except Exception as exc:  # pragma: no cover
            emit_pretool_deny(
                f"[hook blocked] コマンドの検査に失敗しました ({check.__name__}: {exc})。\n"
                "検査できない以上、安全のため拒否しています。"
            )
        if reason:
            emit_pretool_ask(f"[hook] 承認が必要です\n{reason}")

    sys.exit(0)


if __name__ == "__main__":
    main()
