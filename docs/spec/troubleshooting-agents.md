# トラブルシューティング: AI CLI の実行時

Claude Code / Copilot CLI の sandbox・hook・skills と、`common.toml` から生成した設定で
起きる障害をまとめる。症状からの索引は [トラブルシューティング](troubleshooting.md)。
導入時の障害（Python・mise・AI CLI の導入）は
[導入と適用](troubleshooting-bootstrap.md)にある。

各項目は「対象 → 症状 → 確認 → 原因 → 対処 → 成功の確認」の順に書く。

## Linux で sandbox がコマンドを 1 つも実行できない

**対象**: Linux / WSL の Copilot CLI と Claude Code。sandbox の実装が CLI ごとに違うので、
必要なものも CLI ごとに違う
（[sandbox 機能の包括調査](../research/agents/sandbox-capabilities.md#1-全体像)）。

| CLI | Linux の実装 | 必要なもの |
| --- | --- | --- |
| Copilot CLI | bubblewrap（Microsoft MXC の backend） | 下の表の一式 |
| Claude Code | bubblewrap + socat | `bwrap`、`socat`（ripgrep は本体に同梱）。seccomp フィルタは任意 |

どちらも `run_once_after_121_ubuntu.sh.tmpl` が
`bubblewrap slirp4netns util-linux iptables socat` を入れるので、新しい環境では追加作業は
要らない。

### Copilot CLI

**症状**: bash だけでなく、ripgrep を使う `grep` / `glob` やサブエージェントまで、
コマンドの中身に関係なく同じエラーで即座に失敗する。

```text
Bubblewrap: network.enforcementMode='firewall' requires 'slirp4netns' on PATH:
No such file or directory (os error 2).
```

```text
Bubblewrap: network.enforcementMode='firewall' requires 'iptables' on PATH to
enforce firewall enforcement: No such file or directory (os error 2)
```

**確認**: 足りない実行ファイルを一度に洗い出す。

```bash
for c in bwrap slirp4netns unshare nsenter iptables ip6tables iptables-restore ip6tables-restore; do
  command -v "$c" >/dev/null || echo "missing: $c"
done
```

**原因**: `network.enforcementMode` が `firewall` のとき、MXC の bubblewrap backend は
ホスト側の実行ファイルを probe し、**1 つでも欠けると起動を拒否する**。sandbox の外で
走るのは CLI 本体だけなので、結果として全ツールが失敗する。出典は MXC の
`backends/bubblewrap/common/src/proxy_network.rs`（各 probe とエラー文言）。

| 実行ファイル | Ubuntu パッケージ | 役割 |
| --- | --- | --- |
| `bwrap` | `bubblewrap` | 名前空間の構築（0.5.0 以上、一部モードは 0.8 以上） |
| `slirp4netns` | `slirp4netns` | 非特権ユーザでのネットワーク名前空間 |
| `unshare` / `nsenter` | `util-linux` | 名前空間の作成と参加（essential なので通常は導入済み） |
| `iptables` / `ip6tables` | `iptables` | 名前空間内での通信フィルタ |
| `iptables-restore` / `ip6tables-restore` | 同上 | ルールの一括適用 |

**対処**: 不足は 1 つずつしか報告されないので、まとめて入れる。`121_ubuntu` を
走らせ直すより速い（あちらは `apt-get upgrade` や ClamAV の更新まで行う）。

```bash
sudo apt-get install -y bubblewrap slirp4netns util-linux iptables
```

反映には CLI の再起動が要る。

パッケージが揃っていても、次の 2 つはホスト側の状態に依存する。

- **`iptables` が legacy バックエンドを指している**: legacy は `/run/xtables.lock` を開くため
  root が要り、非特権 sandbox では失敗する。nft バックエンドは同ファイルを使わない。
  Ubuntu 20.04 以降の既定は nft なので、切り替えられている場合は戻す。

  ```bash
  update-alternatives --display iptables
  sudo update-alternatives --set iptables /usr/sbin/iptables-nft
  ```

- **`nf_conntrack` が未ロード**: 接続状態マッチに要り、非特権 sandbox は自力でロード
  できない。iptables はこれを `Invalid argument` としか報告しない。

  ```bash
  lsmod | grep nf_conntrack || sudo modprobe nf_conntrack
  ```

依存を導入できない環境では、`/sandbox` の Network タブで `enforcementMode` を `firewall`
以外へ変える。フィルタをかけないぶん `iptables` 系の probe も走らない。

**成功の確認**: CLI を再起動し、`ls` など無害なコマンドが sandbox の中で通る。

### Claude Code

**症状**: sandbox が有効にならない、または Bash が sandbox の中で動かない。

**確認**: `/sandbox` を開く。依存が足りないと Dependencies タブが出て、`ripgrep` /
`bubblewrap` / `socat` / seccomp フィルタのうち欠けているものを示す。必須の依存が
欠けている間は Dependencies タブだけが出る
（[Configure the sandboxed Bash tool](https://code.claude.com/docs/en/sandboxing)）。

**原因**: `bwrap` か `socat` が無い。seccomp フィルタだけが無い場合は動くが、WSL2 では
sandbox から抜けられる（[WSL2 での抜け穴](sandbox/agent-sandbox.md#wsl2-での抜け穴-seccomp-フィルタ)）。

**対処**:

```bash
sudo apt-get install -y bubblewrap socat
```

seccomp フィルタは mise の `npm:@anthropic-ai/sandbox-runtime` が入れ、`chezmoi apply` が
`settings.json` へ橋渡しする（[npm backend で入れている 2 つ](structure.md#npm-backend-で入れている-2-つ)）。
依存の検査は起動時に走るので、入れた後に Claude Code を再起動する。

**成功の確認**: 再起動後の `/sandbox` に Dependencies タブが出ない。

## Windows で Copilot の hook が起動しない

**撤去した**（2026-10、[ADR-0017](../adr/0017-pi-only-and-ts-judge.md)）。Copilot への hook の登録は生成しない。
配備済みの `~/.copilot/hooks/from-claude.json` は `chezmoi apply` が消す。判定は pi の判定器が持つ。

## CLI 起動時に Failed to load 1 skill と出る

**対象**: Claude Code / Copilot CLI。`home/dot_claude/skills/` などの `SKILL.md`。

**症状**: 起動時のバナーに `Failed to load 1 skill.` と件数だけが出て、そのスキルが
使えない。

**確認**: どのファイルかは Copilot CLI に聞く。

```bash
copilot skill list          # 末尾に "The following skills failed to load:" が出る
```

リポジトリ側では、pre-commit と同じ検証を全ファイルに掛ける。

```bash
uv run --with pyyaml --no-project python scripts/agents/validate_skills.py
```

**原因**: `SKILL.md` の YAML frontmatter が壊れていると、CLI はそのスキルを黙って読み
飛ばす。よくあるのは `description` を引用符なしで書いた場合の次の 2 つ。

- `undefined symbol: _ZNK3c10` のような**コロン + 空白**（mapping value と解釈されて
  パースエラーになる）
- `use # for comments` のような**空白 + `#`**（以降がコメントとして無言で捨てられる）

`name` がディレクトリ名と一致しない場合も `validate_skills.py` が弾く。

**対処**: `description: "..."` と二重引用符で囲む。

**成功の確認**: `validate_skills.py` が何も出さずに終わり、CLI の再起動後にバナーの
警告が消える。

## ツール呼び出しの引数が壊れる（`Invalid arguments`、引数が空）

**対象**: pi のツール呼び出し全般（観測したのは `guarded_edit`）。モデルは `claude-sonnet-5.5` で観測。

**症状**: 呼び出しが `Invalid arguments for tool "guarded_edit": Expected ':' after property name in JSON at position N`
で失敗する。記録上の呼び出しは `arguments` が `{}`（空）になる。
他のマシンで「引数が空のツール呼び出し」を見た記憶があるが、同じ現象と推測している（未確認）。

**確認**: セッション記録で失敗を数える。

```sh
grep -rhoE 'argumentsError": ?"[^\\]*' ~/.pi/agent/sessions | cut -c1-110 | sort | uniq -c
```

**原因**: モデルが引数の JSON を生成する途中で、壊れた出力をする。実測では、`"oldText"` の直後に
`:` ではなく `>` が出て、本文も途中で欠けていた。pi が `argumentsError` として検出し、モデルへ
不正な引数と返す。ツールやガードが壊したものではない。

**頻度**（2026-10-18、この機の全セッション）: ツール呼び出し約 2,600 回中 1 回（`guarded_edit` は 211 回中 1 回）。
直後の送り直しで成功した。子のエージェント（`guarded_task`）は `--no-session` で記録が残らないので、
子の失敗率は未測定。

**対処**: 同じ呼び出しを送り直す（モデルが自動で再送する）。頻発するなら、同じ編集を `write`（全文）に替える。

**成功の確認**: 送り直した呼び出しが `Successfully replaced ...` を返す。

## Windows で .copilot/skills のリンクが作られない

**対象**: Windows の Copilot CLI。`run_after_342_copilot_skills.ps1.tmpl` が作る
`~/.copilot/skills` → `~/.claude/skills` の directory junction。

**症状**: Copilot CLI から skill が見えない。apply の出力に
`contains unmanaged data` / `points to ...` / `Failed to maintain the Copilot skills junction`
の警告が出る。

**確認**:

```powershell
Get-Item "$HOME\.copilot\skills" -Force |
    Select-Object FullName, LinkType, Target
```

Windows では `.copilot/skills` を `.chezmoiignore.tmpl` で外しているので、
`chezmoi managed` に出ないのは意図した動作。

**原因**: symlink の作成には Developer Mode か管理者権限が要るため、このスクリプトは通常
権限で作れる junction を使う。次の場合は作らずに警告だけ出す。

- 既存の通常ディレクトリに中身がある（空なら消して作り直す）
- 既存のリンクが `~/.claude/skills` 以外を指している
- ホームディレクトリが UNC / network path にある（junction はローカルのファイルシステム
  にしか作れない）

**対処**: 中身を確認して別の場所へ移してから、もう一度 apply する。`run_after_` なので
毎回の apply で走る。

```powershell
chezmoi apply
```

**成功の確認**: 上の確認コマンドで `LinkType` が `Junction`、`Target` が
`~/.claude/skills` になる。

## pis の内側でクリップボードへコピーできない

**対象**: `pis`（sandbox の内側で動く pi）。WSL2（WSLg）で、Orca のターミナルから使う構成で確認した。

**症状**: `/copy` や選択コピーで `Clipboard unavailable: install \`wl-clipboard\` (\`wl-copy\`) or check Wayland access` と出る。

**原因**: 次の 2 点が重なる（出所は pi 本体の `dist/utils/clipboard.js`、1.3.0）。

- 内側から `DISPLAY` / `WAYLAND_DISPLAY` が見えるため、pi がデスクトップ環境と判断し、
  `wl-copy` / `xclip` / `xsel` だけを試す。OSC 52 には**回らない**（効いたかを確かめられないため）
- sandbox がそれらのソケットと、`powershell.exe` の相互運用を塞ぐ（推測。内側では未実測）

上流の見解（pi Issue #10558、2026-10-07 に not a bug で close）は「表示の変数が出ているなら、動くソケットを
用意するか、変数を unset する」。同じ症状の回避策として、メンテナは `PI_CLIPBOARD_OSC52=1` を挙げている
（Issue #11273）。

**対処**: `pis` は内側の環境へ `PI_CLIPBOARD_OSC52=1` を自動で渡す（`home/dot_local/share/ocs/pi.py` の
`inner_env`）。OSC 52 は端末への書き込み専用なので、sandbox の境界を広げない（X11 / Wayland のソケットを
許可すると、内側からクリップボードを読めてしまう）。端末側で OSC 52 の書き込みを許可する。

- Orca: `Settings → Terminal → Allow TUI Clipboard Writes (OSC 52)`
  （<https://www.onorca.dev/docs/terminal、日付未確認）>
- tmux 内で使うなら、別の問題がある。tmux は既定で OSC 52 を転送しない（pi Issue #10628、open。
  `set -g set-clipboard on` / `allow-passthrough` が要る）。`WT_SESSION` の継承で無言の失敗になる
  報告もある（Issue #11029、2026-10-16 close。`env -u WT_SESSION` が回避策）

**成功の確認**（`pis` の外のシェルで端末が対応しているかを見る）:

```bash
printf '\033]52;c;%s\a' "$(printf hello | base64)"
```

その後に貼り付けて `hello` が出れば、端末は対応している。2026-10-25 に Orca で確認した。

**限界**: pi は OSC 52 の成否を確かめられないので、端末が非対応でも「コピーした」と出る。

[トラブルシューティングへ戻る](troubleshooting.md)
