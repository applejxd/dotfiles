"""gh ブローカーの計画。本物の読み取り専用 PAT はホストの Envoy だけが持ち、箱にはダミーの GH_TOKEN と
gh の config.yml（http_unix_socket）だけを渡す。

仕様は既存の pis 用ブローカーに合わせる（docs/spec/sandbox/broker.md の「GitHub ブローカー」）:
- 仮想ホストは api.github.com の完全一致だけ。他の :authority は 403。メソッド・パスは制限しない（防御は PAT のスコープ）
- Envoy が Authorization を `Bearer <PAT>` に差し替える（credential_injector・overwrite）
- 上流 TLS は CA と SAN（api.github.com の完全一致）で検証する
- ホストの GH_TOKEN・GITHUB_TOKEN は箱へ渡さない

PAT の経路: SecretRef → prepare Op の標準入力 → root 専用 0600 の <state_dir>/token。Envoy の SDS（generic_secret の
filename 参照）がそのファイルを読む。PAT は Envoy の設定（argv）にも環境変数にも入らない。
設定は JSON（YAML の部分集合なので Envoy がそのまま読む）で、標準ライブラリだけで組み立てる。

未確認: SDS の generic_secret が filename を読めるか（実機の Envoy）・SDS の再読み込み。
"""

from __future__ import annotations

import json
from typing import Any

from kcage import model
from kcage.broker import (
    cleanup_op,
    curl_unix_op,
    ensure_command_op,
    ensure_dirs_op,
    host_sock,
    prepare_op,
    require_secret,
    start_unit_op,
    state_dir,
    stop_unit_op,
    unix_proxy_device,
)

GH_HOST = "api.github.com"
IDENTITY_PATH = "/__kcage_broker"
IDENTITY_BODY = "kcage-broker-gh"
DENY_BODY = "kcage-broker: host not allowed"
SECRET_NAME = "gh_token"
SDS_NAME = "sds.json"
CA_FILE = "/etc/ssl/certs/ca-certificates.crt"
TYPE_PREFIX = "type.googleapis.com/envoy.extensions."
STREAM_IDLE = "3600s"
GH_CONFIG_DIR = f"{model.BOX_HOME}/.config/gh-box"
DUMMY_TOKEN = "kcage-dummy-gh-token"
SECRET_REF_NAME = "gh"


def _typed(name: str, **fields: Any) -> dict[str, Any]:
    return {"@type": TYPE_PREFIX + name, **fields}


def direct(status: int, body: str) -> dict[str, Any]:
    return {"direct_response": {"status": status, "body": {"inline_string": body}}}


def upstream_route(cluster: str, host: str) -> dict[str, Any]:
    return {
        "cluster": cluster,
        "timeout": "0s",
        "idle_timeout": STREAM_IDLE,
        "host_rewrite_literal": host,
    }


def http_manager(
    name: str, virtual_hosts: list[dict[str, Any]], sds_dir: str, secret: str
) -> dict[str, Any]:
    """HttpConnectionManager。Authorization を `Bearer <SDS の値>` で上書きする。"""
    injector = _typed(
        "filters.http.credential_injector.v3.CredentialInjector",
        overwrite=True,
        credential={
            "name": "envoy.http.injected_credentials.generic",
            "typed_config": _typed(
                "http.injected_credentials.generic.v3.Generic",
                header="Authorization",
                header_value_prefix="Bearer ",
                credential={
                    "name": secret,
                    "sds_config": {
                        "path_config_source": {
                            "path": f"{sds_dir}/{SDS_NAME}",
                            "watched_directory": {"path": sds_dir},
                        }
                    },
                },
            ),
        },
    )
    manager = _typed(
        "filters.network.http_connection_manager.v3.HttpConnectionManager",
        stat_prefix=name,
        normalize_path=True,
        merge_slashes=True,
        stream_idle_timeout=STREAM_IDLE,
        route_config={"name": name, "virtual_hosts": virtual_hosts},
        http_filters=[
            {"name": "envoy.filters.http.credential_injector", "typed_config": injector},
            {
                "name": "envoy.filters.http.router",
                "typed_config": _typed("filters.http.router.v3.Router"),
            },
        ],
    )
    return {"name": "envoy.filters.network.http_connection_manager", "typed_config": manager}


def upstream_cluster(name: str, host: str, san: dict[str, str]) -> dict[str, Any]:
    """上流（LOGICAL_DNS + TLS）。CA バンドルと SAN で検証する。"""
    return {
        "name": name,
        "type": "LOGICAL_DNS",
        "dns_lookup_family": "V4_ONLY",
        "load_assignment": {
            "cluster_name": name,
            "endpoints": [
                {
                    "lb_endpoints": [
                        {
                            "endpoint": {
                                "address": {"socket_address": {"address": host, "port_value": 443}}
                            }
                        }
                    ]
                }
            ],
        },
        "transport_socket": {
            "name": "envoy.transport_sockets.tls",
            "typed_config": _typed(
                "transport_sockets.tls.v3.UpstreamTlsContext",
                sni=host,
                common_tls_context={
                    "validation_context": {
                        "trusted_ca": {"filename": CA_FILE},
                        "match_typed_subject_alt_names": [{"san_type": "DNS", "matcher": san}],
                    }
                },
            ),
        },
    }


def envoy_config(socket_path: str, sds_dir: str) -> str:
    """gh 用の Envoy 設定（純粋。PAT は入らない）。リスナーは unix ソケット 0600（Envoy は root）。"""
    allowed = {
        "name": "github",
        "domains": [GH_HOST],
        "routes": [{"match": {"prefix": "/"}, "route": upstream_route("github_upstream", GH_HOST)}],
    }
    default = {
        "name": "deny",
        "domains": ["*"],
        "routes": [
            {"match": {"path": IDENTITY_PATH}, **direct(200, IDENTITY_BODY)},
            {"match": {"prefix": "/"}, **direct(403, DENY_BODY)},
        ],
    }
    manager = http_manager("github", [allowed, default], sds_dir, SECRET_NAME)
    listener = {
        "name": "github",
        "address": {"pipe": {"path": socket_path, "mode": 0o600}},
        "filter_chains": [{"filters": [manager]}],
    }
    config = {
        "node": {"id": "kcage-broker", "cluster": "kcage-broker"},  # SDS（generic secret）に必須
        "static_resources": {
            "listeners": [listener],
            "clusters": [upstream_cluster("github_upstream", GH_HOST, {"exact": GH_HOST})],
        },
    }
    return json.dumps(config, sort_keys=True)


def sds_document(token_file: str) -> str:
    """SDS の文書。値そのものではなく、root 専用ファイルのパスを参照する。"""
    return json.dumps(
        {
            "resources": [
                {
                    "@type": "type.googleapis.com/envoy.extensions.transport_sockets.tls.v3.Secret",
                    "name": SECRET_NAME,
                    "generic_secret": {"secret": {"filename": token_file}},
                }
            ]
        }
    )


def plan(cfg: model.BoxConfig, policy: model.RepoPolicy) -> model.BrokerPlan:
    ref = require_secret(policy, SECRET_REF_NAME)
    sock = host_sock(cfg.repo_id, "gh")
    sdir = state_dir(cfg.repo_id, "gh")
    owner = f"{cfg.uid}:{cfg.uid}"
    host_ops = (
        ensure_command_op(
            "envoy", "envoy が無い（ホストに Envoy を入れる。docs/spec/sandbox/broker.md）"
        ),
        stop_unit_op(cfg.repo_id, "gh"),
        ensure_dirs_op(cfg.repo_id),
        prepare_op(cfg.repo_id, "gh", ref, {SDS_NAME: sds_document(f"{sdir}/token")}),
        start_unit_op(
            cfg.repo_id,
            "gh",
            (
                "envoy",
                "--config-yaml",
                envoy_config(sock, sdir),
                "--disable-hot-restart",
                "--log-level",
                "warning",
            ),
            "gh のブローカー（Envoy）を常駐させる",
        ),
    )
    return model.BrokerPlan(
        kind="gh",
        host_ops=host_ops,
        devices=(unix_proxy_device(cfg, "gh"),),
        files=(
            model.FilePut(
                "box",
                f"{GH_CONFIG_DIR}/config.yml",
                "0600",
                owner,
                content=f"http_unix_socket: {model.BOX_SOCK_DIR}/gh.sock\n",
            ),
        ),
        env={
            "GH_CONFIG_DIR": GH_CONFIG_DIR,
            "GH_TOKEN": DUMMY_TOKEN,
            "GH_NO_UPDATE_NOTIFIER": "1",
            "GH_TELEMETRY": "false",
            "GH_PROMPT_DISABLED": "1",
        },
        readiness=curl_unix_op(sock, IDENTITY_PATH, "gh のブローカーが応答するか確かめる"),
        stop_ops=(stop_unit_op(cfg.repo_id, "gh"), cleanup_op(cfg.repo_id, "gh")),
        routes=(
            model.Route(
                "gh", "unix ソケット → ホストの Envoy → api.github.com", ("nat", "proxy-only")
            ),
        ),
    )
