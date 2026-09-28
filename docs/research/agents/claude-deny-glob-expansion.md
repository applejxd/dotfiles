# Claude の sandbox で名前マッチの deny が何件に展開されるか

- **観測日**: 2026-09-13（記録したコミット `7f30a80` は 2026-09-14 00:12）
- **対象**: Claude Code の Linux sandbox（bubblewrap）。数えたのは作業していた機械の
  `$HOME`（OS の記録は無い。同じコミットで記録した Copilot の実測は WSL2）
- **一次情報**: コミット `7f30a80`（`feat(agents): align Claude and Copilot sandboxes
  on a whitelist model`）の本文と、同コミットで `docs/spec/agent-permissions.md` に
  書いた表。**展開数を数えたコマンドと生の出力は残っていない**
- **関連する不具合**: [anthropics/claude-code#45451](https://github.com/anthropics/claude-code/issues/45451)

現在の方式（deny は `~/` の 1 本にして whitelist 化する）と、その理由は
[sandbox (Claude Code / Copilot CLI)](../../spec/agent-sandbox.md#なぜ広い名前マッチを-deny-に置かないか)
が正本。ここには、その判断の根拠になった測定だけを残す。

## 前提

当時の `[sandbox]` は Claude の既定（read は全許可）のまま、秘密らしい名前を
glob で並べて `denyRead` / `denyWrite` に流していた。Claude の Linux sandbox は
**deny 対象の各パスに `/dev/null` を bind-mount する**ので、glob は展開された
パスの数だけ mount になる。

## 測定結果

| パターン | 展開数 |
| --- | ---: |
| `~/**/*secret*` | 1316 |
| `~/**/*credential*` | 1103 |
| `~/**/*.pem` | 473 |
| `~/**/*password*` | 285 |
| **deny 全体** | **3239** |

- 大半は誤検知だった（`node_modules` 配下のテスト用証明書など）
- sandbox 内でコマンドを 1 回実行するたびに、これだけの bind-mount が要る
- 加えて、deny 対象が symlink を経由すると bwrap のセットアップごと失敗し、
  sandbox 内のコマンドが全部動かなくなる（#45451。この環境で再現させたかは記録が無い）

## この測定で変えたこと

deny を whitelist に置き換えた（`denyRead: ["~/"]` + `allowRead` で穴を開ける）。
deny は `~/` の 1 本になり、3239 件の展開も symlink による失敗も起きなくなった。
不変条件は `test_deny_has_no_broad_name_globs` で固定している。

**未検証**: 新しい方式で Claude を実際に動かした確認は、この時点ではしていない
（コミット本文によると、この環境で Claude が `401 invalid OAuth token` を返した）。
