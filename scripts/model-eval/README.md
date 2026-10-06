# model-eval

OpenCode の階層 `routine`（`commit`）と `worker`（`fleet-worker`）に当てるモデルを、
同じ条件で比べるための計測の道具。見直しの手順と判断の目安は
[モデルの割り当ての見直し](../../docs/spec/model-lineup-review.md)、これまでの結果と方法の経緯は
[階層のモデルの計測](../../docs/research/opencode/tier-models.md)・
[commit / review エージェントの実機確認](../../docs/research/opencode/commit-review-agents.md)（記録 E3〜E6）・
[作業役への指示の計測](../../docs/research/opencode/fleet-worker-instructions.md)にある。

> **`routine/` は今は動かない。** 前提の `commit` エージェントを 2026-10-07 に廃止した
> （[コミットの確認](../../docs/spec/agent-config-generation.md#コミットの確認)）。下の `routine` の例は
> 旧版用の手順として残している。`routine` に割り当て先ができたら課題を作り直す。

```text
scripts/model-eval/
├── gen_config.py      # 計測用の設定を作る（階層・エージェントのモデルを差し替える）
├── probe-guide/       # 計装した guide plugin の外側（中身は gen_config.py が複製する）
├── run_isolated.sh    # 1 回の隔離実行（routine / worker 共通）
├── seed_db.py         # 実 DB の複製と、集計用の書き出し
├── batch.sh           # ジョブの一覧を並行に回す
├── env.sh             # 出力先 EVAL_OUT を決める
├── evallib.py         # 集計の共通部分（呼び出しの分類・トークン・単価の試算）
├── routine/           # mkscn.sh（作業用リポジトリ 5 種類）・run.sh・analyze.py・prompts/
└── worker/            # base/（課題のリポジトリ）・briefs/・hidden/・solutions/・
                       # mkws.sh・run.sh・grade.py・selftest.py・analyze.py
```

## 前提

- Linux / WSL（`bash`・`timeout`・`git`・`python3`・`uv`・`chezmoi`・`opencode`）
- その PC の OpenCode で認証を済ませている（実 DB に資格情報がある）
- 設定の生成は `test/agents/agents_common.py` を使うので pytest が要る
  （`uv run --no-project --with pytest --with pyyaml python ...`）

## 隔離の仕組み

- 実 DB（`$EVAL_SOURCE_DB`、既定は `~/.local/share/opencode/opencode.db`）を読み取り専用で複製し、
  セッションの表を空にしたものを `OPENCODE_DB` に渡す。**この複製は資格情報を含む。**
  `run_isolated.sh` は実行が終わると `session_v2` と `session_message` だけを `sessions.json` に
  書き出し、複製を消す（途中で止めても消す）。強制終了などで残ったら消しておく:
  `find "$EVAL_OUT" -name 'seed.db*' -delete`
- 実行ごとに一時の `XDG_DATA_HOME` / `XDG_STATE_HOME` / `XDG_CACHE_HOME` / `TMPDIR`、組ごとに
  `OPENCODE_CONFIG_DIR`。`OPENCODE_CONFIG` / `OPENCODE_CONFIG_CONTENT` は外す
- `opencode run --standalone --auto --format json` で、常駐サービスを使わない。
  `session.synthetic` は使わない
- 計装: plugin は `probe-guide/` だけにする。`permission.evaluate` とツールの実行の前後を
  `events.ndjson` に書く。shell の `ask` は承認した扱い、危ない形（`rm` / `git reset` など）は
  拒否した扱い。`PROBE_APPROVE_ALL=1`（worker の既定）なら shell 以外の `ask` も承認した扱い
- 出力先は `$EVAL_OUT`（既定は `.tmp/model-eval/`。git に入らない）。リポジトリの中なら
  `.tmp/` の下でないと止まる

## 回し方

```bash
cd scripts/model-eval
export EVAL_OUT="$(git rev-parse --show-toplevel)/.tmp/model-eval"   # 既定と同じ。集計の glob で使う
py() { uv run -q --no-project --with pytest --with pyyaml python "$@"; }

# 0. 採点の自己テスト（課題や隠しテストを直したら必ず）。モデルは呼ばない
py worker/selftest.py

# 1. 設定を作る。--tier で階層のモデルを差し替える（書き方は common.toml と同じ）
py gen_config.py ws-low --tier worker='claude-sonnet-5.5#low'
py gen_config.py rs-low --tier routine='claude-sonnet-5.5#low'
#    評価したい版が別の作業ツリーにあるなら --repo、エージェントを直接なら --agent commit=<provider/model>

# 2. 1 回ずつ回す（出力は $EVAL_OUT/runs/<routine|worker>/<組>-<課題>-<回>）
bash worker/run.sh ws-low bugfix 1        # 課題: feature bugfix refactor tests multi semver ini
bash routine/run.sh rs-low multi 1        # 作業用リポジトリ: multi new delete long newdir
bash routine/run.sh -p routine/prompts/approved-long.txt -l rs-low-ap rs-low long 1  # 承認済みの全文を渡す

# まとめて回す。1 行 1 実行で「<routine|worker> <run.sh の引数>」。-s で順を混ぜる
bash batch.sh -j 5 -s "$EVAL_OUT/jobs.txt"

# 3. 集計（Markdown の表）。組は <組>=<glob>、省略時はディレクトリ名の <組> でまとめる
py worker/analyze.py --prices "$EVAL_OUT/models-dev.json" --json "$EVAL_OUT/worker.json"
py routine/analyze.py "medium=$EVAL_OUT/runs/routine/rs-medium-*" "low=$EVAL_OUT/runs/routine/rs-low-*"
```

- `worker/run.sh` は初回に `$EVAL_OUT/venv`（pytest 9.1.1。`EVAL_PYTEST_VERSION` で変える）を作り、
  課題のリポジトリの `.venv` にリンクする。終わると `grade.py` で採点する
- 時間切れは `EVAL_TIMEOUT`（秒。routine 1200・worker 1800）
- `--prices` は models.dev の `api.json`（`curl -so "$EVAL_OUT/models-dev.json" https://models.dev/api.json`）。
  渡すと、同じトークン数に `--price-provider`（既定 `amazon-bedrock`）の単価を掛けた試算の列を出す。
  Copilot の ID は `global.anthropic.` を付けて読み替える（`--price-prefix`）
- 表の各列の意味と数え方は [測る項目](../../docs/spec/model-lineup-review.md#測る項目)

1 回の実行ディレクトリに残るもの: `ws/`（作業用リポジトリ）・`prompt.txt`・`events.ndjson`・
`sessions.json`・`out.ndjson` / `err.log`・`tmp-files.txt`・`wall.txt`、worker は加えて `diff.patch`・
`grade.json`、routine は `log.txt` / `raw.txt`（コミットメッセージ）・`status.txt`。

## Bedrock の PC で回すとき

- **課金される。** 1 本回して結果を確かめてから `batch.sh` を使う
- プロバイダは common.toml の判定（ユーザ名）で決まる。`gen_config.py` の出力に出る
  `provider` が `amazon-bedrock` になっているかを見る。モデルは Bedrock の ID で書く
  （例: `--tier worker='global.anthropic.claude-sonnet-5-5#low'`）。その ID に variant が付けられるかは、
  1 本回して `err.log` と `sessions.json` のモデルで確かめる
- AWS の資格情報は DB の外（`~/.aws` のプロファイル）から来るので、実 DB の `credential` が空なら
  `EVAL_ALLOW_NO_CREDENTIAL=1` を付ける
- `sessions.json` の費用（`session_v2.cost`）は OpenCode の単価表による値。試算の列と比べるなら
  `--prices` を同じ models.dev の取得分にそろえる
