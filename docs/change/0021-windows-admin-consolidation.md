# CHG-0021: Windows の chezmoi セットアップを整え、管理者権限の作業を 1 回の UAC に集約する

- **状態**: In progress
- **更新日**: 2026-10-10
- **基準**: Windows 11 Pro 実機（applejxd）、chezmoi v2.73.0、`bw` 2026.9.1、コミット a21d1aa

## 目的と非目的

**目的**: Windows 11 のクリーンインストールで見つかった問題を直し、次を満たす。

- 管理者権限が要る作業を、chezmoi スクリプト自身が出す UAC 1 回に集約する。通常ユーザーで `chezmoi apply` を実行する設計は保つ
- 昇格先が別アカウントでも、ユーザー設定を別アカウントのホームに書き込まない
- 初回導入・部分的な失敗からの再実行・導入済みの 3 つの場合で冪等に終わる
- `applejxd` の機械では、RDP・OpenSSH Server・SSH 公開鍵の登録まで整える

**非目的**: `310_winget` に残る個別パッケージのインストーラーが自分で出す UAC の制御（user scope で入る前提にした。
[仕様](../spec/structure.md#winget-パッケージの-user--machine-の振り分け)）。管理者グループの利用者向けの `administrators_authorized_keys`。

## 実施計画

| 段 | 解決したいこと | 内容 | 状態 |
| --- | --- | --- | --- |
| 1 | Chocolatey が remote の `install.ps1` を昇格して実行し、拡張も昇格したユーザーで取得していた | winget 経由で入れ、本体・パッケージを個別に判定。Keypirinha 拡張は通常権限の別スクリプトへ分離 | 完了 |
| 2 | UAC が 312・320・340・310（WinSCP）で別々に出た | `309_admin` に集約。不足があるときだけ昇格し、SHA-256 照合・許可リスト・終了コードとログの検証・再判定をする | 完了（実機の UAC は未検証） |
| 3 | どの winget パッケージが UAC を出すか分からなかった | `winget show --scope` の user と machine で棚卸しし、machine 版しかない 11 件と Python Launcher を 309 へ移した | 完了 |
| 4 | applejxd の機械で RDP・OpenSSH Server が無効 | 309 に追加。ファイアウォールは Domain / Private に限る | 完了（実機の UAC は未検証） |
| 5 | 周辺の不具合 | OpenCode の `--allow-scripts`、Explorer のサイドバー、oh-my-posh（MSIX 版）のテーマ、Bitwarden の SSH 鍵から `authorized_keys` への追加 | 完了 |
| 6 | 実機で通っていない | クリーンな Windows で `chezmoi apply` を通し、UAC・導入先・再実行を確かめる | 未着手 |

状態: 未着手 / 進行中 / 完了 / 保留 / 見送り / 消滅

## 現在地

- 2〜5 は実装・docs・試験まで済み。UAC を実際に承認した通し実行（段 6）は未実施。ダミーの `bw`・昇格なしの子の起動・描画後の構文検証までで確かめている
- 現環境は導入済みなので、判定は RDP・OpenSSH Server を除いて「nothing to do」になる。初回導入と部分失敗からの再実行は実機で確かめていない
- 仕様の正本は [管理者権限の集約](../spec/structure.md#管理者権限の集約) と
  [SSH 公開鍵の authorized_keys への追加](../spec/security.md#ssh-公開鍵の-authorized_keys-への追加)

## 未解決点

| 未解決点 | 再開条件 |
| --- | --- |
| UAC 承認を含む通し実行（同一アカウント・別管理者アカウント・クリーン環境）が未検証 | 段 6。クリーンな Windows 実機を用意できたとき |
| Python Launcher（`launcher.msi`、scope 未宣言）が既定で全ユーザーに入り UAC が出るかが未確認 | 段 6 で導入後に UAC の有無と導入先を見る。出なければ 310 へ戻す |
| Orca（NSIS、scope 未宣言）が UAC を出すかが未確認 | 段 6 で UAC が出たら 309 へ移す |
| 管理者グループの利用者は既定の `sshd_config` が `%ProgramData%\ssh\administrators_authorized_keys` を使うため、`authorized_keys` への追加だけでは鍵認証にならない | OpenSSH Server を有効にしたあと、applejxd で鍵認証を試して失敗したとき。管理者権限と ACL が要るので 309 の対象にする |
| OpenSSH Server のパスワード認証は既定のまま | 利用者が `PasswordAuthentication no` を求めたとき |
| Bitwarden の SSH 鍵項目の JSON が `sshKey.publicKey` を持つか。`bw` 2026.9.1 のバイナリの定義でだけ確認した | 利用者が実際の項目で試したとき |
| 昇格先アカウントで `winget` が使えない場合は導入できず、明示エラーで止まる（代替の導入経路は持たない） | 別アカウントで昇格する運用が現実になったとき |
| `test_windows_assets.py` の 3 件（keyhac の検査・scoop の検査・scoop の BOM）が失敗している。変更前から | 利用者が直すと決めたとき。keyhac と scoop は別途修正済みと聞いており、試験側の更新漏れの可能性がある |
| `pre-commit`（依存の `keypirinha-stub` が取得できない）と `lint_templates.py`（Python が見つからない）を、この環境で実行できなかった | 実行できる環境で回す |

## 次の調査・実験

- クリーンな Windows 11 で `chezmoi apply` を通し、UAC が 1 回だけ出ること・導入先・2 回目が「nothing to do」になることを確かめる
- 別管理者アカウントで昇格し、309 が読めること・元ユーザーのホームに 309 由来のファイルが増えないことを確かめる
- Python Launcher と Orca の UAC の有無を、導入のときに記録する

## 評価基準

- 必須: UAC が不足のあるときだけ 1 回出る。導入済みなら出ない。失敗した回は成功として記録されず、直して `apply` すると再実行される
- 必須: 昇格子は許可リスト外のキーを拒否し、実行前の 309 の差し替えを検出する。ユーザープロファイルに書かない
- 必須: RDP と sshd のファイアウォールは Public を開かない
- 望ましい: `310_winget` の個別パッケージが UAC を出さない

## 候補比較

| 候補 | 支持する根拠 | 不利な点・反証 | 未検証点 | 扱い | 次の確認 |
| --- | --- | --- | --- | --- | --- |
| 各スクリプトが自前で昇格する（従来） | 追加の仕組みが要らない | UAC が複数回出る。昇格先の扱いが各所で違う | — | 見送り | — |
| `309_admin` に集約し、不足のときだけ 1 回昇格する | UAC が 1 回。判定を通常権限側に置ける。sol のレビュー 8 回で BLOCKER・MAJOR が 0 になった | 昇格前の temp の 309 の改ざんは防げない（信頼の起点が無い。chezmoi 公式の昇格パターンと同じ前提） | UAC を通した実機の動作 | 採用 | 段 6 |
| 常駐の昇格ヘルパーにタスクを送る | 最初の 1 回だけで済む | 通常権限のプロセスが管理者権限で任意のコマンドを実行できる抜け穴になる | — | 見送り | — |
| winget の全パッケージを 309 に移す | UAC が確実に 1 回 | user 向けのアプリを管理者で入れる。別アカウントで昇格するとそのホームへ入る。Microsoft Store 版は昇格して入れられない | — | 見送り | — |
| Python Launcher を 309 へ移す | `launcher.msi` は scope 未宣言の MSI | 既定が全ユーザーかは断定できない | 導入時の UAC の有無 | 検証中 | 段 6 |
| Orca を 309 へ移す | — | NSIS は既定が per-user のはず | UAC の有無 | 保留（310 に残す） | 段 6 |

扱い: 未評価 / 検証中 / 有望 / 採用 / 保留 / 見送り

## 仕様への変更案

| 変更対象 | 変更前 → 変更後 | 理由・証拠 | 適用結果 |
| --- | --- | --- | --- |
| `structure.md`「管理者権限の集約」 | 記述なし → 309 の流れ・昇格の仕組み・保証しないこと・個別の判断 | 段 2〜4 | 済 |
| `structure.md`「winget パッケージの user / machine の振り分け」 | 記述なし → 実測した scope の一覧と扱い | 段 3 | 済 |
| `security.md`「SSH 公開鍵の authorized_keys への追加」 | 記述なし → 条件と動作の表 | 段 5 | 済 |
| `pi-harness.md`「Windows の子エージェント」 | 記述なし → 読み取り専用の子エージェント | [CHG-0020](0020-pi-migration.md) | 済 |

## 実装・検証

- 実装: `300_windows/310_packages/run_once_before_309_admin.ps1.tmpl`（集約）、`run_once_after_315_keypirinha_extensions.ps1`
  （通常権限）、`300_windows/run_after_348_authorized_keys.ps1.tmpl`、`400_unix/run_after_440_authorized_keys.sh.tmpl`
- 昇格の経路は、スペース・`'`・日本語を含むパスで、昇格なしの子の起動を通した（ハッシュ照合・デコード・引数・ログ・終了コード・許可リスト外の拒否）
- 試験: `test/test_windows_assets.py`（309 の静的検査・振り分け）、`test/test_authorized_keys.py`、
  `test/agents/test_pi_subagents.py`。`test_windows_assets.py` は 3 件失敗（変更前から）
- 実環境の判定: 導入済みのため RDP と OpenSSH Server 以外は「nothing to do」。非管理者で RDP の変更を試すとアクセス拒否で失敗し、何も変わらないことを確かめた

## 重要な更新

- **2026-10-10**: 管理者権限の作業を `309_admin` に集約した（c950274・f517ee1・5fee8ef・aa954dc・a21d1aa）。
  winget の scope を実測して、machine 版しかない 11 件を移した。RDP と OpenSSH Server を applejxd の機械で有効にする処理を足した
- **2026-10-10**: oh-my-posh を winget の MSIX 版（`ohmyposh.cli`）で入れると `POSH_THEMES_PATH` が設定されず、プロファイルがテーマを見つけないまま
  既定のプロンプトで起動していた。`pure.omp.json` の複製を配って直した
- **2026-10-10**: 起票。Windows 11 のクリーンインストールで見つかった問題（Chocolatey の構成、OpenCode の npm 警告）から始まった

## 終了結果

<!-- Done / Abandoned にするときに書く -->
