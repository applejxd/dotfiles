# pi の sandbox 拡張と GPU: 実機の比較（bubblewrap 系・Docker 系）

- **観測日**: 2026-11-11〜12
- **問い**: GPU を使う作業を、秘密を守りながら、pi の sandbox の中でできるか。どの方式が手軽か。
- **結論**: 調べた拡張のどれも、設定だけでは GPU を通せない。`@yuru7/pi-sandbox` の `runnerCommand` に小さなラッパーを差すと、GPU・docker の遮断・worktree の commit・hooks の保護が揃う。採用の判断は [ADR-0035](../../adr/0035-pi-sandbox-gpu-runner.md)、仕様は [pi-sandbox-runner](../../spec/sandbox/pi-sandbox-runner.md)。

## 環境と方法

| 項目 | 値 |
| --- | --- |
| OS | WSL2（kernel 6.18.58.1-microsoft-standard-WSL2）、Ubuntu 24.04.5 |
| bubblewrap / Docker | 0.9.0 / 29.9.2（rootless） |
| GPU | NVIDIA GeForce RTX 3070（WSL2 の `/dev/dxg`） |
| pi | 1.5.0（stock）。実拡張は `pi -p --no-session -ne -e <拡張> --perm build`（`@yuru7` は `--perm` なし）、モデルは `github-copilot/claude-sonnet-5.5`（thinking は low） |
| 対象の版 | `pi-safe`（`c154c00`、2026-06-12）、`@yuru7/pi-sandbox` 0.5.0、`pi-permission-modes` 2.7.2、`@trim21/personal-pi-extensions` 0.1.473、`pi-less-yolo`（`204a753`、2026-09-15。pi 0.85.1 を固定） |

- **共通のプローブ**: 使い捨ての git worktree（main と wt が兄弟）で、sandbox の内側から、cwd と HOME への書き込み・秘密の読み取り・通信（HTTP コードだけ）・docker・GPU・worktree での `git commit` を調べた。秘密は**中身を読まず**、可否だけ（マスクされた空ディレクトリや `/dev/null` を「読めた」と誤判定しないよう、非空かどうかで見る）。
- **GPU の確認**: `nvidia-smi -L` と、`ctypes` で書いた CUDA ドライバ API のカーネル（PTX を JIT して 1M 要素に 1 を足し、読み戻す。torch は要らない）。
- `pi-less-yolo` の実イメージのビルドは、`.asc` のファイルを `--secret` に渡す指定が Safety Net（`secret.ext.asc`）に止められ、していない。起動フラグだけを、手元の別イメージで試した。

## 結果

| 観点 | `pi-safe` | `@yuru7/pi-sandbox` | `pi-permission-modes`（build） | Docker（`pi-less-yolo` のフラグ） |
| --- | --- | --- | --- | --- |
| HOME への書き込み | 遮断 | 遮断（自動レビューが許可した 1 回だけ可） | 遮断（確認なしの実行では拒否） | コンテナの外には書けない |
| cwd への書き込み | 可 | 可 | 可 | `--user 0:0` に直せば可。そのままでは不可 |
| `auth.json` | 読める | 読める | `/dev/null` で隠れる | 読める（`~/.pi/agent` をマウント） |
| `~/.ssh` | 読める | 読める | 空で隠れる | マウントされない |
| `~/.config/gh` | 読める | 読める | **読める**（既定の `denyRead` に無い） | マウントされない |
| 通信 | 無制限 | 無制限 | 許可リスト（npm・PyPI・GitHub）。`example.com` は遮断 | 無制限 |
| docker | 使える（HOME に書けた） | 使える | ソケットは見えるが `docker ps` は不可 | 見えない |
| GPU | 失敗（`/dev/dxg` を足せば可） | 失敗 | 失敗（設定項目なし） | 既定なし。`--gpus all` で可 |
| worktree の `git commit` | 失敗（`.git` が読み取り専用） | 成功（`.git` 全体が書ける） | 成功 | cwd のみのマウントでは失敗。親ごとなら成功 |
| `/tmp` | 可 | 可 | 不可（専用の作業領域のみ） | 可 |
| 導入 | スクリプト 1 本 | `pi install` 1 回（依存 149 パッケージ） | `pi install` 1 回（依存 132 パッケージ） | Docker・mise・イメージのビルド（作者は約 2 分と記載。未測定） |
| 起動の追加時間 | bwrap 約 10 ms（`pi --version` は 213 → 230 ms） | 同程度（未測定） | 未測定 | `docker run` 1 回 約 460 ms |

`@yuru7/pi-sandbox` は、bwrap の引数をコードから再現した結果と、実拡張の結果がすべて一致した。

## 発見

1. **`pi-safe` からは、rootless Docker を介して HOME に書けた。** 内側から `docker run -v $HOME:/h ... touch` でファイルを作れた（作ったファイルは外側で削除し、残っていないことを確認）。「書けるのは cwd だけ」は、docker が使える環境では破れる。
2. **`pi-less-yolo` のフラグは、rootless Docker では cwd に書けない。** `--user $(id -u)` だと、コンテナ内の uid_map は `0 1000 1; 1 100000 65536`（ホストの自分が container root）で、cwd の所有者が `0:0` に見える。`--user 0:0` にすると書け、ホスト側の所有者も自分のままだった。認証は、`~/.pi/agent`（`auth.json` を含む）を書き込み可でマウントするため、内側から読める。
3. **`@yuru7/pi-sandbox` は、linked worktree の `gitdir` と `commondir` を書き込み可にする**ので、worktree で commit できる。代償に、`.git/hooks` へ実行ファイルを置ける（ホストの git が後で実行する経路）。
4. **`@yuru7/pi-sandbox` は、HOME への書き込みの昇格を、別モデルの自動レビューが許可する。** 最初の書き込みは拒否され、エージェントが `danger-full-access` と理由を付けて再試行し、レビューが ALLOW して 1 回だけ書けた（利用者が「そこに作れ」と指示した場合）。
5. **`pi-permission-modes` は、確認なしの実行では拒否で止まる。** 拒否文は「再試行や言い換えをせず、必要なら利用者に聞け」。対話での確認画面は未体験。
6. **Ubuntu 24.04 の AppArmor による bwrap の失敗は、この WSL2 では再現しなかった。** `kernel.apparmor_restrict_unprivileged_userns` の sysctl が存在せず、`pi-safe` は設定なしで動いた。

## GPU の通し方

| 構成 | CUDA カーネル |
| --- | --- |
| 隔離なし | 成功 |
| bwrap（`/dev/dxg` なし） | 失敗（`cuInit` が 100） |
| bwrap ＋ `--dev /dev` の後に `--dev-bind /dev/dxg /dev/dxg` | 成功 |
| bwrap ＋ `--dev-bind` を `--dev /dev` の**前**に置く | 失敗（`--dev /dev` が /dev を作り直して隠す） |
| rootless Docker の `--gpus all` | 成功 |

- 通常の `--bind` は nodev でマウントされ、デバイスを開けない。`--dev-bind` が要る。
- **`pi-permission-modes`** が使う sandbox-runtime は、`bwrapArgs.push('--dev', '/dev')` を固定で持ち、デバイスを足す設定項目がない（`/dev/*` のパスは「`--dev /dev` が扱う」として読み飛ばす）。
- **`@trim21/personal-pi-extensions`** は `extraArgs` を持つが、`--dev /dev` より**前**に置くため、`--dev-bind` が隠れて GPU が通らない（上の表の「前」の行と同じ結果を実測）。
- **`@yuru7/pi-sandbox`** は、`runnerCommand` を引数の先頭に付けて `<runner> <引数> -- <コマンド>` の形で呼ぶ。`--` の直前に `--dev-bind` を足すラッパーで、実拡張から GPU を通せた（`nvidia-smi` と CUDA カーネルの両方）。
- 他の 7 つ（`@erichll/pi-sandbox`、`pi-better-sandbox`、`@nqbao/pi-sandbox`、`@casualjim/pi-heimdall`、`pi-better-harness`、`pi-sandbox`〔carderne〕、`@yandy0725/pi-sandbox`）は、README とソースの検索で、GPU・デバイス・追加引数の記述が見つからなかった（全ソースの精読ではない）。

## 外部の事例（同じ手口が通例）

ラッパーで `--dev-bind` を注入する方法は、他のエージェントの sandbox でも使われている。本家の対応は未了。

- Claude Code の要望 [#13108](https://github.com/anthropics/claude-code/issues/13108)（2025-12-05 起票。取得時も Open）。
- Codex の不具合 [#19676](https://github.com/openai/codex/issues/19676)（`gpu_passthrough` の設定を提案）。
- Claude Code の sandbox 向けの GPU 対応ラッパー（[gist](https://gist.github.com/wassname/c1d2d99097f9a91bbff52b613658caff)）。
- `pearu/agent-sandbox` の PR #244（GPU を既定で通す）、`didvc/ai-bwrap` の PR #13（`--dev-bind` の追加。nodev で開けない問題を説明）。

## ssh.ts によるツール委譲の試験

pi をホストに置き、read・write・edit・bash の実行を別の環境へ送る構成（公式の例 `examples/extensions/ssh.ts`）を、使い捨てのコンテナで試した（2026-11-12）。

- **構成**: `debian:12` に openssh-server・python3 を入れたコンテナ（428 MB、ビルド 25 秒）。`--gpus all`、`127.0.0.1:2222` へ公開、プロジェクトを `/work` にマウント。`ssh.ts` は `host:port` を受け付けないので、PATH の `ssh` を、`-p 2222 -i <使い捨ての鍵>` を足す薄いラッパーに差し替えた。
- **結果**: `pi -p -e ssh.ts --ssh root@localhost:/work` で、
  - bash がコンテナの中で動いた（`ls -A ~` はコンテナのホーム。ホストの鍵は無い）。
  - CUDA カーネルが動いた（`kernel=ok`）。
  - read ツールが README を読み、write ツールが作った `NOTE.txt` が、ホスト側のプロジェクトに反映された（所有者はホストの自分）。
- **費用**: ssh 1 回（新規接続）が約 0.2 秒（10 回の平均 217 ms）。
- **制約**: `ssh.ts` は read・write・edit・bash の 4 つだけを差し替える（grep・find・ls と、他の拡張のツールはホスト）。プロジェクトを環境の中に置く手間（マウントか同期）と、worktree の `.git` の扱いが課題。

## `pi -e npm:` での起動（2026-11-12）

`pi -e npm:@yuru7/pi-sandbox@0.5.0` は、初回に拡張を自動で取得し（28 パッケージ、約 2 秒。起動まで 8 秒）、`~/.pi/agent/tmp/extensions/` にキャッシュする。2 回目は 5 秒。版を固定した指定は、再確認されない（pi 公式の packages の文書）。stock の拡張（`pi-permission-system`・`cc-safety-net` など）を残したままでも、HOME への書き込みが拒否された。

## 限界・未検証

- 対話での確認画面の使い勝手、`pi-permission-modes` の `default` モード（毎回確認）、サブエージェントとの併用は未検証。
- Incus は、`incus-admin` グループへの所属と sudo が要るため、実機では試していない。
- `pi-less-yolo` は、実イメージのビルドをしていない（上記）。
- 件数は、検索で見えた少数の例。Reddit の本文は取得できず、検索結果の抜粋に頼った。
