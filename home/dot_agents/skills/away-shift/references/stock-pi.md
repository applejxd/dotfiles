# 確認（ask）になる操作の一覧（pi の stock）

無人では、確認に誰も答えない。**確認は 5 分で拒否され（`promptTimeoutMs`）、1 回で 5 分を失う。** 拒否は承認にならない。
ここにある操作は、計画に入れない。出て拒否されたら、同じ形で繰り返さず、レポートの「分からなかったこと」に書く。

出典は、方針 `home/.chezmoitemplates/pi-permission-policy.json`（2026-11-10 時点）。仕組みは、このリポジトリの
`docs/spec/agent-config-generation.md` の「permission-system の設定（stock）」。方針は変わるので、**迷ったら配備済みの設定を読む**
（`~/.pi/agent/extensions/pi-permission-system/config.json` の `permission.bash`。読み取りは許可リストにあり、確認が出ない）。

## 拒否（実行できない）

| 種類 | 例 |
| --- | --- |
| 特権・push | `sudo *`、`git push*` |
| スクリプトをシェルへ渡す形 | `sh`・`bash`・`zsh`・`dash`（単独）、`sh -`・`bash -s*` |
| 秘密を取るコマンド | `gh auth token`、`gh secret set\|list`、`bw get\|list\|export`、`op read`、`op item get`、`vault read\|kv get`、`chezmoi secret` |
| 環境変数の一覧 | `printenv`（単独）、`env`（単独）。診断は `env-check` skill |
| 秘密のパス（読み書きとも） | `*.env`・`*.env.*`（`*.env.example` は可）、`*.pem`・`*.key`・`*id_rsa*` など、`~/.ssh/`・`~/.aws/`・`~/.gnupg/`・`~/.netrc`・`~/.config/gh/` |

## 強制の確認（誰も答えなければ拒否）

| 種類 | 例 |
| --- | --- |
| 外部への投稿・変更 | `gh` の `pr`・`issue`・`workflow`・`variable`・`gist` の変更系、`gh repo fork\|rename\|archive\|create\|edit\|delete`、`gh api` の書き込み（`-X`・`-f`・`--method` など）、`chezmoi apply\|update` |
| 公開・配布 | `gh release create\|edit\|delete\|upload`、`npm\|yarn\|pnpm\|uv\|cargo publish`、`twine upload`、`gem push`、`docker push` |
| 履歴・設定の改変 | `git rebase`・`git config`（`--get`・`--list` は可）・`git filter-branch`・`git update-ref -d`・`git reflog expire`・`git worktree remove`・`git remote add\|set-url` |
| 外部送信・永続化 | `scp`・`sftp`・`ssh`・`rsync`・`socat`・`ncat`・`nc`・`telnet`、`aws s3 cp\|sync`、`gsutil cp`、`crontab`・`at`・`batch`、`systemctl` の変更系、`systemd-run` |

読み取り系の `gh`（`gh pr view`・`gh issue list`・`gh api` の GET など）は確認が出ない。

## 床の確認（解釈できない・別のコマンドを包む形）

- `bash -c`・`eval`（中身を再解析しない）
- `sudo`・`env`・`xargs`・`nohup`・`parallel`・`watch`・`flock`、`find -exec`・`fd -x` など、別のコマンドを実行する前置き
  （`time`・`timeout`・`nice`・`stdbuf`・`setsid` は、中のコマンドで判定されるので、`timeout 20m <command>` は使ってよい）
- 解析できない形。例: heredoc と `2>&1` とパイプを同時に使う（`git commit -F - <<'EOF' 2>&1 | tail`）。長い本文は `write` でファイルに書く

## 作業ツリーの外のパス

作業ツリー（リポジトリ）の外の読み書きは、確認になる。確認が出ないのは次のとおり。

- 作業ツリーの中（`.tmp/away-shift/` を含む）
- 読み取りだけ: `/tmp`、`~/.agents/skills/` の下（この skill の `references/` と `scripts/` を含む）、`~/.pi/agent/` の一部（`npm/`・`install/`・`extensions/`・`prompts/` など）
- `python3 <作業ツリー外のスクリプト>` は、スクリプトのパスを読み取りとして扱う（許可リストの下なら確認なし）。
  **`uv run …` や `node …` は向きを証明できず、外のパスで確認になる**
- 実験の出力・キャッシュ・一時ファイルは、`work/` か `/tmp` に置く（`/tmp/*` は読み書きとも可）

## cc-safety-net（実行を止める）

破壊的な形は、確認ではなく**拒否**される（2026-11-10 に `cc-safety-net explain` で確認）: `git reset --hard`・`git checkout -- <path>`・`git restore`・
`git stash drop`・`git branch -D`・`git clean -f`、`find -delete`、作業ツリーの外・ホーム・`.git` を対象にする `rm -rf`。
どれも、この skill の「制約」でも禁じている。

## 確認が出ない（通る）が、やってはいけないもの

方針は「離席中」を区別できないので、次は通る（上の確認は 2026-11-10 の `cc-safety-net explain`。方針の側は、規則に無い bash は allow）。
**`SKILL.md` の「制約」で禁じており、停止時の監査（`git status`・`HEAD`）で確かめる**。

- `git commit`・`git stash`（`drop` 以外）
- `uv add`・`pip install`・`mise use -g`（`uv tool install`・`npm install -g` も、規則に無いので通る見込み。未確認）
- **作業ツリーの中の `rm -rf`**（`work/` の外でも通る。外・ホーム・`.git` だけが拒否される）
- 作業ツリー内の本体ファイルの編集（`write`・`edit` は作業ツリーのどこでも通る）
