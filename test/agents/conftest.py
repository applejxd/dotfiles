"""``test/agents/`` 共通の前提。

ここに置くのは「テストの外側の環境が結果を変えてしまう経路」を塞ぐものだけ。
個別の題材に関する fixture は各テストファイルへ置く。
"""

from __future__ import annotations

import os

import pytest


@pytest.fixture(autouse=True)
def neutral_git_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """実行者の ``GIT_*`` と system / global の git 設定を遮断する。

    ★AI CLI のハーネスは ``GIT_CONFIG_COUNT`` と ``GIT_CONFIG_KEY_n`` /
      ``GIT_CONFIG_VALUE_n`` で ``core.excludesFile=/dev/null`` などを注入する。
      これは **リポジトリローカルの ``git config`` より強い**。
      遮断しないと、テストが ``git config core.excludesFile`` で仕込んだ値が
      無視され、``ensure_ignored`` の「既に無視されているか」の判定が
      環境しだいで変わる。実際 AI CLI の中で実行したときだけ
      ``test_ensure_ignored_skips_writing_when_already_ignored`` が落ちていた。

    ★``GIT_DIR`` / ``GIT_INDEX_FILE`` / ``GIT_WORK_TREE`` が残ると、テストの準備の
      ``git init`` / ``add`` / ``commit`` がテストの外のリポジトリへ書く。
      利用者の ``core.hooksPath`` や ``commit.gpgSign`` が効くと、準備が落ちたり
      実物の hook が走ったりする。

    ``HOME`` / ``XDG_CONFIG_HOME`` は変えない (期待値が実ホームに依存するテストがある)。
    既定の ``core.excludesFile`` (``~/.config/git/ignore``) まで要る準備は、
    その場で ``HOME`` を一時領域へ向ける。

    出典: <https://git-scm.com/docs/git-config#ENVIRONMENT> — 「GIT_CONFIG_COUNT
    ... this is the highest priority」
    """
    for key in [k for k in os.environ if k.startswith("GIT_")]:
        monkeypatch.delenv(key)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)


@pytest.fixture(autouse=True)
def neutral_pi_harness_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """実行者の ``PI_HARNESS_*``・``PI_WORK*``・``ORCA_*``・``PIS_IMAGE_INBOX*`` を遮断する。

    ★フルガード (``pis``) の中で実行すると ``PI_HARNESS_BYPASS=1`` などが子プロセスへ
      引き継がれる。bypass 中は ask が確認なしで通るので、「確認が 1 回出る」ことを
      見る ``test_pi_commit_confirm.py`` が環境しだいで落ちる (実際 23 件落ちた)。
      各テストが必要な値は自分で ``setenv`` する。

    ★作業台帳の旗 (``PI_WORK_TOOL`` など。``pk pi-flags`` が付ける) が残ると、本物の pi を起動する試験で
      ``work`` ツールが加わり、「ガード済みのツールだけ」を見る ``test_pi_settings_launch.py`` などが落ちる。
    """
    prefixes = ("PI_HARNESS_", "ORCA_", "PI_WORK", "PIS_IMAGE_INBOX")
    for key in [k for k in os.environ if k.startswith(prefixes)]:
        monkeypatch.delenv(key)
