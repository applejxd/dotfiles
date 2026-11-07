"""テンプレート作成の計画（template.py）の試験。純粋な計画だけを検査する。"""

from __future__ import annotations

import pytest
from kcage import model, template

FPR = "0123456789ABCDEF0123456789ABCDEF01234567"


def build(**kw) -> model.Plan:
    return template.plan_build(template.TemplateOpts(nvidia_key_fpr=FPR, **kw))


def ops(p: model.Plan) -> list[model.Op]:
    return [s for s in p.steps if isinstance(s, model.Op)]


def flat(p: model.Plan) -> list[str]:
    return [" ".join(o.argv) for o in ops(p)]


def test_一時の箱をubuntu24_04から作る():
    p = build()
    assert p.box == "kcage-template-build"
    launch = next(o for o in ops(p) if o.argv[:2] == ("incus", "launch"))
    assert launch.argv[2:4] == ("images:ubuntu/24.04", "kcage-template-build")
    assert "security.privileged" not in " ".join(launch.argv)  # 特権化しない


def test_docker_node_git_toolkitを入れる():
    text = "\n".join(flat(build()))
    for pkg in ("docker.io", "docker-compose-v2", "git", "nvidia-container-toolkit"):
        assert pkg in text
    # pi は Node 22.1 以上が要る。apt の nodejs（18）ではなく公式配布を検証して入れる
    assert "nodejs.org/dist/latest-v" in text and "sha256sum -c" in text
    assert " nodejs" not in text.split("apt-get install -y")[1].split("\n")[0]


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
        s for s in p.steps if isinstance(s, model.FilePut) and s.path.endswith("kcage-cdi.service")
    )
    assert "nvidia-ctk cdi generate" in unit.content
    assert "WantedBy=multi-user.target" in unit.content
    assert "[Service]" in unit.content and "Type=oneshot" in unit.content
    assert unit.where == "box"
    assert "systemctl enable kcage-cdi.service" in flat(p)
    # イメージ作成時に一度だけ生成する手順は作らない（古くなるため）
    assert not any("cdi generate" in x for x in flat(p))


def test_dockerのcdiを有効にする設定とld_confを置く():
    p = build()
    paths = {s.path: s for s in p.steps if isinstance(s, model.FilePut)}
    assert '"cdi": true' in paths["/etc/docker/daemon.json"].content
    # docker のソケットのグループは箱のユーザーの主グループ（exec の --group で届く。docker.socket の drop-in）
    assert "SocketGroup=ubuntu" in paths[template.DOCKER_SOCKET_DROPIN_PATH].content
    assert paths["/etc/ld.so.conf.d/wsl-lib.conf"].content.strip() == "/usr/lib/wsl/lib"


def test_uid1000のユーザーを用意する():
    assert any("useradd -m -u 1000" in x and "ubuntu" in x for x in flat(build()))


def test_publishして一時の箱を消す_別名は許可表の値():
    p = build(alias="my-template")
    f = flat(p)
    assert "incus publish kcage-template-build --alias my-template" in f
    assert f[-1] == "incus delete kcage-template-build"
    assert f.index("incus publish kcage-template-build --alias my-template") < len(f) - 1
    assert f.index("incus stop kcage-template-build") < f.index(
        "incus publish kcage-template-build --alias my-template"
    )


def test_既定の別名はbox_template():
    assert "incus publish kcage-template-build --alias kcage-template" in flat(build())


def test_配布物があれば箱へ入れ_なければ入れない():
    assert not any("file push" in x for x in flat(build()))
    p = build(dist_dir="/tmp/dist")
    # push -r は元のディレクトリ名で宛先の下へ置く（宛先が無いと Not Found）。所定の名前へは箱の中で移す
    assert "incus file push -r /tmp/dist kcage-template-build/opt/" in flat(p)
    assert any("mv /opt/'dist' /opt/kcage-dist" in x for x in flat(p))
    assert any(x.startswith("chown -R root:root /opt/kcage-dist") for x in flat(p))
    # 元の名前が所定の名前と同じなら移さない
    q = build(dist_dir="/tmp/kcage-dist")
    assert not any("mv /opt/" in x for x in flat(q))


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


# ---- 鍵の指紋・pi の版・build_proxy


def test_nvidia鍵の指紋は主鍵の40桁の16進():
    import re

    assert re.fullmatch(r"[0-9A-F]{40}", template.NVIDIA_KEY_FPR)
    assert template.NVIDIA_KEY_FPR == "C95B321B61E88C1809C4F759DDCAE044F796ECB0"  # gitleaks:allow
    # 既定の opts がそのまま使え、検査の行にも入る
    p = template.plan_build(template.TemplateOpts())
    assert any(template.NVIDIA_KEY_FPR in x for x in flat(p))


def test_pi_versionが無ければ版なしで入れる():
    assert any(x == f"npm install -g {template.PI_PACKAGE}" for x in flat(build()))


@pytest.mark.parametrize("v", ["1.5.0", "0.12.3-beta.1", "2.0.0.rc1", "10.20.30"])
def test_pi_versionは版つきで入れる(v):
    assert f"npm install -g {template.PI_PACKAGE}@{v}" in flat(build(pi_version=v))


@pytest.mark.parametrize(
    "v", ["", "1.5", "latest", "1.5.0; rm -rf /", "^1.5.0", "1.5.0 x", "v1.5.0"]
)
def test_pi_versionの不正は拒否する(v):
    with pytest.raises(ValueError):
        build(pi_version=v)


def test_build_proxyなしなら設定ファイルを置かない():
    p = build()
    paths = [s.path for s in p.steps if isinstance(s, model.FilePut)]
    assert not any("build-proxy" in x for x in paths)
    assert "/etc/gitconfig" not in paths


def test_build_proxyの設定は箱の中へ置きnetを使わない():
    setup_steps, cleanup = template.build_proxy_steps("192.0.2.10:3128")
    puts = {s.path: s.content for s in setup_steps if isinstance(s, model.FilePut)}
    url = "http://192.0.2.10:3128"
    assert url in puts["/etc/apt/apt.conf.d/99kcage-build-proxy"]
    assert "Acquire::https::Proxy" in puts["/etc/apt/apt.conf.d/99kcage-build-proxy"]
    assert "HTTPS_PROXY" in puts["/etc/profile.d/kcage-build-proxy.sh"]
    assert f"proxy = {url}" in puts["/etc/gitconfig"]
    env_op = next(
        s for s in setup_steps if isinstance(s, model.Op) and "/etc/environment" in s.argv[-1]
    )
    assert url in env_op.argv[-1] and ">>" in env_op.argv[-1]
    assert "127.0.0.1:3128" not in repr(setup_steps)  # net.proxy_env の固定値は使わない
    # 片づける側は、置いた設定ファイルを全部消す
    rm = next(s for s in cleanup if isinstance(s, model.Op) and s.argv[:2] == ("rm", "-f"))
    assert set(template.BUILD_PROXY_FILES) <= set(rm.argv)
    assert set(puts) <= set(rm.argv)


def test_build_proxyの設定はpublishの前に消す():
    setup_steps, cleanup = template.build_proxy_steps("proxy.example.test:8080")
    p = build(extra_steps=setup_steps, cleanup_steps=cleanup)
    steps = list(p.steps)
    i_setup = next(
        i
        for i, s in enumerate(steps)
        if isinstance(s, model.FilePut) and "99kcage-build-proxy" in s.path
    )
    i_apt = next(
        i
        for i, s in enumerate(steps)
        if isinstance(s, model.Op) and s.argv[:2] == ("apt-get", "update")
    )
    i_rm = next(
        i for i, s in enumerate(steps) if isinstance(s, model.Op) and s.argv[:2] == ("rm", "-f")
    )
    i_stop = next(
        i
        for i, s in enumerate(steps)
        if isinstance(s, model.Op) and s.argv[:2] == ("incus", "stop")
    )
    i_pub = next(
        i
        for i, s in enumerate(steps)
        if isinstance(s, model.Op) and s.argv[:2] == ("incus", "publish")
    )
    assert i_setup < i_apt  # 最初の apt より前に proxy を置く
    assert i_rm < i_stop < i_pub  # 止める・公開する前に消す


def test_build_proxyの形が不正なら作らない():
    with pytest.raises(ValueError):
        template.build_proxy_steps("http://192.0.2.10:3128")
