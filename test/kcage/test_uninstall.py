"""uninstall.py と、cli の init / uninstall の試験。実際の incus・systemctl・root は使わない（計画と偽物だけ）。"""

from __future__ import annotations

import os

import pytest
from kcage import cli, model, net, setup, uninstall
from kcage import plan as box_plan

FULL = uninstall.State(
    boxes=("kcage-demo",),
    broker_units=("kcage-broker-demo-gh.service",),
    template_image=True,
    nonet_profile=True,
    forward_unit=True,
    forward_del=True,
    sudoers=True,
    helper_dir=True,
    run_dir=True,
    conf_dir=True,
    subuid_has=True,
    subgid_has=True,
)


def opts(**kw) -> uninstall.Opts:
    base = {"user": "alice", "uid": 1000, "gid": 1001, "state": FULL}
    base.update(kw)
    return uninstall.Opts(**base)


def argvs(p: model.Plan) -> list[tuple[str, ...]]:
    return [s.argv for s in p.steps if isinstance(s, model.Op)]


def removes(p: model.Plan) -> list[str]:
    return [s.path for s in p.steps if isinstance(s, uninstall.Remove)]


def index_of(p: model.Plan, pred) -> int:
    return next(i for i, s in enumerate(p.steps) if pred(s))


# ---- 計画 ----


def test_順序は箱_画像_forward_sudoers_配備_subid():
    p = uninstall.plan(opts(drop_subid=True))
    kinds = []
    for s in p.steps:
        if isinstance(s, uninstall.Remove):
            kinds.append(s.path)
        elif isinstance(s, uninstall.SubidDrop):
            kinds.append("subid")
        elif isinstance(s, uninstall.LabelGuard):
            kinds.append("label")
        else:
            kinds.append(s.argv[0] + " " + " ".join(s.argv[1:3]))
    pos = {k: i for i, k in enumerate(kinds)}
    assert pos["systemctl stop kcage-broker-demo-gh.service"] < pos["incus delete --force"]
    assert pos["incus delete --force"] < pos["incus image delete"]
    assert pos["incus image delete"] < pos["incus profile delete"]
    assert pos["incus profile delete"] < pos["systemctl disable --now"]
    assert pos[net.FORWARD_UNIT_PATH] < pos["/etc/sudoers.d/kcage-alice"]
    assert pos["/etc/sudoers.d/kcage-alice"] < pos[model.BROKER_HOST_DIR] < pos[setup.CONF_DIR]
    assert pos[setup.CONF_DIR] < pos["subid"]
    # root 所有の配備コピーは最後（途中で失敗しても再実行の入口が残る）
    assert pos["subid"] < pos[model.ROOT_HELPER_DIR] == len(kinds) - 1


def test_規則の削除は配備コピーを消す前に行う():
    p = uninstall.plan(opts())
    i_del = index_of(p, lambda s: isinstance(s, model.Op) and s.argv == (net.FORWARD_DEL_SCRIPT,))
    i_rm = index_of(
        p, lambda s: isinstance(s, uninstall.Remove) and s.path == model.ROOT_HELPER_DIR
    )
    assert i_del < i_rm


def test_消すパスはすべて許可リストの中():
    p = uninstall.plan(opts())
    assert set(removes(p)) <= uninstall.allowed_paths("alice")
    assert set(removes(p)) == {
        net.FORWARD_UNIT_PATH,
        "/etc/sudoers.d/kcage-alice",
        model.ROOT_HELPER_DIR,
        model.BROKER_HOST_DIR,
        setup.CONF_DIR,
    }


def test_箱とプロファイルとテンプレートは決まった名前だけを対象にする():
    a = argvs(uninstall.plan(opts()))
    assert ("incus", "delete", "--force", "kcage-demo") in a
    assert ("incus", "image", "delete", "kcage-template") in a
    assert ("incus", "profile", "delete", "kcage-nonet") in a
    # シェルを経由せず、rm も使わない
    assert not any(x[0] in ("sh", "bash", "rm") for x in a)


def test_状態に無いものは手順にしない_冪等():
    p = uninstall.plan(opts(state=uninstall.State()))
    assert p.steps == ()
    assert uninstall.plan(opts()) == uninstall.plan(opts())


def test_keep_policyは許可表を残す():
    p = uninstall.plan(opts(keep_policy=True))
    assert setup.CONF_DIR not in removes(p)
    assert model.ROOT_HELPER_DIR in removes(p)
    assert setup.CONF_DIR in removes(uninstall.plan(opts()))


def test_forwardのユニットだけがあるときは規則の削除スクリプトを呼ばない():
    st = uninstall.State(forward_unit=True)
    a = argvs(uninstall.plan(opts(state=st)))
    assert (net.FORWARD_DEL_SCRIPT,) not in a
    assert ("systemctl", "disable", "--now", net.FORWARD_SERVICE) in a


def test_不正な箱とユニット名は計画で拒否する():
    with pytest.raises(uninstall.UninstallError):
        uninstall.plan(opts(state=uninstall.State(boxes=("kcage-x; rm -rf /",))))
    with pytest.raises(uninstall.UninstallError):
        uninstall.plan(opts(state=uninstall.State(boxes=("other-box",))))
    with pytest.raises(uninstall.UninstallError):
        uninstall.plan(opts(state=uninstall.State(broker_units=("sshd.service",))))


def test_Incus本体とグループは消さない手順しか無い():
    flat = [" ".join(a) for a in argvs(uninstall.plan(opts()))]
    assert not any(
        "apt" in x or "groupdel" in x or "gpasswd" in x or "admin init" in x for x in flat
    )
    assert "apt-get purge incus" in uninstall.NOTES


def test_subidはsetupと同じ行だけを対象にする():
    p = uninstall.plan(opts(drop_subid=True))
    drops = {s.path: s.line for s in p.steps if isinstance(s, uninstall.SubidDrop)}
    assert drops == {"/etc/subuid": setup.subid_line(1000), "/etc/subgid": setup.subid_line(1001)}


def test_drop_lineは完全一致の行だけを消す():
    text = "alice:100000:65536\nroot:1000:1\nroot:1000:10\nroot:10000:1\nbob:1000:1\n"
    assert uninstall.drop_line(text, "root:1000:1") == (
        "alice:100000:65536\nroot:1000:10\nroot:10000:1\nbob:1000:1\n"
    )
    assert uninstall.drop_line("a\nb", "c") == "a\nb"  # 末尾の改行の有無も保つ


# ---- 名前・ユーザーの検証 ----


@pytest.mark.parametrize("bad", ["", "root", "../x", "a b", "a/b", "-x", "x" * 40, "a;b"])
def test_sudoersのユーザー名は形を検証する(bad):
    with pytest.raises(uninstall.UninstallError):
        uninstall.sudoers_path(bad)
    with pytest.raises(uninstall.UninstallError):
        uninstall.resolve_caller({"SUDO_USER": bad})


def test_sudoersのパスは1ファイルだけ():
    assert uninstall.sudoers_path("alice") == "/etc/sudoers.d/kcage-alice"


class _Pw:
    pw_uid = 1000


def test_SUDO_GIDはsetupと同じ検証():
    getpw = lambda u: _Pw()  # noqa: E731
    assert uninstall.resolve_caller({"SUDO_USER": "alice", "SUDO_GID": "1500"}, getpw) == (
        "alice",
        1000,
        1500,
    )
    for bad in ("0", "70000", "abc", "-1", ""):
        assert uninstall.resolve_caller({"SUDO_USER": "alice", "SUDO_GID": bad}, getpw)[2] == 1000


# ---- 確認 ----


def test_yesなしでは確認が要り_yesと打たなければ消さない():
    out: list[str] = []
    assert uninstall.confirm(["kcage-demo"], yes=False, input_fn=lambda _: "yes", out=out.append)
    assert "kcage-demo" in out[0]
    assert not uninstall.confirm([], yes=False, input_fn=lambda _: "y", out=out.append)
    assert not uninstall.confirm([], yes=False, input_fn=lambda _: "", out=out.append)

    def eof(_):
        raise EOFError

    assert not uninstall.confirm([], yes=False, input_fn=eof, out=out.append)
    assert uninstall.confirm([], yes=True, input_fn=eof, out=out.append)


# ---- 状態の収集（接頭辞だけでなくラベルも見る） ----


def test_箱は接頭辞とラベルの両方がそろうものだけ選ぶ():
    def capture(argv):
        a = tuple(argv)
        if a[:2] == ("incus", "list"):
            return 0, "kcage-demo\nkcage-template-build\nother\nkcage-evil;x\n"
        if a[:3] == ("incus", "config", "get"):
            return 0, "demo\n" if a[3] == "kcage-demo" else "\n"
        if a[0] == "systemctl":
            return 0, "kcage-broker-demo-gh.service loaded active running x\nsshd.service a b c d\n"
        if a[:3] == ("incus", "image", "alias"):
            return 0, "kcage-template,abc,container,\n"
        if a[:3] == ("incus", "profile", "list"):
            return 0, "default,x,1\nkcage-nonet,y,0\n"
        return 1, ""

    st = uninstall.gather_state(
        1000,
        1001,
        "alice",
        capture=capture,
        lexists=lambda p: p == "/etc/sudoers.d/kcage-alice",
        read=lambda p: "root:1000:1\n" if p == "/etc/subuid" else "root:5:1\n",
        drop_subid=True,
    )
    assert st.boxes == ("kcage-demo",)
    assert st.broker_units == ("kcage-broker-demo-gh.service",)
    assert st.template_image and st.nonet_profile
    assert st.sudoers and not st.helper_dir
    assert st.subuid_has and not st.subgid_has
    assert box_plan.LABEL_KEY.startswith("user.kcage.")


def test_drop_subidなしではsubuidとsubgidを読まない():
    reads: list[str] = []

    def read(p):
        reads.append(p)
        return "root:1000:1\n"

    st = uninstall.gather_state(
        1000, 1000, "alice", capture=lambda a: (127, ""), lexists=lambda p: False, read=read
    )
    assert reads == [] and not st.subuid_has and not st.subgid_has
    st = uninstall.gather_state(
        1000,
        1000,
        "alice",
        capture=lambda a: (127, ""),
        lexists=lambda p: False,
        read=read,
        drop_subid=True,
    )
    assert reads == ["/etc/subuid", "/etc/subgid"] and st.subuid_has


def test_subidの読み取りは通常ファイルだけ_リンクとFIFOは拒否する(tmp_path):
    f = tmp_path / "s"
    f.write_text("root:1:1\n")
    assert uninstall._read(str(f)) == "root:1:1\n"
    assert uninstall._read(str(tmp_path / "none")) == ""
    lnk = tmp_path / "l"
    lnk.symlink_to(f)
    with pytest.raises(uninstall.UninstallError):
        uninstall._read(str(lnk))
    fifo = tmp_path / "fifo"
    os.mkfifo(fifo)
    with pytest.raises(uninstall.UninstallError):
        uninstall._read(str(fifo))


def test_incusが無くても状態を集められる():
    st = uninstall.gather_state(
        1, 1, "alice", capture=lambda a: (127, ""), lexists=lambda p: False, read=lambda p: ""
    )
    assert st == uninstall.State()


# ---- 実行の直前の検査 ----


NOMOUNT = list


def rm(path, allowed, **kw):
    kw.setdefault("root_uid", os.getuid())
    kw.setdefault("mountpoints", NOMOUNT)
    uninstall.safe_remove(str(path), frozenset(allowed), **kw)


def test_許可リストに無いパスは消さない(tmp_path):
    f = tmp_path / "x"
    f.write_text("a")
    with pytest.raises(uninstall.UninstallError):
        rm(f, {"/other"})
    assert f.exists()


def test_シンボリックリンクは拒否する(tmp_path):
    target = tmp_path / "target"
    target.mkdir()
    (target / "keep").write_text("a")
    link = tmp_path / "link"
    link.symlink_to(target)
    with pytest.raises(uninstall.UninstallError):
        rm(link, {str(link)}, recursive=True)
    assert (target / "keep").exists()


def test_root所有でないものは拒否する(tmp_path):
    d = tmp_path / "d"
    d.mkdir()
    with pytest.raises(uninstall.UninstallError):
        rm(d, {str(d)}, recursive=True, root_uid=os.getuid() + 1)
    assert d.exists()


def test_再帰でない削除は通常ファイルだけ_再帰はディレクトリだけ(tmp_path):
    d = tmp_path / "d"
    d.mkdir()
    f = tmp_path / "f"
    f.write_text("a")
    with pytest.raises(uninstall.UninstallError):
        rm(d, {str(d)})
    with pytest.raises(uninstall.UninstallError):
        rm(f, {str(f)}, recursive=True)
    assert d.exists() and f.exists()
    rm(f, {str(f)})
    assert not f.exists()


def test_親にシンボリックリンクがあるパスは拒否する(tmp_path):
    real = tmp_path / "real"
    (real / "sub").mkdir(parents=True)
    (tmp_path / "lnk").symlink_to(real)
    via = tmp_path / "lnk" / "sub"
    with pytest.raises(uninstall.UninstallError):
        rm(via, {str(via)}, recursive=True)
    assert (real / "sub").exists()


def test_子孫にマウントポイントがある再帰削除は拒否する(tmp_path):
    d = tmp_path / "d"
    (d / "mnt").mkdir(parents=True)
    (d / "mnt" / "keep").write_text("a")
    with pytest.raises(uninstall.UninstallError):
        rm(d, {str(d)}, recursive=True, mountpoints=lambda: [str(d / "mnt")])
    assert (d / "mnt" / "keep").exists()
    rm(
        d, {str(d)}, recursive=True, mountpoints=lambda: [str(tmp_path / "dd")]
    )  # 前方一致だけは別物
    assert not d.exists()


def test_許可リストの中の実体は消し_無ければ何もしない(tmp_path):
    d = tmp_path / "d"
    (d / "sub").mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.write_text("keep")
    (d / "sub" / "l").symlink_to(outside)  # 中のリンクは辿らない
    allowed = {str(d)}
    rm(d, allowed, recursive=True)
    assert not d.exists() and outside.exists()
    rm(d, allowed, recursive=True)  # 冪等


def test_subidの書き換えは対象のファイル名を固定する(tmp_path):
    with pytest.raises(uninstall.UninstallError):
        uninstall.safe_drop_subid(str(tmp_path / "subuid"), "root:1:1")


def _exec(p, *, run=lambda a: 0, remove=lambda x, r: None, drop=lambda a, b: None, label=None):
    return uninstall.execute(
        p, run=run, remove=remove, drop=drop, label=label or (lambda b: "demo")
    )


def test_実行は失敗で止まりremoveの拒否も終了コードにする(capsys):
    p = uninstall.plan(opts())
    ran: list[tuple[str, ...]] = []

    def run(argv):
        ran.append(tuple(argv))
        return 1 if argv[:3] == ("incus", "delete", "--force") else 0

    rc = _exec(p, run=run)
    assert rc == 1 and ("incus", "image", "delete", "kcage-template") not in ran
    assert "トランザクションではない" in capsys.readouterr().err

    def deny(path, recursive):
        raise uninstall.UninstallError("拒否")

    assert _exec(p, remove=deny) == 1


def test_ブローカーの停止に失敗したら以降を実行しない():
    p = uninstall.plan(opts())
    ran: list[tuple[str, ...]] = []

    def run(argv):
        ran.append(tuple(argv))
        return 5 if argv[:2] == ("systemctl", "stop") else 0

    removed: list[str] = []
    rc = _exec(p, run=run, remove=lambda x, r: removed.append(x))
    assert rc == 5
    assert ran == [("systemctl", "stop", "kcage-broker-demo-gh.service")] and removed == []


def test_確認の間にラベルが消えた箱は消さず全体を止める():
    p = uninstall.plan(opts())
    ran: list[tuple[str, ...]] = []
    removed: list[str] = []
    rc = _exec(
        p,
        run=lambda a: ran.append(tuple(a)) or 0,
        remove=lambda x, r: removed.append(x),
        label=lambda b: "",
    )
    assert rc == 1
    assert ("incus", "delete", "--force", "kcage-demo") not in ran and removed == []


def test_ラベルの再確認は箱の削除の直前に入る():
    p = uninstall.plan(opts())
    i = index_of(p, lambda s: isinstance(s, uninstall.LabelGuard))
    assert p.steps[i + 1].argv == ("incus", "delete", "--force", "kcage-demo")


# ---- subid（--drop-subid のときだけ。fd・再読込つきの置換） ----


def test_drop_subidなしでは_subidの手順が計画に無い():
    assert not any(isinstance(s, uninstall.SubidDrop) for s in uninstall.plan(opts()).steps)
    assert any(
        isinstance(s, uninstall.SubidDrop) for s in uninstall.plan(opts(drop_subid=True)).steps
    )


def _subid(tmp_path, text="alice:100000:65536\nroot:1000:1\nbob:1:1\n", mode=0o644):
    f = tmp_path / "subuid"
    f.write_text(text)
    f.chmod(mode)
    return f


def _drop(f, **kw):
    kw.setdefault("root_uid", os.getuid())
    uninstall.safe_drop_subid(str(f), "root:1000:1", allowed_files=[str(f)], **kw)


def test_subidの成功時は他の行が残る(tmp_path):
    f = _subid(tmp_path)
    _drop(f)
    assert f.read_text() == "alice:100000:65536\nbob:1:1\n"
    assert oct(f.stat().st_mode & 0o777) == "0o644"
    assert [p.name for p in tmp_path.iterdir()] == ["subuid"]  # 一時ファイルが残らない


def test_subidは非root所有_書き込み可_FIFO_リンクを拒否する(tmp_path):
    f = _subid(tmp_path)
    with pytest.raises(uninstall.UninstallError):
        _drop(f, root_uid=os.getuid() + 1)
    f.chmod(0o664)
    with pytest.raises(uninstall.UninstallError):
        _drop(f)
    f.unlink()
    fifo = tmp_path / "fifo"
    os.mkfifo(fifo)
    with pytest.raises(uninstall.UninstallError):
        uninstall.safe_drop_subid(str(fifo), "x", root_uid=os.getuid(), allowed_files=[str(fifo)])
    real = _subid(tmp_path, mode=0o644)
    lnk = tmp_path / "lnk"
    lnk.symlink_to(real)
    with pytest.raises(uninstall.UninstallError):
        uninstall.safe_drop_subid(
            str(lnk), "root:1000:1", root_uid=os.getuid(), allowed_files=[str(lnk)]
        )
    assert "root:1000:1" in real.read_text()


def test_subidは置換の前に内容が変わっていたら中止する(tmp_path):
    f = _subid(tmp_path)

    def mutate():
        f.write_text("alice:100000:65536\nroot:1000:1\nbob:1:1\ncarol:2:2\n")

    with pytest.raises(uninstall.UninstallError):
        _drop(f, before_replace=mutate)
    assert "carol:2:2" in f.read_text() and "root:1000:1" in f.read_text()
    assert [p.name for p in tmp_path.iterdir()] == ["subuid"]


def test_subidは置換の前にファイルが差し替わっていたら中止する(tmp_path):
    f = _subid(tmp_path)

    def swap():
        other = tmp_path / "other"
        other.write_text(f.read_text())
        os.replace(other, f)

    with pytest.raises(uninstall.UninstallError):
        _drop(f, before_replace=swap)


def test_subidの書き込みは短いwriteでも書き切り_書けなければ元を保つ(tmp_path, monkeypatch):
    real = os.write
    monkeypatch.setattr(os, "write", lambda fd, b: real(fd, bytes(b)[:5]))
    f = _subid(tmp_path)
    _drop(f)
    assert f.read_text() == "alice:100000:65536\nbob:1:1\n"
    g = _subid(tmp_path)
    monkeypatch.setattr(os, "write", lambda fd, b: 0)
    with pytest.raises(OSError):
        _drop(g)
    assert "root:1000:1" in g.read_text()
    assert [p.name for p in tmp_path.iterdir()] == ["subuid"]


# ---- preflight ----


def _trust_fake(bad: set[str]):
    def check(path, *, allow_missing=False, **kw):
        if path in bad:
            raise uninstall.trust.TrustError(f"bad: {path}")

    return check


@pytest.mark.parametrize(
    "bad",
    [
        net.FORWARD_DEL_SCRIPT,
        model.ROOT_HELPER_DIR,
        net.FORWARD_UNIT_PATH,
        model.BROKER_HOST_DIR,
        "/etc/sudoers.d/kcage-alice",
    ],
)
def test_preflightは信頼できない対象を検出する(bad):
    p = uninstall.plan(opts())
    probs = uninstall.preflight(p, check=_trust_fake({bad}), mountpoints=NOMOUNT)
    assert probs == [f"bad: {bad}"]
    assert uninstall.preflight(p, check=_trust_fake(set()), mountpoints=NOMOUNT) == []


def test_preflightはマウントを含む再帰削除を検出する():
    p = uninstall.plan(opts())
    probs = uninstall.preflight(
        p,
        check=_trust_fake(set()),
        mountpoints=lambda: [model.ROOT_HELPER_DIR + "/kcage/x y", "/proc"],
    )
    assert len(probs) == 1 and "マウント" in probs[0]


def test_mountinfoの解析は8進エスケープを解く():
    data = (
        b"36 35 98:0 / /mnt/a\\040b rw - ext3 /dev/x rw\n1 2 3:4 / / rw shared:1 - ext4 /dev/y rw\n"
    )
    assert uninstall.parse_mountinfo(data) == ["/mnt/a b", "/"]
    assert uninstall.mounts_at_or_under("/a", ["/a", "/a/b", "/ab"]) == ["/a", "/a/b"]


def test_mountinfoはU2028_CR_非UTF8を行の区切りにせず_不正な行は中止する():
    # U+2028・CR・非 UTF-8 のバイトは第 5 フィールドの一部（行を割らない）
    data = (
        "1 2 3:4 / /mnt/a\u2028b\rc rw - ext4 /dev/y rw\n".encode()
        + b"1 2 3:4 / /mnt/\xff\xfe rw - ext4 /dev/y rw\n"
    )
    mps = uninstall.parse_mountinfo(data)
    assert mps == ["/mnt/a\u2028b\rc", os.fsdecode(b"/mnt/\xff\xfe")]
    assert uninstall.mounts_at_or_under("/mnt", mps) == mps
    for bad in (b"garbage\n", b"1 2 3:4 / /m rw\n", b"x 2 3:4 / /m rw - ext4 s rw\n"):
        with pytest.raises(uninstall.UninstallError):
            uninstall.parse_mountinfo(bad)
    # 不正なレコードで preflight は問題にし、何も実行しない
    bad_mounts = lambda: uninstall.parse_mountinfo(b"garbage\n")  # noqa: E731
    probs = uninstall.preflight(
        uninstall.plan(opts()), check=_trust_fake(set()), mountpoints=bad_mounts
    )
    assert any("mountinfo" in m for m in probs)


def test_preflightはRemoveの種別の食い違いを検出する():
    import stat as st

    def lstat_of(modes):
        def f(path):
            if path in modes:
                return os.stat_result((modes[path], 0, 0, 1, 0, 0, 0, 0, 0, 0))
            raise FileNotFoundError(path)

        return f

    p = uninstall.plan(opts())
    ok = {model.ROOT_HELPER_DIR: st.S_IFDIR | 0o755, net.FORWARD_UNIT_PATH: st.S_IFREG | 0o644}
    assert (
        uninstall.preflight(p, check=_trust_fake(set()), mountpoints=NOMOUNT, lstat=lstat_of(ok))
        == []
    )
    bad = {model.ROOT_HELPER_DIR: st.S_IFREG | 0o644, net.FORWARD_UNIT_PATH: st.S_IFDIR | 0o755}
    probs = uninstall.preflight(
        p, check=_trust_fake(set()), mountpoints=NOMOUNT, lstat=lstat_of(bad)
    )
    assert len(probs) == 2


def _main_calls(argv, *, bad=frozenset(), **kw):
    calls: list = []
    rc = uninstall.main(
        argv,
        env=ENV,
        euid=0,
        gather=_gather,
        run=lambda a: calls.append(tuple(a)) or 0,
        input_fn=lambda _: "yes",
        preflight_fn=lambda p: uninstall.preflight(
            p, check=_trust_fake(set(bad)), mountpoints=NOMOUNT
        ),
        **kw,
    )
    return rc, calls


def test_preflightが失敗したらsystemctlもincusも呼ばず終了コード2(monkeypatch):
    monkeypatch.setattr(uninstall.pwd, "getpwnam", lambda u: _Pw())
    for bad in (net.FORWARD_DEL_SCRIPT, model.ROOT_HELPER_DIR, net.FORWARD_UNIT_PATH):
        rc, calls = _main_calls(["--yes"], bad={bad})
        assert rc == 2 and calls == []


def test_dry_runでもpreflightの結果を表示する(monkeypatch, capsys):
    monkeypatch.setattr(uninstall.pwd, "getpwnam", lambda u: _Pw())
    rc, calls = _main_calls(["--dry-run"], bad={model.ROOT_HELPER_DIR})
    out = capsys.readouterr().out
    assert rc == 2 and calls == [] and "事前検査: 失敗" in out
    rc, _ = _main_calls(["--dry-run"])
    assert rc == 0 and "事前検査: 通過" in capsys.readouterr().out


# ---- 状態の調査の失敗・子プロセスの環境 ----


def test_問い合わせの失敗では何も消さず止まり_127は未導入として続行する():
    def fail_on(prefix, rc):
        def capture(argv):
            return (rc, "") if tuple(argv[: len(prefix)]) == prefix else (127, "")

        return capture

    for prefix in (
        ("incus", "list"),
        ("systemctl",),
        ("incus", "image"),
        ("incus", "profile"),
    ):
        with pytest.raises(uninstall.UninstallError, match="調査できない"):
            uninstall.gather_state(
                1, 1, "alice", capture=fail_on(prefix, 1), lexists=lambda p: False
            )
    # 失敗は main で終了コード 2・何も実行しない
    calls: list = []

    def boom(*a, **k):
        raise uninstall.UninstallError("調査できない")

    rc = uninstall.main(["--yes"], env=ENV, euid=0, gather=boom, run=calls.append)
    assert rc == 2 and calls == []
    st = uninstall.gather_state(
        1, 1, "alice", capture=lambda a: (127, ""), lexists=lambda p: False, read=lambda p: ""
    )
    assert st == uninstall.State()


def test_起動できない_実行ファイルが無いは未導入_権限などは中止する(monkeypatch):
    def raiser(exc):
        def f(argv, **kw):
            raise exc

        return f

    monkeypatch.setattr(uninstall.subprocess, "run", raiser(FileNotFoundError()))
    assert uninstall._capture(["incus"]) == (127, "")
    for exc in (PermissionError(13, "x"), OSError(5, "EIO")):
        monkeypatch.setattr(uninstall.subprocess, "run", raiser(exc))
        with pytest.raises(uninstall.UninstallError, match="起動できない"):
            uninstall._capture(["incus"])
        # gather は失敗し、main は何も実行せず 2
        with pytest.raises(uninstall.UninstallError):
            uninstall.gather_state(1, 1, "alice", lexists=lambda p: False)
    calls: list = []
    removed: list = []
    p = uninstall.plan(opts(drop_subid=True))

    # ラベルの確認が起動できなければ、箱の削除以降（Remove・SubidDrop）に進まない
    def bad_label(box):
        raise uninstall.UninstallError("起動できない")

    rc = uninstall.execute(
        p,
        run=lambda a: calls.append(a) or 0,
        remove=lambda x, r: removed.append(x),
        drop=lambda a, b: removed.append(a),
        label=bad_label,
    )
    assert rc == 1 and removed == [] and not any(a[:2] == ("incus", "delete") for a in calls)


def test_子プロセスの環境は最小で_INCUS_やPATHを継承しない(monkeypatch):
    monkeypatch.setenv("INCUS_SOCKET", "/evil")
    monkeypatch.setenv("PATH", "/evil/bin")
    seen: list[dict] = []

    class Proc:
        returncode = 0
        stdout = ""

    def fake_run(argv, **kw):
        seen.append(kw.get("env"))
        return Proc()

    monkeypatch.setattr(uninstall.subprocess, "run", fake_run)
    uninstall._run(["true"])
    uninstall._capture(["true"])
    uninstall._label("kcage-x")
    assert len(seen) == 3
    for env in seen:
        assert env == uninstall.CHILD_ENV
        assert not any(k.startswith("INCUS_") for k in env) and "/evil" not in env["PATH"]


# ---- main（入口の検査・dry-run） ----

ENV = {"SUDO_USER": "alice", "SUDO_GID": "1001"}


def _gather(*a, **k):
    return FULL


def test_rootでなければ何もせず非0(capsys):
    calls: list = []
    rc = uninstall.main(["--yes"], env=ENV, euid=1000, gather=_gather, run=calls.append)
    assert rc != 0 and calls == []


@pytest.mark.parametrize("env", [{}, {"SUDO_USER": "root"}, {"SUDO_USER": "a/b"}])
def test_SUDO_USERが無い_不正なら何もせず非0(env):
    calls: list = []
    rc = uninstall.main(["--yes"], env=env, euid=0, gather=_gather, run=calls.append)
    assert rc != 0 and calls == []


def test_dry_runは計画だけを表示して何も実行しない(monkeypatch, capsys):
    monkeypatch.setattr(uninstall.pwd, "getpwnam", lambda u: _Pw())
    calls: list = []
    rc = uninstall.main(
        ["--dry-run"],
        env=ENV,
        euid=0,
        gather=_gather,
        run=calls.append,
        input_fn=lambda _: 1 / 0,
        preflight_fn=lambda p: [],
    )
    out = capsys.readouterr().out
    assert rc == 0 and calls == []
    assert "incus delete --force kcage-demo" in out and "Incus 本体は消していない" in out


def test_終わりの案内は実行結果とフラグから作る():
    full = uninstall.plan(opts(drop_subid=True))
    n = uninstall.build_notes(full, keep_policy=False, drop_subid=True)
    assert "行を消した" in n and "残した（" not in n.split("apt")[-1] and "kcage init" in n
    assert "許可表も消した" in n
    n = uninstall.build_notes(
        uninstall.plan(opts(keep_policy=True)), keep_policy=True, drop_subid=False
    )
    assert "行は残した" in n and "許可表は /etc/kcage に残した" in n
    n = uninstall.build_notes(
        uninstall.plan(opts(state=uninstall.State())), keep_policy=False, drop_subid=True
    )
    assert "kcage init" not in n and "行は無かった" in n


def test_確認で打たなければ何も実行せず終わる(monkeypatch):
    monkeypatch.setattr(uninstall.pwd, "getpwnam", lambda u: _Pw())
    calls: list = []
    rc = uninstall.main(
        [],
        env=ENV,
        euid=0,
        gather=_gather,
        run=calls.append,
        input_fn=lambda _: "no",
        preflight_fn=lambda p: [],
    )
    assert rc != 0 and calls == []


# ---- cli ----


class Runner:
    def __init__(self, fail_on: str | None = None):
        self.calls: list[list[str]] = []
        self.fail_on = fail_on

    def __call__(self, argv, *, capture: bool = False):
        argv = list(argv)
        self.calls.append(argv)
        if self.fail_on and any(a.endswith(self.fail_on) for a in argv):
            return cli.Result(1)
        return cli.Result(0)


class _Fs(cli.Fs):
    pass


def _main(argv, runner, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    return cli.main(
        argv,
        runner=runner,
        fs=_Fs(),
        dist_builder=lambda d: None,
        pi_version_reader=lambda: "1.5.0",
    )


def test_initはsetupの次にtemplateを実行する(tmp_path, monkeypatch):
    r = Runner()
    assert _main(["init"], r, tmp_path, monkeypatch) == 0
    assert r.calls[0][:2] == ["sudo", "python3"] and r.calls[0][2].endswith("kcage/setup.py")
    assert r.calls[1][:3] == ["sudo", cli.HELPER, "template"]
    assert len(r.calls) == 2


def test_initはsetupが失敗したらtemplateを実行しない(tmp_path, monkeypatch):
    r = Runner(fail_on="setup.py")
    assert _main(["init"], r, tmp_path, monkeypatch) == 1
    assert len(r.calls) == 1


def test_init_dry_runはsetupの表示だけでtemplateを実行しない(tmp_path, monkeypatch):
    r = Runner()
    assert _main(["init", "--dry-run"], r, tmp_path, monkeypatch) == 0
    assert len(r.calls) == 1 and r.calls[0][-1] == "--dry-run" and "--update" not in r.calls[0]


def test_uninstallはsudoでuninstall_pyを実行し旗を渡す(tmp_path, monkeypatch):
    from pathlib import Path

    monkeypatch.setattr(cli, "uninstall_script", lambda: Path("/x/kcage/uninstall.py"))
    r = Runner()
    _main(
        ["uninstall", "--dry-run", "--keep-policy", "--drop-subid", "--yes"],
        r,
        tmp_path,
        monkeypatch,
    )
    argv = r.calls[-1]
    assert argv[:4] == ["sudo", "python3", "-I", "-B"] and argv[4].endswith("kcage/uninstall.py")
    assert argv[5:] == ["--dry-run", "--keep-policy", "--drop-subid", "--yes"]
    _main(["uninstall"], r, tmp_path, monkeypatch)
    assert r.calls[-1][5:] == []


def test_配備コピーが信頼できなければsudoを一度も呼ばず終了コード2(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "uninstall_script", lambda: None)
    r = Runner()
    assert _main(["uninstall", "--yes"], r, tmp_path, monkeypatch) == 2
    assert r.calls == [] and "kcage setup --update" in capsys.readouterr().err


def _deploy(tmp_path):
    pkg = tmp_path / "kcage"
    pkg.mkdir(mode=0o755)
    pkg.chmod(0o755)
    script = pkg / "uninstall.py"
    script.write_text("# deployed\n")
    script.chmod(0o644)
    for m in uninstall.trust.UNINSTALL_MODULES:
        if m != "uninstall.py":
            (pkg / m).write_text("# m\n")
            (pkg / m).chmod(0o644)
    return pkg, script


def _us(tmp_path, root_uid=None):
    return cli.uninstall_script(
        str(tmp_path),
        anchor=str(tmp_path.parent),
        root_uid=os.getuid() if root_uid is None else root_uid,
    )


def test_信頼できる配備コピーだけを返し_リポジトリのコピーへは戻らない(tmp_path):
    assert _us(tmp_path) is None  # 欠落
    pkg, script = _deploy(tmp_path)
    assert _us(tmp_path) == script
    assert _us(tmp_path, root_uid=os.getuid() + 1) is None  # root 所有でない
    script.chmod(0o664)  # group writable
    assert _us(tmp_path) is None
    script.chmod(0o646)  # other writable
    assert _us(tmp_path) is None
    script.chmod(0o644)
    pkg.chmod(0o775)
    assert _us(tmp_path) is None
    pkg.chmod(0o755)
    (pkg / "extra.py").write_text("x")
    (pkg / "extra.py").chmod(0o666)
    assert _us(tmp_path) is None  # 配備コピー内の他のファイルも検査する
    (pkg / "extra.py").unlink()
    assert _us(tmp_path) == script
    # 配備の根（kcage の外）にある実体も検査する
    (tmp_path / "kcage-root").write_text("x")
    (tmp_path / "kcage-root").chmod(0o666)
    assert _us(tmp_path) is None
    (tmp_path / "kcage-root").chmod(0o755)
    assert _us(tmp_path) == script


def test_必須モジュールが欠けた配備コピーは信頼しない(tmp_path):
    pkg, script = _deploy(tmp_path)
    assert _us(tmp_path) == script
    for m in uninstall.trust.UNINSTALL_MODULES:
        if m == "uninstall.py":
            continue
        (pkg / m).unlink()
        assert _us(tmp_path) is None, m
        (pkg / m).write_text("# m\n")
        (pkg / m).chmod(0o644)
    assert _us(tmp_path) == script
    assert "配備コピーが古い・欠けている" in cli.UNINSTALL_UNTRUSTED


def test_配備コピーがシンボリックリンク_親がリンクなら信頼しない(tmp_path):
    _pkg, script = _deploy(tmp_path)
    real = tmp_path / "elsewhere.py"
    real.write_text("# other\n")
    script.unlink()
    script.symlink_to(real)
    assert _us(tmp_path) is None
    link_parent = tmp_path.parent / (tmp_path.name + "-lnk")
    link_parent.symlink_to(tmp_path)
    try:
        script.unlink()
        script.write_text("# d\n")
        script.chmod(0o644)
        assert (
            cli.uninstall_script(
                str(link_parent), anchor=str(tmp_path.parent), root_uid=os.getuid()
            )
            is None
        )
    finally:
        link_parent.unlink()


def test_trustは非正規・相対パスを拒否する(tmp_path):
    from kcage import trust

    with pytest.raises(trust.TrustError):
        trust.check_trusted("relative/path")
    with pytest.raises(trust.TrustError):
        trust.check_trusted("/usr/../etc")
    # 存在しない構成要素: 拒否（allow_missing なら、存在する祖先の検査だけで通る）
    missing = str(tmp_path / "a" / "b")
    trust.check_trusted(missing, allow_missing=True, root_uid=os.getuid(), start=str(tmp_path))
    with pytest.raises(trust.TrustError):
        trust.check_trusted(missing, root_uid=os.getuid(), start=str(tmp_path))
