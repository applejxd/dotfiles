# 開発環境（C++・VS Code）

C++ の単一ファイル実行（`runcpp`）、VS Code の拡張、コーディング試験の練習用 VS Code（`code-exam`）。全体の構成は [プロジェクト構造](structure.md)。

## C++ の単一ファイル実行（runcpp）

コーディング試験・競技プログラミングの問題を解くための関数（`functions/cpp.sh`）。
1 ファイルをコンパイルして実行する。zsh では suffix alias（`60_suffix_alias.zsh.tmpl`）で
`.c` / `.cc` / `.cpp` を打つと呼ばれる。

```text
runcpp [オプション] <src.cpp> [オプション] [-- プログラム引数...]
```

| オプション | 意味 |
| --- | --- |
| `-d` / `--debug` | 間違いを見つけるモード（既定） |
| `-r` / `--release` | 提出環境に近いモード。速度の確認用 |
| `-c` / `--compile-only` | コンパイルだけ（警告の確認） |
| `-t` / `--time` | 実行時間を表示 |
| `--std=STD` | 言語規格（既定 `gnu++20`） |

| 環境変数 | 意味 |
| --- | --- |
| `RUNCPP_MODE` | オプションが無いときのモード（`debug` / `release`） |
| `RUNCPP_CXX` | コンパイラ（既定 `g++`。macOS では最新の `g++-N`） |
| `RUNCPP_STD` | `--std` の既定値 |
| `RUNCPP_FLAGS` | 追加フラグ（例 `-I$HOME/ac-library`）。空白で分割する |

suffix alias での使い方:

```zsh
a.cpp < in1.txt                # debug
a.cpp -r -t < big.txt          # release で時間計測
RUNCPP_MODE=release a.cpp      # 環境変数でも切り替えられる
a.cpp -- foo                   # プログラムに引数を渡す
```

設計:

- `--` より前は位置を問わず runcpp のオプションとして読む。suffix alias では
  `a.cpp -r` が `runcpp a.cpp -r` に展開されるため、ソースの後ろにも書けないと
  モードを切り替えられない。`--` の前に置いたオプションでない語もプログラム引数になる
- suffix alias はコマンド位置の語にしか効かない。`./a.cpp` ではなく `a.cpp` と打つ
- バイナリは `${XDG_CACHE_HOME:-~/.cache}/runcpp/<名前>-<モード>` に置く。
  作業ディレクトリを汚さず、debug と release を取り違えない。
  コンパイルに失敗したら実行しない（古いバイナリを動かさない）
- 実行はサブシェルで `ulimit -s 1048576`（1GiB。ハード上限が低ければその値）にする。
  深い再帰の DFS が手元だけでスタックオーバーフローするのを防ぐ

モードごとのフラグ:

| | debug | release |
| --- | --- | --- |
| 最適化 | `-O0 -g -fno-omit-frame-pointer` | `-O2` |
| 警告 | `-Wall -Wextra -Wshadow -Wformat=2 -Wfloat-equal -Wcast-qual`。gcc では `-Wduplicated-cond -Wlogical-op` も | `-Wall -Wextra` |
| 実行時検査 | `-fsanitize=address,undefined -fno-sanitize-recover=all` | なし |
| STL の検査 | `-D_GLIBCXX_DEBUG -D_GLIBCXX_DEBUG_PEDANTIC`（libstdc++）、`-D_LIBCPP_HARDENING_MODE=_LIBCPP_HARDENING_MODE_DEBUG`（libc++） | なし |
| マクロ | `-DLOCAL` | `-DONLINE_JUDGE` |

- `-Wconversion` は `int` と `size_t` の比較などで警告が大量に出るので入れない。
  `-Wpedantic` は `__int128` や可変長配列でも警告が出るので入れない。
  必要なら `RUNCPP_FLAGS` で足す
- release でも `NDEBUG` は付けない。AtCoder などのジャッジでも `assert` は有効なため
- `ulimit -s unlimited` にしない。スタックの上限を無制限にすると Linux がメモリ配置を
  旧方式（mmap を低位アドレスから割り当てる）に切り替え、ASan のシャドウ領域と重なって
  起動時に `Shadow memory range interleaves with an existing memory mapping` で
  落ちることがある（2026-10-06 に Ubuntu 24.04 / g++ 13.3 で観測）
- `-t` の分岐ではサブシェル内で `exec` しない。bash の `time ( exec cmd )` は
  時間を表示しない（同日に bash 5.2 で観測）
- macOS の `g++` は Apple clang で、`bits/stdc++.h` が無く `_GLIBCXX_DEBUG` も効かない。
  そのため Homebrew の `g++-N`（`brew "gcc"`）を探して使う。Apple Silicon の
  Homebrew gcc は sanitizer を使えない可能性があり、その場合は
  `RUNCPP_CXX=clang++` に切り替える（`bits/stdc++.h` は使えなくなる）。macOS 実機では未検証

検査は `test/test_shell_startup.py`（bash / zsh の両方で、release の実行、debug での
範囲外アクセスの検出、`--` 以降の引数、コンパイル失敗時に実行しないこと、不正な入力）。

## VS Code の拡張

拡張は chezmoi では入れない。拡張・設定・キーバインドの正本は VS Code の Settings Sync
（GitHub アカウント）に任せる。新しいマシンでは VS Code でサインインして同期を有効にする
（ブラウザでの認証が要るので自動化できない）。Remote-WSL 側（`~/.vscode-server`）に
拡張が反映されるかは環境により確認が要る（未確認）。

`coding-test` プロファイルは別で、その WSL 拡張だけ `347` が入れる
（[次節](#コーディング試験の練習用-vs-codecode-exam)）。

拡張導入スクリプト（旧 `112` / `340`）は廃止した（理由は [記録](../research/shell/structure-shell-notes.md)）。

## コーディング試験の練習用 VS Code（code-exam）

HackerRank 以外の問題（AtCoder や手元の問題集）を、本番に近い条件で解くための関数。
`applejxd` のときだけ `shellrc.sh` に定義する。当日の `~/coding-test/YYYY-MM-DD/` を作り、
拡張を切った専用プロファイル `coding-test` の VS Code で開く。

```sh
code --disable-extensions --profile coding-test ~/coding-test/YYYY-MM-DD
```

プロファイルは初回の起動で空のものが作られる。拡張もプロファイルごとなので、WSL では
初回に「リモート ウィンドウを開くには、拡張機能 'WSL' が必要です」と出て接続できない。
通知の「インストールして再度読み込む」では入らなかった（`--disable-extensions` 下のため
と思われる）。Windows 側の `chezmoi apply` が
`300_windows/run_after_347_vscode_coding_test.ps1.tmpl` で WSL 拡張をこのプロファイルへ
入れるので、初回は `code-exam` で一度開いてプロファイルを作り、Windows で
`chezmoi apply` してから開き直す。手で入れるなら Windows の PowerShell で次を実行する。

```powershell
code --profile coding-test --install-extension ms-vscode-remote.remote-wsl
```

このスクリプトは `applejxd` のときだけ中身を持つ。VS Code の CLI は存在しない
プロファイルを扱えない（`Profile 'coding-test' not found.`）ため、`storage.json` の
`userDataProfiles` にプロファイルが無いうちは何もしない。プロファイルを作った後の
apply で拾えるよう `run_onchange` ではなく `run_after` にしている。入れる設定は
WSL 拡張だけで、AI 機能のオフ（右下のメニューか `settings.json`）とフォルダーの
信頼は手で行う。

制限モードになったら親フォルダーの `~/coding-test` を信頼する。

設定は chezmoi で管理しないので、
初回だけ、そのウィンドウでコマンドパレットの **Preferences: Open User Settings (JSON)**
を開いて次を書く。補完をどこまで切るかは本番のエディタの設定に合わせる。

```jsonc
{
    "chat.disableAIFeatures": true,
    "editor.inlineSuggest.enabled": false,
    "editor.quickSuggestions": { "other": false, "comments": false, "strings": false },
    "editor.parameterHints.enabled": false
}
```

ビルドと実行は統合ターミナルの `runcpp` で行う（HackerRank の Run Code の代わり）。

設計:

- HackerRank 本番では外部エディタからの貼り付けやタブの切り替えが記録されるため、
  本番は HackerRank のエディタで解く。この関数は練習専用
  （[Test Integrity](https://support.hackerrank.com/articles/1079706165-proctoring-hackerrank-tests)）
- `--profile` で分ける（WSL からも渡る）。`--user-data-dir` で分ける案を採らない理由は [記録](../research/shell/structure-shell-notes.md)
- `--disable-extensions` でも、WSL への接続に使う拡張（resolver）は有効のまま残る
  （`extensionEnablementService.ts` の `_isDisabledInEnv`）。ただし例外になるのは
  プロファイルに入っている拡張だけなので、上の初回手順が要る。厳密には
  「接続用以外の拡張を無効化」である
- WSL 側の Machine 設定（`~/.vscode-server/data/Machine/settings.json`）は
  ふだんの VS Code と共有する

検査は `test/test_shell_startup.py`（bash / zsh の両方で、偽の `code` に渡る引数と
作業ディレクトリの作成、`applejxd` 以外では定義されないこと）。実際に VS Code が開くかは
検査しない。
