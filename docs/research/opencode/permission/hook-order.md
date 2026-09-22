# permission hook の呼ばれ方と action の種類

- **観測日**: 2026-09-22
- **対象**: OpenCode `v2.0.12`
- **方法**: 配備中の `guide-plugin` を計装した複製を `.tmp` に置き、
  `opencode run --standalone --auto` で 1 コマンドずつ実行して記録

[相関と承認要求](../plugin/correlation.md)の続き。あちらは「生コマンドを
どう取るか」で、ここは「hook がいつ・何回呼ばれるか」。

## 1. 呼ばれる順序

`tool.execute.before` は **permission の評価より前**に走る。

```text
setup
execute.before   cmd="cd docs && echo hi"
evaluate         action=shell  ask → deny
execute.after    status=error
```

`execute.before` で生コマンドを `id` に紐づけ、`evaluate` で引く設計
（[相関](../plugin/correlation.md)）はこの順序に依存している。**実測で裏づいた。**

## 2. 1 回のシェル呼び出しで `evaluate` が複数回走る

ワークスペース外に触れると `external_directory` が**別の action として**
立つ。`cd /tmp && echo hi` の記録。

```text
execute.before   cmd="cd /tmp && echo hi"
evaluate         action=external_directory  ask → ask
evaluate         action=shell               ask → deny
execute.after    status=error
```

ワークスペース内（`cd docs && echo hi`）では `shell` の 1 回だけになる。

**plugin は `action` を必ず見ること。** `guide-plugin` は
`if (e.action !== "shell") return` を先頭に置いているので影響を受けないが、
これが無いと外部ディレクトリの確認まで誘導メッセージで潰す。

### 「許可したのに deny された」の正体

対話中に `cd /tmp && echo hi` を実行したとき、ユーザには確認が出て、
許可したあとに誘導の deny が返った。**確認は `external_directory` のもので、
誘導の deny とは別の permission。**順序の不具合ではない。

誘導の `deny` は**確認を出さずに止まる**（`--auto` の記録で `shell` の
`evaluate` が 1 回で `deny` に変わり、ダイアログを経ていない）。

## 3. `--auto` でも plugin の `deny` は効く

`before":"ask"` を `deny` に変えた結果、コマンドは実行されず
`execute.after` が `status=error` になった。
[ask と並列バッチ](../ask-and-parallel-batch.md)の「自動実行で効くのは deny
だけ」と整合する。

## 4. deny のメッセージはモデルへ届き、乗り換えが起きる

`cd docs && echo hi` を deny したあと、エージェントは同じターン内で
`echo hi` を実行し直した。

```text
execute.before   cmd="cd docs && echo hi"   → deny
execute.before   cmd="echo hi"              → ask（自動承認）→ completed
```

誘導が**代替案の提示として機能している**ことの実測。

## 5. 計装の手順

配備物には触らず、`.tmp` に複製を置いて `plugins` で絶対パス指定する。

```jsonc
// .tmp/opencode/probe/cfg/opencode.json
{"permissions": [/* 実環境から引き継ぐ */],
 "plugins": ["/abs/path/.tmp/opencode/probe/plugin"]}
```

```sh
env -u OPENCODE_CONFIG OPENCODE_CONFIG_DIR=<probe cfg> OPENCODE_DB=<seed> \
  opencode run --standalone --auto --model <model> '<prompt>'
```

**`OPENCODE_CONFIG` を外すこと。** 残すと実環境の global config が優先され、
計装版ではなく配備中の plugin が読まれる
（[試験環境の隔離方法](../test-isolation.md)）。

## 再確認すべき情報源

- `external_directory` 以外にどんな action があるか（**未調査**）
- `evaluate` が同一コマンドで 2 回以上 `shell` を評価する条件（**未確認**）

[調査記録一覧へ戻る](../../index.md)
