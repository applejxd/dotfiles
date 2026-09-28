# AI CLI 統合 permission / hook 管理

Claude Code / Copilot CLI の permission (allow/deny/ask) と hook 登録を
**単一ソース** で管理し、`chezmoi apply` で両 CLI の設定ファイルへ自動展開する仕組み。
OpenCode V2 は hook を持たないので、同じソースから permission と MCP だけを生成する。
Gemini CLI は `GEMINI_MANAGED` で定義した一部設定だけを生成する。
`hooks` はOrcaなどの外部ツールが管理するため保持し、`common.toml` からは生成しない。

設計判断の根拠は次のADRを正本とする。

- [ADR-0001: 外部ツール設定との共存](../adr/0001-external-tool-config-coexistence.md)
- [ADR-0002: ループバックHTTPの承認範囲](../adr/0002-loopback-http-approval-scope.md)
- [ADR-0003: agent設定生成にPython 3.11以上を要求](../adr/0003-require-python-311-for-agent-configuration.md)
- [ADR-0004: hook判定軸](../adr/0004-hook-check-semantic-axis.md)
- [ADR-0005: エージェント設定を秘密として扱う](../adr/0005-agent-runtime-config-as-secret.md)
- [ADR-0006: 指示を減らし強制は機構へ寄せる](../adr/0006-instructions-to-mechanisms.md)
- [ADR-0007: filesystem ガードの機構境界](../adr/0007-filesystem-guard-boundary.md)

sandbox が **何を提供しているか** (採用していない機能も含む) の網羅は
[sandbox機能の包括調査](../research/agents/sandbox-capabilities.md) を参照。

## 文書の構成

この文書は入口で、目的・CLI ごとの適用範囲・3 層の概要と、確認・導入・
切り分けの手順を置く。詳細は変えたいものに応じて次の文書を読む。

| 変えたいもの | 文書 |
| --- | --- |
| `common.toml` の構成、生成先と所有権、MCP、OpenCode の設定、hook の登録 | [設定の生成と所有権](agent-config-generation.md) |
| コマンド・ファイルの allow / ask / deny、照合規則、bash 検査ルール | [コマンド・ファイルの判定](agent-command-policy.md) |
| Claude Code / Copilot CLI の sandbox (ファイル・ネットワーク・seccomp)、マシン固有の許可 | [sandbox (Claude Code / Copilot CLI)](agent-sandbox.md) |
| OpenCode の隔離起動 (`ocs`) | [OpenCode 隔離起動のアーキテクチャ](opencode-sandbox.md) |

## 3 層構成

| 層 | 仕組み | 効く CLI |
| --- | --- | --- |
| 0. sandbox | Claude: `~/.claude/settings.json` の `sandbox.filesystem.denyRead/denyWrite`、Copilot: `~/.copilot/settings.json` の `sandbox.userPolicy.filesystem.deniedPaths` (どちらも generate.py が生成)。OS レベル (bwrap/Seatbelt) で強制されるパス単位の deny | **Claude + Copilot** |
| 1. permission リスト | `~/.claude/settings.json` の `permissions` (generate.py が生成) | **Claude のみ** |
| 2. hook | `check_bash.py` が同じリストを読んで deny / ask を返す | **Claude + Copilot** |

人が書くのは `common.toml` の `[bash] allow / ask / deny` と `[sandbox]` の
パス列だけ。そこから permission リストと sandbox 設定が生成され、hook も
同じ `[bash]` リストを読む。ルールを複数箇所に書く必要はない。

**なぜ複数層に配るのか**: hook は設定の読み込みに失敗しうる
(`~/.config/agents/__pycache__` 由来の import 失敗など、トラブルシュートに実例あり)。
permission リストは CLI 本体が評価するので、hook が落ちても Claude 側の deny は残る。
hook 自体も設定を読めないときは **fail-closed** で deny する。
sandbox はさらにその外側で OS が強制するため、hook や permission リストの
実装バグ・迂回パターンに関係なく該当パスへのアクセスを止められる
(ただし sandbox が対応できるのは「パスへのアクセス可否」のみで、コマンドの
意味を解釈する判定 (`check_secret_env_echo` 等) は代替できない)。

Copilot CLI の `permissions-config.json` は deny / ask を表現できない
(公式仕様) ため、Copilot 側の「コマンドの可否」の強制は hook が全面的に担う。
一方 sandbox は Copilot にもあり、`common.toml` の `[sandbox] deny` から
`merge_copilot_settings` が `sandbox.userPolicy.filesystem.deniedPaths` を
生成する (deny リストは両 CLI で共通。ただし Copilot はワイルドカードを
扱えないため、生成時に `*` を含む要素だけ落とす)。

### OpenCode V2 の扱い

この節は**通常起動 (`opencode`)** の扱いを書く。通常起動の OpenCode V2 に
sandbox は無い。強制に使えるのは permission リストと plugin の 2 つで、
`common.toml` の意図はその範囲で表現する。
生成は `generate.py --target opencode-config`。

Ubuntu / WSL では OpenCode を丸ごと OS のアクセス制御で囲う**隔離起動 (`ocs`)**
も併用している。その境界と permission の違いは
[OpenCode 隔離起動のアーキテクチャ](opencode-sandbox.md) が正本。

| 層 | OpenCode (通常起動) での状態 |
| --- | --- |
| 0. sandbox | **無い**。OS レベルの強制は効かない（[検討して不採用](../change/0002-opencode-ask-by-default.md)。隔離起動 `ocs` は別。[OpenCode 隔離起動のアーキテクチャ](opencode-sandbox.md)） |
| 1. permission リスト | `opencode.json` の `permissions`。**既定は `ask`** |
| 2. hook | plugin の `permission.evaluate` / `tool.execute.*`（`guide-plugin`） |

**permission と plugin は安全網であって境界ではない。** 実行前の文字列検査は
クォートと変数で、実行後の出力検査は `base64` ですり抜ける（実測）。

PostToolUse 系の hook (`format-file.sh` / `markdownlint.sh`) だけは、CLI 本体の
`formatter` 機能で等価な結果になる ([整形 (formatter)](agent-config-generation.md#整形-formatter))。

この差から、Claude / Copilot 向けとは 3 点だけ扱いを変えている。

**`ask_hook_owned` を除外しない**: Claude では `rm` のような「hook が承認要否
まで判定する」コマンドを静的 `ask` から外す (静的 ask を出すと hook の
exemption がどのモードでも無効化されるため)。OpenCode には委譲先が無いので、
外すと素通りになる。そのため静的な `ask` として出す。`rm` は毎回確認になる。

**deny の最終防衛線が permission リストしかない**: Claude では hook と sandbox
が同じ deny を別経路で強制するが、OpenCode では `permissions` が落ちれば
防御ごと消える。`opencode.json` 自身を `[file] write_deny_globs` と
`[sandbox] claude_write_deny` に入れて、エージェントが自分の deny を
書き換えられないようにしてある。

**`~/.config/opencode/service.json` は秘密情報として扱う**: background service の
認証 password が平文で入る。`[sandbox] deny` と読み取り deny の両方に入れる。

glob の変換・formatter・plugin・キーバインド・照合順などの詳細は
[OpenCode V2 の設定](agent-config-generation.md#opencode-v2-の設定) にある。

### Codex CLI / Gemini CLI の扱い

この 3 層は Claude Code / Copilot CLI 用で、`check_bash.py` も両 CLI しか
起動しない。Codex CLI と Gemini CLI は独自の宣言的な仕組みを持つので、
`common.toml` からは生成せず、同じ意図を手書きで並べている。

| CLI | 仕組み | ソース |
| --- | --- | --- |
| Codex CLI | `prefix_rule()` (Starlark) | `home/dot_codex/rules/*.rules` |
| Gemini CLI | policy rule (TOML) | `home/dot_gemini/policies/*.toml` |

そのため「必ず止めたい操作」を足すときは、`common.toml` だけでなく
この 2 箇所も更新する。経緯は
[ADR-0006](../adr/0006-instructions-to-mechanisms.md) を参照。

## Windows での扱い

Windows native では、CLI ごとに OS レベルの保護の有無が違う。
**Windows 11 の実機では確かめていない**（2026-09-27 時点。GitHub Actions の
Windows Server でテストを回したのと、上流のソース・公式資料を読んだのが根拠）。

| CLI | 何が効くか |
| --- | --- |
| Claude Code | `permissions` と hook は効く。**sandbox は native Windows 非対応**（公式は macOS・Linux・WSL2 のみ）。`settings.json` に `denyRead` を書いても OS では強制されない |
| Copilot CLI | `permissions-config.json` と hook は効く。sandbox は **Windows Insiders ビルドが必要**で、パス単位の deny は CLI と同梱の MXC の版次第（changelog 1.0.76 は「Windows cannot deny per path」、上流の MXC には deny 対応の判定がある）。`deniedPaths` は Windows では `C:\Users\...` の形に揃えて出す |
| OpenCode | `opencode.json` の permission と guide plugin が効く |

OpenCode は `310_packages/314_agent_cli` が Windows にも入れるので、`.chezmoiignore.tmpl`
の `.config/*` の除外から `.config/opencode/` を外している。以前は外しておらず、
Windows の OpenCode は読み取り禁止も shell の制限も無いまま動いていた。

Windows の OpenCode は grep / glob の結果を `C:\...`（Node の `path.resolve()`）で返す。
guide plugin は読み取り禁止の正規表現（`/` 区切り）を当てる前に `\` を `/` へ揃え、
Windows では大小文字を区別しない。grep の見出しはドライブ付き・UNC も認め、
shell のコマンド中の `\` 区切りのパスも候補にする。生成側（`_home_variants`）も
`~` を展開した形を `/` 区切りに揃える。permission の read の deny は OpenCode 自身が
`/` に揃えて照合するので、この問題は無い。

## 動作確認手順

### unit test

```bash
uv run --with pytest --with pyyaml --no-project pytest test/agents/ -q
```

hook は `AGENTS_CONFIG_DIR` で agents 設定ディレクトリを差し替えられるので、
`~/.config` へ apply する前でもリポジトリの `common.toml` に対してテストできる。

### dry-run

```bash
chezmoi diff ~/.claude/settings.json
chezmoi diff ~/.copilot/hooks/from-claude.json
chezmoi diff ~/.copilot/settings.json
chezmoi diff ~/.copilot/permissions-config.json

# 生成結果だけ見たいとき
chezmoi cat ~/.copilot/hooks/from-claude.json
```

### apply 後の hook 動作確認

```bash
# 正常コマンド (PASS)
echo '{"hook_event_name":"PreToolUse","tool_name":"Bash","tool_input":{"command":"git status"}}' \
  | python3 ~/.claude/hooks/check_bash.py

# critical: cd && bypass を block
echo '{"hook_event_name":"PreToolUse","tool_name":"Bash","tool_input":{"command":"cd /elsewhere && git push"}}' \
  | python3 ~/.claude/hooks/check_bash.py
# -> stdout に permissionDecision: deny の JSON が出力される

# format-file: Claude 形式 (file_path) / Copilot 形式 (path) の両方で動く
echo '{"tool_input":{"path":"/path/to/foo.py"}}' | bash ~/.claude/hooks/format-file.sh
```

## 新環境セットアップ

1. `chezmoi init --apply <repo>` で全ファイルが配置される
2. 全マシン共通の項目はリポジトリの `home/dot_config/agents/common.toml.tmpl` へ
   追加する。配備先の `~/.config/agents/common.toml` は `chezmoi apply` のたびに
   上書きされるので直接編集しない
3. このマシンだけの項目は chezmoi 管理外の `~/.config/agents/local.toml` へ書く
   ([このマシンだけで許可を足す](agent-sandbox.md#このマシンだけで許可を足す-chezmoi-管理に影響を与えない))
4. `chezmoi apply` で各 AI CLI の設定が再生成される

なお初回 apply 時、Claude Code が未起動なら `~/.claude/settings.json` は存在しない。
chezmoi modify_ スクリプトは空 stdin を受けると空オブジェクトとして扱い、common.toml
ベースの最小 settings.json (permissions + hooks) を生成する。

## トラブルシュート

| 症状 | 対応 |
| --- | --- |
| apply 後 Claude が `permissions` / `hooks` を読まない | Claude Code は起動時に settings.json を読むので再起動 |
| Copilot CLI で hook の deny が効かない | `~/.copilot/hooks/from-claude.json` が apply されているか確認。`copilot --log-level debug` で hook がロードされているか確認 |
| `~/.config/agents/command_policy.py` が読めない・壊れている | hook が fail-closed で全 bash を拒否する。`~/.config/agents/__pycache__/` を削除して `chezmoi apply` をやり直す |
| common.toml の編集が反映されない | `chezmoi diff` で差分を確認 → `chezmoi apply` |
| `chezmoi diff` が全て「new file」になる | **AI CLI の sandbox 内で実行している**。`~/` が不可視で展開先が空に見えるため。sandbox 外のシェルで実行する |
| `chezmoi` が `chezmoistate.boltdb: read-only file system` で落ちる | `~/.config/chezmoi` が書き込みの許可に入っているか確認 (`copilot_write_allow` / `claude_write_allow`) |
| `uvx` が `os error 30 at ".../uv/tools/.tmpXXXX"` で落ちる | `~/.local/share/uv/tools` が書き込みの許可に入っているか確認 |
