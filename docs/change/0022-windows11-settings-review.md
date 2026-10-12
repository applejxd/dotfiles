# CHG-0022: Windows 11 の設定を見直し、古い設定の修正と体験の改善を入れる

- **状態**: In progress
- **更新日**: 2026-10-11
- **基準**: Windows 11 Pro 実機（ビルド 26300、applejxd）、コミット 1b6a1c9。見直しは sol（`github-copilot/gpt-6-sol`）との相談と実機の実測による

## 目的と非目的

**目的**: 古い仕様に基づく設定や、効いていない設定を直し、体験を良くする設定を足す。

**非目的**: WSL の導入・移行（下の保留）。Defender の除外、RDP・OpenSSH Server の汎用機への展開、Dev Drive、OneDrive、Windows Update の固定（好みと運用で決める）。

## 実施計画

| 段 | 解決したいこと | 内容 | 状態 |
| --- | --- | --- | --- |
| 1 | 7-Zip の関連付けが効かない（`.zip` の `UserChoice` が `CompressedFolder` のまま。実機で確認） | 既定アプリの一覧に出る形（ProgID + `Capabilities`）で登録し、設定で一度選んでもらう。実機の設定画面での表示が未確認 | 進行中 |
| 2 | `341` が JSONC に弱く、`profiles.defaults` 全体を置き換える | LANG2 の `modify_` に統合し（JSONC のまま、管理するキーだけ更新）、341 と `config/windows/terminal.json` を廃止した | 完了 |
| 3 | 新しいマシンで `ExecutionPolicy` を手で設定する必要がある（README の手順のみ）。Terminal が既定のターミナルアプリでない | `ExecutionPolicy`（5.1、CurrentUser = RemoteSigned）と既定のターミナルアプリを `323_shell_defaults` で自動設定する | 完了 |
| 4 | 広告・推奨・タスクバーの天気（ウィジェット）が邪魔 | 広告・推奨は `324_suggestions`（毎回）で止めた。ウィジェットはレジストリの直接書き込みが全方式で拒否される（保護された値）。ローカル GPO 経由なら止められ、この機は適用済みだが、自動化は見送り（手動の手順を docs に記録） | 完了（ウィジェットは見送り） |
| 5 | scoop の `gow` が古い | `gow` は 0.8.0 のまま更新されない（マニフェストに自動更新が無い）。113 個のコマンドを持ち、このリポジトリは使っていないが、対話で使う grep / sed / awk / less / tar / curl / wget / which などが入る。置き換えるなら `uutils-coreutils`（0.12.0、自動更新あり）に加えて、grep / sed / gawk 等を個別に入れる必要がある。**どのコマンドを使っているか分からないので保留** | 保留 |
| 6 | sudo | scoop の `sudo`（2020 年の近似実装、UAC の窓が出る）は導入をやめた（`311_scoop` から削除。既に入っているものは消さない）。Windows 11 標準の `sudo`（`forceNewWindow`）を、`309_admin` の `Sudo` キーで有効にする（`applejxd` のみ。UAC の承認を通した確認が未了） | 完了（実機確認待ち） |
| 7 | 電源設定を適用後に読み取って確認できない | `powercfg /q` で検査する | 未着手 |
| 8 | クラシック右クリックメニューが現行ビルドで効くか不明 | 実機で確かめ、効かなければ削除する | 未着手 |
| 9 | WSL（仮想ディスクが C ドライブ以外にある）と WSL 3 | 保留。後でまとめて取り組む（下記） | 保留 |

状態: 未着手 / 進行中 / 完了 / 保留 / 見送り / 消滅

## 保留: WSL と WSL 3

- WSL の本体の仮想ディスク（VHDX）が C ドライブ以外にあるため、いまは触らない。後で WSL 3 の検討とあわせてまとめて取り組む
- この機には Linux ディストリビューションが入っておらず、`wsl --version` が `wsl --install` を促す状態（2026-10-11 実測）。`home/dot_wslconfig.tmpl`（`networkingMode=mirrored`、applejxd は `memory=32GB`）は配布されている
- 取り組むときに決めること: 仮想ディスクの置き場所の管理（`wsl --import` / `--move`）、導入と確認の手順、`.wslconfig` の最低版、WSL 3 の扱い

## 未解決点

- 段 4: 新しい機でウィジェットを止める手間が増えたら、LGPO を使った自動化（`structure.md` の設計）を再検討する
