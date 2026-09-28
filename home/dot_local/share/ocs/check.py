"""起動前の境界チェック。"""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import subprocess
from pathlib import Path

from .common import HOME, OPENCODE, _now, die

CHECK = HOME / ".local/bin/ocs-boundary-check"
# 境界チェックで「見えない」ことを確かめる対象。HOME 相対と WSL の Windows 側。
HIDDEN_HOME_TARGETS = (".ssh", ".git-credentials", ".config/gh")
# 境界チェックが必ず 1 件は本当に検査できるよう、ocs 自身が置く目印。
# ~ は deny_read なので、read に載せない限り内側からは見えない。
CANARY_REL = ".local/state/opencode-sandbox/boundary-canary"
# srt は境界を張る前に which / bwrap / socat / bash を PATH から探して動かす。
# see docs/spec/opencode-sandbox.md#信頼の鎖
SRT_PATH = "/usr/bin:/bin"
# srt が境界の外で走らせる rg。SRT_PATH に無いので実体を絶対パスで渡す。
RIPGREP_INSTALLS = HOME / ".local/share/mise/installs/ripgrep"
RIPGREP_SYSTEM = Path("/usr/bin/rg")
WSL_HIDDEN_TARGETS = ("/mnt/c/Users", "/mnt/c/Windows")
CHECKED = HOME / ".local/state/opencode-sandbox/checked.json"
# 合格の再利用期間。★短くする方向にしか動かさないこと。
CHECK_TTL_SECONDS = 24 * 60 * 60


def check_digest(sandbox: dict, boundary: dict, hidden: list[str]) -> str:
    """境界チェックの結果を再利用してよい範囲を表すハッシュ。

    **判定に効く入力を全て混ぜる。** どれかが変われば再検査になる。
    ここに混ぜ忘れたものは「変わっても古い合格が使われる」ことになる。
    ``hidden`` はホストに在る検査対象。後から現れたものを古い合格で素通りさせない。
    """
    digest = hashlib.sha256()
    digest.update(json.dumps(boundary, sort_keys=True).encode("utf-8"))
    digest.update(json.dumps(hidden).encode("utf-8"))
    for path in (Path(sandbox["runtime_path"]), CHECK, OPENCODE):
        digest.update(str(path).encode("utf-8"))
        try:
            # opencode は 200 MiB あるので中身ではなく大きさと更新時刻で見る
            stat = path.stat()
            digest.update(f"{stat.st_size}:{stat.st_mtime_ns}".encode())
        except OSError:
            digest.update(b"missing")
    return digest.hexdigest()


def check_is_fresh(digest: str) -> bool:
    """同じ入力での合格が、まだ有効期間の内にあるか。"""
    if not CHECKED.is_file():
        return False
    try:
        record = json.loads(CHECKED.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(record, dict) or record.get("digest") != digest:
        return False
    from datetime import datetime, timezone

    try:
        passed = datetime.fromisoformat(str(record.get("passed")))
    except ValueError:
        return False
    age = (datetime.now(timezone.utc) - passed).total_seconds()  # noqa: UP017 (common._now)
    # 時計が巻き戻っていたら再検査する (age < 0 を合格にしない)
    return 0 <= age < CHECK_TTL_SECONDS


def save_check(digest: str) -> None:
    CHECKED.parent.mkdir(parents=True, exist_ok=True)
    CHECKED.write_text(
        json.dumps({"digest": digest, "passed": _now()}, indent=2), encoding="utf-8"
    )
    CHECKED.chmod(0o600)


def hidden_targets() -> dict[str, list[str]]:
    """境界の内側で「見えない」ことを確かめる対象を、ホスト側の有無で分ける。

    ★ホストに無いものは内側でも見えなくて当然で、隔離の証拠にならない。
      在ると分かっているものだけを検査に回す。
      see docs/change/closed/0004-opencode-sandbox.md#拒否されたと試験できなかったを区別する
    """
    ensure_canary()
    candidates = [str(HOME / rel) for rel in (CANARY_REL, *HIDDEN_HOME_TARGETS)]
    if _is_wsl():
        candidates += WSL_HIDDEN_TARGETS
    present = [p for p in candidates if _exists(p)]
    return {"present": present, "absent": [p for p in candidates if p not in present]}


def ensure_canary() -> None:
    """境界チェックの目印をホストに置く。作れなければ起動しない。"""
    canary = HOME / CANARY_REL
    try:
        canary.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(canary.parent, 0o700)
        if not canary.exists():
            canary.write_text("ocs boundary canary\n", encoding="utf-8")
        os.chmod(canary, 0o600)
    except OSError as e:
        die(f"境界チェックの目印を作れない: {canary} ({e})")


def srt_env(env: dict) -> dict:
    """srt へ渡す環境変数。PATH だけを :data:`SRT_PATH` に固定する。

    ★srt は境界の外で PATH から ``which`` を起動する。利用者の PATH のまま
      渡すと、先頭の書き込める場所に置いた偽の ``which`` がホストで動く。
      内側へ渡す PATH は :func:`cli.inner_command` が別に戻す。
    """
    return {**env, "PATH": SRT_PATH}


def resolve_ripgrep(config: dict) -> str:
    """srt が境界の外で走らせる rg の実体を返す。**PATH から探さない。**

    mise の shim は mise 本体で、ワークスペースの設定を読む (:func:`cli.resolve_node`)。
    ★実体が境界の内側から書き換えられる場所にあれば起動しない。
    """
    candidates = []
    if RIPGREP_INSTALLS.is_dir():
        versions = sorted(
            (d for d in RIPGREP_INSTALLS.iterdir() if d.is_dir() and not d.is_symlink()),
            key=lambda d: [int(x) if x.isdigit() else -1 for x in d.name.split(".")],
            reverse=True,
        )
        for version in versions:
            candidates += sorted(p for p in version.glob("**/rg") if not p.is_symlink())
    candidates.append(RIPGREP_SYSTEM)
    found = next((p for p in candidates if p.is_file() and os.access(p, os.X_OK)), None)
    if found is None:
        die("rg の実体が見つからない", "mise install ripgrep で入れる")
    real = Path(found).resolve()
    writable = [Path(p).resolve() for p in config["filesystem"]["allowWrite"]]
    if any(real == w or w in real.parents for w in writable):
        die(
            f"rg が境界の内側から書き換えられる場所にある: {real}",
            "追加の write 許可から rg の置き場を外して起動し直す。",
        )
    return str(real)


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
        "BOUNDARY_HIDDEN": _lines(hidden["present"]),
        "BOUNDARY_HIDDEN_ABSENT": _lines(hidden["absent"]),
        "BOUNDARY_PROTECTED": _lines(project["config"]["filesystem"].get("denyWrite") or []),
        # 拒否と不通を区別するための対照
        "BOUNDARY_ALLOWED_HOST": next(
            (d for d in allowed if not d.startswith("*")), "github.com"
        ),
        "BOUNDARY_DENIED_HOST": "example.com",
    }


def run_check(
    node: str, runtime: Path, boundary: str, project: dict, env: dict, hidden: dict
) -> None:
    """境界チェックを 1 回走らせる。不合格なら**起動しない**。"""
    check_env = srt_env(check_environment(project, env, hidden))
    # ★パイプへ通さないこと。終了コードが置き換わり失敗を取りこぼす。
    # ★止まったら起動しない。判定できない ≠ 合格。
    try:
        done = subprocess.run(
            [node, str(runtime), "-s", boundary, "-c", shlex.join(["/bin/sh", str(CHECK)])],
            env=check_env,
            check=False,
            timeout=180,
        )
    except subprocess.TimeoutExpired:
        die("境界チェックが時間内に終わらなかった", "判定できないので起動しない")
    if done.returncode != 0:
        die("起動時の境界チェックが不合格", "上の ★NG を見て設定を直す")
