# OpenCode V2 plugin API の実測（permission hook / fail-open）

> **調査日: 2026-09-21**
> **対象: `opencode v2.0.10`（`@opencode/plugin` 2.0.11 世代）**
>
> 隔離環境（`XDG_CONFIG_HOME` を差し替え + `--standalone`）で実行した実測。
> 実環境の `~/.config/opencode/` には一切触れていない。

## 0. 本書の用途

[プラグイン生態系の棚卸し](opencode-plugins.md) で
「既製プラグインに乗る道は無い」と判明したため、
**自作するとして技術的に成立するか**を実機で確認した。

判定したいのは 1 点。
[エージェント権限仕様](../spec/agent-permissions.md#opencode-v2-の扱い) の
`check_bash.py` 相当（意味解析による deny / ask）を OpenCode へ載せられるか。

## 1. 結論

| 検証 | 結果 |
| --- | --- |
| プラグインのロード方式 | `.opencode/plugins/*.js` が**自動ロード**。`@opencode/plugin` の import 不要 |
| 生コマンドを取れるか | **取れる**（`tool.hook("execute.before")`） |
| cwd を取れるか | **取れる**（`shell.hook("create.before")`） |
| permission イベントと相関できるか | **できる**（`source.id` が tool call id と一致） |
| hook から deny できるか | **できる**。理由文字列もエージェントへ届く |
| hook 内の例外 | **fail-closed**（実行が止まる） |
| プラグインのロード失敗 | **fail-open**（無防備で実行される）。ただし WARN ログには出る |

**`check_bash.py` 相当の移植は技術的に成立する。**
ただし fail-open の性質上、プラグインを**唯一の防御層にしてはいけない**。
生成済みの静的 permission リストが土台として常に必要になる。

## 2. 検証環境

```console
mkdir -p .tmp/omo-eval/{config/opencode,proj/.opencode/plugins,out}
cd .tmp/omo-eval/proj
export XDG_CONFIG_HOME="$PWD/../config"
opencode run --standalone --auto --log-level error '<プロンプト>'
```

`--standalone` で共有バックグラウンドサービスに触れず、
`XDG_CONFIG_HOME` でグローバル設定を隔離した。
プローブは観測とテスト用の deny のみで、実スクリプトは呼んでいない。

## 3. プラグインの最小形

V2 のローダは次を要求する（ロード失敗時の WARN が契約を明示していた）。

> Plugin must export a default definition with an id and an **effect or setup** function.

つまり **`@opencode/plugin` を import しなくても動く**。
依存ゼロの素の ES module で足りる。

```js
export default {
  id: "probe",
  async setup(ctx) { /* ... */ },
}
```

`.opencode/plugins/` 配下は `opencode.json` への登録なしで自動ロードされた
（`ctx.app.version` = `2.0.10`、`ctx.location.directory` = プロジェクト directory）。

## 4. イベントの発火順と中身

`echo one && echo two` を実行させたときの実測（プローブが記録した生 JSON）。

```json
{"ev":"tool.before","data":{"tool":"shell","id":"call_ye8Rz8CQyj2JzJPk9N6gGYIw",
 "messageID":"msg_0c0bb5b76001I15dzbJ3Zw2u7G","agent":"build",
 "input":{"command":"echo one && echo two"}}}

{"ev":"perm","data":{"action":"shell","resources":["echo one","echo two"],
 "effect":"allow","agent":"build","metadata":null,
 "source":{"type":"tool","messageID":"msg_0c0bb5b76001I15dzbJ3Zw2u7G",
           "id":"call_ye8Rz8CQyj2JzJPk9N6gGYIw"}}}
```

発火順は **`tool.execute.before` → `shell.create.before` → `permission.evaluate`**。

| 欲しい情報 | どこで取れるか | 備考 |
| --- | --- | --- |
| 生コマンド（分割前） | `tool.execute.before` の `input.command` | `id` 付きなので相関できる |
| cwd | `shell.create.before` の `cwd` | `timeout` / `shell` / `env` も取れる |
| 分割後のコマンド列 | `permission.evaluate` の `resources[]` | scanner が `&&` で分割済み |
| 判定の変更 | `permission.evaluate` の `effect` / `message` | — |

### ★`permission.evaluate` 単体では足りない

`metadata` は `null` で、**cwd も生コマンドも入っていない**。
`resources[]` は分割済みなので、`curl ... | sh` のような
**コマンド間の関係を見る検査は resources だけでは再現できない**。

相関は `source.id` で可能だった。`tool.execute.before` の `id`
（`call_ye8Rz8CQyj2JzJPk9N6gGYIw`）と
`permission.evaluate` の `source.id` が**完全一致**する。
プローブで `Map<id, input>` に退避して引き当てる実装を試し、
`recovered: {"command":"echo DENYME"}` と復元できることを確認した。

`shell.create.before` には `id` が無い（キーは
`command` / `cwd` / `timeout` / `shell` / `env`）。
cwd の相関はコマンド文字列で突き合わせることになり、
**並列実行時の取り違えは未検証**。

## 5. deny の実効性

`permission.evaluate` で `effect` を書き換えると実際にブロックされた。

```json
{"ev":"perm.denied","data":{"resources":["echo DENYME"]}}
```

```text
✗ echo DENYME failed
Error: [probe] deny の実効性テスト
> 実行は権限設定により拒否されました。
```

`message` に入れた文字列がそのままエラーとして出て、エージェント側も
拒否を認識した。`check_bash.py` が返す理由文をそのまま渡せる。

## 6. 失敗時の挙動（最重要）

| 失敗の種類 | 挙動 | 実測 |
| --- | --- | --- |
| hook 内で例外 | **fail-closed** | `echo THROWTEST` が `Error: [probe] hook 内で例外` で停止 |
| `setup()` で例外 | **fail-open** | `echo SETUPFAIL` が通常実行された |
| 構文エラー | **fail-open** | `echo SYNTAXFAIL` が通常実行された |

ロード失敗は警告として記録される。

```text
level=WARN message="failed to load plugin"
  target=.../.opencode/plugins/probe.js ref=err_07a85762
  cause="Cause([Die(AggregateError: 3 errors building ...)])"
```

`opencode api get /api/plugin` でも `total plugins: 0` となり、
**事後の検出は可能**。ただし実行時には素通りする。

> **含意**: プラグインは「あれば効く」層であり、それ自体は fail-closed にできない。
> ロードされなかったプラグインは自分の不在を検出して deny できない。
> したがって **静的 permission リストを土台として残す**必要がある。
> プラグインが落ちれば静的リストまで縮退する、という設計なら許容できる。

## 7. 副次的な観測

### 非対話実行は `ask` を自動拒否する

`opencode run` で外部ディレクトリに触れるコマンドを実行させたときの出力。

```text
! permission requested: external_directory (/tmp/*); auto-rejecting
✗ cd /tmp && echo hello failed
```

Claude `-p` の「スキップ」、Copilot cloud agent の「deny 扱い」と同じ方向。
既定 `ask` を増やすと無人実行が止まりやすくなる、という論点の裏付けになる。

### Orca のプラグインが V2 でロードに失敗している

検証中、無関係な既存プラグインの失敗ログが出た。

```text
level=WARN message="failed to load plugin"
  target=/home/applejxd/.orca-relay/opencode-overlays/<hash>/plugins/orca-opencode-status.js
  cause="PluginModule.LoadError: Plugin must export a default definition with
         an id and an effect or setup function."
```

V1 形式のため V2 のローダ契約を満たしていない。
[生態系の棚卸し](opencode-plugins.md) の「主要プラグインは V1 のまま」と整合する。
この環境では **Orca の status プラグインが現在機能していない**。

## 再確認すべき情報源

- <https://opencode.ai/v2/docs/build/plugins>（hook の種類と型）
- <https://opencode.ai/v2/docs/permissions>（`PermissionEvaluation` の形）
- 並列実行時の `shell.create.before` と `permission.evaluate` の対応付け（**未検証**）

[調査記録一覧へ戻る](index.md)
