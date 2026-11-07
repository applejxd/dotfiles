"""aws ブローカー（計画と認証情報サーバー）・hf-cache・振り分けの試験。実際の aws・ネットワークは使わない。"""

from __future__ import annotations

import http.client
import json
import os
import shutil
import socket
import subprocess
import tempfile
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest
from kcage import model
from kcage.broker import aws, aws_server, hfcache
from kcage.broker import plan as broker_plan
from test_broker_common import (
    DUMMY_ROLE_ARN,
    DUMMY_STS_KEY,
    DUMMY_STS_SECRET,
    DUMMY_STS_TOKEN,
    REPO,
    cfg,
    flat,
    policy,
    secret_values,
)

# ---- 振り分け ----


def test_plan_dispatches_each_kind() -> None:
    for kind in ("gh", "aws", "copilot", "hf-cache"):
        assert broker_plan(kind, cfg(), policy()).kind == kind


def test_plan_rejects_unknown_kind() -> None:
    with pytest.raises(ValueError, match="未知"):
        broker_plan("bw", cfg(), policy())  # type: ignore[arg-type]


def test_plan_rejects_kind_not_allowed_by_policy() -> None:
    with pytest.raises(ValueError, match="許可表"):
        broker_plan("aws", cfg(), policy(brokers=("hf-cache",)))


def test_plan_rejects_missing_secret() -> None:
    p = model.RepoPolicy(id=REPO, path="/tmp/demo", brokers=("aws",), secrets={})
    with pytest.raises(ValueError, match="aws-role"):
        broker_plan("aws", cfg(), p)


def test_repo_id_cannot_escape_the_socket_directory() -> None:
    bad = model.RepoPolicy(id="../x", path="/tmp/x", brokers=("aws",), secrets=policy().secrets)
    c = cfg().__class__(**{**cfg().__dict__, "repo_id": "../x"})
    with pytest.raises(ValueError, match="repo-id"):
        broker_plan("aws", c, bad)


# ---- aws の計画 ----


def test_aws_device_is_fixed_loopback_to_the_broker_dir() -> None:
    p = broker_plan("aws", cfg(), policy())
    (dev,) = p.devices
    assert dev.type == "proxy"
    assert dict(dev.config) == {
        "listen": "tcp:127.0.0.1:7111",
        "connect": f"unix:{model.BROKER_HOST_DIR}/{REPO}/aws.sock",
        "bind": "instance",
    }
    assert p.env["AWS_CONTAINER_CREDENTIALS_FULL_URI"] == "http://127.0.0.1:7111/creds"
    assert "AWS_CONTAINER_AUTHORIZATION_TOKEN" not in p.env
    assert p.routes[0].modes == ("nat", "proxy-only")


def test_aws_puts_nothing_in_the_box_and_no_long_term_keys() -> None:
    p = broker_plan("aws", cfg(), policy())
    assert p.files == ()
    text = flat(p)
    for needle in (
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_PROFILE",
        ".aws/",
        "sso/cache",
    ):
        assert needle not in text


def test_aws_role_arn_goes_only_through_stdin_secret() -> None:
    p = broker_plan("aws", cfg(), policy())
    with_secret = [op for op in p.host_ops if op.stdin_secret is not None]
    assert len(with_secret) == 1
    assert (
        with_secret[0].stdin_secret is not None and with_secret[0].stdin_secret.name == "aws-role"
    )


def test_no_plan_contains_secret_values() -> None:
    for kind in ("gh", "aws", "copilot", "hf-cache"):
        text = flat(broker_plan(kind, cfg(), policy()))
        for value in secret_values():
            assert value not in text, (kind, "本物の値や出どころが計画に出ている")


def test_aws_has_stop_and_readiness_without_sts() -> None:
    p = broker_plan("aws", cfg(), policy())
    assert p.readiness is not None and "/healthz" in p.readiness.argv[-1]
    assert p.stop_ops and all(op.where == "host" for op in p.stop_ops)
    server = next(op for op in p.host_ops if "kcage.broker.aws_server" in op.argv)
    assert "--ttl" in server.argv and server.argv[server.argv.index("--ttl") + 1] == "3600"


def test_aws_ttl_is_clamped() -> None:
    p = aws.plan(cfg(), policy(), ttl=10)
    server = next(op for op in p.host_ops if "kcage.broker.aws_server" in op.argv)
    assert server.argv[server.argv.index("--ttl") + 1] == "900"


# ---- hf-cache ----


def _flag(op: model.Op, prefix: str) -> list[str]:
    return [a for a in op.argv if a.startswith(prefix)]


def test_aws_unit_runs_as_repo_uid_but_gh_and_copilot_do_not() -> None:
    aws_plan = broker_plan("aws", cfg(), policy())
    unit = next(op for op in aws_plan.host_ops if op.argv[0] == "systemd-run")
    assert "--uid=1000" in unit.argv and "--gid=1000" in unit.argv
    for kind in ("gh", "copilot"):
        for op in broker_plan(kind, cfg(), policy()).host_ops:
            assert not _flag(op, "--uid") and not _flag(op, "--gid"), kind


def test_aws_state_dir_and_arn_file_are_owned_by_uid() -> None:
    p = broker_plan("aws", cfg(), policy())
    prep = next(op for op in p.host_ops if op.stdin_secret is not None)
    script = prep.argv[2]
    assert "install -d -m 0700" in script and "umask 077" in script
    assert 'chown -R -- 1000:1000 "$d"' in script
    state = f"{model.BROKER_HOST_DIR}/{REPO}/.state-aws"
    assert prep.argv[-1] == state
    server = next(op for op in p.host_ops if "kcage.broker.aws_server" in op.argv)
    assert server.argv[server.argv.index("--role-arn-file") + 1] == f"{state}/token"


def test_gh_and_copilot_state_stay_root_only() -> None:
    for kind in ("gh", "copilot"):
        prep = next(op for op in broker_plan(kind, cfg(), policy()).host_ops if op.stdin_secret)
        assert "chown" not in prep.argv[2], kind


def test_aws_socket_dir_is_owned_by_uid_0700() -> None:
    p = broker_plan("aws", cfg(), policy())
    dirs = p.host_ops[2]
    assert dirs.argv[-1] == "1000"
    assert dirs.argv[-2] == f"{model.BROKER_HOST_DIR}/{REPO}"
    assert 'install -d -m 0700 -o "$3" -g "$3" "$2"' in dirs.argv[2]


def test_gh_socket_dir_does_not_reset_owner() -> None:
    from kcage.broker import ensure_dirs_op

    op = ensure_dirs_op(REPO)
    assert len(op.argv) == 6  # uid 引数が無い
    assert '[ -d "$2" ] ||' in op.argv[2]


def test_run_as_rejects_bad_uid() -> None:
    from kcage.broker import ensure_dirs_op, start_unit_op

    for bad in (0, -1, True):
        with pytest.raises(ValueError):
            start_unit_op(REPO, "aws", ("x",), "d", run_as=bad)  # type: ignore[arg-type]
        with pytest.raises(ValueError):
            ensure_dirs_op(REPO, bad)  # type: ignore[arg-type]


def test_cleanup_removes_state_and_socket_as_root() -> None:
    p = broker_plan("aws", cfg(), policy())
    assert p.stop_ops[1].argv[:3] == ("rm", "-rf", "--")
    assert not any("--uid" in a for a in p.stop_ops[1].argv)


def test_aws_plan_has_no_dummy_arn_or_sts_values() -> None:
    text = flat(broker_plan("aws", cfg(), policy()))
    for v in (DUMMY_ROLE_ARN, DUMMY_STS_KEY, DUMMY_STS_SECRET, DUMMY_STS_TOKEN):
        assert v not in text


def test_minimal_env_drops_aws_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    for k, v in {
        "AWS_PROFILE": "other",
        "AWS_ACCESS_KEY_ID": "x",
        "AWS_SECRET_ACCESS_KEY": "y",
        "AWS_SESSION_TOKEN": "z",
        "HOME": "/home/u",
        "PATH": "/usr/bin",
        "LANG": "C",
    }.items():
        monkeypatch.setenv(k, v)
    assert aws_server.minimal_env() == {"HOME": "/home/u", "PATH": "/usr/bin", "LANG": "C"}


def test_default_runner_passes_only_minimal_env(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}

    def fake_run(argv, **kw):  # type: ignore[no-untyped-def]
        seen.update(kw)
        return subprocess.CompletedProcess(argv, 0, stdout="{}", stderr="")

    monkeypatch.setenv("AWS_PROFILE", "other")
    monkeypatch.setattr(aws_server.subprocess, "run", fake_run)
    aws_server._default_runner(["aws"])
    env = seen["env"]
    assert isinstance(env, dict) and not any(k.startswith("AWS_") for k in env)


def test_role_arn_file_must_be_owned_by_self(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    f = tmp_path / "token"
    f.write_text(DUMMY_ROLE_ARN + "\n", encoding="utf-8")
    assert aws_server.read_role_arn_file(str(f)) == DUMMY_ROLE_ARN
    other = os.geteuid() + 1
    monkeypatch.setattr(aws_server.os, "geteuid", lambda: other)
    with pytest.raises(ValueError, match="所有者") as e:
        aws_server.read_role_arn_file(str(f))
    assert DUMMY_ROLE_ARN not in str(e.value)
    assert (
        aws_server.main(
            [
                "--socket",
                str(tmp_path / "s"),
                "--role-arn-file",
                str(f),
                "--session-name",
                "kcage-demo",
            ]
        )
        == 2
    )


def test_hfcache_has_no_secret_no_ops_no_devices() -> None:
    p = hfcache.plan(cfg(), policy())
    assert p.host_ops == () and p.devices == () and p.files == ()
    assert p.env == {"HF_HOME": "/var/cache/kcage/hf", "HF_HUB_DISABLE_TELEMETRY": "1"}
    assert p.routes[0].modes == ("nat", "proxy-only")
    assert "HF_TOKEN" not in p.env


# ---- aws_server ----


class Stub:
    def __init__(self, code: int = 0) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.code = code

    def __call__(self, argv):  # type: ignore[no-untyped-def]
        self.calls.append(tuple(argv))
        out = {
            "Credentials": {
                "AccessKeyId": DUMMY_STS_KEY,
                "SecretAccessKey": DUMMY_STS_SECRET,
                "SessionToken": DUMMY_STS_TOKEN,
                "Expiration": "2099-01-01T00:00:00+00:00",
            }
        }
        return self.code, json.dumps(out) if self.code == 0 else ""


class UnixConn(http.client.HTTPConnection):
    def __init__(self, path: str) -> None:
        super().__init__("localhost")
        self._path = path

    def connect(self) -> None:
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect(self._path)


@pytest.fixture
def tmp_path() -> Iterator[Path]:
    """unix ソケットのパスは 107 バイトまでなので、短い一時ディレクトリで上書きする。"""
    path = Path(tempfile.mkdtemp(prefix="bx-", dir="/tmp"))
    yield path
    shutil.rmtree(path, ignore_errors=True)


def serve(tmp_path: Path, stub: Stub, ttl: int = 3600):  # type: ignore[no-untyped-def]
    sock = str(tmp_path / "aws.sock")
    source = aws_server.CredentialSource(DUMMY_ROLE_ARN, "kcage-demo", ttl, runner=stub)
    server = aws_server.make_server(sock, source)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    return server, sock


def get(sock: str, path: str, method: str = "GET") -> tuple[int, dict]:
    conn = UnixConn(sock)
    conn.request(method, path, headers={"Authorization": "attacker", "X-Role": "other"})
    res = conn.getresponse()
    body = json.loads(res.read())
    conn.close()
    return res.status, body


def test_server_returns_container_credentials_json(tmp_path: Path) -> None:
    server, sock = serve(tmp_path, Stub())
    try:
        status, body = get(sock, "/creds")
    finally:
        server.shutdown()
        server.server_close()
    assert status == 200
    assert body == {
        "AccessKeyId": DUMMY_STS_KEY,
        "SecretAccessKey": DUMMY_STS_SECRET,
        "Token": DUMMY_STS_TOKEN,
        "Expiration": "2099-01-01T00:00:00Z",
    }
    assert (tmp_path / "aws.sock").stat().st_mode & 0o777 == 0o600


def test_server_ignores_request_parameters_and_fixes_role_and_ttl(tmp_path: Path) -> None:
    stub = Stub()
    server, sock = serve(tmp_path, stub, ttl=10)  # 最小に丸められる
    try:
        get(sock, "/creds?role=arn:aws:iam::111111111111:role/admin&ttl=43200&profile=root")
    finally:
        server.shutdown()
        server.server_close()
    (argv,) = stub.calls
    assert argv[argv.index("--role-arn") + 1] == DUMMY_ROLE_ARN
    assert argv[argv.index("--duration-seconds") + 1] == "900"
    assert "admin" not in " ".join(argv) and "111111111111" not in " ".join(argv)


def test_server_caches_credentials(tmp_path: Path) -> None:
    stub = Stub()
    server, sock = serve(tmp_path, stub)
    try:
        get(sock, "/creds")
        get(sock, "/creds")
    finally:
        server.shutdown()
        server.server_close()
    assert len(stub.calls) == 1


def test_server_returns_503_without_credentials_on_failure(tmp_path: Path) -> None:
    server, sock = serve(tmp_path, Stub(code=255))
    try:
        status, body = get(sock, "/creds")
    finally:
        server.shutdown()
        server.server_close()
    assert status == 503
    text = json.dumps(body)
    for value in (DUMMY_STS_KEY, DUMMY_STS_SECRET, DUMMY_ROLE_ARN):
        assert value not in text


def test_server_other_paths_and_methods_are_refused(tmp_path: Path) -> None:
    server, sock = serve(tmp_path, Stub())
    try:
        assert get(sock, "/latest/meta-data")[0] == 404
        assert get(sock, "/creds", method="POST")[0] == 405
        assert get(sock, "/healthz")[0] == 200
    finally:
        server.shutdown()
        server.server_close()


def test_server_logs_nothing_with_credentials(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    server, sock = serve(tmp_path, Stub())
    try:
        get(sock, "/creds")
    finally:
        server.shutdown()
        server.server_close()
    seen = capsys.readouterr()
    for value in (DUMMY_STS_KEY, DUMMY_STS_SECRET, DUMMY_STS_TOKEN):
        assert value not in seen.out + seen.err


def test_source_rejects_bad_role_and_errors_do_not_carry_values() -> None:
    with pytest.raises(ValueError) as e:
        aws_server.CredentialSource("not-an-arn-SECRETISH", "kcage-demo")
    assert "SECRETISH" not in str(e.value)

    def bad_json(argv):  # type: ignore[no-untyped-def]
        return 0, '{"Credentials": {"AccessKeyId": "' + DUMMY_STS_KEY + '"}}'

    src = aws_server.CredentialSource(DUMMY_ROLE_ARN, "kcage-demo", runner=bad_json)
    with pytest.raises(aws_server.CredsError) as e2:
        src.get()
    assert DUMMY_STS_KEY not in str(e2.value)
