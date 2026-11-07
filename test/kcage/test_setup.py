"""setup.py の試験。計画（純粋）と、実行層の止まり方を確かめる。実際の apt・incus・sudo は呼ばない。"""

from __future__ import annotations

from kcage import model, setup

SUDOERS = "alice ALL=(root) NOPASSWD: /usr/local/libexec/kcage/kcage-root up *\n"


def opts(**kw) -> setup.Opts:
    base = {"user": "alice", "uid": 1000, "src_dir": "/src/scripts/kcage", "sudoers_text": SUDOERS}
    base.update(kw)
    return setup.Opts(**base)


def argvs(p: model.Plan) -> list[tuple[str, ...]]:
    return [s.argv for s in p.steps if isinstance(s, model.Op)]


def files(p: model.Plan) -> dict[str, model.FilePut]:
    return {s.path: s for s in p.steps if isinstance(s, model.FilePut)}


def test_初回は導入_初期化_subuid_配備_許可表_sudoersを順に行う():
    p = setup.plan(opts())
    a = argvs(p)
    assert ("apt-get", "install", "-y", "incus") in a
    assert ("incus", "admin", "init", "--minimal") in a
    assert any("root:1000:1" in x[2] and "/etc/subuid" in x[2] for x in a if x[0] == "sh")
    assert any("root:1000:1" in x[2] and "/etc/subgid" in x[2] for x in a if x[0] == "sh")
    f = files(p)
    assert model.POLICY_PATH in f
    assert f[model.POLICY_PATH].mode == "0644"
    assert "[defaults]" in (f[model.POLICY_PATH].content or "")
    assert setup.HELPER_ENTRY in f
    assert f[setup.HELPER_ENTRY].mode == "0755"
    assert f[setup.HELPER_ENTRY].owner == "root:root"


def test_導入済みの状態では飛ばす_冪等():
    st = setup.State(
        incus_installed=True,
        incus_initialized=True,
        subuid_has=True,
        subgid_has=True,
        policy_exists=True,
    )
    p = setup.plan(opts(state=st))
    a = argvs(p)
    assert ("apt-get", "install", "-y", "incus") not in a
    assert ("incus", "admin", "init", "--minimal") not in a
    assert not any(x[0] == "sh" for x in a)
    assert model.POLICY_PATH not in files(p)  # 既存の許可表を上書きしない


def test_2回計画しても同じ():
    assert setup.plan(opts()) == setup.plan(opts())


def test_配備コピーはroot所有の配備先へ作業ツリーから複製する():
    p = setup.plan(opts())
    a = argvs(p)
    assert ("cp", "-r", "/src/scripts/kcage", f"{model.ROOT_HELPER_DIR}/kcage") in a
    assert ("chown", "-R", "root:root", f"{model.ROOT_HELPER_DIR}/kcage") in a
    assert "root_helper" in files(p)[setup.HELPER_ENTRY].content
    # 作業ツリーのコードを sudo で直接実行する手順は無い
    assert not any("/src/" in x[0] for x in a)


def test_updateは配備コピーだけを更新する():
    p = setup.plan(opts(update=True))
    a = argvs(p)
    assert not any(x[0] == "apt-get" for x in a)
    assert model.POLICY_PATH not in files(p)
    assert ("cp", "-r", "/src/scripts/kcage", f"{model.ROOT_HELPER_DIR}/kcage") in a


def test_sudoersは検証の後で置く():
    p = setup.plan(opts())
    names = [("op", s.argv[0]) if isinstance(s, model.Op) else ("file", s.path) for s in p.steps]
    tmp = "/etc/sudoers.d/.kcage-alice.new"
    i_put = names.index(("file", tmp))
    i_visudo = names.index(("op", "visudo"))
    i_mv = [i for i, n in enumerate(names) if n == ("op", "mv")][-1]
    assert i_put < i_visudo < i_mv
    assert files(p)[tmp].mode == "0440"
    assert ("visudo", "-cf", tmp) in argvs(p)
    assert ("mv", "-f", tmp, "/etc/sudoers.d/kcage-alice") in argvs(p)
    assert "/etc/sudoers.d/kcage-alice" not in files(p)  # 検証前に最終名で置かない


def test_visudoが失敗したらsudoersを置かず一時ファイルを消す():
    p = setup.plan(opts())
    ran: list[tuple[str, ...]] = []
    removed: list[str] = []
    put: list[str] = []

    def run(argv):
        ran.append(tuple(argv))
        return 1 if argv[0] == "visudo" else 0

    rc = setup.execute(p, run=run, put=lambda fp: put.append(fp.path), remove=removed.append)
    assert rc == 1
    assert not any(a[0] == "mv" for a in ran)
    assert "/etc/sudoers.d/kcage-alice" not in put
    assert removed == ["/etc/sudoers.d/.kcage-alice.new"]


def test_成功すれば最後まで実行する():
    p = setup.plan(opts())
    ran: list[tuple[str, ...]] = []
    rc = setup.execute(
        p, run=lambda a: ran.append(tuple(a)) or 0, put=lambda fp: None, remove=lambda x: None
    )
    assert rc == 0
    assert ran[-1][0] == "mv"


def test_incus_adminへユーザーを足す手順は作らない():
    p = setup.plan(opts(state=setup.State(user_in_incus_admin=True)))
    flat = [" ".join(a) for a in argvs(p)]
    assert not any(
        "incus-admin" in x and ("usermod" in x or "adduser" in x or "gpasswd -a" in x) for x in flat
    )
    assert not any("usermod" in x for x in flat)


def test_incus_adminに入っていたら警告する():
    w = setup.warnings(opts(state=setup.State(user_in_incus_admin=True)))
    assert any("incus-admin" in x for x in w)
    assert setup.warnings(opts()) == []


def test_netが無いときは警告だけ():
    assert any("kcage.net" in x for x in setup.warnings(opts(), net_available=False))


def test_netの準備は許可表の後_sudoersの前に入る():
    extra = model.Op(
        where="host", argv=("systemctl", "enable", "kcage-forward.service"), desc="FORWARD"
    )
    p = setup.plan(opts(net_steps=(extra,)))
    steps = list(p.steps)
    i = steps.index(extra)
    assert any(isinstance(s, model.FilePut) and s.path == model.POLICY_PATH for s in steps[:i])
    assert any(isinstance(s, model.FilePut) and s.path.endswith(".new") for s in steps[i:])


def test_dry_runの表示は全手順を含みファイルの内容を出さない():
    lines = setup.describe(setup.plan(opts()))
    text = "\n".join(lines)
    assert "visudo" in text
    assert "NOPASSWD" not in text  # FilePut は内容を出さない


def test_複製先とパスはモデルの固定値を使う():
    assert f"{model.ROOT_HELPER_DIR}/kcage-root" == setup.HELPER_ENTRY
    assert setup.subid_line(1001) == "root:1001:1"


def test_配備される入口スクリプトは実際に動き_引数を渡す(tmp_path):
    """e2e で見つけた不具合: 入口が main() を引数なしで呼び、全 verb が TypeError で落ちていた。文字列の試験では見つからない。"""
    import subprocess
    import sys
    from pathlib import Path

    scripts = Path(setup.__file__).resolve().parents[1]
    entry = tmp_path / "kcage-root"
    entry.write_text(
        setup.HELPER_SCRIPT.replace(model.ROOT_HELPER_DIR, str(scripts)), encoding="utf-8"
    )
    # root でないので拒否されるが、使い方の誤り（TypeError）ではなく、kcage-root の拒否メッセージで終わること
    proc = subprocess.run(
        [sys.executable, str(entry), "ls"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={"PATH": "/usr/bin:/bin"},
        check=False,
    )
    assert "TypeError" not in proc.stderr, proc.stderr
    assert proc.returncode != 0 and "kcage-root:" in proc.stderr
    proc = subprocess.run(
        [sys.executable, str(entry), "frobnicate", "demo"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={"PATH": "/usr/bin:/bin"},
        check=False,
    )
    assert "未知の verb" in proc.stderr


def test_最後の案内にbox_templateが入る():
    assert "kcage template" in setup.NEXT_STEPS
    assert setup.NEXT_STEPS.index("kcage template") < setup.NEXT_STEPS.index("kcage register")
