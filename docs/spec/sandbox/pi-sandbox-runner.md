# pi-sandbox-runner（pi の sandbox 拡張に GPU などを足す runner）

pi の sandbox 拡張 `@yuru7/pi-sandbox` の `runnerCommand` に差す、設定つきのラッパー。bash の実行を包む bwrap の引数に、GPU のデバイス・秘密の隠蔽・docker の遮断・git の hooks/config の保護を足す。
採用の判断は [ADR-0035](../../adr/0035-pi-sandbox-gpu-runner.md)、実機の比較は [調査記録](../../research/agents/pi-gpu-sandbox-2026-11.md)。Linux（Ubuntu / WSL）専用。

## 位置づけ

- **ツール単位の sandbox**。pi 本体（と LLM の認証）は外側で動き、エージェントが実行する bash だけを bwrap の内側へ入れる。`write` / `edit` の防護は、拡張がプロセス内で行う。
- `pis`（pi 全体を Fence で包む。凍結。[ADR-0030](../../adr/0030-freeze-agent-stack-return-to-stock-pi.md)）とは別物。守りの強さは「うっかり防止」（悪意への耐性は求めない）。
- 隔離の単位を環境にする方針（[ADR-0027](../../adr/0027-isolation-unit-is-environment.md)）の代わりではない。docker・compose を内側で使う開発は、ここでは扱わない（docker を塞ぐ）。

## 部品

| 部品 | 置き場（source state） | 配備先 |
| --- | --- | --- |
| runner | `home/dot_local/bin/executable_pi-sandbox-runner` | `~/.local/bin/pi-sandbox-runner` |
| 設定 | `home/dot_config/pi-sandbox/runner.toml` | `~/.config/pi-sandbox/runner.toml` |
| 拡張の設定 | `home/dot_pi/agent/create_pi-sandbox.json.tmpl` | `~/.pi/agent/pi-sandbox.json`（無いときだけ作る） |
| 実機の確認 | `scripts/pi_sandbox_selftest.py` | `python3 scripts/pi_sandbox_selftest.py`（リポジトリ直下で実行） |
| 試験 | `test/test_pi_sandbox_runner.py` | — |

Linux 以外へは配らない（`.chezmoiignore.tmpl`）。拡張の package 自体は `pi-stock-packages` に入れていない（全機・全セッションの既定を変えるため。[ADR-0035](../../adr/0035-pi-sandbox-gpu-runner.md#決定)）。

## 契約

拡張は、`runnerCommand` を、自身の bwrap の引数の先頭に付けて呼ぶ（`@yuru7/pi-sandbox` 0.5.0 の `confine.ts` の `[...runnerCommand, ...bwrapProfileArgs, "--", ...argv]`）。

```text
pi-sandbox-runner <bwrap の引数...> -- <コマンド...>
```

runner は、**最初の `--` の直前**に次を足して `bwrap` を exec する。**並びはコードに固定**で、設定では変えられない。

| 順 | 足すもの | 条件 |
| --- | --- | --- |
| 1 | GPU のデバイスを `--dev-bind`（`auto` は `/dev/dxg`・`/dev/nvidia*` のうち存在するもの） | `gpu.devices` |
| 2 | 書き込み可で渡る git ディレクトリ（`--bind A A`。A または `A/.git` が git ディレクトリのもの）の、**存在する** `hooks`・`config`・`config.worktree` を `--ro-bind` | `git.protect` |
| 3 | 隠す場所: ディレクトリは `--tmpfs`、ファイルは `--ro-bind /dev/null`（無ければ何もしない。シンボリックリンクは解決した実体で覆う） | `hide.dirs` / `hide.files` |
| 4 | `/run/user/<uid>`（rootless の docker・podman のソケット）を空の tmpfs で覆い、`/run/docker.sock` と `/var/run/docker.sock` を `/dev/null` で覆う | `docker.block` |

- **GPU を後ろに置く理由**: 拡張の `--dev /dev` は /dev を作り直す。その前に `--dev-bind` を置くと隠れる（[実測](../../research/agents/pi-gpu-sandbox-2026-11.md#gpu-の通し方)）。通常の `--bind` は nodev で、デバイスを開けない。
- **隠蔽を git の後ろに置く理由**: 後から重ねた mount が勝つ。隠す場所（例: `.git` 全体）の中に git の保護の bind があっても、再び見えない。
- **シンボリックリンクを解決する理由**: リンクのままだと bwrap が `Can't mount ... No such file or directory` で失敗し、すべての bash が止まる（実測）。
- **git の保護**: `@yuru7/pi-sandbox` は、worktree の commit のために `gitdir` と `commondir` を書き込み可にする。そのままだと、`hooks` や `config`（`core.hooksPath`・`core.fsmonitor` など）を書き換えて、ホストの git に実行させられる。

## 設定（`runner.toml`）

利用者の階層（`$XDG_CONFIG_HOME/pi-sandbox/runner.toml`、無ければ `~/.config/pi-sandbox/runner.toml`）だけを読む。**作業ツリーの中の設定は読まない**（エージェントが書き換えられるため）。

```toml
version = 1
[gpu]
devices = ["auto"]          # "auto" か /dev/ 以下の絶対パス。無効にするなら []
[hide]
dirs  = ["~/.ssh", "~/.config/gh"]   # 空の tmpfs で覆う
files = ["~/.netrc", "~/.pi/agent/auth.json"]   # /dev/null で覆う
[docker]
block = true                # compose を内側で使うときだけ false
[git]
protect = true
```

- 設定にするのは、リストとオン・オフだけ。任意の追加引数（`extra_args`）は作らない（抜け道になる）。
- **検証は厳格**: `version = 1`（整数。`true`・`1.0` は不可）が必須。未知のキー・型の誤り・`gpu.devices` の `/dev/` 以外・`hide` の相対パスや `/`・`~/` そのものは、エラー。
- **fail-closed**: 設定が無い・読めない（UTF-8 でない場合を含む）・壊れている・`--` が無いときは、bwrap を起動せず終了コード 2。エラーは `pi-sandbox-runner:` で始める。bwrap が無いときは 127。
- 環境変数（試験・調査用）: `PI_SANDBOX_RUNNER_CONFIG`（設定の場所）、`PI_SANDBOX_RUNNER_DRYRUN=1`（exec せずに最終の引数を JSON で出す）。

## 導入と確認

1. `chezmoi apply` で、上の部品が配備される（`pi-sandbox.json` は無いときだけ作る。既にあるなら、`runnerCommand` と `runnerFailureSignatures` を手で足す）。
2. 拡張を入れる: `pi install npm:@yuru7/pi-sandbox@0.5.0`（版は固定する）。
3. `python3 scripts/pi_sandbox_selftest.py` で、書き込み・秘密の隠蔽・docker の遮断・git の保護・GPU の CUDA カーネルを内側から確かめる（GPU が無い機は SKIP）。
4. pi の中で `/permission` を開き、runner が `custom` になっていることを見る（コードでは `runnerCommand` があると `custom` を返す。画面の表示は未確認）。

`pi-sandbox.json` の `runnerFailureSignatures` に `pi-sandbox-runner:` と `bwrap:` を置く（`runnerCommand` と対で必須）。これで runner 自身の失敗が、コマンドの失敗ではなく sandbox の失敗として扱われる。

## 版の固定と更新

runner は、拡張が `<runner> <引数> -- <コマンド>` の形で呼ぶことと、bwrap の引数の中で `--dev /dev` が `--` より前にあることに依存する。拡張の内部の並びで、公開の契約ではない。**更新で GPU が黙って使えなくなる**ことがある。

1. 版は `npm:@yuru7/pi-sandbox@<版>` で固定する。
2. 更新前に、変更履歴と、`src/runners.ts` の `bwrapProfileArgs`・`src/confine.ts` の `runnerCommand` の組み立てを読み、並びが同じか確かめる。
3. `python3 scripts/pi_sandbox_selftest.py`（拡張 0.5.0 の引数の再現で確認）に加えて、**実拡張でも確かめる**: 使い捨ての作業ディレクトリで、`PI_CODING_AGENT_DIR` に `pi-sandbox.json` を置いた一時の場所を指すか、配備した設定のまま、`pi -p` で「`sh ./probe.sh` を 1 回実行して出力を返す」を依頼し、GPU・docker・hooks を見る。
4. 試験（`test/test_pi_sandbox_runner.py`）の「GPU は `--dev /dev` の後」の引数は 0.5.0 のものを写している。拡張の並びが変わったら、試験も直す。

## 認証情報の扱い

隠すのは、`runner.toml` の `hide` に書いた場所だけ（既定の一覧は設定の本文）。観測は 2026-11-12、WSL2。

| 認証情報 | sandbox の内側 | 確認 |
| --- | --- | --- |
| pi の LLM 認証（`~/.pi/agent/auth.json` など） | 隠れる（`/dev/null`）。pi 本体は外側で動くので使える | 実拡張で確認 |
| gh（`~/.config/gh`） | 隠れる。内側の `gh auth status` は「未ログイン」（ホストではログイン済み） | 実測 |
| aws（`~/.aws`） | 隠す設定。この機は aws CLI が無く、`~/.aws` も空のため、動作は未確認 | 設定のみ |
| ssh 鍵（`~/.ssh`） | 隠れる（空に見える）。SSH 経由の git は内側で使えない。`/tmp` にある ssh-agent のソケットには届きうる（未確認） | 実測（鍵）／未確認（agent） |
| 環境変数の鍵（`GH_TOKEN`・`AWS_*` など） | **隠れない**（runner は環境を引き継ぐ） | 仕様。この機では未設定を確認 |
| `~/.gitconfig`・`~/.npmrc` | 隠していない（`~/.gitconfig` は読めることを実測） | 実測／未測定 |

- **隠れるのは bash の内側だけ。** pi の `read` ツール（拡張がプロセス内で動かす）は sandbox の外。秘密のパスを読ませない役は、`pi-permission-system` の path ルールが担う（bash での拒否は確認済み。`read` ツールでの拒否は未確認）。
- **通信は無制限**なので、内側から見えるものは外へ出せる。
- **内側で gh・aws が要るとき**:
  1. **外側で実行する。** 拡張の昇格（`danger-full-access`。承認は既定で別モデルの自動レビュー）か、利用者が打つ `!gh ...`。昇格した 1 コマンドは丸ごと sandbox の外で動く。
  2. **権限を絞った短命のトークンを環境変数で渡す。** 内側から見える前提で、読み取り専用・短期にする（[ADR-0028](../../adr/0028-per-repo-agent-container.md) の「長期の認証情報は入れない」と同じ方針）。
  3. **`hide` から外す。** 読めて通信も開いているので、鍵を持ち出せる。
- **既定は `~/.config/gh` を隠す。** 代わりに、gh の操作は外側で行う（既存の運用「gh は gh コマンドで、変更系は確認」とは、内側では常に失敗する点でぶつかる）。`pi-permission-modes` は既定で gh を隠しておらず、通信の許可リストに GitHub があるため、トークンの持ち出し経路になる（[調査記録](../../research/agents/pi-gpu-sandbox-2026-11.md#結果)）。

## 保証しないこと・限界

- **通信は無制限**（`pi-permission-modes` の許可リストのようには絞らない）。内側から鍵以外の情報を外へ出せる。
- **docker を塞ぐので、compose は内側で使えない。** docker 経由で書き込み制限を破れるため（[実測](../../research/agents/pi-gpu-sandbox-2026-11.md#発見)）。塞ぐのは `/run/user/<uid>` と、`/run/docker.sock`・`/var/run/docker.sock` だけ。ほかの場所のソケット（rootful の podman・containerd など）と、ネットワーク越しの `DOCKER_HOST`（tcp）は塞げない。
- **GPU のデバイスをさらす**ため、内側のコードにドライバの入口が開く（攻撃面は広がる。推測）。GPU の使用を制限する機能はない。
- `/tmp` はホストと共有（拡張の仕様）。
- **git の保護は限定的**:
  - 覆えるのは**既存**の `hooks`・`config`・`config.worktree` だけ。`hooks` が無いリポジトリや、`extensions.worktreeConfig` が有効で `config.worktree` がまだ無いリポジトリでは、内側から新規に作れる（ホストの git が後で実行・解釈する）。
  - `core.hooksPath` が作業ツリーの中を指すときは、その先は書き込み可。`info/`・`modules/`・ネストしたリポジトリ・サブモジュールは対象外（`A` と `A/.git` だけ）。
- **環境変数に入った鍵は隠さない**（runner は環境を引き継いで exec する）。隠すのはファイルとディレクトリだけ。
- 隠したファイルは、内側から開くと権限エラーになる（空のファイルには見えない）。
- 隠すのは、設定に書いた場所だけ。`~/.config/gh` を隠すと、内側で `gh` が使えない（外側で実行する）。`~/.npmrc` などは既定では隠していない。
- 拡張の `!command`（利用者が打つもの）と、拡張の昇格（`danger-full-access`）は、sandbox の外で動く。
- 拡張は 0.x の個人製。版を固定し、更新で確かめる。

## 試験

- `uv run --with pytest --no-project pytest test/test_pi_sandbox_runner.py -q`: 設定の検証・引数の組み立て（GPU は `--dev /dev` の後、隠蔽は git の後）・CLI の fail-closed・実際の bwrap（使える環境だけ）での隠蔽（シンボリックリンクと、隠した `.git` を含む）と git の保護。CLI と実 bwrap の試験は Linux 以外では skip する（runner は `os.getuid()` と bwrap を使う）。
- `python3 scripts/pi_sandbox_selftest.py`: 実機の確認（上の「導入と確認」）。
