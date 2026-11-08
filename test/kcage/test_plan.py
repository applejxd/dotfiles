"""scripts/kcage/plan.py の試験。デバイスの固定生成と、device_to_argv の二重の防御。"""

from __future__ import annotations

import pytest
from kcage import config, model, plan
from kcage_fakes import demo_fs, demo_policy

PE = plan.PlanError


def _cfg(spec: model.RepoSpec | None = None, **over) -> model.BoxConfig:
    cfg = config.resolve(demo_policy(), "demo", spec or model.RepoSpec(), demo_fs())
    import dataclasses

    return dataclasses.replace(cfg, **over)


def _dev(type_: str, **cfg: str) -> model.DeviceSpec:
    return model.DeviceSpec("d1", type_, cfg)  # type: ignore[arg-type]


def _net(mode: str = "proxy-only", **kw) -> model.NetPlan:
    return model.NetPlan(mode=mode, **kw)  # type: ignore[arg-type]


# ---- devices_for / instance_config


def test_devices_for_fixed_generation() -> None:
    cfg = _cfg(model.RepoSpec(data=("models/small",), ports=(8080,), gpu=True))
    devs = plan.devices_for(cfg)
    by = {d.name: d for d in devs}
    assert by["gpu-dxg"].type == "unix-char" and by["gpu-dxg"].config["source"] == "/dev/dxg"
    p = by["p-8080"].config
    assert p == {"bind": "host", "listen": "tcp:127.0.0.1:8080", "connect": "tcp:127.0.0.1:8080"}
    disks = [d for d in devs if d.type == "disk"]
    assert all(d.name.startswith("m-") for d in disks)
    assert any(d.config["readonly"] == "false" for d in disks)  # リポジトリだけが rw
    assert sum(d.config["readonly"] == "false" for d in disks) == 2  # リポジトリと .git の pin
    for d in devs:  # 生成物は必ず関門を通る
        plan.device_to_argv(cfg.name, d)


def test_instance_config() -> None:
    c = plan.instance_config(_cfg())
    assert c["security.privileged"] == "false" and c["security.nesting"] == "true"
    assert c["raw.idmap"] == "uid 1000 1000\ngid 1000 1000"
    assert c[plan.LABEL_KEY] == "demo"
    root = plan.instance_config(_cfg(idmap="root"))
    assert root["raw.idmap"] == "uid 1000 0\ngid 1000 0"


def test_instance_config_gidがuidと違う() -> None:
    user = plan.instance_config(_cfg(gid=1001))
    assert user["raw.idmap"] == "uid 1000 1000\ngid 1001 1000"
    root = plan.instance_config(_cfg(idmap="root", gid=1001))
    assert root["raw.idmap"] == "uid 1000 0\ngid 1001 0"


# ---- device_to_argv

GOOD_PROXY_INST = {
    "bind": "instance",
    "listen": "tcp:127.0.0.1:3128",
    "connect": "tcp:192.0.2.10:3128",
}


@pytest.mark.parametrize(
    "source",
    [
        "/var/run/docker.sock",
        "/run/docker.sock",
        "/var/lib/incus/unix.socket",
        "/var/run",
        "/usr/local/libexec/kcage",
        "/etc/sudoers.d",
        "/tmp/anything.sock",
    ],
)
def test_disk_は管理ソケットや配備先を重ねない(source: str) -> None:
    """親の敵対的検証で見つけた穴: /var/run/docker.sock が通っていた（/var/run は /run への symlink）。"""
    with pytest.raises(plan.PlanError):
        plan.device_to_argv("kcage-demo", _dev("disk", source=source, path="/x", readonly="true"))


def test_device_to_argv_shapes() -> None:
    a = plan.device_to_argv("kcage-demo", _dev("disk", source="/a/b", path="/a/b", readonly="true"))
    assert a == (
        "incus", "config", "device", "add", "kcage-demo", "d1", "disk",
        "source=/a/b", "path=/a/b", "readonly=true",
    )  # fmt: skip
    assert plan.device_to_argv("kcage-demo", _dev("proxy", **GOOD_PROXY_INST))[-3:] == (
        "listen=tcp:127.0.0.1:3128",
        "connect=tcp:192.0.2.10:3128",
        "bind=instance",
    )
    plan.device_to_argv("kcage-demo", _dev("nic", network="incusbr0", name="eth0"))
    plan.device_to_argv("kcage-demo", _dev("unix-char", source="/dev/dxg", path="/dev/dxg"))


@pytest.mark.parametrize(
    "dev",
    [
        # 許可外のキー
        _dev("disk", source="/a", path="/a", shared="true"),
        _dev("disk", source="/a", path="/a", propagation="rshared"),
        _dev("proxy", **GOOD_PROXY_INST, **{"security.uid": "0"}),
        _dev("nic", network="incusbr0", name="e", nictype="bridged"),
        _dev("unix-char", source="/dev/dxg", path="/dev/dxg", mode="0777"),
        # 必須キーなし
        _dev("disk", source="/a"),
        _dev("proxy", listen="tcp:127.0.0.1:1", connect="tcp:127.0.0.1:1"),
        # disk の source
        _dev("disk", source="/", path="/x"),
        _dev("disk", source="/etc/kcage", path="/x"),
        _dev("disk", source="/etc/kcage/policy.toml", path="/x"),
        _dev("disk", source="/etc", path="/x"),
        _dev("disk", source="/var/lib/incus", path="/x"),
        _dev("disk", source="/var/lib/incus/unix.socket", path="/x"),
        _dev("disk", source="/run/docker.sock", path="/x"),
        _dev("disk", source="/dev", path="/x"),
        _dev("disk", source="/home/alice/.ssh", path="/x"),
        _dev("disk", source="/home/alice/.aws/credentials", path="/x"),
        _dev("disk", source="/a/../etc/kcage", path="/x"),
        _dev("disk", source="relative", path="/x"),
        _dev("disk", source="/a", path="relative"),
        _dev("disk", source="/a", path="/x", readonly="maybe"),
        # unix-char
        _dev("unix-char", source="/dev/mem", path="/dev/mem"),
        _dev("unix-char", source="/dev/dxg", path="/dev/other"),
        _dev("unix-char", source="/dev/kmem", path="/dev/dxg"),
        # nic
        _dev("nic", network="other", name="eth0"),
        # 種別
        _dev("usb"),
        _dev("gpu"),
        _dev("infiniband"),
    ],
)
def test_device_rejected(dev: model.DeviceSpec) -> None:
    with pytest.raises(PE):
        plan.device_to_argv("kcage-demo", dev)


@pytest.mark.parametrize(
    "cfg",
    [
        # 管理ソケットへの転送（どの形でも拒否）
        {
            "bind": "host",
            "listen": "tcp:127.0.0.1:8080",
            "connect": "unix:/var/lib/incus/unix.socket",
        },
        {
            "bind": "instance",
            "listen": "unix:/var/lib/kcage-sock/x.sock",
            "connect": "unix:/var/lib/incus/unix.socket",
        },
        {
            "bind": "instance",
            "listen": "unix:/var/lib/kcage-sock/x.sock",
            "connect": "unix:/var/run/docker.sock",
        },
        {
            "bind": "instance",
            "listen": "unix:/var/lib/kcage-sock/x.sock",
            "connect": "unix:/run/docker.sock",
        },
        {
            "bind": "instance",
            "listen": "unix:/var/lib/kcage-sock/docker.sock",
            "connect": "unix:/run/kcage-broker/demo/gh.sock",
        },
        {
            "bind": "instance",
            "listen": "unix:/var/lib/kcage-sock/x.sock",
            "connect": "unix:/run/kcage-broker/demo/unix.socket",
        },
        {
            "bind": "instance",
            "listen": "unix:/var/lib/kcage-sock/x.sock",
            "connect": "unix:/run/other/x.sock",
        },
        {
            "bind": "instance",
            "listen": "unix:/var/lib/kcage-sock/x.sock",
            "connect": "unix:/run/kcage-broker/../x.sock",
        },
        {
            "bind": "instance",
            "listen": "unix:/var/lib/kcage-sock/x.sock",
            "connect": "unix:/run/kcage-broker/demo/sub/x.sock",
        },
        {
            "bind": "instance",
            "listen": "unix:/var/lib/kcage-sock/../x.sock",
            "connect": "unix:/run/kcage-broker/demo/gh.sock",
        },
        {
            "bind": "instance",
            "listen": "unix:/tmp/x.sock",
            "connect": "unix:/run/kcage-broker/demo/gh.sock",
        },
        # bind=host は loopback の tcp だけ
        {"bind": "host", "listen": "tcp:0.0.0.0:8080", "connect": "tcp:127.0.0.1:8080"},
        {"bind": "host", "listen": "tcp:127.0.0.1:8080", "connect": "tcp:192.0.2.1:80"},
        {
            "bind": "host",
            "listen": "unix:/var/lib/kcage-sock/x.sock",
            "connect": "tcp:127.0.0.1:80",
        },
        {"bind": "host", "listen": "tcp:127.0.0.1:0", "connect": "tcp:127.0.0.1:80"},
        {"bind": "host", "listen": "tcp:127.0.0.1:70000", "connect": "tcp:127.0.0.1:80"},
        # bind の値・tcp の形
        {"bind": "both", "listen": "tcp:127.0.0.1:80", "connect": "tcp:192.0.2.1:80"},
        {"bind": "instance", "listen": "tcp:127.0.0.1:80", "connect": "tcp:[::1]:80"},
        {"bind": "instance", "listen": "tcp:127.0.0.1:80", "connect": "tcp:bad host:80"},
        {"bind": "instance", "listen": "tcp:10.0.0.1:80", "connect": "tcp:192.0.2.1:80"},
        {"bind": "instance", "listen": "udp:127.0.0.1:80", "connect": "tcp:192.0.2.1:80"},
        {"bind": "instance", "listen": "tcp:127.0.0.1:80", "connect": "tcp:192.0.2.1:99999"},
        {"bind": "instance", "listen": "tcp:127.0.0.1:80", "connect": "tcp:example.test"},
    ],
)
def test_proxy_rejected(cfg: dict[str, str]) -> None:
    with pytest.raises(PE):
        plan.device_to_argv("kcage-demo", _dev("proxy", **cfg))


@pytest.mark.parametrize(
    "cfg",
    [
        {"bind": "instance", "listen": "tcp:127.0.0.1:3128", "connect": "tcp:192.0.2.10:3128"},
        {
            "bind": "instance",
            "listen": "tcp:0.0.0.0:3128",
            "connect": "tcp:proxy.example.test:3128",
        },
        {
            "bind": "instance",
            "listen": "unix:/var/lib/kcage-sock/gh.sock",
            "connect": "unix:/run/kcage-broker/demo/gh.sock",
        },
        {"bind": "host", "listen": "tcp:127.0.0.1:8080", "connect": "tcp:127.0.0.1:8080"},
    ],
)
def test_proxy_allowed(cfg: dict[str, str]) -> None:
    plan.device_to_argv("kcage-demo", _dev("proxy", **cfg))


def test_device_to_argv_bad_names() -> None:
    with pytest.raises(PE):
        plan.device_to_argv("demo", _dev("nic", network="incusbr0", name="e"))  # 接頭辞なし
    with pytest.raises(PE):
        plan.device_to_argv(
            "kcage-demo",
            model.DeviceSpec("a b", "unix-char", {"source": "/dev/dxg", "path": "/dev/dxg"}),
        )


# ---- plan_up


def _route(modes: tuple[str, ...]) -> model.Route:
    return model.Route("gh", "unix ソケット → ホストのブローカー", modes)  # type: ignore[arg-type]


def _broker(kind: str = "gh", modes: tuple[str, ...] = ("nat", "proxy-only")) -> model.BrokerPlan:
    return model.BrokerPlan(
        kind=kind,  # type: ignore[arg-type]
        host_ops=(model.Op("host", ("/bin/true", kind), f"{kind} 起動"),),
        devices=(
            model.DeviceSpec(
                f"b-{kind}",
                "proxy",
                {
                    "bind": "instance",
                    "listen": f"unix:/var/lib/kcage-sock/{kind}.sock",
                    "connect": f"unix:/run/kcage-broker/demo/{kind}.sock",
                },
            ),
        ),
        readiness=model.Op("host", ("/bin/true", "ready"), f"{kind} 確認"),
        stop_ops=(model.Op("host", ("/bin/true", "stop", kind), f"{kind} 停止"),),
        routes=(_route(modes),),
    )


def _up(cfg, net, brokers=(), **kw):
    base = {"template": "kcage-template", "exists": False, "running": False}
    return plan.plan_up(cfg, net, brokers, **{**base, **kw})


def test_plan_up_new_box_order() -> None:
    cfg = _cfg(model.RepoSpec(brokers=("gh",)))
    nic = model.DeviceSpec("eth0", "nic", {"network": "incusbr0", "name": "eth0"})
    p = _up(cfg, _net(devices=(nic,)), [_broker()])
    kinds = [type(s).__name__ for s in p.steps]
    assert kinds[0] == "Op" and p.steps[0].argv[:4] == (
        "incus",
        "init",
        "kcage-template",
        "kcage-demo",
    )  # type: ignore[union-attr]
    argv0 = p.steps[0].argv  # type: ignore[union-attr]
    assert "-c" in argv0 and "security.privileged=false" in argv0
    assert argv0[argv0.index("-p") : argv0.index("-p") + 2] == ("-p", "default")
    devs = [s for s in p.steps if isinstance(s, model.DeviceSpec)]
    assert {d.name for d in devs} >= {"eth0", "b-gh"}
    start = next(
        i
        for i, s in enumerate(p.steps)
        if isinstance(s, model.Op) and s.argv[:2] == ("incus", "start")
    )
    assert all(i < start for i, s in enumerate(p.steps) if isinstance(s, model.DeviceSpec))
    assert p.steps[start + 1].argv == ("true",)  # type: ignore[union-attr]
    assert p.steps[-1].desc == "gh 確認"  # type: ignore[union-attr]
    assert p.routes == (_route(("nat", "proxy-only")),)


def test_plan_up_nonet_profile() -> None:
    cfg = _cfg()
    ops = (
        model.Op("host", ("incus", "profile", "create", "kcage-nonet"), "作成", check=False),
        model.Op(
            "host",
            (
                "incus",
                "profile",
                "device",
                "add",
                "kcage-nonet",
                "root",
                "disk",
                "path=/",
                "pool=default",
            ),
            "root",
        ),
    )
    p = _up(cfg, _net(profile_ops=ops, profiles=("kcage-nonet",)))
    # プロファイルは init の前に作る（e2e で、後だと「プロファイルが無い」で up が失敗した）
    assert p.steps[0:2] == ops
    init = p.steps[2].argv  # type: ignore[union-attr]
    assert init[:2] == ("incus", "init")
    assert init[init.index("-p") + 1] == "kcage-nonet" and "default" not in init


@pytest.mark.parametrize(
    "profiles", [("default", "kcage-nonet"), ("other",), (), ("kcage-nonet", "x")]
)
def test_plan_up_rejects_profiles(profiles: tuple[str, ...]) -> None:
    with pytest.raises(PE):
        _up(_cfg(), _net(profiles=profiles))


@pytest.mark.parametrize(
    "argv",
    [
        ("incus", "profile", "create", "other"),
        ("incus", "profile", "device", "add", "kcage-nonet", "x", "proxy", "listen=a", "connect=b"),
        ("incus", "profile", "device", "add", "default", "root", "disk", "path=/", "pool=default"),
        ("incus", "profile", "set", "kcage-nonet", "security.privileged=true"),
        (
            "incus",
            "profile",
            "device",
            "add",
            "kcage-nonet",
            "root",
            "disk",
            "path=/",
            "pool=default",
            "x=1",
        ),
        ("sh", "-c", "id"),
        ("incus", "profile", "create", "kcage-nonet", "--project", "x"),
    ],
)
def test_plan_up_rejects_profile_ops(argv: tuple[str, ...]) -> None:
    net = _net(profile_ops=(model.Op("host", argv, "x"),), profiles=("kcage-nonet",))
    with pytest.raises(PE, match="profile_ops"):
        _up(_cfg(), net)
    box_op = model.Op("box", ("incus", "profile", "create", "kcage-nonet"), "x")
    with pytest.raises(PE):  # 実行場所が kcage のものも不可
        _up(_cfg(), _net(profile_ops=(box_op,), profiles=("kcage-nonet",)))


def test_plan_up_rejects_bad_net_device() -> None:
    bad = model.DeviceSpec(
        "evil",
        "proxy",
        {"bind": "host", "listen": "tcp:127.0.0.1:1", "connect": "unix:/var/lib/incus/unix.socket"},
    )
    with pytest.raises(PE):
        _up(_cfg(), _net(devices=(bad,)))
    bad_broker = model.BrokerPlan(kind="gh", devices=(bad,), routes=(_route(("proxy-only",)),))
    with pytest.raises(PE):
        _up(_cfg(), _net(), [bad_broker])


def test_plan_up_net_mode_mismatch() -> None:
    with pytest.raises(PE):
        _up(_cfg(), _net("nat"))


def test_plan_up_idempotent() -> None:
    cfg = _cfg()
    running = _up(cfg, _net(), exists=True, running=True, existing_repo_label="demo")
    assert running.steps == ()
    stopped = _up(cfg, _net(), exists=True, running=False, existing_repo_label="demo")
    argvs = [s.argv for s in stopped.steps if isinstance(s, model.Op)]  # type: ignore[union-attr]
    assert argvs == [("incus", "start", "kcage-demo"), ("true",)]
    assert not any(isinstance(s, model.DeviceSpec) for s in stopped.steps)  # 再作成しない


@pytest.mark.parametrize("label", [None, "other", ""])
def test_plan_up_collision(label: str | None) -> None:
    with pytest.raises(PE, match="衝突"):
        _up(_cfg(), _net(), exists=True, running=True, existing_repo_label=label)


def test_plan_up_offline_drops_brokers() -> None:
    cfg = _cfg(model.RepoSpec(network="offline", brokers=("gh",)))
    assert cfg.network == "offline"
    gh = _broker("gh", ("nat", "proxy-only"))
    p = _up(cfg, _net("offline"), [gh])
    assert not any(isinstance(s, model.DeviceSpec) and s.name == "b-gh" for s in p.steps)
    assert not any(isinstance(s, model.Op) and "gh" in s.desc for s in p.steps)
    assert p.routes == ()
    # offline でも有効な経路のブローカーは残る
    keep = _broker("hf-cache", ("nat", "proxy-only", "offline"))
    p2 = _up(cfg, _net("offline"), [gh, keep])
    assert any(isinstance(s, model.DeviceSpec) and s.name == "b-hf-cache" for s in p2.steps)
    assert len(p2.routes) == 1


# ---- stop / rm / exec


def test_plan_stop_rm() -> None:
    cfg = _cfg()
    s = plan.plan_stop(cfg, [_broker()])
    assert s.steps[0].argv == ("incus", "stop", "kcage-demo")  # type: ignore[union-attr]
    assert s.steps[-1].desc == "gh 停止"  # type: ignore[union-attr]
    r = plan.plan_rm(cfg, [_broker()])
    assert r.steps[-1].argv == ("incus", "delete", "--force", "kcage-demo")  # type: ignore[union-attr]


def test_plan_exec_fixed_shape() -> None:
    cfg = _cfg()
    p = plan.plan_exec(cfg, ["pi", "--help"])
    assert p.steps[0].argv == (  # type: ignore[union-attr]
        "incus", "exec", "kcage-demo", "--user", "1000", "--group", "1000", "--cwd", REPO_PATH,
        "--env", "HOME=/home/ubuntu", "--", "pi", "--help",
    )  # fmt: skip
    with pytest.raises(PE):
        plan.plan_exec(cfg, [])


REPO_PATH = "/home/alice/work/demo"


def test_plan_functions_are_pure() -> None:
    cfg = _cfg()
    assert plan.devices_for(cfg) == plan.devices_for(cfg)
    assert plan.plan_exec(cfg, ["a"]) == plan.plan_exec(cfg, ["a"])


_SOCK = {
    "bind": "instance",
    "listen": "unix:/var/lib/kcage-sock/gh.sock",
    "connect": "unix:/run/kcage-broker/demo/gh.sock",
}


def test_proxy_unix_owner_keys_allowed() -> None:
    a = plan.device_to_argv(
        "kcage-demo", _dev("proxy", **_SOCK, uid="1000", gid="1000", mode="0600")
    )
    assert a[-3:] == ("uid=1000", "gid=1000", "mode=0600")
    plan.device_to_argv("kcage-demo", _dev("proxy", **_SOCK, uid="1000", gid="1000", mode="0660"))


@pytest.mark.parametrize(
    "extra",
    [
        {"mode": "0666"},
        {"mode": "0777"},
        {"mode": "600"},
        {"uid": "0"},
        {"uid": "-1"},
        {"uid": "01000"},
        {"gid": "abc"},
        {"uid": "70000"},
    ],
)
def test_proxy_unix_owner_values_rejected(extra: dict[str, str]) -> None:
    with pytest.raises(PE):
        plan.device_to_argv("kcage-demo", _dev("proxy", **_SOCK, **extra))


@pytest.mark.parametrize(
    "cfg",
    [
        {**GOOD_PROXY_INST, "uid": "1000"},
        {**GOOD_PROXY_INST, "mode": "0600"},
        {
            "bind": "host",
            "listen": "tcp:127.0.0.1:8080",
            "connect": "tcp:127.0.0.1:8080",
            "gid": "1000",
        },
    ],
)
def test_proxy_owner_keys_only_for_unix_listen(cfg: dict[str, str]) -> None:
    with pytest.raises(PE):
        plan.device_to_argv("kcage-demo", _dev("proxy", **cfg))


def test_owner_keys_not_allowed_on_other_types() -> None:
    with pytest.raises(PE):
        plan.device_to_argv("kcage-demo", _dev("disk", source="/a", path="/a", uid="1000"))


# ---- e2e で見つけた: /dev/dxg を重ねても mode 0660（root だけ）だと uid 1000 が GPU を開けない


def test_gpu_dxg_は_mode_0666_で重ね_他の_mode_は拒否する() -> None:
    good = model.DeviceSpec(
        "gpu-dxg", "unix-char", {"source": "/dev/dxg", "path": "/dev/dxg", "mode": "0666"}
    )
    assert "mode=0666" in plan.device_to_argv("kcage-demo", good)
    bad = model.DeviceSpec(
        "gpu-dxg", "unix-char", {"source": "/dev/dxg", "path": "/dev/dxg", "mode": "0777"}
    )
    with pytest.raises(PE):
        plan.device_to_argv("kcage-demo", bad)
    devs = plan.devices_for(_cfg(gpu=True))
    assert any(d.type == "unix-char" and d.config.get("mode") == "0666" for d in devs)


# ---- .git の pin（mv .git の迂回の封じ込め）


def test_pin_の_device_は親が先に並び_device_to_argv_が通る() -> None:
    cfg = _cfg()
    git = "/home/alice/work/demo/.git"
    devs = plan.devices_for(cfg)
    pin = next(i for i, d in enumerate(devs) if d.config.get("source") == git)
    assert devs[pin].config == {"source": git, "path": git, "readonly": "false"}
    plan.device_to_argv(cfg.name, devs[pin])
    # Incus が名前順に処理しても、親（repo・pin）が子の ro の重ねより先になる
    disks = [d for d in devs if d.type == "disk"]
    names = [d.name for d in disks]
    assert names == sorted(names)
    paths = [d.config["path"] for d in disks]
    for i, p in enumerate(paths):
        assert not any(q.startswith(p + "/") for q in paths[:i])


def test_pin_を許しても無関係な_rw_の_source_は拒否のまま() -> None:
    with pytest.raises(PE):
        plan.device_to_argv(
            "kcage-demo", _dev("disk", source="/home/alice/.ssh", path="/home/alice/.ssh")
        )
    with pytest.raises(PE):
        plan.device_to_argv(
            "kcage-demo", _dev("disk", source="/var/lib/incus/unix.socket", path="/x/.git")
        )


# ---- 資源の上限と idmap の分離（任意。既定は従来どおり）


def test_instance_config_既定では上限も分離も入れない() -> None:
    c = plan.instance_config(_cfg())
    assert not any(k.startswith("limits.") for k in c)
    assert "security.idmap.isolated" not in c


def test_instance_config_上限と分離が入る() -> None:
    c = plan.instance_config(_cfg(cpu=4, memory_mib=8192, processes=4096, idmap_isolated=True))
    assert c["limits.cpu"] == "4" and c["limits.memory"] == "8192MiB"
    assert c["limits.processes"] == "4096" and c["security.idmap.isolated"] == "true"


@pytest.mark.parametrize(
    "over", [{"cpu": 0}, {"cpu": True}, {"memory_mib": 64}, {"processes": 10}, {"cpu": "4"}]
)
def test_instance_config_範囲外や型違いは拒否する(over) -> None:
    with pytest.raises(PE):
        plan.instance_config(_cfg(**over))


def test_plan_up_は上限を_incus_init_の_c_へ_1_引数で渡す() -> None:
    p = _up(_cfg(cpu=2, memory_mib=1024, processes=512, idmap_isolated=True), _net())
    init = next(s for s in p.steps if isinstance(s, model.Op) and s.argv[:2] == ("incus", "init"))
    for kv in (
        "limits.cpu=2",
        "limits.memory=1024MiB",
        "limits.processes=512",
        "security.idmap.isolated=true",
    ):
        assert kv in init.argv
    assert "limits.cpu=2" in init.argv and init.argv[init.argv.index("limits.cpu=2") - 1] == "-c"
