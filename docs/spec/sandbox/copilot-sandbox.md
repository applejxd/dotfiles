# Copilot の sandbox（Claude とは別物）

Copilot CLI の sandbox が Claude Code の sandbox と違う点と、実測した既定の許可範囲。sandbox 層の全体は [Claude / Copilot の sandbox](agent-sandbox.md)。

## Copilot の sandbox は Claude と別物

Copilot の sandbox 設定は `~/.copilot/settings.json` の `sandbox` キーに入る。
スキーマは公式ドキュメントに記載が無く、実機で `/sandbox` の TUI を操作して
確認したもの (Copilot CLI 1.0.84-5):

```jsonc
"sandbox": {
  "enabled": true,
  "allowBypass": true,          // sandbox 外での実行を都度承認で許可
  "allowDevToolAccess": false,  // 自動許可。ADR-0008 により無効化
  "addCurrentWorkingDirectory": true,
  "sandboxMcpServers": true,
  "sandboxLspServers": true,
  "auth": { "git": true, "gh": true },
  "userPolicy": {
    "filesystem": {
      "readwritePaths": [], "readonlyPaths": [], "deniedPaths": []
    },
    "network": { "allowOutbound": true, "allowLocalNetwork": true }
  }
}
```

Claude との差で特に重要なもの:

- **既定のモデルが逆だった**。Claude の既定は「read 全許可 → deny を引く」
  ブラックリストだが、Copilot は **deny-by-default のホワイトリスト**
  (公式: "The sandbox is deny-by-default: unless a path is explicitly
  granted, a command cannot use it")。
  → このリポジトリでは Claude 側を `denyRead: ["~/"]` + `allowRead` で
  whitelist 化し、**両者のモデルを揃えてある**。
  → Copilot は cwd の外への書き込みがそもそもできないので、
  `claude_write_deny` (改竄防止) に相当する設定は**渡していない**。
- **`claude_read_allow` / `claude_write_allow` を Copilot に渡してはいけない**。
  Copilot 側は `copilot_read_allow` / `copilot_write_allow` が同じ役割を担う。
  内容はほぼ同じだが、ホーム外の扱いと write の範囲が違うため
  生成側が参照するキーを取り違えないことをテストで固定している
  (`test_copilot_sandbox_reads_only_the_copilot_keys`)。
- **ワイルドカード非対応・絶対パス限定** (公式ドキュメントに明記)。
  `deny` に書いた `~/**/.env` のようなパターンは Copilot 側では
  自動的に除外される (`build_copilot_sandbox` が `*` を含む要素を落とす)。
- **`deniedPaths` に read/write の区別が無い**。Claude の
  `denyWrite` 相当 (「改竄防止のため書き込みだけ止めたい」) を
  ここに書くと **read も止まり通常の開発作業が壊れる**:
  `~/.gitconfig` を入れると git が user 情報や include を読めず全 git 操作が
  失敗し、`~/.copilot/hooks` や `~/.config/agents` を入れると hook 自体が
  読めなくなる。よって共通の `deny` には
  **「純粋な秘密情報で、通常の開発で読む必要が無いもの」だけ**を置き、
  write のみ止めたいものは `claude_write_deny` (Claude 専用) に分ける
  (この不変条件は `test_copilot_deny_excludes_read_required_files` で固定)。
- `readonlyPaths` は Claude の `denyWrite` とは**別物**。前者は
  deny-by-default のホワイトリストへの「read 権限の付与」(足し算) で、
  後者は「write 権限の剥奪」(引き算)。ただし重なった場合は
  **より具体的なパスが勝ち、ユーザーが明示した規則は自動付与より優先される**
  ため、広い read/write 付与の内側を `readonlyPaths` で書き込み禁止にする
  使い方はできる (公式の例: `/project` は writable だが
  `/project/secrets` を read-only にするとそこだけ保護される)。
  リポジトリ内の秘密ディレクトリを守りたい場合はこれが使える。
- `~/.ssh` を denied にすると git over SSH は使えなくなるが、
  `auth.git` / `auth.gh` が GitHub 向けトークンを注入するため
  HTTPS 経由の `git` / `gh` は sandbox 内でも動作する。
- sandbox の適用範囲はプロセスによって強度が違う。shell コマンドや
  `grep`/`glob` (ripgrep) は **OS が強制**するが、CLI 内蔵の read/edit
  ツールは同じポリシーを**ソフトウェア的に自己チェックするだけ**
  (OS のバックストップが無い)。リモート MCP には適用されない。

`generate.py` が管理するのは `enabled`・`allowDevToolAccess`・
`userPolicy.filesystem` の 3 リスト。`network` / `allowBypass` / `auth`
といった挙動設定には触れない (家用の緩い運用を壊さないため)。
`readwritePaths` / `readonlyPaths` は `/sandbox config` の TUI から足した分と
`common.toml` の分を **union** する (生成側が手作業の追加を消さない)。

### 実測した既定の許可範囲 (WSL2, chezmoi リポジトリを cwd として `/sandbox policy`)

`copilot_*` の許可を足す前の Copilot が既定で何を許したかの実測は
[記録](../../research/agents/agent-sandbox-measurements.md#実測した既定の許可範囲wsl2-chezmoi-リポジトリを-cwd-として-sandbox-policy)
（当時は `allowDevToolAccess = true`。現在は `false` で許可も足してあるので、同じ表示にはならない）。
既定で許可されるのはシステム領域 (read-only)、`$TMPDIR`・cwd・セッション領域
(read-write)、`~/.copilot/logs` と skill 置き場 (read-only) だけ。

ここから分かること:

- **`$HOME` 直下は一切許可されていない**。`~/.gitconfig` `~/.bashrc`
  `~/.ssh` などは設定を足さなくても既定で触れない。
  `~/.copilot` も `logs` だけが read-only で、`hooks` や `settings.json` は
  許可対象外 = **改竄不能**。
- したがって Copilot 側では `deny` の大半が多重防御 (冗長) であり、
  実際に効くのは `allowDevToolAccess` が拾う可能性のある
  `~/.npmrc` / `~/.pypirc` / `~/.config/gh/hosts.yml` あたり。ただし
  **cwd を `$HOME` にして起動すると home 全体が read-write になる**ため、
  その場合の保険として残してある
  (公式: "Rules that you configure are always kept" なので自動付与に勝つ)。
- `$TMPDIR` が read-write で許可される。このリポジトリでは zsh 側で
  `TMPDIR` をリポジトリ直下 `.tmp` に向けているため
  (`home/dot_zshenv` の `_tmpdir_repo_local_update`)、
  sandbox の一時領域もリポジトリ内に収まる。
- 設定変更は **セッション開始時に読まれる**。`chezmoi apply` 後は
  Copilot を起動し直さないと `/sandbox policy` に反映されない。
- **存在しないパスの deny ルールは黙って無効化される**。未作成の
  `~/.netrc` などは enforce されず、Notes 節に
  `does not exist; it is not enforced by the OS sandbox` と出る。
  → 後からファイルが作られても (例: `npm login` が `~/.npmrc` を作る)
  そのセッション中は deny が効かない。次のセッションからは効く。
  `$HOME` が既定で未許可であるため実害は小さいが、ルールが効いているか
  どうかは **Notes 節を必ず確認する**こと。
  後から作られると困るもの（`~/.local/state/opencode-sandbox`）は、
  chezmoi が apply で先に作っておく（[信頼の鎖](fence-boundary.md#信頼の鎖)）。
- `/sandbox policy` は cwd ごとに解決されるため、確認したいディレクトリで
  実行すること。

実効ポリシー (設定 + 自動付与 + 管理ポリシーの合成結果) は Copilot の
セッション内で `/sandbox policy` を実行すると確認できる。
拒否の発生を記録したい場合は **Denial capture** を有効にする。

`/tmp` の read/write を sandbox で全面遮断する案は、zsh 側で
リポジトリ直下 `.tmp` へ `TMPDIR` を向ける仕組みとセットで行う将来タスクで
あり、現時点では対象外 (`executable_redirect-tmp.py` が引き続き担当する)。
