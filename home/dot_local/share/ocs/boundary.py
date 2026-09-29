"""境界 (Fence の設定) の組み立てと、プロジェクトごとの追加。

see docs/spec/opencode-sandbox.md#境界の中身
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from . import backup
from .common import HOME, die

RULES = HOME / ".config/opencode/guide-plugin/rules.json"
REQUEST_REL = ".opencode/sandbox.toml"
REQUEST_KEYS = ("read", "write", "network_allow")


def load_boundary() -> dict:
    if not RULES.is_file():
        die(f"{RULES} が無い", "chezmoi apply で生成する")
    try:
        rules = json.loads(RULES.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        die(f"{RULES} を読めない: {e}")
    sandbox = rules.get("sandbox") if isinstance(rules, dict) else None
    if not sandbox:
        die(
            "境界の設定が出力されていない",
            "[opencode.sandbox] が enabled=false。chezmoi apply で生成する",
        )
    if not isinstance(sandbox, dict):
        die(f"{RULES} の sandbox が object でない")
    for key in ("runtime_path", "base", "config_dir"):
        if not sandbox.get(key):
            die(f"境界の設定に {key} が無い")
    if not isinstance(sandbox["base"], dict):
        die(f"{RULES} の sandbox.base が object でない")
    return sandbox


def project_extras(request: dict | None) -> dict:
    """``.opencode/sandbox.toml`` で足す分。宣言が無ければ追加はゼロ。"""
    if request is None:
        return {"read": [], "write": [], "network_allow": []}
    return request["extras"]


def git_common_dir(workspace: Path) -> Path | None:
    """linked worktree のとき、共有 ``.git`` の実体を返す。

    ★ここは境界の外で走る。``/usr/bin/git`` を絶対パスで呼び、利用者の ``GIT_*`` を落とす
      (``GIT_DIR`` を通すと、別のリポジトリが書けるようになる)。
    """
    done = subprocess.run(
        ["/usr/bin/git", "-C", str(workspace), "rev-parse", "--path-format=absolute",
         "--git-common-dir"],
        capture_output=True,
        text=True,
        check=False,
        env=backup.git_env(),
    )
    if done.returncode != 0:
        return None
    common = Path(done.stdout.strip())
    if not common.is_dir():
        return None
    # 通常のリポジトリ (共有 .git が起動ディレクトリの中) なら足すものは無い
    if common == workspace or workspace in common.parents:
        return None
    return common


def _real(path: Path) -> Path:
    """在る所まで symlink を解いた実体。"""
    try:
        return path.resolve()
    except (OSError, RuntimeError):  # symlink の循環など
        return path


def _normalized(raw: str) -> list[Path]:
    """書いたままの形と実体の両方。``workspace`` は実体なので、symlink 越しでも比べられる。"""
    path = Path(os.path.normpath(Path(raw).expanduser()))
    return _uniq_paths([path, _real(path)])


def reject_unsafe_workspace(sandbox: dict, workspace: Path) -> None:
    """書き込みを許すと広すぎる起動ディレクトリを拒否する。

    起動ディレクトリは無条件に書ける。``unsafe_workspace`` の項目そのものか、その祖先で
    起動すると、ホーム全体や ``/tmp``・``/mnt`` が書けてしまう。子孫での起動は許す。
    ``workspace`` は実体パスで渡すこと。
    """
    for raw in sandbox["base"].get("unsafe_workspace", []):
        for target in _normalized(raw):
            if target.is_relative_to(workspace):
                die(
                    f"広すぎる場所で起動しようとした: {workspace}",
                    f"ここで起動すると {target} 以下が書き込み可能になる。"
                    "作業対象のディレクトリへ cd してから起動する。",
                )


def _overlaps(a: Path, b: Path) -> bool:
    return a.is_relative_to(b) or b.is_relative_to(a)


def reject_control_dirs(sandbox: dict, workspace: Path, request: dict | None = None) -> None:
    """配備済みの制御ファイルの置き場と重なる起動ディレクトリと ``write`` を拒否する。

    そのもの・祖先・子孫のどれで起動しても置き場の中が書けてしまう。
    ``workspace`` は実体パスで渡すこと。
    see docs/spec/opencode-sandbox.md#起動ディレクトリの制限
    """
    targets = _uniq_paths(
        [t for raw in sandbox["base"].get("control_dirs", []) for t in _normalized(raw)]
    )
    for target in targets:
        if _overlaps(workspace, target):
            die(
                f"ocs の制御ファイルの置き場と重なる場所で起動しようとした: {workspace}",
                f"ここで起動すると {target} (次回の境界を決めるファイル) が書き込み可能になる。"
                "ここの編集は ocs を使わずに行う。",
            )
    for raw in project_extras(request)["write"]:
        for path in _normalized(raw):
            for target in targets:
                if _overlaps(path, target):
                    die(
                        f"ocs の制御ファイルの置き場と重なる場所を書ける場所に足そうとした: {raw}",
                        f"{target} は書き込み可能にできない。{request['path']} の write から外し、"
                        "ここの編集は ocs を使わずに行う。",
                    )


def protected_candidates(sandbox: dict, workspace: Path) -> list[Path]:
    """保護対象を、起動ディレクトリとリポジトリの根の両方を基準に解決する (実体パスで返す)。

    see docs/spec/opencode-sandbox.md#保護対象denywrite
    """
    roots = [workspace]
    top = backup.git_toplevel(workspace)
    if top is not None:
        roots.append(top.resolve())
    rels = sandbox["base"].get("protected", [])
    return _uniq_paths([_real(root / rel) for root in roots for rel in rels])


def reject_protected_workspace(
    sandbox: dict, workspace: Path, request: dict | None = None
) -> None:
    """保護対象の中での起動と、保護対象の中を ``write`` に足す宣言を拒否する。

    see docs/spec/opencode-sandbox.md#保護対象denywrite
    """
    targets = protected_candidates(sandbox, workspace)
    for target in targets:
        if workspace.is_relative_to(target):
            die(
                f"保護対象の中で起動しようとした: {workspace}",
                f"ここで起動すると {target} が書き込み可能になる。"
                "ここの編集は ocs を使わずに行う。",
            )
    for raw in project_extras(request)["write"]:
        real = _real(Path(raw))
        for target in targets:
            if real.is_relative_to(target):
                die(
                    f"保護対象の中を書ける場所に足そうとした: {raw}",
                    f"{target} は書き込みから外せない。{request['path']} の write から外し、"
                    "ここの編集は ocs を使わずに行う。",
                )


def _within(path: str, roots: list[str]) -> bool:
    target = Path(path)
    return any(target == Path(r) or Path(r) in target.parents for r in roots)


def _existing(paths: list[str]) -> list[str]:
    return [p for p in _uniq(paths) if Path(p).exists()]


def prepare_protected(paths: list[str]) -> list[str]:
    """``denyWrite`` へ渡す保護対象を返す。

    ★Fence の ``denyWrite`` は**まだ無いパスに効かない**。無い保護対象は、親が在れば
      空のディレクトリとして先に作ってから塞ぐ。親が無いもの (別のリポジトリの
      ``home/dot_config/agents`` など) は、その起動ディレクトリでは守る意味が無いので落とす。
    """
    out = []
    for raw in _uniq(paths):
        path = Path(raw)
        if not path.exists() and not path.is_symlink() and path.parent.is_dir():
            try:
                path.mkdir()
            except OSError as e:
                die(f"保護対象を用意できない: {path} ({e})")
        if path.exists():
            out.append(raw)
    return out


def build_boundary(
    sandbox: dict, workspace: Path, request: dict | None = None, data_dir: Path | None = None
) -> dict:
    """起動ディレクトリを書き込み可能領域として Fence の設定を組み立てる。

    読み取りは既定で拒否し (``defaultDenyRead``)、道具の置き場・作業用の親ディレクトリ・
    書き込み先だけを開ける。無いパスは渡さない。
    """
    base = sandbox["base"]
    extras = project_extras(request)
    write = [str(workspace), *base.get("write", []), *extras.get("write", [])]
    if data_dir is not None:
        write.append(str(data_dir))
    extra_protected = []
    common = git_common_dir(workspace)
    if common:
        # commit に共有 .git への書き込みが要る。hooks と config はホストで動くので塞ぐ。
        write.append(str(common))
        extra_protected = [str(common / "hooks"), str(common / "config")]
    read = [*base.get("read", []), *base.get("work_read", []), *extras.get("read", [])]
    allow_write = _existing(write)
    allow_read = _existing([str(workspace), *read])
    opened = [*allow_read, *allow_write]
    # 書ける場所の外にある保護対象は元から書けないので渡さない (作りもしない)。
    # 書ける場所も実体で比べる (symlink 越しに許した場所の中の保護対象を落とさない)
    write_real = [str(_real(Path(p))) for p in allow_write]
    protected = [
        *(str(p) for p in protected_candidates(sandbox, workspace) if _within(str(p), write_real)),
        *extra_protected,
    ]
    # ホーム配下の秘密は開けた場所の内側にあるときだけ隠す (それ以外は元から見えない)。
    # ホームの外 (/run/user など) は Fence が既定で見せるので、在れば隠す。
    # 実体でも比べ、実体で渡す (ホームが symlink だと起動ディレクトリは実体になる)
    opened_real = [str(_real(Path(p))) for p in opened]
    home_real = [str(_real(HOME))]
    deny_read = _uniq([
        str(_real(Path(p))) for p in _existing(base.get("deny_read", []))
        if not _within(p, [str(HOME)])
        or not _within(str(_real(Path(p))), home_real)
        or _within(p, opened)
        or _within(str(_real(Path(p))), opened_real)
    ])
    network = dict(base["network"])
    if extras.get("network_allow"):
        network["allowedDomains"] = _uniq(
            [*network.get("allowedDomains", []), *extras["network_allow"]]
        )
    return {
        "network": network,
        "filesystem": {
            "defaultDenyRead": True,
            "allowRead": allow_read,
            "allowWrite": allow_write,
            "denyRead": deny_read,
            "denyWrite": prepare_protected(protected),
        },
        # TUI の再描画 (リサイズ) に要る
        "allowPty": True,
    }


def _uniq(values: list[str]) -> list[str]:
    seen: dict[str, None] = {}
    for value in values:
        seen.setdefault(value, None)
    return list(seen)


def _uniq_paths(values: list[Path]) -> list[Path]:
    return [Path(v) for v in _uniq([str(v) for v in values])]


def _resolve_requested(value: str, workspace: Path) -> str:
    """``~`` を展開し、相対パスは起動ディレクトリ基準にする。"""
    expanded = Path(value).expanduser()
    if not expanded.is_absolute():
        expanded = workspace / expanded
    return os.path.normpath(expanded)


def read_request(workspace: Path) -> dict | None:
    """``.opencode/sandbox.toml`` を読む。無ければ ``None``。"""
    path = workspace / REQUEST_REL
    if not path.is_file():
        return None
    try:
        import tomllib
    except ModuleNotFoundError:  # pragma: no cover - 3.11 未満
        die(f"{path} を読めない (tomllib が無い)", "Python 3.11 以降が要る")
    try:
        data = tomllib.loads(path.read_bytes().decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        die(f"{path} を解釈できない: {exc}")
    unknown = sorted(set(data) - set(REQUEST_KEYS))
    if unknown:
        die(f"{path} に知らない項目がある: {', '.join(unknown)}")
    extras: dict[str, list[str]] = {}
    for key in REQUEST_KEYS:
        values = data.get(key, [])
        if not isinstance(values, list) or any(not isinstance(v, str) for v in values):
            die(f"{path} の {key} は文字列の配列でなければならない")
        extras[key] = [
            v if key == "network_allow" else _resolve_requested(v, workspace)
            for v in values
        ]
    if not any(extras.values()):
        return None
    return {"path": path, "extras": extras}


def describe_request(request: dict) -> str:
    """起動時に表示する、``.opencode/sandbox.toml`` で足した分。"""
    labels = {"read": "読める", "write": "書ける", "network_allow": "通信"}
    lines = [f"ocs: {request['path']} の追加を適用する"]
    for key, label in labels.items():
        values = request["extras"][key]
        if values:
            lines.append(f"  {label}: {', '.join(values)}")
    return "\n".join(lines)


def announce_request(request: dict | None) -> None:
    if request is not None:
        print(describe_request(request), file=sys.stderr)
