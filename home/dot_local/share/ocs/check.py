"""境界チェック (``ocs --check``)。

see docs/spec/opencode-sandbox.md#境界チェック
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import subprocess
import time
from pathlib import Path

from .common import HOME, STATE, die

CHECK = HOME / ".local/bin/ocs-boundary-check"
# 境界チェックで「読めない」ことを確かめる対象。HOME 相対と WSL の Windows 側。
HIDDEN_HOME_TARGETS = (".ssh", ".git-credentials", ".config/gh", ".config/chezmoi/key.txt")
# 境界チェックが必ず 1 件は本当に検査できるよう、ocs 自身が置く目印。
# read にも write にも載せないこと。
CANARY_REL = ".local/state/opencode-sandbox/boundary-canary"
WSL_HIDDEN_TARGETS = ("/mnt/c/Users", "/mnt/c/Windows")
# 許可外ドメインの検査先の候補 (IANA の予約ドメイン。HTTPS で応答する)
DENIED_CANDIDATES = ("example.com", "example.net", "example.org")
# Fence は境界を張る前に bwrap / socat / bash を PATH から探して動かす。
# see docs/spec/opencode-sandbox.md#信頼の鎖
HOST_PATH = "/usr/bin:/bin"


def service_json() -> Path:
    """常駐サービスの接続情報。境界の内側から見えてはいけない。"""
    state = os.environ.get("XDG_STATE_HOME") or str(HOME / ".local/state")
    return Path(state) / "opencode/service.json"


def hidden_targets() -> dict[str, list[str]]:
    """境界の内側で「読めない」ことを確かめる対象を、ホスト側の有無で分ける。

    ★ホストに無いものは内側でも読めなくて当然で、隔離の証拠にならない。
      在ると分かっているものだけを検査に回す。
    """
    ensure_canary()
    candidates = [
        str(HOME / rel) for rel in (CANARY_REL, *HIDDEN_HOME_TARGETS)
    ] + [str(service_json())]
    if _is_wsl():
        candidates += WSL_HIDDEN_TARGETS
    present = [p for p in candidates if _exists(p)]
    return {"present": present, "absent": [p for p in candidates if p not in present]}


def ensure_canary() -> None:
    """境界チェックの目印をホストに置く。作れなければ検査しない。"""
    canary = HOME / CANARY_REL
    try:
        canary.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(canary.parent, 0o700)
        if not canary.exists():
            canary.write_text("ocs boundary canary\n", encoding="utf-8")
        os.chmod(canary, 0o600)
    except OSError as e:
        die(f"境界チェックの目印を作れない: {canary} ({e})")


def host_env(env: dict, tmpdir: Path) -> dict:
    """Fence へ渡す環境変数。PATH を :data:`HOST_PATH` に、TMPDIR を状態領域に固定する。

    内側の opencode へ渡す PATH と TMPDIR は :func:`cli.inner_command` が戻す。
    """
    return {**env, "PATH": HOST_PATH, "TMPDIR": str(tmpdir)}


def _is_wsl() -> bool:
    try:
        return "microsoft" in Path("/proc/version").read_text(encoding="utf-8").lower()
    except OSError:
        return False


def _exists(path: str) -> bool:
    try:
        return Path(path).exists()
    except OSError:
        return False


def _lines(paths: list[str]) -> str:
    """検査スクリプトへ渡すパスの列。★区切りは改行なので、改行を含むパスは弾く。"""
    for path in paths:
        if "\n" in path:
            die(f"改行を含むパスは境界チェックへ渡せない: {path!r}")
    return "\n".join(paths)


def check_environment(project: dict, env: dict, hidden: dict[str, list[str]]) -> dict:
    """境界チェックへ渡す環境変数。パスの列は改行区切りにする (空白・glob を壊さない)。"""
    allowed = project["config"]["network"].get("allowedDomains") or []
    # BOUNDARY_CURL は検査スクリプトの試験用の差し替え口。利用者の環境から通さない
    inherited = {k: v for k, v in env.items() if k != "BOUNDARY_CURL"}
    return {
        **inherited,
        "BOUNDARY_WORKSPACE": project["workspace"],
        "BOUNDARY_DATA_DIR": _lines([project["data_dir"]]),
        "BOUNDARY_HIDDEN": _lines(hidden["present"]),
        "BOUNDARY_HIDDEN_ABSENT": _lines(hidden["absent"]),
        "BOUNDARY_PROTECTED": _lines(project["config"]["filesystem"].get("denyWrite") or []),
        # 拒否と不通を区別するための対照
        "BOUNDARY_ALLOWED_HOST": next(
            (d for d in allowed if not d.startswith("*")), "github.com"
        ),
        "BOUNDARY_DENIED_HOST": denied_probe(allowed),
    }


def denied_probe(allowed: list[str]) -> str:
    """拒否を確かめる通信先。許可に当たらない候補の先頭で、残らなければ空 (検査しない)。"""
    return next((h for h in DENIED_CANDIDATES if not _may_be_allowed(h, allowed)), "")


def _may_be_allowed(host: str, allowed: list[str]) -> bool:
    """★安全側に判定する。``*.x`` は Fence では ``x`` 自体を含まないが、ここでは含める。"""
    for pattern in allowed:
        p = pattern.strip().lower().rstrip(".")
        if p.startswith("*."):
            if host == p[2:] or host.endswith(p[1:]):
                return True
        elif "*" in p:
            if fnmatch.fnmatchcase(host, p):
                return True
        elif host == p:
            return True
    return False


# 事前検査の合格の記憶。設定・Fence の版・検査スクリプトのどれかが変わると鍵が変わり、再検査する
PREFLIGHT_DIR = STATE / "preflight"
PREFLIGHT_MAX_AGE_SECONDS = 7 * 24 * 60 * 60


def preflight_key(runtime: Path, project: dict, volatile: list[str]) -> str:
    """事前検査の鍵。起動ごとに変わるパス (``volatile``) は固定の記号に置き換えて数える。"""
    try:
        version = subprocess.run(
            [str(runtime), "--version"], capture_output=True, text=True, timeout=15, check=False
        ).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        version = ""
    try:
        script = hashlib.sha256(CHECK.read_bytes()).hexdigest()
    except OSError:
        script = ""
    config = json.dumps(project["config"], sort_keys=True)
    for index, path in enumerate(volatile):
        config = config.replace(path, f"<volatile-{index}>")
    payload = json.dumps(
        {"config": config, "workspace": project["workspace"], "fence": version, "check": script}
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def preflight(
    runtime: Path, boundary: str, project: dict, env: dict, tmpdir: Path, volatile: list[str]
) -> int:
    """事前検査。同じ設定・Fence・検査スクリプトで合格した記憶があれば、再検査しない。

    ★合格だけを覚える (不合格や時間切れは覚えない)。記憶は一定期間で捨てる (環境の変化に備える)。
    """
    marker = PREFLIGHT_DIR / preflight_key(runtime, project, volatile)
    try:
        if time.time() - marker.stat().st_mtime < PREFLIGHT_MAX_AGE_SECONDS:
            return 0
    except OSError:
        pass
    code = run_check(runtime, boundary, project, env, tmpdir)
    if code == 0:
        try:
            PREFLIGHT_DIR.mkdir(parents=True, exist_ok=True)
            os.chmod(PREFLIGHT_DIR, 0o700)
            marker.write_text("ok\n", encoding="utf-8")
            _prune_preflight()
        except OSError:
            pass  # 覚えられなくても起動は妨げない (次回また検査する)
    return code


def _prune_preflight() -> None:
    cutoff = time.time() - PREFLIGHT_MAX_AGE_SECONDS
    for path in PREFLIGHT_DIR.glob("*"):
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink()
        except OSError:
            pass


def run_check(
    runtime: Path, boundary: str, project: dict, env: dict, tmpdir: Path
) -> int:
    """境界チェックを 1 回走らせ、終了コードを返す (0 = 合格)。"""
    if not CHECK.is_file():
        die(f"境界チェックが無い: {CHECK}", "chezmoi apply で配備する")
    check_env = host_env(check_environment(project, env, hidden_targets()), tmpdir)
    # ★パイプへ通さないこと。終了コードが置き換わり失敗を取りこぼす。
    # ★止まったら不合格。判定できない ≠ 合格。
    try:
        done = subprocess.run(
            [str(runtime), "--settings", boundary, "--", "/bin/sh", str(CHECK)],
            env=check_env,
            check=False,
            timeout=180,
        )
    except subprocess.TimeoutExpired:
        print("境界チェック: 時間内に終わらなかった (不合格)")
        return 1
    return done.returncode
