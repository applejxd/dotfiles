# トラブルシューティング: 導入と適用

`chezmoi apply` / `chezmoi update` の途中で起きる障害と、Python・Bitwarden・mise・
APT・AI CLI の導入で起きる障害をまとめる。症状からの索引は
[トラブルシューティング](troubleshooting.md)。

各項目は「対象 → 症状 → 確認 → 原因 → 対処 → 成功の確認」の順に書く。

## スクリプトを走らせ直す

**対象**: 全 OS。`home/.chezmoiscripts/` の `run_once_` / `run_onchange_`。

**症状**: 前提（VS Code・ネットワーク・Bitwarden など）を揃えてから `chezmoi apply`
しても、スクリプトが走らない。

**確認**: 次の apply で走るスクリプトは `chezmoi status` に `R` として出る。
出ていなければ走らない。

```bash
chezmoi status --include=scripts
```

**原因**: chezmoi は `run_once_` / `run_onchange_` を**成功したときだけ**記録し、
記録と内容が一致する間は走らせない
（[Use scripts to perform actions](https://www.chezmoi.io/user-guide/use-scripts-to-perform-actions/)）。

- 非ゼロで終わったスクリプトは記録されない。**次の apply でもう一度走る**
- 警告だけ出して 0 で終わったスクリプトは成功として記録される。**内容が変わるまで
  走らない**。外部の一時的な不調で apply を止めないため、次は 0 で終わる
  - `100_linux/110_native/112_vscode_extensions`（`code` が無いとき）
  - `100_linux/125_mise`（`mise install` の一部が失敗したとき。
    [ツール 1 個の失敗で apply を止めない](structure.md#ツール-1-個の失敗で-apply-を止めない)）

`100_linux/126_agent_cli` / `200_mac/226_agent_cli`（AI CLI の導入）と
`400_unix/420_omp_skills` / `400_unix/430_omp_claude_assets`（omp の設定の取得・解析に
失敗したとき）は例外で、失敗したら `~/.local/share/dotfiles/retry/` の下の印を書き直す
（順に `agent-cli-failed` / `omp-skills-failed` / `omp-claude-assets-failed`）。
スクリプトにはこの印の**更新時刻だけ**を埋め込むので、次の apply で中身が変わって走り直す。
成功した回は印に触れないので、その後は走り直さない。仕組みは
`home/.chezmoitemplates/retry-marker.sh.tmpl` にある。

印は apply（ホスト）が書くので、置き場はどのエージェントの sandbox からも書けない
場所にする。`~/.local/state` は Claude Code / Copilot CLI の sandbox から書ける
（[agent-sandbox.md](agent-sandbox.md)）ので使わない。書けると、印を `~/.bashrc` への
symlink に差し替えてホストの apply に中身を書き潰させられる。
同じ理由で、印は同じディレクトリの一時ファイルから `mv` で差し替え、既存の symlink を
追わない。中身を埋め込まないのは、書き換えられたときにスクリプトへコードが入らないため。
OS の境界を持たない実行（ocs を通さない OpenCode、omp）からは、この置き場でも守れない。

> [!NOTE]
> 以前の置き場 `~/.local/state/dotfiles/agent-cli-failed` はもう読まない。残っていても
> 害は無く、消してよい。

**対処**: 1 本だけ走らせ直すなら、テンプレートを描画して直接実行する。
chezmoi の記録には触らない。

```bash
src="$(chezmoi source-path)"
chezmoi execute-template < "$src/.chezmoiscripts/100_linux/run_onchange_after_126_agent_cli.sh.tmpl" | bash
```

`run_onchange_` なら、そのスクリプトの記録だけを消して次の apply に走らせることも
できる。記録は `entryState` バケットにスクリプトの target 名をキーとして入っている
（[Architecture](https://www.chezmoi.io/developer-guide/architecture/)）。
キーの正確な形は `get-bucket` の出力で確かめてから消す。

```bash
chezmoi state get-bucket --bucket=entryState | grep agent_cli
chezmoi state delete --bucket=entryState --key='<上で確かめたキー>'
chezmoi apply
```

> [!WARNING]
> バケットごと消すと、再実行の範囲が 1 本では済まない。
>
> - `chezmoi state delete-bucket --bucket=scriptState` は**すべての `run_once_`** の
>   記録を消す。次の apply でその OS の `run_once_` が全部走り直す（Ubuntu なら
>   `121_ubuntu` の `apt-get upgrade` と ClamAV の `freshclam`、Windows なら winget /
>   scoop / choco の一括導入とレジストリ設定）
> - `chezmoi state delete-bucket --bucket=entryState` は**すべての `run_onchange_`** の
>   記録を消す。同じバケットには管理ファイルの書き込み記録も入っている
>
> どちらも公式に案内された操作だが、1 本だけ直したいときは上の方法を使う。

**成功の確認**: スクリプトの末尾の `✅ 完了：...` が出る。
`run_onchange_` の記録を消した場合は、消す前に `chezmoi status --include=scripts` に
出なかったスクリプトが `R` で出る。

## sudo のパスワードで止まる

**対象**: macOS の `200_mac/205_homebrew` / `210_osx` / `250_defaults` と、Linux の
`sudo -v` を使うスクリプト。

**症状**: `chezmoi apply` がパスワードの入力待ちで止まる、または認証に失敗して
スクリプトが止まる。

**原因**: パスワードは `sudo -v` が端末で尋ねる。端末につながっていない実行や、
入力を誤ったときに止まる。環境変数では渡せない
（[sudo パスワード](development.md#sudo-パスワード)）。

**対処**: 対話できる端末で `chezmoi apply` を実行し、尋ねられたら入力する。
失敗したスクリプトは記録されないので、次の apply でもう一度走る。

**成功の確認**: 同じ apply で macOS / Linux のスクリプトが最後まで進み、
`chezmoi status --include=scripts` に残らない。

## Unix で tomllib が無いと言われて apply が止まる

**対象**: Linux / WSL / macOS。`scripts/agents/generate.py` を呼ぶ modify script
（`.claude/settings.json` など）。

**症状**: apply が次で止まる。

```text
ModuleNotFoundError: No module named 'tomllib'
chezmoi: .claude/settings.json: exit status 1
```

`generate.py` の案内（「agent 設定の生成には Python 3.11 以上が必要です」）が出ることもある。

**確認**: 3.11 以上の Python がどこかにあるかを見る。

```bash
python3 --version
ls ~/.local/share/mise/installs/python/*/bin/python3.* 2>/dev/null
ls ~/.local/share/uv/python/*/bin/python3.* 2>/dev/null
```

**原因**: `tomllib` は Python 3.11 以上の標準ライブラリ。chezmoi は project の uv 環境では
なく `[interpreters.py]` の Python で modify script を動かす。Ubuntu 22.04 の既定は 3.10、
20.04 は 3.8 なので該当する（24.04 は 3.12）。

通常は次の 2 段で防いでおり、**どこかに 3.11 以上が 1 つあれば `chezmoi apply` だけで通る**
（[ADR-0003](../adr/0003-require-python-311-for-agent-configuration.md)）。

1. `000_unix/run_before_005_python.sh.tmpl` がファイル適用より前に走り、3.11 以上が
   無ければ uv をユーザ領域へ入れて `uv python install 3.13` する（sudo 不要）。
   見つけた Python を `~/.local/bin/chezmoi-python3` へ張る。`[interpreters.py]` は
   init 時に PATH 上で 3.11 以上が見つからなければこの shim を指す
2. modify script のラッパー（`home/.chezmoitemplates/modify_json.py.tmpl`）が実行時に
   探し直す。順序は、自分自身 → PATH の `python3.14` … `python3.11` →
   PATH の `python3` / `python`（`tomllib` を試す）→ mise / uv の導入先のうち最新

このエラーが出るのは、どこにも無く、1 の自動取得も失敗した場合（オフラインなど）。
その場合は先に 005 の警告が出ている。

```text
⚠️  uv を導入できませんでした。3.11 以上の Python を手動で入れてください。
```

**対処**: sudo なしで入れる。`tomli` は入れない（ADR-0003）。

```bash
uv python install 3.13     # uv があるなら
mise use -g python@3.13    # mise があるなら
chezmoi apply
```

どちらも使えないときの最後の手段が system への導入。

```bash
sudo apt-get install -y python3.12
chezmoi apply
```

まっさらな機械で `chezmoi apply` より先に `chezmoi diff` を回すと、次のエラーになる
ことがある。diff はスクリプトを走らせないので、005 がまだ shim を張っていない。
`chezmoi apply` を 1 回回せば解消する。

```text
chezmoi: .claude/settings.json: fork/exec /home/<user>/.local/bin/chezmoi-python3: no such file or directory
```

**成功の確認**: `chezmoi apply` が modify script で止まらずに終わり、
`~/.local/bin/chezmoi-python3 -c 'import tomllib'` が成功する。

## Windows で tomllib や Python のエラーが出る

**対象**: Windows。設定生成と agent hook（どちらも `py -3` で起動する）。

**症状**: `chezmoi apply` や hook が `tomllib` の import か Python の起動で失敗する。

**確認**: `py -3` が選ぶ Python が 3.11 以上か見る。

```powershell
py -3 -c "import sys, tomllib; print(sys.version)"
```

**原因**: `tomllib` は Python 3.11 以上の標準ライブラリ。`py -3` が 3.10 以下を選んでいる。
`tomli` の手動導入は不要（[ADR-0003](../adr/0003-require-python-311-for-agent-configuration.md)）。

**対処**: Python 3.12 を入れ、PowerShell を開き直してから再実行する。

```powershell
winget install --id Python.Python.3.12 --exact --silent `
  --accept-package-agreements --accept-source-agreements
chezmoi apply
```

**成功の確認**: 上の確認コマンドが 3.11 以上の版を表示する。

## chezmoi update が Bitwarden で止まる

**対象**: 全 OS。`bitwarden` テンプレート関数を使う `~/.config/git/user` と
`~/.config/sops/age/keys.txt`。

**症状**: 久しぶりの `chezmoi update` で次がまとめて出て止まる。

```text
chezmoi: warning: config file template has changed, run chezmoi init to regenerate config file
.config/git/ignore has changed since chezmoi last wrote it?
You are not logged in.
chezmoi: .config/git/user: template: ...: error calling bitwarden:
  ... bw unlock --raw: exit status 1
```

**確認**: ログイン状態と `bw` の実体を見る。

```bash
bw status
mise which bw           # Unix。~/.local/share/mise/installs/... を指すこと
```

```powershell
Get-Command bw          # Windows
```

**原因**: 3 つが同時に起きている。上から順に片付ける。

| 行 | 意味 | 対処 |
| --- | --- | --- |
| `config file template has changed` | `home/.chezmoi.toml.tmpl` が更新された。`~/.config/chezmoi/chezmoi.toml` は古いまま | `chezmoi init` |
| `... has changed since chezmoi last wrote it?` | 展開先が chezmoi の記録と食い違う。上書き可否を聞かれている | `chezmoi diff` で中身を見てから答える |
| `error calling bitwarden` | `bw` は入ったが未ログイン。`bw unlock` が失敗しテンプレートが落ちる | `bw login` してセッションを張る |

`bw: command not found` なら `bw` 自体が入っていない。Unix は mise の npm backend、
Windows は winget で入る（[セキュリティ](security.md#bitwarden連携)）。

**対処**:

```bash
chezmoi init                                  # 設定ファイルを再生成
chezmoi diff ~/.config/git/ignore             # 上書きしてよいか確認
bw login && bw sync
export BW_SESSION="$(bw unlock --raw)"
chezmoi apply
```

別のアカウントでログインしていたなど、セッションを張り直すときは
`bw logout` から始める。`bw` が無い場合は次で入れる。

```bash
mise install            # npm:@bitwarden/cli を含むツール一式
mise reshim
```

```powershell
winget install --id Bitwarden.CLI --exact
```

`BW_SESSION` を張らないまま `chezmoi apply` しても止まらない。`.chezmoiignore.tmpl` は
`BW_SESSION` が無い間、または展開先が既にある間は `~/.config/git/user` と
`~/.config/sops/age/keys.txt` を無視する。Bitwarden を使わないマシンならそのままで
構わない。age 鍵が無い・sops で復号できない場合は
[秘密情報の管理セットアップ](sops-age.md#鍵が展開されない)を参照。

**成功の確認**: テンプレート関数が値を返し、2 つのファイルが展開される。

```bash
chezmoi execute-template '{{ (bitwarden "item" "gitconfig").login.username }}'
ls -l ~/.config/git/user ~/.config/sops/age/keys.txt   # 中身は表示しない
```

## mise の npm ツールが突然動かなくなる

**対象**: Linux / WSL / macOS。mise の npm backend で入れたツール
（`bw` / `markdownlint-cli2` など）。

**症状**: ある日突然落ちる。`mise ls` には正常に出るので気付きにくい。
壊れ方は 2 通りあり、対処は同じ。

```text
Error: Cannot find module
  '~/.local/share/mise/installs/npm-bitwarden-cli/latest/node_modules/
   .mise/@bitwarden+cli@2026.7.0/node_modules/@bitwarden/cli/build/bw.js'
```

```text
exec: node: not found      # あるいは shim が解決できない
```

**確認**: キャッシュへの symlink が宙ぶらりんになったもの（下の A）は次で洗い出せる。

```bash
find ~/.local/share/mise/installs -path '*/node_modules/.mise/*' \
     -maxdepth 6 -xtype l -printf '%h\n' | sort -u
```

この検索には PATH に載っていない古い残骸も出る。mise は以前 `installs/<tool>/` の名前で
入れており、現在の `installs/npm-<tool>/` とは別に残る。
`~/.config/mise/config.toml` とリポジトリの `mise.toml` に宣言が無ければ残骸なので、
そのまま消してよい。

**原因**: 導入物の一部が消えている。2026-09-15 に次の 2 通りを観測した。
**何が消したかは特定できていない**（キャッシュ削除ツール、ディスク掃除、中断した
導入などが候補）。

- **A. キャッシュの実体が消えた**: npm backend は依存の実体を
  `~/.cache/aube/virtual-store/` に置き、`installs/` からそこへ symlink を張ることがある。
  `~/.cache` を消すとリンク先だけが消える。npm-bitwarden-cli 2026.7.0 では `.mise/` 配下の
  symlink 213 個が全滅し、実体ディレクトリで入っていた npm-anthropic-ai-sandbox-runtime は
  無傷だった
- **B. 導入物の一部が欠けた**: 古い世代の導入物は `bin/<tool>` が
  `../lib/node_modules/...` を指す。npm-markdownlint-cli2 0.22.1 は `bin/` が残って
  `lib/` だけが無かった。同じ世代の npm-google-gemini-cli は無傷で、個別の欠損だった

**対処**: ディレクトリごと消してから入れ直す。Copilot CLI の sandbox の中では
`~/.local/share/mise` が read-only なので（Claude Code の sandbox は書き込みを許している）、
`rm` も `mise install --force` も `Read-only file system` で失敗する。sandbox の外の
シェルで実行する（[sandbox](agent-sandbox.md)）。

```bash
rm -rf ~/.local/share/mise/installs/npm-bitwarden-cli
mise install "npm:@bitwarden/cli"
```

入れ直した後の `.mise/` 配下は symlink ではなく実体のディレクトリになっていた
（2026-09-15、3 ツールとも symlink 0 件）。再び symlink で入るようなら、`~/.cache` を
消さない運用にするか、消した直後に入れ直す。

**成功の確認**: `bw --version` などが版を表示し、上の `find` が何も出さない。

## VS Code の拡張が入っていない

**対象**: ネイティブ Linux（`100_linux/110_native/`。WSL と Raspberry Pi では対象外）と
Windows（`300_windows/340_vscode`）。

**症状**: VS Code は使えるが、`chezmoi apply` 後も拡張が入っていない。

**確認**: `code` が PATH にあるか見る。

```bash
command -v code
code --list-extensions
```

**原因**: Linux の `112_vscode_extensions` は `code` が無いと拡張の導入を飛ばし、
**0 で終わる**。`run_once_` なので成功として記録され、後から VS Code を入れても
走り直さない。通常は直前の `111_microsoft` が `code` を入れるので起きない。

Windows の `340_vscode` は VS Code が無ければ winget で入れ、拡張の導入に失敗すると
非ゼロで終わる。記録されないので、次の apply でもう一度走る。ただし入れた直後に
`code` が見つからない場合は、警告だけ出して 0 で終わる（Linux と同じく走り直さない）。

**対処**: Linux は VS Code を入れてから `112` だけを走らせ直す
（[スクリプトを走らせ直す](#スクリプトを走らせ直す)）。

```bash
src="$(chezmoi source-path)"
bash "$src/.chezmoiscripts/100_linux/110_native/run_once_after_112_vscode_extensions.sh.tmpl"
```

このテンプレートはテンプレート構文を含まないので、描画せずに実行できる。

**成功の確認**: `code --list-extensions` に `eamodio.gitlens` などが出る。

## apt update が GitHub CLI の NO_PUBKEY を警告する

**対象**: Ubuntu。`gh` を mise 管理へ移す前に登録した APT リポジトリ。

**症状**: `apt update` のたびに次が出る。

```text
GPG エラー: https://cli.github.com/packages stable InRelease:
  公開鍵を利用できないため、以下の署名は検証できませんでした: NO_PUBKEY ...
```

**確認**: 登録の場所を見る。

```bash
grep -rl 'cli\.github\.com' /etc/apt/sources.list.d/
```

**原因**: 残っている APT 登録の署名鍵が失効している。**chezmoi は自動で直さない。**
既存の APT 登録・鍵・認証設定は自動削除しない方針のため
（[mise による CLI 管理](structure.md#mise-による-cli-管理)）。

**対処**: どちらかを手で選ぶ。`gh` は mise から入るので、消しても困らない。

```bash
# A) もう使わないので消す（mise 版の gh はそのまま使える）
sudo rm /etc/apt/sources.list.d/github-cli.list
sudo apt-get update

# B) APT 版の gh を使い続けるので鍵だけ入れ直す
wget -qO- https://cli.github.com/packages/githubcli-archive-keyring.gpg |
  sudo tee /usr/share/keyrings/githubcli-archive-keyring.gpg >/dev/null
sudo chmod 0644 /usr/share/keyrings/githubcli-archive-keyring.gpg
sudo apt-get update
```

**成功の確認**: `apt-get update` が警告を出さない。どちらを選んでも
`mise which gh` の結果は変わらない。

## apt update が VS Code のソース二重登録を警告する

**対象**: ネイティブ Linux（Ubuntu）。

**症状**: `apt update` が VS Code のソースを二重に登録していると警告する。

**確認**:

```bash
ls /etc/apt/sources.list.d/vscode.*
```

**原因**: `vscode.list`（`111_microsoft` が `.sources` の無いときに作る）と `vscode.sources`
（`code` パッケージ自身が置く deb822 形式）が競合している。

**対処**: `111_microsoft` と `121_ubuntu` は、`.sources` があるときに `.list` を消す。
ただしどちらも `run_once_` なので、直るのはスクリプトが走ったとき（初回と内容の変更時）
だけ。走った後に再発した場合は手で消す。

```bash
sudo rm -f /etc/apt/sources.list.d/vscode.list
sudo apt-get update
```

**成功の確認**: `ls` に `vscode.sources` だけが残り、`apt-get update` が警告を出さない。

## AI CLI が mise に global default version を指定しろと言う

**対象**: Linux / WSL / macOS の `opencode` / `omp` / `claude` / `copilot`。
Windows は未確認（下記）。

**症状**: CLI を起動すると次が出る。

```text
mise ERROR No version is set for shim: opencode
Set a global default version with: mise use -g opencode@<version>
```

言われたとおり `mise use -g` すると、今度は `configuration invalid at ...` になる。
`omp` はそもそも mise のレジストリに無く（`tool not found in registry: omp`）、
`mise use -g omp` は成功しない。

**確認**: CLI の解決先を見る。

```bash
command -v opencode      # ~/.local/share/mise/shims/opencode なら該当
```

**原因**: CLI が公式の導入先ではなく **mise の残骸 shim** に解決されている。

AI CLI は `d0abd95` で mise 管理から各社の公式インストーラーへ移したが、切り替え前の
shim と installs は残る。PATH 上では mise の shims が公式の導入先（`~/.local/bin` など）
より前に来る。ここで抜けられない輪ができる。

1. 残骸の shim が版を解決できず、上のエラーになる
2. `mise use -g opencode@latest` すると宣言が足されて動く
3. 次の `chezmoi apply` が `~/.config/mise/config.toml`（chezmoi 管理。正本は
   `home/dot_config/mise/config.toml.tmpl`）を上書きし、宣言が消えて 1 へ戻る

`configuration invalid` は別物が入るために起きる。`mise registry opencode` は
`aqua:anomalyco/opencode`（V1 系）で、生成する `~/.config/opencode/opencode.json` は
V2 スキーマなので V1 のバイナリが弾く。世代の違いは
[V2 の仕様](../research/opencode/v2-capabilities.md)を参照。

**対処**: `126_agent_cli` / `226_agent_cli`（中身は
`home/.chezmoitemplates/agent-cli-install.sh.tmpl`）が残骸を消し、shim を「導入済み」と
数えない（[mise 版からの移行](structure.md#mise-版からの移行)）。掃除を入れた版に
更新された最初の apply で 1 回走る。**その後に再発した場合は `chezmoi apply` では
走らない**ので、手で消す。

```bash
rm -f ~/.local/share/mise/shims/{claude,copilot,opencode,omp}
rm -rf ~/.local/share/mise/installs/{claude,claude-code,copilot,opencode,omp}
chezmoi apply            # mise use -g で足した宣言を戻す
exec zsh                 # PATH を張り直す
```

公式版が入っていない CLI があれば、手で入れるか `126` を走らせ直す
（[スクリプトを走らせ直す](#スクリプトを走らせ直す)）。

Windows の `314_agent_cli` は `Get-Command` で判定し、同じ掃除は入れていない
（実機で確認できていないため）。Windows で同じ症状が出たら `%LOCALAPPDATA%\mise\shims` を
確認する。

**成功の確認**:

```bash
command -v opencode      # ~/.opencode/bin/opencode であること
opencode --version       # v2.x であること
```

## AI CLI の導入が 403 で失敗する

**対象**: Linux / WSL / macOS の `126_agent_cli` / `226_agent_cli`。主に oh-my-pi（`omp`）。

**症状**: apply の出力に次が出る。

```text
curl: (22) The requested URL returned error: 403
⚠️  導入できなかった CLI: omp
⚠️  完了：一部の AI CLI が入っていません
```

**確認**: GitHub API のレート制限の残量を見る。

```bash
curl -s https://api.github.com/rate_limit
```

**原因**: oh-my-pi のインストーラーは最新リリースを GitHub API
（`api.github.com/repos/.../releases/latest`）から引く。未認証の GitHub API は
60 リクエスト/時で、超えると 403 を返す。

`agent-cli-install.sh.tmpl` は CLI ごとに失敗を受け止めるので、1 つ 403 でも残りは入り、
**`chezmoi apply` 自体は成功する**。失敗した回は再実行の印を書き直すので、
**次の `chezmoi apply` で、入っていない CLI だけを導入し直す**
（[スクリプトを走らせ直す](#スクリプトを走らせ直す)）。レート制限が戻る前に apply すると
また失敗するが、そのたびに印が書き直されるので、戻った後の apply で入る。

**対処**: `remaining` が 0 なら 1 時間ほどで戻る。戻ってから `chezmoi apply` するか、
失敗した CLI だけを手で入れる。

```bash
curl -fsSL https://omp.sh/install | sh
```

他の CLI が失敗した場合の導入コマンドは、スクリプトの警告に出ている
（`home/.chezmoitemplates/agent-cli-install.sh.tmpl`）。スクリプトごと走らせ直すなら
「スクリプトを走らせ直す」の `execute-template` を使う。既に入っている CLI には触らない。

**成功の確認**: `command -v omp` が導入先を表示する。

[トラブルシューティングへ戻る](troubleshooting.md)
