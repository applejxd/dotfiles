# bypass を「ask を allow にするだけ」に再定義できるか（plugin 方式）

- **観測日**: 2026-10-03
- **対象**: OpenCode `v2.0.14` / WSL2 Ubuntu / モデル `github-copilot/claude-haiku-4.5`
- **方法**: `mise run opencode:probe`（`opencode run --standalone`、実 DB を汚さない）。
  `generate.py` が出した `opencode.json` を元に、一時設定を `.tmp/bypass-exp/` に置き
  `OPENCODE_PROBE_CONFIG` で渡した（記録後に削除）。ダミーファイルも同じ場所に作った
- **前提の記録**: [bypass-agent.md](bypass-agent.md)、[hook-order.md](hook-order.md)、
  [shell-allow-and-plugin-gate.md](shell-allow-and-plugin-gate.md) 4 章、
  [early-guard.md](early-guard.md)

## 問い

現行の `bypass` は `permission = { "*" = "allow", … }` で全部 allow にする。これを、
**通常エージェントと同じ permission のまま、`ask` になるものだけを `allow` にする**
形へ変えられるか。deny はそのまま効かせ、plugin が無ければ `ask` に戻る（安全側）。

## 構成

- 元の設定: `chezmoi execute-template` で `common.toml` を描画し、`generate.py --target opencode-config`
  で出力。`mcp` は外し、`plugins` を試験用の 1 つへ差し替えた
- bypass 系の変更（`*` の allow を外す）:
  - `agent.bypass.permission = { task = { "*" = "allow", general = "deny", fleet-worker = "deny" } }`
  - `agent.bypass-worker.permission = { task = "deny" }`
  - `agents.bypass-fleet-worker.permissions` の先頭の全 allow を削除
- `opencode api config.get --standalone` の正規化後、`bypass` の `permissions` は
  `subagent` の 3 規則（`* allow` → `general deny` → `fleet-worker deny`）だけになった
- 試験用 plugin（`execute.before` と `permission.evaluate` の入力を記録）。
  `evaluate` で `agent` が `bypass` / `bypass-worker` / `bypass-fleet-worker` かつ
  `effect === "ask"` なら `allow` へ書き換える
- 設定の種類:
  - **A**: V1 のマップ + plugin あり
  - **B**: A から plugin を外した対照
  - **C**: V2 の配列版（`agents.bypass.permissions = [subagent × 3]`）+ plugin あり
- 各試験は 1 回の tool 呼び出しだけを頼むプロンプトで、`--agent bypass`、`--auto` なし
  （ask は自動拒否されるので ask と allow を区別できる）。一部は `--auto` あり
- 作業ツリーの外の読み取りは、書き込みを避けて既存の `/etc/os-release` と
  `/home/applejxd/.profile` を使った。`.env` / `id_rsa` / `.env.local` は
  `.tmp/bypass-exp/work/` のダミー

## 結果

「before」は `evaluate` の入力時の effect。「静的」は `evaluate` が**呼ばれなかった**
（config の deny が前段で効く）。

| # | 項目 | 設定 | 結果 |
| --- | --- | --- | --- |
| 1 | shell `touch …/x` | A | **確認なしで実行**（before `ask` → `allow`、`agent: "bypass"`）。`--auto` なしも あり も同じ |
| 1 | shell `rm …/x1`（`rm *` は ask 規則） | A | 実行された（before `ask` → `allow`） |
| 2 | read / edit / write（通常の作業ファイル） | A | 実行された。before は**もともと `allow`**（書き換え不要）。`write` の action は `edit` |
| 2 | read / edit（`.env.local`。通常は ask の規則） | A | 実行された（before `ask` → `allow`）。**ask 規則の秘密ファイルまで通る** |
| 3 | `/etc/os-release` の read | A / C | 実行された。`external_directory`（resource `/etc/*`）が before `ask` → `allow`、続く `read` は `allow`。`--auto` でも同じ |
| 3 | `/home/applejxd/.profile` の read | A | 実行された。`external_directory`（`/home/applejxd/*`）が before `ask` → `allow` |
| 4 | `pip --version` | A / C（`--auto` あり・なし） | **`Permission denied: shell`**。静的（`evaluate` 記録なし） |
| 4 | `.env` / `id_rsa` の read | A（`--auto` あり・なし） | **`Permission denied: read`**。静的 |
| 4 | `…/sub/.ssh/x` の write（`*/.ssh/*` の edit deny） | A | **`Permission denied: edit`**。静的 |
| 5 | `bypass` → `bypass-worker` の起動 | A / C | 起動でき `WORKER_OK`。`evaluate` は `subagent`（`bypass-worker`）が `allow` → `allow` |
| 5 | `build` → `bypass-worker` の起動 | A | **`Permission denied: subagent`**（静的。`agent: "build"` の `execute.before` のみ） |
| 5 | `bypass` → `general` の起動 | A / C | `Permission denied: subagent`（静的）。`general` / `fleet-worker` を外す task 規則は効く |
| 5 | `bypass-worker` 内の `touch` | A | 実行された。`evaluate` の `agent: "bypass-worker"`、before `ask` → `allow` |
| 6 | `bypass` → ask 規則を持つ子（`askchild`：`shell * ask` だけの試験用） | A | 子の `evaluate` は `agent: "askchild"`、before `ask` → **`ask` のまま**。ファイルは作られない。`--auto` なしで確認が自動拒否されず、**170 秒で timeout**（下の注） |
| 7 | shell `touch`（`--auto` なし） | B | `permission requested: shell …; auto-rejecting` で**拒否**。`--auto` ありは通る（自動承認） |
| 7 | `.env.local` の read / edit | B | 自動拒否 |
| 7 | `/etc/os-release`、`/home/applejxd/.profile` の read | B | 自動拒否（外部ディレクトリの ask） |
| 7 | 通常ファイルの read / edit / write | B | 通る（もともと allow なので A と同じ） |
| 7 | `pip --version`、`id_rsa` の read | B | A と同じく deny（静的） |
| 8 | `evaluate` の記録 | A / C | `shell`・`read`・`edit`・`external_directory`・`subagent` の**すべてに `agent` が載った**。書き換え（`ask` → `allow`）は挙動に反映された（1・3） |

### 補足

- 6 の `askchild` は `commit` の代わりの試験用の子（`commit` は実際に git commit を
  するので使っていない）。`agents.askchild = { mode = "subagent", permissions = [shell * ask] }`。
  `commit` と同じく**子の agent 名は `bypass` ではない**ので、plugin の対象外になった。
  `--auto` なしの子では ask が自動拒否されず待ち続けた（timeout で打ち切った）。
  拒否にならなかった理由は未確認。ask のまま allow に化けないことだけを確認した
- 2 の通常ファイルの read / edit / write は、**通常エージェントでも元から allow**
  （B で確認）。引き上げが要るのは shell の ask 規則・`.env.*` などの ask 規則・
  外部ディレクトリ（`external_directory`）
- 3 の `external_directory` は read の前に別 action として立ち、先にその ask が出る
  （[hook の呼ばれ方](hook-order.md)と同じ）。plugin が書き換えれば read まで通る
- C（V2 の配列版）は A と同じ結果になった（1・3・4・5 を確認。6 と `.env` の read、
  `--auto` なしの 7 は C では試していない）

## 結論

**方式は成立する。** `bypass` の `permission` から `*` の allow を外し、`evaluate` で
`bypass` / `bypass-worker` / `bypass-fleet-worker` の `ask` を `allow` に書き換えるだけで:

- shell・外部ディレクトリ・ask 規則の read / edit が確認なしで通る
- 静的 deny（`pip`、秘密ファイル、`.ssh` の edit）は `evaluate` を通らず、そのまま止まる。
  **現行の `"*" = "allow"` では外れていた秘密ファイルの read deny が残る**
- 子エージェントの起動元の制限（`bypass` からだけ `bypass-worker`、`general` は deny）は
  task 規則だけで保てる
- ask 規則を持つ子（`commit` 相当）の ask は、agent 名が違うので allow に化けない
- plugin を外すと 1・3 は ask に戻り、`--auto` なしでは自動拒否される（安全側）

## 注意点・設計上の含意

- **ask 規則の秘密ファイル（`.env.*` の read / edit）まで allow になる。** 現行 bypass は
  `.env.*` も通るので後退ではないが、「deny はそのまま」の範囲は**静的 deny だけ**。
  ask のまま残したい規則は、plugin 側で resource を見て除外する必要がある
  （`e.resources` は読めるが、除外の一覧は別に持つことになる）
- `evaluate` の `effect` は `deny` なら呼ばれない。plugin が緩められるのは `ask` → `allow` だけで、
  deny を外すことは構造上できない（これが利点でもある）
- `mode = "primary"` の宣言や、`bypass-worker` の `task = "deny"` は従来どおり要る
  （`*` の allow が無くなっても、子の入れ子を止めるのは subagent の deny）
- plugin 内の `bypass` の名前一覧は、生成器が `rules.json` の `bypass_agents` で出している
  ものと揃える必要がある（今回は決め打ち）。現行の「全部 allow のエージェント」の判定
  （`_grants_everything`）は使えなくなる（`*` の allow が無いため）。別の印が要る
- 全体の `permissions` に残る `{subagent, bypass-worker, deny}` は、`bypass` の
  `task "*" allow` が後ろに付いて上書きする（実測どおり。A・C）

## 未確認

- plugin のロードに失敗したとき（壊れた `index.js` など）の挙動。ロード失敗は plugin 無し（B）と
  同じ ask に戻るはずだが、今回は試していない
- 本物の `commit` エージェントを `bypass` から起動した結果（`askchild` の代用で
  agent 名による非対象を確認しただけ）
- `--auto` なしで子の ask が自動拒否されず待ち続けた理由（親の ask は自動拒否された）。
  対話モード（TUI）での挙動も未確認
- 並列 tool 呼び出しで ask と allow が混ざる場合
- TUI で `bypass` に切り替えたときの `evaluate` の `agent`（今回は `--agent bypass` の
  `opencode run` のみ）
- Windows / macOS（WSL2 Ubuntu のみ）
- 設定の種類 C で `fleet-worker` / `bypass-fleet-worker` の deny の細部は確認していない

## 追記（2026-10-03）: 実装後の実測

実際の生成物（`generate.py`）と実際の `guide-plugin`（`.tmp/` に写した一時設定。
`OPENCODE_PROBE_CONFIG`）で、`--agent bypass` / `--agent build`、モデル
`github-copilot/claude-haiku-4.5`、`--auto` なしで確認した。

| 項目 | 結果 |
| --- | --- |
| `bypass`: shell `touch …`（ask 規則） | **確認なしで実行**された |
| `bypass`: shell `pip --version` | 誘導文（`uv add` など）付きで止まった（`execute.before` の前段停止。`bypass` でも効く） |
| `bypass`: read `.env` / `.env.local` | どちらも `Permission denied: read` |
| `bypass`: read `.env.example` | 読めた（deny の例外） |
| `bypass` → `bypass-worker` の起動 | 起動でき `WORKER_OK` |
| `build` → `bypass-worker` の起動 | 起動できない（一覧に出ない） |
| `build`: shell `touch …`（対照） | `auto-rejecting`（ask のまま。`bypass` 以外は変わらない） |

`bypass` の `permission` には全 allow が無く（`task` の規則だけ）、`bypass-fleet-worker` は
`fleet-worker` と同じ deny だけを持つ。

### 追記 2（2026-10-03）: 誘導・作業役・`.env.*`・例外の位置

上と同じ方法（`.tmp/` のダミーのリポジトリと `.ssh/` 相当のディレクトリ）で、`--agent bypass`:

| 項目 | 結果 |
| --- | --- |
| shell `rm -rf <ダミー>/.git`（`rm *` は ask 規則） | 誘導文付きで止まった（`evaluate` 経由の誘導が `bypass` でも効く。ask→deny） |
| `bypass` → `bypass-fleet-worker` の起動 | 起動でき `FLEET_OK` |
| edit `app/.env.local`、write `app/.env.production` | どちらも `Permission denied: edit` |
| write `app/.env.example` | 成功（deny の例外） |
| read `app/.env.example` | 読めた |
| read `.ssh/.env.example`（`.ssh/*` の deny に当たる一時パス） | `Permission denied: read`（例外は `.env.*` の deny にだけ効き、`.ssh` の deny は残る） |

未確認: `commit` を `bypass` から起動した結果、TUI での `bypass` 選択。

[調査記録一覧へ戻る](../../index.md)
