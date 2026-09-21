# OpenCode V2 の shell allow の費用対効果と plugin ゲート（P1-3）

> **調査日: 2026-09-21**
> **対象: `opencode v2.0.10`**
>
> 実履歴の集計は `~/.local/share/opencode/opencode.db` の複製から。
> 挙動の実測は隔離環境（`XDG_CONFIG_HOME` / `XDG_DATA_HOME` を差し替え +
> `--standalone`）で行った。実環境の `~/.config/opencode/` は無傷。
> [CHG-0002](../change/0002-opencode-ask-by-default.md) の P1-3 を潰すための調査。
>
> **訂正 (2026-09-21)**: 隔離手段の記述は誤り。OpenCode は config dir の
> 決定に `XDG_CONFIG_HOME` を使わない（`OPENCODE_CONFIG_DIR` が正しい）。
> **本記録の結論は有効**（permission をプロジェクト側に置いており、
> global config に依存していないため）。
> 詳細は [試験環境の隔離方法](opencode-test-isolation.md)。

## 0. 本書の用途

段階 1 の `[opencode.shell] allow` に何を載せるかを決める。あわせて、
`find` のような「用途は安全だが危険な形も取れる」コマンドの扱い方を決める。

## 1. 結論

| # | 結果 |
| --- | --- |
| **P1-3** | **決着。** allow は読み取り専用 7 件。任意コード実行を含む 6 件は落とす |
| 静的パターン | `-exec` だけを deny できる。ただし**クォートと変数で回避できる** |
| plugin ゲート | **`ask` → `allow` の引き上げが効く。**deny のメッセージで代替手段へ誘導できる |
| `find` | 段階 1 では allow に載せず `ask`。段階 2 の plugin で選別器にする |

**最大の収穫は `ask` → `allow` の引き上げが実測できたこと**である。
CHG-0002 の段階 2 以降は「機構で確認回数を回復する」構想に全面的に依存して
いるが、ここまで deny 側しか実測していなかった。

## 2. 現行 allow 14 件の費用対効果

### 方法

`session_message` の `assistant` 行から `content[].type == "tool"` を抽出し、
`shell` の `input.command` を集めた。`&&` / `||` / `;` / `|` で粗く分割し、
`[bash] allow` の各項目へ前方一致させた。

```text
session_message 499 行（assistant 416）
ツール呼び出し: shell 264 / edit 100 / read 43 / webfetch 24 / grep 11 /
                write 11 / skill 5 / websearch 4 / subagent 4 / question 3 /
                execute 2 / glob 2
shell コマンド 264 件 -> セグメント 1,247 件
```

### 結果

| allow 項目 | ヒット | 任意コード実行 |
| --- | ---: | :---: |
| `grep -n` | 29 | — |
| `git status` | 11 | — |
| `git diff` | 9 | — |
| `wc` | 8 | — |
| `find` | 7 | **あり**（`-exec` / `-delete`） |
| `git log` | 4 | — |
| `gcc` | 0 | **あり** |
| `g++` | 0 | **あり** |
| `cmake -S` | 0 | **あり** |
| `cmake --build` | 0 | **あり** |
| `uv sync` | 0 | **あり** |
| `mise run` | 0 | **あり** |
| `uv pip list` | 0 | — |
| `docker ps` | 0 | — |

**合計 68 / 1,247 セグメント（5%）。**
任意コード実行を含む 6 件のうち 5 件がヒット 0 で、
**リスクだけ負って利得が無い**状態だった。

この DB は最近の OpenCode 利用のみで、C++ プロジェクトの作業を含まない。
`gcc` / `cmake` の 0 はサンプルの偏りの可能性がある（**推測**）。ただし
allow の採否はリスク基準で決めるべきで、頻度は「落としても痛くない」ことの
確認にしか使っていない。

### 未ヒット側（1,179 件）の先頭トークン

| 先頭 | 件数 | 被覆 |
| --- | ---: | ---: |
| `cd` | 208 | 16.7% |
| `echo` | 152 | 12.2% |
| `sed` | 68 | 5.5% |
| `head` | 67 | 5.4% |
| `tail` | 56 | 4.5% |
| `python3` | 50 | 4.0% |
| `grep` | 46 | 3.7% |
| `ls` | 44 | 3.5% |
| `uv` | 32 | 2.6% |
| `rm` | 30 | 2.4% |
| `cat` | 25 | 2.0% |

`sed` 68 件のうち 52 件は `sed -n`（読み取り）。残りは `sed 's/…/…/'` で
置換を含む。

読み取り系（`grep` / `head` / `tail` / `sed -n` / `cat` / `ls`）を足すと
被覆は 5% → 約 32% になるが、これらは
[read deny を迂回する](opencode-permission-gaps.md)。現行の `grep -n` が
既にこの穴を開けている。**段階 1 では広げず、保護を作ってから広げる。**

## 3. 静的パターンの表現力と限界

### `-exec` だけを deny できる

```json
{ "action": "shell", "resource": "find *",        "effect": "allow" },
{ "action": "shell", "resource": "find * -exec*", "effect": "deny"  }
```

| コマンド | 結果 |
| --- | --- |
| `find . -name "*.md"` | allow（実行された） |
| `find . -name "*.md" -exec echo FOUND {} \;` | **deny**（`Permission denied: shell`） |

`*` は空白を跨いで一致し、`-exec*` は `-execdir` にも当たる。
deny 時は `permission.evaluate` の hook が**呼ばれなかった**。
config の deny が hook より前段で効くという
[既知の性質](opencode-plugin-api-probe.md)と整合する。

### クォートと変数で回避できる

破壊的要素を排除するため、無害なトークンで同じ構造を測った。
deny パターンは `echo * --zap*`。

| コマンド | 結果 | scanner が見た resource |
| --- | --- | --- |
| `echo hi --zap x` | **deny** | —（hook 未発火） |
| `echo hi --z""ap x` | allow | `echo hi --z""ap x` |
| `echo hi --ZAP x` | allow | `echo hi --ZAP x` |
| `Z=--zap; echo hi $Z x` | allow | `echo hi $Z x` |

2 行目と 4 行目はシェルが `--zap` として解釈する。とくに 4 行目は
**scanner が `;` で分割した結果、変数代入 `Z=--zap` が resource から
消えている**。

つまり静的パターンは、**シェルが後から再解釈する文字列**に対する
blocklist であり、境界としては機能しない。この性質は `find` 固有ではなく
**`[bash] deny` 全体に等しく当たる**。Claude 側は hook で `shlex` 正規化を
通すため事情が異なる。

### 含意: deny パターンは allow を正当化しない

| 構成 | `find . -exe""c sh -c '…'` の扱い |
| --- | --- |
| `find *` を allow + `-exec*` を deny | `find *` に一致 → **無確認で任意コード実行** |
| `find` を allow に載せない | どれにも当たらない → **ask でユーザに出る** |

deny パターンを足すと「守れている」という誤った安心を作りつつ allow を
残す口実になる。**allow から外すほうが deny を足すより強い。**

## 4. plugin による選別（ask → allow の引き上げ）

### 方法

config は `{action:"shell", resource:"*", effect:"ask"}` の 1 行のみ。
plugin が `permission.evaluate` で判定を上書きする。
**`--auto` は付けない**（付けると `ask` が自動承認され、引き上げが
効いたのか区別できない）。

```js
const DANGEROUS = new Set(["-exec","-execdir","-ok","-okdir",
                           "-delete","-fprintf","-fls","-fprint","-fprint0"])
const raw = new Map()   // tool call id -> 生コマンド

await ctx.tool.hook("execute.before", (e) => {
  if (e.tool === "shell") raw.set(e.id, e.input?.command ?? "")
})
await ctx.permission.hook("evaluate", (e) => {
  if (e.action !== "shell") return
  const cmd = raw.get(e.source?.id) ?? e.resources.join(" ; ")
  const t = cmd.replace(/["']/g, "").split(/\s+/).filter(Boolean)
  if (!t.includes("find")) return                    // 触らない = ask のまま
  const hit = t.find((x) => DANGEROUS.has(x))
  if (hit) { e.effect = "deny"; e.message = "… glob ツールを使ってください。"; return }
  if (/[$`]/.test(cmd)) return                       // 間接参照は ask へ落とす
  e.effect = "allow"
})
```

### 結果

| コマンド | plugin の判定 | 実際の挙動 |
| --- | --- | --- |
| `find . -name "*.md"` | `allow` | **確認なしで実行された** |
| `find . -name "*.md" -exec echo FOUND {} \;` | `deny` | ブロック + メッセージ到達 |
| `echo hello` | 触らず | `ask` へ落ちた |

deny の後、エージェントは自力で代替手段へ切り替えた。

```text
Error: find の -exec は任意コード実行/破壊的操作になるため禁止です。
       ファイル列挙なら glob ツールを使ってください。

That find command was blocked — I'll list markdown files with the suggested alternative.
✱ Glob "**/*.md"  2 matches
```

**メッセージが逐語で届き、代替手段に乗り換えてタスクを完遂した。**
これが指示ファイルへの記載との決定的な差である。指示は読み飛ばせるが、
deny は実行を止めたうえで代替案を差し込める。

### 3 分岐が要る理由

`find` を丸ごと deny にすると、逃げ場が `python3 -c "os.walk(…)"` や
`ls -R` になり**かえって悪化する**。実測 7 件は全てファイル列挙で、
`-exec` / `-delete` は 1 件も無かった。

```text
find home -path '*mise*' -o -name '*.toml.tmpl'
find home/dot_claude/hooks -name '*.py' -o -name '*.sh'
find . -type f
find proj -type f
find ~/.config/opencode -maxdepth 2
find ~/.opencode -maxdepth 3
find / -maxdepth 6 -name "opencode.json*"
```

末尾 3 件は**深さ制限つきのワークスペース外の列挙**で、`glob` では素直に
書けない。列挙形は通す必要がある。

なお `shlex` はクォート除去をするので、正規化を挟めば回避形を捕まえられる。

```python
shlex.split('find . -exe""c echo hi {} \\;')
# -> ['find', '.', '-exec', 'echo', 'hi', '{}', ';']
```

これは静的パターンには原理的に書けない。クォート除去も、
「曖昧なら `ask` に落とす」という第三の答えも、config には表現手段が無い。

## 5. 並列バッチの巻き添え中断

**既定 ask へ移行する際の前提に関わる観測。**

1 ターンで 3 件の shell を並列に出させ、うち 1 件が `ask` に落ちた場合を
観測した。非対話実行なので `ask` は自動拒否される。

```text
! permission requested: shell (echo hello); auto-rejecting
✗ find . -name "*.md" failed    Error: Tool execution interrupted
✗ echo hello failed             Error: Tool execution interrupted
✗ (3件目) failed                Error: Tool execution interrupted
Error: Step interrupted
```

plugin が `allow` と判定済みだった `find` まで巻き添えで止まっている。
**非対話・自動実行の文脈では、バッチ内の 1 件の `ask` がステップ全体を
壊す。** 対話利用なら確認が出るだけで済む。

CHG-0002 は「できるだけ全自動で走らせたい」が前提なので、既定 ask への
移行はこの性質とセットで評価する必要がある。

## 6. 既存資産との差分

`find` の危険フラグは既にリポジトリ内にある。

```toml
# home/dot_claude/hooks/lib/bashrules/tables.toml:181
find_exec_flags = ["-exec", "-execdir", "-ok", "-okdir"]
```

ただし `check_find_dangerous`（`bashrules/rm.py`）が見ているのは
`-exec rm|unlink|shred|rmdir` と `-delete` **だけ**で、次は対象外。

- `-exec sh -c '…'` のような汎用の任意コード実行
- `-fprintf` / `-fls` / `-fprint`（任意ファイルへの書き込み）

段階 2 で Python 資産へ橋渡しするなら、ここの拡張が要る。

また、Copilot の先頭トークン粗粒度化は `bash.allow` にのみ掛かる
（`scripts/agents/generate.py:514`）。将来 `[bash] deny` へ `find -exec` 系を
足しても、Copilot で `find` 全体が落ちる事故にはならない。

## 7. CHG-0002 への反映

| 項目 | 内容 |
| --- | --- |
| P1-3 | 決着。allow は読み取り専用 7 件 |
| 段階 1 | `find` と実測 0 件の 6 件を落とす。落としても確認は 7 件しか増えない |
| 段階 2 | `find` 選別器を追加。`ask` → `allow` の引き上げが実測できたので実現性は確定 |
| 段階 2 | plugin は `e.resources` ではなく `tool.execute.before` の生コマンドを読む |
| 新規リスク | 並列バッチの巻き添え中断。既定 ask の評価とセットにする |

### 段階 1 の allow（確定）

```toml
[opencode.shell]
allow = [
  "git diff", "git status", "git log",
  "wc", "grep -n",
  "uv pip list", "docker ps",
]
```

落とすのは `find` / `gcc` / `g++` / `cmake -S` / `cmake --build` /
`uv sync` / `mise run`。後者 6 件は実測ヒット 0 なので**確認は 1 件も
増えない**。`find` のみ +7 件（0.6%）で、段階 2 の選別器で回収する。

`uv pip list` と `docker ps` はヒット 0 だが、読み取り専用でリスクが無く、
他プロジェクトでの利用が見込めるため残す。

## 再確認すべき情報源

- 並列バッチの巻き添え中断が対話モードでも起きるか（**未確認**）
- `glob` ツールで深さ制限つきの列挙ができるか（**未確認**）
- `gcc` / `cmake` の利用頻度を C++ プロジェクトの履歴で再測定（**未実施**）

[調査記録一覧へ戻る](index.md)
