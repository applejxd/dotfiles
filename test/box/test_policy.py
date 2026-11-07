"""scripts/box/policy.py の試験。厳格な解釈・許可表の安全確認・追記。"""

from __future__ import annotations

import pytest
from box import model, policy
from box_fakes import POLICY_TEXT, FakeFs

P = policy.PolicyError


def _repo(extra: str = "") -> str:
    return f'[repo.demo]\npath = "/home/a/demo"\n{extra}'


def test_parse_demo() -> None:
    pol = policy.parse(POLICY_TEXT)
    r = pol.repos["demo"]
    assert r.gpu and r.uid == 1000 and r.network == "proxy-only"
    assert r.ports == (model.PortRange(8080, 8080), model.PortRange(9000, 9099))
    assert pol.deny_paths == ("/mnt/d/private",)


@pytest.mark.parametrize(
    "text",
    [
        "[repo.demo]\npath='/a'\nunknown=1\n",  # 未知のキー
        "unknown = 1\n",  # 最上位の未知のキー
        "[defaults]\nfoo=1\n",
        "[repo.Bad_ID]\npath='/a'\n",  # id の形
        "[repo." + "a" * 32 + "]\npath='/a'\n",  # 長すぎる id
        "[repo.demo]\npath='relative'\n",
        "[repo.demo]\npath='/a/../b'\n",
        "[repo.demo]\npath='/a'\ndata_roots=['rel']\n",
        "[repo.demo]\npath='/a'\nports=['80']\n",
        "[repo.demo]\npath='/a'\nports=[[1,2,3]]\n",
        "[repo.demo]\npath='/a'\nports=[[9,1]]\n",
        "[repo.demo]\npath='/a'\nports=[70000]\n",
        "[repo.demo]\npath='/a'\nports=[true]\n",
        "[repo.demo]\npath='/a'\nbrokers=['ssh']\n",
        "[repo.demo]\npath='/a'\nnetwork='open'\n",
        "[repo.demo]\npath='/a'\nidmap='both'\n",
        "[repo.demo]\npath='/a'\nuid=0\n",
        "[repo.demo]\npath='/a'\nuid=65536\n",
        "[repo.demo]\npath='/a'\nuid='1000'\n",
        "[repo.demo]\npath='/a'\ngpu='yes'\n",
        "[repo.demo]\npath='/a'\nsubnet='10.0.0.1/8'\n",  # strict でない CIDR
        "[repo.demo]\npath='/a'\nnetwork='proxy-only'\n",  # 上流なし
        "[repo.demo]\npath='/a'\nproxy_upstream='bad'\n",
        "[repo.demo]\npath='/a'\nproxy_upstream='h:99999'\n",
        "[repo.demo.secrets.gh]\nsource='file'\n",  # path なし
        "[repo.demo.secrets.gh]\nsource='command'\nargv='sh -c x'\n",  # 配列でない
        "[repo.demo.secrets.gh]\nsource='env'\n",
        "[repo.demo.secrets.gh]\nsource='file'\npath='/a'\nvalue='x'\n",  # 値は書けない
        "not toml [",
    ],
)
def test_parse_rejects(text: str) -> None:
    if text.startswith("[repo.demo.secrets"):
        text = "[repo.demo]\npath='/a'\n" + text
    with pytest.raises(P):
        policy.parse(text)


def test_upstream_forms() -> None:
    for up in ("192.0.2.1:8080", "[2001:db8::1]:3128", "proxy.example.test:3128"):
        pol = policy.parse(_repo(f'network="proxy-only"\nproxy_upstream="{up}"\n'))
        assert pol.repos["demo"].proxy_upstream == up


def test_secrets_parse() -> None:
    pol = policy.parse(
        _repo()
        + "[repo.demo.secrets.gh]\nsource='file'\npath='/etc/box/s/gh'\n"
        + "[repo.demo.secrets.aws]\nsource='command'\nargv=['/usr/bin/x','y']\n"
        + "[repo.demo.secrets.hf]\nsource='prompt'\n"
    )
    s = pol.repos["demo"].secrets
    assert s["gh"].source == "file" and s["aws"].argv == ("/usr/bin/x", "y")
    assert s["hf"].source == "prompt"


def test_defaults_network_inherited() -> None:
    pol = policy.parse('[defaults]\nnetwork="offline"\n' + _repo())
    assert pol.repos["demo"].network == "offline"


def _fs_for_policy() -> FakeFs:
    fs = FakeFs()
    fs.add_dir("/etc", uid=0, mode=0o755)
    fs.add_dir("/etc/box", uid=0, mode=0o755)
    fs.add_file("/etc/box/policy.toml", "", uid=0, mode=0o644)
    return fs


def test_check_file_safe_ok() -> None:
    policy.check_file_safe("/etc/box/policy.toml", fs=_fs_for_policy())


@pytest.mark.parametrize(
    ("path", "kw"),
    [
        ("/etc/box/policy.toml", {"uid": 1000}),  # 所有者が root でない
        ("/etc/box/policy.toml", {"mode": 0o666}),  # 他人から書ける
        ("/etc/box/policy.toml", {"mode": 0o664}),  # グループから書ける
        ("/etc/box", {"uid": 1000}),  # 親が root 所有でない
        ("/etc/box", {"mode": 0o777}),  # 親が書ける
        ("/etc", {"mode": 0o775}),  # 祖先が書ける
    ],
)
def test_check_file_safe_rejects(path: str, kw: dict) -> None:
    fs = _fs_for_policy()
    fs.nodes[path].update(kw)
    with pytest.raises(P):
        policy.check_file_safe("/etc/box/policy.toml", fs=fs)


def test_check_file_safe_missing() -> None:
    with pytest.raises(P):
        policy.check_file_safe("/etc/box/none.toml", fs=_fs_for_policy())


def test_load_uses_fs() -> None:
    fs = _fs_for_policy()
    fs.add_file("/etc/box/policy.toml", POLICY_TEXT)
    assert "demo" in policy.load("/etc/box/policy.toml", fs=fs).repos


def test_render_and_add_repo_roundtrip() -> None:
    block = policy.render_repo_block(
        "new1",
        path="/home/a/new",
        data_roots=("/mnt/d/x",),
        ports=(model.PortRange(80, 80), model.PortRange(9000, 9010)),
        brokers=("gh",),
        gpu=True,
        network="proxy-only",
        proxy_upstream="192.0.2.5:3128",
        idmap="root",
        uid=1001,
        subnet="10.88.0.0/24",
    )
    text = policy.add_repo(POLICY_TEXT, block)
    r = policy.parse(text).repos["new1"]
    assert r.idmap == "root" and r.uid == 1001 and r.ports[1].hi == 9010
    assert "demo" in policy.parse(text).repos  # 既存は残る


def test_add_repo_to_empty_and_duplicate() -> None:
    block = policy.render_repo_block("a1", path="/home/a/x")
    text = policy.add_repo("", block)
    assert "a1" in policy.parse(text).repos
    with pytest.raises(P, match="重複"):
        policy.add_repo(text, block)


def test_add_repo_rejects_bad_block() -> None:
    with pytest.raises(P):
        policy.add_repo("", '[repo.a1]\npath = "rel"\n')
    with pytest.raises(P):
        policy.add_repo("", '[defaults]\nnetwork = "offline"\n')
    with pytest.raises(P):  # 2 つ同時には足せない
        policy.add_repo("", '[repo.a1]\npath = "/a"\n[repo.b1]\npath = "/b"\n')


def test_render_does_not_mutate_inputs_and_is_pure() -> None:
    a = policy.render_repo_block("a1", path="/x")
    b = policy.render_repo_block("a1", path="/x")
    assert a == b
