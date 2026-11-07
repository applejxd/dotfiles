"""箱 (Incus) の制御面を AI から触らせない規則 (common.toml の incus / kcage-root / kcage の動詞と kcage-* の誘導)。

ホストの pi は Incus を直接操作しない。管理操作・ソケット・配備先・許可表への書き込みを拒否する。
うっかり防止であり、敵対的な迂回 (動的な組み立て・別言語での書き込みなど) は防げない。
see docs/spec/guard/agent-command-policy.md#箱incusの管理操作の拒否
"""

from __future__ import annotations

import pytest
from agents_common import load_common
from test_pi_confirm import _bash, _judge, needs_node

pytestmark = needs_node

ROLES = ["implementer", "worker"]
FLAGS = [{}, {"bypass": True}]


def _decide(commands, role="implementer"):
    reqs = [{**_bash(c, **flags), "role": role} for c in commands for flags in FLAGS]
    results = _judge(reqs)
    keys = [(c, bool(f)) for c in commands for f in FLAGS]
    return list(zip(keys, results, strict=True))


def _assert_all(commands, expected, role="implementer"):
    for (cmd, bypass), result in _decide(commands, role):
        assert result["decision"] == expected, f"{cmd!r} bypass={bypass} -> {result}"


# ─── 1. incus コマンドの全般 (読み取りも拒否) ────────────────────────────────────────────
INCUS = [
    "incus list",
    "incus ls",
    "incus config set x security.privileged=true",
    "incus config device add c1 sock proxy listen=unix:/a connect=unix:/b",
    "incus exec c1 -- bash",
    "incus launch images:ubuntu/24.04 c1",
    "incus project list",
    "/usr/bin/incus list",
    "sudo incus list",
    "cd /tmp && incus list",
    "echo x | incus file push - c1/tmp/a",
    "env incus list",
    "env FOO=1 incus list",
    "command incus list",
    "xargs incus delete",
    "sh -c 'incus list'",
    "bash -lc 'incus list'",
    "bash -c 'echo a; incus list'",
    "timeout 5 incus list",
    "nohup incus list",
]


@pytest.mark.parametrize("role", ROLES)
def test_incus_commands_are_denied(role):
    _assert_all(INCUS, "deny", role)


def test_denials_have_guidance_in_the_opencode_deny_guide():
    # pi の [bash] deny は誘導より先に当たり、理由は定型になる。案内文は OpenCode の deny_guide に持たせる
    alternatives = load_common()["bash"]["deny_guide"]["alternative"]
    messages = {c: a["message"] for a in alternatives for c in a["commands"]}
    assert "kcage ls" in messages["incus"]
    assert (
        "kcage" in messages["kcage-root"]
        and "kcage" in messages["/usr/local/libexec/kcage/kcage-root"]
    )
    for verb in ("kcage rm", "kcage register", "kcage setup", "kcage init", "kcage uninstall"):
        assert "人だけ" in messages[verb]


# ─── 2. root 所有の補助の直接呼び出し ──────────────────────────────────────────────────
BOX_ROOT = [
    "kcage-root ls",
    "/usr/local/libexec/kcage/kcage-root ls",
    "sudo kcage-root up repo",
    "sudo -n kcage-root ls",
    "sudo -n /usr/local/libexec/kcage/kcage-root ls",
    "env kcage-root ls",
    "sh -c 'kcage-root ls'",
    "xargs kcage-root",
]


def test_box_root_direct_calls_are_denied():
    _assert_all(BOX_ROOT, "deny")


# ─── 3. 人だけが行う kcage の動詞 ────────────────────────────────────────────────────────
BOX_HUMAN = [
    "kcage rm repo",
    "kcage register",
    "kcage register ~/src/repo",
    "kcage setup",
    "kcage init",
    "kcage init --dry-run",
    "kcage uninstall",
    "kcage uninstall --yes --keep-policy",
    "sh -c 'kcage uninstall'",
    "env kcage init",
    "cd /tmp && kcage rm repo",
    "env kcage rm repo",
    "sh -c 'kcage setup'",
    "bash -lc 'kcage register x'",
    "xargs kcage rm",
]
BOX_ALLOWED = [
    "kcage ls",
    "kcage up",
    "kcage stop",
    "kcage pi",
    "kcage exec -- ls",
    "kcage doctor",
    "kcage selftest",
]


def test_human_only_box_verbs_are_denied():
    _assert_all(BOX_HUMAN, "deny")


def test_allowed_box_verbs_are_not_denied():
    for (cmd, bypass), result in _decide(BOX_ALLOWED):
        assert result["decision"] != "deny", f"{cmd!r} bypass={bypass} -> {result}"


# ─── 4. Incus・Docker のソケット ─────────────────────────────────────────────────────
SOCKETS = [
    "curl --unix-socket /var/lib/incus/unix.socket http://incus/1.0",
    "curl --unix-socket=/var/lib/incus/unix.socket http://incus/1.0",
    "curl -s --unix-socket /var/run/docker.sock http://localhost/containers/json",
    "nc -U /var/lib/incus/unix.socket",
    "python3 -c \"import socket; s=socket.socket(socket.AF_UNIX); s.connect('/var/lib/incus/unix.socket')\"",
    "python -c \"import socket; socket.socket(socket.AF_UNIX).connect('/var/run/docker.sock')\"",
    "docker -H unix:///var/run/docker.sock ps",
    "node -e \"require('net').connect('/var/lib/incus/unix.socket')\"",
    "sh -c 'curl --unix-socket /var/lib/incus/unix.socket http://x/'",
]
SOCKET_OK = [
    "ls /var/lib",
    "grep -r docker.sock docs/",
    "grep -rn unix.socket docs/",
    "ls /var/run",
    "curl http://localhost:8080/",
]


def test_incus_and_docker_socket_access_is_denied():
    _assert_all(SOCKETS, "deny")


def test_socket_mentions_without_a_connecting_command_are_not_denied():
    for (cmd, bypass), result in _decide(SOCKET_OK):
        assert result["decision"] != "deny", f"{cmd!r} bypass={bypass} -> {result}"


# ─── 5. 配備先・許可表・sudoers・ブローカーのソケットへの書き込み ────────────────────────
PROTECTED = [
    "/etc/kcage/policy.toml",
    "/usr/local/libexec/kcage/kcage-root",
    "/etc/sudoers.d/kcage",
    "/etc/sudoers",
    "/run/kcage-broker/x.sock",
]
FILE_TOOLS = ["write", "edit"]


def _file(tool, path, role="implementer"):
    return {
        "tool": tool,
        "input": {"path": path, "content": "x"},
        "cwd": "/work/proj",
        "role": role,
    }


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("path", PROTECTED)
def test_file_tools_cannot_write_the_box_control_paths(role, path):
    results = _judge([_file(t, path, role) for t in FILE_TOOLS])
    assert [r["decision"] for r in results] == ["deny"] * len(FILE_TOOLS), results


@pytest.mark.parametrize("path", PROTECTED)
def test_shell_writes_to_the_box_control_paths_are_denied(path):
    commands = [
        f"echo x > {path}",
        f"echo x >> {path}",
        f"tee {path} < /dev/null",
        f"cp /tmp/a {path}",
        f"mv /tmp/a {path}",
        f"rm {path}",
        f"install -m 755 /tmp/a {path}",
        f"sed -i s/a/b/ {path}",
        f"sh -c 'echo x > {path}'",
    ]
    _assert_all(commands, "deny")


def test_reads_and_user_config_are_not_denied():
    reads = [
        "ls /usr/local/bin",
        "ls /etc",
        "ls -la /usr/local/libexec/kcage/",
        "echo x > ~/.config/kcage/config.toml",
        "cp /tmp/a ~/.config/kcage/config.toml",
        "echo x > /usr/local/bin/foo",
    ]
    for (cmd, bypass), result in _decide(reads):
        assert result["decision"] != "deny", f"{cmd!r} bypass={bypass} -> {result}"
    for tool in FILE_TOOLS:
        (result,) = _judge([_file(tool, "~/.config/kcage/config.toml")])
        assert result["decision"] != "deny", result


# ─── 6. incus-admin への追加 ──────────────────────────────────────────────────────────
ADMIN = [
    "usermod -aG incus-admin $USER",
    "sudo usermod -aG incus-admin $USER",
    "sudo -n usermod -a -G incus-admin me",
    "gpasswd -a me incus-admin",
    "sudo gpasswd -a me incus-admin",
    "adduser me incus-admin",
    "sudo adduser me incus-admin",
    "sg incus-admin -c 'incus list'",
    "newgrp incus-admin",
]


def test_adding_to_the_incus_admin_group_is_denied():
    _assert_all(ADMIN, "deny")


# ─── 誤検知の抑制 ─────────────────────────────────────────────────────────────────────
HARMLESS = [
    "echo incus",
    "grep -r incus docs/",
    "grep -rn 'incus list' docs/",
    "ls /usr/local/bin",
    "git log --oneline -- docs/adr/0028-per-repo-agent-container.md",
    "cat docs/research/agents/incus-dev-environment.md",
    "echo kcage-root",
    "ls docs | grep incus",
    "id -nG",
]


def test_unrelated_commands_mentioning_incus_are_not_denied():
    # cat などほかの誘導で止まるものがあっても、箱の規則 (kcage-* の誘導・[bash] deny) が理由ではないこと
    for (cmd, bypass), result in _decide(HARMLESS):
        guide = result.get("guide") or ""
        reason = result.get("reason") or ""
        assert not guide.startswith("kcage-"), f"{cmd!r} bypass={bypass} -> {result}"
        assert "deny パターン" not in reason, f"{cmd!r} bypass={bypass} -> {result}"
