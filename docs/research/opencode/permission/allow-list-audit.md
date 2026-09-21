# OpenCode V2 の allow リスト監査（段階 1 の最終確認）

> **調査日: 2026-09-21**
> **対象: `opencode v2.0.10` / `git 2.43.0`**
>
> [CHG-0002](../../../change/0002-opencode-ask-by-default.md) 段階 1 の allow を
> 確定させるための監査。`github-copilot/gpt-6-astra` へレビューを依頼し、
> 指摘を実測で検証した。

## 0. 結論

**追加すべきコマンドは無い。むしろ `git diff` と `git status` を外した。**

段階 1 で「任意コード実行を含まない」という基準を立てたが、
**その基準を既存の allow 自身が満たしていなかった**。

| 発見 | 影響 |
| --- | --- |
| `git diff` は外部 diff で任意コマンドを起動する | allow から削除 |
| `git status` は `core.fsmonitor` で任意コマンドを起動する | allow から削除 |
| `sed -n` は書き込みも実行もできる | 追加候補から除外 |
| **リダイレクトが resource に残るため、allow 済みコマンドは全て任意書き込みの手段になる** | allow を最小に保つ根拠 |
| コマンド置換の内側は別 resource として抽出される | 静的パターンの数少ない利点 |

## 1. 実測データ（2,363 セグメント、2 日分）

現 allow の被覆は 126 件（5%）。

| allow 項目 | ヒット |
| --- | ---: |
| `grep -n` | 61 |
| `git status` | 29 |
| `wc` | 14 |
| `git diff` | 13 |
| `git log` | 9 |
| `uv pip list` / `docker ps` | 0 |

`ask` に落ちている 2,237 件の上位は `cd` 386 / `echo` 316 / `head` 132 /
`tail` 107 / `sed` 102 / `grep` 101 / `python3` 83 / `ls` 69。

標本はこの権限設計作業そのもののセッション由来で、`python3 -c` による分析や
`opencode api` が多い偏りがある。**比率の傾向を見る用途に限る。**

## 2. `sed -n` は安全ではない

`-n` は自動出力の抑制であって安全モードではない。

```console
$ sed -n 'w written-by-sed.txt' f.txt
$ ls written-by-sed.txt
written-by-sed.txt                     ← w フラグで書き込み

$ sed -n '1e touch EXECUTED-BY-SED' f.txt
$ ls EXECUTED-BY-SED
EXECUTED-BY-SED                        ← e コマンドで実行
```

`head` / `tail` / `cat` と並べて「読み取り専用」に分類していたが誤り。

## 3. `git diff` / `git status` は任意コード実行の経路

### `git diff`: 外部 diff

```console
$ printf '[diff "p"]\n\tcommand = sh -c "touch X"\n' >> .git/config
$ echo 'tracked.txt diff=p' > .gitattributes
$ git diff
touch: ファイルオペランドがありません
fatal: external diff died, stopping at tracked.txt
```

`fatal: external diff died` は git が外部コマンドを**起動した**証拠
（`sh -c touch` の引数の渡り方でファイルが作られなかっただけ）。

書き込みも単独で可能。

```console
$ git diff --output=WRITTEN.txt && ls WRITTEN.txt
WRITTEN.txt
```

### `git status`: fsmonitor

```console
$ printf '[core]\n\tfsmonitor = "sh -c \\"touch EXECUTED-BY-STATUS\\""\n' >> .git/config
$ git status --short
$ ls EXECUTED-BY-STATUS
EXECUTED-BY-STATUS                     ← 実行された
```

### `git log -p` は再現せず

同じ textconv を仕込んで `git log -p` を実行したが発火しなかった（**未再現**）。
原因は未特定。`git log` は allow に残しているが、同種の経路が無いとは
言えない。

### 成立条件

`.git/config` への書き込みが要る。監査時点で **`.git/*` に対する
write deny は 1 つも無く**、実際に追記できた。
`git config --local` は deny していたが、ファイルを直接書く経路が空いていた。

## 4. リダイレクトは resource に残る（最も重い発見）

scanner がシェル構文をどう分割するかを `permission.evaluate` で観測した。

| 生コマンド | `e.resources` |
| --- | --- |
| `echo $(echo INNER)` | `["echo $(echo INNER)", "echo INNER"]` |
| `wc -l < f.txt` | `["wc -l < f.txt"]` |
| `echo A > b.txt; echo C` | `["echo A > b.txt", "echo C"]` |

コマンド置換の内側は別 resource として抽出されるが、
**リダイレクトは分割されずコマンド文字列に残る**。前方一致なので、
allow 済みコマンドに `> path` を足した形がそのまま allow になる。

実環境（配備済みの設定）で確認した。

```console
$ wc -l f.txt > WRITTEN-VIA-WC.txt      ← 確認なしで実行された
{"resources":["wc -l f.txt > WRITTEN-VIA-WC.txt"]}
$ cat WRITTEN-VIA-WC.txt
1 f.txt
```

**allow に 1 つ載せるたびに、任意ファイル書き込みの手段が 1 つ増える。**
`.git/config` の write deny も、`edit` ツールを止めるだけで
shell のリダイレクトは通らない。

## 5. Astra に指摘された設計上の誤り

### `allow` を増やしても `deny` は弱まらない

「allow を増やすと deny の前段が緩む」と記述していたが誤り。permission は
多層防御ではなく**最終一致で決まる 1 つの判定**で、`generate.py` は
allow → ask → deny の順に並べるため deny が常に後ろにある。

正しい整理:

| | 対話実行 | 自動実行 |
| --- | --- | --- |
| `allow` | 確認なし | 実行される |
| `ask` | 確認が出る | **自動承認で実行される** |
| `deny` | 止まる | 止まる |

**自動実行では `allow` と `ask` は等価。** したがって allow の増減は
自動実行の権限境界を変えない。`find` / `uv sync` を外した効果も
「対話時に確認が戻る」ことであって、自動実行の封鎖ではなかった。

### 既存 allow にも秘密の読み出し経路がある

`grep -n` は `read` deny 対象のファイル内容を出力できる（既知）。
`git diff` / `git log` も履歴中の秘密を出す。「`cat` は保留、既存は安全」
という区別は成立しない。

### 「プラグインができたら解禁」では不十分

段階 2 のプラグインが実行前の文字列を検査するだけなら、クォート・変数・
子プロセスによる迂回が残る（[静的パターンの回避](shell-allow-and-plugin-gate.md)
と整合）。解禁条件は実装の有無ではなく、**秘密へのアクセスを実際に
遮断できること**。

## 6. 適用した変更

| 対象 | 変更 |
| --- | --- |
| `[opencode.shell] allow` | `git diff` / `git status` を削除（7 → 5 件） |
| `claude_write_deny_globs` | `**/.git/config` / `**/.git/hooks/**` / `~/.gitconfig` を追加 |
| `test_generate_opencode.py` | allow の固定値を更新。git 設定の write deny と、実行経路を持つ git コマンドが allow に無いことを固定 |

`.gitattributes` は通常のリポジトリファイルで編集頻度が高いため対象外。
`.git/config` を塞げば外部 diff の連鎖は切れる。

削除により対話時の確認は 42 件（1.8%）増える。

## 7. 未検証のまま残した論点

- `git log -p` の textconv 経路（**未再現**。原因未特定）
- プロセス置換 `<(...)` を scanner がどう扱うか（**未測定**）
- 子エージェントの権限が親の部分集合か（**未確認**）
- MCP 経由の読み取りが `read` deny を尊重するか（**未確認**）

## 再確認すべき情報源

- <https://opencode.ai/v2/docs/permissions>（最終一致、scanner の best-effort 性）
- リダイレクト先を permission の対象にする upstream の動きがあるか（**未調査**）

[調査記録一覧へ戻る](../../index.md)
