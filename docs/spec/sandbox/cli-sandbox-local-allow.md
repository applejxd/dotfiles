# このマシンだけで許可を足す（Claude / Copilot）

chezmoi 管理に影響を与えずに、このマシンだけで sandbox の許可を足す方法（`local.toml`・`settings.local.json`・Copilot の `allowed_directories`・対話プロンプト・TUI・1 セッションだけ）と、どれを使うかの判断。sandbox 層の全体は [Claude / Copilot の sandbox](agent-sandbox.md)。

## このマシンだけで許可を足す (chezmoi 管理に影響を与えない)

データセット置き場 (`/data1`) や外部マウントなど、**このマシンでしか意味が
無いパス**を共有の `common.toml` に書きたくない場合の手段。共有設定を汚さず、
`chezmoi diff` にも出ない方法が CLI ごとに用意してある。

> [!IMPORTANT]
> `~/.claude/settings.json` の `sandbox` キーを直接編集しても無駄。
> `chezmoi apply` のたびに `generate.py` が丸ごと生成し直すため上書きされる。
> `~/.copilot/settings.json` も `deniedPaths` だけは同様に再生成される。

### 1. `~/.config/agents/local.toml` (両 CLI・マシン全体)

`generate.py` は起動時にこのファイルがあれば読み、**追記だけ**を共有設定へ
マージする。chezmoi の管理対象ではないので `chezmoi apply` でも消えず、
`chezmoi diff` にも現れない。

```toml
# ~/.config/agents/local.toml (chezmoi 管理外・このマシン専用)
[sandbox]
claude_read_allow   = ["/data1", "/data2"]   # データセットは read-only で十分
claude_write_allow  = ["/data1/outputs"]     # 書き出し先だけ read-write
copilot_read_allow  = ["/data1", "/data2"]   # Copilot にも要るなら両方書く
copilot_write_allow = ["/data1/outputs"]
deny                = ["/data1/private"]     # 許可した中の一部を塞ぐことも可能

# このマシンの「この案件でだけ」開きたいもの (Copilot)
[[copilot.locations]]
path = "~/src/some-project"
allowed_directories = ["/data1/some-project"]
```

- 反映させるには `chezmoi apply` を実行する (生成時に読まれる)。
- `[sandbox]` で追記できるのは `deny` / `claude_read_allow` /
  `claude_write_allow` / `claude_write_deny` / `copilot_read_allow` /
  `copilot_write_allow` のみ。**共有設定のエントリを消したり緩めたりはできない**
  (`sandbox.enabled = false` のようなキーは無視される)。
- `[[copilot.locations]]` で追記できるのは `path` / `approvals` /
  `allowed_directories`。同じ `path` が共有側にもあれば **union** される。
- **CLI 名の接頭辞を省略できない。** 無印の `read_allow` を書いても黙って
  無視されるため、`generate.py` が stderr に警告を出す。
- パスは実在している必要がある。存在しないパスは bwrap の bind-mount が
  失敗する要因になる。
- `AGENTS_LOCAL_CONFIG` 環境変数でファイルの場所を差し替えられる (テスト用)。
- `~/.config/agents` は `claude_write_deny` に入っているため、**sandbox 内の
  コマンドからは書けない**。エージェントがここに許可を書き足して自分の
  権限を広げることはできない。

### 2. `.claude/settings.local.json` (Claude・プロジェクト単位)

Claude の設定スコープは上から managed → `claude --settings` →
`.claude/settings.local.json` (project local) → `.claude/settings.json`
(shared project) → `~/.claude/settings.json` (user) の 5 段。
**`sandbox.filesystem` の配列はスコープをまたいでマージされる**
(上書きではなく結合) ので、project local に穴だけ書けばよい。
このファイルは Claude 自身が global gitignore に追加するためコミットされない。

```json
{ "sandbox": { "filesystem": { "allowRead": ["/data1"] } } }
```

user スコープに `settings.local.json` は**存在しない**。マシン全体に効かせたい
場合は 1 の `local.toml` を使うこと。

### 3. `[[copilot.locations]] allowed_directories` (Copilot・プロジェクト単位)

Copilot には **作業ディレクトリごと**の追加許可がある。`common.toml` に書くと
`~/.copilot/permissions-config.json` の `locations.<path>.allowed_directories`
へ展開され、そのプロジェクトで作業しているときだけ適用される。

```toml
[[copilot.locations]]
path = "~/src/some-project"
allowed_directories = ["/data1/some-project"]
```

location キーは **Git ルート** (リポジトリ外なら正規化した cwd)。
絶対パスのみで、公式仕様が「適用時に実在すること」を要求するため
`generate.py` が存在しないパスを落とす。**deny は書けない**
(`permissions-config.json` は deny / ask 非対応)。

案件固有のものは共有設定を汚さないよう、`common.toml` ではなく
chezmoi 管理外の `~/.config/agents/local.toml` に同じ書式で書く
(同じ `path` は union される)。

> [!IMPORTANT]
> **設定の実体はプロジェクトの外 (`~/.copilot/`) にある。**
> リポジトリの中に置いて共有することは**できない**。
> Copilot のリポジトリ設定が受け付けるキーは公式に列挙されており、
> `sandbox` も `permissions-config.json` の `locations` も含まれない。
> 許されているのは `deniedUrls` / `disabledMcpServers` のように
> **union で追加するだけ・削除できない** = 締める方向のキーに限られる。

### 4. 対話プロンプトで承認する (Copilot・プロジェクト単位・設定不要)

**実は一番手軽なのはこれ。** Copilot はディレクトリやツールの承認を
`~/.copilot/permissions-config.json` へ**自分で保存する**。公式に
「When you approve a tool or grant access to a directory for the current
location, the CLI records the decision here」とある。

> [!IMPORTANT]
> このファイルは CLI が書き込むため、`generate.py` は **location 単位で
> union** する (全置換しない)。以前は全置換していたため、
> **`chezmoi apply` のたびに対話承認が消えて同じプロンプトが再発する**
> 不具合があった。承認を取り消したいときは CLI を終了してから手で消す。

### 5. `/sandbox config` の TUI (Copilot・マシン全体)

Copilot の `readonlyPaths` / `readwritePaths` は、`generate.py` が既存の値に
`copilot_read_allow` / `copilot_write_allow` を**合算**して書く (既存分は消さない)。
そのため TUI で足した許可はそのまま残る (`chezmoi apply` でも消えない)。
`deniedPaths` だけは共有の `deny` で**置き換え**て再生成する。

### 6. 一時的に 1 セッションだけ

- Claude: `claude --settings '{"sandbox":{"filesystem":{"allowRead":["/data1"]}}}'`
- Copilot: `--add-dir` で作業ディレクトリを足す

> [!NOTE]
> どの方法でも **symlink は許可の手段にならない**。プロジェクト配下に
> `/data1` へのリンクを張っても、許可は実パスに与える必要がある
> ([symlink の扱い](agent-sandbox.md#symlink-の扱い))。

### まとめ: どれを使うか

| 効かせたい範囲 | Claude | Copilot |
| --- | --- | --- |
| **このプロジェクトだけ (まず試す)** | プロンプトで「don't ask again」→ `.claude/settings.local.json` | **プロンプトで承認** → `permissions-config.json` に自動保存 |
| このプロジェクトだけ (共有したい) | `.claude/settings.json` **(リポジトリ内・コミット)** | **不可** |
| このプロジェクトだけ (設定で明示) | `.claude/settings.local.json` | `local.toml` の `[[copilot.locations]]` |
| このマシン全体 | `local.toml` の `[sandbox]` | 同左 |
| 全マシン (共有) | `common.toml` の `claude_*` | `common.toml` の `copilot_*` |
| 1 セッションだけ | `claude --settings` | `--add-dir` |

**まず対話プロンプトで承認すれば足りることが多い。** 設定ファイルを書く必要が
あるのは「無人実行で聞かれたくない」「複数マシンへ配りたい」場合に限られる。

リポジトリの中に許可を置けるのは Claude だけ。Copilot はプロジェクト単位の
スコープを持つが、設定ファイルの実体は常にリポジトリの外にある。

> [!WARNING]
> **Claude の `.claude/settings.json` はコミット対象の共有ファイル**で、
> 公式に「In a git repository, commit it so teammates get it」とある。
> `sandbox.filesystem` の配列はスコープをまたいで結合されるので、
> **信頼していないリポジトリを clone しただけで自分の sandbox が広がりうる**。
> 緩和は `--setting-sources` で project スコープを除外する (v2.1.246+) か、
> managed settings の `allowManagedReadPathsOnly`。
> Copilot はリポジトリ設定に `sandbox` を許していないためこの経路が無い。
