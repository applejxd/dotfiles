"""許可表（HostPolicy）の読み込みと検証。root 所有の /etc/box/policy.toml が権限の元。

ファイルの形（TOML。未知のキー・型違いは PolicyError）:

    [defaults]
    network = "nat"                 # nat | proxy-only | offline（省略時 nat）
    deny_paths = ["/mnt/c/Users"]   # 根の下でも拒否する追加のパス（絶対パス）
    template = "box-template"       # テンプレートのイメージの別名
    build_proxy = "192.0.2.10:3128" # テンプレート作成時だけ使う上流プロキシ（host:port。省略時は直接つなぐ）

    [repo.myrepo]                   # repo id: ^[a-z0-9][a-z0-9-]{0,30}$
    path = "/home/alice/work/myrepo"        # rw で重ねる唯一のパス（絶対パス）
    data_roots = ["/mnt/d/datasets"]        # ro で渡してよい根
    ports = [8080, [9000, 9099]]            # 整数 または [lo, hi]
    brokers = ["gh", "copilot"]
    gpu = true
    network = "proxy-only"
    proxy_upstream = "192.0.2.10:3128"      # proxy-only のとき必須（IPv4:port / [IPv6]:port / host:port）
    idmap = "user"                          # user | root
    uid = 1000                              # 1〜65535
    subnet = "10.77.0.0/24"

    [repo.myrepo.secrets.gh]        # 秘密の出どころ（値は書かない）
    source = "file"                 # file | command | prompt
    path = "/etc/box/secret/gh"     # file のとき
    # argv = ["/usr/bin/pass", "show", "x"]   # command のとき（配列。シェルなし）

標準ライブラリだけ。副作用なし（load / check_file_safe だけがファイルを見る）。
"""

from __future__ import annotations

import ipaddress
import json
import posixpath
import re
import tomllib
from collections.abc import Mapping
from typing import Any

from box import model

REPO_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,30}$")
SECRET_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
BROKER_KINDS: tuple[str, ...] = ("gh", "aws", "copilot", "hf-cache")
NET_MODES: tuple[str, ...] = tuple(model.NET_STRICTNESS)
IDMAP_MODES: tuple[str, ...] = ("user", "root")

_DEFAULT_KEYS = {"network", "deny_paths", "template", "build_proxy"}
_REPO_KEYS = {
    "path",
    "data_roots",
    "ports",
    "brokers",
    "gpu",
    "network",
    "proxy_upstream",
    "idmap",
    "uid",
    "subnet",
    "secrets",
}
_HOST_RE = re.compile(
    r"^[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?(\.[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*$"
)
_ALIAS_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,62}$")


class PolicyError(ValueError):
    """許可表が不正。"""


def _is_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _abs_path(v: Any, what: str) -> str:
    if not isinstance(v, str) or not v.startswith("/") or "\x00" in v or "\n" in v:
        raise PolicyError(f"{what} は絶対パスの文字列が必要")
    if ".." in v.split("/") or (posixpath.normpath(v) != v.rstrip("/") and v != "/"):
        raise PolicyError(f"{what} は正規化された絶対パスが必要: {v}")
    return v


def _check_keys(table: Mapping[str, Any], allowed: set[str], where: str) -> None:
    unknown = sorted(set(table) - allowed)
    if unknown:
        raise PolicyError(f"{where} に未知のキー: {', '.join(unknown)}")


def _str_list(v: Any, what: str) -> list[str]:
    if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
        raise PolicyError(f"{what} は文字列の配列が必要")
    return v


def _net_mode(v: Any, what: str) -> str:
    if v not in NET_MODES:
        raise PolicyError(f"{what} は {'/'.join(NET_MODES)} のいずれか")
    return v


def _port(v: Any, what: str) -> int:
    if not _is_int(v) or not 1 <= v <= 65535:
        raise PolicyError(f"{what} は 1〜65535 の整数が必要")
    return v


def _parse_ports(v: Any) -> tuple[model.PortRange, ...]:
    if not isinstance(v, list):
        raise PolicyError("ports は配列が必要")
    out: list[model.PortRange] = []
    for item in v:
        if _is_int(item):
            p = _port(item, "ports")
            out.append(model.PortRange(p, p))
        elif isinstance(item, list) and len(item) == 2:
            lo, hi = _port(item[0], "ports"), _port(item[1], "ports")
            if lo > hi:
                raise PolicyError("ports の範囲は lo <= hi が必要")
            out.append(model.PortRange(lo, hi))
        else:
            raise PolicyError("ports の要素は整数 または [lo, hi] の組")
    return tuple(out)


def validate_upstream(v: Any) -> str:
    """proxy_upstream: IPv4:port / [IPv6]:port / ホスト名:port。"""
    if not isinstance(v, str):
        raise PolicyError("proxy_upstream は文字列が必要")
    if v.startswith("["):
        host, sep, port = v[1:].partition("]:")
        if not sep:
            raise PolicyError("proxy_upstream の [IPv6]:port の形が不正")
        try:
            ipaddress.IPv6Address(host)
        except ValueError as e:
            raise PolicyError("proxy_upstream の IPv6 が不正") from e
    else:
        host, sep, port = v.rpartition(":")
        if not sep:
            raise PolicyError("proxy_upstream は host:port の形が必要")
        try:
            ipaddress.IPv4Address(host)
        except ValueError:
            if not _HOST_RE.match(host):
                raise PolicyError("proxy_upstream のホストが不正") from None
    if not port.isdigit():
        raise PolicyError("proxy_upstream のポートが不正")
    _port(int(port), "proxy_upstream のポート")
    return v


def _parse_secrets(repo_id: str, v: Any) -> dict[str, model.SecretRef]:
    if not isinstance(v, dict):
        raise PolicyError("secrets はテーブルが必要")
    out: dict[str, model.SecretRef] = {}
    for name, t in v.items():
        if not SECRET_NAME_RE.match(name) or not isinstance(t, dict):
            raise PolicyError(f"repo.{repo_id}.secrets の名前または形が不正")
        _check_keys(t, {"source", "path", "argv"}, f"repo.{repo_id}.secrets.{name}")
        src = t.get("source")
        if src == "file":
            if "argv" in t:
                raise PolicyError("file の secrets に argv は書けない")
            out[name] = model.SecretRef(name, "file", path=_abs_path(t.get("path"), "secrets.path"))
        elif src == "command":
            argv = t.get("argv")
            if "path" in t or not isinstance(argv, list) or not argv:
                raise PolicyError("command の secrets は argv の配列が必要（path は不可）")
            out[name] = model.SecretRef(
                name, "command", argv=tuple(_str_list(argv, "secrets.argv"))
            )
        elif src == "prompt":
            if "path" in t or "argv" in t:
                raise PolicyError("prompt の secrets に path・argv は書けない")
            out[name] = model.SecretRef(name, "prompt")
        else:
            raise PolicyError("secrets.source は file / command / prompt のいずれか")
    return out


def _parse_repo(repo_id: str, t: Any, default_net: str) -> model.RepoPolicy:
    if not REPO_ID_RE.match(repo_id):
        raise PolicyError(f"repo id の形が不正: {repo_id!r}")
    if not isinstance(t, dict):
        raise PolicyError(f"repo.{repo_id} はテーブルが必要")
    _check_keys(t, _REPO_KEYS, f"repo.{repo_id}")
    if "path" not in t:
        raise PolicyError(f"repo.{repo_id} に path が必要")
    path = _abs_path(t["path"], "path")
    roots = tuple(
        _abs_path(r, "data_roots") for r in _str_list(t.get("data_roots", []), "data_roots")
    )
    brokers = _str_list(t.get("brokers", []), "brokers")
    bad = sorted(set(brokers) - set(BROKER_KINDS))
    if bad:
        raise PolicyError(f"brokers に未知の種類: {', '.join(bad)}")
    gpu = t.get("gpu", False)
    if not isinstance(gpu, bool):
        raise PolicyError("gpu は真偽値が必要")
    network = _net_mode(t.get("network", default_net), "network")
    idmap = t.get("idmap", "user")
    if idmap not in IDMAP_MODES:
        raise PolicyError("idmap は user / root のいずれか")
    uid = t.get("uid", 1000)
    if not _is_int(uid) or not 1 <= uid <= 65535:
        raise PolicyError("uid は 1〜65535 の整数が必要（0 は不可）")
    subnet = t.get("subnet")
    if subnet is not None:
        try:
            ipaddress.ip_network(subnet, strict=True)
        except (ValueError, TypeError) as e:
            raise PolicyError("subnet は CIDR が必要") from e
    upstream = t.get("proxy_upstream")
    if upstream is not None:
        upstream = validate_upstream(upstream)
    if network == "proxy-only" and upstream is None:
        raise PolicyError(f"repo.{repo_id} は proxy-only なので proxy_upstream が必要")
    return model.RepoPolicy(
        id=repo_id,
        path=path,
        data_roots=roots,
        ports=_parse_ports(t.get("ports", [])),
        brokers=tuple(brokers),  # type: ignore[arg-type]
        gpu=gpu,
        network=network,  # type: ignore[arg-type]
        proxy_upstream=upstream,
        idmap=idmap,
        uid=uid,
        subnet=subnet,
        secrets=_parse_secrets(repo_id, t.get("secrets", {})),
    )


def parse(text: str) -> model.HostPolicy:
    """許可表の本文を厳格に解釈する。"""
    try:
        doc = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise PolicyError(f"TOML の構文エラー: {e}") from e
    _check_keys(doc, {"defaults", "repo"}, "最上位")
    d = doc.get("defaults", {})
    if not isinstance(d, dict):
        raise PolicyError("defaults はテーブルが必要")
    _check_keys(d, _DEFAULT_KEYS, "defaults")
    default_net = _net_mode(d.get("network", "nat"), "defaults.network")
    deny = tuple(
        _abs_path(p, "deny_paths") for p in _str_list(d.get("deny_paths", []), "deny_paths")
    )
    template = d.get("template", "box-template")
    if not isinstance(template, str) or not _ALIAS_RE.match(template):
        raise PolicyError("template はイメージの別名（英数と . _ -）が必要")
    repos_doc = doc.get("repo", {})
    if not isinstance(repos_doc, dict):
        raise PolicyError("repo はテーブルが必要")
    build_proxy = d.get("build_proxy")
    if build_proxy is not None:
        build_proxy = validate_upstream(build_proxy)
    repos = {rid: _parse_repo(rid, t, default_net) for rid, t in repos_doc.items()}
    return model.HostPolicy(
        repos=repos,
        deny_paths=deny,
        default_network=default_net,  # type: ignore[arg-type]
        template=template,
        build_proxy=build_proxy,
    )


def check_file_safe(path: str, *, fs: Any = None) -> None:
    """許可表と、その親ディレクトリがすべて root 所有で、グループ・他人から書けないこと。"""
    from box.config import RealFs

    fs = fs or RealFs()
    cur = posixpath.normpath(path)
    while True:
        if not fs.exists(cur):
            raise PolicyError(f"許可表の経路が存在しない: {cur}")
        if fs.stat_uid(cur) != 0:
            raise PolicyError(f"root 所有でない: {cur}")
        if fs.stat_mode(cur) & 0o022:
            raise PolicyError(f"グループ・他人から書ける: {cur}")
        parent = posixpath.dirname(cur)
        if parent == cur:
            return
        cur = parent


def load(path: str = model.POLICY_PATH, *, fs: Any = None) -> model.HostPolicy:
    """許可表を読む。check_file_safe は呼び出し側（root_helper）が先に行う。"""
    from box.config import RealFs

    fs = fs or RealFs()
    if not fs.exists(path):
        raise PolicyError(f"許可表が無い: {path}")
    if fs.size(path) > 1024 * 1024:
        raise PolicyError("許可表が大きすぎる")
    try:
        text = fs.read_bytes(path).decode("utf-8")
    except UnicodeDecodeError as e:
        raise PolicyError("許可表が UTF-8 でない") from e
    return parse(text)


def _q(s: str) -> str:
    return json.dumps(s, ensure_ascii=False)  # TOML の基本文字列と互換


def render_repo_block(
    repo_id: str,
    *,
    path: str,
    data_roots: tuple[str, ...] = (),
    ports: tuple[model.PortRange, ...] = (),
    brokers: tuple[str, ...] = (),
    gpu: bool = False,
    network: str | None = None,
    proxy_upstream: str | None = None,
    idmap: str = "user",
    uid: int = 1000,
    subnet: str | None = None,
) -> str:
    """[repo.<id>] のブロックを描画する（純粋関数。描画後に parse で検証する）。"""
    lines = [f"[repo.{repo_id}]", f"path = {_q(path)}"]
    if data_roots:
        lines.append("data_roots = [" + ", ".join(_q(r) for r in data_roots) + "]")
    if ports:
        items = [str(p.lo) if p.lo == p.hi else f"[{p.lo}, {p.hi}]" for p in ports]
        lines.append("ports = [" + ", ".join(items) + "]")
    if brokers:
        lines.append("brokers = [" + ", ".join(_q(b) for b in brokers) + "]")
    if gpu:
        lines.append("gpu = true")
    if network is not None:
        lines.append(f"network = {_q(network)}")
    if proxy_upstream is not None:
        lines.append(f"proxy_upstream = {_q(proxy_upstream)}")
    lines.append(f"idmap = {_q(idmap)}")
    lines.append(f"uid = {uid}")
    if subnet is not None:
        lines.append(f"subnet = {_q(subnet)}")
    return "\n".join(lines) + "\n"  # 形の検証は add_repo が parse で行う


def add_repo(text: str, block: str) -> str:
    """許可表の本文へ [repo.<id>] を追記した新しい本文を返す（既存 id は PolicyError）。"""
    old = parse(text) if text.strip() else model.HostPolicy(repos={})
    try:
        new_doc = tomllib.loads(block)
    except tomllib.TOMLDecodeError as e:
        raise PolicyError(f"追記するブロックが不正: {e}") from e
    if set(new_doc) != {"repo"} or len(new_doc["repo"]) != 1:
        raise PolicyError("追記できるのは [repo.<id>] 1 つだけ")
    (rid,) = new_doc["repo"]
    if rid in old.repos:
        raise PolicyError(f"repo id が重複: {rid}")
    new_text = (text.rstrip("\n") + "\n\n" if text.strip() else "") + block
    parse(new_text)  # 追記後の全体が通ることを確認
    return new_text
