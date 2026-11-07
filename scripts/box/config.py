"""リポジトリの box.toml（要求）を読み、許可表（HostPolicy）と突き合わせて BoxConfig を作る。

box.toml は箱から書き換えられるので、許可表の範囲の部分集合を選ぶ「要求」にすぎない（契約 C13）。
範囲外・未知のキー・symlink・拒否リストとの重なりは、すべて ConfigError で拒否する。

box.toml の例（未知のキーは拒否）:

    data = ["models/small"]     # 許可表の data_roots の下の相対パス
    ports = [8080]
    brokers = ["gh"]
    gpu = false
    network = "offline"         # より厳しい方向にだけ効く
    images = false              # true は未対応（拒否）
"""

from __future__ import annotations

import os
import posixpath
import tomllib
from collections.abc import Sequence
from typing import Protocol

from box import model
from box.policy import BROKER_KINDS, NET_MODES

MAX_SPEC_BYTES = 64 * 1024

# コードに固定する拒否リスト（絶対パス）と、ホーム相対の拒否リスト
DENY_ABS: tuple[str, ...] = (
    "/etc/box",
    "/usr/local/libexec/box",
    "/etc/sudoers",
    "/etc/sudoers.d",
    "/var/lib/incus",
    "/var/lib/docker",
    "/var/run",
    "/run",
    "/proc",
    "/sys",
    "/dev",
)
DENY_HOME_REL: tuple[str, ...] = (
    ".ssh",
    ".gnupg",
    ".aws",
    ".azure",
    ".config/box",
    ".config/gh",
    ".docker/config.json",
    ".netrc",
    ".git-credentials",
    ".pi/agent/auth.json",
    ".cache/huggingface/token",
    ".cache/huggingface/stored_tokens",
)

_SPEC_KEYS = {"data", "ports", "brokers", "gpu", "network", "images"}


class ConfigError(ValueError):
    """box.toml または解決の拒否。"""


class Fs(Protocol):
    """ファイルシステムの読み取り口。試験では FakeFs に差し替える。"""

    def realpath(self, path: str) -> str: ...
    def isdir(self, path: str) -> bool: ...
    def islink(self, path: str) -> bool: ...
    def exists(self, path: str) -> bool: ...
    def stat_uid(self, path: str) -> int: ...
    def stat_mode(self, path: str) -> int: ...
    def size(self, path: str) -> int: ...
    def read_bytes(self, path: str) -> bytes: ...
    def home_of(self, uid: int) -> str | None: ...


class RealFs:
    def realpath(self, path: str) -> str:
        return os.path.realpath(path)

    def isdir(self, path: str) -> bool:
        return os.path.isdir(path)

    def islink(self, path: str) -> bool:
        return os.path.islink(path)

    def exists(self, path: str) -> bool:
        return os.path.lexists(path)

    def stat_uid(self, path: str) -> int:
        return os.lstat(path).st_uid

    def stat_mode(self, path: str) -> int:
        return os.lstat(path).st_mode & 0o7777

    def size(self, path: str) -> int:
        return os.lstat(path).st_size

    def read_bytes(self, path: str) -> bytes:
        with open(path, "rb") as f:
            return f.read()

    def home_of(self, uid: int) -> str | None:
        import pwd

        try:
            return pwd.getpwuid(uid).pw_dir
        except KeyError:
            return None


def _contains(parent: str, child: str) -> bool:
    parent = parent.rstrip("/")
    return child == parent or child.startswith(parent + "/")


def is_denied(path: str, deny_abs: Sequence[str] = DENY_ABS) -> bool:
    """path が拒否リストと包含関係（path が親・子・同一）にあれば True。

    ホーム相対（~/.ssh など）は、構成要素の並びとして path の中にあれば拒否する（子の方向）。
    ホームの絶対パスが分かるときは、呼び出し側が deny_abs に展開して渡すと、親の方向も拒否できる。
    """
    p = posixpath.normpath(path)
    if p == "/":
        return True
    for d in deny_abs:
        d = posixpath.normpath(d)
        if _contains(d, p) or _contains(p, d):
            return True
    parts = [x for x in p.split("/") if x]
    for rel in DENY_HOME_REL:
        seg = rel.split("/")
        for i in range(len(parts) - len(seg) + 1):
            if parts[i : i + len(seg)] == seg:
                return True
    return False


def _bad_path_chars(p: str) -> bool:
    return any(ord(c) < 32 or c == "\x7f" for c in p)


def load_spec(repo_path: str, *, fs: Fs | None = None) -> model.RepoSpec:
    """<repo_path>/box.toml を読む。無ければ既定（要求なし）。"""
    fs = fs or RealFs()
    path = posixpath.join(repo_path, "box.toml")
    if fs.islink(path):
        raise ConfigError("box.toml が symlink（拒否）")
    if not fs.exists(path):
        return model.RepoSpec()
    if fs.size(path) > MAX_SPEC_BYTES:
        raise ConfigError("box.toml が 64KiB を超える")
    try:
        doc = tomllib.loads(fs.read_bytes(path).decode("utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as e:
        raise ConfigError(f"box.toml を解釈できない: {e}") from e
    unknown = sorted(set(doc) - _SPEC_KEYS)
    if unknown:
        raise ConfigError(f"box.toml に未知のキー: {', '.join(unknown)}")

    def strs(key: str) -> tuple[str, ...]:
        v = doc.get(key, [])
        if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
            raise ConfigError(f"{key} は文字列の配列が必要")
        return tuple(v)

    ports = doc.get("ports", [])
    if not isinstance(ports, list) or not all(
        isinstance(x, int) and not isinstance(x, bool) for x in ports
    ):
        raise ConfigError("ports は整数の配列が必要")
    brokers = strs("brokers")
    bad = sorted(set(brokers) - set(BROKER_KINDS))
    if bad:
        raise ConfigError(f"brokers に未知の種類: {', '.join(bad)}")
    for key in ("gpu", "images"):
        if not isinstance(doc.get(key, False), bool):
            raise ConfigError(f"{key} は真偽値が必要")
    network = doc.get("network")
    if network is not None and network not in NET_MODES:
        raise ConfigError(f"network は {'/'.join(NET_MODES)} のいずれか")
    return model.RepoSpec(
        data=strs("data"),
        ports=tuple(ports),
        brokers=brokers,  # type: ignore[arg-type]
        gpu=doc.get("gpu", False),
        network=network,
        images=doc.get("images", False),
    )


def _resolve_data(rel: str, roots: Sequence[str], fs: Fs) -> str:
    if not rel or rel.startswith("/") or _bad_path_chars(rel):
        raise ConfigError(f"data は相対パスが必要: {rel!r}")
    parts = rel.split("/")
    if any(p in ("", ".", "..") for p in parts):
        raise ConfigError(f"data に空要素・'.'・'..' は使えない: {rel!r}")
    found: list[str] = []
    for root in roots:
        cur = root.rstrip("/")
        for part in parts:
            cur = f"{cur}/{part}"
            if fs.islink(cur):
                raise ConfigError(f"data の構成要素に symlink がある: {rel}")
        if not fs.isdir(cur):
            continue
        rp, root_rp = fs.realpath(cur), fs.realpath(root)
        if not _contains(root_rp, rp):
            raise ConfigError(f"data が許可された根の外: {rel}")
        found.append(rp)
    if not found:
        raise ConfigError(f"data が許可された根の下に無い（ディレクトリのみ可）: {rel}")
    if len(found) > 1:
        raise ConfigError(f"data が複数の根で見つかり曖昧: {rel}")
    return found[0]


def resolve(
    policy: model.HostPolicy,
    repo_id: str,
    spec: model.RepoSpec,
    fs: Fs,
    *,
    host_ports_in_use: Sequence[int] = (),
) -> model.BoxConfig:
    """許可表と要求を突き合わせる。範囲外・拒否対象は ConfigError。"""
    rp = policy.repos.get(repo_id)
    if rp is None:
        raise ConfigError(f"未登録の repo id: {repo_id}")
    if spec.images:
        raise ConfigError("images は未対応")

    # 拒否リスト（コード固定＋許可表＋ホームの秘密の絶対パス展開）
    deny = list(DENY_ABS) + list(policy.deny_paths)
    home = fs.home_of(rp.uid)
    if home:
        deny += [posixpath.join(home, rel) for rel in DENY_HOME_REL]

    # リポジトリ本体
    repo = rp.path
    if fs.islink(repo) or not fs.isdir(repo):
        raise ConfigError("リポジトリが実在のディレクトリではない（symlink も不可）")
    if fs.realpath(repo) != posixpath.normpath(repo):
        raise ConfigError("リポジトリのパスの構成要素に symlink がある")
    if is_denied(repo, deny):
        raise ConfigError("リポジトリが拒否リストと重なる")

    # ブローカー・GPU
    brokers: list[str] = []
    for b in spec.brokers:
        if b not in rp.brokers:
            raise ConfigError(f"許可されていないブローカー: {b}")
        if b not in brokers:
            brokers.append(b)
    if spec.gpu and not rp.gpu:
        raise ConfigError("許可されていない gpu")

    # ネットワーク（より厳しい方向にだけ）
    network = model.effective_network(rp.network, spec.network)
    if network == "proxy-only" and not rp.proxy_upstream:
        raise ConfigError("proxy-only には許可表の proxy_upstream が必要")

    # ポート
    ports: list[model.PortForward] = []
    seen: set[int] = set()
    for p in spec.ports:
        if not 1 <= p <= 65535:
            raise ConfigError(f"ポートが範囲外: {p}")
        if not any(r.contains(p) for r in rp.ports):
            raise ConfigError(f"許可されていないポート: {p}")
        if p in seen:
            raise ConfigError(f"ポートが重複: {p}")
        if p in host_ports_in_use:
            raise ConfigError(f"ポートが使用中: {p}")
        seen.add(p)
        ports.append(model.PortForward(box_port=p, host_port=p))

    # マウント
    mounts: list[model.Mount] = [model.Mount("repo", repo, repo, False)]
    git = posixpath.join(repo, ".git")
    if fs.isdir(git) and not fs.islink(git):
        for sub in ("hooks", "config"):
            src = posixpath.join(git, sub)
            if fs.islink(src):
                raise ConfigError(f".git/{sub} が symlink（拒否）")
            if fs.exists(src):
                mounts.append(model.Mount("repo", src, src, True))
    for rel in spec.data:
        src = _resolve_data(rel, rp.data_roots, fs)
        if is_denied(src, deny):
            raise ConfigError(f"data が拒否リストと重なる: {rel}")
        if _contains(repo, src) or _contains(src, repo):
            raise ConfigError(f"data がリポジトリと重なる: {rel}")
        mounts.append(model.Mount("data", src, src, True))
    if spec.gpu:
        mounts.append(model.Mount("gpu-lib", model.GPU_LIB, model.GPU_LIB, True))
        mounts.append(model.Mount("gpu-drivers", model.GPU_DRIVERS, model.GPU_DRIVERS, True))

    return model.BoxConfig(
        name=model.box_name(repo_id),
        repo_id=repo_id,
        repo_path=repo,
        uid=rp.uid,
        idmap=rp.idmap,
        mounts=tuple(mounts),
        ports=tuple(ports),
        brokers=tuple(brokers),  # type: ignore[arg-type]
        gpu=spec.gpu,
        network=network,
        proxy_upstream=rp.proxy_upstream,
        subnet=rp.subnet,
        labels={
            model.LABEL_PREFIX + "repo": repo_id,
            model.LABEL_PREFIX + "managed": "true",
        },
    )
