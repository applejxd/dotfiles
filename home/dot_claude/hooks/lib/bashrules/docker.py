"""docker のホスト側への影響を判定する (権限昇格・ホストマウント)。"""
from __future__ import annotations

import shlex

from . import tables
from ._shared import _HOME_TOKENS, _basename, _canonical_rm_target, _segments

_DOCKER_RUN_SUBCOMMANDS = tables.as_set("docker", "docker_run_subcommands")


_DOCKER_PRIVILEGED_FLAGS = tables.as_set("docker", "docker_privileged_flags")


_DOCKER_NAMESPACE_OPTS = tables.as_set("docker", "docker_namespace_opts")


_DOCKER_MOUNT_FLAGS = tables.as_set("docker", "docker_mount_flags")


_DOCKER_FATAL_MOUNTS = tables.as_tuple("docker", "docker_fatal_mounts")


_DOCKER_CAP_DANGEROUS = tables.as_set("docker", "docker_cap_dangerous")


def _docker_mount_source(token: str) -> str | None:
    """`-v src:dst` / `--mount type=bind,source=src,...` の src を返す。"""
    if "=" in token and ("source=" in token or "src=" in token or
                         token.startswith("type=")):
        for part in token.split(","):
            key, _, value = part.partition("=")
            if key.strip() in {"source", "src"}:
                return value.strip()
        return None
    source = token.split(":", 1)[0]
    return source or None


def _docker_run_tokens(segment: str) -> list[str] | None:
    """`docker run` / `docker container create` の引数列を返す。該当しなければ None。"""
    try:
        tokens = shlex.split(segment)
    except ValueError:
        tokens = segment.split()
    if not tokens or _basename(tokens[0].strip("'\"")) != "docker":
        return None
    subcommands = [t for t in tokens[1:] if not t.startswith("-")]
    if not (_DOCKER_RUN_SUBCOMMANDS & set(subcommands[:2])):
        return None
    return [t.strip("'\"") for t in tokens[1:]]


def _docker_opt_value(rest: list[str], index: int) -> tuple[str, str]:
    """`--net=host` と `--net host` の両方から (キー, 値) を取り出す。"""
    key, sep, value = rest[index].partition("=")
    if sep:
        return key, value
    following = rest[index + 1] if index + 1 < len(rest) else ""
    return key, ("" if following.startswith("-") else following)


def check_docker_host_escape(cmd: str) -> str | None:
    """`docker run` でホストの root 相当を得られる形を検出する。

    `sudo` を deny している以上、コンテナ経由で同じことができる形も同じ扱いに
    する。`--privileged`、ホストのルートや `/etc` のマウント、docker socket の
    マウントは承認の余地が無い。

    分離を弱めるだけの `--network host` などは `check_docker_isolation` が ask
    にする。オプションの順序と `=` の有無に依存しないようトークンを走査する。
    """
    for segment in _segments(cmd):
        rest = _docker_run_tokens(segment)
        if rest is None:
            continue
        for index, token in enumerate(rest):
            if token in _DOCKER_PRIVILEGED_FLAGS:
                return (
                    f"`docker {token}` はコンテナに全権限を与える操作です。\n"
                    "コンテナ経由の権限昇格に繋がるため許可されていません。"
                )
            key, value = _docker_opt_value(rest, index)
            if key == "--cap-add" and value.upper() in _DOCKER_CAP_DANGEROUS:
                return (
                    f"`docker --cap-add {value}` は特権相当の capability です。\n"
                    "コンテナ経由の権限昇格に繋がるため許可されていません。"
                )
            if token in _DOCKER_MOUNT_FLAGS or key in _DOCKER_MOUNT_FLAGS:
                mount = value if key in _DOCKER_MOUNT_FLAGS else ""
                if not mount and token in _DOCKER_MOUNT_FLAGS:
                    mount = rest[index + 1] if index + 1 < len(rest) else ""
                source = _docker_mount_source(mount) if mount else None
                canonical = _canonical_rm_target(source) if source else None
                if canonical is None:
                    continue
                if canonical in _DOCKER_FATAL_MOUNTS or canonical in _HOME_TOKENS:
                    return (
                        f"`docker` がホストの `{source}` をコンテナへマウント"
                        "しようとしています。\n"
                        "ホストのファイルを直接書き換えられるため許可されていません。"
                    )
    return None


def check_docker_isolation(cmd: str) -> str | None:
    """`docker run --network host` のように分離を弱める形を検出する。

    root 相当ではないので deny にはしないが、ホストのネットワークや
    プロセス空間へ届くので確認を挟む。
    """
    for segment in _segments(cmd):
        rest = _docker_run_tokens(segment)
        if rest is None:
            continue
        for index in range(len(rest)):
            key, value = _docker_opt_value(rest, index)
            if key in _DOCKER_NAMESPACE_OPTS and value == "host":
                return (
                    f"`docker {key} host` はホストの名前空間をコンテナと"
                    "共有します。\n"
                    f"実行しようとしているコマンド: {segment.strip()[:200]}\n"
                    "分離が弱まるため、内容を確認して問題なければ承認してください。"
                )
    return None
