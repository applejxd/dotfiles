"""commondir の封じ込め（gitmeta・root_helper の up・config の重ね・plan の device）の試験。実機は要らない。"""

from __future__ import annotations

import pytest
from kcage import config, gitmeta, model, plan
from kcage.config import ConfigError
from kcage_fakes import FakeCommondirOps, FakeRunner, demo_fs, demo_policy
from test_root_helper import call

GIT = "/home/alice/work/demo/.git"


# ---- 純粋な判定


@pytest.mark.parametrize("content", [b".", b".\n", b" . \n\n", GIT.encode(), GIT.encode() + b"\n"])
def test_無害な中身は何もしない(content: bytes) -> None:
    assert gitmeta.decide(content, GIT) == "ok"


def test_無ければ作る() -> None:
    assert gitmeta.decide(None, GIT) == "create"


@pytest.mark.parametrize("content", [b"/tmp/evil", b"../x", b"", b"\xff\xfe", b".git"])
def test_それ以外は拒否する(content: bytes) -> None:
    with pytest.raises(ConfigError, match="commondir"):
        gitmeta.decide(content, GIT)


# ---- 実行層（偽物）


def test_権限を落として作り_戻す() -> None:
    ops = FakeCommondirOps(None)
    assert gitmeta.ensure_commondir(GIT, 1000, 1001, ops) == "created"
    assert ops.events == ["drop:1000:1001", "is_real_dir", "read", "create", "restore"]
    assert ops.created == [(GIT + "/commondir", b".\n")]


def test_有って無害なら作らない() -> None:
    ops = FakeCommondirOps(b".\n")
    assert gitmeta.ensure_commondir(GIT, 1000, 1000, ops) == "ok"
    assert ops.created == [] and ops.events[-1] == "restore"


def test_実ディレクトリでなければ何もしない() -> None:
    ops = FakeCommondirOps(None, real_dir=False)
    assert gitmeta.ensure_commondir(GIT, 1000, 1000, ops) == "skipped"
    assert ops.events == ["drop:1000:1000", "is_real_dir", "restore"]


@pytest.mark.parametrize(
    "ops",
    [
        FakeCommondirOps(b"/tmp/evil"),
        FakeCommondirOps(None, read_error=OSError(40, "Too many levels of symbolic links")),
        FakeCommondirOps(None, create_error=OSError(13, "Permission denied")),
    ],
)
def test_例外でも権限を戻す(ops: FakeCommondirOps) -> None:
    with pytest.raises(ConfigError):
        gitmeta.ensure_commondir(GIT, 1000, 1000, ops)
    assert ops.events[0].startswith("drop") and ops.events[-1] == "restore"
    assert ops.created == []


# ---- 重ねと device


def test_commondir_は_ro_の重ねに入り_device_が通る() -> None:
    cfg = config.resolve(demo_policy(), "demo", model.RepoSpec(), demo_fs())
    srcs = {m.source: m for m in cfg.mounts if m.readonly}
    m = srcs[GIT + "/commondir"]
    assert m.path == m.source
    devs = [d for d in plan.devices_for(cfg) if d.config.get("source") == GIT + "/commondir"]
    assert len(devs) == 1 and devs[0].config["readonly"] == "true"
    plan.device_to_argv(cfg.name, devs[0])


def test_commondir_が_symlink_なら_resolve_は拒否() -> None:
    fs = demo_fs()
    del fs.nodes[GIT + "/commondir"]
    fs.add_link(GIT + "/commondir", "/tmp/x")
    with pytest.raises(ConfigError, match="commondir"):
        config.resolve(demo_policy(), "demo", model.RepoSpec(), fs)


# ---- up の経路


def test_up_は箱を作る前に_commondir_を用意する() -> None:
    ops = FakeCommondirOps(None)
    rc, runner, o = call(
        ["up", "demo"], commondir_ops=ops, env={"SUDO_UID": "1000", "SUDO_GID": "1001"}
    )
    assert rc == 0, o.err.getvalue()
    assert ops.events[0] == "drop:1000:1001" and ops.created
    assert any(a[:2] == ("incus", "init") for a in runner.argvs)


def test_up_は別の場所を指す_commondir_を拒否し箱を作らない() -> None:
    ops = FakeCommondirOps(b"/tmp/evil\n")
    runner = FakeRunner()
    rc, runner, o = call(["up", "demo"], commondir_ops=ops, runner=runner)
    assert rc == 1
    assert "commondir" in o.err.getvalue()
    assert runner.argvs == [] or not any(a[:2] == ("incus", "init") for a in runner.argvs)


def test_stop_は_commondir_を触らない() -> None:
    ops = FakeCommondirOps(b"/tmp/evil\n")
    call(["stop", "demo"], commondir_ops=ops)
    assert ops.events == []
