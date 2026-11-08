# 自作ハーネス（custom プロファイル。凍結）の拡張を触るとき

> **凍結（[ADR-0030](../../../../docs/adr/0030-freeze-agent-stack-return-to-stock-pi.md)）した、自作のフルガード・`pis`・自作の拡張を触るときだけ読む。**
> 通常（stock プロファイルの pi）は、[ADR-0031](../../../../docs/adr/0031-evaluate-existing-extensions-first.md) に沿って、既存の拡張・設定で足りるかを先に評価する。
> ここの手順は、旧スキルの「現行のハーネスとの相性」と「自作して試験する」を、そのまま移したもの。

## 現行のハーネスとの相性を確かめる

次を `docs/spec/guard/pi-guard.md` と実コードで確認する。

- **判定と伏字化**: 拡張のツールは `guarded_*` の判定を通る。役割（`implementer` など）の `tools` に載せるか、判定の規則が要るか。
  `bash` を置き換える方式は、判定を迂回しないかを必ず見る
- **bg_run のようにコマンドを扱うツール**: bash と同じ判定（`decide`）に通すか
- **起動の違い**: `pis` は `-ne`（自動発見なし）で、自作は `[pi] own_extensions` から `-e` で足す。素の `pi` は自動発見で読む。
  サンドボックスの読み取り許可も一覧から生成される
- **システムプロンプトへの露出**: ツールには `promptSnippet`（必要なら `promptGuidelines`）を付けないとモデルが使い忘れる
- **pi の内部に頼る点**: 増やすなら [pi の内部の挙動に頼る点](../../../../docs/spec/guard/pi-guard.md#pi-の内部の挙動に頼る点) へ足す
- **Windows**: プロセス停止やパスの扱いが違う。実機で回せないなら未検証と明記する
- 既存の拡張（`todo` / `plan` / `btw` / `activity` / `subagents`）と機能・名前が重ならないか
- **同じ脅威を既存の仕組み（サンドボックス・判定器・確認）がすでに防いでいないか。** 防いでいるなら、重ねない
- 新機能が、利用者の今の操作（確認の回数、入力、表示）のどこを変えるか

提案は、防御の強さの違う 3 案を出す旧のひな形（[custom-harness-proposal.md](custom-harness-proposal.md)）を使う。

## 自作して試験する

- 置き場: `home/dot_pi/agent/extensions/<名前>/index.ts`。一覧は `home/dot_config/agents/common.toml.tmpl` の `[pi] own_extensions` の 1 か所
- 判定器のルールや誘導を変えたら、`docs/spec/guard/pi-decide.md` と golden（`scripts/agents/export_decide_golden.py`）も合わせる
- 偽のモデル（`test/agents/pi/faux.ts`）で、決まったツール呼び出しを通信なしに出させて試す。
  既存の試験（`test/agents/test_pi_harness.py` / `test_pi_harness_extensions.py` / `test_pi_subagents.py`）が型になる
- 試験する観点: ツールがシステムプロンプトに載る / 判定（allow・deny・ask）/ 伏字化 / `/reload` 後の状態 / 異常系
- **使い勝手の観点**: 確認の回数・メッセージの分かりやすさ・失敗時の回復が、見込みどおりかを確かめる。
  数えられるものは試験で数え、数えられないものは実機で確かめる項目へ足す
- 実行（pi が無い環境では skip になる。**skip は通過ではない**ので、skip 件数を必ず報告する）:

  ```bash
  uv run --with pytest --with pyyaml --no-project pytest test/agents/ -q
  uv run pre-commit run --files <変更したファイル>
  mise exec -- python3 scripts/lint_templates.py
  ```

- 偽のモデルで確かめられないこと（TUI の表示、実際のモデルの使い分け、Windows）は、
  `docs/spec/guard/pi-guard.md` の「実機で確認する項目」へ未確認として足す。確かめていない結果を書かない

## 記録（終わるとき）

公式に明示が無い挙動を実測したら `pi-upstream.md` の表 B へ（原則は試験で固定）。自作の拡張は `guard/pi-guard.md`（自作の拡張の表）、
実機でしか確かめられないものは「実機で確認する項目」へ。
