"""箱の外向き通信（box.net）の試験。incus・nft・ネットワークは呼ばない。"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from box import net
from box.model import BoxConfig, FilePut, Op

UPSTREAM = "192.0.2.10:3128"


def cfg(network="nat", upstream=UPSTREAM) -> BoxConfig:
    return BoxConfig(
        name="box-x",
        repo_id="x",
        repo_path="/work/x",
        uid=1000,
        idmap="user",
        mounts=(),
        ports=(),
        brokers=(),
        gpu=False,
        network=network,
        proxy_upstream=upstream,
        subnet=None,
    )


def files(p):
    return {f.path: f for f in p.files}


def test_nat_は_nic_だけ():
    p = net.plan(cfg("nat"))
    assert [(d.type, dict(d.config)) for d in p.devices] == [
        ("nic", {"network": "incusbr0", "name": "eth0"})
    ]
    assert p.files == () and dict(p.env) == {}
    assert [r.path for r in p.routes] == ["NAT（incusbr0 → ホストの外）"]


def test_proxy_only_は_nic_なしで_proxy_1つ():
    p = net.plan(cfg("proxy-only"))
    assert [d.type for d in p.devices] == ["proxy"]
    assert dict(p.devices[0].config) == {
        "bind": "instance",
        "listen": "tcp:0.0.0.0:3128",
        "connect": f"tcp:{UPSTREAM}",
    }
    assert [r.path for r in p.routes] == ["proxy デバイス → 上流プロキシ"]
    assert p.routes[0].upstream == UPSTREAM


def test_proxy_only_の箱内ファイルと環境変数():
    p = net.plan(cfg("proxy-only"))
    f = files(p)
    assert set(f) == {
        "/etc/environment",
        "/etc/apt/apt.conf.d/99box-proxy",
        "/etc/systemd/system/docker.service.d/box-proxy.conf",
        "/etc/gitconfig",
        "/etc/profile.d/box-proxy.sh",
    }
    assert all(isinstance(x, FilePut) and x.where == "box" for x in p.files)
    env = f["/etc/environment"].content
    for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
        assert f"{k}=http://127.0.0.1:3128\n" in env
    assert "NO_PROXY=127.0.0.1,localhost,::1,172.17.0.1,host.docker.internal\n" in env
    assert "/run/box" not in env
    assert "Acquire::https::Proxy" in f["/etc/apt/apt.conf.d/99box-proxy"].content
    assert "HTTPS_PROXY=http://127.0.0.1:3128" in (
        f["/etc/systemd/system/docker.service.d/box-proxy.conf"].content
    )
    assert "proxy = http://127.0.0.1:3128" in f["/etc/gitconfig"].content
    assert dict(p.env)["HTTPS_PROXY"] == "http://127.0.0.1:3128"
    assert "172.17.0.1" in dict(p.env)["NO_PROXY"]


def test_compose_のコンテナには環境変数を渡さない():
    p = net.plan(cfg("proxy-only"))
    assert not any("config.json" in x.path or ".docker" in x.path for x in p.files)
    assert "compose" in (net.__doc__ or "")


def test_proxy_only_で上流が無い・不正なら拒否():
    for bad in (None, "", "proxy.example.test", "proxy.example.test:99999"):
        with pytest.raises(net.NetError):
            net.plan(cfg("proxy-only", bad))
        with pytest.raises(net.NetError):
            net.routes_table(cfg("proxy-only", bad))
    assert net.plan(cfg("proxy-only", "proxy.example.test:3128")).devices


def test_offline_は外向きの経路が無い():
    p = net.plan(cfg("offline", upstream=None))
    assert p.devices == () and p.files == () and dict(p.env) == {} and p.routes == ()


@pytest.mark.parametrize("mode", ["proxy-only", "offline"])
def test_nat_以外は_nic_が付かない(mode):
    assert all(d.type != "nic" for d in net.plan(cfg(mode)).devices)


@pytest.mark.parametrize("mode", ["proxy-only", "offline"])
def test_nic_なしモードは_box_nonet_プロファイルを使う(mode):
    """default プロファイルは eth0（NIC）を持つので、NIC なしの箱は box-nonet を使う。"""
    p = net.plan(cfg(mode))
    assert p.profiles == ("box-nonet",)
    argvs = [o.argv for o in p.profile_ops]
    assert ("incus", "profile", "create", "box-nonet") in argvs
    assert (
        "incus",
        "profile",
        "device",
        "add",
        "box-nonet",
        "root",
        "disk",
        "path=/",
        "pool=default",
    ) in argvs
    # プロファイルの Op は冪等（既にあっても失敗で止めない）で、box-nonet 以外に触れない
    assert all(not o.check and "box-nonet" in o.argv for o in p.profile_ops)


def test_nat_は_default_プロファイルで_プロファイル操作なし():
    p = net.plan(cfg("nat"))
    assert p.profiles == ("default",) and p.profile_ops == ()


@pytest.mark.parametrize("mode", ["nat", "proxy-only", "offline"])
def test_経路表は_plan_の_routes_と一致(mode):
    c = cfg(mode)
    assert net.routes_table(c) == net.plan(c).routes
    assert all(mode in r.modes for r in net.routes_table(c))


def _cmds(plan):
    return [x for x in plan if isinstance(x, Op)]


def test_host_setup_plan_の準備():
    ops = net.host_setup_plan()
    assert ("incus", "network", "set", "incusbr0", "ipv6.address", "none") in [
        o.argv for o in _cmds(ops)
    ]
    assert not any("ipv4.address" in o.argv for o in _cmds(ops))
    with_subnet = net.host_setup_plan("10.99.0.1/24")
    assert ("incus", "network", "set", "incusbr0", "ipv4.address", "10.99.0.1/24") in [
        o.argv for o in _cmds(with_subnet)
    ]
    assert all(o.where == "host" for o in ops)


def test_追加スクリプトは冪等でコメントつき_docker_user_なしなら何もしない():
    f = {x.path: x for x in net.host_setup_plan() if isinstance(x, FilePut)}
    add = f[net.FORWARD_ADD_SCRIPT].content
    assert add.startswith("#!/bin/sh\n") and "set -eu" in add
    assert add.count("grep -qF") == 2  # 挿入前に同じ規則の有無を見る
    assert add.count("nft insert rule") == 2
    assert add.count("incus-box") >= 4  # 各規則にコメント
    assert 'iifname "incusbr0" accept' in add
    assert 'oifname "incusbr0" ct state established,related accept' in add
    # DOCKER-USER が無ければ exit 0（挿入より前）
    assert add.index("exit 0") < add.index("nft insert rule")
    assert "nft list chain ip filter DOCKER-USER" in add


def test_削除スクリプトはコメント_incus_box_の規則だけ():
    f = {x.path: x for x in net.host_setup_plan() if isinstance(x, FilePut)}
    d = f[net.FORWARD_DEL_SCRIPT].content
    assert 'comment "incus-box"' in d and "nft delete rule ip filter DOCKER-USER handle" in d
    assert "flush" not in d
    assert d.index("exit 0") < d.index("nft delete rule")
    assert [o.argv for o in net.host_teardown_plan()][1] == (net.FORWARD_DEL_SCRIPT,)


def test_ユニットの内容():
    f = {x.path: x for x in net.host_setup_plan() if isinstance(x, FilePut)}
    u = f[net.FORWARD_UNIT_PATH].content
    assert "After=docker.service incus.service" in u
    assert f"ExecStart={net.FORWARD_ADD_SCRIPT}" in u
    assert f"ExecStop={net.FORWARD_DEL_SCRIPT}" in u
    assert "Type=oneshot" in u
    argvs = [o.argv for o in _cmds(net.host_setup_plan())]
    assert ("systemctl", "enable", "--now", "box-forward.service") in argvs


def test_本体は_dotfiles_固有のものを_import_しない():
    root = Path(net.__file__).parent
    for py in (root / "net.py", root / "tools" / "fake_proxy.py"):
        for node in ast.walk(ast.parse(py.read_text(encoding="utf-8"))):
            mods = []
            if isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                mods = [("." * node.level) + (node.module or "")]
            for m in mods:
                assert not m.startswith(("scripts", "adapters", "verify")), (py, m)
                assert not m.startswith("..") or m == ".model" or m.startswith(".model"), (py, m)
