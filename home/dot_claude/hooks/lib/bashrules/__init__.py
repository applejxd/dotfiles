"""Bash コマンド検査ルールの登録簿。

``check_bash.py`` はこのパッケージから 3 つのリストを受け取り、順に適用する
だけになっている。**ルールの優先順位を決めるのはこのファイル**。

ルールを足すとき:

1. 内容に合うモジュールへ ``check_xxx(cmd: str) -> str | None`` を書く
     - 任意コード実行         -> ``rules_exec.py``
     - 防御機構・環境の改変   -> ``rules_guard.py``
     - ファイルの読み書き     -> ``rules_files.py``
     - 秘密情報              -> ``secrets.py``
     - curl / wget           -> ``http.py``
     - gh api                -> ``ghapi.py``
     - 削除                  -> ``rm.py``
     - docker                -> ``docker.py``
   拒否したい理由の文字列を返し、問題なければ ``None`` を返す。
2. 下の ``DENY_CHECKS`` か ``ASK_CHECKS`` に 1 行足す。

コマンド名の前方一致で済むものは Python を書く必要はない。
``~/.config/agents/common.toml`` の ``[bash] deny`` / ``ask`` に 1 行足せば
``check_policy_deny`` / ``check_policy_ask`` が拾う。

★リストの順序には意味がある。先に一致したものがユーザーへのメッセージを
  決めるため、具体的な代替案を出せるルールを汎用のものより前に置く。
"""
from __future__ import annotations

from .docker import check_docker_host_escape, check_docker_isolation
from .ghapi import (
    check_gh_api_mutation,
    check_gh_api_sensitive_input,
    check_gh_token_exposure,
)
from .http import (
    check_curl_file_send,
    check_curl_wget_mutation,
    check_http_dangerous_output,
)
from .policy import check_policy_ask, check_policy_deny, check_policy_loaded
from .rm import check_find_dangerous, check_find_root_guard, check_rm_root_guard
from .rules_exec import (
    check_encoded_command,
    check_interpreter_inline_code,
    check_pipe_to_shell,
    check_reverse_shell,
    check_xargs_pipe,
)
from .rules_files import (
    check_archive,
    check_env_exposure,
    check_file_read,
    check_pip_redirect,
)
from .rules_guard import (
    check_block_device_write,
    check_git_config_write,
    check_global_env_mutation,
    check_guard_tampering,
    check_privilege_escalation,
    check_shell_startup_write,
    check_tool_self_update,
)
from .sensitive import check_git_add_sensitive, check_history_access, check_secret_env_echo

# uv 非依存のチェック（常時有効）
#
# DENY_CHECKS が先に評価される。ASK_CHECKS は deny に該当しなかったものだけを
# 対象にするので、例えば `rm -rf /` は root guard (deny) が critical_ask より
# 優先される。
DENY_CHECKS = [
    check_policy_loaded,      # ★最初に実行: 設定が読めないなら fail-closed
    check_rm_root_guard,      # 壊滅的な削除は承認の余地なし
    # 具体的な代替案を返せるチェックは、汎用の policy_deny より先に置く
    # (先に一致したものがメッセージを決めるため)
    check_pip_redirect,       # pip → uv/uvx (プロジェクト種別を問わず全面禁止)
    check_pipe_to_shell,      # curl ... | sh の類
    check_interpreter_inline_code,  # python -c "os.system(...)" の類
    check_git_add_sensitive,  # git add .env の類
    check_secret_env_echo,    # echo $GITHUB_TOKEN の類
    check_gh_token_exposure,  # gh auth status --show-token
    check_gh_api_sensitive_input,  # gh api -F key=@.env / --input .env
    check_history_access,     # history / fc
    check_guard_tampering,    # hook や settings.json の改変
    check_reverse_shell,      # /dev/tcp や nc -e の類
    check_shell_startup_write,  # .bashrc / authorized_keys への追記
    check_http_dangerous_output,  # curl -o / wget -O で起動・認証設定を上書き
    check_privilege_escalation,  # setuid 付与・sudoers 変更
    check_docker_host_escape, # docker run --privileged / -v /:... の権限昇格
    check_tool_self_update,   # mise self-update / implode
    check_encoded_command,    # base64 -d | sh の類
    check_git_config_write,   # git config alias.x / core.hooksPath の類
    check_block_device_write, # dd of=/dev/sda の類
    check_find_root_guard,    # find ~ -delete のような一括削除
    check_policy_deny,        # common.toml の [bash] deny を強制
    check_env_exposure,       # 引数なし環境変数露出は問答無用でブロック
    # `git -C <dir> <sub>` は normalize が `git <sub>` に畳むため
    # check_policy_deny が捕捉する (専用チェックは誤検知しか生まなかった)
    check_file_read,
    check_archive,
    check_curl_file_send,
    check_xargs_pipe,
]

# パスだけを見るチェック。`cd` 展開版に対して二度目の適用をする
PATH_CHECKS = [
    check_file_read,
    check_guard_tampering,
    check_shell_startup_write,
    check_archive,
    check_curl_file_send,
]

# 承認を求めるチェック（ユーザーが許可すればそのまま実行される）
ASK_CHECKS = [
    check_policy_ask,         # common.toml の [bash] ask
    check_gh_api_mutation,    # REST / GraphQL の mutation と判定不能形式
    check_curl_wget_mutation, # curl/wget の mutation と判定不能形式
    check_find_dangerous,     # find -exec rm / -delete によるファイル削除
    check_docker_isolation,   # docker run --network host のような分離の緩和
    check_global_env_mutation,  # mise use -g / cmake --target install
]
