# 静的 deny の pip を `execute.before` で説明付きに止める

- **観測日**: 2026-10-03
- **対象**: OpenCode `v2.0.14` / WSL2 Ubuntu
- **方法**: `mise run opencode:probe`（`opencode run --standalone`、モデル `github-copilot/claude-opus-5`、
  実 DB を汚さない）。`generate.py` で作った設定と `guide-plugin` を `.tmp/early/` に置き、
  `OPENCODE_PROBE_CONFIG` で渡した（記録後に削除）

## 問い

V2 は config の静的 deny に当たると plugin の `permission.evaluate` を呼ばず、モデルには
`Permission denied: shell` だけが返る（[hook の呼ばれ方](hook-order.md)）。
そのため `pip` / `pip3` の静的 deny には uv への誘導文を付けられなかった
（[ADR-0013](../../../adr/0013-opencode-shell-guard-inside-ocs.md)）。静的 deny を変えずに、
**`tool.execute.before` で例外を投げて説明付きで止められるか**。

## 実装

- `common.toml.tmpl` の pip の guide 規則に `early = true` を付け、`generate.py` が
  `rules.json` の `guide[].early` へ渡す（規則名の決め打ちはしない）
- `guide-plugin/index.js` の `execute.before` が、shell ツールで bypass エージェントでなければ、
  `early` の規則を生のコマンドへ当てる（`unless` も同じ）。当たれば `throw new Error(message)`
- `rules.json` が読めなければ `compiled` が空になり何もしない（後段の静的 deny が止める）

## 結果

投げた例外のメッセージは、モデルへは `{"error":{"type":"unknown","message":"<message>"},"content":[]}` の
形で届いた。静的 deny の `permission.rejected` とは `type` で区別できる。

| 項 | 設定・コマンド | 結果 |
| --- | --- | --- |
| a | 通常版（静的 pip deny あり）+ plugin、`pip install x` | **`execute.before` が静的 deny より先に走り**、`pip は使わないでください。…uv add…` がモデルへ届いた（`Permission denied: shell` ではない）。コマンドは実行されない |
| b1 | 通常版の静的 deny + plugin 無し、`pip install x` | `Permission denied: shell` で止まる |
| b2 | 同 + `rules.json` が構文不正（`{ broken`）、`pip install x` | plugin は読み込まれ、例外を投げずに `Permission denied: shell` で止まる |
| c1 | ocs 相当（pip の permission を除き既定 allow）、`pip --version` | 誘導文で止まる（実行されない） |
| c2 | 同 + `--auto` | c1 と同じ。差は無い |
| c3 | 同 + `--agent bypass`（`--auto` あり・なし） | 止まらず `pip 26.0.1 from … (python 3.13)` が実行された。`execute.before` の入力に `agent` が載っている |
| d1 | `uv pip --version` | 止まらない（uv 自身のエラーが返った＝実行された） |
| d2 | `echo "pip install"` | 止まらない（出力 `pip install`） |
| d3 | `git commit --allow-empty -m "use pip"`（workdir 指定） | 止まらない（コミットされた） |
| d4 | `ls && pip --version` | **止まる**（`ls` も実行されない） |
| e | 同一メッセージで並列に 3 呼び出し: `git commit …`、`pip --version`、`echo PARALLEL_OK` | `pip` だけが失敗。他の 2 つは実行され、結果が返った |

- d2 の `echo "pip install"` は行頭が `echo` なので規則に当たらず、止まらなかった（正規表現の限界で
  止まる例は今回見つからなかった）。行頭以外（`sh -c 'pip install x'` など）は実測していない
- d3 は最初 `cd <dir> && git commit …` で試したが、pip と無関係の `cd` の誘導（別の guide 規則）で
  止まったため、workdir 指定に変えた
- 前段は `python -m pip` なども止める（plugin に通した検査のみ。実機では `pip` / `pip3` だけを実測）

## 結論

- **方式は成立する。** 静的 deny を変えずに、通常版の `pip` / `pip3` にも uv への誘導文を付けられた。
  plugin が無い・壊れているときは従来どおり静的 deny が止める（b）
- `tool.execute.after` で結果へ説明を足す案は、a が成立したので試していない
- 他の guide 規則（`rm` など）はこの方式に移していない（`early` を付けた規則だけが前段の対象）
- 前段は `permission` を通らないので、`ask` の確認や `evaluate` の `message` 経路は使わない。
  誘導のための停止はエラー扱いでモデルへ返る

## 検査

`test/agents/test_guide_early_pip.py`（生成した `rules.json` を実際の plugin に通す。止める例・
止めない例・bypass・読めない `rules.json`）。

[調査記録一覧へ戻る](../../index.md)
