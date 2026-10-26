"""Bedrock ブローカーの実機確認スクリプト (scripts/agents/bedrock_probe.py) の試験。

AWS へはつながない。Envoy の設定が通ること、偽の上流で署名・ストリーミング・鍵ファイルの更新が
確かめられること (selftest) を、Envoy があるときだけ試す。
see docs/research/agents/bedrock-broker-field-test.md
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest
from agents_common import ROOT

SCRIPT = ROOT / "scripts" / "agents" / "bedrock_probe.py"


def _load():
    spec = importlib.util.spec_from_file_location("bedrock_probe_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    saved, sys.dont_write_bytecode = sys.dont_write_bytecode, True
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = saved
    return module


probe = _load()


def _envoy() -> str | None:
    try:
        return probe.broker.find_envoy()
    except Exception:
        return None


needs_envoy = pytest.mark.skipif(_envoy() is None, reason="envoy が無い")


def test_model_path_encodes_the_colon_like_the_sdk_unless_asked_not_to():
    assert probe.model_path("a.b-v1:0", "converse") == "/model/a.b-v1%3A0/converse"
    assert probe.model_path("a.b-v1:0", "converse-stream", raw_colon=True) == (
        "/model/a.b-v1:0/converse-stream"
    )


def test_read_credentials_from_a_profile_without_printing_values(tmp_path, monkeypatch, capsys):
    path = tmp_path / "credentials"
    path.write_text(
        "[probe]\naws_access_key_id = AKIAEXAMPLE\naws_secret_access_key = s3cr3t\n"
        "[other]\naws_access_key_id = X\n",
        encoding="utf-8",
    )
    for name in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", str(path))
    assert probe.read_credentials("probe") == ("AKIAEXAMPLE", "s3cr3t", "")
    assert probe.read_credentials("other") is None  # 秘密鍵が無い
    assert probe.read_credentials("missing") is None
    assert capsys.readouterr().out == ""


def test_environment_variables_win_over_the_file(tmp_path, monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIAENV")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "envsecret")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "tok")
    assert probe.read_credentials("anything") == ("AKIAENV", "envsecret", "tok")


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("", "none"),
        ("http://user:pw@proxy.example:8080", "http"),
        ("https://proxy.example:8080", "https"),
        ("socks5h://127.0.0.1:1080", "socks5h"),
        ("proxy.example:8080", "http"),
        ("ftp://proxy.example", "other"),
    ],
)
def test_proxy_kind_reports_only_the_scheme(value, expected, monkeypatch):
    for name in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"):
        monkeypatch.delenv(name, raising=False)
    if value:
        monkeypatch.setenv("HTTPS_PROXY", value)
    assert probe.proxy_kind() == expected


def test_credentials_file_is_written_atomically_with_owner_only_permissions(tmp_path):
    path = tmp_path / "credentials"
    probe.write_credentials(path, "AKIA1", "sec1", "tok1")
    assert path.stat().st_mode & 0o777 == 0o600
    probe.write_credentials(path, "AKIA2", "sec2")
    text = path.read_text(encoding="utf-8")
    assert "AKIA2" in text and "tok1" not in text
    assert not list(tmp_path.glob("*.tmp"))


@needs_envoy
@pytest.mark.parametrize("bridge_port", [None, 18555], ids=["direct", "bridge"])
def test_real_tls_config_is_accepted_by_envoy(tmp_path, bridge_port):
    cred = tmp_path / "credentials"
    probe.write_credentials(cred, "AKIATEST", "secret")
    config = probe.build_config(
        18998,
        "us-east-1",
        cred,
        "bedrock-runtime.us-east-1.amazonaws.com",
        ca_file=probe.broker.find_ca_file(),
        bridge_port=bridge_port,
    )
    path = tmp_path / "envoy.json"
    path.write_text(config, encoding="utf-8")
    done = subprocess.run(
        [_envoy(), "--mode", "validate", "-c", str(path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )
    assert done.returncode == 0, (done.stdout + done.stderr)[-500:]


@needs_envoy
def test_selftest_signing_streaming_reload_and_large_request_pass():
    done = subprocess.run(
        [sys.executable, "-B", str(SCRIPT), "selftest"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=180,
        check=False,
    )
    assert done.returncode == 0, done.stdout[-800:] + done.stderr[-400:]
    assert "報告コード: BP1----11111---" in done.stdout


def test_the_script_names_no_organization_or_secrets():
    text = Path(SCRIPT).read_text(encoding="utf-8")
    assert "AKIA" not in text.replace("AKIAPROBEINVALID0000", "").replace("AKIASELFTEST000000", "")
