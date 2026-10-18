# 過去の実装に依存する処理の棚卸し

- **観測日**: 2026-10-18
- **対象**: このリポジトリの `home/.chezmoiscripts/`、`home/.chezmoiremove`、`home/.chezmoitemplates/`、
  `scripts/`、`home/dot_config/`、`home/dot_zshrc*`、Windows のスクリプト
- **一次情報**: リポジトリの読み取り（3 領域を並列に調査）と、WSL2（Ubuntu）・同じ機の Windows 側の
  実在確認。`git log -S` で引けた由来のコミットは下表に書いた（引けなかったものは「不明」）

方針は「**過去の実装に依存する形をやめたい**」。ただし、削除してよいかは
**他のマシンに適用済みか**で決まる。会社の PC など、台数も適用状況も把握できないマシンが
多いので、**他のマシンの状態に依存しない削除だけ**を行い、残りはここに記録する。

## 結論

- 削除したのは、コメントアウトされた Edge の導入ブロック（`111_microsoft`）だけ
  （どのマシンの状態にも依存しない死にコード）
- ほかの掃除・移行コードは**残す**。理由は、旧状態が残っているマシンがあり得て、
  消すと次の不具合が残るため（例: 旧 mise の shim が公式の AI CLI を隠す、
  ohmyzsh の壊れた補完で `_z` が壊れる）
- 再検討の条件は下表の「消せる条件」。全マシンで適用済みと言えるようになったら外す

## 分類の基準

| 区分 | 意味 | 扱い |
| --- | --- | --- |
| 移行・掃除 | 過去のこのリポジトリが作ったものを、今のバージョンが消す・置き換える | 他のマシンの適用状況次第。条件が揃うまで残す |
| 外部の残骸への対処 | このリポジトリ由来ではない（Docker Desktop、Orca、zinit など） | 今の構成でも起こり得るので残す |
| 個人環境の古い互換 | 過去の個人環境の導入物に備える `-e` ガードなど | 使っているかの確認が要る |

## 移行・掃除（消せる条件が揃うまで残す）

| 項目 | 場所 | 由来 | 今の構成で新規に発生するか | この機（WSL）の状態 | 消せる条件 |
| --- | --- | --- | --- | --- | --- |
| 移行の削除一覧 18 件 | `home/.chezmoiremove` | 2026-08〜10 の改名・廃止（CHG-0014 / CHG-0023、ADR-0017 など。各項目のコメントに日付） | しない | 対象はすべて無い | 全マシンで `apply` 済み。`.claude/skills/checkpoint` は残すと OpenCode が古い方を読むので最後に外す |
| mise の旧 shim・installs の削除 | `home/.chezmoitemplates/agent-cli-install.sh.tmpl` 23〜41 行 | AI CLI を mise から公式インストーラーへ移した変更（コミットは不明） | しない（現行の mise 宣言に無い）。手で `mise use -g` すれば起こる | 無い | 全マシンで `apply` 済み。名前固定の `rm -rf installs/<名前>` が、手動で入れたものも消す点に注意 |
| ohmyzsh 補完の symlink と `.zcompdump` の削除 | `home/.chezmoiscripts/000_unix/run_onchange_after_020_zinit_completions.sh` | `nocompletions` の追加（`2fccf27`、2026-09-05） | しない | 壊れた symlink は 0 件 | 全マシンで `apply` 済み。`run_onchange_` なので消しても他のマシンへの影響は「旧状態が残る」だけ |
| `_z` の再 source | `home/dot_zshrc.tmpl` の `zshrc-reload-z` | `efcf925`（2026-09-05） | 再発しにくいが、他の経路は未確認 | `~/.zinit/completions/_z` は無い | 外して `z` が動くことを実機で確認できたとき。毎回の zsh 起動で `z.sh` を再 source するので起動時間にも効く |
| 旧 npm 版 pi の撤去 | `home/.chezmoiscripts/300_windows/310_packages/run_onchange_after_314_agent_cli.ps1.tmpl` 88〜96 行 | pi を npm global から mise（aqua）へ移した変更（コミットは不明） | しない（手動の `npm i -g` を除く） | **Windows 側に旧 npm 版が実在する**（`AppData\Roaming\npm\node_modules\@earendil-works`）。まだ撤去が走っていない | 全 Windows 機で撤去済み |
| Copilot の skills の symlink 撤去 | `home/.chezmoiscripts/300_windows/run_after_342_copilot_skills.ps1.tmpl` | 過去に symlink で配備した可能性（推測。コミットは不明） | ほぼしない（利用者が手動で作れば起こる） | **Windows 側の `.copilot/skills` が symlink で実在する** | 全 Windows 機で Junction へ移行済み |
| agents の `__pycache__` 削除 | `home/.chezmoiscripts/300_windows/run_once_after_344_cleanup_agents_pycache.ps1` | 古い `.pyc` による import の失敗（`docs/spec/agent-permissions.md`） | `__pycache__` 自体は今後も作られる。壊れ方の再発は根拠が足りない | Windows 側に無い | `run_once_` なので再発の防止にはならない。削除してよい可能性が高いが根拠は弱い |
| Raspberry Pi の旧 GUI の撤去 | `scripts/raspi/uninstall_gui.sh`（手動） | Pi 判定が効く前の旧 `apply`（`3f2e4b1`、2026-09-26） | しない | 該当なし（x86_64） | Pi の全台で実行済み |
| 壊れた systemd ユニットの再作成 | `scripts/ubuntu/docker.sh` 151〜154 行 | `9e3b908`（2026-10-18） | 今の手順では新規には起きない | ユニットは存在する | 入れたばかり。別の日に再検討 |

## 外部の残骸への対処（残す）

今の構成でも起こり得るので残す。

| 項目 | 場所 | 補足 |
| --- | --- | --- |
| `vscode.list` と `vscode.sources` の重複解消 | `121_ubuntu`、`111_microsoft` | `111` が今も `.list` を作る分岐を持つ。この機は `vscode.list` だけで重複なし |
| 旧ロケールの空フォルダの `rmdir` | `121_ubuntu` | OS が今も作る。許可リストで `rmdir` なので安全 |
| Docker Desktop の残骸（壊れた symlink、`credsStore`）と rootful 停止 | `scripts/ubuntu/docker.sh` | 壊れた symlink の削除は `contexts` に限定すると、`~/.docker` 直下の他の壊れリンクを巻き込まない（未実施） |
| zinit 補完の壊れた symlink の掃除 | `mise.toml` の `dotfiles-update` | upstream プラグインの変更による外部要因 |
| `OPENCODE_CONFIG` の環境変数の補完 | `home/dot_config/shell/shellenv.sh.tmpl` | Orca を使う限り起こる |
| Windows Terminal の旧形式の互換、`cache.ps1` の一時ファイル掃除、`git-config-env.ps1`、GPU 設定のディレクトリ作り直し、フォントの一時物 | `300_windows/`、`home/dot_config/powershell/` | 外部の形式への対応、または自分が作る一時物の後片付け |

## 個人環境の古い互換（要確認）

| 項目 | 場所 | 状況 |
| --- | --- | --- |
| `openssl@1.1`、wxMaxima | `home/dot_config/shell/osxenv.sh` | `-e` ガード付きで害は無い。macOS は「たまに使う」ので、使っているかを確認してから判断 |
| Java 11 | `home/dot_config/shell/wslenv.sh` | 同上 |
| fish の設定全体 | `home/dot_config/fish/config.fish` | **fish は使っていない**。MAMP、fink、FDK、YaTeX など古い macOS 向けが中心。削除候補 |
| `{"key":…, "value":[…]}` と素の配列の両方を受ける | `400_unix/run_onchange_after_420 / 430` | 旧形式が実在した裏付けが無い、予防的な処理 |

## 手法の注意

- 由来のコミットは `git log --format='%h %ad %s' -S'<特徴的な文字列>' -- <path>` で引いた。
  引けなかったものは「不明」とした
- 「この機の状態」は 2026-10-18 時点の WSL2 と、同じ機の Windows 側（`/mnt/c/Users/applejxd`）の
  実在確認。ほかのマシン（会社の PC、macOS、Raspberry Pi）は未確認
- 「今の構成で新規に発生するか」は、今のスクリプトが同じ状態を作るか、外部ツールが今も作るかで判断した。
  推測は「推測」と書いた

## 未検証

- 会社の PC・macOS・Raspberry Pi・別の Windows 機の状態
- `zshrc-reload-z` を外したときの `z` の挙動
