# OpenCode V2 の plugin ロード経路

> **調査日: 2026-09-21**
> **対象: `opencode v2.0.10`**
>
> [CHG-0002](../../../change/0002-opencode-ask-by-default.md) 段階 2 の誘導 plugin を
> どこに置くかを決めるための実測。**公式ドキュメントと実装が食い違う。**

## 0. 結論

**明示指定は「絶対パスのディレクトリ」でないと解決されない。**
相対パスでも `~` でも単一ファイルでも、OpenCode は**黙って無視する**。

| 指定 | 結果 |
| --- | ---: |
| `plugins: ["/abs/dir"]`（`index.js` のみ） | **ロードされる** |
| `plugins: ["/abs/dir"]`（`package.json` あり） | **ロードされる** |
| `plugins: ["/abs/path.ts"]`（単一ファイル） | 無視 |
| `plugins: ["/abs/path.js"]`（単一ファイル） | 無視 |
| `plugins: ["~/path/dir"]` | 無視（`~` は展開されない） |
| `<OPENCODE_CONFIG_DIR>/plugins/` 直下 | 自動探索される |
| `<OPENCODE_CONFIG_DIR>/plugin/` 直下 | 自動探索される |
| `<cwd>/.opencode/plugins/` 直下 | 自動探索される |

> [!NOTE]
> **追記 (2026-09-23 / `v2.0.12`)**: `<cwd>/.opencode/plugins/` の自動探索を
> 再確認した。**クローンしたリポジトリの plugin がそのまま実行される**
> （[permission の穴 §5](../permission/gaps.md#5-プロジェクト設定がグローバルの-deny-を上書きする2026-09-23-再確認)）。
>
> 同時に分かったこと: **plugin はサーバ起動時ではなくセッション開始時に
> 読み込まれる。** `opencode api get` を叩くだけでは動かないので、
> 試験でロードを確かめるならセッションを 1 回回す。
>
> 試験のときは **`PWD` を試験用ディレクトリに合わせる**こと。子プロセスの
> `cwd` だけ変えると、OpenCode は呼び出し元をプロジェクトと見なし、
> 自動探索が起きずに「読み込まれない」という誤った結論が出る（実際に出した）。

`package.json` は不要。`index.js` だけのディレクトリで足りる。

**ただし上表はサーバ側 plugin の話。** TUI 側 plugin は経路が違い、
`cli.json` に書かないと読まれない（セクション 4）。

公式ドキュメントは `"/absolute/path/plugin.ts"` という**単一ファイル指定を
例示している**が、2.0.10 では動かない。設定スキーマ（`opencode.ai/config.json`）
がキー名を `plugin`（単数）としている点も V1 のままで、実際は `plugins` /
`plugin` のどちらを書いても `plugins` へ正規化される。

## 1. 失敗が見えない

解決に失敗しても**エラーも警告も出ない**。設定自体は受理される。

```console
$ opencode api config.get --standalone
{"plugins": ["/abs/path/a.js", "/abs/path/a.js"]}   ← 受理されている
```

それでも `setup()` は呼ばれない。「設定は正しいのに動かない」という
切り分けの難しい壊れ方をする。**ロード確認用のマーカーを書く plugin を
1 つ用意して実測する**のが唯一の確かめ方。

`opencode plugin list` はローカル plugin を列挙しない（`No plugins found`
と出る）。`opencode api` 系のサブコマンドは **plugin をロードしない**ので、
ロード可否の判定には使えない（較正して確認済み）。

## 2. Orca overlay との関係

Orca は `OPENCODE_CONFIG_DIR` を自前の overlay へ向ける
（[試験環境の隔離方法](../test-isolation.md)）。

```text
~/.orca-relay/opencode-overlays/<hash>/
├── service.json                      ← Orca 連携の実体
└── plugins/orca-opencode-status.js
```

自動探索は `OPENCODE_CONFIG_DIR` 基準なので、**Orca セッションでは
`~/.config/opencode/plugins/` が読まれない**（実測）。overlay には Orca の
実体があるため、`OPENCODE_CONFIG_DIR` をこちらで上書きする案は採れない。

一方、`OPENCODE_CONFIG` が指す設定ファイルの `plugins` は overlay 下でも
効く。overlay 相当の条件を作って確認した。

```text
OPENCODE_CONFIG_DIR = <overlay>                        ← Orca が差し替える
OPENCODE_CONFIG     = ~/.config/opencode/opencode.json ← 既存の対処
   └─ "plugins": ["/abs/dir"]   → ロードされる
```

**絶対パスのディレクトリを設定ファイルに書くのが、Orca でも素の端末でも
効く唯一の方法。**

`<cwd>/.opencode/plugins/` も cwd 基準なので overlay の影響を受けないが、
プロジェクトごとに配る必要がある。

## 3. ディレクトリ名に `plugin` / `plugins` を使わない

設定ディレクトリ直下のこの 2 つは自動探索される。明示指定と同じ場所に
置くと二重ロードになるため、`guide-plugin` のような別名にする。

## 4. TUI plugin は `cli.json` に書かないと読まれない（2026-09-22 追記）

サーバ側 plugin と TUI 側 plugin では**読まれる経路が違う**。
`opencode.json` の `plugins` に書いたディレクトリは、サーバ側しか
ロードされない。

`script` による自動検証（[試験環境の隔離方法](../test-isolation.md)）で
比較した。対照はプロジェクト直下の `.opencode/plugins/<name>/tui.ts`。

| 指定方法 | `package.json` | TUI plugin |
| --- | --- | --- |
| `opencode.json` の `plugins` | 無し | **読まれない** |
| `opencode.json` の `plugins` | `exports: {"./tui": "./tui.ts"}` あり | **読まれない** |
| **`cli.json` の `plugins`** | 無し | **読まれる** |
| **`cli.json` の `plugins`** | あり | **読まれる** |
| `<project>/.opencode/plugins/<name>/tui.ts` | — | 読まれる |

**`package.json` は不要。** 必要なのは `cli.json` への登録。

公式ドキュメントは「`opencode.json` に書いた plugin が TUI 部品を
持っていれば CLI が自動で読む。`cli.json` へ重ねて書く必要はない」と
説明するが、**2.0.12 では実装と食い違う**（ロード経路の食い違いはこれで 2 件目）。

`cli.json` の位置は `~/.config/opencode/cli.json`。
**Orca の overlay 下では読まれない**（`OPENCODE_CONFIG_DIR` 基準。
`OPENCODE_CONFIG` は `opencode.json` しか差し替えない）。2026-09-22 に確定した。

| 条件 | `cli.json` |
| --- | --- |
| `OPENCODE_CONFIG_DIR` 未設定 | `~/.config/opencode/cli.json` を読む |
| `OPENCODE_CONFIG_DIR` = overlay（Orca セッション） | **読まない**。plugin もキーバインドも既定に戻る |
| `OPENCODE_CONFIG_DIR` = `cli.json` を置いたディレクトリ | そこから読む |

**パスを渡す環境変数は無い。** バイナリが持つのは
`OPENCODE_CLI_CONFIG_CONTENT`（JSON 本文）だけで、`OPENCODE_CONFIG` の
CLI 版に当たるものが存在しない。そのため `shellenv.sh` で本文を流し込む。

```sh
if [[ -n "${OPENCODE_CONFIG_DIR:-}" && -f "${HOME}/.config/opencode/cli.json" ]]; then
  OPENCODE_CLI_CONFIG_CONTENT="$(<"${HOME}/.config/opencode/cli.json")"
  export OPENCODE_CLI_CONFIG_CONTENT
fi
```

確認は**キー入力では取れない**。隔離環境では Orca 自身の plugin が失敗して
モーダルが開き、そこにキーが吸われる。ログの `role=cli` を数えるほうが確実。

| 条件 | `role=cli` の行 | `guide-plugin` |
| --- | ---: | --- |
| overlay のみ | 0 | 無し |
| overlay + `OPENCODE_CLI_CONFIG_CONTENT` | 12 | **有り** |

## 5. Claude Code との違い

同じ「hook を配る」でも仕組みが違い、OpenCode 側だけ不確実性が多い。

| | Claude Code | OpenCode V2 |
| --- | --- | --- |
| 実体 | コマンド文字列（外部プロセス） | JS/TS モジュール |
| 登録先 | `~/.claude/settings.json`（固定パス） | `OPENCODE_CONFIG_DIR` 相対の探索 |
| 失敗時 | エラーが出る | 黙って無視 |

Claude 側は絶対パスのコマンドを固定ファイルに書くだけで、解決の曖昧さが
無い。

```json
{"type": "command", "command": "python3 \"/home/applejxd/.claude/hooks/check_bash.py\""}
```

## 再確認すべき情報源

- <https://opencode.ai/v2/docs/plugins>（単一ファイル指定の例が実装と食い違う）
- <https://opencode.ai/v2/docs/cli/plugins>（「`cli.json` へ重ねて書く必要はない」と
  説明するが、2.0.12 では TUI plugin は `cli.json` が必須）
- 単一ファイル指定が将来のバージョンで動くようになるか（**未追跡**）
- `plugins` の `-` プレフィックスによる無効化が実際に効くか（**未検証**）

[調査記録一覧へ戻る](../../index.md)
