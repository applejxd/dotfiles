"""scripts/kcage/config.py の試験。kcage.toml は要求にすぎず、範囲外・危険なものは拒否される。"""

from __future__ import annotations

import dataclasses

import pytest
from kcage import config, model, policy
from kcage_fakes import POLICY_TEXT, demo_fs, demo_policy

REPO = "/home/alice/work/demo"
E = config.ConfigError


def _resolve(spec: model.RepoSpec, fs=None, pol=None, **kw) -> model.BoxConfig:
    return config.resolve(pol or demo_policy(), "demo", spec, fs or demo_fs(), **kw)


def _spec_fs(text: str):
    fs = demo_fs()
    fs.add_file(f"{REPO}/kcage.toml", text, uid=1000)
    return fs


def test_defaults_mounts_and_labels() -> None:
    cfg = _resolve(model.RepoSpec())
    assert cfg.name == "kcage-demo" and cfg.uid == 1000
    rw = [m for m in cfg.mounts if not m.readonly]
    assert [(m.kind, m.source, m.path) for m in rw] == [
        ("repo", REPO, REPO),
        ("repo", f"{REPO}/.git", f"{REPO}/.git"),  # pin（.git を自分自身へ rw で bind）
    ]
    ro = {m.source for m in cfg.mounts if m.readonly}
    assert ro == {f"{REPO}/.git/hooks", f"{REPO}/.git/config", f"{REPO}/.git/commondir"}
    assert cfg.labels[model.LABEL_PREFIX + "repo"] == "demo"
    assert cfg.labels[model.LABEL_PREFIX + "managed"] == "true"
    assert cfg.network == "proxy-only" and cfg.proxy_upstream == "192.0.2.10:3128"


def _wipe_git(fs) -> None:
    for p in [k for k in fs.nodes if k.startswith(REPO + "/.git")]:
        del fs.nodes[p]


def test_pin_は_ro_の子の重ねより前に入る() -> None:
    mounts = _resolve(model.RepoSpec()).mounts
    git = f"{REPO}/.git"
    pin = next(i for i, m in enumerate(mounts) if m.source == git)
    assert not mounts[pin].readonly and mounts[pin].path == git
    ro_idx = [i for i, m in enumerate(mounts) if m.readonly]
    assert ro_idx and all(pin < i for i in ro_idx)


def test_pin_は_git_が_symlink_ファイル_無し_のとき入らない() -> None:
    git = f"{REPO}/.git"
    fs = demo_fs()
    _wipe_git(fs)
    fs.add_link(git, "/tmp/elsewhere")
    assert all(m.source != git for m in _resolve(model.RepoSpec(), fs).mounts)
    fs = demo_fs()
    _wipe_git(fs)
    fs.add_file(git, "gitdir: /x/.git/worktrees/w\n", uid=1000)  # linked worktree
    assert all(m.source != git for m in _resolve(model.RepoSpec(), fs).mounts)
    fs = demo_fs()
    _wipe_git(fs)
    assert all(m.source != git for m in _resolve(model.RepoSpec(), fs).mounts)


def test_no_git_dir_no_extra_mounts() -> None:
    fs = demo_fs()
    for p in [k for k in fs.nodes if k.startswith(REPO + "/.git")]:
        del fs.nodes[p]
    assert len(_resolve(model.RepoSpec(), fs).mounts) == 1


def test_data_gpu_ports() -> None:
    cfg = _resolve(model.RepoSpec(data=("models/small",), ports=(8080, 9001), gpu=True))
    kinds = [(m.kind, m.readonly) for m in cfg.mounts]
    assert ("data", True) in kinds and ("gpu-lib", True) in kinds and ("gpu-drivers", True) in kinds
    data = next(m for m in cfg.mounts if m.kind == "data")
    assert data.source == data.path == "/mnt/d/datasets/models/small"
    assert cfg.ports == (model.PortForward(8080, 8080), model.PortForward(9001, 9001))
    assert cfg.gpu


def test_unregistered_id() -> None:
    with pytest.raises(E, match="未登録"):
        config.resolve(demo_policy(), "nope", model.RepoSpec(), demo_fs())


def test_images_unsupported() -> None:
    with pytest.raises(E, match="images は未対応"):
        _resolve(model.RepoSpec(images=True))


def test_gpu_and_broker_not_allowed() -> None:
    pol = policy.parse(POLICY_TEXT.replace("gpu = true", "gpu = false"))
    with pytest.raises(E, match="gpu"):
        _resolve(model.RepoSpec(gpu=True), pol=pol)
    with pytest.raises(E, match="ブローカー"):
        _resolve(model.RepoSpec(brokers=("aws",)))
    assert _resolve(model.RepoSpec(brokers=("gh", "gh"))).brokers == ("gh",)


@pytest.mark.parametrize("ports", [(80,), (9100,), (0,), (70000,), (8080, 8080)])
def test_ports_rejected(ports: tuple[int, ...]) -> None:
    with pytest.raises(E):
        _resolve(model.RepoSpec(ports=ports))


def test_port_in_use() -> None:
    with pytest.raises(E, match="使用中"):
        _resolve(model.RepoSpec(ports=(8080,)), host_ports_in_use=(8080,))


@pytest.mark.parametrize(
    "rel",
    ["", "/mnt/d/datasets/models", "../x", "models/../small", "models//small", "./models", "nope"],
)
def test_data_rejected(rel: str) -> None:
    with pytest.raises(E):
        _resolve(model.RepoSpec(data=(rel,)))


def test_data_symlink_component_rejected() -> None:
    fs = demo_fs()
    fs.add_dir("/outside/secret-data", uid=1000)
    fs.add_link("/mnt/d/datasets/link", "/outside/secret-data")
    with pytest.raises(E, match="symlink"):
        _resolve(model.RepoSpec(data=("link",)), fs)
    fs.add_link("/mnt/d/datasets/models/sub", "/outside")
    with pytest.raises(E, match="symlink"):
        _resolve(model.RepoSpec(data=("models/sub/secret-data",)), fs)


def test_data_file_not_dir_rejected() -> None:
    fs = demo_fs()
    fs.add_file("/mnt/d/datasets/f.bin", "x")
    with pytest.raises(E):
        _resolve(model.RepoSpec(data=("f.bin",)), fs)


def test_data_ambiguous_across_roots() -> None:
    fs = demo_fs()
    fs.add_dir("/mnt/e/data/models/small", uid=1000)
    with pytest.raises(E, match="曖昧"):
        _resolve(model.RepoSpec(data=("models/small",)), fs)


def test_data_root_denied_by_policy_deny_paths() -> None:
    fs = demo_fs()
    fs.add_dir("/mnt/d/datasets/x", uid=1000)
    text = POLICY_TEXT.replace('["/mnt/d/private"]', '["/mnt/d/datasets/x"]')
    with pytest.raises(E, match="拒否リスト"):
        _resolve(model.RepoSpec(data=("x",)), fs, policy.parse(text))
    # 根そのものが拒否リストの親（deny が根の下）でも、子の方向で拒否される
    text = POLICY_TEXT.replace('["/mnt/d/private"]', '["/mnt/d/datasets/x/y"]')
    with pytest.raises(E, match="拒否リスト"):
        _resolve(model.RepoSpec(data=("x",)), fs, policy.parse(text))


def test_data_overlapping_repo_rejected() -> None:
    text = POLICY_TEXT.replace('["/mnt/d/datasets", "/mnt/e/data"]', '["/home/alice/work"]')
    with pytest.raises(E, match="リポジトリと重なる"):
        _resolve(model.RepoSpec(data=("demo",)), demo_fs(), policy.parse(text))


@pytest.mark.parametrize(
    "repo",
    [
        "/home/alice/.ssh/repo",  # ホームの秘密の下
        "/home/alice",  # ホームの秘密の親
        "/run/user/1000/x",
        "/etc/kcage",
        "/var/lib/docker/x",
        "/",
        "/mnt/d/private/x",  # 許可表の deny_paths の下
        "/mnt/d",  # deny_paths の親
    ],
)
def test_repo_denied(repo: str) -> None:
    fs = demo_fs()
    fs.add_dir(repo, uid=1000)
    text = POLICY_TEXT.replace('path = "/home/alice/work/demo"', f'path = "{repo}"')
    with pytest.raises(E):
        _resolve(model.RepoSpec(), fs, policy.parse(text))


def test_repo_symlink_or_missing_rejected() -> None:
    fs = demo_fs()
    del fs.nodes[REPO]
    fs.add_link(REPO, "/mnt/e/data/other")
    with pytest.raises(E):
        _resolve(model.RepoSpec(), fs)
    fs2 = demo_fs()
    del fs2.nodes[REPO]
    with pytest.raises(E):
        _resolve(model.RepoSpec(), fs2)


def test_repo_parent_symlink_rejected() -> None:
    fs = demo_fs()
    fs.add_link("/home/alice/link", "/home/alice/work")
    text = POLICY_TEXT.replace(REPO, "/home/alice/link/demo")
    with pytest.raises(E):
        _resolve(model.RepoSpec(), fs, policy.parse(text))


def test_git_hooks_symlink_rejected() -> None:
    fs = demo_fs()
    del fs.nodes[f"{REPO}/.git/hooks"]
    fs.add_link(f"{REPO}/.git/hooks", "/tmp/evil")
    with pytest.raises(E, match="hooks"):
        _resolve(model.RepoSpec(), fs)


def test_network_only_stricter() -> None:
    nat = policy.parse(
        POLICY_TEXT.replace('network = "proxy-only"\nproxy_upstream = "192.0.2.10:3128"\n', "")
    )
    assert _resolve(model.RepoSpec(network="offline"), pol=nat).network == "offline"
    # 緩和は効かない
    assert _resolve(model.RepoSpec(network="nat")).network == "proxy-only"
    assert _resolve(model.RepoSpec(network="offline")).network == "offline"


def test_proxy_only_request_without_upstream() -> None:
    nat = policy.parse(
        POLICY_TEXT.replace('network = "proxy-only"\nproxy_upstream = "192.0.2.10:3128"\n', "")
    )
    with pytest.raises(E, match="proxy_upstream"):
        _resolve(model.RepoSpec(network="proxy-only"), pol=nat)


# ---- load_spec


def test_load_spec_missing_is_default() -> None:
    assert config.load_spec(REPO, fs=demo_fs()) == model.RepoSpec()


def test_load_spec_full() -> None:
    fs = _spec_fs(
        'data=["a/b"]\nports=[80]\nbrokers=["gh"]\ngpu=true\nnetwork="offline"\nimages=false\n'
    )
    s = config.load_spec(REPO, fs=fs)
    assert s == model.RepoSpec(("a/b",), (80,), ("gh",), True, "offline", False)


@pytest.mark.parametrize(
    "text",
    [
        "unknown=1\n",
        'data="x"\n',
        "data=[1]\n",
        'ports=["80"]\n',
        "ports=[true]\n",
        'brokers=["ssh"]\n',
        'gpu="yes"\n',
        'network="open"\n',
        "images=1\n",
        "bad toml [",
        "uid = 0\n",  # 権限に関わるキーは書けない
        "mounts = []\n",
        "proxy_upstream = 'x:1'\n",
    ],
)
def test_load_spec_rejects(text: str) -> None:
    with pytest.raises(E):
        config.load_spec(REPO, fs=_spec_fs(text))


def test_load_spec_symlink_and_size() -> None:
    fs = demo_fs()
    fs.add_link(f"{REPO}/kcage.toml", "/etc/kcage/policy.toml")
    with pytest.raises(E, match="symlink"):
        config.load_spec(REPO, fs=fs)
    with pytest.raises(E, match="64KiB"):
        config.load_spec(REPO, fs=_spec_fs("#" + "a" * 70000))


def test_resolved_config_is_frozen() -> None:
    cfg = _resolve(model.RepoSpec())
    with pytest.raises(dataclasses.FrozenInstanceError):
        cfg.uid = 0  # type: ignore[misc]


def test_is_denied_both_directions() -> None:
    assert config.is_denied("/etc")  # 親
    assert config.is_denied("/etc/kcage/x")  # 子
    assert config.is_denied("/run")
    assert config.is_denied("/home/u/.ssh")
    assert config.is_denied("/home/u/.config/kcage/x")
    assert not config.is_denied("/home/u/work")


def _hf_fs():
    fs = demo_fs()
    fs.add_file("/home/alice/.cache/huggingface/token", "x", uid=1000)
    fs.add_dir("/home/alice/.cache/huggingface/hub", uid=1000)
    return fs


def test_hf_cache_whole_denied_but_hub_allowed() -> None:
    text = POLICY_TEXT.replace('["/mnt/d/datasets", "/mnt/e/data"]', '["/home/alice/.cache"]')
    with pytest.raises(E, match="拒否リスト"):
        _resolve(model.RepoSpec(data=("huggingface",)), _hf_fs(), policy.parse(text))
    text = POLICY_TEXT.replace(
        '["/mnt/d/datasets", "/mnt/e/data"]', '["/home/alice/.cache/huggingface"]'
    )
    cfg = _resolve(model.RepoSpec(data=("hub",)), _hf_fs(), policy.parse(text))
    assert any(m.source == "/home/alice/.cache/huggingface/hub" for m in cfg.mounts)


@pytest.mark.parametrize(
    "p",
    [
        "/home/alice/.config/gh",
        "/home/alice/.docker/config.json",
        "/home/alice/.netrc",
        "/home/alice/.git-credentials",
        "/home/alice/.pi/agent/auth.json",
        "/home/alice/.cache/huggingface/token",
        "/home/alice/.cache/huggingface/stored_tokens",
    ],
)
def test_builtin_credential_paths_denied(p: str) -> None:
    assert config.is_denied(p)
    assert not config.is_denied("/home/alice/.cache/huggingface/hub")


# ---- 資源の上限（kcage.toml は許可表より小さい値にだけできる）


def _limited_policy(**kw) -> model.HostPolicy:
    import dataclasses

    pol = demo_policy()
    repo = dataclasses.replace(pol.repos["demo"], **kw)
    return dataclasses.replace(pol, repos={"demo": repo})


def test_上限は許可表が未設定なら要求を無視する() -> None:
    cfg = _resolve(model.RepoSpec(cpu=2, memory_mib=256, processes=100))
    assert (cfg.cpu, cfg.memory_mib, cfg.processes, cfg.idmap_isolated) == (None, None, None, False)


def test_上限は小さい要求だけが効く() -> None:
    pol = _limited_policy(cpu=4, memory_mib=4096, processes=1000, idmap_isolated=True)
    cfg = _resolve(model.RepoSpec(cpu=2, memory_mib=8192), pol=pol)
    assert (cfg.cpu, cfg.memory_mib, cfg.processes) == (2, 4096, 1000)  # 大きい要求は切り詰め
    assert cfg.idmap_isolated is True
    assert _resolve(model.RepoSpec(), pol=pol).cpu == 4


def test_kcage_toml_の上限を読む() -> None:
    spec = config.parse_spec('cpu = 2\nmemory = "1GiB"\nprocesses = 100\n')
    assert (spec.cpu, spec.memory_mib, spec.processes) == (2, 1024, 100)


@pytest.mark.parametrize(
    "text", ["cpu = 0\n", 'memory = "1GB"\n', "processes = 1\n", 'cpu = "2"\n']
)
def test_kcage_toml_の不正な上限は拒否する(text: str) -> None:
    with pytest.raises(E):
        config.parse_spec(text)
