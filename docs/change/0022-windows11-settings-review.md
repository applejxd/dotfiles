# CHG-0022: Windows 11 の設定を見直し、古い設定の修正と体験の改善を入れる

- **状態**: In progress
- **更新日**: 2026-10-12
- **基準**: Windows 11 Pro 実機（ビルド 26300、applejxd）、コミット 1b6a1c9。見直しは sol（`github-copilot/gpt-6-sol`）との相談と実機の実測による

## 目的と非目的

**目的**: 古い仕様に基づく設定や、効いていない設定を直し、体験を良くする設定を足す。

**非目的**: WSL の導入・移行（下の保留）。Defender の除外、RDP・OpenSSH Server の汎用機への展開、Dev Drive、OneDrive、Windows Update の固定（好みと運用で決める）。

## 実施計画

| 段 | 解決したいこと | 内容 | 状態 |
| --- | --- | --- | --- |
| 1 | 7-Zip の関連付けが効かない（`.zip` の `UserChoice` が `CompressedFolder` のまま。実機で確認） | `UserChoice` は直接書けないため、ProgID・`OpenWithProgids`・`Capabilities`・`RegisteredApplications` を登録し、「既定のアプリ」に「7-Zip (extract)」が出る形にした（[仕様](../spec/structure.md#7-zip-の関連付け)）。**設定の一覧に出ることを目視で確認した（2026-10-12）** | 完了 |
| 2 | `341` が JSONC に弱く、`profiles.defaults` 全体を置き換える | LANG2 の `modify_` に統合し（JSONC のまま、管理するキーだけ更新）、341 と `config/windows/terminal.json` を廃止した | 完了 |
| 3 | 新しいマシンで `ExecutionPolicy` を手で設定する必要がある（README の手順のみ）。Terminal が既定のターミナルアプリでない | `ExecutionPolicy`（5.1、CurrentUser = RemoteSigned）と既定のターミナルアプリを `323_shell_defaults` で自動設定する | 完了 |
| 4 | 広告・推奨・タスクバーの天気（ウィジェット）が邪魔 | 広告・推奨は `324_suggestions`（毎回）で止めた。ウィジェットはレジストリの直接書き込みが全方式で拒否される（保護された値）。ローカル GPO 経由なら止められ、この機は適用済みだが、自動化は見送り（手動の手順を docs に記録） | 完了（ウィジェットは見送り） |
| 5 | scoop の `gow` が古い | `gow` は 0.8.0 のまま更新されない（マニフェストに自動更新が無い）。**置き換え・削除は保留。** 普通の PowerShell（PATH は Machine + User）で、`grep`・`egrep`・`sed`・`awk`・`less`・`which`・`head`・`tail`・`xargs`・`touch`・`du`・`df`・`vim`・`nano`・`env`・`id`・`uname`・`seq`・`tr`・`cut`・`wc`・`gzip`・`zip`・`unrar` などは**`gow` が唯一の提供元**（`find`・`sort`・`tar`・`curl`・`wget`・`cat`・`ls` などは Windows・PowerShell の標準が先で、影響しない。`gow` の `find` は `gfind`）。PowerShell の履歴は、起動ディスクの交換と OS の再インストール（2026-10）で短く（131 行）、**使用の実績の根拠にならない**。数週間使ってから履歴を集計し直して決める。置き換えるなら `uutils-coreutils`（0.12.0、自動更新あり）に加えて、grep / sed / gawk 等を個別に入れる必要がある | 保留 |
| 6 | sudo | scoop の `sudo`（2020 年の近似実装、UAC の窓が出る）は導入をやめた（`311_scoop` から削除。既に入っているものは消さない）。Windows 11 標準の `sudo`（`forceNewWindow`）を、`309_admin` の `Sudo` キーで有効にする（`applejxd` のみ。UAC の承認を通した有効化を実機で確認済み、2026-10-12） | 完了 |
| 7 | 電源設定を適用後に読み取って確認できない | `331_power` が、設定のあとに `powercfg /q` で読み取って確かめ、違えば警告する（`apply` は止めない） | 完了 |
| 8 | クラシック右クリックメニューが現行ビルドで効くか不明 | ビルド 26300 で、最初から旧来のメニューが出ることを利用者が目視で確認した（2026-10-12）。設定（`HKCU\Software\Classes\CLSID\{86ca1aa0-…}\InprocServer32` の既定値が空）は、そのまま残す | 完了 |
| 9 | WSL（仮想ディスクが C ドライブ以外にある）と WSL 3 | WSL 本体だけを `309_admin` で導入する（`WslPlatform`。applejxd の全 PC、ディストロなし）。ディストロの導入と置き場所の方針は保留 | 一部完了（本体）・ディストロは保留 |

状態: 未着手 / 進行中 / 完了 / 保留 / 見送り / 消滅

## 保留: WSL と WSL 3

- **WSL 本体（ディストロなし）は 309 で導入するようにした**（2026-10-12。[仕様](../spec/structure.md#wsl-本体wslplatform)）。**ディストロの導入と、仮想ディスク（VHDX）が C ドライブ以外にあることの扱いは、いまは触らない**
- この機には Linux ディストリビューションが入っておらず、`wsl --version` が `wsl --install` を促す状態（2026-10-11 実測）。`home/dot_wslconfig.tmpl`（`networkingMode=mirrored`、applejxd のみ `memory` を指定、値はテンプレートが正本）は配布されている
- **「隔離 GPU サンドボックス」用の専用ディストロだけは、手動実行のスクリプトで作れるようにした**（2026-10-17。[仕様](../spec/sandbox/wsl-sandbox.md)。通しの実行は未検証）。既定のディストロと置き場所の方針は引き続き保留
- 取り組むときに決めること: 仮想ディスクの置き場所の管理（`wsl --import` / `--move`）、導入と確認の手順、`.wslconfig` の最低版、WSL 3 の扱い

## 現在地

- 段 1・2・3・4・6・7・8 は完了。段 4 のウィジェットは自動化を見送った（手動の手順を docs に記録）
- 段 1（7-Zip）は、設定 → アプリ → 既定のアプリに「7-Zip (extract)」が出ることを目視で確認した
- 段 9 は、WSL 本体の導入だけ完了（再起動後の `wslc` の確認が残る）。ディストロは保留。段 5（`gow`）も保留。`gow` は数週間使ってから履歴を集計し直して決める。WSL は仮想ディスクの置き場所の整理と WSL 3 の検討のときにまとめて取り組む
- この案件を閉じる条件: 保留 2 件（`gow`、WSL・WSL 3）の決着

## 未解決点

- 段 4: 新しい機でウィジェットを止める手間が増えたら、LGPO を使った自動化（`structure.md` の設計）を再検討する
- 段 5: 数週間使ったあとの履歴の集計と、`gow` の扱いの決定
