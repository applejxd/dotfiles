"""箱の認証ブローカーの計画。標準ライブラリだけ。計画の関数は純粋（副作用なし・秘密を読まない）。

`plan(kind, cfg, policy)` が kind ごとの planner（gh・aws・copilot・hf-cache）へ振り分ける。
実行（Op の実行・秘密の解決）は W1a の root_helper の薄い層が行う。

共通の規約（固定値は model.py）:
- ホスト側のソケット: <BROKER_HOST_DIR>/<repo-id>/<kind>.sock（root 所有。接続先は常にこの下で、呼び出し側は指定できない）
- 箱の中のソケット: <BOX_SOCK_DIR>/<kind>.sock（箱の uid だけが使える）
- つなぎは proxy デバイス（bind=instance）。ソケットが箱ごとに別なので、入場トークンは使わない
- 秘密は SecretRef で参照し、Op の stdin_secret でだけ渡す（argv・環境変数・計画の表示・箱のファイルに出さない。C1）

実行順の約束（executor への申し送り）: BrokerPlan の host_ops は先頭から順に実行し、files は host_ops の
前に置く（host の FilePut は使わず、ホスト側の設定は argv か prepare Op で渡すので順序に依存しない）。
see docs/spec/sandbox/broker.md
"""

from __future__ import annotations

import re
from collections.abc import Callable

from kcage import model

KNOWN_KINDS: tuple[str, ...] = ("gh", "aws", "copilot", "hf-cache")

_REPO_ID = re.compile(r"[a-z0-9][a-z0-9-]{0,40}")


def check_repo_id(repo_id: str) -> str:
    """repo-id はソケットのパスと unit 名に入るので、安全な文字だけを通す。"""
    if not _REPO_ID.fullmatch(repo_id):
        raise ValueError("repo-id がパスに使えない形（英小文字・数字・ハイフンだけ）")
    return repo_id


def host_dir(repo_id: str) -> str:
    return f"{model.BROKER_HOST_DIR}/{check_repo_id(repo_id)}"


def host_sock(repo_id: str, kind: str) -> str:
    """ホスト側のブローカーのソケット。"""
    return f"{host_dir(repo_id)}/{kind}.sock"


def state_dir(repo_id: str, kind: str) -> str:
    """ホスト側の状態ディレクトリ（root 専用 0700。長期トークン・SDS を置く）。箱からは見えない。"""
    return f"{host_dir(repo_id)}/.state-{kind}"


def box_sock(kind: str) -> str:
    """箱の中のソケット。"""
    return f"{model.BOX_SOCK_DIR}/{kind}.sock"


def unit_name(repo_id: str, kind: str, role: str = "") -> str:
    suffix = f"-{role}" if role else ""
    return f"kcage-broker-{check_repo_id(repo_id)}-{kind}{suffix}.service"


def unix_proxy_device(cfg: model.BoxConfig, kind: str) -> model.DeviceSpec:
    """箱の中の unix ソケット → ホストのブローカーの unix ソケット。接続先は固定生成。

    箱の中の待受は、箱の uid だけが使える最小のモード（0600）にする。
    """
    return model.DeviceSpec(
        name=f"broker-{kind}",
        type="proxy",
        config={
            "listen": f"unix:{box_sock(kind)}",
            "connect": f"unix:{host_sock(cfg.repo_id, kind)}",
            "bind": "instance",
            "uid": str(cfg.uid),
            "gid": str(cfg.uid),
            "mode": "0600",
        },
    )


def loopback_proxy_device(cfg: model.BoxConfig, kind: str, port: int) -> model.DeviceSpec:
    """箱の中の loopback の TCP → ホストのブローカーの unix ソケット（SDK が HTTP を loopback にだけ許すため）。"""
    return model.DeviceSpec(
        name=f"broker-{kind}",
        type="proxy",
        config={
            "listen": f"tcp:{model.LOOPBACK}:{port}",
            "connect": f"unix:{host_sock(cfg.repo_id, kind)}",
            "bind": "instance",
        },
    )


def require_secret(policy: model.RepoPolicy, name: str) -> model.SecretRef:
    ref = policy.secrets.get(name)
    if ref is None:
        raise ValueError(f"許可表の secrets に {name!r} の出どころが無い")
    return ref


def _check_uid(uid: int) -> int:
    """シェルへ埋め込む uid は、1 以上の整数だけ（root への付け替えや文字列の混入を防ぐ）。"""
    if isinstance(uid, bool) or not isinstance(uid, int) or uid < 1:
        raise ValueError("uid が不正（1 以上の整数）")
    return uid


def ensure_dirs_op(repo_id: str, owner_uid: int | None = None) -> model.Op:
    """ブローカーのソケットの置き場を作る。

    親（BROKER_HOST_DIR）は root 所有 0711。<repo-id> ディレクトリは、owner_uid があればその uid 所有 0700
    （aws_server が uid の権限でソケットを作る。root の Envoy・forkproxy は 0700 でも入れる）。
    owner_uid が無いとき（gh・copilot）は、無ければ root 所有 0711 で作り、既にあれば所有者を変えない
    （aws が先に作った uid 所有のディレクトリを root へ戻さない）。
    """
    parent = model.BROKER_HOST_DIR
    d = host_dir(repo_id)
    script = (
        'set -eu; install -d -m 0711 -o root -g root "$1"; '
        'if [ "$#" -ge 3 ]; then install -d -m 0700 -o "$3" -g "$3" "$2"; '
        'else [ -d "$2" ] || install -d -m 0711 -o root -g root "$2"; fi'
    )
    argv = ["sh", "-c", script, "kcage-dirs", parent, d]
    if owner_uid is not None:
        argv.append(str(_check_uid(owner_uid)))
    desc = (
        "ブローカーのソケットのディレクトリを作る（uid 所有 0700）"
        if owner_uid is not None
        else "ブローカーのソケットのディレクトリを作る（無ければ root 所有 0711）"
    )
    return model.Op("host", tuple(argv), desc)


def prepare_op(
    repo_id: str,
    kind: str,
    ref: model.SecretRef,
    extra_files: dict[str, str] | None = None,
    owner_uid: int | None = None,
) -> model.Op:
    """秘密を、root 専用 0600 のファイル <state_dir>/token へ書く。値は stdin だけで渡す。

    extra_files（名前 → 内容。秘密を含まない設定だけ）も、同じ 0700 のディレクトリへ 0600 で置く。
    改行・CR は取り除く（SDS・Envoy が値をそのまま読むため）。
    owner_uid があれば、ディレクトリとファイルをその uid 所有にする（0700 / 0600。aws_server が uid で読む）。
    """
    d = state_dir(repo_id, kind)
    extras = extra_files or {}
    script = 'set -eu; umask 077; d=$1; install -d -m 0700 "$d"; tr -d "\\r\\n" > "$d/token"'
    argv: list[str] = ["sh", "-c", script, "kcage-prepare", d]
    for i, (name, body) in enumerate(sorted(extras.items()), start=2):
        if "/" in name or name.startswith("."):
            raise ValueError("extra_files の名前が不正")
        script += f'; printf %s "${i}" > "$d/{name}"'
        argv.append(body)
    if owner_uid is not None:
        uid = _check_uid(owner_uid)
        script += f'; chown -R -- {uid}:{uid} "$d"'
    argv[2] = script
    return model.Op(
        "host",
        tuple(argv),
        f"秘密 {ref.name} を root 専用の一時ファイルへ書く（標準入力。argv・ログに出さない）",
        stdin_secret=ref,
    )


def ensure_command_op(command: str, hint: str) -> model.Op:
    """必要な実行ファイルが無ければ、分かりやすく失敗する。"""
    return model.Op(
        "host",
        ("sh", "-c", f'command -v {command} >/dev/null 2>&1 || {{ echo "{hint}" >&2; exit 1; }}'),
        f"{command} が使えるか確かめる",
    )


def start_unit_op(
    repo_id: str,
    kind: str,
    argv: tuple[str, ...],
    desc: str,
    role: str = "",
    run_as: int | None = None,
) -> model.Op:
    """systemd の一時 unit として常駐させる（停止は stop_unit_op。再起動の復活はしない）。

    run_as があれば、その uid・gid で動かす（HOME は systemd がそのユーザーのものにする）。
    """
    who: tuple[str, ...] = ()
    if run_as is not None:
        uid = _check_uid(run_as)
        who = (f"--uid={uid}", f"--gid={uid}")
    return model.Op(
        "host",
        (
            "systemd-run",
            "--quiet",
            "--collect",
            f"--unit={unit_name(repo_id, kind, role)}",
            *who,
            *argv,
        ),
        desc,
    )


def stop_unit_op(repo_id: str, kind: str, role: str = "") -> model.Op:
    return model.Op(
        "host",
        ("systemctl", "stop", unit_name(repo_id, kind, role)),
        f"{kind} の常駐を止める（無ければ何もしない）",
        check=False,
    )


def cleanup_op(repo_id: str, kind: str) -> model.Op:
    """ソケットと状態ディレクトリ（長期トークンの一時ファイル）を消す。"""
    return model.Op(
        "host",
        ("rm", "-rf", "--", state_dir(repo_id, kind), host_sock(repo_id, kind)),
        f"{kind} のソケットと状態ディレクトリを消す",
        check=False,
    )


def curl_unix_op(sock: str, path: str, desc: str, host: str = "kcage-broker.invalid") -> model.Op:
    """ソケットが応答するかの確認（readiness）。"""
    return model.Op(
        "host",
        (
            "curl",
            "--silent",
            "--fail",
            "--max-time",
            "3",
            "--retry",
            "10",
            "--retry-connrefused",
            "--retry-delay",
            "1",
            "--unix-socket",
            sock,
            "--output",
            "/dev/null",
            f"http://{host}{path}",
        ),
        desc,
    )


def _planners() -> dict[str, Callable[[model.BoxConfig, model.RepoPolicy], model.BrokerPlan]]:
    # 循環 import を避けるため、遅延で読む
    from kcage.broker import aws, copilot, gh, hfcache

    return {"gh": gh.plan, "aws": aws.plan, "copilot": copilot.plan, "hf-cache": hfcache.plan}


def plan(
    kind: model.BrokerKind, cfg: model.BoxConfig, policy: model.RepoPolicy
) -> model.BrokerPlan:
    """kind の planner へ振り分ける。未知の kind・許可表にないブローカーは拒否する（C13）。"""
    planners = _planners()
    if kind not in planners:
        raise ValueError(f"未知のブローカー: {kind!r}")
    if kind not in policy.brokers:
        raise ValueError(f"許可表がブローカー {kind!r} を許していない")
    if policy.id != cfg.repo_id:
        raise ValueError("許可表と設定のリポジトリが一致しない")
    return planners[kind](cfg, policy)
