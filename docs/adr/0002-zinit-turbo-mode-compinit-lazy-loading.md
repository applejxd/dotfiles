# ADR 0002: zinit turbo mode と compinit 遅延ロードの導入

- **Status**: Proposed
- **Date**: 2026-03-11
- **Deciders**: applejxd

## Context

Phase 1 (nvm 削除) により起動時間は 10.7s → 1.2-1.5s に改善された。
しかし `zprof` の結果、以下のボトルネックが残っている:

| コンポーネント | 時間 (ms) | 備考 |
|--------------|-----------|------|
| compinit (2回呼び出し) | 659 | compdef 1040回 |
| zinit プラグイン 11個 | 265 | 全て同期ロード |
| compaudit | 139 | セキュリティ監査 |
| pure プロンプト | 114 | 初期化 |
| mise activate | 52 | eval 実行 |

### 重要な制約: zeno.zsh の読み込み順序

zeno.zsh は以下の依存関係がある:

```
compinit (補完システム)
  → mise activate (deno, fzf を PATH に追加)
    → zeno.zsh (deno が必要、fzf が必要)
      → zeno keybindings ($ZENO_LOADED で判定)
```

zeno.zsh のソースコードを確認した結果:
- 起動時に `whence -p deno` で deno の存在チェック → なければ `return`
- fpath にウィジェットディレクトリを追加し `autoload -Uz` + `zle -N` で登録
- `deno cache` を実行してキャッシュウォーム
- 最後に `ZENO_LOADED=1` をセット
- keybinding 設定は `$ZENO_LOADED` をチェック

### 参考: 実績のある手法

[Zinit の遅延読み込みを活用して Zsh 起動時間を短縮する](https://zenn.dev/i9wa4/articles/2026-01-01-zsh-startup-optimization-zinit) にて同一構成 (compinit + mise + zeno.zsh) での turbo mode 適用が報告されている。

## Decision

zinit の turbo mode サブスロット (`wait'0a'`, `wait'0b'`, `wait'0c'`) を使い、
依存順序を保ちつつプラグインを遅延ロードする。

### 変更方針

### 変更方針 (最終案)

**即時ロード (同期):**
- zinit 本体の初期化
- pure プロンプト
- **mise activate** (プロンプトと fzf に必要な環境変数のため)
- **zeno.zsh 本体の初期化** (プロンプト表示に直結するため)

**Turbo 遅延ロード:**

| サブスロット | コンポーネント | 理由 |
|------------|--------------|------|
| `wait'0a'` | compinit | 補完の基盤 (最も重い) |
| `wait'0b'` | zsh-completions | 補完定義 |
| `wait'0b'` | **fzf-tab** | `autosuggestions` 等より前に読み込む必要あり |
| `wait'0c'` | zsh-autosuggestions | 補完後 |
| `wait'0c'` | fast-syntax-highlighting | 順序不問 |
| `wait'0e'` | Docker 系 / ohmyzsh git | 使用頻度低 |

### compinit の最適化
- `compinit -C` を使用し `.zcompdump` キャッシュ利用 (compaudit スキップ)
- 2回目の compinit 呼び出しを排除

## Consequences

### Positive
- 起動時間の劇的な短縮 (~0.55s)
- プロンプトが即座に表示され、初期表示の崩れがない (先頭 `>` の欠損防止)
- fzf 予測タブのレイアウトが正しく適用される

### Negative
- 特に重い `compinit` によるボトルネックは解消できたが、`mise`(50ms) と `zeno`(5ms) を同期に残した分、理論上の最速値 (~0.45s) からわずかに後退 (~0.55s) した。
- turbo mode のデバッグが難しい (タイミング依存の不具合)

### レッスン
- プロンプトフックに依存するプラグイン (今回は `zeno` と、その必須環境である `mise`) はプロンプトより前に同期で評価する必要がある。
- スタイルを変更するプラグイン (`fzf-tab`) を用いる場合は、他の UI 変更系プラグイン (`zsh-autosuggestions`) との相対順序が壊れないように `wait` スロットのアルファベット順を前倒しする必要がある。
