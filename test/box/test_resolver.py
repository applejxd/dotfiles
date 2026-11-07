"""scripts/box/resolver.py の試験。秘密の参照の解決（file・command・prompt）と、値を出さないこと。"""

from __future__ import annotations

import os
import stat
import subprocess
from types import SimpleNamespace

import pytest
from box import model, resolver

# ダミーの値（gitleaks に誤検出されない形）
VALUE = "dummy-value-" + "0123456789"


def _st(mode: int = 0o100600, uid: int = 1000, size: int = 20) -> os.stat_result:
    return os.stat_result((mode, 0, 0, 1, uid, 1000, size, 0, 0, 0))


def _env(
    *, st=None, data: bytes = (VALUE + "\n").encode(), run=None, prompt=None, lstat_error=None
):
    def lstat(path):
        if lstat_error:
            raise lstat_error
        return st or _st(size=len(data))

    def read(path, limit):
        return data[: limit + 1]

    return resolver.Env(
        lstat=lstat,
        read=read,
        run=run or (lambda argv, **kw: subprocess.CompletedProcess(argv, 0, stdout=data)),
        prompt=prompt or (lambda text: VALUE),
        getpw=lambda uid: SimpleNamespace(pw_gid=1000, pw_dir="/home/u"),
    )


def _file(path: str = "/home/u/tok") -> model.SecretRef:
    return model.SecretRef("t", "file", path=path)


def test_file_ok() -> None:
    assert resolver.resolve(_file(), caller_uid=1000, env=_env()) == VALUE


@pytest.mark.parametrize(
    ("st", "why"),
    [
        (_st(mode=0o100644), "グループ・他人"),
        (_st(mode=0o120600), "symlink"),
        (_st(mode=0o040700), "通常ファイル"),
        (_st(uid=1234), "所有者"),
        (_st(size=5000), "大きすぎる"),
    ],
)
def test_file_は不正な状態を拒否する(st, why) -> None:
    with pytest.raises(resolver.SecretError) as e:
        resolver.resolve(_file(), caller_uid=1000, env=_env(st=st))
    assert VALUE not in str(e.value)


def test_file_は相対パスと親ディレクトリ参照を拒否する() -> None:
    for p in ("tok", "/home/u/../etc/x"):
        with pytest.raises(resolver.SecretError):
            resolver.resolve(_file(p), caller_uid=1000, env=_env())


def test_file_は_root_所有を許す() -> None:
    assert resolver.resolve(_file(), caller_uid=1000, env=_env(st=_st(uid=0))) == VALUE


def test_file_の読めないエラーに値が出ない() -> None:
    with pytest.raises(resolver.SecretError) as e:
        resolver.resolve(
            _file(), caller_uid=1000, env=_env(lstat_error=FileNotFoundError("/home/u/tok"))
        )
    assert "/home/u/tok" not in str(e.value)


@pytest.mark.parametrize(
    "bad",
    [b"", b"\n", b"has space\n", b"two\nlines\n", b"\xe3\x81\x82", b"x" * 256, b"tab\tx"],
)
def test_値の検査(bad: bytes) -> None:
    with pytest.raises(resolver.SecretError):
        resolver.resolve(_file(), caller_uid=1000, env=_env(data=bad))


def test_command_は呼び出し元の権限・最小環境・シェルなしで実行する() -> None:
    seen = {}

    def run(argv, **kw):
        seen.update(argv=argv, **kw)
        return subprocess.CompletedProcess(argv, 0, stdout=(VALUE + "\n").encode())

    ref = model.SecretRef("t", "command", argv=("gh", "auth", "token"))
    assert resolver.resolve(ref, caller_uid=1000, env=_env(run=run)) == VALUE
    assert seen["argv"] == ["gh", "auth", "token"]
    assert seen["shell"] is False
    assert seen["user"] == 1000 and seen["group"] == 1000
    assert seen["env"]["HOME"] == "/home/u"
    assert set(seen["env"]) == {"PATH", "HOME"}
    assert seen["stdin"] == subprocess.DEVNULL and seen["stderr"] == subprocess.DEVNULL
    assert seen["timeout"] == 30


def test_command_の失敗・時間切れ・大きすぎる出力() -> None:
    ref = model.SecretRef("t", "command", argv=("x",))
    with pytest.raises(resolver.SecretError):
        resolver.resolve(
            ref,
            caller_uid=1000,
            env=_env(run=lambda a, **k: subprocess.CompletedProcess(a, 1, stdout=VALUE.encode())),
        )

    def timeout(a, **k):
        raise subprocess.TimeoutExpired(a, 30)

    with pytest.raises(resolver.SecretError):
        resolver.resolve(ref, caller_uid=1000, env=_env(run=timeout))
    with pytest.raises(resolver.SecretError):
        resolver.resolve(ref, caller_uid=1000, env=_env(data=b"x" * 5000))


def test_command_の空_argv_は拒否する() -> None:
    with pytest.raises(resolver.SecretError):
        resolver.resolve(model.SecretRef("t", "command", argv=()), caller_uid=1000, env=_env())


def test_prompt() -> None:
    ref = model.SecretRef("t", "prompt")
    assert resolver.resolve(ref, env=_env(prompt=lambda t: VALUE)) == VALUE
    with pytest.raises(resolver.SecretError):
        resolver.resolve(ref, env=_env(prompt=lambda t: "has space"))

    def eof(t):
        raise EOFError

    with pytest.raises(resolver.SecretError):
        resolver.resolve(ref, env=_env(prompt=eof))


def test_モードは_0600_だけ許す() -> None:
    assert stat.S_IMODE(_st().st_mode) == 0o600
