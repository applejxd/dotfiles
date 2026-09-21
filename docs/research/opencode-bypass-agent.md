# OpenCode V2 のカスタムエージェント（Bypass モード）とキーバインド

> **調査日: 2026-09-21**
> **対象: `opencode v2.0.10`**
>
> 依頼元は次の 2 つ。どちらも V1 前提の情報だったため、V2 での可否を実測した。
>
> - Zenn「OpenCode が Ctrl+C で不意に終了するのを防ぐ設定方法」（2026-02-27）
> - `open-code.ai/ja/docs/modes`（脚注に「**非公式、参考用**」と明記）

## 0. 結論

| 依頼 | 結果 |
| --- | --- |
| キーバインド変更（`keybinds.app_exit`） | **V2 では不可。**設定から除去される |
| 全ツール許可の Bypass モード | **実装可。**ただし `mode` ではなく `agent` を使う |

## 1. キーバインドは V2 の設定に存在しない

### 実測: 設定に書いても消える

```json
{ "$schema": "https://opencode.ai/config.json",
  "keybinds": { "app_exit": "ctrl+d,<leader>q" } }
```

`opencode api config.get` が返した解決済みの設定:

```json
{"path":".../a/opencode.json","info":{"$schema":"https://opencode.ai/config.json"}}
```

**`keybinds` が丸ごと落ちている。** バイナリには V1 設定から `keybinds`
ノードを除去する JSON 操作コードが含まれており、移行時に捨てる実装に見える。

### 裏付け

- 公式 V2 ドキュメントに **keybinds のページが無い**
  （`/v2/docs/keybinds` は 404。ナビにも項目が無い）
- バイナリに `app_exit` という文字列が**存在しない**
  （`switch_mode` や `leader` は存在する）

V1 のキーバインド機構自体は残骸が残っているが、`app_exit` は V2 の
アクション名ではない。Zenn 記事は V1 向けで、そのまま適用しても効かない。

**未確認**: V2 が別経路（TUI の設定画面など）でキーバインドを持つか。

## 2. Bypass モードは `agent` で実装する

### `mode` は非推奨

`open-code.ai` の記事は `mode` を使う書き方だが、同ページ冒頭に
「モードは agent オプションで設定するようになりました。`mode` は非推奨」
と注記がある。設定スキーマでも `mode` は
`@deprecated Use 'agent' field instead.` になっている。

### 実測: 3 つの書き方を比較

`opencode api config.get` で正規化後の形を見た。

| 入力 | 正規化後 | 判定 |
| --- | --- | --- |
| `agent.bypass.permission = "allow"` | `agents.bypass.permissions = [{action:"*", resource:"*", effect:"allow"}]` | **正解** |
| `agent.bypass.permissions = [...]`（配列） | `agents.bypass.request.body.permissions` へ押し込まれる | 誤り |
| `keybinds` | 消える | — |

**`permission` に文字列 `"allow"` を置くと、OpenCode が
「全 action・全 resource を allow」へ展開する。** これがそのまま
「全ツール許可」になる。配列で書くと別の場所へ解釈されるので使わない。

### 実測: グローバルの deny を上書きできる

グローバル設定で `pip *` を deny している状態で確認した。

```console
$ opencode run --agent bypass 'Run one shell tool call: pip --version'
> bypass · claude-opus-5
$ pip --version
pip 26.0.1 from ...  (exit 0)
```

通常のエージェントでは `Permission denied: shell` になるコマンドが通る。

## 3. セキュリティ上の含意

**bypass は permission 層を丸ごと無効にする。** 影響は shell だけではない。

`{action:"*", resource:"*", effect:"allow"}` は `read` / `edit` にも当たるため、
次の保護が**すべて外れる**。

- `~/.ssh/**` / `*.pem` / `*secret*` などの read deny
- `~/.config/opencode/opencode.json` の write deny（自分の permission を
  書き換えられる状態になる）
- `.git/config` の write deny

つまり bypass 中は「エージェントがホスト権限で何でもできる」。
[段階 1 の設計](../change/0002-opencode-ask-by-default.md)が前提にしている
防御は 1 つも残らない。

既定エージェントは変えていないので、**明示的に `--agent bypass` を
選んだときだけ**この状態になる。常用するものではない。

## 4. 実装

単一ソース（`common.toml`）から生成する。生成先は直接編集しない。

```toml
[opencode.agent.bypass]
description = "全ツールを無確認で実行する (permission を全て allow で上書き)"
permission = "allow"
```

`generate.py` に `merge_opencode_agents()` を追加した。`mcp` と同じ方針で、
**common.toml に無いエージェントは残す**（`/agents` などが同じファイルへ
書くため）。

使い方:

```bash
opencode run --agent bypass '<prompt>'
# TUI では Tab または switch_mode のキーバインドで切り替える
```

## 再確認すべき情報源

- V2 にキーバインド設定の経路があるか（**未確認**）
- `agents` へ正規化される仕様がドキュメント化されているか（**未確認**）
- `permission: "allow"` 以外の文字列（`"ask"` / `"deny"`）の展開（**未検証**）

[調査記録一覧へ戻る](index.md)
