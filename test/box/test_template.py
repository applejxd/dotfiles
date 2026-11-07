"""テンプレート作成の計画（template.py）の試験。純粋な計画だけを検査する。"""

from __future__ import annotations

import pytest
from box import model, template

FPR = "0123456789ABCDEF0123456789ABCDEF01234567"


def build(**kw) -> model.Plan:
    return template.plan_build(template.TemplateOpts(nvidia_key_fpr=FPR, **kw))


def ops(p: model.Plan) -> list[model.Op]:
    return [s for s in p.steps if isinstance(s, model.Op)]


def flat(p: model.Plan) -> list[str]:
    return [" ".join(o.argv) for o in ops(p)]


def test_一時の箱をubuntu24_04から作る():
    p = build()
    assert p.box == "box-template-build"
    launch = next(o for o in ops(p) if o.argv[:2] == ("incus", "launch"))
    assert launch.argv[2:4] == ("images:ubuntu/24.04", "box-template-build")
    assert "security.privileged" not in " ".join(launch.argv)  # 特権化しない


def test_docker_node_git_toolkitを入れる():
    text = "\n".join(flat(build()))
    for pkg in ("docker.io", "nodejs", "git", "nvidia-container-toolkit"):
        assert pkg in text


def test_nvidiaの鍵は指紋を確かめてから置く():
    p = build()
    f = flat(p)
    i_fetch = next(i for i, x in enumerate(f) if "nvidia.asc" in x and x.startswith("curl"))
    i_check = next(i for i, x in enumerate(f) if FPR in x)
    i_dearmor = next(i for i, x in enumerate(f) if x.startswith("gpg --dearmor"))
    assert i_fetch < i_check < i_dearmor
    assert next(o for o in ops(p) if FPR in " ".join(o.argv)).check is True


@pytest.mark.parametrize("bad", ["", "xyz", "12 zz"])
def test_指紋が無いか不正なら計画を作らない(bad):
    with pytest.raises(ValueError):
        template.plan_build(template.TemplateOpts(nvidia_key_fpr=bad))


def test_cdiのユニットは起動のたびに生成する():
    p = build()
    unit = next(
        s for s in p.steps if isinstance(s, model.FilePut) and s.path.endswith("box-cdi.service")
    )
    assert "nvidia-ctk cdi generate" in unit.content
    assert "WantedBy=multi-user.target" in unit.content
    assert "[Service]" in unit.content and "Type=oneshot" in unit.content
    assert unit.where == "box"
    assert "systemctl enable box-cdi.service" in flat(p)
    # イメージ作成時に一度だけ生成する手順は作らない（古くなるため）
    assert not any("cdi generate" in x for x in flat(p))


def test_dockerのcdiを有効にする設定とld_confを置く():
    p = build()
    paths = {s.path: s for s in p.steps if isinstance(s, model.FilePut)}
    assert '"cdi": true' in paths["/etc/docker/daemon.json"].content
    assert paths["/etc/ld.so.conf.d/wsl-lib.conf"].content.strip() == "/usr/lib/wsl/lib"


def test_uid1000のユーザーを用意する():
    assert any("useradd -m -u 1000" in x and "ubuntu" in x for x in flat(build()))


def test_publishして一時の箱を消す_別名は許可表の値():
    p = build(alias="my-template")
    f = flat(p)
    assert "incus publish box-template-build --alias my-template" in f
    assert f[-1] == "incus delete box-template-build"
    assert f.index("incus publish box-template-build --alias my-template") < len(f) - 1
    assert f.index("incus stop box-template-build") < f.index(
        "incus publish box-template-build --alias my-template"
    )


def test_既定の別名はbox_template():
    assert "incus publish box-template-build --alias box-template" in flat(build())


def test_配布物があれば箱へ入れ_なければ入れない():
    assert not any("file push" in x for x in flat(build()))
    p = build(dist_dir="/tmp/dist")
    assert "incus file push -r /tmp/dist box-template-build/opt/box-dist" in flat(p)


def test_net由来の手順は起動の直後_apt_getの前に入る():
    extra = model.FilePut(
        where="box",
        path="/etc/environment",
        mode="0644",
        owner="root:root",
        content="HTTP_PROXY=x\n",
    )
    p = build(extra_steps=(extra,))
    steps = list(p.steps)
    i = steps.index(extra)
    launch = next(
        i
        for i, s in enumerate(steps)
        if isinstance(s, model.Op) and s.argv[:2] == ("incus", "launch")
    )
    apt = next(
        i
        for i, s in enumerate(steps)
        if isinstance(s, model.Op) and s.argv[:2] == ("apt-get", "update")
    )
    assert launch < i < apt


def test_計画に秘密や組織固有の値を含めない():
    text = "\n".join(flat(build()))
    assert "token" not in text.lower()


def test_計画は純粋で毎回同じ():
    assert build() == build()
