"""確認サーバの画面を実ブラウザで操作し、操作がファイルに保存されることを確かめる(任意の検証)。

unittest の自動検出には含まれない(`mise run test:conference-video` では動かない)。
ブラウザの起動と ffmpeg が要るため、画面や API を変えたときに手元で実行する。

    uv run --with playwright python skills/conference-video/tests/e2e/ui_e2e.py

- Playwright が使う Chromium は、`playwright install chromium` で入れる。
  すでに入っている headless shell を使うときは、環境変数 E2E_CHROMIUM に実行ファイルの
  パスを指定する(例: ~/.cache/ms-playwright/chromium_headless_shell-*/*/chrome-headless-shell)
- 作業フォルダは一時フォルダに作る(画像・動画・音声は ffmpeg で生成)。利用者のファイルには触れない
- 終了コード: 0 = 全項目成功、1 = 失敗あり

確かめること: 承認、台本の修正(.bak)、指摘、外部変更後の承認の 409、読み・素材の保存、素材のサムネ、
動画の行リンクでのシーク、行の音声の再生、壊れた承認記録の警告と承認ボタンの無効化、JS エラーが無いこと。
"""

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("playwright が無い: uv run --with playwright python <このファイル>")
    sys.exit(2)

SERVER = Path(__file__).resolve().parents[2] / "scripts" / "review_server.py"

NARRATION = """subtitles:
- 単眼 SLAM を紹介します。
- 次に地図の話です。
- 最後に結果です。
"""


def ts_json() -> str:
    subs = []
    for i, (t, ph) in enumerate(
        [
            ("単眼 SLAM を紹介します。", ["タンガン", "スラム"]),
            ("次に地図の話です。", ["ツギニ", "チズ"]),
            ("最後に結果です。", ["サイゴニ", "ケッカ"]),
        ]
    ):
        subs.append(
            {
                "index": i,
                "text": t,
                "start_s": i * 4.0,
                "end_s": i * 4.0 + 4.0,
                "duration_s": 4.0,
                "phrases": [{"text": p} for p in ph],
            }
        )
    return json.dumps({"total_duration_s": 12.0, "subtitles": subs}, ensure_ascii=False)


def make_fixture(work: Path) -> None:
    (work / "assets").mkdir(parents=True)
    (work / "narration.txt").write_text(NARRATION, encoding="utf-8")
    (work / "timestamps.json").write_text(ts_json(), encoding="utf-8")
    yomi_entries = {
        "SLAM": {"pron": "スラム", "accent": 1, "status": "確認済み", "note": ""},
        "RANSAC": {"pron": "ランサック", "accent": 1, "status": "確認済み", "note": ""},
        "KL": {"pron": "ケーエル", "accent": 0, "status": "候補", "note": ""},
    }
    (work / "yomi.json").write_text(
        json.dumps({"schema": 1, "entries": yomi_entries}, ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )
    (work / "assets.json").write_text(
        json.dumps(
            {
                "schema": 1,
                "entries": {
                    "assets/a.png": {
                        "出典URL": "https://example.org/a",
                        "作者": "太郎",
                        "ライセンス": "CC BY 4.0",
                        "状態": "確認済み",
                        "場面": "動機",
                        "メモ": "",
                        "取得日": "2026-10-27",
                    }
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    ff = ["ffmpeg", "-y", "-loglevel", "error"]
    subprocess.run(
        ff
        + [
            "-f",
            "lavfi",
            "-i",
            "color=c=red:s=320x180",
            "-frames:v",
            "1",
            str(work / "assets/a.png"),
        ],
        check=True,
    )
    subprocess.run(
        ff
        + [
            "-f",
            "lavfi",
            "-i",
            "testsrc=duration=12:size=320x180:rate=10",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=12",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(work / "video.mp4"),
        ],
        check=True,
    )
    subprocess.run(
        ff
        + [
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=330:duration=12",
            str(work / "voiceover.wav"),
        ],
        check=True,
    )


def sha12(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()[:12]


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="ui-e2e-"))
    work = tmp / "work"
    make_fixture(work)
    proc = subprocess.Popen(
        [
            sys.executable,
            "-u",
            str(SERVER),
            "--workdir",
            str(work),
            "--no-open",
            "--port",
            "0",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    url = None
    for line in proc.stdout:
        m = re.search(r"REVIEW_READY (\S+)", line)
        if m:
            url = m.group(1)
            break
    if not url:
        print("REVIEW_READY が出ない")
        return 1

    results: list[tuple[str, bool]] = []

    def check(name: str, cond, detail=""):
        results.append((name, bool(cond)))
        print(
            ("OK  " if cond else "NG  ")
            + name
            + (f"  [{detail}]" if detail and not cond else "")
        )

    def approvals() -> dict:
        p = work / "approvals.json"
        return (
            json.loads(p.read_text(encoding="utf-8")).get("entries", {})
            if p.exists()
            else {}
        )

    try:
        with sync_playwright() as pw:
            exe = os.environ.get("E2E_CHROMIUM")
            # 音声出力の無い環境(PulseAudio につながらない WSL など)でも再生を試験できるようにする
            args = [
                "--autoplay-policy=no-user-gesture-required",
                "--disable-audio-output",
            ]
            browser = (
                pw.chromium.launch(executable_path=exe, args=args)
                if exe
                else pw.chromium.launch(args=args)
            )
            page = browser.new_page(viewport={"width": 1200, "height": 900})
            msgs: list[str] = []
            page.on("pageerror", lambda e: msgs.append(f"pageerror: {e}"))
            page.on(
                "console",
                lambda m: (
                    msgs.append(f"console.{m.type}: {m.text}")
                    if m.type == "error"
                    and "409" not in m.text  # 意図した衝突のログは除く
                    else None
                ),
            )
            orig = page.wait_for_selector

            def wfs(sel, *a, **k):
                r = orig(sel, *a, **k)
                if (
                    sel == ".toast.ok"
                ):  # 再読み込みを待ち、次の操作と取り違えないよう通知を消す
                    page.wait_for_timeout(400)
                    page.evaluate(
                        "() => document.getElementById('toast').replaceChildren()"
                    )
                return r

            page.wait_for_selector = wfs
            page.goto(url + "#script")
            page.wait_for_selector("textarea")

            # 1. 承認
            page.get_by_role("button", name="承認", exact=True).click()
            page.wait_for_selector(".toast.ok")
            check(
                "台本を承認すると approvals.json に記録される",
                approvals().get("script", {}).get("status") == "承認",
            )

            # 2. 本文の修正
            before = (work / "narration.txt").read_text(encoding="utf-8")
            ta = page.locator("textarea").nth(1)
            ta.fill(ta.input_value() + "(直した)")
            page.get_by_role("button", name="本文を保存").nth(1).click()
            page.wait_for_selector(".toast.ok")
            check(
                "本文の修正が narration.txt に入り、直前の内容が .bak に残る",
                "(直した)" in (work / "narration.txt").read_text(encoding="utf-8")
                and (work / "narration.txt.bak").read_text(encoding="utf-8") == before,
            )
            chip = page.locator(".chip", has_text="台本").inner_text()
            check("台本を変えたので承認が古くなる", "古い" in chip, chip)

            # 3. 指摘
            note = page.get_by_placeholder("指摘(読み・同期・内容)").nth(2)
            note.fill("3 行目を確認")
            note.blur()
            page.wait_for_selector(".toast.ok")
            notes = json.loads((work / "notes.json").read_text(encoding="utf-8"))[
                "entries"
            ]
            check(
                "指摘が notes.json の 3 行目に入る",
                notes.get("3", {}).get("note") == "3 行目を確認",
                notes,
            )

            # 4. 外部変更後の承認は 409
            narr = work / "narration.txt"
            narr.write_text(narr.read_text(encoding="utf-8") + "\n", encoding="utf-8")
            page.get_by_role("button", name="承認", exact=True).click()
            page.wait_for_selector(".toast.bad")
            check(
                "外部変更後の承認は拒否される",
                "変わりました" in page.locator(".toast.bad").first.inner_text(),
            )
            check(
                "拒否された承認は記録されない",
                approvals()["script"]["hash"] != sha12(narr),
            )
            page.wait_for_timeout(800)  # 画面が最新を読み直す
            page.get_by_role("button", name="承認", exact=True).click()
            page.wait_for_selector(".toast.ok")
            check(
                "最新を表示した後は承認できる",
                approvals()["script"]["hash"] == sha12(narr),
            )

            # 5. 読み
            page.locator(".chip", has_text="読み").click()
            page.wait_for_selector("tbody tr")
            row = page.locator("tbody tr", has_text="RANSAC").first
            row.locator("input[type=text]").nth(1).fill("e2e で確認")
            row.get_by_role("button", name="保存").click()
            page.wait_for_selector(".toast.ok")
            check(
                "読みのメモが yomi.json に入る",
                "e2e で確認" in (work / "yomi.json").read_text(encoding="utf-8"),
            )
            page.locator("input[placeholder^='表記']").fill("TESTWORD")
            page.locator("input[placeholder^='読み']").fill("テ'スト")
            page.get_by_role("button", name="追加").click()
            page.wait_for_selector(".toast.ok")
            check(
                "語を追加できる",
                "TESTWORD" in (work / "yomi.json").read_text(encoding="utf-8"),
            )

            # 6. 素材
            page.locator(".chip", has_text="素材").click()
            page.wait_for_selector(".card")
            card = page.locator(".card").first
            card.locator("select").select_option("出典表示")
            card.get_by_role("button", name="保存").click()
            page.wait_for_selector(".toast.ok")
            check(
                "素材の状態が assets.json に入る",
                "出典表示" in (work / "assets.json").read_text(encoding="utf-8"),
            )
            check(
                "素材のサムネが読み込める",
                page.evaluate(
                    "() => [...document.querySelectorAll('.card img')].every(i => i.complete && i.naturalWidth > 0)"
                ),
            )

            # 7. 動画のシーク
            page.locator(".chip", has_text="動画").click()
            page.wait_for_selector("video.player")
            page.wait_for_function(
                "() => document.querySelector('video.player').readyState >= 1"
            )
            page.get_by_role("link", name="0:08").click()
            page.wait_for_timeout(600)
            t = page.evaluate(
                "() => document.querySelector('video.player').currentTime"
            )
            check("動画の行リンクで再生位置が移る", 7.5 < t < 9.5, t)
            page.evaluate("() => document.querySelector('video.player').pause()")

            # 8. 行の音声
            page.locator(".chip", has_text="台本").click()
            page.wait_for_selector("textarea")
            page.get_by_role("button", name="▶ 聴く").nth(2).click()
            page.wait_for_timeout(1200)
            at = page.evaluate(
                "() => { const a = document.getElementById('voice'); return [a.currentTime, a.readyState]; }"
            )
            check(
                "行の音声を再生できる(その行の先頭から進む)",
                7.5 <= at[0] <= 12 and at[1] >= 2,
                at,
            )
            page.evaluate("() => document.getElementById('voice').pause()")

            # 9. 壊れた承認記録
            (work / "approvals.json").write_text("[1,2]", encoding="utf-8")
            page.reload()
            page.wait_for_selector(".banner.bad")
            check(
                "承認記録が壊れていると警告が出て承認ボタンが無効",
                page.get_by_role("button", name="承認", exact=True).is_disabled(),
            )

            check("ページの JS エラーが無い", not msgs, msgs)
            browser.close()
    finally:
        proc.terminate()
        proc.wait(10)
        shutil.rmtree(tmp, ignore_errors=True)

    ng = [n for n, ok in results if not ok]
    print(
        f"\n{len(results) - len(ng)}/{len(results)} 件 OK"
        + (f"、NG: {ng}" if ng else "")
    )
    return 1 if ng else 0


if __name__ == "__main__":
    sys.exit(main())
