# OpenCode V2 の試験環境の隔離方法（訂正を含む）

> **調査日: 2026-09-21**
> **対象: `opencode v2.0.10`**
>
> **本記録は過去の調査記録の前提を訂正する。**
> それまでの記録は隔離手段として `XDG_CONFIG_HOME` の差し替えを挙げていたが、
> **OpenCode は config dir の決定に `XDG_CONFIG_HOME` を使わない**。

## 0. 本書の用途

[CHG-0002](../../change/0002-opencode-ask-by-default.md) 段階 1 の実機試験で、
生成した global config が読まれていないことに気付いた。原因を特定し、
正しい隔離手段と、過去の記録への影響範囲を確定する。

## 1. 結論

| 項目 | 結果 |
| --- | --- |
| config dir の指定 | **`OPENCODE_CONFIG_DIR`**。`XDG_CONFIG_HOME` は**使われない** |
| 認証情報 | config dir の外。**セッション DB の `credential` テーブル**にある |
| モデルカタログ | 認証に依存する。DB を差し替えると Copilot が引けなくなる |
| セッション DB の隔離 | **`OPENCODE_DB`** で可能。ただし実 DB を種にして認証を引き継ぐ必要がある |
| 過去の記録への影響 | **結論は全て有効。** 影響は「隔離できているつもりだった」点のみ |

## 2. `XDG_CONFIG_HOME` は効かない

全コマンドを deny する config を置いて、読まれるかどうかで判定した。

```json
{ "$schema": "https://opencode.ai/config.json",
  "permissions": [ { "action": "shell", "resource": "*", "effect": "deny" } ] }
```

| 置き場所 | 環境変数 | `echo HELLO` の判定 |
| --- | --- | --- |
| `$XDG_CONFIG_HOME/opencode/opencode.json` | `XDG_CONFIG_HOME` | **`allow`**（deny が効かない） |
| `$OPENCODE_CONFIG_DIR/opencode.json` | `OPENCODE_CONFIG_DIR` | **`deny`**（効く） |

`OPENCODE_CONFIG_DIR` を使った場合、`permission.evaluate` の hook は
**発火しなかった**。設定の deny が hook より前段で効くという
[既知の性質](plugin/api-probe.md)と整合する。

バイナリから拾える関連の環境変数は次のとおり。

```text
OPENCODE_CONFIG            OPENCODE_CONFIG_DIR
OPENCODE_CONFIG_CONTENT    OPENCODE_CONFIG_PROJECT_DISABLE
OPENCODE_DISABLE_PROJECT_CONFIG
OPENCODE_DB
```

`OPENCODE_DB` があるので、セッション DB も分離できる可能性がある（**未検証**）。

### `HOME` の差し替えは使えない

`HOME` を差し替えると provider 認証が壊れ、モデル呼び出しの前に落ちる。

```text
Error from provider (Console): OpenCode's free tier can only be used from within OpenCode
```

一方 `OPENCODE_CONFIG_DIR` を差し替えても `opencode auth list` は
`GitHub Copilot ... stored` を返す。**認証情報は config dir の外**にある。

## 3. `XDG_DATA_HOME` を差し替えるとモデルが引けない

`--model github-copilot/claude-opus-5` で切り分けた。

| 条件 | 結果 |
| --- | --- |
| `XDG_DATA_HOME` そのまま | 成功 |
| `XDG_DATA_HOME` を差し替え | **`Model unavailable: github-copilot/claude-opus-5`** |

プロバイダ／モデルのカタログが `~/.local/share/opencode` にあるため。
`opencode models` は 31 件を列挙するが、これは**既知のモデル一覧**であって
利用可能なものではない。列挙されていても `Model unavailable` になる。

### 既定モデルは OpenCode の無料枠

`--model` を指定しない場合の既定は `muse-spark-1.3-contributor-free` で、
連続実行すると次で止まる。

```text
Error from provider (Console): OpenCode's free tier can only be used from within OpenCode
```

GitHub Copilot の認証が入っているなら `--model github-copilot/...` を明示する。

## 4. セッション DB の隔離（`OPENCODE_DB`）

`OPENCODE_DB` は **DB ファイルのパス**を取る。指定すると、そこへ
セッションが書かれ、実環境の `~/.local/share/opencode/opencode.db` は
変化しない（複数回の試験で `session_v2` が 16 件のまま）。

### 落とし穴: 認証情報も DB の中にある

まっさらなパスを指定すると Copilot が使えなくなる。

```text
Error: Model unavailable: github-copilot/claude-opus-5
```

原因は `credential` テーブルが DB 内にあること。

| | `credential` | `session_v2` |
| --- | ---: | ---: |
| 実 DB | 1 | 16 |
| まっさらな隔離 DB | **0** | 1 |

`XDG_DATA_HOME` を差し替えたときにモデルが引けなくなるのも同じ理由
（DB ごと差し替わるため）。

### 解決: 実 DB を種にして履歴だけ消す

`sqlite3` の backup で複製し、セッション系のテーブルだけ空にする。
認証は残り、履歴は空になる。

```python
import sqlite3
src = sqlite3.connect("file:~/.local/share/opencode/opencode.db?mode=ro", uri=True)
dst = sqlite3.connect("/tmp/opencode/<name>/seed.db")
src.backup(dst)
for t in ("session_message", "session_v2", "session_inbox", "session_pending", "event"):
    dst.execute(f"delete from {t}")
dst.commit()
dst.execute("vacuum")
```

この種を使うと、Copilot のモデルが解決でき、実 DB は汚れない。
`OPENCODE_CONFIG_DIR` との併用も確認した（deny が効き、実 DB は不変）。

**注意**: トークンが更新されると隔離側の複製にだけ書かれる。長く使い回すと
種が古くなるので、認証で失敗したら作り直す。

## 5. 推奨する試験手順

```bash
# 1. 認証を引き継いだ空の DB を用意する (上のスクリプト)
# 2. config を隔離する
export OPENCODE_CONFIG_DIR=/tmp/opencode/<name>/config
export OPENCODE_DB=/tmp/opencode/<name>/seed.db

opencode run --standalone \
  --model github-copilot/claude-opus-5 \
  --log-level error '<prompt>'
```

- `XDG_CONFIG_HOME` / `XDG_DATA_HOME` / `HOME` は**差し替えない**
- `--standalone` は常時起動のサービスを避けるために付ける
- permission を試すだけならプロジェクト側の `.opencode/opencode.json` でよい。
  global config の挙動を見るときだけ `OPENCODE_CONFIG_DIR` が要る
- `OPENCODE_DB` を省くと、試験セッションが実環境の DB に残り、
  [利用実績の集計](permission/shell-allow-and-plugin-gate.md)の母数が汚れる

### 制約: 子エージェントを起動する試験は完走しない

`subagent` ツールで子エージェントを起動させると、**3 回とも子側の
最初のツール判定の直後に `Error: Transport` で落ちた**（設定を変えた
2 通りと対照 1 通り）。`OPENCODE_DB` を差し替えていることが原因と
思われるが未特定。

hook の観測（`tool.execute.before` / `permission.evaluate`）は判定まで
届くので、**権限まわりの確認には使える**。実行結果まで見たい場合は
この手順では取れない（[出力フィルタと子エージェント](permission/output-filter-and-subagents.md)）。

## 6. 過去の記録への影響

**結論はいずれも有効。** 理由は、global config に permission を置いた実験が
今日まで 1 件も無かったため。

| 記録 | permission の置き場所 | 判定 |
| --- | --- | --- |
| [permission 適用範囲の穴](permission/gaps.md) | プロジェクトの `.opencode/opencode.json` | 有効 |
| [plugin API の実測](plugin/api-probe.md) | 同上 | 有効 |
| [相関と承認要求の可否](plugin/correlation.md) | 同上（`$schema` のみ）+ plugin | 有効 |
| [allow の費用対効果と plugin ゲート](permission/shell-allow-and-plugin-gate.md) | 同上 | 有効 |
| [ask と並列バッチ](ask-and-parallel-batch.md) | 同上 | 有効 |
| [ツールのコンテキストコスト](tool-context-cost.md) | permission を使わない | 有効 |

ただし各記録の冒頭にある「`XDG_CONFIG_HOME` を差し替えた隔離環境」という
記述は**手段として誤り**。実際には OpenCode は実環境の
`~/.config/opencode/` を config dir として読んでいた。そこに
`opencode.json` が無かった（`service.json` だけ）ため、結果的に
「global config 無し + プロジェクト config あり」という、各記録が
想定していた条件と一致していた。

**実環境への書き込みは発生していない**（読み取りのみ）。

## 7. `OPENCODE_CONFIG_DIR` は global config を「置き換える」（upstream の不具合）

### 症状

`OPENCODE_CONFIG_DIR` を設定すると、`~/.config/opencode/opencode.json` の
**permission が一切効かなくなる**。指定先に `opencode.json` が無い場合でも、
global config へフォールバックしない。

この環境では Orca が overlay ディレクトリを指しており、実際に影響が出ていた。

```text
OPENCODE_CONFIG_DIR=~/.orca-relay/opencode-overlays/<hash>/
  中身: service.json と plugins/orca-opencode-status.js のみ（opencode.json 無し）
```

| config dir | `echo HELLO` |
| --- | --- |
| overlay（Orca 経由のセッション） | **通る**（permission 層が無い） |
| 既定（`~/.config/opencode`） | `ask` |

### 原因: upstream の既知の不具合

[anomalyco/opencode#32825](https://github.com/anomalyco/opencode/issues/32825)
（**Open**、label `bug` / `core` / `2.0`）。

> The old loader treats `OPENCODE_CONFIG_DIR` as an extra config directory.
> The v2/core path currently treats it as a **replacement** for the normal
> XDG global config directory through `Global.config`.

`packages/core/src/global.ts` の
`config: Flag.OPENCODE_CONFIG_DIR ?? Path.config` により、v2 では
「global config の置き場所」自体が差し替わる。

**公式ドキュメントの記述とは食い違う。** ドキュメントは
「設定は結合される（merged, not replaced）」「`OPENCODE_CONFIG_DIR` は
`.opencode` と同様に追加で探索される」と書いており、DeepWiki も同じ説明を
返す。**実装は 2.0.10 時点でそうなっていない。**

関連: [#28658](https://github.com/anomalyco/opencode/issues/28658)（Open）は
global `AGENTS.md` が読まれなくなる同根の問題。ただし 2.0.10 では
`~/.config/opencode/AGENTS.md` は読まれており、こちらは部分的に直っている
（**未確認**）。

### 回避策: `OPENCODE_CONFIG` を併用する

`OPENCODE_CONFIG`（単一ファイル指定）は `Global.config` を経由せず
独立したレイヤとして merge されるため、不具合の影響を受けない。

```bash
export OPENCODE_CONFIG="${HOME}/.config/opencode/opencode.json"
```

### 読み込まれる設定ソースの実測

`opencode api config.get` が**解決済みの設定ソース一覧**を返す。LLM を
使わずに検証できる。**中立な作業ディレクトリで実行する**（cwd に
`opencode.json` があるとプロジェクト設定として拾われ、測定が汚れる）。

```bash
cd /tmp/<empty> && opencode api config.get --standalone
```

| 条件 | global config の読み込み | 結果 |
| --- | --- | --- |
| A. 素の状態 | 1 回（218 rules） | 正常 |
| B. `OPENCODE_CONFIG` のみ | **2 回**（218 + 218） | 二重 merge |
| C. overlay + `OPENCODE_CONFIG` | 1 回（218 rules） | **回復** |
| D. overlay のみ | **0 回** | permission 層が消える |

D が Orca 経由のセッションの状態で、段階 1 が効かない理由そのもの。

### 二重 merge は無害

B の状態を実測した。`git status --short` は無確認で実行され、
`echo HELLO` は `ask` になった。素の状態と同じ挙動である。

配列は `mergeConfigConcatArrays` で連結されるので、permission は
218 件が 2 本つながって 436 件になる。ただし内容と順序が同一なので、
**後勝ちの評価では最後に一致する規則が変わらない**。`[X, X]` の最後の
一致は `X` の最後の一致と等しい。

サイズと評価コストは倍になるが、判定結果は変わらない。

### なぜ Orca が `OPENCODE_CONFIG_DIR` を設定するのか

[stablyai/orca#10328](https://github.com/stablyai/orca/pull/10328) が該当機能。

> OpenCode reports status via a JS **plugin** dropped into `OPENCODE_CONFIG_DIR`
> (unlike Claude/Codex, which use managed `hooks.json` scripts).

Orca のサイドバーへ Idle / Working / Done を出すためだけの仕組み。Claude や
Codex は `hooks.json` で済むが、OpenCode は plugin を置く必要があり、その
置き場所として `OPENCODE_CONFIG_DIR` を使っている。

Orca は**既存の `OPENCODE_CONFIG_DIR` があれば symlink で overlay へ mirror**
してから自分の plugin を足す設計で、ユーザー設定を壊さない配慮がある。
元の値は `ORCA_OPENCODE_SOURCE_CONFIG_DIR` に退避される。

**しかし既定の `~/.config/opencode` は mirror の対象外。** mirror するのは
「ユーザーが既に指定していた config dir」だけなので、`OPENCODE_CONFIG_DIR` を
設定していない環境では plugin だけの素の overlay が作られる。

さらに Orca 側のレビューには次の記述がある。

> OpenCode also confirmed **`OPENCODE_CONFIG_DIR` is additive**:
> default XDG config and the extra directory were both loaded.

**検証されたのは OpenCode 1.18.x（v1）。** v2 で挙動が変わったため、
Orca の前提が崩れている。どちらも単体では正しく、組み合わせで壊れる。

### overlay の plugin は v2 でロードに失敗している

`~/.local/share/opencode/log/opencode.log` より。

```text
level=WARN message="failed to load plugin"
  target=.../opencode-overlays/<hash>/plugins/orca-opencode-status.js
  cause="Plugin must export a default definition with an id and an effect or
         setup function. SchemaError(Missing key at ["default"]["effect"]
         / ["default"]["setup"])"
```

つまり現状は、**overlay の目的（ステータス表示）が達成できていないまま、
副作用（global config を隠す）だけが出ている**。

Orca は [#14612](https://github.com/stablyai/orca/pull/14612) で V2 互換に
取り組んでいるが、そちらは `server()` を足す内容で、2.0.10 が要求する
`effect` / `setup` とは噛み合っていない（PR 本文に「1.18.18 で検証、
v2 では未確認」と明記されている）。

### 採用した対処

`home/dot_config/shell/shellenv.sh.tmpl` に条件付きで入れた。
`shellenv.sh` は `.zshenv` から無条件に source され、**zsh のあらゆる起動で
最初に走る**ため、Orca がログインシェル経由で opencode を起動する経路に
間に合う。

```sh
if [[ -n "${OPENCODE_CONFIG_DIR:-}" && -f "${HOME}/.config/opencode/opencode.json" ]]; then
  export OPENCODE_CONFIG="${HOME}/.config/opencode/opencode.json"
fi
```

`OPENCODE_CONFIG_DIR` があるときだけ働くので、二重 merge を避けられる。
Orca が将来 mirror するようになったり overlay をやめたりしても、
自然に無害化する。

実環境での確認（`opencode api config.get`）:

| 条件 | global config |
| --- | --- |
| 現状の Orca セッション | **document 0 件** |
| 条件分岐が発火した状態 | **218 rules を 1 回** |

Orca 側には `agentStatusHooksEnabled` を `false` にして overlay をやめる
経路もあるが、内部の `PtySpawnConfig` の値で、UI から切れるかは**未確認**。

### 配備後の実機確認（2026-09-21）

`chezmoi apply` と Orca の再起動後に確認した。permission 層は生きている。

```text
OPENCODE_CONFIG=~/.config/opencode/opencode.json   ← 条件分岐が発火
doc: ~/.config/opencode/opencode.json | permissions: 218
  shell 先頭: {'action': 'shell', 'resource': '*', 'effect': 'ask'}

$ pip --version
Permission denied: shell                            ← deny が実効
```

`ask` 側は自動承認されて素通りする。`deny` だけが貫通を許さない。
段階 2 で「自動実行で止めたいものは `ask` ではなく `deny` に倒す」と
決めた根拠（[ask と並列バッチ](ask-and-parallel-batch.md)）が
配備後の実環境でも成り立っている。

### 注意: 常駐サービス経由の起動では届かないことがある

再起動の前後でプロセス構成が変わった。

```text
再起動前: /init → zsh -l          → opencode -s ses_...
再起動後: /init → opencode serve --service → zsh -c
```

**`shellenv.sh` は zsh の起動時にしか走らない。** 今回はサービスが
修正後（21:14:35 > コミット 21:09:49）に立ち上がり、かつ zsh を経由した
ため `OPENCODE_CONFIG` を持っていた。

しかしサービスは長命で、シェルを経由しない経路で起動されると古い環境を
持ち続ける。**permission が効いていない疑いがあるときは、まず
`/proc/<service pid>/environ` に `OPENCODE_CONFIG` があるかを見る。**
無ければサービスを再起動する。

```bash
pgrep -af 'opencode serve'
tr '\0' '\n' < /proc/<pid>/environ | grep OPENCODE_CONFIG
```

## 8. 配備先の想定は正しい

実環境の `~/.config/opencode/` には OpenCode 自身が作った `service.json` が
あり、ここが既定の config dir であることを裏付けている。
`home/dot_config/opencode/modify_opencode.json.py.tmpl` が
`~/.config/opencode/opencode.json` へ配備する設計は妥当。

## 再確認すべき情報源

- [#32825](https://github.com/anomalyco/opencode/issues/32825) の修正状況
  （Open。修正されたら `OPENCODE_CONFIG` の併用が不要になる）
- [#28658](https://github.com/anomalyco/opencode/issues/28658) の修正状況
  （Open。ただし 2.0.10 で global `AGENTS.md` は読まれている）
- `opencode models` が利用可否を反映しない件が仕様か不具合か（**未確認**）
- 隔離 DB の種が古くなる周期（トークン更新の頻度。**未測定**）

[調査記録一覧へ戻る](../index.md)
