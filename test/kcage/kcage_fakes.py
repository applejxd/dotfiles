"""箱の試験用の偽物（FakeFs・FakeRunner）と、共通の許可表。incus も root も要らない。"""

from __future__ import annotations

import posixpath
from collections.abc import Sequence

from kcage import model, policy

POLICY_TEXT = """\
[defaults]
network = "nat"
deny_paths = ["/mnt/d/private"]

[repo.demo]
path = "/home/alice/work/demo"
data_roots = ["/mnt/d/datasets", "/mnt/e/data"]
ports = [8080, [9000, 9099]]
brokers = ["gh", "copilot"]
gpu = true
network = "proxy-only"
proxy_upstream = "192.0.2.10:3128"
uid = 1000
"""


class FakeFs:
    """メモリ上のファイルシステム。symlink・所有者・権限を表せる。"""

    def __init__(self) -> None:
        self.nodes: dict[str, dict] = {}
        self.homes: dict[int, str] = {1000: "/home/alice"}
        self.add_dir("/")

    def _parents(self, path: str) -> None:
        cur = posixpath.dirname(path)
        while cur not in self.nodes:
            self.nodes[cur] = {"kind": "dir", "uid": 0, "mode": 0o755}
            cur = posixpath.dirname(cur)

    def add_dir(self, path: str, uid: int = 0, mode: int = 0o755) -> None:
        self._parents(path)
        self.nodes[path] = {"kind": "dir", "uid": uid, "mode": mode}

    def add_file(self, path: str, data: bytes | str = b"", uid: int = 0, mode: int = 0o644) -> None:
        self._parents(path)
        raw = data.encode() if isinstance(data, str) else data
        self.nodes[path] = {"kind": "file", "uid": uid, "mode": mode, "data": raw}

    def add_link(self, path: str, target: str) -> None:
        self._parents(path)
        self.nodes[path] = {"kind": "link", "uid": 0, "mode": 0o777, "target": target}

    def realpath(self, path: str) -> str:
        parts = [p for p in path.split("/") if p]
        resolved: list[str] = []
        for _ in range(40):
            changed = False
            resolved = []
            for i, p in enumerate(parts):
                cur = "/" + "/".join([*resolved, p])
                node = self.nodes.get(cur)
                if node and node["kind"] == "link":
                    tgt = node["target"]
                    base = tgt if tgt.startswith("/") else "/" + "/".join([*resolved, tgt])
                    parts = [x for x in posixpath.normpath(base).split("/") if x] + parts[i + 1 :]
                    changed = True
                    break
                resolved.append(p)
            if not changed:
                break
        return "/" + "/".join(resolved)

    def _node(self, path: str) -> dict | None:
        return self.nodes.get(self.realpath(path))

    def isdir(self, path: str) -> bool:
        n = self._node(path)
        return bool(n and n["kind"] == "dir")

    def islink(self, path: str) -> bool:
        n = self.nodes.get(path)
        return bool(n and n["kind"] == "link")

    def exists(self, path: str) -> bool:
        return path in self.nodes or self._node(path) is not None

    def stat_uid(self, path: str) -> int:
        return self.nodes[path]["uid"]

    def stat_mode(self, path: str) -> int:
        return self.nodes[path]["mode"]

    def size(self, path: str) -> int:
        return len(self.nodes[path].get("data", b""))

    def read_bytes(self, path: str) -> bytes:
        return self.nodes[path]["data"]

    def home_of(self, uid: int) -> str | None:
        return self.homes.get(uid)


def demo_fs() -> FakeFs:
    fs = FakeFs()
    fs.add_dir("/home/alice/work/demo", uid=1000)
    fs.add_dir("/home/alice/work/demo/.git", uid=1000)
    fs.add_dir("/home/alice/work/demo/.git/hooks", uid=1000)
    fs.add_file("/home/alice/work/demo/.git/config", "[core]\n", uid=1000)
    fs.add_dir("/mnt/d/datasets/models/small", uid=1000)
    fs.add_dir("/mnt/e/data/other", uid=1000)
    fs.add_dir("/etc/kcage")
    fs.add_file("/etc/kcage/policy.toml", POLICY_TEXT)
    return fs


def demo_policy() -> model.HostPolicy:
    return policy.parse(POLICY_TEXT)


class Res:
    def __init__(self, rc: int = 0, out: str = "") -> None:
        self.rc, self.out = rc, out


class FakeRunner:
    """実行した argv・stdin を記録する。capture は incus の状態の問い合わせに答える。"""

    def __init__(self, status: str = "", label: str = "") -> None:
        self.calls: list[tuple[tuple[str, ...], bytes | None]] = []
        self.status, self.label = status, label
        self.fail_on: set[tuple[str, ...]] = set()

    def run(self, argv: Sequence[str], *, stdin: bytes | None = None, check: bool = True) -> int:
        self.calls.append((tuple(argv), stdin))
        return 0

    def capture(self, argv: Sequence[str]) -> tuple[int, str]:
        a = tuple(argv)
        if a[:2] == ("incus", "list"):
            return 0, self.status + "\n" if self.status else ""
        if a[:3] == ("incus", "config", "get"):
            return 0, self.label + "\n"
        return 1, ""

    @property
    def argvs(self) -> list[tuple[str, ...]]:
        return [c[0] for c in self.calls]
