# サンドボックス（総覧）

`pis`（pi をサンドボックスで包む標準の起動）が、**何を・どこまで・何で守るか**の全体像。個々の仕様は下の「文書の地図」へ。
このページは、判断の根拠と責務の分担（どの層が何を強制し、何が保証の外か）を 1 か所にまとめる。

## 目的と脅威モデル

- **最優先**: 本物の認証キー（LLM・GitHub・検索 API）を、エージェントが動く領域（内側）に置かない。
  プロンプトインジェクションで内側の指示が乗っ取られても、キーは持ち出せない。
- **次に**: 内側から読み書きできる範囲を、作業ツリーと必要な場所に絞る（読み取りは既定で拒否し、許可した場所だけ開ける）。
- **保証しないこと**: 内側で許された操作の「中身」の妥当性。認証済みの操作で何ができるかは、**外部のスコープ**（PAT・IAM・ブランチ保護）で決まる。
  コマンドの判定（[ガード](../guard/index.md)）は、境界ではなく「うっかり防止」（Python などで迂回できる）。
- 責務の分担:
  - **OS（Fence）とブローカーが強制する**: 読み書きの境界、デバイス、ネットワーク、認証キーの隔離。
  - **外部のスコープが強制する**: 認証済みの操作の範囲（PAT の権限、IAM、リポジトリのロール、ブランチ保護）。
  - **ガードは補助**: 誤操作の検知と、内容を見た確認。

## 層

| 層 | 役割 | 強制するもの | 正本 |
| --- | --- | --- | --- |
| Fence（bubblewrap など） | 読み書き・デバイス・ネットワークの境界 | 読み取りは既定で拒否（許可した場所だけ開ける）、書き込みは作業ツリーなど、`deny_read` で個別に隠す | [境界の構成](opencode-sandbox.md) |
| 認証ブローカー（Envoy） | 認証キーを内側へ出さずに、LLM・GitHub・検索へ中継 | キーはホスト側の Envoy だけが持つ。内側からは 127.0.0.1 のポートか Unix ソケットだけ | [ブローカー](broker.md) |
| ガード（判定器・拡張） | ツール呼び出しの判定と確認 | deny / ask / confirm（[ガード](../guard/index.md)） | [pi のガード](../guard/pi-guard.md) |

## 起動のモード

| 起動 | サンドボックス | bypass の既定 | ブローカー | 用途 |
| --- | --- | --- | --- | --- |
| `pis` | あり（Linux / WSL のみ） | オン | `[pis.broker]` の設定どおり | 標準。確認（ask）を出さず、deny と confirm は効く |
| `pis --no-bypass` | あり | オフ | 同上 | 確認（ask）を出す |
| `pis --no-sandbox` | なし（守りはガードだけ） | オフ | 同上 | ガード自身のソースを変えるとき（サンドボックスの中ではガードのソースが読み取り専用） |
| `pis --no-broker` | あり | 既定どおり | **外す**（内側に本物の認証が入る。通知が出る） | ブローカーを一時的に外すとき |
| 素の `pi` | なし | — | なし | Windows・Orca・Zed。ガードの拡張は自動で読まれる |

`--bypass` / `--no-bypass` で明示できる。bypass は ask を許可に変えるが、**deny と confirm（外部への送信・公開の確認）には効かない**。
環境変数で機能を有効化する入口は作らない（設定 `[pis.broker]` と CLI の引数で指定する）。

## 内側から見えるもの・見えないもの

実測または設定の読み取りで確かめたことだけを書く（`pis` の内側。2026-10 時点）。

| 対象 | 見えるか | 根拠 |
| --- | --- | --- |
| 作業ツリー | 読み書きできる | 境界の設定（`allowWrite`） |
| `~/.config/agents`（判定器の設定） | 読めるが書けない | `[pi.sandbox] read` |
| `~/.config/agents/websearch-keys.json`（検索 API の鍵） | **見えない**（読むと「許可がありません」。`/dev/null` と同じ文字デバイスに見える） | `[pi.sandbox] deny_read`。実測 2026-10-25。**`test -r` は真になる**ので、可否は実際に読んで確かめる |
| `~/.pi/agent/auth.json`、`/run/user/*`、ホストのプロセス | 見えない | 実測 2026-10-24 |
| ホームの他の場所（`~/.ssh`、`~/.aws` など） | 既定で見えない（読み取りは既定で拒否） | `defaultDenyRead`（境界の生成）。個別には未実測 |
| 環境変数 `GH_TOKEN`・`GITHUB_TOKEN`・`SSH_AUTH_SOCK`・`AWS_*`、名前に `TOKEN`・`SECRET`・`PASSWORD`・`PASSPHRASE` を含むもの | 渡さない | `DROP_ENV` とパターン |
| 検索 API の鍵の環境変数（`BRAVE_API_KEY` ほか 3 種） | 渡さない | `DROP_ENV`（2026-10-25 に追加） |
| 作業ツリー内の `.env` や、他の `*_API_KEY` 環境変数 | **見える**（保護していない） | 設計上の穴。利用者が置かない運用に頼る |
| `--no-broker` のときの Copilot の認証 | 見える（内側に本物が入る） | `--no-broker` の仕様 |

## 通信の方針

- **内側から外へ出られる宛先**は、Fence の許可リスト（`[web] allow_domains`・`[sandbox] shell_network_allow`）と、ブローカーのローカルのポート・ソケットだけ。
- 検索のプロバイダー（Brave・Exa・Tavily・OpenAlex・DuckDuckGo）は許可リストに入れず、**検索ブローカー経由**で届く（実測: 内側から検索が通る）。
- ページ本文の取得（`fetch`）は、許可リストの範囲（`[web] allow_domains`）。任意の URL には届かない。
- 方針の候補（未決。[CHG-0037](../../change/0037-pis-usability-and-telemetry.md)）: 許可リスト型から、拒否リスト型（危険な宛先だけ止める）へ。
- **認証つき HTTP プロキシ・TLS 検査を経由する環境での動作は未対応**。設計案と調査は[ブローカー](broker.md#未対応未検証)。

## 設定と試験の対応

| 設定 | 入口 | 試験 |
| --- | --- | --- |
| `[opencode.sandbox]`（共有）・`[pi.sandbox]`（`read`・`deny_read`・`control_dirs`・`protected`・`network_allow`） | `common.toml.tmpl` → 生成器 `pi_sandbox` | `test/agents/test_pi_boundary.py`、`test_generate_opencode_sandbox.py` |
| 内側へ渡さない環境変数 | `ocs/cli.py` の `DROP_ENV`、`ocs/pi.py` | `test/agents/test_opencode_launcher.py` |
| `[pis.broker]` | `common.toml.tmpl` → `rules.json` の `broker.*` | `test_pi_broker_generate.py`、`test_broker.py`、`test_broker_search.py` |
| 起動と境界の検査（カナリア） | `ocs/pi.py`・`ocs/boundary.py` | `test_pi_boundary.py` |

## 文書の地図

- [ブローカー](broker.md): Copilot・GitHub・検索の認証ブローカーの正本。
- [境界の構成（`ocs`）](opencode-sandbox.md): 起動の順序、状態・DB、環境変数での追加、制御ファイルの保護。
- [Claude Code / Copilot CLI の sandbox](agent-sandbox.md): CLI 側の sandbox の層・ネットワーク・seccomp。
- [隔離 GPU サンドボックス（WSL2）](wsl-sandbox.md): 専用の WSL2 ディストロ。
- [ガード（総覧）](../guard/index.md): 判定と確認。

## 未解決

- 作業ツリー内の `.env` と、残りの `*_API_KEY` 環境変数が内側から見える。
- ホームの他の場所の可視性は、個別に実測していない（段 G6 の可視性表）。
- 通信の方針（拒否リスト型）、認証つき HTTP プロキシ、Bedrock の署名・AgentCore の MCP 中継は未対応。
- 経緯と未解決は [CHG-0033](../../change/0033-sandbox-build-value-assessment.md)（責務の棚卸し）・[CHG-0037](../../change/0037-pis-usability-and-telemetry.md)。
