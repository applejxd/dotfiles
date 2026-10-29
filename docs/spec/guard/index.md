# ガード（総覧）

pi のツール呼び出し（`bash`・`read`・`edit`・`write`・`grep`・`find`・`ls`・`task` など）を、**実行の前に判定し、必要なら確認を出す**仕組みの全体像。
サンドボックス（[総覧](../sandbox/index.md)）が OS で強制するのに対し、ガードは**「うっかり防止」**。Python などで迂回できるので、境界とは呼ばない。

## 目的と保証の範囲

- **防ぐもの**: 誤操作（破壊的な削除、意図しない外部への送信・公開、秘密の表示、危険なパイプ実行など）。
- **保証しないもの**: 悪意のある迂回（スクリプト経由の送信など）。**迂回できないのは、OS・ブローカー・外部のスコープ**（PAT・IAM・ブランチ保護）だけ。
- 方針（[CHG-0038](../../change/0038-guard-reclassification.md)）: ガードの規則は「防ぐ害」で分類し、**公開・削除のような決定的な防御は、できるだけ外部の権限で**行う。
  ガードは、内容を人が見て決める確認（投稿など）と、明瞭な誤操作の検知に絞る。
- 現状の保証の限界: 認証済みの GitHub 操作以外の外部書き込み（`curl` / `wget` の POST、MCP の書き込み、Python 経由）は、bypass 可能な ask か、判定の外。

## 判定の 4 つの結果

| 結果 | 意味 | bypass | 例 |
| --- | --- | --- | --- |
| **deny** | 実行しない。理由と代替をモデルへ返す | 効かない | `rm -rf` の危険な形、`curl \| sh`、`gh repo edit`、`npm publish`、`docker push`、`gh api` の公開・配布系 |
| **confirm**（`mustConfirm` の ask） | 内容を見せて利用者に確認する。無反応は deny | **効かない**（bypass でもサンドボックスの緩和でも allow にならない） | `gh pr create`、`gh issue comment`、`gh api` の書き込み |
| **ask** | 確認する | bypass で許可になる | `git commit`、`[bash] ask` の各種、作業ツリー外の読み書き |
| **allow** | そのまま実行 | — | 読み取り系の定型コマンド、作業ツリー内の読み書き |

確認を出せない（UI が無い: print モード、子エージェント）ときは、ask・confirm とも **deny**（`not approved:` の接頭辞を保つ）。

## 評価の順番

共通の禁止 → 役割のツール → 誘導 → `guarded_action` の置き換え → 役割の `shell_deny` → confirm → ask / allow → 既定 → サンドボックスの緩和と bypass の順。
各段の仕様の正本は [判定 API](pi-decide.md#評価の順番)。

## 役割

`[pi.profiles]` の役割ごとに、使えるツールと既定を決める（実装役・読み取り役・探索役など）。子エージェントは、同じガードと判定器で、子の役割で判定される。
`bypass` は子へ引き継がない（`inherit_bypass` で明示した場合だけ）。

## 確認（confirm）の振る舞い

判定は [confirm](pi-decide.md#confirm)、確認画面は [確認の UI](pi-guard.md#confirm-の確認) が正本。
無反応は deny（`[pi.confirm] timeout_seconds`、既定 300）。公開・配布（`gh repo edit/create`、`npm publish` など）は、確認ではなく deny。

## 権限の設計（GitHub）

決定的な防御は、トークンのスコープで行う（[CHG-0038 段 G10](../../change/0038-guard-reclassification.md)）。

- 個人機: fine-grained PAT（Metadata Read・Issues Write・Pull requests Write・Contents Read、Administration 無し）が理想。fine-grained PAT は Web でしか作れない。
- 制約のある環境の機: fine-grained PAT が使えず classic PAT だけの場合がある。`repo` スコープは粗く、**投稿だけ許して push を許さない形は作れない**。リポジトリのロールが Admin でない場合、Admin 級（公開化・設定変更・Webhook・削除）を拒否させ、保護ブランチは規則で守る。非保護ブランチへの refs・contents・release の書き込みと GraphQL の mutation は、PAT では塞げず、判定器の deny が残る。
- 判定器の `gh api` 公開系の列挙（`check_gh_api_publish`）は、権限側で塞げると確認できた部分から縮小する。確認が取れていない部分は撤去しない。確認の進み具合は [CHG-0038](../../change/0038-guard-reclassification.md)。

## 投稿・コミットの流れ（`guarded_action`）

`git commit`・`gh issue comment`・`gh issue edit` は、**内容を見せて 1 回だけ承認を取り、承認した内容で実行する**専用ツール `guarded_action` に寄せる（同じ操作の bash は deny）。
操作は `[[pi.actions]]` の表で宣言する。仕様の正本は [pi のガード](pi-extensions.md#guarded_action承認つきの外部操作)。

## ツール定義の拡張

`guarded_read`・`guarded_write`・`guarded_edit`・`guarded_bash` の説明と引数を、使用コストを下げる形で拡張している。
仕様の正本は [pi のガード](pi-extensions.md#ツールの拡張guarded_read--guarded_write--guarded_bash-の使いやすさ)、経緯と目標は [CHG-0038](../../change/0038-guard-reclassification.md)。

## 設定と試験の対応

| 設定・実装 | 入口 | 試験 |
| --- | --- | --- |
| `[bash]`（allow / ask / deny / deny_guide）、`[file]`、`[pi.shell]`、`[pi.profiles]` | `common.toml.tmpl` → 生成器 | `test_check_bash_*.py`、`test_pi_*.py` |
| `[pi.confirm]`（確認表・`checks`・`timeout_seconds`） | `common.toml.tmpl` → `rules.json` の `judge.common.pi.confirm` | `test_pi_confirm.py`、`test_pi_confirm_view.py`、`test_pi_harness.py` |
| 判定器（TS 版が本番、Python 版が照合用） | `home/dot_config/pi/harness/judge/`、`home/dot_claude/hooks/lib/bashrules/` | `test_decide_golden.py`、`test_pi_boundary.py`（正解データの照合） |
| ツールの拡張 | `home/dot_config/pi/harness/tools-ext.ts` | `test_pi_tools_ext.py` |

判定器を触るときは、TS・Python の両実装と、正解データ 3 種（`scripts/agents/export_{decide,policy,checks}_golden.py`）の再生成が要る。

## 文書の地図

- [判定 API（`decide`）](pi-decide.md): 入力・応答・評価の順番・confirm・誘導・TS 版への移植。
- [pi のガード](pi-guard.md): 起動・bypass・confirm の UI・Windows・pi の設定・MCP。
- [pi の拡張と補助機能](pi-extensions.md): 拡張の方針・`guarded_action`・ツールの拡張・圧縮・commit の確認・整形・`/fleet`。
- [gitflow 規約の強制](pi-gitflow-guard.md): develop / main の作業ツリーを直接編集・コミットさせない制限層（CHG-0049）。
- [pi の子エージェント](pi-subagents.md): `guarded_task`・job・worktree 隔離・Windows の `task`。
- [pis のサンドボックス（pi の側）](pi-sandbox.md): agent 置き場・通信・緩和のゲート。
- [OpenCode のガードの仕様](opencode-guard.md): 保留中のレガシー（撤去予定）の誘導・deny の説明。
- [コマンド・ファイルの判定](agent-command-policy.md): 照合規則、allow / ask / deny の一覧、意味解析。
- [設定の生成](../agent-config-generation.md): `common.toml` から各 CLI の設定を作る仕組み。
- [サンドボックス（総覧）](../sandbox/index.md)。

## 未解決

進行中の課題は案件で管理する。

- 確認画面・GitHub のトークン権限の実機確認: [CHG-0038](../../change/0038-guard-reclassification.md)、[CHG-0040](../../change/0040-pi-guard-by-settings.md)
- Python 版の判定器（照合用）の撤去: [CHG-0035](../../change/0035-retire-python-judge-oracle.md)
- 経緯と調査: [他社の比較](../../research/agents/permission-bypass-survey.md)、[代替設計の調査](../../research/agents/guard-design-alternatives.md)
