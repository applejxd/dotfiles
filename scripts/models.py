#!/usr/bin/env python3
"""子エージェントのモデルのカタログ (`[pi.model.catalog.<provider>]`) の鮮度と確認の道具 (CHG-0043 段 4)。

  python3 scripts/models.py check [--common PATH] [--list-file PATH] [--days N]
  python3 scripts/models.py probe [--common PATH] [--model ID] [--effort LEVEL] [--all] [--dry-run]

`check`: カタログと `pi --list-models` を比べ、(1) 一覧に無い項目 (2) 同じ系統の新しい世代 (3) 分類できない ID
(4) `reviewed_on` が古い、を警告する。**一覧の取得に失敗した・空のときは「問題なし」にせず、終了コード 2**。
一覧に無いことは、廃止の証明ではない (Copilot の Terra は、一覧に無いが動く)。保証の範囲は「確認済みカタログ内」で、
外部の最新との一致は、この警告と、定期的な見直しで補う。
`probe`: 固定の無害なファイルを読ませ、応答にその固定の文字列が含まれること (ツール呼び出しの成功) を確かめる。
**`verified` は自動では書き換えない** (結果を見て、手で直す)。

終了コード: 0 = 問題なし / 1 = 警告・失敗がある / 2 = 実行できなかった (一覧の取得失敗など)

see docs/change/0043-model-catalog.md
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "agents"))
import generate  # noqa: E402

STALE_DAYS = 30
PROBE_TIMEOUT = 150
PROBE_MAX_RUNS = 8
PROBE_FILE = "probe.txt"
# 世代を表す部分: 直前が `-` で、直後が `-` か末尾の、数字の列 (`6.1`・`5-5`)
VERSION_RE = re.compile(r"(?<=-)\d+(?:[.-]\d+)*(?=-|$)")


def default_common() -> Path:
    base = Path(os.environ.get("AGENTS_CONFIG_DIR", str(Path.home() / ".config" / "agents")))
    return base / "common.toml"


def load_catalog(common_path: Path) -> dict:
    try:
        common = tomllib.loads(common_path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as e:
        raise SystemExit(f"設定を読めない: {common_path}: {e}") from e
    catalog = generate.pi_catalog(common)
    if catalog is None:
        raise SystemExit("この設定のプロバイダには、[pi.model.catalog.<provider>] が無い")
    return catalog


# ─── pi --list-models ───


def parse_list(text: str) -> dict[str, set[str]]:
    """`pi --list-models` の表 (provider model context max-out thinking images) を、プロバイダごとの ID の集合にする。"""
    out: dict[str, set[str]] = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 2 or parts[0] == "provider":
            continue
        out.setdefault(parts[0], set()).add(parts[1])
    return out


def run_list(pi: str, timeout: int = 60) -> str:
    proc = subprocess.run(
        [pi, "--list-models"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=timeout,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"pi --list-models が失敗した (終了コード {proc.returncode}): {proc.stderr.strip()[-300:]}"
        )
    return proc.stdout


def generation_of(model_id: str) -> tuple[str, tuple[int, ...]] | None:
    """ID を、世代の部分を穴にした正規表現と、世代の整数の列に分ける。世代の部分が無ければ None。"""
    m = VERSION_RE.search(model_id)
    if not m:
        return None
    pattern = (
        re.escape(model_id[: m.start()])
        + r"(?P<gen>\d+(?:[.-]\d+)*)"
        + re.escape(model_id[m.end() :])
    )
    return f"^{pattern}$", tuple(int(x) for x in re.split(r"[.-]", m.group(0)))


# ─── check ───


def check(
    catalog: dict, listed: dict[str, set[str]], today: dt.date, stale_days: int = STALE_DAYS
) -> tuple[list[str], list[str]]:
    """(警告, 情報) を返す。"""
    provider = catalog["provider"]
    ids = listed.get(provider, set())
    warnings: list[str] = []
    info: list[str] = []
    reviewed = dt.date.fromisoformat(catalog["reviewed_on"])
    age = (today - reviewed).days
    if age > stale_days:
        warnings.append(
            f"reviewed_on が {age} 日前 ({catalog['reviewed_on']})。最新かどうかを見直す (閾値 {stale_days} 日)"
        )
    for m in catalog["models"]:
        mid = m["id"]
        if mid not in ids:
            warnings.append(
                f"{mid}: pi の一覧に無い。廃止とは限らない (custom id で動くことがある)。`models:probe` で確かめる"
            )
        parsed = generation_of(mid)
        if parsed is None:
            warnings.append(
                f"{mid}: 世代の部分を ID から取り出せない (分類不能)。新しい世代の検出の対象外"
            )
            continue
        regex, mine = parsed
        newer = sorted(
            (
                (tuple(int(x) for x in re.split(r"[.-]", hit.group("gen"))), cand)
                for cand in ids
                if (hit := re.match(regex, cand))
            ),
            reverse=True,
        )
        for gen, cand in newer:
            if gen > mine:
                warnings.append(
                    f"{mid}: 同じ系統の新しい世代が一覧にある: {cand} (カタログの世代 {list(mine)} → {list(gen)})"
                )
    info.append(f"プロバイダ {provider}: カタログ {len(catalog['models'])} 件、一覧 {len(ids)} 件")
    return warnings, info


def cmd_check(args: argparse.Namespace) -> int:
    catalog = load_catalog(Path(args.common))
    started = dt.datetime.now().astimezone()
    try:
        text = (
            Path(args.list_file).read_text(encoding="utf-8")
            if args.list_file
            else run_list(args.pi)
        )
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as e:
        print(f"実行できなかった: モデルの一覧を取得できない: {e}", file=sys.stderr)
        print("(一覧が無いので、鮮度は確かめられていない。問題なし、ではない)", file=sys.stderr)
        return 2
    listed = parse_list(text)
    provider = catalog["provider"]
    shown = ", ".join(sorted(listed)) or "(なし)"
    print(
        f"取得時刻: {started.isoformat(timespec='seconds')}  対象プロバイダ: {provider}  一覧のプロバイダ: {shown}"
    )
    if not listed.get(provider):
        print(
            f"実行できなかった: 一覧に {provider} のモデルが 1 つも無い (認証・キャッシュ・取得の失敗の可能性)。鮮度は確かめられていない",
            file=sys.stderr,
        )
        return 2
    warnings, info = check(catalog, listed, dt.date.today(), args.days)
    for line in info:
        print(line)
    for w in warnings:
        print(f"警告: {w}")
    if not warnings:
        print("問題なし (確認済みカタログの範囲。外部の最新との一致は、定期的な見直しで補う)")
        return 0
    return 1


# ─── probe ───


def probe_one(pi: str, model_arg: str, timeout: int) -> tuple[bool, float, str]:
    token = secrets.token_hex(6)
    with tempfile.TemporaryDirectory(prefix="models-probe-") as d:
        (Path(d) / PROBE_FILE).write_text(token + "\n", encoding="utf-8")
        cmd = [
            pi, "-p", "-ne", "--no-session", "-na", "--tools", "read", "--model", model_arg,
            f"Read the file {PROBE_FILE} in the current directory and reply with exactly the word it contains, nothing else.",
        ]  # fmt: skip
        started = time.monotonic()
        try:
            proc = subprocess.run(
                cmd,
                cwd=d,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return False, time.monotonic() - started, f"時間切れ ({timeout} 秒)"
        took = time.monotonic() - started
        ok = proc.returncode == 0 and token in proc.stdout
        note = (
            ""
            if ok
            else (
                proc.stdout.strip()[-160:]
                or proc.stderr.strip()[-160:]
                or f"終了コード {proc.returncode}"
            )
        )
        return ok, took, note


def cmd_probe(args: argparse.Namespace) -> int:
    catalog = load_catalog(Path(args.common))
    provider = catalog["provider"]
    pi = shutil.which(args.pi) or args.pi
    if args.model:
        wanted = [args.model]
    elif args.all:
        wanted = [m["id"] for m in catalog["models"]]
    else:
        wanted = [m["id"] for m in catalog["models"] if not m["verified"]] or [
            m["id"] for m in catalog["models"]
        ]
    if len(wanted) > PROBE_MAX_RUNS:
        print(
            f"実行できなかった: 1 回の上限は {PROBE_MAX_RUNS} 件 (費用の保護)。--model で絞る",
            file=sys.stderr,
        )
        return 2
    levels = [args.effort] if args.effort else [None]
    runs = [(mid, lvl) for mid in wanted for lvl in levels]
    for mid, lvl in runs:
        arg = f"{provider}/{mid}" + (f":{lvl}" if lvl else "")
        if args.dry_run:
            print(
                f"[dry-run] {pi} -p -ne --no-session -na --tools read --model {arg} <固定の読み取りの依頼>"
            )
    if args.dry_run:
        return 0
    failures = 0
    print(f"{'モデル':50} {'結果':6} {'秒':>6}  備考")
    for mid, lvl in runs:
        arg = f"{provider}/{mid}" + (f":{lvl}" if lvl else "")
        ok, took, note = probe_one(pi, arg, args.timeout)
        failures += 0 if ok else 1
        print(f"{arg:50} {'OK' if ok else 'NG':6} {took:6.1f}  {note}")
    print("verified は手で直す (OK を確認した項目だけ true にする)。")
    return 1 if failures else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("check", "probe"):
        sp = sub.add_parser(name)
        sp.add_argument(
            "--common",
            default=str(default_common()),
            help="描画済みの common.toml (既定: ~/.config/agents/common.toml)",
        )
        sp.add_argument("--pi", default="pi", help="pi の実行ファイル")
    c = sub.choices["check"]
    c.add_argument(
        "--list-file", help="`pi --list-models` の出力のファイル (試験用。無ければ pi を実行する)"
    )
    c.add_argument(
        "--days", type=int, default=STALE_DAYS, help=f"reviewed_on の警告の日数 (既定 {STALE_DAYS})"
    )
    p = sub.choices["probe"]
    p.add_argument(
        "--model", help="確かめるモデルの ID (カタログの id。既定: 未確認のもの。無ければ全部)"
    )
    p.add_argument("--effort", help="effort の段を付けて確かめる")
    p.add_argument("--all", action="store_true", help="カタログの全部を確かめる")
    p.add_argument("--dry-run", action="store_true", help="実行せずに、コマンドを表示する")
    p.add_argument("--timeout", type=int, default=PROBE_TIMEOUT, help="1 件の時間切れ (秒)")
    args = ap.parse_args(argv)
    return cmd_check(args) if args.cmd == "check" else cmd_probe(args)


if __name__ == "__main__":
    sys.exit(main())
