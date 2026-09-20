"""``test/agents/`` 共通の前提。

ここに置くのは「テストの外側の環境が結果を変えてしまう経路」を塞ぐものだけ。
個別の題材に関する fixture は各テストファイルへ置く。
"""

from __future__ import annotations

import os

import pytest


@pytest.fixture(autouse=True)
def neutral_git_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """``GIT_CONFIG_*`` 経由の外部設定を遮断する。

    ★AI CLI のハーネスは ``GIT_CONFIG_COUNT`` と ``GIT_CONFIG_KEY_n`` /
      ``GIT_CONFIG_VALUE_n`` で ``core.excludesFile=/dev/null`` などを注入する。
      これは **リポジトリローカルの ``git config`` より強い**。

    遮断しないと、テストが ``git config core.excludesFile`` で仕込んだ値が
    無視され、``ensure_ignored`` の「既に無視されているか」の判定が
    環境しだいで変わる。実際 AI CLI の中で実行したときだけ
    ``test_ensure_ignored_skips_writing_when_already_ignored`` が落ちていた。

    出典: <https://git-scm.com/docs/git-config#ENVIRONMENT> — 「GIT_CONFIG_COUNT
    ... this is the highest priority」
    """
    raw = os.environ.get("GIT_CONFIG_COUNT")
    if raw is None:
        return

    monkeypatch.delenv("GIT_CONFIG_COUNT", raising=False)
    try:
        count = int(raw)
    except ValueError:
        # 壊れた値なら git 自体が無視する。消す対象も決められないのでここで終わり。
        return

    for index in range(count):
        monkeypatch.delenv(f"GIT_CONFIG_KEY_{index}", raising=False)
        monkeypatch.delenv(f"GIT_CONFIG_VALUE_{index}", raising=False)
