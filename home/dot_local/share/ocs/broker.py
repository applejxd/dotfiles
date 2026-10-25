"""``pis`` の Copilot / GitHub ブローカー (設定 ``[pis.broker]``) を、pis と同じ寿命で動かす。

ホスト側 (Fence の外) で自分専用の Envoy を 1 つ立て、pis の終了で止める。
本物の認証情報 (GitHub の長期トークンと短命の Copilot トークン、``gh`` 用の PAT) は
ホストと Envoy だけが持ち、内側にはダミーしか渡さない。Envoy は ``credential_injector`` で
``Authorization`` を付ける。Copilot は 127.0.0.1 の空きポート、GitHub (``gh``) は Unix ソケット。
有効なものだけのリスナー・クラスタ・SDS を 1 つの設定に組む。
検索 (``websearch.py``) 用のリスナーは、鍵をルートごとのヘッダーとして設定ファイル (0600) へ書く。

- 状態ディレクトリ (0700) に SDS ファイル・Envoy の設定・ログを置き、終了時に丸ごと消す
- 短命トークンは期限の少し前に取り直し、SDS ファイルを rename で置き換える (Envoy が監視している)
- PAT の出どころ (ファイルかコマンド) の読み取りは純関数 (``read_token_file`` / ``run_token_command``)
- トークンの値は、標準出力・標準エラー・例外メッセージ・ログに出さない

see docs/change/0037-pis-usability-and-telemetry.md
"""

from __future__ import annotations

import contextlib
import ctypes
import http.client
import json
import os
import re
import shutil
import signal
import socket
import ssl
import stat
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator, Mapping, Sequence
from pathlib import Path
from typing import NamedTuple

# pi-ai (dist/auth/oauth/github-copilot.js) の COPILOT_HEADERS と同じ
HEADERS = {
    "Accept": "application/json",
    "User-Agent": "GitHubCopilotChat/0.35.0",
    "Editor-Version": "vscode/1.107.0",
    "Editor-Plugin-Version": "copilot-chat/0.35.0",
    "Copilot-Integration-Id": "vscode-chat",
}
TOKEN_URL = "https://api.github.com/copilot_internal/v2/token"
PROVIDER = "github-copilot"
SECRET_NAME = "copilot_token"
SDS_NAME = "copilot-sds.json"
CONFIG_NAME = "envoy.yaml"
LOG_NAME = "broker.log"
ENVOY_LOG_NAME = "envoy.log"
GH_HOST = "api.github.com"
TYPE_PREFIX = "type.googleapis.com/envoy.extensions."
STREAM_IDLE = "3600s"
GH_SECRET_NAME = "gh_token"
GH_SDS_NAME = "gh-sds.json"
GH_SOCKET_NAME = "gh.sock"
# GitHub のリスナーの身元確認: 許可外のホストは 403 + この本文で答える (上流へは出ない)
GH_IDENTITY_HOST = "pis-broker.invalid"
GH_IDENTITY_PREFIX = "pis-broker:"
GH_TOKEN_MAX_BYTES = 4096
GH_COMMAND_TIMEOUT_SECONDS = 30
UNIX_PATH_MAX = 107  # sockaddr_un.sun_path (108 バイト) から終端の NUL を引く
GH_FILE_HINT = "chmod 600 で自分だけに絞った通常ファイルにする (シンボリックリンク・他人所有は不可)"
GH_SHAPE_HINT = "PAT は 1 行・ASCII の印字可能文字・空白なし・255 文字以内で出力する"
GH_COMMAND_HINT = (
    "[pis.broker] は github_token_file か github_token_command のどちらか 1 つ (argv の配列)"
)
DEFAULT_HOST = "api.individual.githubcopilot.com"
IDENTITY_PATH = "/__pis_broker"
IDENTITY_PREFIX = "pis-broker-copilot"
COPILOT_PATHS = ("/v1/messages", "/responses", "/chat/completions")
UPSTREAM_SUFFIX = ".githubcopilot.com"
CA_FALLBACKS = (
    "/etc/ssl/certs/ca-certificates.crt",
    "/etc/pki/tls/certs/ca-bundle.crt",
    "/etc/ssl/cert.pem",
)
PR_SET_PDEATHSIG = 1

# 検索ブローカー: 接頭辞 → 上流・認証ヘッダー・通すメソッドとパス (websearch.py が呼ぶものだけ)。
# 契約は .tmp/handoff-search/README.md。鍵なしのプロバイダーは auth が None。
SEARCH_IDENTITY_PREFIX = "pis-broker-search"
SEARCH_AUTH_HEADERS = ("authorization", "proxy-authorization", "x-api-key", "x-subscription-token")
SEARCH_KEYS_FILE = Path("~/.config/agents/websearch-keys.json")
SEARCH_KEYS_MAX_BYTES = 64 * 1024
SEARCH_KEY_MAX_CHARS = 512
SEARCH_TIMEOUT = "60s"


class _SearchProvider(NamedTuple):
    name: str
    host: str
    header: str | None  # 鍵を入れるヘッダー名 (鍵なしの上流は None)
    prefix: str  # ヘッダー値の前置き
    routes: tuple[tuple[str, str], ...]  # (メソッドの正規表現, 上流のパス)


SEARCH_PROVIDERS = (
    _SearchProvider(
        "brave",
        "api.search.brave.com",
        "X-Subscription-Token",
        "",
        (("GET", "/res/v1/web/search"),),
    ),
    _SearchProvider("exa", "api.exa.ai", "x-api-key", "", (("POST", "/search"),)),
    _SearchProvider("tavily", "api.tavily.com", "Authorization", "Bearer ", (("POST", "/search"),)),
    _SearchProvider("openalex", "api.openalex.org", None, "", (("GET", "/works"),)),
    _SearchProvider("ddg", "html.duckduckgo.com", None, "", (("GET|POST", "/html/"),)),
)

REFRESH_MARGIN_SECONDS = 5 * 60  # 期限のこれだけ前に取り直す
RETRY_SECONDS = 60  # 取り直しに失敗したときの待ち
READY_TIMEOUT_SECONDS = 10.0
READY_INTERVAL_SECONDS = 0.2
EXCHANGE_TIMEOUT_SECONDS = 30
STOP_TIMEOUT_SECONDS = 5

INSTALL_HINT = (
    "chezmoi apply で導入される (llm-provider が github-copilot の機)。手動なら、"
    "Envoy の公式リリースの Linux バイナリと同じリリースの sha256 を取り、"
    "照合してから ~/.local/bin/envoy へ置いて実行権限を付ける"
)


class BrokerSession(NamedTuple):
    """``session()`` が返す値。

    ``url`` は Copilot 用の Envoy の URL (Copilot が無効なら None)、``state`` は起動ごとの
    状態ディレクトリ、``github_socket`` は GitHub 用の Unix ソケット (無効なら None)、
    ``search_url`` は検索用の URL (``http://127.0.0.1:<port>``。無効なら None)。
    """

    url: str | None
    state: Path
    github_socket: Path | None = None
    search_url: str | None = None


class BrokerError(RuntimeError):
    """ブローカーを立てられない。``hint`` は次の手 (``pi.py`` が ``die`` へ渡す)。"""

    def __init__(self, message: str, hint: str = "") -> None:
        super().__init__(message)
        self.hint = hint


def find_envoy(home: Path | None = None) -> str:
    """``envoy`` の実行ファイル。PATH、無ければ ``~/.local/bin/envoy``。"""
    found = shutil.which("envoy")
    if found:
        return found
    base = home if home is not None else Path.home()
    local = base / ".local" / "bin" / "envoy"
    if local.is_file() and os.access(local, os.X_OK):
        return str(local)
    raise BrokerError("envoy が見つからない (PATH にも ~/.local/bin/envoy にも無い)", INSTALL_HINT)


def agent_dir() -> Path:
    return Path(os.environ.get("PI_CODING_AGENT_DIR") or Path.home() / ".pi" / "agent")


def load_refresh_token(agent: Path) -> str:
    """ホストの ``auth.json`` から、長期の GitHub トークン (``refresh``) を読む。"""
    path = agent / "auth.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise BrokerError(
            f"{path} を読めない ({type(e).__name__})", "pi で /login して auth.json を作る"
        ) from None
    entry = data.get(PROVIDER) if isinstance(data, dict) else None
    refresh = entry.get("refresh") if isinstance(entry, dict) else None
    if not isinstance(refresh, str) or not refresh:
        raise BrokerError(
            f"{path} に {PROVIDER} の OAuth の資格情報が無い", "pi で /login して先に作る"
        )
    return refresh


def exchange(refresh: str) -> tuple[str, int]:
    """長期トークンで、短命の Copilot トークンと ``expires_at`` (UNIX 秒) を得る。

    例外にはトークンも要求ヘッダーも入れない (型名と HTTP の状態だけ)。
    """
    request = urllib.request.Request(
        TOKEN_URL, headers={**HEADERS, "Authorization": f"Bearer {refresh}"}
    )
    try:
        with urllib.request.urlopen(request, timeout=EXCHANGE_TIMEOUT_SECONDS) as response:
            raw = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise BrokerError(f"Copilot のトークンを取れない (HTTP {e.code})") from None
    except (OSError, ValueError) as e:
        raise BrokerError(f"Copilot のトークンを取れない ({type(e).__name__})") from None
    token = raw.get("token") if isinstance(raw, dict) else None
    expires_at = raw.get("expires_at") if isinstance(raw, dict) else None
    if not isinstance(token, str) or not token or not isinstance(expires_at, int):
        raise BrokerError("Copilot のトークンの応答の形が想定と違う")
    return token, expires_at


def upstream_host(token: str) -> str:
    """トークンの ``proxy-ep=`` から中継先を決める (``proxy.`` → ``api.``)。無ければ既定。

    ``.githubcopilot.com`` で終わらない・ホスト名として不正なら、資格情報の送り先を
    トークンの内容で変えないよう :class:`BrokerError` にする。
    """
    match = re.search(r"proxy-ep=([^;]+)", token)
    if not match:
        return DEFAULT_HOST
    host = match.group(1).replace("proxy.", "api.", 1)
    # 設定へ埋め込むので、ホスト名の文字だけを通す
    valid = re.fullmatch(r"[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?", host) is not None
    if not valid or not host.endswith(UPSTREAM_SUFFIX):
        raise BrokerError(
            "想定外の上流のホスト (トークンの proxy-ep が githubcopilot.com の下に無い)"
        )
    return host


def find_ca_file() -> str:
    """上流の証明書の検証に使う CA バンドル。どれも無ければ :class:`BrokerError` (検証なしで続けない)。"""
    candidates = [ssl.get_default_verify_paths().cafile, *CA_FALLBACKS]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return candidate
    raise BrokerError(
        "上流の証明書を検証する CA バンドルが見つからない",
        "ca-certificates を入れる (/etc/ssl/certs/ca-certificates.crt が要る)",
    )


def write_sds(path: Path, token: str, name: str = SECRET_NAME) -> None:
    """Envoy が監視するディレクトリへ、rename でアトミックに置く (0600)。"""
    body = {
        "resources": [
            {
                "@type": "type.googleapis.com/envoy.extensions.transport_sockets.tls.v3.Secret",
                "name": name,
                "generic_secret": {"secret": {"inline_string": token}},
            }
        ]
    }
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".sds-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(body, handle)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _typed(name: str, **fields: object) -> dict:
    return {"@type": TYPE_PREFIX + name, **fields}


def _direct(status: int, body: str) -> dict:
    return {"direct_response": {"status": status, "body": {"inline_string": body}}}


def _upstream_route(cluster: str, host: str) -> dict:
    return {
        "cluster": cluster,
        "timeout": "0s",
        "idle_timeout": STREAM_IDLE,
        "host_rewrite_literal": host,
    }


def _http_manager(
    name: str,
    log_format: str,
    virtual_hosts: list[dict],
    sds: tuple[str, str, str] | None = None,
    formatters: list[dict] | None = None,
) -> dict:
    """HttpConnectionManager (アクセスログ・正規化・タイムアウト) と SDS の認証注入。

    ``sds`` = (ディレクトリ, ファイル名, シークレット名)。あれば ``credential_injector`` が ``Authorization`` を付ける。
    値は SDS ファイルにだけあり、設定にも内側にも出ない。無いとき (検索) はルート側でヘッダーを付ける。
    """
    http_filters: list[dict] = []
    if sds is not None:
        sds_dir, sds_file, secret = sds
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
                                "path": f"{sds_dir}/{sds_file}",
                                "watched_directory": {"path": sds_dir},
                            }
                        },
                    },
                ),
            },
        )
        http_filters.append(
            {"name": "envoy.filters.http.credential_injector", "typed_config": injector}
        )
    http_filters.append(
        {
            "name": "envoy.filters.http.router",
            "typed_config": _typed("filters.http.router.v3.Router"),
        }
    )
    manager = _typed(
        "filters.network.http_connection_manager.v3.HttpConnectionManager",
        stat_prefix=name,
        normalize_path=True,
        merge_slashes=True,
        access_log=[
            {
                "name": "envoy.access_loggers.stdout",
                "typed_config": _typed(
                    "access_loggers.stream.v3.StdoutAccessLog",
                    log_format={
                        "text_format_source": {"inline_string": log_format},
                        **({"formatters": formatters} if formatters else {}),
                    },
                ),
            }
        ],
        stream_idle_timeout=STREAM_IDLE,
        route_config={"name": name, "virtual_hosts": virtual_hosts},
        http_filters=http_filters,
    )
    return {"name": "envoy.filters.network.http_connection_manager", "typed_config": manager}


def _listener(name: str, address: dict, manager: dict) -> dict:
    """リスナー。``address`` は tcp (``socket_address``) か unix (``pipe``)。"""
    return {"name": name, "address": address, "filter_chains": [{"filters": [manager]}]}


def _upstream_cluster(name: str, host: str, ca_file: str, san: dict) -> dict:
    """上流のクラスタ (LOGICAL_DNS + TLS)。CA バンドルで検証し、SAN (``san``: exact か suffix) を固定する。"""
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
                        "trusted_ca": {"filename": ca_file},
                        "match_typed_subject_alt_names": [{"san_type": "DNS", "matcher": san}],
                    }
                },
            ),
        },
    }


def _copilot(port: int, host: str, sds_dir: str, ca_file: str) -> tuple[dict, dict]:
    """Copilot のリスナーとクラスタ (127.0.0.1)。

    通すのは観測した 3 つの POST (完全一致のパス) と身元確認だけ。他は 403。
    see docs/spec/sandbox/broker.md#copilot-ブローカー
    """
    post = {"name": ":method", "string_match": {"exact": "POST"}}
    routes: list[dict] = [
        # pis が起動前に身元を確かめる (上流へは出さない)
        {"match": {"path": IDENTITY_PATH}, **_direct(200, IDENTITY_PREFIX)},
    ]
    routes += [
        {
            "match": {"path": path, "headers": [post]},
            "route": _upstream_route("copilot_upstream", host),
        }
        for path in COPILOT_PATHS
    ]
    routes.append(
        {"match": {"prefix": "/"}, **_direct(403, "pis-broker: path or method not allowed")}
    )
    manager = _http_manager(
        "copilot",
        "ACCESS %REQ(:METHOD)% %REQ(:PATH)% %RESPONSE_CODE%\n",
        [{"name": "copilot", "domains": ["*"], "routes": routes}],
        (sds_dir, SDS_NAME, SECRET_NAME),
    )
    listener = _listener(
        "copilot", {"socket_address": {"address": "127.0.0.1", "port_value": port}}, manager
    )
    cluster = _upstream_cluster(
        "copilot_upstream", host, ca_file, {"suffix": UPSTREAM_SUFFIX.lstrip(".")}
    )
    return listener, cluster


def _github(socket_path: str, sds_dir: str, ca_file: str) -> tuple[dict, dict]:
    """GitHub (``gh``) のリスナー (Unix ソケット 0600) とクラスタ。

    送れるのは ``api.github.com`` だけ (メソッドとパスは制限しない。操作の防御は PAT のスコープ)。
    他のホストは 403 で、上流へ出さない (pis が起動前の身元確認に使う)。
    see docs/spec/sandbox/broker.md#copilot-ブローカー
    """
    allowed = {
        "name": "github",
        "domains": [GH_HOST],
        "routes": [
            {"match": {"prefix": "/"}, "route": _upstream_route("github_upstream", GH_HOST)}
        ],
    }
    denied = {
        "name": "deny",
        "domains": ["*"],
        "routes": [
            {"match": {"prefix": "/"}, **_direct(403, GH_IDENTITY_PREFIX + " host not allowed")}
        ],
    }
    manager = _http_manager(
        "github",
        "ACCESS github %REQ(:METHOD)% %REQ(:AUTHORITY)% %REQ(:PATH)% %RESPONSE_CODE%\n",
        [allowed, denied],
        (sds_dir, GH_SDS_NAME, GH_SECRET_NAME),
    )
    listener = _listener("github", {"pipe": {"path": socket_path, "mode": 0o600}}, manager)
    cluster = _upstream_cluster("github_upstream", GH_HOST, ca_file, {"exact": GH_HOST})
    return listener, cluster


def _search_cluster_name(provider: _SearchProvider) -> str:
    return f"search_{provider.name}_upstream"


def _search_header(key: str, value: str) -> dict:
    # Envoy はヘッダー値の % を書式として解釈するので、% は %% にする
    return {
        "header": {"key": key, "value": value.replace("%", "%%")},
        "append_action": "OVERWRITE_IF_EXISTS_OR_ADD",
    }


def _search(
    port: int,
    ca_file: str,
    keys: Mapping[str, str],
    test_upstreams: Mapping[str, int] | None = None,
) -> tuple[dict, list[dict]]:
    """検索 (``websearch.py``) のリスナー (127.0.0.1) と、上流のクラスタ 5 つ。

    ルートは ``/<名前>`` の接頭辞つきで、``websearch.py`` が呼ぶメソッドとパスだけ (完全一致)。接頭辞を
    除いて上流へ中継し、Host は上流のホスト名にする。認証ヘッダーはルートごとに ``OVERWRITE_IF_EXISTS_OR_ADD``
    で付け、**自分以外の認証ヘッダーは内側から来ても削除する** (別のプロバイダーへ通さない)。
    鍵の無い Brave / Exa / Tavily は 503。身元確認 (``/__pis_broker``) と許可外 (403) は上流へ出さない。
    ``test_upstreams`` (名前 → ポート) は試験用: TLS 無しの 127.0.0.1 の偽の上流へ差し替える。
    """
    routes: list[dict] = [
        {
            # 身元確認は GET だけ (他のメソッドは末尾の 403)
            "match": {
                "path": IDENTITY_PATH,
                "headers": [{"name": ":method", "string_match": {"exact": "GET"}}],
            },
            **_direct(200, SEARCH_IDENTITY_PREFIX),
        }
    ]
    clusters: list[dict] = []
    for provider in SEARCH_PROVIDERS:
        cluster = _search_cluster_name(provider)
        if test_upstreams is not None and provider.name in test_upstreams:
            clusters.append(_local_cluster(cluster, test_upstreams[provider.name]))
        else:
            clusters.append(
                _upstream_cluster(cluster, provider.host, ca_file, {"exact": provider.host})
            )
        key = keys.get(provider.name) if provider.header is not None else None
        others = [h for h in SEARCH_AUTH_HEADERS if h != (provider.header or "").lower()]
        for methods, path in provider.routes:
            method = {
                "name": ":method",
                "string_match": (
                    {"safe_regex": {"regex": methods}} if "|" in methods else {"exact": methods}
                ),
            }
            match = {"path": f"/{provider.name}{path}", "headers": [method]}
            if provider.header is not None and key is None:
                routes.append(
                    {
                        "match": match,
                        **_direct(503, f"pis-broker: no key for {provider.name}"),
                    }
                )
                continue
            route = {
                "cluster": cluster,
                "timeout": SEARCH_TIMEOUT,
                "idle_timeout": STREAM_IDLE,
                "host_rewrite_literal": provider.host,
                "regex_rewrite": {"pattern": {"regex": f"^/{provider.name}"}, "substitution": ""},
            }
            entry: dict = {
                "match": match,
                "route": route,
                "request_headers_to_remove": others,
            }
            if provider.header is not None and key is not None:
                entry["request_headers_to_add"] = [
                    _search_header(provider.header, provider.prefix + key)
                ]
            routes.append(entry)
    routes.append(
        {"match": {"prefix": "/"}, **_direct(403, "pis-broker: path or method not allowed")}
    )
    manager = _http_manager(
        "search",
        # クエリに検索語が入るので、パスはクエリを除いて出す。ヘッダーは出さない
        "ACCESS search %REQ(:METHOD)% %REQ_WITHOUT_QUERY(:PATH)% %RESPONSE_CODE%\n",
        [{"name": "search", "domains": ["*"], "routes": routes}],
        formatters=[
            {
                "name": "envoy.formatter.req_without_query",
                "typed_config": _typed("formatter.req_without_query.v3.ReqWithoutQuery"),
            }
        ],
    )
    listener = _listener(
        "search", {"socket_address": {"address": "127.0.0.1", "port_value": port}}, manager
    )
    return listener, clusters


def _local_cluster(name: str, port: int) -> dict:
    """試験用: TLS 無しで 127.0.0.1 の偽の上流へつなぐクラスタ (本番の経路からは使わない)。"""
    return {
        "name": name,
        "type": "STATIC",
        "load_assignment": {
            "cluster_name": name,
            "endpoints": [
                {
                    "lb_endpoints": [
                        {
                            "endpoint": {
                                "address": {
                                    "socket_address": {"address": "127.0.0.1", "port_value": port}
                                }
                            }
                        }
                    ]
                }
            ],
        },
    }


def build_config(
    *,
    sds_dir: Path,
    ca_file: str,
    copilot_port: int | None = None,
    copilot_host: str | None = None,
    github_socket: Path | None = None,
    search_port: int | None = None,
    search_keys: Mapping[str, str] | None = None,
    search_test_upstreams: Mapping[str, int] | None = None,
) -> str:
    """有効なブローカーだけのリスナー・クラスタを組んだ Envoy の設定 (JSON 文字列) を返す。

    JSON は YAML の部分集合なので、Envoy はそのまま読める。``"`` ``\\`` 改行を含むパスは、
    今までどおり拒否する。
    Copilot (``copilot_port`` と ``copilot_host``)・GitHub (``github_socket``)・検索 (``search_port``。
    ``search_keys`` はプロバイダー名 → 鍵で、無い名前は鍵なし) のどれも無ければ例外。
    鍵は設定へ書かれる (呼び出し側が 0600 で書く)。例外・``repr`` には出さない。
    """
    paths = [str(sds_dir), ca_file]
    if github_socket is not None:
        paths.append(str(github_socket))
        if len(os.fsencode(github_socket)) > UNIX_PATH_MAX:
            raise BrokerError(
                f"Unix ソケットのパスが長すぎる ({len(os.fsencode(github_socket))} バイト。"
                f"上限 {UNIX_PATH_MAX}): {github_socket}",
                'HOME を短いパスにするか、github = "off" にする',
            )
    for path in paths:
        if any(ch in path for ch in ('"', "\\", "\n", "\r")):
            raise BrokerError("設定へ埋め込めないパス (引用符・バックスラッシュ・改行を含む)")
    sds = str(sds_dir)
    listeners: list[dict] = []
    clusters: list[dict] = []
    if copilot_port is not None and copilot_host is not None:
        listener, cluster = _copilot(copilot_port, copilot_host, sds, ca_file)
        listeners.append(listener)
        clusters.append(cluster)
    if github_socket is not None:
        listener, cluster = _github(str(github_socket), sds, ca_file)
        listeners.append(listener)
        clusters.append(cluster)
    if search_port is not None:
        keys = dict(search_keys or {})
        for name, value in keys.items():
            if (
                not isinstance(name, str)
                or not isinstance(value, str)
                or re.fullmatch(rf"[\x21-\x7e]{{1,{SEARCH_KEY_MAX_CHARS}}}", value) is None
            ):
                raise BrokerError("検索の鍵の形式が不正 (値は出さない)")
        listener, search_clusters = _search(search_port, ca_file, keys, search_test_upstreams)
        listeners.append(listener)
        clusters.extend(search_clusters)
    if not listeners:
        raise BrokerError("有効なブローカーが無い (Envoy の設定を組めない)")
    config = {
        "node": {"id": "pis-broker", "cluster": "pis-broker"},
        "static_resources": {"listeners": listeners, "clusters": clusters},
    }
    return json.dumps(config, indent=2, ensure_ascii=False)


def _check_token_shape(raw: bytes) -> str:
    """取得した PAT を整えて検査する (末尾の空白・改行を除き、1 行・ASCII の印字可能文字・1〜255 文字)。

    違反は「出どころ無し」ではなく起動拒否。例外の本文には値を入れない。
    """
    try:
        value = raw.decode("utf-8").rstrip()
    except UnicodeDecodeError:
        raise BrokerError("GitHub の PAT が UTF-8 でない", GH_SHAPE_HINT) from None
    if re.fullmatch(r"[\x21-\x7e]{1,255}", value) is None:
        raise BrokerError("GitHub の PAT の形式が不正", GH_SHAPE_HINT)
    return value


def read_token_file(path: Path) -> str | None:
    """PAT をファイルから読む。ファイルが無ければ None (出どころ無し)。

    シンボリックリンク・通常ファイル以外・他人所有・グループ / 他人に開いた権限・
    4096 バイト超は :class:`BrokerError` (起動拒否)。値は例外に入れない。
    """
    try:
        # O_NONBLOCK: FIFO を渡されてもここで止まらず、下の種別検査で拒否する
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return None
    except OSError as e:  # シンボリックリンク (ELOOP) を含む
        raise BrokerError(
            f"GitHub の PAT のファイルを開けない ({path}: {type(e).__name__})", GH_FILE_HINT
        ) from None
    try:
        info = os.fstat(fd)  # ディレクトリも O_RDONLY で開けるので、fdopen より前に種別を検査する
        if not stat.S_ISREG(info.st_mode):
            raise BrokerError(f"GitHub の PAT のファイルが通常ファイルでない: {path}", GH_FILE_HINT)
        if info.st_uid != os.getuid():
            raise BrokerError(f"GitHub の PAT のファイルの所有者が自分でない: {path}", GH_FILE_HINT)
        if info.st_mode & 0o077:
            raise BrokerError(
                f"GitHub の PAT のファイルの権限が広すぎる ({stat.S_IMODE(info.st_mode):04o}): {path}",
                GH_FILE_HINT,
            )
        if info.st_size > GH_TOKEN_MAX_BYTES:
            raise BrokerError(f"GitHub の PAT のファイルが大きすぎる: {path}", GH_FILE_HINT)
        raw = os.read(fd, GH_TOKEN_MAX_BYTES + 1)
    finally:
        os.close(fd)
    if len(raw) > GH_TOKEN_MAX_BYTES:
        raise BrokerError(f"GitHub の PAT のファイルが大きすぎる: {path}", GH_FILE_HINT)
    return _check_token_shape(raw)


def run_token_command(argv: Sequence[str]) -> str | None:
    """PAT をコマンド (argv、シェル無し) の標準出力から取る。

    環境はホストのものを継承する (Bitwarden の ``BW_SESSION`` などが要る。利用者の設定を信頼)。
    実行ファイルが無い・タイムアウト・終了コードが 0 でない・出力が 4096 バイト超は
    None (出どころ無し)。標準エラーは捨てる。形式違反は :class:`BrokerError` (起動拒否)。
    """
    if not argv:
        raise BrokerError("github_token_command が空", GH_COMMAND_HINT)
    try:
        result = subprocess.run(
            list(argv),
            shell=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=GH_COMMAND_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):  # 実行ファイル無し・実行権限無し・タイムアウト
        return None
    except ValueError:  # 引数に NUL 文字
        raise BrokerError("github_token_command の引数が不正", GH_COMMAND_HINT) from None
    if result.returncode != 0 or len(result.stdout) > GH_TOKEN_MAX_BYTES:
        return None
    return _check_token_shape(result.stdout)


def github_origin(token_file: str | None, token_command: Sequence[str] | None) -> str | None:
    """通知用の PAT の出どころ (ファイルのパスか、コマンドの先頭の語)。どちらも無ければ None。"""
    if token_file is not None:
        return str(Path(token_file).expanduser())
    if token_command:
        return token_command[0]
    return None


def resolve_github_token(token_file: str | None, token_command: Sequence[str] | None) -> str | None:
    """設定された出どころから PAT を得る。出どころ無し (ファイル無し・コマンド失敗・未設定) は None。

    両方の設定、権限・形式の違反は :class:`BrokerError` (起動拒否)。
    """
    if token_file is not None and token_command is not None:
        raise BrokerError(
            "github_token_file と github_token_command は両方は書けない", GH_COMMAND_HINT
        )
    if token_file is not None:
        return read_token_file(Path(token_file).expanduser())
    if token_command is not None:
        return run_token_command(token_command)
    return None


def read_search_keys(path: Path | None = None) -> tuple[dict[str, str], list[str]]:
    """検索の鍵ファイル (``websearch-keys.json``) をホスト側で読み、(鍵, 通知文の一覧) を返す。

    鍵を必要とするプロバイダー (brave / exa / tavily) だけを拾う。環境変数は見ない。
    無い・シンボリックリンク・通常ファイル以外・他人所有・グループ / 他人に開いた権限・64 KiB 超・
    壊れた JSON・文字列でない / 形式不正の値は、該当のプロバイダーを鍵なしとして扱い、
    鍵を出さない通知文を添える (例外にはしない)。
    """
    target = (path if path is not None else SEARCH_KEYS_FILE).expanduser()
    names = [p.name for p in SEARCH_PROVIDERS if p.header is not None]
    try:
        fd = os.open(target, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return {}, [f"検索の鍵ファイルが無い ({target})"]
    except OSError as e:
        return {}, [f"検索の鍵ファイルを開けない ({target}: {type(e).__name__})"]
    try:
        info = os.fstat(fd)
        problem = None
        if not stat.S_ISREG(info.st_mode):
            problem = "通常ファイルでない"
        elif info.st_uid != os.getuid():
            problem = "所有者が自分でない"
        elif info.st_mode & 0o077:
            problem = f"権限が広すぎる ({stat.S_IMODE(info.st_mode):04o}。chmod 600)"
        elif info.st_size > SEARCH_KEYS_MAX_BYTES:
            problem = "大きすぎる"
        if problem is not None:
            return {}, [f"検索の鍵ファイルを使わない: {problem} ({target})"]
        raw = os.read(fd, SEARCH_KEYS_MAX_BYTES + 1)
    finally:
        os.close(fd)
    if len(raw) > SEARCH_KEYS_MAX_BYTES:
        return {}, [f"検索の鍵ファイルを使わない: 大きすぎる ({target})"]
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return {}, [f"検索の鍵ファイルを JSON として読めない ({target})"]
    if not isinstance(data, dict):
        return {}, [f"検索の鍵ファイルがオブジェクトでない ({target})"]
    keys: dict[str, str] = {}
    notes: list[str] = []
    for name in names:
        value = data.get(name)
        if value is None:
            continue
        value = value.strip() if isinstance(value, str) else value
        if (
            not isinstance(value, str)
            or re.fullmatch(rf"[\x21-\x7e]{{1,{SEARCH_KEY_MAX_CHARS}}}", value) is None
        ):
            notes.append(f"検索の鍵が不正なので使わない: {name}")
            continue
        keys[name] = value
    return keys, notes


def free_port() -> int:
    """127.0.0.1 の空きポートを 1 つ得る (閉じてから Envoy が使う)。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def make_state_dir(home: Path | None = None) -> Path:
    """起動ごとの状態ディレクトリ (0700)。``$XDG_RUNTIME_DIR`` の下、無ければ ``~/.local/state/pis``。"""
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    if runtime:
        base = Path(runtime)
    else:
        base = (home if home is not None else Path.home()) / ".local" / "state" / "pis"
        base.mkdir(parents=True, exist_ok=True)
    state = Path(tempfile.mkdtemp(prefix="pis-broker-", dir=str(base)))
    os.chmod(state, 0o700)
    return state


def _log(path: Path, message: str) -> None:
    """失敗の事実を状態ディレクトリのログへ追記する (トークンの値は書かない)。"""
    with path.open("a", encoding="utf-8") as f:
        f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {message}\n")


def _die_with_parent() -> None:
    """子 (Envoy) 側で、親の死亡時に SIGTERM を受けるようにする (Linux)。

    ``preexec_fn`` の中なので、標準エラー (= Envoy のログ) へ直接 1 行書く。失敗しても起動は続ける。
    """
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        if libc.prctl(PR_SET_PDEATHSIG, int(signal.SIGTERM), 0, 0, 0) != 0:
            os.write(
                2, f"pis-broker: prctl(PDEATHSIG) failed errno={ctypes.get_errno()}\n".encode()
            )
    except (OSError, AttributeError) as e:
        os.write(2, f"pis-broker: prctl(PDEATHSIG) unavailable: {type(e).__name__}\n".encode())


def _refresh_loop(
    stop: threading.Event,
    refresh: str,
    sds: Path,
    log: Path,
    expires_at: int,
    margin: float,
    retry: float,
) -> None:
    """期限の ``margin`` 秒前に取り直して SDS を書き直す。失敗したら ``retry`` 秒後に再試行する。"""
    while True:
        if stop.wait(max(0.0, expires_at - time.time() - margin)):
            return
        try:
            token, expires_at = exchange(refresh)
            write_sds(sds, token)
        except (BrokerError, OSError) as e:
            if stop.is_set():
                return  # 終了処理中に状態ディレクトリが消えただけ
            try:
                _log(log, f"トークンの更新に失敗: {type(e).__name__}: {e}")
            except OSError as log_error:
                print(f"pis-broker: ログへ書けない ({type(log_error).__name__})", file=sys.stderr)
            if stop.wait(retry):
                return


def _tail(path: Path, lines: int = 20) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "(ログを読めない)"
    return "\n".join(text.splitlines()[-lines:])


def _probe(opener: urllib.request.OpenerDirector, url: str, prefix: str = IDENTITY_PREFIX) -> bool:
    """身元の確認 1 回。200 かつ本文が ``prefix`` (既定 ``pis-broker-copilot``) で始まれば True。まだなら False。"""
    try:
        with opener.open(url + IDENTITY_PATH, timeout=1) as response:
            body = response.read(256).decode("utf-8", errors="replace")
            return response.status == 200 and body.startswith(prefix)
    except OSError:
        return False  # まだ待ち受けていない (呼び出し側が期限まで再試行する)


class _UnixConnection(http.client.HTTPConnection):
    """Unix ソケットへつなぐ HTTP 接続 (Host は身元確認用の固定の名前)。"""

    def __init__(self, path: str, timeout: float) -> None:
        super().__init__(GH_IDENTITY_HOST, timeout=timeout)
        self._path = path

    def connect(self) -> None:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            sock.settimeout(self.timeout)
            sock.connect(self._path)
        except OSError:
            sock.close()
            raise
        self.sock = sock


def _probe_unix(path: Path) -> bool:
    """GitHub のリスナーの身元の確認 1 回。許可外のホストへの 403 と ``pis-broker:`` の本文なら True。"""
    connection = _UnixConnection(str(path), timeout=1)
    try:
        connection.request("GET", "/")
        response = connection.getresponse()
        body = response.read(256).decode("utf-8", errors="replace")
        return response.status == 403 and body.startswith(GH_IDENTITY_PREFIX)
    except (OSError, http.client.HTTPException):
        return False  # まだ待ち受けていない (呼び出し側が期限まで再試行する)
    finally:
        connection.close()


def _wait_ready(
    probes: Sequence[Callable[[], bool]],
    target: str,
    proc: subprocess.Popen,
    log: Path,
    timeout: float,
) -> None:
    """全リスナーが身元の確認に答えるまで待つ (プロキシは使わない)。出なければログ末尾を添えて例外。"""
    deadline = time.monotonic() + timeout
    while True:
        if proc.poll() is not None:
            raise BrokerError(
                f"Envoy が起動直後に終了した (code={proc.returncode})\n{_tail(log)}",
                f"{log} を見る",
            )
        if all(probe() for probe in probes):
            return
        if time.monotonic() >= deadline:
            raise BrokerError(
                f"Envoy が {timeout:g} 秒以内に応答しなかった ({target})\n{_tail(log)}",
                f"{log} を見る",
            )
        time.sleep(READY_INTERVAL_SECONDS)


def _terminate(proc: subprocess.Popen | None) -> None:
    """SIGTERM、``STOP_TIMEOUT_SECONDS`` 待って、残れば SIGKILL。"""
    if proc is None:
        return
    if proc.poll() is None:
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=STOP_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


@contextlib.contextmanager
def session(
    agent: Path | None = None,
    *,
    home: Path | None = None,
    copilot: bool = True,
    github_token: str | None = None,
    github_socket: Path | None = None,
    search: bool = False,
    search_keys: Mapping[str, str] | None = None,
    search_test_upstreams: Mapping[str, int] | None = None,
    refresh_margin: float = REFRESH_MARGIN_SECONDS,
    retry_seconds: float = RETRY_SECONDS,
    ready_timeout: float = READY_TIMEOUT_SECONDS,
) -> Iterator[BrokerSession]:
    """自分専用の Envoy を 1 つ立て、有効なブローカーの接続先と状態ディレクトリを返す。

    抜けると止めて状態を消す。

    - ``copilot``: Copilot 用のリスナー (``http://127.0.0.1:<port>``) を立てる。``agent`` はホストの agent 置き場
      (``auth.json`` がある所。既定は ``PI_CODING_AGENT_DIR`` か ``~/.pi/agent``)。
    - ``github_token`` と ``github_socket``: ``gh`` 用のリスナー (Unix ソケット) を立てる。
      PAT は呼び出し側が :func:`resolve_github_token` で得て渡す (出どころ無しは立てない)。
    - ``search``: 検索用のリスナー (``http://127.0.0.1:<port>``) を同じ Envoy に足す。``search_keys`` は
      プロバイダー名 → 鍵 (呼び出し側が :func:`read_search_keys` で得る。無い名前は鍵なし = 503)。鍵は
      状態ディレクトリの設定ファイル (0600) にだけ入り、戻り値には URL しか入れない。

    どれも無効なら :class:`BrokerError`。立てられなければ :class:`BrokerError` (呼び出し側が
    ``die`` に変える)。``refresh_margin`` ``retry_seconds`` ``ready_timeout`` は試験で短くするための引数。
    """
    use_github = github_token is not None
    if use_github != (github_socket is not None):
        raise BrokerError("github_token と github_socket は組で渡す")
    if not copilot and not use_github and not search:
        raise BrokerError("有効なブローカーが無い (Copilot も GitHub も無効)")
    envoy = find_envoy(home)
    refresh = token = host = None
    expires_at = 0
    if copilot:
        refresh = load_refresh_token(agent if agent is not None else agent_dir())
        token, expires_at = exchange(refresh)
        host = upstream_host(token)
    ca_file = find_ca_file()
    state = make_state_dir(home)
    stop = threading.Event()
    proc: subprocess.Popen | None = None
    thread: threading.Thread | None = None
    try:
        sds = state / SDS_NAME
        port = None
        if token is not None:
            write_sds(sds, token)
            del token
            port = free_port()
        if github_token is not None:
            write_sds(state / GH_SDS_NAME, github_token, GH_SECRET_NAME)
            del github_token
        config = state / CONFIG_NAME
        search_port = None
        if search:
            search_port = free_port()
            while search_port == port:
                search_port = free_port()
        config.write_text(
            build_config(
                sds_dir=state,
                ca_file=ca_file,
                copilot_port=port,
                copilot_host=host,
                github_socket=github_socket,
                search_port=search_port,
                search_keys=search_keys,
                search_test_upstreams=search_test_upstreams,
            ),
            encoding="utf-8",
        )
        os.chmod(config, 0o600)
        env = {"PATH": os.environ.get("PATH", ""), "HOME": str(home or Path.home())}
        envoy_log = state / ENVOY_LOG_NAME
        with envoy_log.open("ab") as out:
            proc = subprocess.Popen(
                [
                    envoy,
                    "--config-path",
                    str(config),
                    "--log-level",
                    "warning",
                    "--disable-hot-restart",
                ],
                stdin=subprocess.DEVNULL,
                stdout=out,
                stderr=out,
                start_new_session=True,
                preexec_fn=_die_with_parent,
                env=env,
            )
        if refresh is not None:
            thread = threading.Thread(
                target=_refresh_loop,
                args=(
                    stop,
                    refresh,
                    sds,
                    state / LOG_NAME,
                    expires_at,
                    refresh_margin,
                    retry_seconds,
                ),
                daemon=True,
            )
            thread.start()
        probes: list[Callable[[], bool]] = []
        targets: list[str] = []
        url = None
        search_url = None
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        if port is not None:
            url = f"http://127.0.0.1:{port}"
            probes.append(lambda: _probe(opener, url))
            targets.append(url)
        if search_port is not None:
            search_url = f"http://127.0.0.1:{search_port}"
            probes.append(lambda: _probe(opener, search_url, SEARCH_IDENTITY_PREFIX))
            targets.append(search_url)
        if github_socket is not None:
            probes.append(lambda: _probe_unix(github_socket))
            targets.append(str(github_socket))
        _wait_ready(probes, ", ".join(targets), proc, envoy_log, ready_timeout)
        yield BrokerSession(url, state, github_socket, search_url)
    finally:
        stop.set()
        if thread is not None:
            thread.join(timeout=STOP_TIMEOUT_SECONDS)
        _terminate(proc)
        shutil.rmtree(state, ignore_errors=True)
