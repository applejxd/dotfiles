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

## 5. `evaluate` のイベントに `agent` が載る

`permission.evaluate` のイベントは次の形。

```text
sessionID / agent / action / resources / metadata / source / effect
```

`bypass` エージェントで走らせると `agent:"bypass"` と `effect:"allow"` が
同時に届く。

| 実行 | `execute.before` の `agent` | `evaluate` の `agent` | `effect` |
| --- | --- | --- | --- |
| 既定 | `build` | `build` | `ask` |
| `--agent bypass` | `bypass` | `bypass` | `allow` |

**これで `effect === "allow"` による bypass 判定を置き換えられる。**
effect で見分けると、静的 allow を含む呼び出し（`cd x && git log`）まで
誘導が素通りしてしまう。名前で見れば誘導を allow にも効かせつつ、
bypass だけを逃がせる。

`source` は `{type:"tool", messageID, id}` で、`id` が
`tool.execute.before` の `id` と一致する（生コマンドの相関に使う）。

## 6. 配備を確かめる手順（踏んだ落とし穴つき）

サーバ側 plugin は常駐サービスのプロセス内で動く。`chezmoi apply` だけでは
反映されず、**`opencode service restart` が要る**（`Ctrl+X` → `v`）。

反映されたかを確かめるには、サービスの**起動時刻**が `rules.json` の更新より
後であることを見る。ここで 2 回誤った。

| 誤り | なぜ駄目か | 正しい方法 |
| --- | --- | --- |
| `stat -c %Y /proc/<pid>` を起動時刻として使う | **起動時刻ではない。** 実行中に動く | `ps -o lstart= -p <pid>` |
| `pgrep -f "opencode serve --service"` で PID を取る | `-f` はコマンドライン全体に当たるため、**その文字列を含む自分自身のシェル**にヒットする。`head -1` が毎回「たった今起動した」偽の PID を返す | `ps -C opencode -o pid,lstart,args` |

この 2 つで「再起動を確認した」と 3 回誤判定し、**誘導が一度も効いていない
状態を「配備済み」と記録した**。`execute.after` の hook は別経路で再読み込み
されていたため動いており、それが誤りを覆い隠した。

**`evaluate` が効かないときは、まず再起動を疑う。** 自動承認モードや hook の
未発火を疑う前に、`ps -C opencode` で起動時刻を見る。

### 効いているかの最小確認

配備済みの規則を 1 つ叩く。deny が返れば `evaluate` は生きている。

```sh
head -1 README.md   # 誘導が効いていれば permission.rejected が返る
```

## 7. 計装の手順

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
