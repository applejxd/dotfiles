# Claude / Copilot の sandbox のネットワーク層

Claude Code / Copilot CLI の sandbox のネットワーク層（`[web]` → `sandbox.network`）: ドメインの whitelist、資格情報の除去、WSL2 の抜け穴（seccomp）、sandbox に移せないネットワーク系の検査。sandbox 層の全体は [Claude / Copilot の sandbox](agent-sandbox.md)。`pis` の通信は [pis のサンドボックス](../guard/pi-sandbox.md)。

## ネットワーク層 (`[web]` → `sandbox.network`)

ファイル層と違い、**ネットワークは Claude と Copilot で足並みを揃えられない**。

| | Claude | Copilot |
| --- | --- | --- |
| 粒度 | **ドメイン単位** (`allowedDomains` / `deniedDomains`) | **on/off のみ** (`allowOutbound` / `allowLocalNetwork`) |
| 強制方法 | sandbox 外のプロキシ。全サブプロセスに適用 | OS レベル |
| 許可外の扱い | **承認プロンプト** (既定) | 単純に不可 |

`common.toml` の `[web] allow_domains` (WebFetch 用のドキュメントサイト) と
`[sandbox] shell_network_allow` (shell が実際に通信する CDN 等) を合算したものが
Claude の `sandbox.network.allowedDomains` になり、`deny_domains` は
`deniedDomains` に反映される。2 つに分けているのは役割が違うため:
前者を増やすと WebFetch の自動承認が広がり、後者を増やすと shell の通信先が
広がる (`test_network_allow_is_disjoint_from_web_allow_domains` で混在を検出)。

なお Claude は `WebFetch(domain:...)` の許可ルールからも sandbox の allowlist を
組み立てるため前者は実質二重だが、permission 側の記法が変わっても sandbox の
許可が崩れないよう明示的に出している。

> [!WARNING]
> **sandbox に効く wildcard は先頭の `*.` と単独の `*` だけ**。
> `example.*` のように他の位置に置いた wildcard は `WebFetch` には効くが
> sandbox 側は無視するため、穴が開いたつもりで開いていない状態になる
> (`test_web_wildcards_are_sandbox_compatible` で固定)。

### ネットワークも whitelist にしてある (Claude のみ)

`[sandbox] claude_network_strict = true` から `sandbox.network.strictAllowlist` を
立てており、**許可外ドメインへの接続は拒否される** (Claude Code v2.1.219 以降が
必要)。これが無いと許可外は拒否ではなく**承認プロンプト**になる。

許可漏れがあっても即座に破綻はしない。sandbox 内で接続が失敗し、
「sandbox 外での再実行」を求める承認プロンプトに落ちるだけなので、
足りないドメインが判明したら `shell_network_allow` に追記すればよい。

**Copilot 側は outbound が全ドメイン許可のまま**で、これは変えられない
(ドメイン単位の設定が存在しないため)。`allowedUrls` は公式に
"URLs or domains allowed without prompting" とあるとおり**承認プロンプトの
省略リスト**であって通信制限ではなく、sandbox 内の `curl` は任意のホストへ
到達できる。結果としてネットワークは Claude (制約のある環境用・厳しめ) と
Copilot (家用・緩め) で非対称なままになるが、これは運用方針とは一致している。

### 資格情報を sandbox 側で落とす (`sandbox.credentials`)

Claude Code v2.1.187 以降では `sandbox.credentials` で、sandbox 内の
環境変数を unset する (`deny`) か、値を伏せたままツールを動かす (`mask`)
ことができる。`check_secret_env_echo` や `check_gh_token_exposure` の一部を
肩代わりできるが、`mask` は TLS 終端 (`network.tlsTerminate`) を要求し
プロキシに平文を見せることになるため、導入は別途検討する (現在は未使用)。

### WSL2 での抜け穴 (seccomp フィルタ)

WSL2 では Windows バイナリ (`cmd.exe`, `/mnt/c/...`) の起動が Unix domain
socket 経由になるため、**seccomp フィルタが無いと sandbox から脱出できる**
(公式: "the optional seccomp filter has to be installed to block the socket
in the first place")。未導入だと Claude は
`[Sandbox Linux] apply-seccomp binary not available - unix socket blocking
disabled.` を出す。

このリポジトリでは **mise で導入し、パスを settings.json で教える**方式を
取っている。`npm install -g` は `[bash] deny` で禁止しているため使わない。

- `home/dot_config/mise/config.toml.tmpl` の
  `"npm:@anthropic-ai/sandbox-runtime"` が本体を入れる。
- `common.toml` の `[sandbox] seccomp_apply_path` が導入先を指し、
  `generate.py` が `sandbox.seccomp.applyPath` を生成する。

> [!IMPORTANT]
> **mise に書くだけでは効かない。** Claude が `apply-seccomp` を自動検出するのは
> npm のグローバル領域だけである:
>
> - npm グローバル prefix (`npm -g config get prefix`) 配下の `lib/node_modules`
> - `/usr/lib` / `/usr/local/lib` / `/opt/homebrew/lib` の `node_modules`
>
> mise の `npm:` バックエンドはパッケージを
> `~/.local/share/mise/installs/npm-.../` へ**隔離**するため、上記のどこにも
> 現れない (実機で npm prefix 配下の `@anthropic-ai/` が空のままになることを
> 確認済み)。そこで公式が用意している代替手段
> 「copy `vendor/seccomp/*` from sandbox-runtime and set
> `sandbox.seccomp.bpfPath` and `applyPath` in settings.json」を使い、
> **コピーの代わりに mise の導入先を直接指している**。

`seccomp_apply_path` の `{arch}` は `generate.py` が `x64` / `arm64` に
置換する。バージョン更新に追従するよう mise の `latest` エイリアスを経由し、
**パスが実在するときだけ**設定を出力する (未導入のマシンや非対応
アーキテクチャでは設定が出ず、Claude は従来どおり自動検出に戻るだけ)。

導入後は `/sandbox` の Dependencies タブに不足が出ていないことを確認する。

> [!NOTE]
> **版は固定していない。** `sandbox-runtime` は research preview で、
> README が「API と設定フォーマットは変わりうる」と明記している。
> `latest` 経由で Claude に効く（OpenCode の `ocs` は Fence に替えた。
> [OpenCode 隔離起動のアーキテクチャ](fence-boundary.md#版の扱い)）。
> 更新時は「拒否すべきものが拒否される」ことを確かめる（deny・直接通信・
> Unix socket・cwd 違い・並行実行）。Claude 側は `applyPath` が実在しなくなると**設定が出力されず自動検出へ戻る**
> ため、seccomp が黙って無効化されうる。

### sandbox に移せないネットワーク系チェック

以下は「どのドメインに繋ぐか」では表現できないため hook に残す:

| チェック | 残す理由 |
| --- | --- |
| `check_reverse_shell` | `/dev/tcp`・`nc -e`・待ち受けソケット。ドメイン許可の話ではない |
| `check_pipe_to_shell` | `curl \| sh` は**許可済みドメイン**でも成立する |
| `check_curl_file_send` | 許可済みドメインへの外部送信は sandbox では止まらない |
| `check_pip_redirect` | uv に統一するという**ポリシー**であってセキュリティではない |
| `check_gh_api_*` | GitHub API の意味解釈が必要 |

逆に `check_http_dangerous_output` (`curl` でシェル起動ファイルを上書き) は
[残る非対称](agent-sandbox.md#残る非対称) の Protected paths と `denyWrite` で**完全に冗長**になっている。
