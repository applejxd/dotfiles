# OpenCode V2 のキーバインド

- **観測日**: 2026-09-22
- **対象**: OpenCode `v2.0.12`（Linux / WSL、Orca セッション内）
- **一次情報**: <https://opencode.ai/v2/docs/cli/keybinds>

現在の割り当てと運用は
[エージェント権限仕様](../../spec/agent-permissions.md)「キーバインド」が正本。
ここには実測だけを残す。

## 1. 公式一覧は最新版向けで、2.0.12 に無い ID が載っている

**未知の ID は「拒否される」と書かれているが、実際は
その行だけ黙って無視され、他の行は生きる。**

`app.exit` / `session.interrupt` / `permission.mode` / `service.restart` の
4 件を同時に投入したところ、前 2 件は効き、`permission.mode` だけが無反応
だった。エラーもログも出ない。

**leader 系が無視されると、続きのキーが素通りして文字入力になる。**
`<leader>p` が死んでいると `Ctrl+X` → `p` が「`p` と打った」ことになる。
何も起きないのではなく**別のことが起きる**ので、設定ミスだと気づきにくい。

### 実在の確認方法

バイナリに単独の文字列として入っているかを見る。

```console
$ strings -n 4 ~/.opencode/bin/opencode | grep -x 'service.restart'
service.restart
```

**部分一致で見てはいけない。** `grep -F permission.mode` は 3 件を返すが、
中身は minify された JavaScript の断片で、ID ではない。

```console
$ strings -n 6 ~/.opencode/bin/opencode | grep -F 'permission.mode' | cut -c1-60
`);if(Te.bytes.byteLength===0){De.dispatch("prompt.paste");re
${y.slice(-D).join("")}`}function Ko(r,i){let m=[];return r.f
`)},get tool(){return r.part.name},get part(){return r.part}}
```

完全一致（`grep -x`）だと 0 件になる。

### 2.0.12 に実在する `permission.*`

```text
permission.asked            permission.replied
permission.prompt.fullscreen permission.request.list
permission.rejected         permission.saved.list
                            permission.saved.remove
```

**自動承認のトグルに当たる ID は無い。** 公式一覧の `permission.mode` は
より新しい版のもの。2.0.12 では
[bypass エージェント](permission/bypass-agent.md)が唯一の一時解除手段。

## 2. `ctrl+c` は `app.exit` が既定で握っている

既定は `app.exit = "ctrl+c,ctrl+d,<leader>q"`。`session.interrupt`（既定
`escape`）へ `ctrl+c` を割るだけでは**中断ではなくアプリ終了**になる。
`app.exit` から明示的に外す必要がある。

| キー | 既定で握っているコマンド |
| --- | --- |
| `ctrl+c` | `app.exit`, `prompt.clear` |
| `ctrl+d` | `app.exit`, `session.delete`, `input.delete` |

`prompt.clear` も `ctrl+c` を持つが、`session.interrupt` へ移したあとも
実機で中断が効いた。文脈で振り分けられている（実測）。

## 3. `<leader>` の空きは 9 文字

既定で埋まっているのは `a b c e g i l m n q r s t u w x y` と `0`〜`9`。
空きは `d f h j k o p v z` のみ。

`d` は `diff.open`（既定 `none`）用に空けてある。

## 4. キー送出による自動検証は成立しなかった

`script -qec "opencode"` に生バイトを流す方法を試したが、**対照が通らず
判定できない**。以下の 3 つに順に引っかかった。

| 失敗 | 症状 | 原因 |
| --- | --- | --- |
| 計測が 68 秒 | `timeout 20` が効かない | プロセス置換 `< <(… sleep 60)` の完了をシェルが待つ |
| 対照が即死（1 秒） | 起動すらしない | `env NAME=val -u VAR` の順序。`-u` が代入の後ろだと**コマンド名として解釈される** |
| 対照が終了しない | 効くはずのキーが無反応 | Orca の plugin が失敗して**モーダルが開き、キーを吸う** |

```text
Plugin failed: …/opencode-overlays/<hash>/plugins/orca-opencode-status.js
```

新規 DB での起動直後も同様に入力が通らない場面があり、再現性を確保できな
かった。**キーバインドの検証は実機で人が押すのが早い。**

### 代わりに成立した検証

キー入力に依存しない指標なら測れる。`cli.json` が読まれたかどうかは
ログの `role=cli` で分かる（[ロード経路](plugin/loading.md)）。

| 条件 | `role=cli` の行 | `guide-plugin` |
| --- | ---: | --- |
| overlay のみ | 0 | 無し |
| overlay + `OPENCODE_CLI_CONFIG_CONTENT` | 12 | **有り** |

## 5. 設定の届き方

`OPENCODE_CLI_CONFIG_CONTENT`（JSON 本文）は常に効く。ファイル
（`cli.json`）は `OPENCODE_CONFIG_DIR` 基準で探されるため、Orca
セッションでは読まれない。詳細は[ロード経路](plugin/loading.md)。

## 再確認すべき情報源

- <https://opencode.ai/v2/docs/cli/keybinds>（ID 一覧。**版が進むと増える**）
- `permission.mode` が 2.0.12 より後のどの版で入ったか（**未追跡**）
- `leader.timeout` の既定値（**未確認**。公式ページに記載が無い）

[調査記録一覧へ戻る](../index.md)
