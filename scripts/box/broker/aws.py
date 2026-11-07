"""aws ブローカーの計画。箱へは、読み取り専用ロールの短期認証情報だけが、コンテナ認証情報エンドポイント経由で届く。

経路: 箱の AWS SDK → 127.0.0.1:7111（proxy デバイス）→ ホストの unix ソケット → aws_server → aws sts assume-role。
- ロールの ARN は policy.secrets["aws-role"]（SecretRef）。実行時にだけ root 専用ファイルへ書く（stdin）。argv・計画には出ない
- 箱の中に長期キー・~/.aws・AWS_CONTAINER_AUTHORIZATION_TOKEN を置かない（ソケットが箱ごとに別なので不要）
- ホストの aws の認証（SSO など）は、リポジトリの uid（cfg.uid）で動かすサーバーが、その uid の ~/.aws から得る
  （systemd-run --uid/--gid。状態ディレクトリ・ロール ARN のファイルは uid 所有の 0700 / 0600）
- 未確認: AWS CLI が箱の中から FULL_URI の認証情報を取れるか（実機）。uid の ~/.aws の SSO が有効か（実機）
- 未確認: PYTHONPATH（ROOT_HELPER_DIR の親）に box パッケージが配備される前提
"""

from __future__ import annotations

import os

from box import model
from box.broker import (
    cleanup_op,
    curl_unix_op,
    ensure_command_op,
    ensure_dirs_op,
    host_sock,
    loopback_proxy_device,
    prepare_op,
    require_secret,
    start_unit_op,
    state_dir,
    stop_unit_op,
)

AWS_PORT = 7111
ROLE_SECRET = "aws-role"
DEFAULT_TTL = 3600


def session_name(repo_id: str) -> str:
    return f"box-{repo_id}"


def plan(
    cfg: model.BoxConfig, policy: model.RepoPolicy, ttl: int = DEFAULT_TTL
) -> model.BrokerPlan:
    ref = require_secret(policy, ROLE_SECRET)
    ttl = max(900, min(ttl, 43200))
    sock = host_sock(cfg.repo_id, "aws")
    role_file = f"{state_dir(cfg.repo_id, 'aws')}/token"
    pythonpath = os.path.dirname(model.ROOT_HELPER_DIR)
    host_ops = (
        ensure_command_op("aws", "aws CLI が無い（ホストに aws を入れる）"),
        stop_unit_op(cfg.repo_id, "aws"),
        ensure_dirs_op(cfg.repo_id, owner_uid=cfg.uid),
        prepare_op(cfg.repo_id, "aws", ref, owner_uid=cfg.uid),
        start_unit_op(
            cfg.repo_id,
            "aws",
            (
                f"--setenv=PYTHONPATH={pythonpath}",
                "python3",
                "-m",
                "box.broker.aws_server",
                "--socket",
                sock,
                "--role-arn-file",
                role_file,
                "--session-name",
                session_name(cfg.repo_id),
                "--ttl",
                str(ttl),
            ),
            "aws の認証情報サーバーを常駐させる（リポジトリの uid で。固定ロール・固定 TTL）",
            run_as=cfg.uid,
        ),
    )
    return model.BrokerPlan(
        kind="aws",
        host_ops=host_ops,
        devices=(loopback_proxy_device(cfg, "aws", AWS_PORT),),
        files=(),  # 箱の中に ~/.aws・長期キーを置かない
        env={
            "AWS_CONTAINER_CREDENTIALS_FULL_URI": f"http://{model.LOOPBACK}:{AWS_PORT}/creds",
            "AWS_EC2_METADATA_DISABLED": "true",
        },
        readiness=curl_unix_op(sock, "/healthz", "aws の認証情報サーバーが応答するか確かめる"),
        stop_ops=(stop_unit_op(cfg.repo_id, "aws"), cleanup_op(cfg.repo_id, "aws")),
        routes=(
            model.Route(
                "aws",
                "loopback → proxy デバイス → unix ソケット → ホストの認証情報サーバー → STS",
                ("nat", "proxy-only"),
            ),
        ),
    )
