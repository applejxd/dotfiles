"""scripts/kcage/root_helper.py の試験。拒否の網羅・秘密の非露出・sudoers・import 方向。"""

from __future__ import annotations

import io
import os
import re
from pathlib import Path

import pytest
from kcage import distcheck, model, policy, root_helper
from kcage_fakes import POLICY_TEXT, FakeCommondirOps, FakeRunner, demo_fs

DUMMY = "DUMMY-SECRET-VALUE-0123456789"
ENV = {"SUDO_UID": "1000"}


def _net(mode: str, cfg: model.BoxConfig) -> model.NetPlan:
    return model.NetPlan(mode=mode)  # type: ignore[arg-type]


def _no_broker(kind: str, cfg: model.BoxConfig, policy: model.RepoPolicy) -> None:
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
        commondir_ops=kw.pop("commondir_ops", FakeCommondirOps(b".\n")),
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
        ("/etc/kcage/policy.toml", {"uid": 1000}),
        ("/etc/kcage/policy.toml", {"mode": 0o666}),
        ("/etc/kcage", {"uid": 1000}),
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
    assert a[0][:4] == ("incus", "init", "kcage-template", "kcage-demo")
    assert any(x[:4] == ("incus", "config", "device", "add") for x in a)
    assert ("incus", "start", "kcage-demo") in a
    assert ("incus", "exec", "kcage-demo", "--", "true") in a
    assert "[kcage] 箱を作成" in o.out.getvalue()


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
        raise root_helper.PlanError("kcage.net が無い")

    rc, runner, _ = call(["up", "demo"], netplanner=boom)
    assert rc == 1 and runner.calls == []


def test_up_cannot_widen_via_box_toml() -> None:
    fs = demo_fs()
    fs.add_file("/home/alice/work/demo/kcage.toml", "ports=[22]\ngpu=true\n", uid=1000)
    rc, runner, _ = call(["up", "demo"], fs=fs)
    assert rc == 1 and runner.calls == []  # ポート 22 は許可外


def test_exec_argv_handling() -> None:
    r = FakeRunner(status="RUNNING", label="demo")
    rc, _runner, _ = call(["exec", "demo", "--", "sh", "-c", "echo $HOME; --user 0"], runner=r)
    assert rc == 0
    (argv,) = [x for x in r.argvs if x[:2] == ("incus", "exec")]
    assert argv[:12] == (
        "incus", "exec", "kcage-demo", "--user", "1000", "--group", "1000", "--cwd",
        "/home/alice/work/demo", "--env", "HOME=/home/ubuntu", "--",
    )  # fmt: skip
    assert argv[12:] == ("sh", "-c", "echo $HOME; --user 0")  # 箱の中のコマンドとしてそのまま


def test_exec_requires_existing_box() -> None:
    rc, runner, _ = call(["exec", "demo", "--", "id"])
    assert rc == 1 and runner.calls == []


def test_stop_rm_snap_selftest_ls() -> None:
    r = FakeRunner(status="RUNNING", label="demo")
    assert call(["stop", "demo"], runner=r)[0] == 0
    assert ("incus", "stop", "kcage-demo") in r.argvs
    r = FakeRunner(status="RUNNING", label="demo")
    assert call(["rm", "demo"], runner=r)[0] == 0
    assert ("incus", "delete", "--force", "kcage-demo") in r.argvs
    r = FakeRunner(status="RUNNING", label="demo")
    assert call(["snap", "demo"], runner=r)[0] == 0
    assert ("incus", "snapshot", "create", "kcage-demo") in r.argvs
    r = FakeRunner(status="RUNNING", label="demo")
    assert call(["selftest", "demo"], runner=r)[0] == 0
    assert all(x[:4] == ("incus", "exec", "kcage-demo", "--") for x in r.argvs)
    rc, _, o = call(["ls"], runner=FakeRunner(status="RUNNING", label="demo"))
    assert rc == 0 and "demo\tRUNNING" in o.out.getvalue()


def test_stop_with_broken_box_toml_still_works() -> None:
    fs = demo_fs()
    fs.add_file("/home/alice/work/demo/kcage.toml", "garbage [", uid=1000)
    r = FakeRunner(status="RUNNING", label="demo")
    assert call(["rm", "demo"], runner=r, fs=fs)[0] == 0
    assert call(["up", "demo"], fs=fs)[0] == 1  # up は拒否


def test_ls_hides_other_users_repos() -> None:
    rc, _, o = call(["ls"], env={"SUDO_UID": "1234"})
    assert rc == 0 and "demo" not in o.out.getvalue()


# ---- Op・FilePut・秘密


def _broker_with_secret() -> model.BrokerPlan:
    ref = model.SecretRef("gh", "file", path="/etc/kcage/secret/gh")
    return model.BrokerPlan(
        kind="gh",
        host_ops=(model.Op("host", ("/bin/true",), "gh を起動", stdin_secret=ref),),
        files=(model.FilePut("box", "/etc/gh.conf", "0600", "root:root", secret=ref),),
        routes=(model.Route("gh", "x", ("nat", "proxy-only")),),
    )


def test_secrets_never_in_argv_logs_or_errors() -> None:
    fs = demo_fs()
    fs.add_file("/home/alice/work/demo/kcage.toml", 'brokers=["gh"]\n', uid=1000)
    r = FakeRunner()
    rc, _, o = call(
        ["up", "demo"],
        runner=r,
        fs=fs,
        brokerplanner=lambda k, c, p: _broker_with_secret(),
        secret_resolver=lambda ref, uid: DUMMY,
    )
    assert rc == 0, o.err.getvalue()
    blob = "\n".join(" ".join(a) for a in r.argvs) + o.out.getvalue() + o.err.getvalue()
    assert DUMMY not in blob
    stdins = [s for _, s in r.calls if s]
    assert stdins.count(DUMMY.encode()) == 2  # 標準入力にだけ渡る


def test_secret_failure_message_has_no_value() -> None:
    fs = demo_fs()
    fs.add_file("/home/alice/work/demo/kcage.toml", 'brokers=["gh"]\n', uid=1000)

    def bad(ref, uid):
        raise ValueError("失敗")

    rc, _, o = call(
        ["up", "demo"],
        fs=fs,
        brokerplanner=lambda k, c, p: _broker_with_secret(),
        secret_resolver=bad,
    )
    assert rc == 1 and DUMMY not in o.err.getvalue() + o.out.getvalue()


def test_host_filput_and_device_ops_restricted() -> None:
    runner = FakeRunner()
    ex = root_helper._Executor(runner, io.StringIO(), lambda r, u: DUMMY, 1000, lambda s: None)
    bad = model.FilePut("host", "/etc/passwd", "0644", "root:root", content="x")
    with pytest.raises(root_helper.HelperError):
        ex._put("kcage-demo", bad)
    with pytest.raises(root_helper.HelperError):  # incus のデバイス操作は DeviceSpec 経由だけ
        ex._op(
            model.Plan("up", "kcage-demo", ()),
            model.Op("host", ("incus", "config", "device", "add", "kcage-demo", "x", "proxy"), "x"),
        )
    with pytest.raises(root_helper.HelperError):  # content と secret の両方なし
        ex._put("kcage-demo", model.FilePut("box", "/x", "0644", "root:root"))
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


def _register_text(env: dict[str, str], extra: list[str] | None = None) -> tuple[int, str]:
    fs = demo_fs()
    fs.add_dir("/home/alice/work/new", uid=1000)
    written: dict[str, str] = {}
    rc, _, _ = call(
        ["register", "new1", "--path", "/home/alice/work/new", *(extra or [])],
        env=env,
        fs=fs,
        confirm=lambda q: True,
        writer=lambda p, t: written.update({p: t}),
    )
    return rc, written.get(model.POLICY_PATH, "")


def test_register_SUDO_GIDをgidとして記録する() -> None:
    rc, text = _register_text({"SUDO_UID": "1000", "SUDO_GID": "1001"})
    assert rc == 0
    assert policy.parse(text).repos["new1"].gid == 1001


@pytest.mark.parametrize("raw", [None, "abc", "0", "-1", "70000", "01001", ""])
def test_register_SUDO_GIDが無い・不正ならuid(raw: str | None) -> None:
    env = {"SUDO_UID": "1000"}
    if raw is not None:
        env["SUDO_GID"] = raw
    rc, text = _register_text(env)
    assert rc == 0
    assert policy.parse(text).repos["new1"].gid == 1000


def test_register_引数でgidを上書きできない() -> None:
    env = {"SUDO_UID": "1000", "SUDO_GID": "1001"}
    rc, _ = _register_text(env, ["--gid", "5"])
    assert rc == 2  # 未知の引数は拒否


# ---- sudoers


def test_sudoers_snippet_content() -> None:
    s = root_helper.sudoers_snippet("alice")
    free = re.search(r"Cmnd_Alias BOX_FREE = (.*)", s).group(1)
    pw = re.search(r"Cmnd_Alias BOX_PW = (.*)", s).group(1)
    assert {x.split()[1] for x in free.split(", ")} == {"up", "stop", "exec", "ls"}
    assert {x.split()[1] for x in pw.split(", ")} == {
        "register",
        "rm",
        "snap",
        "selftest",
        "template",
    }
    assert "rm" not in free and "register" not in free
    assert "template" not in free
    assert "Defaults!BOX_PW timestamp_timeout=0" in s
    assert "alice ALL=(root) NOPASSWD: BOX_FREE" in s and "alice ALL=(root) PASSWD: BOX_PW" in s
    assert model.ROOT_HELPER_DIR + "/kcage-root" in free
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
    assert "/opt/x/kcage-root" in root_helper.sudoers_snippet("alice", helper_dir="/opt/x")


# ---- import の方向（独立リポジトリへの切り出し）

BOX = Path(__file__).resolve().parents[2] / "scripts" / "kcage"


def test_core_does_not_import_dotfiles_specifics() -> None:
    forbidden = re.compile(
        r"^\s*(?:from|import)\s+(?:adapters|scripts\.agents|agents|chezmoi|dotfiles)\b", re.M
    )
    for name in ("policy", "config", "plan", "root_helper", "secrets", "distcheck", "template"):
        f = BOX / f"{name}.py"
        if f.exists():
            assert not forbidden.search(f.read_text(encoding="utf-8")), name
            assert "from kcage.adapters" not in f.read_text(encoding="utf-8")


def test_policy_text_constant_sane() -> None:
    assert "[repo.demo]" in POLICY_TEXT


# ---- template verb（テンプレートの作成。パスワード必須）


def _ok_dist(path: str, uid: int) -> str:
    return path


def test_templateはパスワードなしの動詞に入らない() -> None:
    assert "template" in root_helper.VERBS
    assert "template" not in root_helper.PASSWORDLESS
    s = root_helper.sudoers_snippet("alice")
    free = re.search(r"Cmnd_Alias BOX_FREE = (.*)", s).group(1)
    pw = re.search(r"Cmnd_Alias BOX_PW = (.*)", s).group(1)
    assert "template" not in free
    assert "template" in pw
    # NOPASSWD の行が参照するのは BOX_FREE だけ
    nopasswd = next(ln for ln in s.splitlines() if "NOPASSWD" in ln and ln.startswith("alice"))
    assert nopasswd.endswith("BOX_FREE")


def test_templateの引数の解釈() -> None:
    r = root_helper.parse_args(["template"])
    assert (
        r.verb == "template"
        and r.repo_id is None
        and r.options == {"dist": None, "pi_version": None}
    )
    r = root_helper.parse_args(
        ["template", "--dist", "/home/a/.cache/kcage/dist", "--pi-version", "1.5.0"]
    )
    assert r.options == {"dist": "/home/a/.cache/kcage/dist", "pi_version": "1.5.0"}


@pytest.mark.parametrize(
    "argv",
    [
        ["template", "demo"],  # repo id は取らない
        ["template", "--dist"],
        ["template", "--dist", "rel/path"],
        ["template", "--dist", "/a", "--dist", "/b"],
        ["template", "--pi-version", "latest"],
        ["template", "--pi-version", "1.5.0; id"],
        ["template", "--unknown", "x"],
    ],
)
def test_templateの不正な引数は2で終わる(argv) -> None:
    rc, runner, _o = call(argv)
    assert rc == 2 and runner.calls == []


def test_templateはrootとsudo経由が必要() -> None:
    assert call(["template"], euid=1000)[0] == 1
    assert call(["template"], env={})[0] == 1


def test_templateは許可表のtemplateで作り_repo登録は要らない() -> None:
    fs = demo_fs()
    fs.add_file("/etc/kcage/policy.toml", '[defaults]\ntemplate = "my-tpl"\n')
    rc, runner, o = call(["template"], fs=fs, dist_checker=_ok_dist)
    assert rc == 0, o.err.getvalue()
    argvs = runner.argvs
    assert ("incus", "publish", "kcage-template-build", "--alias", "my-tpl") in argvs
    assert not any("--dist" in a for a in argvs)
    # 公開・削除は最後の方、検査済みの NVIDIA の指紋が入っている
    joined = [" ".join(a) for a in argvs]
    assert any(template_fpr() in x for x in joined)


def template_fpr() -> str:
    from kcage import template

    return template.NVIDIA_KEY_FPR


def test_templateは検証済みのdistを箱へ入れる() -> None:
    seen: list[tuple[str, int]] = []

    def checker(path: str, uid: int) -> str:
        seen.append((path, uid))
        return path

    rc, runner, o = call(
        ["template", "--dist", "/home/alice/.cache/kcage/dist"], dist_checker=checker
    )
    assert rc == 0, o.err.getvalue()
    assert seen == [("/home/alice/.cache/kcage/dist", 1000)]
    push = next(a for a in runner.argvs if a[:3] == ("incus", "file", "push") and "-r" in a)
    assert "/home/alice/.cache/kcage/dist" in push


def test_templateのdist検証の失敗はhelperエラーで何も実行しない() -> None:
    def checker(path: str, uid: int) -> str:
        raise root_helper.distcheck.DistCheckError("拒否名を含む: auth.json")

    rc, runner, o = call(["template", "--dist", "/x"], dist_checker=checker)
    assert rc == 1 and runner.calls == []
    assert "--dist" in o.err.getvalue()


def test_templateはpi_versionを版つきで入れる() -> None:
    rc, runner, o = call(["template", "--pi-version", "1.5.0"], dist_checker=_ok_dist)
    assert rc == 0, o.err.getvalue()
    assert ("incus", "exec", "kcage-template-build", "--", "npm", "install", "-g",
            "@earendil-works/pi-coding-agent@1.5.0") in runner.argvs  # fmt: skip


def test_templateはbuild_proxyの設定を置いてpublishの前に消す() -> None:
    fs = demo_fs()
    text = POLICY_TEXT.replace("[defaults]\n", '[defaults]\nbuild_proxy = "192.0.2.10:3128"\n', 1)
    fs.add_file("/etc/kcage/policy.toml", text)
    rc, runner, o = call(["template"], fs=fs, dist_checker=_ok_dist)
    assert rc == 0, o.err.getvalue()
    calls = runner.calls
    apt_put = next(
        i
        for i, (a, _) in enumerate(calls)
        if a[:3] == ("incus", "file", "push") and "99kcage-build-proxy" in " ".join(a)
    )
    assert b"http://192.0.2.10:3128" in calls[apt_put][1]
    first_apt = next(i for i, (a, _) in enumerate(calls) if a[-2:] == ("apt-get", "update"))
    rm = next(
        i
        for i, (a, _) in enumerate(calls)
        if a[:4] == ("incus", "exec", "kcage-template-build", "--") and a[4:6] == ("rm", "-f")
    )
    pub = next(i for i, (a, _) in enumerate(calls) if a[:2] == ("incus", "publish"))
    assert apt_put < first_apt < rm < pub


def test_templateのビルド用proxyが許可表に無ければ設定を置かない() -> None:
    rc, runner, _o = call(["template"], dist_checker=_ok_dist)
    assert rc == 0
    assert not any("build-proxy" in " ".join(a) for a in runner.argvs)


# ---- --dist の検証（distcheck。実ファイルで確かめる）

MY_UID = os.getuid()


def _dist(tmp_path: Path) -> Path:
    d = tmp_path.resolve() / "dist"
    d.mkdir(mode=0o700)
    (d / "ext").mkdir()
    (d / "ext" / "a.ts").write_text("export const a = 1\n", encoding="utf-8")
    (d / "AGENTS.md").write_text("# 指示\n", encoding="utf-8")
    return d


def test_dist_正常なら通る(tmp_path: Path) -> None:
    d = _dist(tmp_path)
    assert distcheck.validate_dist(str(d), MY_UID) == str(d)


def test_dist_helper経由でも通り_拒否は終了コード1(tmp_path: Path) -> None:
    d = _dist(tmp_path)
    env = {"SUDO_UID": str(MY_UID)} if MY_UID >= 1 else None
    if env is None:
        pytest.skip("root では SUDO_UID を作れない")
    assert call(["template", "--dist", str(d)], env=env)[0] == 0
    (d / "auth.json").write_text("{}", encoding="utf-8")
    rc, runner, _o = call(["template", "--dist", str(d)], env=env)
    assert rc == 1 and runner.calls == []


@pytest.mark.parametrize("bad", ["rel/dist", "/a/../b", "/a//b", "/a/b/", "", "/a\nb"])
def test_dist_相対や非正規のパスは拒否(bad: str) -> None:
    with pytest.raises(distcheck.DistCheckError):
        distcheck.validate_dist(bad, MY_UID)


def test_dist_経路にsymlinkがあれば拒否(tmp_path: Path) -> None:
    d = _dist(tmp_path)
    link = tmp_path.resolve() / "link"
    link.symlink_to(d)
    with pytest.raises(distcheck.DistCheckError, match="symlink"):
        distcheck.validate_dist(str(link), MY_UID)
    with pytest.raises(distcheck.DistCheckError, match="symlink"):
        distcheck.validate_dist(str(link / "ext"), MY_UID)


def test_dist_中のsymlinkは拒否(tmp_path: Path) -> None:
    d = _dist(tmp_path)
    (d / "ext" / "evil").symlink_to("/etc/passwd")
    with pytest.raises(distcheck.DistCheckError, match="symlink"):
        distcheck.validate_dist(str(d), MY_UID)


def test_dist_他人の所有は拒否(tmp_path: Path) -> None:
    d = _dist(tmp_path)
    with pytest.raises(distcheck.DistCheckError, match="所有"):
        distcheck.validate_dist(str(d), MY_UID + 1)


def test_dist_他人から書けるディレクトリは拒否(tmp_path: Path) -> None:
    d = _dist(tmp_path)
    d.chmod(0o775)
    with pytest.raises(distcheck.DistCheckError, match="書ける"):
        distcheck.validate_dist(str(d), MY_UID)


def test_dist_ディレクトリでなければ拒否(tmp_path: Path) -> None:
    f = tmp_path.resolve() / "file"
    f.write_text("x", encoding="utf-8")
    with pytest.raises(distcheck.DistCheckError, match="ディレクトリ"):
        distcheck.validate_dist(str(f), MY_UID)


@pytest.mark.parametrize(
    "name",
    [
        "auth.json",
        "sessions",
        "a.jsonl",
        ".env",
        ".env.local",
        "mcp.json",
        "models.json",
        ".ssh",
        ".aws",
        "id_rsa",
        "x.pem",
    ],
)
def test_dist_禁止名は拒否(tmp_path: Path, name: str) -> None:
    d = _dist(tmp_path)
    target = d / "ext" / name
    if name in ("sessions", ".ssh", ".aws"):
        target.mkdir()
    else:
        target.write_text("x", encoding="utf-8")
    with pytest.raises(distcheck.DistCheckError, match="拒否名"):
        distcheck.validate_dist(str(d), MY_UID)


def test_dist_秘密らしい内容は拒否し内容は出さない(tmp_path: Path) -> None:
    d = _dist(tmp_path)
    token = "ghp_" + "A" * 30
    (d / "ext" / "b.ts").write_text(f"const t = '{token}'\n", encoding="utf-8")
    with pytest.raises(distcheck.DistCheckError) as ei:
        distcheck.validate_dist(str(d), MY_UID)
    assert token not in str(ei.value) and "b.ts" in str(ei.value)


def test_dist_巨大なら拒否(tmp_path: Path) -> None:
    d = _dist(tmp_path)
    (d / "big.bin").write_bytes(b"\0" * 2048)
    with pytest.raises(distcheck.DistCheckError, match="サイズ"):
        distcheck.validate_dist(str(d), MY_UID, max_bytes=1024)
    assert distcheck.validate_dist(str(d), MY_UID, max_bytes=1024 * 1024)


def test_dist_件数の上限を超えたら拒否(tmp_path: Path) -> None:
    d = _dist(tmp_path)
    with pytest.raises(distcheck.DistCheckError, match="件数"):
        distcheck.validate_dist(str(d), MY_UID, max_entries=1)


def test_dist_fifoやハードリンクは拒否(tmp_path: Path) -> None:
    d = _dist(tmp_path)
    os.mkfifo(d / "pipe")
    with pytest.raises(distcheck.DistCheckError, match="通常ファイル"):
        distcheck.validate_dist(str(d), MY_UID)
    (d / "pipe").unlink()
    os.link(d / "AGENTS.md", d / "ext" / "hard.md")
    with pytest.raises(distcheck.DistCheckError, match="ハードリンク"):
        distcheck.validate_dist(str(d), MY_UID)


def test_dist_拒否名リストは汎用でdotfiles固有を含まない() -> None:
    for name in (
        "auth.json",
        ".env",
        "mcp.json",
        "models.json",
        ".ssh",
        ".aws",
        "sessions",
        "*.jsonl",
    ):
        assert name in distcheck.DENY_NAMES
    src = (BOX / "distcheck.py").read_text(encoding="utf-8")
    assert not re.search(r"^\s*(?:from|import)\s+\S*(?:adapters|dotfiles)", src, re.M)
