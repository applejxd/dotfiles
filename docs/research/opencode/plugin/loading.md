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

`package.json` は不要。`index.js` だけのディレクトリで足りる。

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

## 4. Claude Code との違い

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
- 単一ファイル指定が将来のバージョンで動くようになるか（**未追跡**）
- `plugins` の `-` プレフィックスによる無効化が実際に効くか（**未検証**）

[調査記録一覧へ戻る](../../index.md)
