"""プラットフォームの最小検証(Windows / WSL / Ubuntu)。現行の確認サーバと、立て直しで使う仕組みを確かめる。

標準ライブラリだけ(Python 3.9 以上)。自分で一時フォルダを作り、利用者のファイルには触れない。

使い方(リポジトリのルートで):

    python skills/conference-video/tests/e2e/platform_smoke.py
    python skills/conference-video/tests/e2e/platform_smoke.py --interactive   # ブラウザの目視確認も行う

Windows では `python` が無ければ `py` を使う。結果は画面と `platform-smoke-report.txt`(実行した
フォルダ)に出る。その内容をそのまま共有してほしい。

確かめること:
  A. 環境(OS、Python、WSL か、文字コード)
  B. 日本語・空白を含むパスで確認サーバが起動し、API と静的配信が動く
  C. localhost(127.0.0.1 / localhost / ::1)への到達
  D. Excel のようにファイルを開いたままの状態で、保存がどうなるか(現行の挙動の記録)
  E. 終了の扱い(terminate、Windows の Ctrl+Break)と、再起動・二重起動
  F. 立て直しで使う部品: O_EXCL のロックファイル(複数プロセスの競合)、他のプロセスが開いている
     ファイルへの os.replace
  --interactive: ブラウザで URL を開く手順(WSL ではサーバは WSL、ブラウザは Windows 側で開く)
"""

from __future__ import annotations

import argparse
import http.client as httpc
import json
import locale
import os
import platform
import queue
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

HERE = Path(__file__).resolve()
SERVER = HERE.parents[2] / "scripts" / "review_server.py"
REPORT: list[str] = []
RESULTS: list[tuple[str, bool]] = []


def log(line: str = "") -> None:
    print(line, flush=True)
    REPORT.append(line)


def check(name: str, ok: bool, detail: str = "") -> bool:
    RESULTS.append((name, bool(ok)))
    log(("OK  " if ok else "NG  ") + name + (f"  [{detail}]" if detail else ""))
    return bool(ok)


def note(name: str, detail: str) -> None:
    """合否ではなく、挙動の記録。"""
    log(f"記録 {name}: {detail}")


# ───────────── 環境 ─────────────


def is_wsl() -> bool:
    try:
        return "microsoft" in Path("/proc/version").read_text().lower()
    except OSError:
        return False


def section_env() -> None:
    log("== A. 環境")
    log(f"OS: {platform.platform()}")
    log(f"Python: {sys.version.split()[0]} ({sys.executable})")
    log(f"sys.platform={sys.platform} os.name={os.name} WSL={is_wsl()}")
    log(
        f"fs encoding={sys.getfilesystemencoding()} "
        f"preferred={locale.getpreferredencoding(False)} stdout={sys.stdout.encoding}"
    )
    log(f"サーバ: {SERVER} ({'有' if SERVER.is_file() else '無'})")
    if not SERVER.is_file():
        log("エラー: リポジトリのルートから実行してください")
        sys.exit(2)


# ───────────── 試験データ ─────────────

NARRATION = (
    "subtitles:\n- 単眼 SLAM を紹介します。\n- 次に地図の話です。\n- 最後に結果です。\n"
)


def make_workdir(root: Path) -> Path:
    work = root / "作業 フォルダ" / "動画 テスト"
    (work / "assets").mkdir(parents=True)
    (work / "narration.txt").write_text(NARRATION, encoding="utf-8")
    subs = [
        {
            "index": i,
            "text": t,
            "start_s": i * 4.0,
            "end_s": i * 4.0 + 4.0,
            "duration_s": 4.0,
            "phrases": [{"text": "テスト"}],
        }
        for i, t in enumerate(
            ["単眼 SLAM を紹介します。", "次に地図の話です。", "最後に結果です。"]
        )
    ]
    (work / "timestamps.json").write_text(
        json.dumps({"total_duration_s": 12.0, "subtitles": subs}, ensure_ascii=False),
        encoding="utf-8",
    )
    (work / "yomi.json").write_text(
        json.dumps(
            {
                "schema": 1,
                "entries": {
                    "SLAM": {
                        "pron": "スラム",
                        "accent": 1,
                        "status": "確認済み",
                        "note": "",
                    }
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (work / "assets.json").write_text(
        json.dumps({"schema": 1, "entries": {}}), encoding="utf-8"
    )
    (work / "video.mp4").write_bytes(bytes(range(256)) * 8)
    return work


# ───────────── サーバ操作 ─────────────


class Server:
    def __init__(self, work: Path, extra=(), new_group: bool = False):
        flags = 0
        if new_group and os.name == "nt":
            flags = subprocess.CREATE_NEW_PROCESS_GROUP
        self.proc = subprocess.Popen(
            [
                sys.executable,
                "-u",
                str(SERVER),
                "--workdir",
                str(work),
                "--no-open",
                *extra,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=flags,
        )
        self.lines: list[str] = []
        self._q: queue.Queue = queue.Queue()
        threading.Thread(target=self._pump, daemon=True).start()
        self.url = None

    def _pump(self) -> None:
        for ln in self.proc.stdout:
            self.lines.append(ln.rstrip("\n"))
            self._q.put(ln)
        self._q.put(None)

    def wait_ready(self, timeout: float = 15.0):
        end = time.time() + timeout
        while time.time() < end:
            try:
                ln = self._q.get(timeout=0.2)
            except queue.Empty:
                continue
            if ln is None:
                return None
            m = re.search(r"REVIEW_READY (\S+)", ln)
            if m:
                self.url = m.group(1)
                return self.url
        return None

    def stop(self, kind: str = "terminate", timeout: float = 10.0):
        if self.proc.poll() is None:
            if kind == "break" and os.name == "nt":
                self.proc.send_signal(signal.CTRL_BREAK_EVENT)
            elif kind == "kill":
                self.proc.kill()
            else:
                self.proc.terminate()
            try:
                self.proc.wait(timeout)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(5)
        return self.proc.returncode

    def tail(self, n: int = 12) -> str:
        return " | ".join(self.lines[-n:])


def http(
    url: str,
    method: str,
    path: str,
    body=None,
    host: str | None = None,
    timeout: float = 10.0,
):
    u = urlparse(url)
    conn = httpc.HTTPConnection(host or u.hostname, u.port, timeout=timeout)
    headers = {"Content-Type": "application/json"} if body is not None else {}
    data = (
        json.dumps(body, ensure_ascii=False).encode("utf-8")
        if body is not None
        else None
    )
    try:
        conn.request(
            method,
            path,
            body=data,
            headers=headers,
        )
        r = conn.getresponse()
        return r.status, r.read()
    finally:
        conn.close()


def yomi_entry(url: str, surface: str):
    """画面が「見た値」として更新に添える、その語の現在の値(無ければ None)。"""
    return {y["surface"]: y["entry"] for y in state(url).get("yomi", [])}.get(surface)


def state(url: str) -> dict:
    s, b = http(url, "GET", "/api/state")
    return json.loads(b) if s == 200 else {}


# ───────────── B / C / D / E ─────────────


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def section_server(root: Path) -> None:
    log("")
    log("== B. 日本語・空白を含むパスでの起動と API")
    work = make_workdir(root)
    log(f"作業フォルダ: {work}")
    port0 = free_port()
    srv = Server(work, extra=("--port", str(port0)))
    url = srv.wait_ready()
    if not check("確認サーバが起動し REVIEW_READY を出す", url, srv.tail()):
        srv.stop()
        return
    log(f"URL: {url}")
    s, b = http(url, "GET", "/")
    check("画面(HTML)を配信できる", s == 200 and b"<html" in b.lower(), f"status={s}")
    st = state(url)
    lines = st.get("script", {}).get("lines", [])
    check(
        "状態 API が日本語の台本を返す",
        len(lines) == 3 and "単眼" in lines[0]["text"],
        str(lines[:1]),
    )
    check(
        "作業フォルダのパスが一致する",
        Path(st.get("workdir", "")).resolve() == work.resolve(),
        st.get("workdir", ""),
    )
    s, b = http(url, "GET", "/files/video.mp4")
    check("動画を配信できる", s == 200 and len(b) == 2048, f"status={s} len={len(b)}")
    u = urlparse(url)
    conn = httpc.HTTPConnection(u.hostname, u.port, timeout=10)
    conn.request(
        "GET",
        "/files/video.mp4",
        headers={"Range": "bytes=10-19"},
    )
    r = conn.getresponse()
    r.read()
    conn.close()
    check(
        "Range 要求に 206 で答える(動画のシーク)", r.status == 206, f"status={r.status}"
    )

    log("")
    log("== C. localhost への到達")
    port = u.port
    for host in ("127.0.0.1", "localhost"):
        try:
            s, _ = http(url, "GET", "/api/state", host=host)
            note(
                f"{host}:{port}",
                f"status={s}" + (" (Host 検査で拒否の可能性)" if s == 403 else ""),
            )
            check(f"{host} で状態 API に届く", s == 200, f"status={s}")
        except OSError as e:
            check(f"{host} で状態 API に届く", False, repr(e))
    try:
        with socket.create_connection(("::1", port), timeout=3):
            note("::1(IPv6)", "接続できた(サーバは 127.0.0.1 のみのはずなので想定外)")
    except OSError as e:
        note(
            "::1(IPv6)",
            f"接続不可(想定どおり。localhost が ::1 を先に引くブラウザは IPv4 へ戻る必要がある): {e!r}",
        )

    log("")
    log("== B'. 保存の動作")
    h = state(url)["hashes"]
    s, b = http(
        url,
        "POST",
        "/api/note",
        {"line": 1, "note": "スモーク", "hash": h["script"], "expected": None},
    )
    check("指摘を保存できる", s == 200, f"status={s} {b[:120]!r}")

    def save_yomi(surface, reading, note_text=""):
        return http(
            url,
            "POST",
            "/api/yomi",
            {
                "surface": surface,
                "reading": reading,
                "status": "確認済み",
                "note": note_text,
                "expected": yomi_entry(url, surface),
            },
        )

    s, b = save_yomi("RANSAC", "ラ'ンサック", "smoke")
    check("読みを保存できる(yomi.json)", s == 200, f"status={s} {b[:120]!r}")
    raw = (work / "yomi.json").read_bytes()
    note("yomi.json の先頭バイト", repr(raw[:12]))
    note("yomi.json の改行", "CRLF" if b"\r\n" in raw else "LF")

    log("")
    log("== D. ファイルを開いたままの保存(Excel を想定)")
    holder = open(
        work / "yomi.json", "rb"
    )  # Windows では、これで置き換え・削除ができなくなる
    try:
        s, b = save_yomi("KL", "ケ'ーエル")
        note("他のプロセスが開いている間の保存", f"status={s} body={b[:300]!r}")
        if os.name == "nt":
            check(
                "開いている間は成功せず、原因の候補(他のアプリ・読み取り専用・権限)を案内する",
                s != 200 and "他のアプリ" in b.decode("utf-8", "replace"),
                f"status={s}",
            )
        else:
            check("POSIX では開いていても保存できる", s == 200, f"status={s}")
    finally:
        holder.close()
    s, b = save_yomi("KL", "ケ'ーエル")
    check("閉じた後は保存できる", s == 200, f"status={s} {b[:120]!r}")
    check("ロックファイルを残さない", not (work / "yomi.json.lock").exists())
    leftovers = [p.name for p in work.iterdir() if p.name.startswith(".")]
    check("失敗しても一時ファイルを残さない", not leftovers, str(leftovers))

    log("")
    log("== E. 終了と再起動")
    # 二重起動: 同じポートでもう 1 つ起動しても、同じフォルダなら URL を案内して終わる
    # (Windows では同じポートへの二重バインドを拒否する設定に依存。未検証)
    srv2 = Server(work, extra=("--port", str(port0)))
    url2 = srv2.wait_ready()
    note("二重起動(2 つ目)の出力", srv2.tail(6))
    check("二重起動では同じ URL を案内する", url2 == url, f"url={url} url2={url2}")
    srv2.stop()
    srv.stop("terminate")
    rc = srv.proc.returncode
    note("terminate の終了コード", str(rc))
    srv3 = Server(work, extra=("--port", str(port0)))
    url3 = srv3.wait_ready()
    check("終了後に同じポートで再起動できる", bool(url3), srv3.tail())
    if os.name == "nt" and url3:
        rc = srv3.stop("break")
        note("Ctrl+Break の終了コード", str(rc))
    else:
        srv3.stop()


# ───────────── F: 立て直しで使う部品 ─────────────

LOCK_WORKER = """
import os, sys, time
path, start = sys.argv[1], float(sys.argv[2])
while time.time() < start:
    pass
try:
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    os.close(fd)
    print("WIN")
except FileExistsError:
    print("LOSE")
except OSError as e:
    print("ERR", repr(e))
"""

HOLD_WORKER = """
import sys, time
f = open(sys.argv[1], "rb")
print("OPEN", flush=True)
time.sleep(float(sys.argv[2]))
"""


def section_parts(root: Path) -> None:
    log("")
    log("== F. 立て直しで使う部品")
    d = root / "部品 試験"
    d.mkdir()
    # F1: O_EXCL のロックファイル(複数プロセスの競合)
    wins = 0
    for trial in range(3):
        lock = d / f"x{trial}.lock"
        start = time.time() + 1.0
        procs = [
            subprocess.Popen(
                [sys.executable, "-c", LOCK_WORKER, str(lock), str(start)],
                stdout=subprocess.PIPE,
                text=True,
            )
            for _ in range(6)
        ]
        outs = [p.communicate(timeout=20)[0].strip() for p in procs]
        wins += outs.count("WIN") == 1 and outs.count("LOSE") == 5
        if trial == 0:
            note("O_EXCL の競合(6 プロセス)の結果の例", ", ".join(outs))
    check(
        "O_EXCL のロックファイルは、競合しても勝つのは 1 プロセスだけ(3 回)",
        wins == 3,
        f"成功 {wins}/3",
    )
    # F2: ロックファイルの削除(古いロックの解除)
    lock = d / "stale.lock"
    lock.write_text("x")
    try:
        lock.unlink()
        check("ロックファイルを削除できる(古いロックの解除)", True)
    except OSError as e:
        check("ロックファイルを削除できる(古いロックの解除)", False, repr(e))
    # F3: 他のプロセスが開いているファイルへの os.replace
    target = d / "state.json"
    target.write_text('{"v": 1}', encoding="utf-8")
    holder = subprocess.Popen(
        [sys.executable, "-c", HOLD_WORKER, str(target), "6"],
        stdout=subprocess.PIPE,
        text=True,
    )
    holder.stdout.readline()  # OPEN
    tmp = d / "state.json.tmp"
    tmp.write_text('{"v": 2}', encoding="utf-8")
    try:
        os.replace(tmp, target)
        note("他プロセスが開いている JSON への os.replace", "成功(置換できる)")
        ok_replace = True
    except OSError as e:
        note(
            "他プロセスが開いている JSON への os.replace",
            f"失敗 {e!r}(winerror={getattr(e, 'winerror', None)})",
        )
        ok_replace = False
    holder.wait(timeout=20)
    if tmp.exists():
        tmp.unlink()
    check(
        "開いているファイルへの置換の挙動を記録した(Windows では失敗が想定。窓口は原因を案内する)",
        True,
        "置換できた" if ok_replace else "置換できなかった",
    )
    # F4: 日本語名・空白を含む一時ファイルと置換
    jp = d / "辞書 テスト.json"
    jp.write_text("{}", encoding="utf-8")
    tmp = d / ".辞書 テスト.json.tmp"
    tmp.write_text('{"a": 1}', encoding="utf-8")
    os.replace(tmp, jp)
    check(
        "日本語名・空白を含むファイルの置換",
        json.loads(jp.read_text(encoding="utf-8")) == {"a": 1},
    )
    # F5: 改行・BOM の書き込み(newline を指定しない書き込みが OS で変わるか)
    p = d / "newline.txt"
    with open(p, "w", encoding="utf-8") as f:
        f.write("a\nb\n")
    note("open(..., 'w') で \\n を書いたときのバイト", repr(p.read_bytes()))


# ───────────── 目視(任意) ─────────────


def section_interactive(root: Path) -> None:
    log("")
    log("== 目視確認(--interactive)")
    work = make_workdir(root / "目視")
    srv = Server(work, extra=("--port", str(free_port())))
    url = srv.wait_ready()
    if not url:
        check("目視用のサーバが起動する", False, srv.tail())
        return
    wsl = is_wsl()
    log("")
    log(f"URL: {url}")
    log(
        "このサーバを起動したまま、次をブラウザで確認してください(結果は下の質問に答える)。"
    )
    if wsl:
        log(
            "・WSL 上のサーバです。**Windows 側のブラウザ**で上の URL を開いてください。"
        )
        log(
            "  開けないときは、URL の 127.0.0.1 を localhost に替える・WSL の IP(`hostname -I`)を試す、も記録してください。"
        )
    else:
        log("・上の URL をブラウザで開いてください。")
    log("・画面が表示され、「台本」タブに 3 行が出ること")
    log(
        "・「動画」タブで video.mp4 の再生枠が出ること(中身はダミーなので再生はできなくてよい)"
    )
    log("・台本の 1 行に指摘を書いて、フォーカスを外す → 保存のメッセージが出ること")
    answers = {}
    for key, q in [
        (
            "ブラウザ(名前と OS)",
            "ブラウザは何ですか(例: Windows の Edge / Ubuntu の Firefox)? ",
        ),
        ("URL が開けた", "URL は開けましたか(はい/いいえ。いいえなら試したこと)? "),
        ("画面が表示された", "画面は表示されましたか(はい/いいえ)? "),
        ("指摘が保存できた", "指摘は保存できましたか(はい/いいえ)? "),
        ("気づいたこと", "そのほか気づいたこと(なければ空欄)? "),
    ]:
        try:
            answers[key] = input(q).strip()
        except EOFError:
            answers[key] = "(入力なし)"
    for k, v in answers.items():
        log(f"目視 {k}: {v}")
    note_file = work / "notes.json"
    log(f"目視 notes.json ができたか: {'はい' if note_file.exists() else 'いいえ'}")
    srv.stop()


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--interactive", action="store_true", help="ブラウザでの目視確認も行う"
    )
    ap.add_argument("--report", default="platform-smoke-report.txt")
    a = ap.parse_args()
    root = Path(tempfile.mkdtemp(prefix="確認 smoke "))
    try:
        section_env()
        section_server(root)
        section_parts(root)
        if a.interactive:
            section_interactive(root)
    finally:
        shutil.rmtree(root, ignore_errors=True)
    ng = [n for n, ok in RESULTS if not ok]
    log("")
    log(
        f"{len(RESULTS) - len(ng)}/{len(RESULTS)} 項目 OK"
        + (f" / NG: {ng}" if ng else "")
    )
    try:
        Path(a.report).write_text("\n".join(REPORT) + "\n", encoding="utf-8")
        print(f"レポート: {Path(a.report).resolve()}")
    except OSError as e:
        print(f"レポートを書けない: {e!r}")
    return 1 if ng else 0


if __name__ == "__main__":
    sys.exit(main())
