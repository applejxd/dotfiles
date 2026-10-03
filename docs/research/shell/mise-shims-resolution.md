# 非対話シェルで mise の shims を PATH に足したときのツール解決

<!-- 現在の総合判断は docs/change/ の候補比較表が正本。
     ここは「いつ何を観測したか」を積む場所 -->

## 記録 E1 — 2026-10-03

- **対象バージョン**: mise 2026.9.18（linux-x64）、python 3.11.11 / 3.12.11 / 3.13.6
- **環境**: WSL2 Ubuntu（Linux 6.6.87.2-microsoft-standard-WSL2）。基準コミット 09abaed。
  グローバル設定 `~/.config/mise/config.toml` は `python = latest`（= 3.13.6）
- 一次情報: <https://mise.jdx.dev/dev-tools/shims.html>（未参照。本記録は実測のみ）

### 問い

AI エージェントのシェルツールは `/usr/bin/zsh` を非対話・TTY 無しで起動し `.zshenv`
だけを読む。`mise activate` は効かないので、`~/.local/share/mise/shims` を PATH に足せば
mise のツールが使えるか。足したとき、**どの版が選ばれるか**、PATH のどこに置くべきか、
重複や venv とどう干渉するか。

### 結論（先に）

| 観測 | 結果 |
| --- | --- |
| 最小 PATH（shims 先頭）で版指定の違う 2 ディレクトリ | **cwd の `mise.toml` に従う**（3.11.11 / 3.12.11） |
| `mise activate` 済みシェルの PATH を継承して別ディレクトリで実行 | **activate した時点の版に固定**（3.13.6）。cwd の指定は無視される |
| 継承した PATH の**先頭**へ shims を足す | cwd に従う（3.11.11 / 3.12.11） |
| 継承した PATH の**末尾**へ shims を足す | 継承した版が勝つ（3.13.6）。shims は効かない |
| 未 trust の設定がある cwd | shim は **エラー終了（rc=1）。待ちは無い**（0.04 秒） |
| venv の `bin` が先頭、shims が後ろ | venv の `python` が勝つ。shims の重複は結果を変えない |
| shims が venv の**前** | shim が勝ち、venv は無視される |
| 1 回の起動コスト | shim 経由は約 40 ms、実体直呼びは約 3.5 ms |

→ **shims は PATH の先頭側ではなく「活性化済みの PATH より前」に置くと cwd の版に従う。
末尾に置くと「継承した版」が勝つ。** venv を使う作業は venv の `bin` が先頭なら壊れない。
どの版が選ばれたかを保証したいときは `mise exec` を使う（shim は cwd の設定に依存するため）。

### 方法・条件

`.tmp/research-mise/{a,b,c}/mise.toml` に `python = "3.11.11"`（a）・`"3.12.11"`（b, c）を置き
`mise trust` 済みの状態で比較した（インストール済みの版だけ。ネットワークなし）。

### 結果

#### a. 最小 PATH

```console
$ cd a; timeout 20 env -i HOME=$HOME PATH=$HOME/.local/share/mise/shims:/usr/bin:/bin sh -c 'which python; python --version'
/home/applejxd/.local/share/mise/shims/python
Python 3.11.11
$ cd b; (同上)
/home/applejxd/.local/share/mise/shims/python
Python 3.12.11
```

`which` は両方とも shim を指し、版は cwd ごとに変わった。

#### b. `mise activate` 済みの PATH を継承

`zsh -i -c 'echo $PATH'` を chezmoi リポジトリ内で取り出して保存し、別ディレクトリで
`env PATH=<保存した PATH> sh -c 'which python; python --version'` を実行した。
保存した PATH（84 要素）には `~/.local/share/mise/installs/<tool>/<ver>/bin` が並び、
`installs/python/latest/bin` が 29 番目、shims（`~/.local/share/mise/shims`）が
43 番目に**既に入っていた**（`tr : '\n' < path.txt | grep -n` で確認）。
つまり対話シェルの PATH では shims が活性化した `bin` より後ろにある。

```console
$ (a, b それぞれで) env HOME=$HOME PATH="<保存した PATH>" sh -c 'which python; python --version'
/home/applejxd/.local/share/mise/installs/python/latest/bin/python
Python 3.13.6
/home/applejxd/.local/share/mise/installs/python/latest/bin/python
Python 3.13.6
```

継承した PATH はグローバル設定の `latest`（3.13.6）を指し、a / b の指定を**無視した**。
対照として、同じ a / b で `zsh -i -c "cd <dir>; which python; python --version"` を
実行すると、activate の hook が cwd の版へ切り替えた（3.11.11 / 3.12.11、実体は
`installs/python/<ver>/bin/python`）。

#### c. activate 済み PATH に shims も足す

（保存した PATH は元から 43 番目に shims を持つ。ここでは先頭／末尾への追加の効果を見た）

```console
$ PATH="$HOME/.local/share/mise/shims:<保存した PATH>"   # 先頭
/home/applejxd/.local/share/mise/shims/python   Python 3.11.11 (a) / 3.12.11 (b)
$ PATH="<保存した PATH>:$HOME/.local/share/mise/shims"   # 末尾
/home/applejxd/.local/share/mise/installs/python/latest/bin/python   Python 3.13.6 (a, b とも)
```

#### d. 未 trust の設定

`MISE_STATE_DIR` を空のディレクトリへ向けて trust 状態を空にし、shim を呼んだ。
trust 判定は設定ファイル単位で、cwd の祖先（リポジトリ直下の `mise.toml`）で止まった。

```console
$ env -i HOME=$HOME PATH=$HOME/.local/share/mise/shims:/usr/bin:/bin MISE_STATE_DIR=... sh -c 'which python; python --version; echo rc=$?' </dev/null
/home/applejxd/.local/share/mise/shims/python
mise ERROR error parsing config file: ~/.local/share/chezmoi/mise.toml
mise ERROR Config files in ~/.local/share/chezmoi/mise.toml are not trusted.
Trust them with `mise trust`. ...
rc=1
```

- 所要は 0.04 秒。**対話の確認待ちは無い**（`</dev/null`、TTY 無し）。`timeout` は発動しなかった
- 同じ状態で `mise activate` 済みの `zsh -i` も同じエラーを出し、`python --version` は rc=1
- 未 trust のリポジトリでは、shim 経由のツールが**黙って別の版にならず、エラーで止まる**

#### e. 重複と venv

`b` に venv（`python -m venv`。作成に使った python は 3.12.11）を作り、`VIRTUAL_ENV` 付きで
`which python` / `which pip` を見た。

| PATH の順 | `which python` | `which pip` |
| --- | --- | --- |
| venv, shims | venv | venv |
| shims, venv | **shim** | **shim** |
| venv, shims, shims（重複） | venv | venv |
| shims, venv, shims | **shim** | **shim** |

- shims の重複は解決結果に影響しない（先頭に近い方が効く）。**venv が勝つかは「venv が最初の
  shims より前か」だけで決まる**
- venv が先頭なら、3.11 の cwd（a）でも venv の python（3.12.11）が選ばれた

#### 速度

```console
for i in 1..10; do env -i PATH=$S:/usr/bin python --version; done   # 0.397 s（約 40 ms/回）
for i in 1..10; do $HOME/.local/share/mise/installs/python/3.12.11/bin/python --version; done   # 0.035 s
```

shim は `~/.local/bin/mise` へのシンボリックリンクで、毎回 mise が設定を解いて実体へ exec する。
`env -i PATH=...shims:/usr/bin` でも動いたので、`mise` が PATH に無くても shim 自体は動く
（ただし `mise exec` は PATH に `mise` が要る: `env: 'mise': そのようなファイルやディレクトリはありません`）。

### 考察

- **推測**: shims を PATH の**先頭**へ足す方式なら、非対話シェルでも cwd の `mise.toml` に従う。
  ただし venv を先頭に置く運用（`.venv/bin` が `activate` で先頭へ入る）では、venv が
  後から先頭へ来るので壊れない。`.zshenv` で足す位置は、`activate` を使わない非対話シェルでは
  「他のユーザー PATH の前」でよい
- 重複防止は `case ":$PATH:" in *":$S:"*) ;; *) PATH="$S:$PATH" ;; esac` の形で足りる
  （本記録では未実装・未検証。重複しても結果は変わらないことだけ実測した）
- 対話シェル（`activate` 済み）で `.zshenv` が先頭へ shims を足すと、対話では
  `activate` が自前の PATH を先頭へ置くので shim は後ろへ回る（**未検証**）
- shim の 40 ms は、エージェントが短い呼び出しを大量に繰り返す場面では効く（推測）
- 版の再現性が要る操作（lint・ビルド・CI 相当）は `mise exec` か実体の絶対パスを使う
  （cwd の設定に依存せず、未 trust でも `mise exec` のエラーで明確に止まる。
  `mise exec` 側の未 trust の挙動は未測定）

### 次の問い

- `.zshenv` の実際の実装後に、`zsh -c`（非対話）で shims が先頭に来るかと、重複しないかを測る
- `mise exec` の未 trust 時の挙動と、`mise.toml` の `[env]` / `_.path` が shim 経由でも効くか
- bash（`.bash_profile` は login のみ読まれる）経由の非対話起動での PATH

### 参照

- 構成の正本: [構成](../../spec/structure.md)
- 関連: [エージェントの git 入力待ち対策](../agents/noninteractive-git-env.md)

[調査記録一覧へ戻る](../../index.md)
