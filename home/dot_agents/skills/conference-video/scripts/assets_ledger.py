#!/usr/bin/env python3
"""素材台帳(assets.json): 取得した画像・動画の出典・ライセンス・公開可否を管理する。

台帳は JSON(`{"schema": 1, "entries": {ファイル: {...}}}`)。人が手で編集せず、このモジュールの CLI か
確認サーバの画面で直す(ADR-0003)。書き込みは state_store を通るので、サーバと CLI が同時に書いても
更新は消えない。Excel で見たいときは `export` で CSV を書き出す(取り込みはしない)。

項目(値は文字列): 出典URL, 作者, ライセンス, 状態, 場面, メモ, 取得日, 種別, 書誌, 位置
- ファイル(キー)は台帳のあるフォルダからの相対パス
- 状態 `確認済み`: 出典とライセンスを確認し、使ってよいと判断した素材(CC0 / CC BY /
  Pexels など許諾があるもの、著者本人が許可したもの)
- 状態 `出典表示`: 許諾は未確認だが、出典を明示して使う素材(利用者の方針。
  条件は references/attribution.md)。作者(提供元)と取得日が要る
- 状態 `仮`: 私的な検証だけに使う素材(公開前に差し替える)
- 種別: CC素材 / 論文の図 / 公式動画 / その他(空でもよい)。論文の図・公式動画は「引用」で、
  書誌(論文の書式の出典)と位置(Fig. 番号、ページ、動画の時刻)が要り、画面の出典は書誌と位置で出す

コマンド(LEDGER は assets.json):
  init LEDGER                    空の台帳を作る(既存なら止まる)
  add LEDGER FILE --url U ...    素材を足す(既存のファイルなら競合で止まる。状態の既定は仮)
  set LEDGER FILE --note ...     指定した項目だけを直す
  rm LEDGER FILE                 台帳のレコードだけを消す(素材ファイルは消さない)
  list LEDGER                    一覧
  check LEDGER [--public]        ファイルの有無・出典URL・ライセンス・(出典表示なら)作者と取得日・
                                 (引用なら)書誌と位置を検査する。--public は 仮、およびライセンス不明で
                                 状態が「確認済み」でも「出典表示」でもない素材があれば止める
  credits LEDGER                 動画の説明文に入れる出典の行を出す(仮・出典表示には印を付ける)
  export LEDGER --out FILE.csv   Excel 用の CSV(BOM 付き)に書き出す

画面に出す短い出典は short_credit(row)(script.py から import する)。

終了コード: 0 = 問題なし、1 = 指摘あり・該当なし、2 = 入力が不正・書き込み失敗、3 = 他の書き手と競合。
"""

from __future__ import annotations

import argparse
import csv
import sys
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))

import state_store  # noqa: E402

FIELDS = [
    "出典URL",
    "作者",
    "ライセンス",
    "状態",
    "場面",
    "メモ",
    "取得日",
    "種別",
    "書誌",
    "位置",
]
HEADER = ["ファイル", *FIELDS]
CONFIRMED, ATTRIBUTION, PROVISIONAL = "確認済み", "出典表示", "仮"
STATUSES = (CONFIRMED, ATTRIBUTION, PROVISIONAL)
KINDS = ("", "CC素材", "論文の図", "公式動画", "その他")
CITATION_KINDS = ("論文の図", "公式動画")


def validate_entry(name: str, e) -> None:
    """1 点の検証(state_store の validate に渡す)。不正なら ValueError。"""
    if not name.strip():
        raise ValueError("ファイル名が空")
    if not isinstance(e, dict):
        raise ValueError("値は辞書")
    for k, v in e.items():
        if k not in FIELDS:
            raise ValueError(f"未知の項目: {k!r}")
        if not isinstance(v, str):
            raise ValueError(f"{k} は文字列")
    if e.get("状態", PROVISIONAL) not in STATUSES:
        raise ValueError(f"状態は {' / '.join(STATUSES)}: {e.get('状態')!r}")
    if e.get("種別", "") not in KINDS:
        raise ValueError(
            f"種別は {' / '.join(k or '(空)' for k in KINDS)}: {e.get('種別')!r}"
        )


def store(path: Path | str) -> state_store.Store:
    return state_store.Store(path, validate=validate_entry)


def rows_from_entries(entries: dict) -> list[dict]:
    """窓口から読んだ生の entries を、行(「ファイル」を含む辞書。既定値を補う)にする。"""
    out = []
    for name, e in entries.items():
        row = {"ファイル": name, **{f: "" for f in FIELDS}, **{k: v.strip() for k, v in e.items()}}
        row["状態"] = row["状態"] or PROVISIONAL
        out.append(row)
    return out


def load(path: Path | str) -> list[dict]:
    """台帳を行のリスト(「ファイル」を含む辞書)で返す。無ければ FileNotFoundError、壊れていれば ValueError。"""
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"素材台帳が無い: {p}")
    try:
        entries = store(p).read().entries
    except state_store.Corrupt as e:
        raise ValueError(str(e)) from e
    return rows_from_entries(entries)


def is_citation(row: dict) -> bool:
    return row.get("種別", "") in CITATION_KINDS


def check(
    rows: list[dict], base: Path, public: bool = False
) -> tuple[list[str], list[str]]:
    """(指摘, 警告)を返す。"""
    issues, warns = [], []
    for r in rows:
        name = r["ファイル"]
        if not (base / name).is_file():
            issues.append(f"{name}: ファイルが無い")
        if not r["出典URL"].startswith(("http://", "https://")):
            issues.append(f"{name}: 出典URLが無い(http で始まる URL)")
        if not r["ライセンス"]:
            issues.append(f"{name}: ライセンスが空(分からなければ「不明」と書く)")
        if r["状態"] == ATTRIBUTION:
            if not r["作者"]:
                issues.append(f"{name}: 出典表示には作者(提供元)が要る")
            if not r["取得日"]:
                issues.append(f"{name}: 出典表示には取得日が要る")
        if is_citation(r):
            if not r["書誌"]:
                issues.append(
                    f"{name}: 引用({r['種別']})には書誌(論文の書式の出典)が要る"
                )
            if not r["位置"]:
                issues.append(
                    f"{name}: 引用({r['種別']})には位置(Fig. 番号・ページ・時刻)が要る"
                )
        if public:
            if r["状態"] == PROVISIONAL:
                issues.append(
                    f"{name}: 状態が「仮」(公開用は確認済みまたは出典表示の素材だけ)"
                )
            if r["ライセンス"] == "不明" and r["状態"] != ATTRIBUTION:
                issues.append(
                    f"{name}: ライセンスが不明(公開用は差し替えるか、状態を出典表示にする)"
                )
        elif r["状態"] == PROVISIONAL:
            warns.append(f"{name}: 状態が「仮」(私的な検証だけ。公開前に差し替える)")
        if r["状態"] == ATTRIBUTION:
            warns.append(
                f"{name}: 出典表示で使用(許諾は未確認。画面に出典を出し、条件は references/attribution.md)"
            )
    return issues, warns


def citation_text(row: dict) -> str:
    """論文の書式の出典(書誌 + 位置)。"""
    cite, loc = row.get("書誌", ""), row.get("位置", "")
    return f"{cite}, {loc}" if cite and loc else cite or loc


def short_credit(row: dict) -> str:
    """画面の隣に小さく出す出典。引用(書誌がある論文の図・公式動画)は「書誌, 位置」、
    ライセンスが分かれば「作者 / ライセンス」、不明・空なら「出典: 作者 (取得元のドメイン)」。"""
    if is_citation(row) and row.get("書誌"):
        return citation_text(row)
    who = row.get("作者") or "作者不明"
    lic = row.get("ライセンス") or ""
    if lic and lic != "不明":
        return f"{who} / {lic}"
    host = urlparse(row.get("出典URL", "")).netloc.removeprefix("www.")
    return f"出典: {who} ({host})" if host else f"出典: {who}"


def credit_lines(rows: list[dict]) -> list[str]:
    out = []
    for r in rows:
        mark = {PROVISIONAL: " (仮)", ATTRIBUTION: " (出典表示)"}.get(r["状態"], "")
        label = r["場面"] or r["ファイル"]
        if is_citation(r) and r["書誌"]:
            out.append(f"素材: {label}: {citation_text(r)}({r['出典URL']}){mark}")
            continue
        who = r["作者"] or "作者不明"
        out.append(
            f"素材: {label}: {who} / {r['ライセンス'] or '不明'}({r['出典URL']}){mark}"
        )
    return out


# ───────────── コマンド ─────────────


def _edit(path: Path, name: str, make) -> bool:
    """`make(現在の値)` で新しい値(削除は None)を作って窓口で更新する。競合したら読み直して数回やり直す。
    戻り値は「既に存在した」か。"""
    st = store(path)
    for _ in range(3):
        cur = st.read().entries.get(name)
        try:
            st.update(name, cur, make(cur))
            return cur is not None
        except state_store.Conflict:
            continue
    raise state_store.Conflict(None, f"「{name}」が他の書き手と競合し続けている")


def _fields_from_args(a) -> dict:
    mapping = {
        "url": "出典URL",
        "author": "作者",
        "license": "ライセンス",
        "status": "状態",
        "scene": "場面",
        "note": "メモ",
        "date": "取得日",
        "kind": "種別",
        "citation": "書誌",
        "locator": "位置",
    }
    return {
        mapping[k]: getattr(a, k) for k in mapping if getattr(a, k, None) is not None
    }


def cmd_add(a, path: Path) -> int:
    fields = {
        "状態": PROVISIONAL,
        "取得日": date.today().isoformat(),
        **_fields_from_args(a),
    }
    entry = {f: fields.get(f, "") for f in FIELDS}
    store(path).update(a.name, None, entry)  # 既存なら Conflict(終了コード 3)
    print(f"追加: {a.name}({entry['状態']})")
    return 0


def cmd_set(a, path: Path) -> int:
    changes = _fields_from_args(a)
    if not changes:
        print("エラー: 直す項目を指定してください(--status など)")
        return 2
    existed = _edit(
        path, a.name, lambda cur: None if cur is None else {**cur, **changes}
    )
    print(f"直した: {a.name}" if existed else f"台帳に無い: {a.name}")
    return 0 if existed else 1


def cmd_rm(a, path: Path) -> int:
    existed = _edit(path, a.name, lambda cur: None)
    print(
        f"台帳から外した(素材ファイルは残す): {a.name}"
        if existed
        else f"台帳に無い: {a.name}"
    )
    return 0 if existed else 1


def cmd_export(a, path: Path) -> int:
    rows = load(path)
    out = Path(a.out)
    with out.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(HEADER)
        for r in rows:
            w.writerow([r[h] for h in HEADER])
    print(f"書き出し: {out}({len(rows)} 点。Excel 用。取り込みはしない)")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    def edit_fields(p):
        p.add_argument("--url")
        p.add_argument("--author")
        p.add_argument("--license")
        p.add_argument("--status")
        p.add_argument("--scene")
        p.add_argument("--note")
        p.add_argument("--date")
        p.add_argument("--kind")
        p.add_argument("--citation", help="書誌(論文の書式の出典)")
        p.add_argument("--locator", help="位置(Fig. 番号・ページ・動画の時刻)")

    p = sub.add_parser("init")
    p.add_argument("file")
    p = sub.add_parser("add")
    p.add_argument("file")
    p.add_argument("name")
    edit_fields(p)
    p = sub.add_parser("set")
    p.add_argument("file")
    p.add_argument("name")
    edit_fields(p)
    p = sub.add_parser("rm")
    p.add_argument("file")
    p.add_argument("name")
    p = sub.add_parser("list")
    p.add_argument("file")
    p = sub.add_parser("check")
    p.add_argument("file")
    p.add_argument("--public", action="store_true")
    p = sub.add_parser("credits")
    p.add_argument("file")
    p = sub.add_parser("export")
    p.add_argument("file")
    p.add_argument("--out", required=True)
    a = ap.parse_args(argv)

    path = Path(a.file)
    try:
        if a.cmd == "init":
            if not store(path).initialize():  # 存在確認と作成を同じロックの中で
                print(f"エラー: {path} が既にある(上書きしない)")
                return 2
            print(f"作成: {path}")
            return 0
        if a.cmd in ("add", "set", "rm"):
            return {"add": cmd_add, "set": cmd_set, "rm": cmd_rm}[a.cmd](a, path)
        rows = load(path)
        if a.cmd == "export":
            return cmd_export(a, path)
        if a.cmd == "list":
            for r in rows:
                print(
                    f"{r['ファイル']}\t{r['状態']}\t{r['種別']}\t{short_credit(r)}\t{r['場面']}"
                )
            print(f"({len(rows)} 点)", file=sys.stderr)
            return 0
        if a.cmd == "credits":
            print("\n".join(credit_lines(rows)))
            return 0
        issues, warns = check(rows, path.resolve().parent, a.public)
        for w in warns:
            print(f"注意: {w}")
        for i in issues:
            print(f"指摘: {i}")
        print(f"{len(rows)} 点、指摘 {len(issues)} 件")
        return 1 if issues else 0
    except state_store.Conflict as e:
        print(f"エラー(競合): {e}")
        return 3
    except (ValueError, FileNotFoundError, state_store.StoreError) as e:
        print(f"エラー: {e}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
