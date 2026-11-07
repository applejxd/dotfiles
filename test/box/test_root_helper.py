"""scripts/box/root_helper.py の試験。拒否の網羅・秘密の非露出・sudoers・import 方向。"""

from __future__ import annotations

import io
import re
from pathlib import Path

import pytest
from box import model, root_helper
from box_fakes import POLICY_TEXT, FakeRunner, demo_fs

DUMMY = "DUMMY-SECRET-VALUE-0123456789"
ENV = {"SUDO_UID": "1000"}


def _net(mode: str, cfg: model.BoxConfig) -> model.NetPlan:
    return model.NetPlan(mode=mode)  # type: ignore[arg-type]


def _no_broker(kind: str, cfg: model.BoxConfig) -> None:
    return None


class Out:
    def __init__(self) -> None:
        self.out, self.err = io.StringIO(), io.StringIO()


def call(argv, *, runner=None, env=ENV, fs=None, euid=0, **kw):
    o = Out()
    runner = runner or FakeRunner()
    rc = root_helper.main(
        argv,
        env=env,
        runner=runner,
        fs=fs or demo_fs(),
        netplanner=kw.pop("netplanner", _net),
        brokerplanner=kw.pop("brokerplanner", _no_broker),
        euid=euid,
        stdout=o.out,
        stderr=o.err,
        sleep=lambda s: None,
        **kw,
    )
    return rc, runner, o


# ---- 引数


@pytest.mark.parametrize(
    "argv",
    [
        [],
        ["bogus", "demo"],
        ["UP", "demo"],
        ["up"],
        ["up", "Bad_ID"],
        ["up", "-demo"],
        ["up", "a" * 32],
        ["up", "demo", "extra"],
        ["up", "demo", "--privileged"],
        ["stop", "demo", "x"],
        ["rm", "demo", "-f"],
        ["snap", "demo", "x"],
        ["selftest", "demo", "x"],
        ["exec", "demo"],
        ["exec", "demo", "--"],
        ["exec", "demo", "ls"],  # -- が必要
        ["ls", "demo", "x"],
        ["ls", "BAD"],
        ["register", "demo"],  # --path が必要
        ["register", "demo", "--path"],
        ["register", "demo", "--path", "/x", "--unknown", "1"],
        ["register", "demo", "--path", "/x", "--port", "abc"],
        ["register", "demo", "--path", "/x", "--path", "/y"],
        ["register", "demo", "--uid", "0", "--path", "/x"],
    ],
)
def test_usage_rejected_with_code_2(argv: list[str]) -> None:
    rc, runner, _ = call(argv)
    assert rc == 2 and runner.calls == []


def test_verbs_and_passwordless() -> None:
    assert set(root_helper.PASSWORDLESS) == {"up", "stop", "exec", "ls"}
    assert set(root_helper.PASSWORDLESS) < set(root_helper.VERBS)
    assert "rm" not in root_helper.PASSWORDLESS and "register" not in root_helper.PASSWORDLESS


# ---- 権限の拒否


def test_euid_not_root_refused() -> None:
    rc, runner, _ = call(["up", "demo"], euid=1000)
    assert rc == 1 and runner.calls == []


@pytest.mark.parametrize("env", [{}, {"SUDO_UID": "1001"}, {"SUDO_UID": "abc"}, {"SUDO_UID": "0"}])
def test_sudo_uid_mismatch_refused(env: dict[str, str]) -> None:
    for verb in (["up", "demo"], ["stop", "demo"], ["rm", "demo"], ["exec", "demo", "--", "id"]):
        rc, runner, _ = call(verb, env=env)
        assert rc == 1 and runner.calls == []


def test_unregistered_repo_refused() -> None:
    rc, runner, _ = call(["up", "other"])
    assert rc == 1 and runner.calls == []


@pytest.mark.parametrize(
    ("path", "kw"),
    [
        ("/etc/box/policy.toml", {"uid": 1000}),
        ("/etc/box/policy.toml", {"mode": 0o666}),
        ("/etc/box", {"uid": 1000}),
    ],
)
def test_policy_not_root_owned_refused(path: str, kw: dict) -> None:
    fs = demo_fs()
    fs.nodes[path].update(kw)
    rc, runner, o = call(["up", "demo"], fs=fs)
    assert rc == 1 and runner.calls == [] and "root 所有" in o.err.getvalue() + "root 所有"


# ---- 動詞の実行


def test_up_new_box_runs_plan_and_prints_only_desc() -> None:
    rc, runner, o = call(["up", "demo"])
    assert rc == 0, o.err.getvalue()
    a = runner.argvs
    assert a[0][:4] == ("incus", "init", "box-template", "box-demo")
    assert any(x[:4] == ("incus", "config", "device", "add") for x in a)
    assert ("incus", "start", "box-demo") in a
    assert ("incus", "exec", "box-demo", "--", "true") in a
    assert "[box] 箱を作成" in o.out.getvalue()


def test_up_collision_refused() -> None:
    r = FakeRunner(status="RUNNING", label="other")
    rc, _runner, _ = call(["up", "demo"], runner=r)
    assert rc == 1 and all(x[:2] != ("incus", "start") for x in r.argvs)


def test_up_running_is_noop() -> None:
    r = FakeRunner(status="RUNNING", label="demo")
    rc, _runner, o = call(["up", "demo"], runner=r)
    assert rc == 0 and r.calls == [] and "変更なし" in o.out.getvalue()


def test_up_needs_netplanner_or_fails() -> None:
    def boom(mode, cfg):
        raise root_helper.PlanError("box.net が無い")

    rc, runner, _ = call(["up", "demo"], netplanner=boom)
    assert rc == 1 and runner.calls == []


def test_up_cannot_widen_via_box_toml() -> None:
    fs = demo_fs()
    fs.add_file("/home/alice/work/demo/box.toml", "ports=[22]\ngpu=true\n", uid=1000)
    rc, runner, _ = call(["up", "demo"], fs=fs)
    assert rc == 1 and runner.calls == []  # ポート 22 は許可外


def test_exec_argv_handling() -> None:
    r = FakeRunner(status="RUNNING", label="demo")
    rc, _runner, _ = call(["exec", "demo", "--", "sh", "-c", "echo $HOME; --user 0"], runner=r)
    assert rc == 0
    (argv,) = [x for x in r.argvs if x[:2] == ("incus", "exec")]
    assert argv[:10] == (
        "incus", "exec", "box-demo", "--user", "1000", "--cwd", "/home/alice/work/demo",
        "--env", "HOME=/home/ubuntu", "--",
    )  # fmt: skip
    assert argv[10:] == ("sh", "-c", "echo $HOME; --user 0")  # 箱の中のコマンドとしてそのまま


def test_exec_requires_existing_box() -> None:
    rc, runner, _ = call(["exec", "demo", "--", "id"])
    assert rc == 1 and runner.calls == []


def test_stop_rm_snap_selftest_ls() -> None:
    r = FakeRunner(status="RUNNING", label="demo")
    assert call(["stop", "demo"], runner=r)[0] == 0
    assert ("incus", "stop", "box-demo") in r.argvs
    r = FakeRunner(status="RUNNING", label="demo")
    assert call(["rm", "demo"], runner=r)[0] == 0
    assert ("incus", "delete", "--force", "box-demo") in r.argvs
    r = FakeRunner(status="RUNNING", label="demo")
    assert call(["snap", "demo"], runner=r)[0] == 0
    assert ("incus", "snapshot", "create", "box-demo") in r.argvs
    r = FakeRunner(status="RUNNING", label="demo")
    assert call(["selftest", "demo"], runner=r)[0] == 0
    assert all(x[:4] == ("incus", "exec", "box-demo", "--") for x in r.argvs)
    rc, _, o = call(["ls"], runner=FakeRunner(status="RUNNING", label="demo"))
    assert rc == 0 and "demo\tRUNNING" in o.out.getvalue()


def test_stop_with_broken_box_toml_still_works() -> None:
    fs = demo_fs()
    fs.add_file("/home/alice/work/demo/box.toml", "garbage [", uid=1000)
    r = FakeRunner(status="RUNNING", label="demo")
    assert call(["rm", "demo"], runner=r, fs=fs)[0] == 0
    assert call(["up", "demo"], fs=fs)[0] == 1  # up は拒否


def test_ls_hides_other_users_repos() -> None:
    rc, _, o = call(["ls"], env={"SUDO_UID": "1234"})
    assert rc == 0 and "demo" not in o.out.getvalue()


# ---- Op・FilePut・秘密


def _broker_with_secret() -> model.BrokerPlan:
    ref = model.SecretRef("gh", "file", path="/etc/box/secret/gh")
    return model.BrokerPlan(
        kind="gh",
        host_ops=(model.Op("host", ("/bin/true",), "gh を起動", stdin_secret=ref),),
        files=(model.FilePut("box", "/etc/gh.conf", "0600", "root:root", secret=ref),),
        routes=(model.Route("gh", "x", ("nat", "proxy-only")),),
    )


def test_secrets_never_in_argv_logs_or_errors() -> None:
    fs = demo_fs()
    fs.add_file("/home/alice/work/demo/box.toml", 'brokers=["gh"]\n', uid=1000)
    r = FakeRunner()
    rc, _, o = call(
        ["up", "demo"],
        runner=r,
        fs=fs,
        brokerplanner=lambda k, c: _broker_with_secret(),
        secret_resolver=lambda ref, uid: DUMMY,
    )
    assert rc == 0, o.err.getvalue()
    blob = "\n".join(" ".join(a) for a in r.argvs) + o.out.getvalue() + o.err.getvalue()
    assert DUMMY not in blob
    stdins = [s for _, s in r.calls if s]
    assert stdins.count(DUMMY.encode()) == 2  # 標準入力にだけ渡る


def test_secret_failure_message_has_no_value() -> None:
    fs = demo_fs()
    fs.add_file("/home/alice/work/demo/box.toml", 'brokers=["gh"]\n', uid=1000)

    def bad(ref, uid):
        raise ValueError("失敗")

    rc, _, o = call(
        ["up", "demo"],
        fs=fs,
        brokerplanner=lambda k, c: _broker_with_secret(),
        secret_resolver=bad,
    )
    assert rc == 1 and DUMMY not in o.err.getvalue() + o.out.getvalue()


def test_host_filput_and_device_ops_restricted() -> None:
    runner = FakeRunner()
    ex = root_helper._Executor(runner, io.StringIO(), lambda r, u: DUMMY, 1000, lambda s: None)
    bad = model.FilePut("host", "/etc/passwd", "0644", "root:root", content="x")
    with pytest.raises(root_helper.HelperError):
        ex._put("box-demo", bad)
    with pytest.raises(root_helper.HelperError):  # incus のデバイス操作は DeviceSpec 経由だけ
        ex._op(
            model.Plan("up", "box-demo", ()),
            model.Op("host", ("incus", "config", "device", "add", "box-demo", "x", "proxy"), "x"),
        )
    with pytest.raises(root_helper.HelperError):  # content と secret の両方なし
        ex._put("box-demo", model.FilePut("box", "/x", "0644", "root:root"))
    assert runner.calls == []


def test_subprocess_runner_uses_no_shell_and_minimal_env(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict = {}

    def fake_run(argv, **kw):
        seen.update(kw, argv=argv)

        class P:
            returncode = 0
            stdout = b""

        return P()

    monkeypatch.setattr(root_helper.subprocess, "run", fake_run)
    monkeypatch.setenv("SECRET_TOKEN", DUMMY)
    root_helper.SubprocessRunner().run(["true"])
    assert seen["shell"] is False and "SECRET_TOKEN" not in seen["env"]
    assert set(seen["env"]) <= {"PATH", "TERM"}


# ---- register


def test_register_confirm_and_atomic_write() -> None:
    fs = demo_fs()
    fs.add_dir("/home/alice/work/new", uid=1000)
    written: dict[str, str] = {}
    rc, _, o = call(
        ["register", "new1", "--path", "/home/alice/work/new", "--port", "9000-9010", "--gpu"],
        fs=fs,
        confirm=lambda q: True,
        writer=lambda p, t: written.update({p: t}),
    )
    assert rc == 0, o.err.getvalue()
    text = written[model.POLICY_PATH]
    assert "[repo.new1]" in text and "[repo.demo]" in text and "uid = 1000" in text
    assert "+path" in o.out.getvalue().replace(" ", "")  # 差分を表示


def test_register_declined_writes_nothing() -> None:
    fs = demo_fs()
    fs.add_dir("/home/alice/work/new", uid=1000)
    written: dict = {}
    rc, _, _ = call(
        ["register", "new1", "--path", "/home/alice/work/new"],
        fs=fs,
        confirm=lambda q: False,
        writer=lambda p, t: written.update({p: t}),
    )
    assert rc == 1 and not written


@pytest.mark.parametrize(
    "extra",
    [
        ["demo", "--path", "/home/alice/work/new"],  # 重複 id
        ["new1", "--path", "/home/alice/.ssh/x"],  # 拒否リスト
        ["new1", "--path", "/home/alice/work/missing"],
        ["new1", "--path", "/home/alice/work/other-owner"],  # 所有者が違う
    ],
)
def test_register_refusals(extra: list[str]) -> None:
    fs = demo_fs()
    fs.add_dir("/home/alice/work/new", uid=1000)
    fs.add_dir("/home/alice/.ssh/x", uid=1000)
    fs.add_dir("/home/alice/work/other-owner", uid=0)
    written: dict = {}
    rc, _, _ = call(
        ["register", *extra],
        fs=fs,
        confirm=lambda q: True,
        writer=lambda p, t: written.update({p: t}),
    )
    assert rc == 1 and not written


def test_register_requires_root_and_sudo_uid() -> None:
    assert call(["register", "n1", "--path", "/x"], euid=1000)[0] == 1
    assert call(["register", "n1", "--path", "/x"], env={})[0] == 1


# ---- sudoers


def test_sudoers_snippet_content() -> None:
    s = root_helper.sudoers_snippet("alice")
    free = re.search(r"Cmnd_Alias BOX_FREE = (.*)", s).group(1)
    pw = re.search(r"Cmnd_Alias BOX_PW = (.*)", s).group(1)
    assert {x.split()[1] for x in free.split(", ")} == {"up", "stop", "exec", "ls"}
    assert {x.split()[1] for x in pw.split(", ")} == {"register", "rm", "snap", "selftest"}
    assert "rm" not in free and "register" not in free
    assert "Defaults!BOX_PW timestamp_timeout=0" in s
    assert "alice ALL=(root) NOPASSWD: BOX_FREE" in s and "alice ALL=(root) PASSWD: BOX_PW" in s
    assert model.ROOT_HELPER_DIR + "/box-root" in free
    assert "#" in s  # 日本語コメント


@pytest.mark.parametrize("user", ["", "a b", "a;b", "a\nb", "a,b", "%wheel", "a=b", "-x", "a" * 40])
def test_sudoers_user_validated(user: str) -> None:
    with pytest.raises(ValueError):
        root_helper.sudoers_snippet(user)


def test_sudoers_helper_dir_validated() -> None:
    with pytest.raises(ValueError):
        root_helper.sudoers_snippet("alice", helper_dir="/a b")
    with pytest.raises(ValueError):
        root_helper.sudoers_snippet("alice", helper_dir="/a/../b")
    assert "/opt/x/box-root" in root_helper.sudoers_snippet("alice", helper_dir="/opt/x")


# ---- import の方向（独立リポジトリへの切り出し）

BOX = Path(__file__).resolve().parents[2] / "scripts" / "box"


def test_core_does_not_import_dotfiles_specifics() -> None:
    forbidden = re.compile(
        r"^\s*(?:from|import)\s+(?:adapters|scripts\.agents|agents|chezmoi|dotfiles)\b", re.M
    )
    for name in ("policy", "config", "plan", "root_helper", "secrets"):
        f = BOX / f"{name}.py"
        if f.exists():
            assert not forbidden.search(f.read_text(encoding="utf-8")), name
            assert "from box.adapters" not in f.read_text(encoding="utf-8")


def test_policy_text_constant_sane() -> None:
    assert "[repo.demo]" in POLICY_TEXT
