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
    (work / "brief.md").write_text("# 構想\n単眼 SLAM の紹介。\n", encoding="utf-8")
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
            page.goto(url + "#plan")
            page.wait_for_selector("pre")

            # 1. 承認は構成案と最終動画だけ。構成案を承認する(着手の許可)
            page.get_by_role("button", name="承認", exact=True).click()
            page.wait_for_selector(".toast.ok")
            check(
                "構成案を承認すると approvals.json に記録される",
                approvals().get("plan", {}).get("status") == "承認",
            )
            page.locator(".chip", has_text="台本").click()
            page.wait_for_selector("textarea")
            check(
                "台本タブには承認ボタンが無い(承認しない作業状態)",
                page.get_by_role("button", name="承認", exact=True).count() == 0,
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
            chip = page.locator(".chip", has_text="構成案").inner_text()
            check(
                "台本を直しても構成案の承認は古くならない",
                "古い" not in chip and "承認" in chip,
                chip,
            )

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
                any(
                    e.get("note") == "3 行目を確認" and e.get("line") == 3
                    for e in notes.values()
                ),
                notes,
            )

            # 4. 外部変更後の承認は 409
            page.locator(".chip", has_text="構成案").click()
            page.wait_for_selector("pre")
            narr = work / "brief.md"
            narr.write_text(
                narr.read_text(encoding="utf-8") + "追記\n", encoding="utf-8"
            )
            page.get_by_role("button", name="承認", exact=True).click()
            page.wait_for_selector(".toast.bad")
            check(
                "外部変更後の承認は拒否される",
                "変わりました" in page.locator(".toast.bad").first.inner_text(),
            )
            check(
                "拒否された承認は記録されない",
                approvals()["plan"]["hash"] != sha12(narr),
            )
            page.wait_for_timeout(800)  # 画面が最新を読み直す
            page.get_by_role("button", name="承認", exact=True).click()
            page.wait_for_selector(".toast.ok")
            check(
                "最新を表示した後は承認できる",
                approvals()["plan"]["hash"] == sha12(narr),
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

            # 7a. 公開前チェック: 機械の項目の結果と、人が確かめる 4 項目。通らない間は承認できない
            rel = page.locator("#release").inner_text()
            check(
                "公開前チェックに機械の項目と人の確認 4 項目が出る",
                "公開前チェック" in rel
                and "読み辞書に候補が残っていない" in rel
                and page.locator("#release input[type=checkbox]").count() == 4,
                rel[:120],
            )
            for i in range(4):
                page.locator("#release input[type=checkbox]").nth(i).check()
            check(
                "人の確認を全部つけても、機械のチェックが通らない間は承認できない",
                page.get_by_role("button", name="承認", exact=True).is_disabled(),
            )
            os.utime(work / "video.mp4", None)  # 確かめた後に、動画が差し替わった
            try:
                page.wait_for_function(
                    "() => document.querySelectorAll('#release input[type=checkbox]:checked').length === 0",
                    timeout=6000,
                )
                cleared = True
            except Exception:
                cleared = False
            check("確認した後に動画が変わると、人の確認のチェックが外れる", cleared)

            # 7b. 指摘を保存しても、動画の要素・再生位置・再生状態を保つ
            page.evaluate(
                "() => { const v = document.querySelector('video.player');"
                " v.dataset.keep = '1'; v.play(); }"
            )
            page.wait_for_timeout(500)
            before = page.evaluate(
                "() => document.querySelector('video.player').currentTime"
            )
            note_box = page.locator("#vl1 input[type=text]")
            note_box.fill("動画を見て気づいた点")
            note_box.blur()
            page.wait_for_function(
                "() => [...document.querySelectorAll('.toast')]"
                ".some(t => t.textContent.includes('保存しました'))"
            )
            page.wait_for_timeout(300)
            kept = page.evaluate(
                "() => { const v = document.querySelector('video.player');"
                " return [v.dataset.keep, v.currentTime, v.paused]; }"
            )
            check("指摘を保存しても動画の要素が作り直されない", kept[0] == "1", kept)
            check(
                "指摘を保存しても再生位置が戻らない",
                kept[1] >= before - 0.1,
                (before, kept[1]),
            )
            check("指摘を保存しても再生が続く", kept[2] is False, kept)
            page.evaluate("() => document.querySelector('video.player').pause()")
            note_box = page.locator("#vl1 input[type=text]")
            note_box.fill("")
            note_box.blur()
            page.wait_for_timeout(500)

            # 7c. 外でファイルが変わったとき、画面が追従し、入力中の文章は残る
            page.locator(".chip", has_text="台本").click()
            page.wait_for_selector("textarea")
            first = page.locator("textarea").nth(0).input_value()
            second = page.locator("textarea").nth(1).input_value()
            page.locator("textarea").nth(1).fill("入力中の文章です。")
            original = (work / "narration.txt").read_text(encoding="utf-8")
            (work / "narration.txt").write_text(
                original.replace(first, first + "追記", 1), encoding="utf-8"
            )
            try:
                page.wait_for_function(
                    "(t) => document.querySelectorAll('textarea')[0].value === t",
                    arg=first + "追記",
                    timeout=6000,
                )
                followed = True
            except Exception:
                followed = False
            check("外で台本が変わると画面が数秒で追従する", followed)
            kept_text = page.locator("textarea").nth(1).input_value()
            check(
                "追従しても入力中の文章が残る",
                kept_text == "入力中の文章です。",
                kept_text,
            )
            page.locator("textarea").nth(1).fill(second)

            # 7d. 古い画面から指摘を書いて 409 になっても、入力した文章を失わない
            (work / "narration.txt").write_text(
                original.replace(first, first + "別の追記", 1), encoding="utf-8"
            )
            note_in = page.locator("input[placeholder^='指摘']").nth(2)
            note_in.fill("409 でも消えない指摘")
            note_in.blur()  # 追従の前に送ると 409、追従後なら保存される。どちらでも文章は残る
            page.wait_for_timeout(3500)
            shown = page.locator("input[placeholder^='指摘']").nth(2).input_value()
            check(
                "409 でも入力した指摘が消えない", shown == "409 でも消えない指摘", shown
            )
            note_in = page.locator("input[placeholder^='指摘']").nth(2)
            note_in.fill("")
            note_in.blur()
            page.wait_for_timeout(800)
            (work / "narration.txt").write_text(original, encoding="utf-8")
            page.wait_for_timeout(2800)  # 元の台本に戻し、画面の追従を待つ

            # 7e. 指摘の状態(対応済み)と、行が増えても同じ本文の行へついていくこと
            def notes_data():
                return json.loads((work / "notes.json").read_text(encoding="utf-8"))[
                    "entries"
                ]

            note_in = page.locator("input[placeholder^='指摘']").nth(2)
            note_in.fill("状態の確認")
            note_in.blur()
            page.get_by_role("button", name="✓ 対応済み").first.wait_for()
            page.get_by_role("button", name="✓ 対応済み").first.click()
            page.wait_for_selector("input.fixed")
            check(
                "直した指摘を「対応済み」にでき、画面に残る",
                any(e.get("status") == "fixed" for e in notes_data().values()),
                notes_data(),
            )
            t3 = page.locator("textarea").nth(2).input_value()
            raw2 = (work / "narration.txt").read_text(encoding="utf-8")
            (work / "narration.txt").write_text(
                raw2.replace("- " + first, "- 追加です。\n- " + first, 1),
                encoding="utf-8",
            )
            try:
                page.wait_for_function(
                    "(t) => { const f = document.querySelector('input.fixed');"
                    " return document.querySelectorAll('tbody tr').length === 4 && !!f"
                    " && f.closest('tr').querySelector('textarea').value === t; }",
                    arg=t3,
                    timeout=6000,
                )
                followed = page.evaluate(
                    "() => { const rows = [...document.querySelectorAll('tbody tr')];"
                    " return rows.findIndex(r => r.querySelector('input.fixed')) + 1; }"
                )
            except Exception:
                followed = -1
            check("行が増えても指摘は同じ本文の行へついていく", followed == 4, followed)
            (work / "narration.txt").write_text(raw2, encoding="utf-8")
            page.wait_for_function(
                "() => document.querySelectorAll('tbody tr').length === 3", timeout=6000
            )
            page.get_by_role("button", name="消す").first.click()
            page.wait_for_function(
                "() => document.querySelectorAll('input.fixed').length === 0"
            )
            page.wait_for_timeout(500)

            # 7f. 未保存の入力(下書き)は、タブを移っても、行が増えても同じ本文の行へ戻り、
            #     行き場が無くなれば退避表示される
            page.locator(".chip", has_text="台本").click()
            page.wait_for_selector("textarea")
            raw7f = (work / "narration.txt").read_text(encoding="utf-8")
            first7 = page.locator("textarea").nth(0).input_value()
            second7 = page.locator("textarea").nth(1).input_value()
            page.locator("textarea").nth(1).fill("下書きの本文です。")
            page.locator(".chip", has_text="読み").click()
            page.wait_for_timeout(300)
            page.locator(".chip", has_text="台本").click()
            page.wait_for_selector("textarea")
            back = page.locator("textarea").nth(1).input_value()
            check(
                "別のタブへ移って戻っても、未保存の入力が残る",
                back == "下書きの本文です。",
                back,
            )
            (work / "narration.txt").write_text(
                raw7f.replace("- " + first7, "- 先頭へ足した行です。\n- " + first7, 1),
                encoding="utf-8",
            )
            try:
                page.wait_for_function(
                    "() => document.querySelectorAll('textarea').length === 4"
                    " && document.querySelectorAll('textarea')[2].value === '下書きの本文です。'",
                    timeout=6000,
                )
                followed = True
            except Exception:
                followed = False
            check("行が増えても、未保存の入力は元の本文の行へついていく", followed)
            (work / "narration.txt").write_text(
                raw7f.replace("- " + second7, "- 全く別の本文に変わりました。", 1),
                encoding="utf-8",
            )
            try:
                page.wait_for_selector("#orphans", timeout=6000)
                orphan = page.locator("#orphans").inner_text()
            except Exception:
                orphan = ""
            check(
                "対象の行が変わって行き場が無くなった入力は、失わずに退避表示される",
                "下書きの本文です。" in orphan,
                orphan + page.evaluate("() => JSON.stringify([...drafts])"),
            )
            page.get_by_role("button", name="破棄").first.click()
            (work / "narration.txt").write_text(raw7f, encoding="utf-8")
            page.wait_for_function(
                "() => document.querySelectorAll('textarea').length === 3 && !document.getElementById('orphans')",
                timeout=6000,
            )

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
            rev1 = page.evaluate("() => document.getElementById('voice').dataset.rev")
            wav = work / "voiceover.wav"
            wav.write_bytes(
                wav.read_bytes() + b"\x00\x00"
            )  # 再合成で音声が差し替わった
            page.wait_for_timeout(3000)
            page.get_by_role("button", name="▶ 聴く").nth(2).click()
            page.wait_for_timeout(400)
            rev2 = page.evaluate("() => document.getElementById('voice').dataset.rev")
            check(
                "音声が差し替わったら、試聴は新しい音声を読み込み直す",
                bool(rev1) and bool(rev2) and rev1 != rev2,
                (rev1, rev2),
            )
            page.evaluate("() => document.getElementById('voice').pause()")

            # 9. 壊れた承認記録
            (work / "approvals.json").write_text("[1,2]", encoding="utf-8")
            page.goto(url + "#plan")
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
