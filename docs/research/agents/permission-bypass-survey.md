# 全承認（bypass・yolo）モードでも確認を残す仕組みと、公開・送信系のガードの分類

- **観測日**: 2026-10-25。`explore` の子 3 件（公式 docs・ソース・issue・第三者の記事。取得日が分からないものは日付を書かない）。実行は無し
- **目的**: 自作ハーネスの `confirm`（bypass でも確認を出す ask。[pi-decide.md](../../spec/guard/pi-decide.md#confirm)）と、公開・配布の deny／投稿の確認の分類表の参考（[CHG-0038](../../change/0038-guard-reclassification.md) 段 G1〜G5）

## 結論

- **自作の `confirm` と最も近いのは Claude Code**: bypass でも、明示した ask 規則と hook の ask は確認を出し、deny 規則は全モードで効く。UI が無い（`-p`）ときは、確認が残る呼び出しは deny。設計の方向は一致
- **全承認モードで確認を残す仕組みは、製品でまちまち**: Gemini CLI は priority の階層で、yolo でも `ask_user`／deny を上に置ける。Codex は `forbidden > prompt > allow` だが、yolo に近い設定で `prompt` が効かない不具合の報告が未解決。VS Code は「Allow all」で全部通り、deny の仕組みは無い。Cursor は Agent Hooks のみ
- **外部送信・公開を、既定で止める製品は無い**。`git push` などは、利用者が ask／deny の規則で足す前提。公開・投稿系を網羅した OSS は見つからなかった（自作の表のほうが先行）
- **落とし穴の報告**: ① 上位層が ask を黙って自動回答する（Claude Code の VS Code 拡張の古い版で、hook の `permissionDecision: "ask"` が bypass で自動承認された。issue #77212）。② 「prompt 規則が最上位で強制される」ことを試験で固定する必要（Codex の issue #25312）

## Claude Code（公式 docs）

- <https://code.claude.com/docs/en/permission-modes>: 「Deny rules block in every mode, including bypassPermissions」「Allow rules have no effect in bypassPermissions」。bypass でも自動承認しないもの: 明示した ask 規則、組織が ask にした connector tool、`AskUserQuestion`、`rm`/`rmdir` の重要パスの削除（allow 規則や hook の allow でも承認されない）、作業ディレクトリ外の読み取り（`blockReadsOutsideWorkingDirectories` が有効なとき）。`claude -p --dangerously-skip-permissions` では、確認が残る呼び出しは deny。保護パス（`.git`・`.claude`）への書き込みは、bypass では通る
- <https://code.claude.com/docs/en/permissions>: 評価順は「deny → ask → allow」。広い deny を狭い allow で上書きできない。「a matching ask rule prompts even when a more specific allow rule also matches」。「Permission rules are enforced by Claude Code, not by the model」。`git -C . push` のような別形は `git push *` に当たらない、と明記
- 確認の内容: 「A permission prompt shows what Claude is about to do」（hook の理由も出る）。重要パス削除の確認には、無人時のカウントダウンがある（時間切れの結果は未確認）

## 他の製品

| 製品 | 全承認でも残る確認 | deny は全承認で効くか | 出典 |
| --- | --- | --- | --- |
| Gemini CLI | priority 998 の yolo の全許可に対し、`ask_user` は 999 で yolo でも対話が残る | 階層で効く（実機は未確認） | 公式ソース（`yolo.toml`、policy-engine.md） |
| Codex | `prefix_rule(decision="prompt")`。複数規則に当たると forbidden > prompt > allow | `forbidden` が最強。ただし yolo 時の `prompt` が効かない不具合の報告（#25312。open） | 公式 docs と issue |
| OpenCode | `"git push *": "ask"` などの規則 | deny あり。「全承認でも残す」仕組みは未確認 | 検索結果の抜粋 |
| VS Code Copilot | 「Allow all」は確認なし。`autoApprove` の false は「承認要求であって、ブロックではない」 | deny の仕組みは未確認 | 公式 docs |
| Cursor | 「Run Everything」は確認なし。deny は Agent Hooks のみ | — | 第三者の記事 |

## pi の公開拡張（導入はしない。ADR-0016）

- pi.dev で `permission` を検索すると 84 件。主流は、allow／ask／deny の規則型（MasuRii/pi-permission-system ★175 など）、サンドボックス型、LLM による自動承認型。**bypass でも出す確認を設計の柱にした拡張は、概要の範囲では見つからなかった**
- 同梱の `permission-gate.ts`（pi 1.3.0）は、正規表現 3 種に当たったものだけを `select` で確認し、UI が無ければ deny。**bypass の概念も、タイムアウトも無い**（自作のほうが強い）。`timed-confirm.ts` は `confirm` の `{timeout}` の例（時間切れは falsy）。pi の `timeout` は TUI でも守られる（画面を出した時点から数え、残り秒数が出て、期限で false。ソースを確認）。RPC でも `hasUI` は真（子は、親が UI 要求を自動で取り消す）
- 参考にできる点: 確認の選択肢に「理由つきで拒否」を持ち、拒否の理由をモデルへ返す（MasuRii）。**deny は床**（後から重ねる規則で緩められない）。入力が改変された後の引数で再判定する。判定を JSONL の監査ログに残す（pi-bouncer）。oh-my-pi の承認モードは、**確定キーを表示直後の 0.5 秒だけ無視**（誤入力の防止）、本文を 1 行に要約して全文は展開、UI が無いときは黙って許可せず失敗

## コマンドガードの OSS（公開・送信系の分類）

- **dcg**（Dicklesworthstone/destructive_command_guard）: `platform.github` は破壊系が手厚い（`gh repo delete`、`gh repo edit --visibility`、`gh repo archive`、`gh gist/release/issue delete`、secrets・variables・hooks・keys の DELETE、`gh api -X DELETE`）。`gh pr/issue create`・`gh repo create`・`gh workflow run`・`gh api` の POST/PUT/PATCH は規則が無い。publish 系（`npm/yarn/pnpm publish`、`cargo publish`、`gem push` など）は deny で、既定では無効（opt-in）。`publish` は「サブコマンド位置か」をトークン解析で判定（引用された値と区別）。`--dry-run` の免除は同一セグメントに限る。評価が時間切れ・上限超えのときは allow にせず ask/deny。**`gh api` は「`-X GET` 明示のときだけ safe」で、`-f`/`-F` による暗黙の POST に手当てが無い**
- **すり抜けの報告（dcg）**: #423 `gh repo edit --description --help --visibility public` が通っていた（cobra が値を取るフラグの直前の `--help` を値として食う）。#306 `--dry-run` が別セグメントの publish を隠していた。#380 `delete` と `delete-asset` の取り違え。正規表現のバックトラック上限で fail-open になりうる
- **guardrail**（0★）: `public_publish_guard`（`gh repo create --public`、`gh gist create -p`、visibility の public 化）。`self_bypass_guard` と HMAC 署名トークンで、エージェントが自分でゲートを開けないようにする
- **Codex の execpolicy**: `prefix_rule` は完全な前置一致で、`gh pr --repo x view` のような前置フラグに弱い。`bash -lc` は単純な連結のときだけ分解する（変数・`$()`・リダイレクトを含むと、全体を 1 コマンドとして規則に当てる）
- **gg**（github-guard）: git／gh の薄いプロキシで、`confirm`（端末で y/n）と `deny` の glob。「経由したときだけ効く」と明記
- **Trail of Bits**: 既定は `rm -rf` と main への直接 push だけ。「フックは安全境界ではなく、プロンプトインジェクションで回避できる」

## 自作の表との比較（推測を含む）

- **先行している点**: `gh api` の公開系（REST のエンドポイントと GraphQL のミューテーション名）の列挙は、調べた OSS に見当たらなかった
- **取り入れる点**: `gh api` に `-f`/`-F`/`--input` があれば書き込みとみなす判定、`-X` の別形（`--method=PUT`、`-XPUT`）と前置フラグ（`gh --hostname x api`）への対応（試験で確かめる）。評価の失敗は allow にしない。`publish` のトークン位置の判定は、現状の前方一致で足りるかを試験で確かめる
- **過剰な点**: dcg の `gh run cancel`・`gh issue delete`・`gh gist delete` の deny は、日常の用途と衝突しうる（自作は確認に倒す）

## 未確認

- Claude Code の「Time limits and denials in auto and bypassPermissions modes」の本文（時間切れの結果）と hooks docs。Gemini の yolo と user 層の deny の実機の勝ち負け。cc-safe・claude-code-safety-net の docs・nono・sbx・OWASP の記事
- pi の公開拡張のうち、npm が取得できなかったもの（pi-bouncer の README 以外の詳細）。各リポジトリの最終更新日

## 参照

- <https://code.claude.com/docs/en/permission-modes>、<https://code.claude.com/docs/en/permissions>、<https://github.com/anthropics/claude-code/issues/77212>
- <https://github.com/google-gemini/gemini-cli>（`packages/core/src/policy/policies/yolo.toml`、`docs/reference/policy-engine.md`）
- <https://developers.openai.com/codex/rules>、<https://github.com/openai/codex/issues/25312>、<https://code.visualstudio.com/docs/agents/run/approvals>
- <https://pi.dev/packages?name=permission>、<https://github.com/MasuRii/pi-permission-system>、<https://github.com/gvanderclay/pi-bouncer>、<https://github.com/can1357/oh-my-pi/blob/main/docs/approval-mode.md>
- <https://github.com/Dicklesworthstone/destructive_command_guard>、<https://developers.openai.com/codex/rules>（execpolicy）
