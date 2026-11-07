"""結合試験: 許可表 → 解決 → 本物の net・broker の計画 → plan_up → box-root の実行（FakeRunner）。

担当ごとに別々に作った部品（W1a の核・W2 の net・W3 の broker）が、署名・型・許可の検査で噛み合うことを確かめる。
incus も root も要らない。
"""

from __future__ import annotations

import io

import pytest
from box import root_helper
from box_fakes import FakeRunner, demo_fs

DUMMY = "DUMMY-SECRET-VALUE-0123456789"

POLICY = """\
[defaults]
network = "nat"

[repo.demo]
path = "/home/alice/work/demo"
data_roots = ["/mnt/d/datasets"]
ports = [[9000, 9099]]
brokers = {brokers}
gpu = true
network = "{network}"
{upstream}uid = 1000

[repo.demo.secrets.gh]
source = "file"
path = "/home/alice/.config/box/gh-token"

[repo.demo.secrets.copilot]
source = "file"
path = "/home/alice/.config/box/copilot-token"

[repo.demo.secrets.aws-role]
source = "file"
path = "/home/alice/.config/box/aws-role"
"""


def _run(network: str, brokers: list[str]):
    upstream = 'proxy_upstream = "192.0.2.10:3128"\n' if network == "proxy-only" else ""
    text = POLICY.format(brokers=str(brokers).replace("'", '"'), network=network, upstream=upstream)
    fs = demo_fs()
    fs.add_file("/etc/box/policy.toml", text)
    runner = FakeRunner()
    out, err = io.StringIO(), io.StringIO()
    rc = root_helper.main(
        ["up", "demo"],
        env={"SUDO_UID": "1000"},
        runner=runner,
        fs=fs,
        euid=0,
        stdout=out,
        stderr=err,
        sleep=lambda s: None,
        secret_resolver=lambda ref, uid: DUMMY,
    )
    return rc, runner, out.getvalue(), err.getvalue()


@pytest.mark.parametrize("network", ["nat", "proxy-only", "offline"])
@pytest.mark.parametrize(
    "brokers",
    [[], ["hf-cache"], ["gh"], ["copilot"], ["aws"], ["gh", "aws", "copilot", "hf-cache"]],
)
def test_全モード_全ブローカーで_up_が通り_秘密が_argv_に出ない(
    network: str, brokers: list[str]
) -> None:
    rc, runner, out, err = _run(network, brokers)
    assert rc == 0, err
    # 秘密は argv・出力に出ない（stdin_secret 経由だけ）
    assert all(DUMMY not in " ".join(a) for a in runner.argvs)
    assert DUMMY not in out + err


def test_nic_なしのモードは_box_nonet_で作る() -> None:
    for network in ("proxy-only", "offline"):
        rc, runner, _, err = _run(network, [])
        assert rc == 0, err
        inits = [a for a in runner.argvs if a[:2] == ("incus", "init")]
        assert inits and "-p" in inits[0] and "box-nonet" in inits[0], inits
        assert not any(
            a[:6] == ("incus", "config", "device", "add", "box-demo", "eth0") for a in runner.argvs
        )
        # e2e で見つけた: プロファイルの作成は init より前（後だと「プロファイルが無い」で失敗する）
        i_create = runner.argvs.index(("incus", "profile", "create", "box-nonet"))
        i_init = runner.argvs.index(inits[0])
        assert i_create < i_init


def test_nat_は_default_プロファイルと_nic() -> None:
    rc, runner, _, err = _run("nat", [])
    assert rc == 0, err
    inits = [a for a in runner.argvs if a[:2] == ("incus", "init")]
    assert "default" in inits[0]
    assert any("nic" in a and "network=incusbr0" in a for a in runner.argvs)


def test_offline_はブローカーを外す() -> None:
    rc, runner, _out, err = _run("offline", ["gh", "aws"])
    assert rc == 0, err
    # offline は外へつながる proxy・relay を付けない（契約 C15）
    assert not any("proxy" in a and "box-broker" in " ".join(a) for a in runner.argvs)


def test_proxy_only_は上流への_proxy_デバイスだけ() -> None:
    rc, runner, _, err = _run("proxy-only", [])
    assert rc == 0, err
    proxies = [
        a
        for a in runner.argvs
        if a[:6] == ("incus", "config", "device", "add", "box-demo", "proxy-out")
    ]
    assert len(proxies) == 1
    assert "connect=tcp:192.0.2.10:3128" in proxies[0]


# ---- W1b（cli）と W1a（config）の接続: doctor の box.toml 検査が、未知のキーを実際に検出すること


class _CliFs:
    def __init__(self, text: str | None) -> None:
        self.text = text

    def exists(self, path: str) -> bool:
        return self.text is not None

    def read_text(self, path: str) -> str:
        assert self.text is not None
        return self.text


@pytest.mark.parametrize(
    ("text", "status"),
    [
        (None, "warn"),
        ("gpu = true\nports = [9000]\n", "ok"),
        ("unknown_key = 1\n", "fail"),
        ('ports = ["x"]\n', "fail"),
        ("not = [valid", "fail"),
    ],
)
def test_doctor_の_box_toml_検査は_config_の厳格な検証を使う(text, status) -> None:
    from box import cli

    assert cli.check_box_toml("/repo", _CliFs(text)).status == status


def test_parse_spec_は純粋で_load_spec_と同じ検証() -> None:
    from box import config

    spec = config.parse_spec('gpu = true\nports = [9000]\nbrokers = ["gh"]\n')
    assert spec.gpu and spec.ports == (9000,) and spec.brokers == ("gh",)
    with pytest.raises(config.ConfigError):
        config.parse_spec("unknown = 1")


# ---- e2e で見つけた: パスワードなしで何でも実行できる sudo の検出


def test_doctor_は_nopasswd_all_を検出する() -> None:
    from box import cli

    bad = "User u may run the following commands:\n    (ALL : ALL) ALL\n    (ALL) NOPASSWD: ALL\n"
    assert cli.check_passwordless_sudo(bad).status == "fail"
    ok = "User u may run the following commands:\n    (root) NOPASSWD: /usr/local/libexec/box/box-root up *\n    (ALL : ALL) ALL\n"
    assert cli.check_passwordless_sudo(ok).status == "ok"
    assert cli.check_passwordless_sudo(None).status == "warn"


# ---- e2e 前に見つけた: cli の register が box-root の register の引数の形（--path 必須）と合っていること


def test_cli_の_register_の引数を_root_helper_が解釈できる() -> None:
    from box import cli
    from test_cli import FakeFs, FakeRunner

    runner = FakeRunner(top="/home/alice/work/newrepo")
    rc = cli.main(
        [
            "register",
            "--data-root",
            "/mnt/d/datasets",
            "--port",
            "9000-9099",
            "--broker",
            "gh",
            "--gpu",
            "--network",
            "proxy-only",
            "--proxy-upstream",
            "192.0.2.10:3128",
        ],
        runner=runner,
        fs=FakeFs({}),
    )
    assert rc == 0
    argv = [c for c in runner.calls if "register" in c][-1]
    i = argv.index("register")
    req = root_helper.parse_args(argv[i:])
    assert req.verb == "register" and req.repo_id == "newrepo"
    assert req.options["path"] == "/home/alice/work/newrepo"
    assert req.options["gpu"] and req.options["brokers"] == ["gh"]
