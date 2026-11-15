---
name: chezmoi-usage
description: "chezmoi 本体の使い方と落とし穴。source state の編集・属性接頭辞（dot_・private_・exact_・modify_・create_・run_once_・run_onchange_・symlink_・remove_）・テンプレート（.chezmoi.* 変数・関数・execute-template）・特殊ファイル（.chezmoiignore・.chezmoiremove・.chezmoiexternal・.chezmoidata・.chezmoiroot・.chezmoitemplates）・scripts の実行条件と適用順序・hooks・chezmoi update / apply / diff / init / doctor / managed / unmanaged / verify の挙動と限界を扱う。「chezmoi のスクリプトが走らない」「inconsistent state が出る」「.chezmoiignore が効かない」「modify_ の書き方」「chezmoi update で設定が変わらない」「このテンプレートを検査して」で使う。このリポジトリ固有の規約（番号体系・docs・試験の登録）は dotfiles-conventions を使う。chezmoi を使わないリポジトリや、dotfiles 以外の一般的なシェル・git の質問には使わない。"
---

# chezmoi-usage

chezmoi 本体の知識と落とし穴。**このリポジトリ固有の規約は [dotfiles-conventions](../dotfiles-conventions/SKILL.md)**（番号体系・コメントの書き分け・検証コマンド・docs）。ここは重複させず、chezmoi 一般のことだけを持つ。

確認した版: このリポジトリが使う **v2.67.0**（実測はこの版）。公式の最新は v2.74.1（2026-11-10）。差分は [sources.md](references/sources.md)。

## 最初に守ること

1. **事実と推測を分ける。** 各 references の `[docs]`（公式文書）・`[src]`（ソース）・`[実測]`（v2.67.0 を実際に動かした）・`[推測]` の印を保つ。印のない断定を足さない。
2. **編集は source state で行う。** `~/` の実ファイルや生成先は直接編集しない（編集したら `chezmoi add` / `re-add`。`.tmpl` には `re-add` が効かない）。
3. **`--dry-run` / `diff` を安全の証明にしない。** `modify_` スクリプトは dry-run でも実行され、hooks も実行される。scripts の効果は diff に出ない（[commands.md](references/commands.md#dry-run-と-diff-の限界)）。
4. **`chezmoi update` は `init` を呼ばない。** `chezmoi.toml`（`[data]`・`hooks`・`interpreters`）は `init` / `--init` のときだけ再生成される（[pitfalls.md](references/pitfalls.md#update-は-init-を呼ばない)）。
5. **`.chezmoiignore` はターゲットのパスで書く**（`dot_foo` ではなく `.foo`）。`.chezmoiremove` と source に同じターゲットを置くと、宛先に実在するとき `inconsistent state` で apply 全体が止まる（[pitfalls.md](references/pitfalls.md#chezmoiremove-と-source-の-inconsistent-state)）。

## 場面別の参照先

| 場面 | 読むもの |
| --- | --- |
| ファイル名の接頭辞・接尾辞（`dot_`・`exact_`・`modify_`・`create_`…）、順序の規則 | [attributes.md](references/attributes.md) |
| `.chezmoiignore`・`.chezmoiremove`・`.chezmoiexternal`・`.chezmoidata`・`.chezmoiroot`・`.chezmoiversion`・`.chezmoitemplates`・設定テンプレート | [special-files.md](references/special-files.md) |
| scripts の実行条件（`run_` / `once_` / `onchange_`）・適用順序・hooks・interpreters | [scripts-and-order.md](references/scripts-and-order.md) |
| テンプレートの変数・関数・ディレクティブ・検査 | [templates.md](references/templates.md) |
| コマンドの使い分け・`--dry-run` と `diff` の限界・Windows | [commands.md](references/commands.md) |
| 事故の型・症状から原因を引く | [pitfalls.md](references/pitfalls.md) |
| 出典 URL・取得日・版ごとの差分・調査で訂正した点・未確認 | [sources.md](references/sources.md) |

## 作業の型

- **テンプレートを書く・直す**: `chezmoi execute-template < file.tmpl`（設定テンプレートは `--init` を付ける）で描画して確かめる。このリポジトリでは `lint_templates.py` も要る（dotfiles-conventions）。
- **ファイルをソースへ足す**: 接頭辞は [attributes.md](references/attributes.md) の順序表に従う。迷ったら `chezmoi add` に任せ、生成された名前を見る。
- **scripts を足す・直す**: 実行条件と状態の持ち方（[scripts-and-order.md](references/scripts-and-order.md)）を先に読む。冪等にする。
- **挙動を疑う**: まず `chezmoi doctor`・`chezmoi data`・`chezmoi managed` / `ignored`・`-v`（詳細は `--debug`）。公式の版が違うときは [sources.md](references/sources.md) の差分を見る。
- **sandbox 内では `~/` が見えない**ので `chezmoi diff` / `status` は証拠にならない。一時の `-S <source> -D <dest> -c <config> --persistent-state <db>` で隔離して実測できる（[commands.md](references/commands.md#隔離して実測する)）。
