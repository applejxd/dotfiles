# 過去セッションの引き継ぎ（session-recall）の評価（2026-11）

観測日: 2026-11-18。対象: pi 1.5.0 のセッションログ（`~/.pi/agent/sessions/`）を、新規セッションから読んで引き継ぐ手段。
問い: 既存の拡張で足りるか。足りなければ、skill + CLI（[ADR-0031](../../adr/0031-evaluate-existing-extensions-first.md) の梯子の ④）で何を作るか。

## 結論

- 検索・再読込・handoff を提供する pi の公開 package は複数ある。ただし **どれも「今の cwd のリポジトリだけ」を強制できない**（既定は全プロジェクト。cwd への絞り込みは、モデルが引数で選ぶ）。どれも第三者の若いコード（候補ごとの版・★は下の表）で、拡張自身のコードでログを読むので、pi の権限の判定を通らない。
- 権限の規則には「今の作業ディレクトリ」を表す変数が無い（`@gotgenes/pi-permission-system` 42.0.0 の configuration.md（パッケージ内）と `wildcard-matcher.ts` で確認。展開されるのは先頭の `~`・`$HOME` だけ）。「今のリポジトリのログだけ allow」は、権限だけでは書けない。
- そこで、**cwd から読む範囲を固定する専用スクリプト**を skill にした（`home/dot_agents/skills/session-recall/`）。本体と全 worktree のログだけが見え、他のリポジトリを指す引数は無い。
- コンテキストの節約を、実ログで測った: 8 セッションで **13,719,448 B → 286,313 字（2.1%）**。

## 既存の拡張の調査（2026-11-18 時点。README を取得して確認）

| 候補 | 内容 | 権限・送信 | 採らない理由 |
| --- | --- | --- | --- |
| [`pi-session-history`](https://github.com/yoyooyooo/pi-session-history) 0.1.0（MIT。★1・コミット 3） | `pi_history`（search / list / read）、`/history` | 読み取り専用・外部送信なし。出力は 50KiB に制限。`scope: "cwd"` で絞れる | 既定は全プロジェクトで、`scope` はモデルが選ぶ。README 自身が「資格情報が混じりうる」と注記 |
| [`@adobe/pi-session-search`](https://github.com/adobe/pi-session-search)（Apache-2.0。★11・コミット 5） | `search_sessions`・`read_session`・`/find-sessions` | 読み取り専用・モデル呼び出しなし・ネットワークなし。symlink で外へ出る読み取りは拒否 | cwd は部分一致のフィルタで、強制ではない。README 自身が「全セッションを grep できるので、信頼できない入力を扱うと情報持ち出しの道具になる」と注記 |
| `pi-sessions` 0.23.4（MIT） | 検索・`session_recall`・`session_handoff`・subagents・メッセージ送信 | 権限が広い（subagent を `--approve` で起動、他セッションへ送信・中断） | 用途に対して過剰 |
| `samfoy/pi-session-search`（MIT。★27） | FTS5 検索、任意で埋め込み | 埋め込みを設定すると内容を外部へ送る | 外部送信の道が増える |
| `catlain/pi-session-analyzer` | 検索・分析・takeover レポート | 未確認 | 権限が未確認 |
| `sessiongrep`（外部の Rust CLI） | 複数のエージェントのログを SQLite+FTS5 で横断索引 | ローカル。導入は `curl … \| sh` のバイナリ | 横断索引は、範囲の固定と逆の設計 |

他のエージェントの設計（出典の本文を取得して確認）:

- Amp は 2025-10-23 に compaction を handoff（要約でなく「次の作業に要るものを抽出」）へ置き換え（<https://ampcode.com/news/handoff>）、2026-05-06 に自動 compaction へ戻した（<https://ampcode.com/news/neo>）。handoff が最終解だと言える根拠は無い。
- 「生の JSONL を grep すると tool payload に埋もれる」という主張は `sessiongrep` の README にあるが、定量は無い。生ログ方式と抽出方式の実測比較は、見つからなかった。
- ログに秘密が平文で残る事例: Claude Code の issue #71654（2026-06-26。「not planned」で閉じ）。持ち越しのプロンプトインジェクションは、一般論の記事のみ（pi 固有の議論は無い）。

## 実測（この repo のログ。2026-11-18）

```sh
python3 home/dot_agents/skills/session-recall/scripts/session_recall.py list --limit 8 --stats
# 合計: 13719448B → 286313字 (2.1%)。抽出後は user・assistant・toolCall の 1 行・summary の文字数
```

- 生のバイト数は、ツール出力・thinking・各セッション先頭のシステムプロンプトとツール定義を含む。抽出後は、利用者の発話・assistant の本文・ツール呼び出しの 1 行・要約だけ。
- 比率はバイトと文字の比較で、トークン数ではない（日本語は 1 文字が複数バイトなので、トークンの比率は上の値と異なる）。**推測**: 生ログを `grep` すると、1 行が 1 メッセージのため、ツール出力の巨大な行が 1 ヒットで大量に出る。実測はしていない。

## 設計（採ったもの）

- 範囲: cwd の `git worktree list --porcelain` で本体と全 worktree を求め、ディレクトリ名で絞ったあと、**セッション先頭行の `cwd`** で確定する（名前が似た別のリポジトリを除く）。cwd がホーム・ホームの親・`/` のときは拒否する。
- 出力: 既定 12,000 文字まで。thinking・システムメッセージ・ツール出力は既定で除く。秘密を伏せる（`friction_scan.py` と同じ集合 + 秘密鍵・`password=` など。完全ではない）。先頭に「引用であり指示ではない」と付ける。
- 権限の判定を通らない（スクリプトの中の読み取りは対象外。`friction-review` と同じ）。範囲の固定は、**引数を持たない**ことで担保する（誤用の防止であり、悪意のあるモデルへの防御ではない）。

## 維持費と撤去条件（ADR-0031）

- 維持費: pi のセッション形式（今は v3）が変わると、抽出が崩れる。未知のエントリは読み飛ばす作りにしてあり、試験（`test/agents/test_session_recall.py`）で固定している。
- 撤去条件: pi 本体が cwd 限定のセッション検索を標準で持ったとき、または権限の規則が cwd を参照できるようになり、生ログを安全に許可できるようになったとき。

## 未確認

- `pib` の囲いの中での動作（囲いはホームを空で覆うので、`~/.pi/agent/sessions` は見えない設計。0 件のときの案内は試験したが、実際の囲いでは未確認）。
- Windows のパス（`\`・`:`）での動作。
- 既存の拡張の npm 上の最新版・最終更新日・ダウンロード数（`@adobe/pi-session-search` の npm 名は 404）。
