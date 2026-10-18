# zsh の起動時間

- **観測日**: 2026-10-18
- **対象**: WSL2（Ubuntu）の zsh。mise 2026.10.9
- **一次情報**: この文書の実測（このリポジトリの外に公開された一次情報は無い）。
  `/usr/bin/time` の出力そのものは残っておらず、下の数値は測定者の記録による

現行の対処と理由は [プロジェクト構造](../../spec/structure.md#zsh-の起動時間) が正本。
ここには、その数値の根拠だけを残す。

## 結論

`zsh -i -c exit` は 0.37〜0.40 s から 0.24〜0.25 s になった。
主な要因は、PATH の `/mnt/*` の走査、`.zshenv` の shims 処理、`mise activate zsh` の fork。

## 条件

- 全体の時間: `zsh -i -c exit` を 3 回ずつ、`/usr/bin/time -f %e` で計測
- 区間別: `zsh -f` から個別に `source` し、`EPOCHREALTIME` の差で測定（改善前の状態）
- **xtrace は使わない**: zsh の xtrace で PATH を表示すると、PATH 展開の表示自体が
  遅く見える（`PS4` とのずれ）

## 結果

### 全体（3 回）

| 状態 | 時間（s） |
| --- | --- |
| 改善前 | 0.37 / 0.39 / 0.40（計測順は 0.40, 0.39, 0.37） |
| PATH から `/mnt/*` を外して起動（`.zshrc` で外す前に環境変数 PATH から外した） | 0.31 ×3（同じ日の改善前は 0.36〜0.37。約 -60 ms） |
| 上に `mise activate` 出力のキャッシュを足した | 0.29〜0.31 |
| さらに `.zshenv` の shims 処理を zsh では `path` 配列にした | 0.24〜0.25 |

### 区間別（改善前）

| 区間 | 時間 |
| --- | --- |
| `.zshenv` 全体 | 47 ms（うち `shellenv.sh` 47 ms、`wslenv.sh` 3 ms） |
| `mise activate zsh` の eval | 90 ms（fork 部分のみ 33 ms、`_mise_hook` 37〜52 ms） |
| `shellrc.sh` | 24 ms |
| `fzf.sh` | 38 ms |
| `60_suffix_alias` | 11 ms |
| `fzf --zsh` | 4 ms |

### 要因の単体測定

- 存在しないコマンドを `command -v` で探すと 1 回あたり約 10 ms
  （PATH の `/mnt/*` 6 エントリを走査。4 コマンドで 42 ms）
- zsh の `$commands` ハッシュの初回構築は 37 ms。構築後の参照は 0.016 ms
- `shellenv.sh` の `${__p#*":${shims}:"}`（先頭 `*` の最短一致、PATH 3492 文字）は 37 ms。
  `${__p%%…*}` は 0.1 ms、`path` 配列の `${path:#…}` は 0.09 ms
- tmpdir 関連の判定は fork なし

## 考察

- 0.24〜0.25 s の内訳のうち、初回 `_mise_hook` は約 40 ms、残りは zinit の同期ロード
  （zeno・fast-syntax-highlighting・pure）などで、これらの区間は改善後に測り直していない
- 各対処の効果は、上の全体の表を順に積んだ差で読める（個別の寄与の独立性は未確認）

## 未検証

- macOS / Windows / 別マシンでの値
- 改善後の区間別の内訳（zinit の各プラグインなど）
