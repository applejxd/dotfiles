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
| 3 | 新しいマシンで `ExecutionPolicy` を手で設定する必要がある（README の手順のみ）。Terminal が既定のターミナルアプリでない | `ExecutionPolicy`（CurrentUser = RemoteSigned）と既定のターミナルアプリを自動設定する | 未着手 |
| 4 | 広告・推奨・タスクバーの天気（ウィジェット）が邪魔 | レジストリ / ポリシーで抑止する。Windows 11 では `HKCU` への直接書き込みが拒否される項目があるため、実機で通るか確かめる | 未着手 |
| 5 | scoop の `gow` が古い | `uutils-coreutils` などへの置き換えを検討する | 未着手 |
| 6 | sudo | scoop 版と Windows 標準の `sudo.exe` の使い分けを決める | 未着手 |
| 7 | 電源設定を適用後に読み取って確認できない | `powercfg /q` で検査する | 未着手 |
| 8 | クラシック右クリックメニューが現行ビルドで効くか不明 | 実機で確かめ、効かなければ削除する | 未着手 |
| 9 | WSL（仮想ディスクが C ドライブ以外にある）と WSL 3 | 保留。後でまとめて取り組む（下記） | 保留 |

状態: 未着手 / 進行中 / 完了 / 保留 / 見送り / 消滅

## 保留: WSL と WSL 3

- WSL の本体の仮想ディスク（VHDX）が C ドライブ以外にあるため、いまは触らない。後で WSL 3 の検討とあわせてまとめて取り組む
- この機には Linux ディストリビューションが入っておらず、`wsl --version` が `wsl --install` を促す状態（2026-10-11 実測）。`home/dot_wslconfig.tmpl`（`networkingMode=mirrored`、applejxd は `memory=32GB`）は配布されている
- 取り組むときに決めること: 仮想ディスクの置き場所の管理（`wsl --import` / `--move`）、導入と確認の手順、`.wslconfig` の最低版、WSL 3 の扱い

## 未解決点

- 段 4 のレジストリが、ビルド 26300 で `HKCU` から書き込めるか（User Choice Protection Driver が、一部の Explorer 設定の書き込みを拒否する）
- 段 6 の `sudo` の導入形式の比較（Windows 標準、scoop、winget）
