"""境界 (Fence の設定) の組み立てと、プロジェクトごとの追加。

see docs/spec/sandbox/opencode-sandbox.md#境界の中身
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

from . import backup
from .common import HOME, die

RULES = HOME / ".config/opencode/guide-plugin/rules.json"
REQUEST_REL = ".opencode/sandbox.toml"
REQUEST_KEYS = ("read", "write", "network_allow", "devices")
EXTRA_READ_ENV = "PIS_EXTRA_READ"
EXTRA_DEVICES_ENV = "PIS_EXTRA_DEVICES"
# devices に足せる /dev/ 直下の名前 (CUDA の計算に要るものだけ)。これ以外は拒否
# see docs/spec/sandbox/opencode-sandbox.md#プロジェクトごとの追加
ALLOWED_DEVICE_NAMES = (
    "dxg",
    "nvidiactl",
    "nvidia-uvm",
    "nvidia-uvm-tools",
)
# 番号付きのノード (nvidia0・nvidia12 など)。re.fullmatch で照合する
ALLOWED_DEVICE_PATTERN = r"nvidia[0-9]+"
# エラーのヒントに出す許可の一覧
ALLOWED_DEVICES = (*ALLOWED_DEVICE_NAMES, ALLOWED_DEVICE_PATTERN)


def load_boundary(
    rules_path: Path | None = None, required: tuple[str, ...] = ("config_dir",)
) -> dict:
    """境界の素材 (``rules.json`` の ``sandbox``) を読む。pi は ``config_dir`` を持たない。

    既定の ``RULES`` は呼び出しのときに引く (定義時に固定しない)。
    """
    rules_path = rules_path if rules_path is not None else RULES
    if not rules_path.is_file():
        die(f"{rules_path} が無い", "chezmoi apply で生成する")
    try:
        rules = json.loads(rules_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        die(f"{rules_path} を読めない: {e}")
    sandbox = rules.get("sandbox") if isinstance(rules, dict) else None
    if not sandbox:
        die(
            "境界の設定が出力されていない",
            "[opencode.sandbox] が enabled=false。chezmoi apply で生成する",
        )
    if not isinstance(sandbox, dict):
        die(f"{rules_path} の sandbox が object でない")
    for key in ("runtime_path", "base", *required):
        if not sandbox.get(key):
            die(f"境界の設定に {key} が無い")
    if not isinstance(sandbox["base"], dict):
        die(f"{rules_path} の sandbox.base が object でない")
    return sandbox


def project_extras(request: dict | None) -> dict:
    """``.opencode/sandbox.toml`` で足す分。宣言が無ければ追加はゼロ。"""
    if request is None:
        return {key: [] for key in REQUEST_KEYS}
    return request["extras"]


def git_common_dir(workspace: Path) -> Path | None:
    """linked worktree のとき、共有 ``.git`` の実体を返す。

    ★ここは境界の外で走る。``/usr/bin/git`` を絶対パスで呼び、利用者の ``GIT_*`` を落とす
      (``GIT_DIR`` を通すと、別のリポジトリが書けるようになる)。
    """
    done = subprocess.run(
        [
            "/usr/bin/git",
            "-C",
            str(workspace),
            "rev-parse",
            "--path-format=absolute",
            "--git-common-dir",
        ],
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
    see docs/spec/sandbox/opencode-sandbox.md#起動ディレクトリの制限
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

    see docs/spec/sandbox/opencode-sandbox.md#保護対象denywrite
    """
    roots = [workspace]
    top = backup.git_toplevel(workspace)
    if top is not None:
        roots.append(top.resolve())
    rels = sandbox["base"].get("protected", [])
    return _uniq_paths([_real(root / rel) for root in roots for rel in rels])


def reject_protected_workspace(sandbox: dict, workspace: Path, request: dict | None = None) -> None:
    """保護対象の中での起動と、保護対象の中を ``write`` に足す宣言を拒否する。

    see docs/spec/sandbox/opencode-sandbox.md#保護対象denywrite
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
    deny_read = _uniq(
        [
            str(_real(Path(p)))
            for p in _existing(base.get("deny_read", []))
            if not _within(p, [str(HOME)])
            or not _within(str(_real(Path(p))), home_real)
            or _within(p, opened)
            or _within(str(_real(Path(p))), opened_real)
        ]
    )
    network = dict(base["network"])
    if extras.get("network_allow"):
        network["allowedDomains"] = _uniq(
            [*network.get("allowedDomains", []), *extras["network_allow"]]
        )
    config = {
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
    if extras.get("devices"):
        # auto の挙動に依存しないよう minimal を明示する (足さないときはキーごと作らない)
        config["devices"] = {"mode": "minimal", "allow": list(extras["devices"])}
    return config


# 秘密ファイルの列挙で降りないディレクトリ (巨大で、秘密を置く場所でもない)
SECRET_SCAN_PRUNE = frozenset(
    {".git", "node_modules", ".venv", "venv", "__pycache__", ".tox", ".mypy_cache", ".ruff_cache"}
)
SECRET_SCAN_MAX_ENTRIES = 300_000
SECRET_SCAN_MAX_DENY = 2_000


def _load_secret_policy(agents_dir: Path | None = None):
    """照合する関数 (パス → 当たった glob か None) を返す。正本は ``[file] read_deny_globs``。

    判定器と同じ command_policy を使う。読めないときは起動を止める (秘密を隠せないまま動かさない)。
    """
    import importlib.util

    agents = agents_dir if agents_dir is not None else HOME / ".config/agents"
    module_path, common = agents / "command_policy.py", agents / "common.toml"
    if not module_path.is_file() or not common.is_file():
        die(
            f"秘密ファイルの一覧を読めない: {agents} (command_policy.py / common.toml)",
            "chezmoi apply で配る",
        )
    try:
        spec = importlib.util.spec_from_file_location("_ocs_command_policy", module_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        globs = module.load_file_globs("read_deny_globs", str(common))
        exceptions = module.load_read_deny_exceptions(str(common))
    except Exception as e:  # どんな破損でも起動を止める
        die(f"秘密ファイルの一覧を読めない: {e}", "chezmoi apply で配り直す")
    if not globs:
        die("read_deny_globs が空 (秘密ファイルを確かめられない)", "chezmoi apply で配り直す")
    return lambda path: module.matches_read_deny(path, globs, exceptions)


def find_secret_paths(workspace: Path, matches) -> list[str]:
    """起動ディレクトリの中で ``read_deny_globs`` に当たる実在のファイル・ディレクトリを返す。

    ``.env`` のように作業ディレクトリの中にある秘密を、OS の層 (Fence の ``denyRead``) でも隠すため。
    ディレクトリ全体が当たる規則 (``**/.ssh/**``・``**/secrets/**``) は、中を降りずにそのディレクトリを返す。
    **起動後に作られるファイルは隠せない** (列挙は起動時の 1 回)。
    """
    found: list[str] = []
    seen = 0
    for root, dirs, files in os.walk(workspace, followlinks=False):
        kept = []
        for name in sorted(dirs):
            path = os.path.join(root, name)
            seen += 1
            if name in SECRET_SCAN_PRUNE:
                continue
            if matches(path + "/x") or matches(path):
                found.append(str(_real(Path(path))))
            else:
                kept.append(name)
        dirs[:] = kept
        for name in sorted(files):
            seen += 1
            path = os.path.join(root, name)
            if matches(path):
                found.append(str(_real(Path(path))))
        if seen > SECRET_SCAN_MAX_ENTRIES:
            die(
                f"起動ディレクトリが大きすぎて秘密ファイルを列挙できない ({SECRET_SCAN_MAX_ENTRIES} 件超)",
                "より狭いディレクトリで起動する",
            )
        if len(found) > SECRET_SCAN_MAX_DENY:
            die(
                f"秘密ファイルに当たるものが多すぎる ({SECRET_SCAN_MAX_DENY} 件超)",
                "より狭いディレクトリで起動する",
            )
    return _uniq(found)


def hide_workspace_secrets(
    config: dict, workspace: Path, agents_dir: Path | None = None
) -> list[str]:
    """``config`` の ``denyRead`` へ、起動ディレクトリの中の秘密ファイルを足し、足したものを返す。"""
    hidden = find_secret_paths(workspace, _load_secret_policy(agents_dir))
    filesystem = config["filesystem"]
    filesystem["denyRead"] = _uniq([*filesystem.get("denyRead", []), *hidden])
    return hidden


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


def env_extra_read() -> list[str]:
    """``PIS_EXTRA_READ`` (コロン区切りの絶対パス) を読む。相対パスは起動しない。

    see docs/spec/sandbox/opencode-sandbox.md#環境変数での追加
    """
    out: list[str] = []
    bad: list[str] = []
    for raw in os.environ.get(EXTRA_READ_ENV, "").split(":"):
        if not raw:
            continue
        expanded = Path(raw).expanduser()
        if not expanded.is_absolute():
            bad.append(raw)
            continue
        out.append(os.path.normpath(expanded))
    if bad:
        die(
            f"{EXTRA_READ_ENV} に絶対パスでない要素がある: {', '.join(bad)}",
            "絶対パス (または ~ 始まり) をコロンで区切って書く",
        )
    return _uniq(out)


def _device_problem(raw: str) -> str | None:
    """``devices`` の 1 要素の問題。無ければ ``None``。

    glob は拒否する (Fence の README に ``devices.allow`` が glob を受けるとの記述が無い)。
    """
    if not raw.startswith("/"):
        return "絶対パスでない (~ も不可)"
    if any(c in raw for c in "*?["):
        return "glob 文字は使えない"
    if os.path.normpath(raw) != raw:
        return "正規化されていない (.. や // や末尾の / など)"
    parent, name = os.path.split(raw)
    if parent != "/dev" or not name:
        return "/dev/ 直下の名前 1 つでない"
    if name not in ALLOWED_DEVICE_NAMES and not re.fullmatch(ALLOWED_DEVICE_PATTERN, name):
        return "許可リストにない"
    return None


def _checked_devices(values: list[str], source: str) -> list[str]:
    """``devices`` の要素を検証する。1 つでも不正なら、どの要素かを示して起動しない。"""
    bad = [f"{v!r} ({p})" for v in values if (p := _device_problem(v)) is not None]
    if bad:
        die(
            f"{source} に不正なデバイスがある: {', '.join(bad)}",
            f"/dev/ 直下の名前 1 つの絶対パスで、許可リストにある名前だけ。許可: {', '.join(ALLOWED_DEVICES)}",
        )
    return values


def env_extra_devices() -> list[str]:
    """``PIS_EXTRA_DEVICES`` (コロン区切りの ``/dev/`` 直下の絶対パス) を読む。

    see docs/spec/sandbox/opencode-sandbox.md#環境変数での追加
    """
    raws = [r for r in os.environ.get(EXTRA_DEVICES_ENV, "").split(":") if r]
    return _uniq(_checked_devices(raws, EXTRA_DEVICES_ENV))


def read_request(workspace: Path) -> dict | None:
    """``.opencode/sandbox.toml`` と環境変数 (``PIS_EXTRA_READ``・``PIS_EXTRA_DEVICES``) を読む。

    足す分が無ければ ``None``。環境変数はファイルの後ろに足す。
    ``env_read``・``env_devices`` は、ファイルに無い環境変数由来の分 (表示用)。
    """
    path, extras = _read_request_file(workspace)
    env_read = [p for p in env_extra_read() if p not in extras["read"]]
    extras["read"] = _uniq([*extras["read"], *env_read])
    env_devices = [d for d in env_extra_devices() if d not in extras["devices"]]
    extras["devices"] = _uniq([*extras["devices"], *env_devices])
    if not any(extras.values()):
        return None
    return {
        "path": path,
        "extras": extras,
        "env_read": env_read,
        "env_devices": env_devices,
    }


def _read_request_file(workspace: Path) -> tuple[Path | None, dict[str, list[str]]]:
    """``.opencode/sandbox.toml`` の中身。ファイルが無ければ ``(None, 空)``。"""
    path = workspace / REQUEST_REL
    empty: dict[str, list[str]] = {key: [] for key in REQUEST_KEYS}
    if not path.is_file():
        return None, empty
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
        if key == "devices":
            extras[key] = _uniq(_checked_devices(values, f"{path} の devices"))
            continue
        extras[key] = [
            v if key == "network_allow" else _resolve_requested(v, workspace) for v in values
        ]
    return path, extras


def describe_request(request: dict) -> str:
    """起動時に表示する、``.opencode/sandbox.toml`` で足した分。"""
    labels = {
        "read": "読める",
        "write": "書ける",
        "network_allow": "通信",
        "devices": "デバイス",
    }
    env_names = {"read": EXTRA_READ_ENV, "devices": EXTRA_DEVICES_ENV}
    env_values = {
        "read": set(request.get("env_read", [])),
        "devices": set(request.get("env_devices", [])),
    }
    sources = [env_names[k] for k in env_names if env_values[k]]
    origin = request["path"] or " / ".join(sources) or EXTRA_READ_ENV
    lines = [f"ocs: {origin} の追加を適用する"]
    for key, label in labels.items():
        values = request["extras"][key]
        if key in env_names:
            values = [f"{v} ({env_names[key]})" if v in env_values[key] else v for v in values]
        if values:
            lines.append(f"  {label}: {', '.join(values)}")
    return "\n".join(lines)


def announce_request(request: dict | None) -> None:
    if request is not None:
        print(describe_request(request), file=sys.stderr)
