# CHG-0011: AI エージェントがシェルの主な利用者である前提へ整える

- **状態**: In progress
- **更新日**: 2026-10-03
- **基準**: ecaf230（起動ファイルの対話 / 非対話の分離。
  [シェルの起動契約](../spec/structure.md#シェルの起動契約)と
  `test/test_shell_startup.py`）

## 目的と非目的

**目的**: シェルを使うのが主に AI エージェント（非対話・非 TTY で起動）である前提で、
起動ファイル・環境変数・OpenCode の拒否規則の残課題を片付ける。
横断レビューで出た残課題が対象。

**非目的**:

- Nix 化、`rm` を `gomi` に差し替える alias、`is_human` による人間判定
  （参考記事 <https://tellme.tokyo/post/2026/10/01/ai-agent-first-dotfiles/> のうち不採用。
  理由は[シェルの起動契約](../spec/structure.md#シェルの起動契約)）
- `EDITOR=true` のように成功を偽装する設定
- 安全境界の強化。危険な `rm` の拒否は「うっかり防止」であって完全な保護ではない

## 実施計画

作業の記号（`1a` `2a` など）と波（実施の順）をここで定義する。

| 記号 | 内容 | 波 | 状態 |
| --- | --- | --- | --- |
| 0 | 本案件の起票と、「シェルの起動契約」の表記の正確化（全シェル / 全 bash が言い過ぎ） | 1 | 完了 |
| 1a | ROS 読み込みの選び方を一定にし、ROS 用ディレクトリが空のときの不具合を直す | 1 | 完了（`ROS_DISTRO` を優先し、無ければ候補が 1 つのときだけ読む） |
| 1b | WSL の `wslenv.sh` が全シェルで `fcitx-autostart` / `xset` を起動するのを対話側へ移す | 1 | 完了（WSL 実機の対話シェルでの起動は未確認） |
| 2c | git が入力を求めないための環境変数（Q2、Q3）と、OpenCode プラグインから入れられるかの調査 | 1 | 完了 |
| 2a | 非対話シェルで mise のツールを使えるよう、`shellenv.sh` で shims を PATH に足す（Q1） | 2 | 完了（実装・実測済み。[調査記録](../research/shell/mise-shims-resolution.md)） |
| 1c | 秘密ファイル一覧（hook の `tables.toml` と `common.toml.tmpl` の `read_deny_globs`）をそろえ、直下以外の `.env` の保護を実測する | 2 | 完了（一覧をそろえ `.env` を `**/` 化。[調査記録](../research/agents/secret-file-lists.md)） |
| 1d | PowerShell の補助関数を対話判定の後ろへ。Console 設定の失敗を無視する。既定文字コード（`*:Encoding`）は 5.1 の退行を避けるため非対話でも維持 | 2 | 実装済み（Windows 実機は未検証） |
| 2b | OpenCode の拒否規則: pip 系を止めて uv へ誘導（Q4）、危険な `rm` を止める（Q5） | 3 | 実装済み（guide 規則・実機確認済み。[ADR-0013](../adr/0013-opencode-shell-guard-inside-ocs.md)。通常版の pip の静的 deny にも `execute.before` で誘導文を付けた。[実測](../research/opencode/permission/early-guard.md)） |
| 3a | git の環境変数を AI CLI の起動側で入れる（Q2、Q3）。OpenCode は `guide-plugin` の `shell.create.before` で実装済み（Claude Code / Copilot CLI は未着手） | 3 | 進行中 |

状態: 未着手 / 進行中 / 調査中 / 完了 / 保留 / 見送り

## 現在地

2026-10-03 に、次の方針をユーザーと決めた。実測は
[mise の shims](../research/shell/mise-shims-resolution.md)、
[非対話の git](../research/agents/noninteractive-git-env.md)、
[秘密ファイル一覧](../research/agents/secret-file-lists.md) にある。

| 問い | 決定 |
| --- | --- |
| Q1 mise を非対話で使う | `shellenv.sh` で shims を PATH に足す。版の再現性が要る操作は `mise exec`。shims を他の PATH より前に置けば cwd の版に従う（実測済み） |
| Q2 git が入力を求めない | AI CLI の起動側（`ocs` など）で、変数ごとに未設定のときだけ入れる。`GIT_TERMINAL_PROMPT=0` は入れる。`GCM_INTERACTIVE=never` は Git Credential Manager のある環境で候補。`GIT_SSH_COMMAND` は git 設定の SSH 指定と衝突しうるので一律には入れない。OpenCode は `guide-plugin` の `shell.create.before` で入れる（実測済み） |
| Q3 エディタ | 自動実行のときだけ `GIT_EDITOR=false`。既存の指定は残す。`GIT_SEQUENCE_EDITOR` は別判断。`EDITOR=true` は採らない |
| Q4 pip | OpenCode で `pip` / `pip3` / `python -m pip` を止めて uv へ誘導する。poetry / pipenv は止めない。`ocs` の中にも効かせる（安全境界ではなく uv を使う運用の取り決めのため）。既存の pip の deny は、静的 deny の呼び出しが plugin の `evaluate` に届かず説明が出ないため、`execute.before`（`home/dot_config/opencode/guide-plugin/index.js`）で先に止めて説明を返す（2026-10-03 実測）。既存の deny は外さない |
| Q5 危険な `rm` | OpenCode で、止めたい具体例（`.git` の直接削除、`~` や `/` の指定、作業ディレクトリ全体など）に限って止める。`ocs` の中にも効かせる。「うっかり防止であり完全な保護ではない」と明記する。[ADR-0012](../adr/0012-ocs-boundary-for-accidents.md)（`ocs` の中では `rm` などを確認しない）の部分変更として記録する |

## 未解決点

- Q2 / Q3: Claude Code（`settings.json` の `env`）と Copilot CLI で同じ変数を
  未設定時のみ入れられるか（未調査）
- Q4（解決済み・2026-10-03）: 通常版の `pip` / `pip3` は静的 deny で plugin の `evaluate` に届かず
  誘導文が出なかったが、静的 deny は変えずに plugin の `tool.execute.before` で止めて
  説明を返す形にした（[実測](../research/opencode/permission/early-guard.md)）
- 1d: Windows 実機での検証。**実機で回せなければ未検証と明記する**
  （WSL では対話テストが skip されるだけ）

## 評価基準

必須:

- 非対話の zsh / login bash で、alias・関数・出力が増えない（`test/test_shell_startup.py`）
- Q5 の規則が、通常の削除（例: `rm ./.tmp/x`、`rm -rf node_modules`）を止めない
- 呼び出し元が明示した環境変数を上書きしない
- ocs の外でも中でも pip 系を止め、誘導の説明が出る

望ましい:

- docs の記述が起動の実態と一致する（`bash -c` と `bash -lc` の違いなど）

## 候補比較

| 論点 | 候補 | 扱い | 理由 |
| --- | --- | --- | --- |
| Q1 | `mise activate` を非対話で使う | 見送り | 起動ファイルごとに activate を書き分ける必要があり、`bash -c` や zsh 以外の起動で揃わない（実測は 2a で確かめる） |
| Q1 | shims を PATH に足す | 採用 | 非対話でも効く。版は cwd に従うか実測する |
| Q2 | `GIT_SSH_COMMAND` を一律に入れる | 見送り | git 設定の SSH 指定と衝突しうる |
| Q3 | `EDITOR=true` | 見送り | 成功を偽装する |
| Q4 | 既存の pip の deny を外し誘導の規則だけにする | 見送り | 説明のために既存の拒否を弱めない |
| Q5 | `rm` を `gomi` に差し替える | 見送り | 標準コマンドの意味を変えない方針と合わない |
| Q5 | `rm` を全面的に確認へ | 見送り | ADR-0012（`ocs` 内では確認しない）の趣旨に反し、通常の削除まで止める |

## 仕様への変更案

| 変更対象 | 変更前 → 変更後 | 適用結果 |
| --- | --- | --- |
| `spec/structure.md` 「シェルの起動契約」 | 「全シェル」「全 bash」→ 起動形態ごとの正確な表記 | 作業 0 で適用 |
| `spec/structure.md` | 非対話でも mise の shims が PATH にあることを追記 | 2a で適用 |
| `spec/agent-command-policy.md` | pip 系と危険な `rm` の規則を追記 | 2b で適用 |
| ADR-0012 | 危険な `rm` の部分変更を記録 | [ADR-0013](../adr/0013-opencode-shell-guard-inside-ocs.md) として適用 |

## 重要な更新

- 2026-10-03 — 起票。方針 Q1〜Q5 を決定
- 2026-10-03 — 波 1〜3 を実装。残りは未解決点の 3 件（Claude / Copilot への環境変数、
  通常版 pip の誘導文、Windows 実機での検証）
- 2026-10-03 — 通常版 pip の誘導文を、静的 deny を残したまま plugin の前段停止で解決
