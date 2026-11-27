"""bash / zsh の機能を PowerShell へ取り入れた関数・設定の試験 (Windows。docs/spec/shell.md#bashzsh-と-powershell-の対応)。

関数は modules/ の小さなモジュールで、プロファイルの interactive.ps1 が PSModulePath へ足すと、初めて呼んだときに
自動で読み込まれる。試験は interactive.ps1 を dot-source して、本物と同じ経路 (自動読み込み) で呼ぶ。
外部の道具 (fzf・pi・sudo・bat・eza・gh) は、PATH の先頭に置く偽物で差し替え、渡した引数や標準入力を確かめる。
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows PowerShell")

ROOT = Path(__file__).resolve().parents[1]
POWERSHELL_DIR = ROOT / "home/dot_config/powershell"
INTERACTIVE = POWERSHELL_DIR / "commands/interactive.ps1"
CACHE = POWERSHELL_DIR / "cache.ps1"
PWSH = shutil.which("pwsh")

PRELUDE_HEAD = """
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)
"""
PRELUDE_TAIL = f""". '{CACHE}'
. '{INTERACTIVE}'
"""


def powershell(
    tmp_path: Path,
    body: str,
    *,
    env: dict[str, str] | None = None,
    cwd: Path | None = None,
    preload: str = "",
    as_command: bool = False,
):
    """interactive.ps1 を読み込んだ pwsh で body を実行する。返り値は (stdout の行, stderr, 終了コード)。

    as_command=True は、body を `-Command` の文字列として評価する。トップレベルのコマンドが「ホストから直接
    入力された」(CommandOrigin が Runspace) ものになり、auto_cd の対象になる。-File のスクリプトの中は Internal。
    """
    assert PWSH, "pwsh is not installed"
    stem = f"case-{abs(hash(body))}"
    prelude = tmp_path / f"{stem}-prelude.ps1"
    prelude.write_text(PRELUDE_HEAD + preload + PRELUDE_TAIL, encoding="utf-8-sig")
    if as_command:
        command = [PWSH, "-NoLogo", "-NoProfile", "-Command", f". '{prelude}'\n{body}"]
    else:
        script = tmp_path / f"{stem}.ps1"
        script.write_text(f". '{prelude}'\n{body}", encoding="utf-8-sig")
        command = [PWSH, "-NoLogo", "-NoProfile", "-File", str(script)]
    environment = dict(os.environ)
    environment.update(env or {})
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=cwd or tmp_path,
        env=environment,
        stdin=subprocess.DEVNULL,
        timeout=180,
    )
    return completed.stdout.replace("\r\n", "\n").splitlines(), completed.stderr, completed.returncode


def fake_tool(directory: Path, name: str, body: str) -> None:
    """PATH の先頭へ置く偽のコマンド (.cmd → pwsh の .ps1)。"""
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{name}.ps1").write_text(body, encoding="utf-8-sig")
    (directory / f"{name}.cmd").write_text(
        f'@pwsh -NoLogo -NoProfile -File "%~dp0{name}.ps1" %*\r\n', encoding="ascii"
    )


def with_path(directory: Path) -> dict[str, str]:
    return {"PATH": f"{directory}{os.pathsep}{os.environ['PATH']}"}


def path_without(*names: str) -> dict[str, str]:
    """指定した道具 (eza・bat など) が入っているディレクトリを除いた PATH。入っていない機と同じにする。"""
    kept = []
    for directory in os.environ["PATH"].split(os.pathsep):
        if any((Path(directory) / f"{name}{ext}").exists() for name in names for ext in (".exe", ".cmd", ".bat", ".com")):
            continue
        kept.append(directory)
    return {"PATH": os.pathsep.join(kept)}


# fzf の偽物: 標準入力の行のうち、FAKE_FZF_PICK (正規表現) に最初に一致した行を出す。
# FAKE_FZF_ONCE のファイルがあれば 2 回目は 130 (Esc) で終わる。--expect=ctrl-d のときは、先頭行に FAKE_FZF_KEY を出す
FAKE_FZF = r"""
$lines = @($input)
$args | Add-Content -LiteralPath "$env:FAKE_FZF_LOG" -ErrorAction Ignore
if ($env:FAKE_FZF_ONCE) {
  if (Test-Path -LiteralPath $env:FAKE_FZF_ONCE) { exit 130 }
  Set-Content -LiteralPath $env:FAKE_FZF_ONCE 'used'
}
$pick = $lines | Select-Object -First 1
if ($env:FAKE_FZF_PICK) {
  $pick = $lines | Where-Object { $_ -match $env:FAKE_FZF_PICK } | Select-Object -First 1
}
if (-not $pick) { exit 1 }
if ($args -contains '--expect=ctrl-d') { $env:FAKE_FZF_KEY }
$pick
"""


@pytest.fixture
def fakebin(tmp_path: Path) -> Path:
    directory = tmp_path / "fakebin"
    fake_tool(directory, "fzf", FAKE_FZF)
    return directory


def fzf_env(fakebin: Path, tmp_path: Path, **extra: str) -> dict[str, str]:
    return {**with_path(fakebin), "FAKE_FZF_LOG": str(tmp_path / "fzf.log"), **extra}


#----------#
# 小さい関数 #
#----------#


def test_small_functions_behave_like_the_shell_ones(tmp_path: Path):
    work = tmp_path / "work"
    (work / "sub").mkdir(parents=True)
    (work / "sub" / "a.txt").write_text("hello\nneedle here\nbye\n", encoding="utf-8")
    (work / "b.txt").write_text("no match\n", encoding="utf-8")
    for name in ("alpha", "beta", "gamma delta", "e1\\e2", "e3", "keep"):
        (work / name).mkdir(parents=True)
    (work / "keep" / "f.txt").write_text("x", encoding="utf-8")
    body = r"""
Set-Location $args[0]
'SHA1=' + (sha1 'abc')
'SHA1U=' + (sha1 'あ')
'SEARCH=' + ((search needle) -join '|')
jcd 'gam'; 'JCD=' + (Split-Path -Leaf (Get-Location))
Set-Location $args[0]
'JCDMISS=' + (jcd zzz)
cleanup | Out-Null
'CLEANUP=' + ((Get-ChildItem -Directory | Where-Object { $_.Name -match '^(e1|e3|keep|alpha)$' } | ForEach-Object Name) -join ',')
Push-Location sub; 'DIRS=' + ((dirs) -join '|').Replace($args[0], '<W>'); Pop-Location
'LT=' + ((lt) -join '|')
'CAT=' + (cat b.txt)
'CATRAW=' + (cat b.txt -Raw).TrimEnd()
'LL=' + ((ll | ForEach-Object Name) -join ',')
'CATCMD=' + (Get-Command cat).CommandType
"""
    # 引数は -File のあとに渡せないので、パスは本文へ埋め込む
    # eza・bat があっても、無い機と同じ結果になる (PATH から外す)
    lines, stderr, code = powershell(
        tmp_path, body.replace("$args[0]", f"'{work}'"), env=path_without("eza", "bat", "lsd")
    )
    assert code == 0, stderr
    values = dict(line.split("=", 1) for line in lines if "=" in line and line.split("=", 1)[0].isupper())
    # 'abc' の SHA-1 と、UTF-8 の「あ」の SHA-1
    assert values["SHA1"] == "a9993e364706816aba3e25717850c26c9cd0d89d"
    assert values["SHA1U"] == "98fdfc0a7426bbb0fca0b106fd1a6c907446d7c0"
    assert values["SEARCH"] == r"sub\a.txt:2:needle here"
    assert values["JCD"] == "gamma delta"
    assert values["JCDMISS"] == "directory not found"
    # 2 階層までの空のディレクトリだけが消え、中身のあるものは残る
    assert values["CLEANUP"] == "keep"
    assert values["DIRS"].startswith(" 0  <W>\\sub| 1  <W>")
    # eza が無いときの木 (.git などは除く)。bat が無いときの cat は Get-Content のまま
    assert "keep" in values["LT"] and "f.txt" in values["LT"]
    assert values["CAT"] == "no match"
    assert values["CATRAW"] == "no match"
    assert "b.txt" in values["LL"]
    assert values["CATCMD"] == "Function"


def test_cat_uses_bat_only_for_plain_file_arguments(tmp_path: Path):
    fakebin = tmp_path / "fakebin"
    fake_tool(fakebin, "bat", "'BAT ' + ($args -join ' ')")
    (tmp_path / "f.txt").write_text("line\n", encoding="utf-8")
    body = r"""
'PLAIN=' + (cat f.txt)
'MULTI=' + (cat f.txt f.txt)
'RAW=' + (cat f.txt -Raw).TrimEnd()
'PIPED=' + (Get-Item f.txt | cat)
"""
    lines, stderr, code = powershell(tmp_path, body, env=with_path(fakebin))
    assert code == 0, stderr
    values = dict(line.split("=", 1) for line in lines if "=" in line)
    # オプションなし・入力なしのファイル指定だけが bat (ページャーなし・装飾なし)
    assert values["PLAIN"] == "BAT --paging=never -p f.txt"
    assert values["MULTI"] == "BAT --paging=never -p f.txt f.txt"
    # -Raw などのオプションや、パイプラインの入力は Get-Content のまま
    assert values["RAW"] == "line"
    assert values["PIPED"] == "line"


def test_cat_keeps_provider_paths_and_wildcards_on_get_content(tmp_path: Path):
    fakebin = tmp_path / "fakebin"
    fake_tool(fakebin, "bat", "'BAT ' + ($args -join ' ')")
    (tmp_path / "f.txt").write_text("line\n", encoding="utf-8")
    body = r"""
$env:ZZ_CAT_VAR = 'from-env'
'ENV=' + (cat Env:ZZ_CAT_VAR)
'GLOB=' + (cat *.txt)
$ErrorActionPreference = 'Continue'
# xdist (popen-gw0) 配下の長い tmp_path だと ErrorView 既定整形が 120 桁付近で 'nothing.txt' を折り返すため改行を除いて照合する
'MISSING=' + (((cat nothing.txt 2>&1 | Out-String) -replace '\r?\n', '') -match 'nothing\.txt')
'FILE=' + (cat f.txt)
"""
    lines, stderr, code = powershell(tmp_path, body, env=with_path(fakebin))
    assert code == 0, stderr
    values = dict(line.split("=", 1) for line in lines if "=" in line)
    assert values["ENV"] == "from-env"
    assert values["GLOB"] == "line"
    assert values["MISSING"] == "True"
    assert values["FILE"] == "BAT --paging=never -p f.txt"


def test_eza_aliases_use_eza_when_present(tmp_path: Path):
    fakebin = tmp_path / "fakebin"
    fake_tool(fakebin, "eza", "'EZA ' + ($args -join ' ')")
    body = r"""
'LL=' + (ll)
'LA=' + (la)
'LLA=' + (lla)
'LAL=' + (lal -x)
'LT=' + (lt)
'LTL=' + (ltl)
"""
    lines, stderr, code = powershell(tmp_path, body, env=with_path(fakebin))
    assert code == 0, stderr
    values = dict(line.split("=", 1) for line in lines if "=" in line)
    assert values["LL"] == "EZA -l"
    assert values["LA"] == "EZA -a"
    assert values["LLA"] == "EZA -la"
    assert values["LAL"] == "EZA -la -x"
    assert values["LT"] == "EZA -T -L 3 -a -I node_modules|.git|.cache|.venv"
    assert values["LTL"] == "EZA -T -L 3 -a -I node_modules|.git|.cache|.venv -l"


#----------------#
# git と fzf     #
#----------------#


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    path = tmp_path / "repo"
    path.mkdir()
    identity = {
        "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com",
    }
    env = {**os.environ, **identity}

    def git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=path, env=env, check=True, capture_output=True)

    git("init", "-q", "-b", "main", ".")
    (path / "a.txt").write_text("one\n", encoding="utf-8")
    git("add", "a.txt")
    git("-c", "core.autocrlf=false", "commit", "-q", "-m", "first")
    git("branch", "feature/x")
    git("branch", "other")
    return path


def test_git_fzf_functions_check_out_stage_and_move(repo: Path, tmp_path: Path, fakebin: Path):
    identity = {
        "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com",
    }
    body = rf"""
Set-Location '{repo}'
$env:FAKE_FZF_PICK = 'feature/x'; fbr 2>&1 | Out-Null; 'FBR=' + (git branch --show-current)
$env:FAKE_FZF_PICK = 'main'; fbr 2>&1 | Out-Null; 'FBRMAIN=' + (git branch --show-current)
$env:FAKE_FZF_PICK = 'other'; fbrm 2>&1 | Out-Null; 'FBRM=' + (git branch --show-current)
git checkout -q main 2>&1 | Out-Null
Set-Content b.txt two
$env:FAKE_FZF_PICK = 'b.txt'; $env:FAKE_FZF_ONCE = '{tmp_path}\once1'
fadd; 'FADD=' + ((git status --short) -join '|')
Set-Content a.txt changed
$env:FAKE_FZF_PICK = 'a.txt'; $env:FAKE_FZF_KEY = 'ctrl-d'; $env:FAKE_FZF_ONCE = '{tmp_path}\once2'
$diff = (fadd) -join "`n"
'FADDD=' + (($diff -match 'diff --git') -and ((git status --short) -join '|') -eq ' M a.txt|A  b.txt')
$env:FAKE_FZF_KEY = ''
git add -A; git commit -q -m second
$env:FAKE_FZF_PICK = 'second'; $env:FAKE_FZF_ONCE = '{tmp_path}\once3'
'FSHOW=' + ((fshow) -join "`n" -match 'commit [0-9a-f]{{40}}')
Remove-Item Env:FAKE_FZF_ONCE
git worktree add -q ../repo-wt -b wt-branch
$env:FAKE_FZF_PICK = 'wt-branch'; cdworktree
'CDW=' + (Split-Path -Leaf (Get-Location))
Set-Location '{tmp_path}'
$null = cdworktree 3>&1
'NOTREPO=' + (Split-Path -Leaf (Get-Location))
"""
    lines, stderr, code = powershell(tmp_path, body, env={**fzf_env(fakebin, tmp_path), **identity}, cwd=repo)
    assert code == 0, stderr
    values = dict(line.split("=", 1) for line in lines if "=" in line)
    assert values["FBR"] == "feature/x"
    assert values["FBRMAIN"] == "main"
    assert values["FBRM"] == "other"
    assert values["FADD"] == "A  b.txt"
    # Ctrl-D は差分を見るだけで、add しない
    assert values["FADDD"] == "True"
    assert values["FSHOW"] == "True"
    assert values["CDW"] == "repo-wt"
    assert values["NOTREPO"] == tmp_path.name


def test_fadd_stages_only_the_selected_file_even_with_glob_characters(repo: Path, tmp_path: Path, fakebin: Path):
    # PowerShell の Set-Content は、`[ab].txt` をワイルドカードと読むので、ファイルは Python で作る
    (repo / "[ab].txt").write_text("glob", encoding="utf-8")
    body = rf"""
Set-Location '{repo}'
Set-Content a.txt changed
$env:FAKE_FZF_PICK = '\[ab\]'; $env:FAKE_FZF_ONCE = '{tmp_path}\once1'
fadd
'STATUS=' + ((git status --short) -join '|')
"""
    lines, stderr, code = powershell(tmp_path, body, env=fzf_env(fakebin, tmp_path), cwd=repo)
    assert code == 0, stderr
    status = next(line for line in lines if line.startswith("STATUS="))
    # `[ab].txt` というパターンに a.txt が一致しても、選んでいない a.txt は add されない
    assert status == "STATUS=A  [ab].txt| M a.txt"


def test_cdworktree_takes_the_path_from_the_porcelain_output(repo: Path, tmp_path: Path, fakebin: Path):
    """空白や、ハッシュに見える語を含むパスでも、途中で切れない。"""
    identity = {
        "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com",
    }
    tricky = tmp_path / "sample 123abcd backup" / "wt"
    body = rf"""
Set-Location '{repo}'
git worktree add -q '{tricky}' -b tricky-branch
$env:FAKE_FZF_PICK = 'tricky-branch'; cdworktree
'CDW=' + (Get-Location).Path
"""
    lines, stderr, code = powershell(tmp_path, body, env={**fzf_env(fakebin, tmp_path), **identity}, cwd=repo)
    assert code == 0, stderr
    assert f"CDW={tricky}" in lines


def test_gwq_functions_report_a_missing_gwq_and_use_it_when_present(tmp_path: Path, fakebin: Path):
    work = tmp_path / "worktrees" / "feat"
    work.mkdir(parents=True)
    # `--` は pwsh -File が食べるので、cmd の偽物にする (本物の gwq.exe は `--` を受け取る)
    (fakebin / "gwq.cmd").write_text(
        "@echo off\r\n"
        'if "%1"=="list" (echo feat& echo main& exit /b 0)\r\n'
        f'if "%1"=="get" (echo {work}& exit /b 0)\r\n'
        "echo GWQEXEC %*\r\n",
        encoding="ascii",
    )
    fake_tool(fakebin, "code", "'CODE ' + ($args -join ' ')")
    body = r"""
$env:FAKE_FZF_PICK = '^feat$'
xgw; 'XGW=' + (Split-Path -Leaf (Get-Location))
'GWCODE=' + (gwcode)
"""
    lines, stderr, code = powershell(tmp_path, body, env=fzf_env(fakebin, tmp_path))
    assert code == 0, stderr
    values = dict(line.split("=", 1) for line in lines if "=" in line)
    assert values["XGW"] == "feat"
    assert values["GWCODE"] == "GWQEXEC exec feat -- code ."
    # gwq が無い機は、読み込みは成功し、呼ぶと理由を出す (他の PATH の gwq を隠すため PATH を絞る)
    plain = tmp_path / "plain"
    plain.mkdir()
    lines, stderr, code = powershell(
        tmp_path,
        "$ErrorActionPreference = 'Continue'; (xgw 2>&1 | Out-String).Trim()",
        env={"PATH": f"{plain}{os.pathsep}{Path(PWSH).parent}{os.pathsep}{os.environ['SYSTEMROOT']}\\System32"},
    )
    assert "gwq が PATH に無い" in "\n".join(lines)


def test_v_shellf_and_mise_select_pass_the_selection_on(tmp_path: Path, fakebin: Path):
    fake_tool(fakebin, "mise", "if ($args[0] -eq 'ls-remote') { '1.0'; '2.0'; '3.0' } else { 'MISE ' + ($args -join ' ') }")
    fake_tool(fakebin, "vim", "'VIM ' + ($args -join ' ')")
    home = tmp_path / "home"
    home.mkdir()
    (home / "keep.txt").write_text("x", encoding="utf-8")
    (home / ".viminfo").write_text(
        "# viminfo\n> ~/keep.txt\n\t*\t1\n> ~/gone.txt\n> C:/nowhere/missing.txt\n", encoding="utf-8"
    )
    body = r"""
$env:FAKE_FZF_PICK = '^3'
'MISE=' + (mise-select node)
$env:FAKE_FZF_PICK = 'keep'
function vim { 'VIM ' + ($args -join ' ') }
'V=' + (v)
"""
    lines, stderr, code = powershell(tmp_path, body, env={**fzf_env(fakebin, tmp_path), "HOME": str(home), "USERPROFILE": str(home)})
    assert code == 0, stderr
    values = dict(line.split("=", 1) for line in lines if "=" in line)
    # 版は新しい順 (--tac)。選んだ版で mise use
    assert values["MISE"] == "MISE use node@3.0"
    # viminfo の、実在するファイルだけが候補になり、選んだものを vim へ渡す
    assert values["V"].endswith("keep.txt") and values["V"].startswith("VIM ")
    assert "--tac" in (tmp_path / "fzf.log").read_text(encoding="utf-8", errors="replace")


#---------------#
# 圧縮と C++    #
#---------------#


@pytest.mark.skipif(shutil.which("zstd") is None, reason="zstd が無い (scoop install zstd)")
@pytest.mark.parametrize("tar_flavor", ["gnu", "bsd"])
def test_zpack_zunpack_and_extract_work_with_both_tars(tmp_path: Path, tar_flavor: str):
    system_tar = Path(os.environ["SYSTEMROOT"]) / "System32" / "tar.exe"
    env = {}
    if tar_flavor == "bsd":
        if not system_tar.exists():
            pytest.skip("Windows 標準の tar が無い")
        env["PATH"] = f"{system_tar.parent}{os.pathsep}{os.environ['PATH']}"
    else:
        # Git for Windows 同梱の GNU tar (usr/bin) を先頭に置く
        git = shutil.which("git")
        gnu_dir = None
        for parent in Path(git).parents if git else []:
            if (parent / "usr" / "bin" / "tar.exe").exists():
                gnu_dir = parent / "usr" / "bin"
                break
        if gnu_dir is None:
            pytest.skip("GNU tar (Git for Windows の usr/bin) が無い")
        env["PATH"] = f"{gnu_dir}{os.pathsep}{os.environ['PATH']}"
    work = tmp_path / "work"
    (work / "data" / "sub").mkdir(parents=True)
    (work / "data" / "a.txt").write_text("alpha", encoding="utf-8")
    (work / "data" / "sub" / "b.txt").write_text("beta", encoding="utf-8")
    body = rf"""
Set-Location '{work}'
zpack data | Out-Null
'FLAVOR=' + (Get-Variable TarFlavor -Scope Global -ValueOnly)
'PACKED=' + ((Get-Item data.tar.zst).Length -gt 0)
$ErrorActionPreference = 'Continue'
'REFUSED=' + ((zpack data 2>&1 | Out-String) -match 'already exists')
$env:ZPACK_LEVEL = 'x'; 'BADLEVEL=' + ((zpack data bad.tar.zst 2>&1 | Out-String) -match 'must be an integer')
$env:ZPACK_LEVEL = '3'; zpack data level3.tar.zst | Out-Null; 'LEVEL3=' + (Test-Path level3.tar.zst)
Remove-Item Env:ZPACK_LEVEL
'INSIDE=' + ((zpack data data\in.tar.zst 2>&1 | Out-String) -match 'inside the source')
zunpack data.tar.zst out
'UNPACK=' + ((Get-ChildItem out -Recurse -File | ForEach-Object Name | Sort-Object) -join ',')
zunpack '{work}\data.tar.zst' '{work}\out2'
'ABSOLUTE=' + (@(Get-ChildItem out2 -Recurse -File).Count)
New-Item -ItemType Directory ex1 | Out-Null; Set-Location ex1
extract ..\data.tar.zst | Out-Null
'EXTRACTZST=' + (@(Get-ChildItem -Recurse -File).Count)
Set-Location '{work}'
tar -czf d.tar.gz data
New-Item -ItemType Directory ex2 | Out-Null; Set-Location ex2
extract ..\d.tar.gz | Out-Null
'EXTRACTGZ=' + (@(Get-ChildItem -Recurse -File).Count)
Set-Location '{work}'
Compress-Archive -Path data -DestinationPath d.zip
New-Item -ItemType Directory ex3 | Out-Null; Set-Location ex3
extract ..\d.zip | Out-Null
'EXTRACTZIP=' + (@(Get-ChildItem -Recurse -File).Count)
Set-Location '{work}'
Set-Content foo.bin 1
'UNSUPPORTED=' + ((extract foo.bin 2>&1 | Out-String) -match '未対応')
"""
    lines, stderr, code = powershell(tmp_path, body, env=env, cwd=work)
    assert code == 0, stderr
    values = dict(line.split("=", 1) for line in lines if "=" in line)
    assert values["FLAVOR"] == tar_flavor
    for key in ("PACKED", "REFUSED", "BADLEVEL", "LEVEL3", "INSIDE", "UNSUPPORTED"):
        assert values[key] == "True", key
    assert values["UNPACK"] == "a.txt,b.txt"
    assert values["ABSOLUTE"] == "2"
    assert values["EXTRACTZST"] == values["EXTRACTGZ"] == values["EXTRACTZIP"] == "2"


def test_zpack_cleans_up_its_work_directory_when_tar_fails(tmp_path: Path):
    fakebin = tmp_path / "fakebin"
    fake_tool(fakebin, "zstd", "exit 0")
    # tar の偽物: --version は GNU を名乗り、-cf では書きかけのファイルを作って失敗する
    fake_tool(
        fakebin,
        "tar",
        "if ($args -contains '--version') { 'tar (GNU tar) 1.35'; exit 0 }\n"
        "$index = [array]::IndexOf($args, '-cf')\n"
        "if ($index -ge 0) { Set-Content -LiteralPath $args[$index + 1] 'partial' }\n"
        "exit 2",
    )
    work = tmp_path / "work"
    (work / "data").mkdir(parents=True)
    (work / "data" / "a.txt").write_text("alpha", encoding="utf-8")
    # 以前の版が使っていた一時ファイルの名前と同じものがあっても、触らない
    decoy = work / "out.tar.zst.zpack.1234"
    decoy.write_text("keep me", encoding="utf-8")
    body = rf"""
Set-Location '{work}'
$ErrorActionPreference = 'Continue'
'ERROR=' + ((zpack data out.tar.zst 2>&1 | Out-String) -match 'failed to create archive')
'OUTPUT=' + (Test-Path out.tar.zst)
'LEFTOVER=' + (@(Get-ChildItem -Force -Filter '.zpack-*').Count)
"""
    lines, stderr, code = powershell(tmp_path, body, env=with_path(fakebin), cwd=work)
    assert code == 0, stderr
    values = dict(line.split("=", 1) for line in lines if "=" in line)
    assert values["ERROR"] == "True"
    assert values["OUTPUT"] == "False"
    assert values["LEFTOVER"] == "0"
    assert decoy.read_text(encoding="utf-8") == "keep me"


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ が無い")
def test_runcpp_compiles_runs_and_passes_stdin_arguments_and_exit_code(tmp_path: Path):
    work = tmp_path / "work"
    work.mkdir()
    (work / "hello.cpp").write_text(
        "#include <bits/stdc++.h>\n"
        "int main(int argc, char** argv) {\n"
        "  std::string line; std::getline(std::cin, line);\n"
        "#ifdef LOCAL\n  std::cout << \"LOCAL \";\n#endif\n"
        "#ifdef ONLINE_JUDGE\n  std::cout << \"JUDGE \";\n#endif\n"
        "  std::cout << \"in=\" << line << \" args=\" << argc - 1;\n"
        "  for (int i = 1; i < argc; i++) std::cout << \" [\" << argv[i] << \"]\";\n"
        "  std::cout << \"\\n\";\n"
        "  return line == \"fail\" ? 7 : 0;\n}\n",
        encoding="utf-8",
    )
    (work / "bad.cpp").write_text("int main( { }\n", encoding="utf-8")
    body = rf"""
Set-Location '{work}'
$env:XDG_CACHE_HOME = '{tmp_path}\cache'
$ErrorActionPreference = 'Continue'
'DEBUG=' + ('abc' | runcpp hello.cpp -- x y)
'DEBUGEXIT=' + $LASTEXITCODE
'RELEASE=' + ('abc' | runcpp -r hello.cpp)
$null = 'fail' | runcpp -r hello.cpp
'EXIT=' + $LASTEXITCODE
'TIME=' + (('abc' | runcpp -r -t hello.cpp *>&1 | Out-String) -match 'real [0-9.]+s')
runcpp -c -r hello.cpp
'COMPILEONLY=' + (Test-Path '{tmp_path}\cache\runcpp\hello-release.exe')
'BADOPTION=' + ((runcpp --bogus hello.cpp 2>&1 | Out-String) -match 'unknown option')
'NOFILE=' + ((runcpp nope.cpp 2>&1 | Out-String) -match 'No such file')
'COMPILEERROR=' + ((runcpp -r bad.cpp 2>&1 | Out-String) -match 'error')
'HELP=' + ((runcpp --help | Out-String) -match 'Standard input: pass it through the pipeline')
"""
    lines, stderr, code = powershell(tmp_path, body, cwd=work)
    assert code == 0, stderr
    values = dict(line.split("=", 1) for line in lines if "=" in line)
    # debug: LOCAL が定義される (MinGW は sanitizer が無いので、あれば足し、無ければ足さない)。引数と標準入力が届く
    assert values["DEBUG"] == "LOCAL in=abc args=2 [x] [y]"
    assert values["DEBUGEXIT"] == "0"
    assert values["RELEASE"] == "JUDGE in=abc args=0"
    assert values["EXIT"] == "7"
    for key in ("TIME", "COMPILEONLY", "BADOPTION", "NOFILE", "COMPILEERROR", "HELP"):
        assert values[key] == "True", key


#-------------#
# pi と pk    #
#-------------#


def test_drypi_and_superpi_pass_the_dry_flags_and_run_from_the_drive_root(tmp_path: Path):
    fakebin = tmp_path / "fakebin"
    fake_tool(fakebin, "pi", "'PI cwd=' + (Get-Location).Path + ' args=' + ($args -join ' ') + ' stdin=' + (@($input) -join '/')")
    fake_tool(fakebin, "sudo", "'SUDO cwd=' + (Get-Location).Path + ' ' + ($args -join ' ')")
    work = tmp_path / "work"
    work.mkdir()
    body = rf"""
Set-Location '{work}'
'DRY=' + (drypi -p 'hi there')
'DRYPIPE=' + ('question' | drypi -p)
'SUPER=' + (superpi -p x)
'AFTER=' + (Get-Location).Path
"""
    lines, stderr, code = powershell(tmp_path, body, env=with_path(fakebin), cwd=work)
    assert code == 0, stderr
    values = dict(line.split("=", 1) for line in lines if "=" in line)
    dry = "--no-extensions --no-skills --no-prompt-templates --no-context-files --no-approve"
    assert values["DRY"].startswith(f"PI cwd={work} args={dry} -p hi there")
    # 標準入力は pi へ届く
    assert values["DRYPIPE"].endswith("stdin=question")
    # superpi: sudo で pi (絶対パス) を、同じ停止の一覧 + --no-session --offline で呼ぶ。ドライブの根から。終わると元の場所へ戻る
    assert values["SUPER"].startswith("SUDO cwd=")
    assert "pi.cmd" in values["SUPER"] and f"{dry} --no-session --offline -p x" in values["SUPER"]
    assert re.match(r"SUDO cwd=[A-Za-z]:\\ ", values["SUPER"])
    assert values["AFTER"] == str(work)


def test_pk_runs_the_python_entry_through_sh_and_returns_its_exit_code(tmp_path: Path):
    sh = shutil.which("sh") or next(
        (str(path) for path in (Path(os.environ.get("PROGRAMFILES", "")) / "Git" / "bin" / "sh.exe",) if path.exists()), None
    )
    python = shutil.which("python") or shutil.which("py")
    if not sh or not python:
        pytest.skip("sh (Git for Windows) か python が無い")
    home = tmp_path / "home"
    (home / ".local" / "bin").mkdir(parents=True)
    shutil.copy(ROOT / "home/dot_local/bin/executable_pk", home / ".local" / "bin" / "pk")
    keep = tmp_path / "keep"
    topic = keep / "demo"
    topic.mkdir(parents=True)
    (topic / "run.sh").write_text('# デモの道具\necho "args=$*"\nexit 3\n', encoding="utf-8", newline="\n")
    body = r"""
$global:LASTEXITCODE = 0
'LIST=' + ((pk) -join '|')
'RUN=' + ((pk demo a 'b c' 2>$null) -join '|')
'EXIT=' + $LASTEXITCODE
"""
    lines, stderr, code = powershell(
        tmp_path, body, env={"HOME": str(home), "USERPROFILE": str(home), "PK_ROOT": str(keep)}
    )
    assert code == 0, stderr
    values = dict(line.split("=", 1) for line in lines if "=" in line)
    assert "demo" in values["LIST"] and "デモの道具" in values["LIST"]
    assert values["RUN"] == "args=a b c"
    assert values["EXIT"] == "3"


#------------------#
# 個人用・補完      #
#------------------#


def test_personal_functions_build_the_expected_commands(tmp_path: Path):
    fakebin = tmp_path / "fakebin"
    fake_tool(fakebin, "code", "'CODE ' + ($args -join ' ')")
    fake_tool(fakebin, "yt-dlp", "'YTDLP ' + ($args -join ' ')")
    home = tmp_path / "home"
    home.mkdir()
    body = r"""
'EXAM=' + (code-exam)
'AUDIO=' + (audio-dl 'https://example.com/v')
'VIDEO=' + (video-dl 'https://example.com/v')
"""
    lines, stderr, code = powershell(tmp_path, body, env={**with_path(fakebin), "HOME": str(home), "USERPROFILE": str(home)})
    assert code == 0, stderr
    values = dict(line.split("=", 1) for line in lines if "=" in line)
    assert values["EXAM"].startswith("CODE --disable-extensions --profile coding-test ")
    assert "coding-test" in values["EXAM"] and (home / "coding-test").is_dir()
    assert "--extract-audio --audio-format mp3 --embed-thumbnail https://example.com/v" in values["AUDIO"]
    assert "Downloads" in values["AUDIO"] and "%(title)s.%(ext)s" in values["AUDIO"]
    assert "--recode-video mp4 --add-metadata https://example.com/v" in values["VIDEO"]


COBRA_COMPLETION = r"""
function __faketool_debug { if ($env:BASH_COMP_DEBUG_FILE) { "$args" | Out-File -Append -FilePath "$env:BASH_COMP_DEBUG_FILE" } }
filter __faketool_escape { $_ -replace '\s', '`$&' }
[scriptblock]${__faketoolCompleterBlock} = {
  param($WordToComplete, $CommandAst, $CursorPosition)
  __faketool_debug "called"
  foreach ($value in 'alpha', 'beta', 'alphabet') {
    if ($value -like "$WordToComplete*") {
      [System.Management.Automation.CompletionResult]::new(($value | __faketool_escape), $value, 'ParameterValue', $value)
    }
  }
}
Register-ArgumentCompleter -CommandName 'faketool' -ScriptBlock ${__faketoolCompleterBlock}
"""


def test_lazy_completion_generates_caches_and_reuses_the_tools_completion_script(tmp_path: Path):
    """初めて Tab を押したときに生成してキャッシュし、スクリプトの登録を横取りして呼ぶ (cobra 製の補助関数・フィルターも使える)。"""
    fakebin = tmp_path / "fakebin"
    counter = tmp_path / "generated.log"
    script_file = tmp_path / "faketool-completion.ps1"
    script_file.write_text(COBRA_COMPLETION, encoding="utf-8")
    fake_tool(
        fakebin,
        "faketool",
        f"Add-Content -LiteralPath '{counter}' 'generated'\nGet-Content -LiteralPath '{script_file}' -Raw",
    )
    local = tmp_path / "localappdata"
    body = r"""
Register-LazyCompletion -CommandName faketool -GeneratorArguments 'completion', 'powershell'
function Complete($text) { (TabExpansion2 $text $text.Length).CompletionMatches | ForEach-Object CompletionText }
'FIRST=' + ((Complete 'faketool al') -join ',')
'SECOND=' + ((Complete 'faketool b') -join ',')
'CACHED=' + (Test-Path (Join-Path $env:LOCALAPPDATA 'PowerShellProfileCache\completion-faketool.ps1'))
'ALLCOUNT=' + (@(Complete 'faketool ').Count)
"""
    lines, stderr, code = powershell(
        tmp_path, body, env={**with_path(fakebin), "LOCALAPPDATA": str(local)}
    )
    assert code == 0, stderr
    values = dict(line.split("=", 1) for line in lines if "=" in line)
    assert values["FIRST"] == "alpha,alphabet"
    assert values["SECOND"] == "beta"
    assert values["CACHED"] == "True"
    assert values["ALLCOUNT"] == "3"
    # 補完スクリプトの生成は 1 回だけ (2 回目以降はキャッシュ)
    assert counter.read_text(encoding="utf-8").count("generated") == 1


def test_lazy_completion_does_not_cache_output_that_is_not_a_completion_script(tmp_path: Path):
    """使い方の表示やエラーをキャッシュして、本物として実行しない (引数が渡らなかった事故の再発防止)。"""
    fakebin = tmp_path / "fakebin"
    fake_tool(fakebin, "brokentool", "'usage: brokentool [options]'")
    local = tmp_path / "localappdata"
    body = r"""
Register-LazyCompletion -CommandName brokentool -GeneratorArguments 'completion', 'powershell'
$matches = (TabExpansion2 'brokentool x' 12).CompletionMatches
'CACHED=' + (Test-Path (Join-Path $env:LOCALAPPDATA 'PowerShellProfileCache\completion-brokentool.ps1'))
"""
    lines, stderr, code = powershell(tmp_path, body, env={**with_path(fakebin), "LOCALAPPDATA": str(local)})
    assert code == 0, stderr
    assert "CACHED=False" in lines


def test_lazy_completion_ignores_an_explicit_path_to_the_tool(tmp_path: Path):
    """`.\\faketool` や絶対パスで呼ぶものは、PATH の同名の別物の補完を出さない (生成もしない)。"""
    fakebin = tmp_path / "fakebin"
    counter = tmp_path / "generated.log"
    script_file = tmp_path / "faketool-completion.ps1"
    script_file.write_text(COBRA_COMPLETION, encoding="utf-8")
    fake_tool(
        fakebin,
        "faketool",
        f"Add-Content -LiteralPath '{counter}' 'generated'\nGet-Content -LiteralPath '{script_file}' -Raw",
    )
    body = r"""
Register-LazyCompletion -CommandName faketool -GeneratorArguments 'completion', 'powershell'
function Complete($text) { (TabExpansion2 $text $text.Length).CompletionMatches | ForEach-Object CompletionText }
'RELATIVE=' + ((Complete '.\faketool al') -join ',')
'ABSOLUTE=' + ((Complete 'C:\\tools\\faketool.exe al') -join ',')
'BARE=' + ((Complete 'faketool al') -join ',')
"""
    lines, stderr, code = powershell(
        tmp_path, body, env={**with_path(fakebin), "LOCALAPPDATA": str(tmp_path / "localappdata")}
    )
    assert code == 0, stderr
    values = dict(line.split("=", 1) for line in lines if "=" in line)
    assert values["RELATIVE"] == "" or "alpha" not in values["RELATIVE"]
    assert "alpha" not in values["ABSOLUTE"]
    assert values["BARE"] == "alpha,alphabet"
    assert counter.read_text(encoding="utf-8").count("generated") == 1


def test_an_evaluated_snippet_that_fails_or_is_empty_is_not_expanded(tmp_path: Path):
    body = r"""
Import-Module ShellSnippets
function Resolve($snippet) { & (Get-Module ShellSnippets) { param($s) Resolve-SnippetText -Snippet $s } $snippet }
function Make($text) { [pscustomobject]@{ evaluate = $true; snippet = $text } }
'OK=' + (Resolve (Make "'abc'"))
'THROWS=' + ($null -eq (Resolve (Make "throw 'x'")))
'EMPTY=' + ($null -eq (Resolve (Make '$null')))
'PLAIN=' + (Resolve ([pscustomobject]@{ evaluate = $false; snippet = 'git status' }))
"""
    lines, stderr, code = powershell(tmp_path, body)
    assert code == 0, stderr
    values = dict(line.split("=", 1) for line in lines if "=" in line)
    assert values["OK"] == "abc"
    assert values["THROWS"] == "True"
    assert values["EMPTY"] == "True"
    assert values["PLAIN"] == "git status"


def test_ssh_hosts_are_completed_from_the_ssh_config(tmp_path: Path):
    home = tmp_path / "home"
    (home / ".ssh").mkdir(parents=True)
    (home / ".ssh" / "config").write_text(
        "Host *\n  ServerAliveInterval 30\nHost alpha beta\n  HostName x\nHost gamma-* !skip\nHost delta\n",
        encoding="utf-8",
    )
    body = r"""
function Complete($text) { (TabExpansion2 $text $text.Length).CompletionMatches | ForEach-Object CompletionText }
'ALL=' + ((Complete 'ssh ') -join ',')
'PREFIX=' + ((Complete 'ssh a') -join ',')
'USER=' + ((Complete 'scp me@d') -join ',')
'OPTION=' + ((Complete 'ssh -') -join ',')
"""
    lines, stderr, code = powershell(tmp_path, body, env={"HOME": str(home), "USERPROFILE": str(home)})
    assert code == 0, stderr
    values = dict(line.split("=", 1) for line in lines if "=" in line)
    # ワイルドカードと否定のホストは出さない
    assert values["ALL"] == "alpha,beta,delta"
    assert values["PREFIX"] == "alpha"
    assert values["USER"] == "me@delta"
    assert values["OPTION"] == ""


#--------------------------#
# TEMP・auto_cd・chpwd     #
#--------------------------#


def update_repo_local_temp_source() -> str:
    text = (POWERSHELL_DIR / "profile.ps1.tmpl").read_text(encoding="utf-8-sig")
    start = text.index("function Update-RepoLocalTemp {")
    end = text.index("\nUpdate-RepoLocalTemp\n", start)
    return text[start:end]


UNSET = object()


def run_temp_case(
    tmp_path: Path,
    cwd: Path,
    temp: str,
    original: str | None = None,
    *,
    tmp: object = None,
    original_tmp: str | None = None,
) -> str:
    """tmp は、省略すると temp と同じ。UNSET なら TMP を消す。original / original_tmp は、控えの環境変数。"""
    tmp_value = temp if tmp is None else tmp
    set_tmp = "Remove-Item Env:TMP -ErrorAction Ignore" if tmp_value is UNSET else f"$env:TMP = '{tmp_value}'"
    set_original = (
        f"$env:_TMPDIR_REPO_LOCAL_ORIG = '{original}'"
        if original
        else "Remove-Item Env:_TMPDIR_REPO_LOCAL_ORIG -ErrorAction Ignore"
    )
    set_original_tmp = (
        f"$env:_TMPDIR_REPO_LOCAL_ORIG_TMP = '{original_tmp}'"
        if original_tmp
        else "Remove-Item Env:_TMPDIR_REPO_LOCAL_ORIG_TMP -ErrorAction Ignore"
    )
    body = f"""
$env:TEMP = '{temp}'; {set_tmp}
{set_original}
{set_original_tmp}
{update_repo_local_temp_source()}
Set-Location '{cwd}'
Update-RepoLocalTemp
'TEMP=' + $env:TEMP
'TMP=' + $(if ($null -eq $env:TMP) {{ '<unset>' }} else {{ $env:TMP }})
'ORIG=' + $env:_TMPDIR_REPO_LOCAL_ORIG
'ORIGTMP=' + $env:_TMPDIR_REPO_LOCAL_ORIG_TMP
"""
    script = tmp_path / f"temp-{abs(hash(body))}.ps1"
    script.write_text(body, encoding="utf-8-sig")
    completed = subprocess.run(
        [PWSH, "-NoLogo", "-NoProfile", "-File", str(script)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
    )
    assert completed.returncode == 0, completed.stderr
    return completed.stdout


def test_temp_follows_the_repository_and_returns_outside(tmp_path: Path):
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    (repo / "src" / "deep").mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    system_temp = str(tmp_path / "SystemTemp")

    inside = run_temp_case(tmp_path, repo / "src" / "deep", system_temp)
    # リポジトリの中 (深い場所からでも) では、その .tmp へ。TEMP と TMP の両方。元の値を控える
    assert f"TEMP={repo}\\.tmp\n" in inside and f"TMP={repo}\\.tmp\n" in inside
    assert f"ORIG={system_temp}\n" in inside
    assert (repo / ".tmp").is_dir()
    # リポジトリの外では、控えた元の値へ戻る (親が向けた別のリポジトリの .tmp を、元の値と取り違えない)
    other = run_temp_case(tmp_path, outside, str(repo / ".tmp"), original=system_temp)
    assert f"TEMP={system_temp}\n" in other and f"TMP={system_temp}\n" in other


def test_temp_keeps_a_pi_session_directory_and_a_worktree_file_marker(tmp_path: Path):
    repo = tmp_path / "worktree"
    repo.mkdir()
    # git の worktree は .git がファイル
    (repo / ".git").write_text("gitdir: elsewhere", encoding="utf-8")
    session = repo / ".tmp" / "s" / "abc123"
    session.mkdir(parents=True)
    system_temp = str(tmp_path / "SystemTemp")

    kept = run_temp_case(tmp_path, repo, str(session), original=system_temp)
    assert f"TEMP={session}\n" in kept
    plain = run_temp_case(tmp_path, repo, system_temp)
    assert f"TEMP={repo}\\.tmp\n" in plain
    # .tmp が作れない (ファイルがある) ときは、元の値を保つ
    blocked = tmp_path / "blocked"
    (blocked / ".git").mkdir(parents=True)
    (blocked / ".tmp").write_text("a file", encoding="utf-8")
    assert f"TEMP={system_temp}\n" in run_temp_case(tmp_path, blocked, system_temp)


def test_temp_and_tmp_are_saved_and_restored_separately(tmp_path: Path):
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    system_temp, system_tmp = str(tmp_path / "SysTemp"), str(tmp_path / "SysTmp")

    inside = run_temp_case(tmp_path, repo, system_temp, tmp=system_tmp)
    assert f"TEMP={repo}\\.tmp\n" in inside and f"TMP={repo}\\.tmp\n" in inside
    assert f"ORIG={system_temp}\n" in inside and f"ORIGTMP={system_tmp}\n" in inside
    # 外へ出ると、それぞれの元の値へ戻る (TMP が TEMP の値にならない)
    back = run_temp_case(
        tmp_path, outside, str(repo / ".tmp"), original=system_temp, tmp=str(repo / ".tmp"), original_tmp=system_tmp
    )
    assert f"TEMP={system_temp}\n" in back and f"TMP={system_tmp}\n" in back
    # TMP が元々無いときは、控えは <unset> で、外では TMP を消す
    unset_in = run_temp_case(tmp_path, repo, system_temp, tmp=UNSET)
    assert "ORIGTMP=<unset>\n" in unset_in
    unset_back = run_temp_case(
        tmp_path, outside, str(repo / ".tmp"), original=system_temp, tmp=str(repo / ".tmp"), original_tmp="<unset>"
    )
    assert f"TEMP={system_temp}\n" in unset_back and "TMP=<unset>\n" in unset_back
    # TEMP が既に目的地で、TMP だけ違っていても、TMP を直す
    half = run_temp_case(tmp_path, repo, str(repo / ".tmp"), original=system_temp, tmp=system_tmp, original_tmp=system_tmp)
    assert f"TEMP={repo}\\.tmp\n" in half and f"TMP={repo}\\.tmp\n" in half


def test_temp_ignores_a_junction_as_the_repository_tmp(tmp_path: Path):
    """.tmp がジャンクション (行き先がリポジトリの外かもしれない) なら、向けずに元の値を保つ。"""
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    made = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(repo / ".tmp"), str(elsewhere)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if made.returncode != 0:
        pytest.skip(f"ジャンクションを作れない: {made.stderr or made.stdout}")
    system_temp = str(tmp_path / "SystemTemp")
    result = run_temp_case(tmp_path, repo, system_temp)
    assert f"TEMP={system_temp}\n" in result and f"TMP={system_temp}\n" in result


def test_mise_cache_stays_in_the_original_temp_when_temp_follows_the_repository(tmp_path: Path):
    """mise の cache は既定で %TEMP% の mise。TEMP を向けても、リポジトリごとに冷えないよう元の場所へ固定する。"""
    text = (POWERSHELL_DIR / "profile.ps1.tmpl").read_text(encoding="utf-8-sig")
    start = text.index("if (-not $env:MISE_CACHE_DIR) {")
    closing = "\n  }\n}\n"
    block = text[start : text.index(closing, start) + len(closing)]
    original = str(tmp_path / "SystemTemp")

    def run(setup: str) -> str:
        body = f"{setup}\n{block}\n'MISE=' + $(if ($null -eq $env:MISE_CACHE_DIR) {{ '<none>' }} else {{ $env:MISE_CACHE_DIR }})\n"
        script = tmp_path / f"mise-{abs(hash(setup))}.ps1"
        script.write_text(body, encoding="utf-8-sig")
        completed = subprocess.run(
            [PWSH, "-NoLogo", "-NoProfile", "-File", str(script)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
        assert completed.returncode == 0, completed.stderr
        return completed.stdout.strip()

    unset_cache = "Remove-Item Env:MISE_CACHE_DIR -ErrorAction Ignore"
    assert run(f"{unset_cache}; $env:_TMPDIR_REPO_LOCAL_ORIG = '{original}'") == f"MISE={original}\\mise"
    # 利用者の指定は上書きしない。控えが無い・<unset> のときは何もしない
    assert run(rf"$env:MISE_CACHE_DIR = 'D:\cache'; $env:_TMPDIR_REPO_LOCAL_ORIG = '{original}'") == r"MISE=D:\cache"
    assert run(f"{unset_cache}; $env:_TMPDIR_REPO_LOCAL_ORIG = '<unset>'") == "MISE=<none>"
    assert run(f"{unset_cache}; Remove-Item Env:_TMPDIR_REPO_LOCAL_ORIG -ErrorAction Ignore") == "MISE=<none>"


def test_auto_cd_changes_into_directories_typed_as_commands(tmp_path: Path):
    work = tmp_path / "work"
    (work / "sub1" / "inner").mkdir(parents=True)
    (work / "sub2").mkdir()
    home = tmp_path / "home"
    (home / "homedir").mkdir(parents=True)
    # 対話の入力と同じ経路 (Runspace 起点) にするため、-Command のトップレベルのコマンドとして評価する
    body = f"""
Set-Location '{work}'
function Here {{ (Get-Location).Path.Substring('{tmp_path}'.Length) }}
sub1
'CD1=' + (Here)
inner
'CD2=' + (Here)
..
'UP=' + (Here)
./inner
'REL=' + (Here)
...
'UPUP=' + (Here)
sub2
'SIBLING=' + (Here)
sub1
'CDPATHPARENT=' + (Here)
homedir
'CDPATHHOME=' + (Here)
~
'HOME=' + (Get-Location).Path
Set-Location '{work}'
$ErrorActionPreference = 'Continue'
try {{ zz-no-such-dir-xyz }} catch {{ 'NOTFOUND=' + ($_.Exception.GetType().Name -eq 'CommandNotFoundException') }}
'STILL=' + (Here)
"""
    lines, stderr, code = powershell(
        tmp_path, body, env={"HOME": str(home), "USERPROFILE": str(home)}, cwd=work, as_command=True
    )
    assert code == 0, stderr
    values = dict(line.split("=", 1) for line in lines if "=" in line)
    assert values["CD1"] == r"\work\sub1"
    assert values["CD2"] == r"\work\sub1\inner"
    assert values["UP"] == r"\work\sub1"
    assert values["REL"] == r"\work\sub1\inner"
    assert values["UPUP"] == r"\work"
    assert values["SIBLING"] == r"\work\sub2"
    # cdpath: カレントに無ければ、親 (..)、ホーム (~) の順に探す
    assert values["CDPATHPARENT"] == r"\work\sub1"
    assert values["CDPATHHOME"] == r"\home\homedir"
    assert values["HOME"] == str(home)
    # ディレクトリでも無いものは、ふつうのエラーのまま (移動しない)
    assert values["NOTFOUND"] == "True"
    assert values["STILL"] == r"\work"


def test_auto_cd_needs_a_bare_word_and_survives_reloading(tmp_path: Path):
    work = tmp_path / "work"
    (work / "zz-dir").mkdir(parents=True)
    body = f"""
Set-Location '{work}'
$ErrorActionPreference = 'Continue'
# 再読み込み (プロファイルを読み直す操作) をしても、ハンドラが自分を呼んで止まらない
. '{INTERACTIVE}'
. '{INTERACTIVE}'
try {{ zz-dir --help; 'ARGS=moved' }} catch {{ 'ARGS=' + $_.Exception.GetType().Name }}
'STAYED=' + ((Get-Location).Path -eq '{work}')
zz-dir
'BARE=' + (Split-Path -Leaf (Get-Location))
try {{ zz-no-such-xyz }} catch {{ 'MISSING=' + $_.Exception.GetType().Name }}
"""
    lines, stderr, code = powershell(tmp_path, body, cwd=work, as_command=True)
    assert code == 0, stderr
    values = dict(line.split("=", 1) for line in lines if "=" in line)
    assert values["ARGS"] == "CommandNotFoundException"
    assert values["STAYED"] == "True"
    assert values["BARE"] == "zz-dir"
    assert values["MISSING"] == "CommandNotFoundException"


def test_auto_cd_is_ignored_when_called_from_a_script(tmp_path: Path):
    """関数・スクリプトの中から呼ばれた存在しないコマンドを、ディレクトリ名で取り違えて黙って移動しない。"""
    work = tmp_path / "work"
    (work / "zz-missing-tool").mkdir(parents=True)
    body = f"""
Set-Location '{work}'
$ErrorActionPreference = 'Continue'
function Run-Missing {{ zz-missing-tool }}
$result = Run-Missing 2>&1 | Out-String
'STAYED=' + ((Get-Location).Path -eq '{work}')
'ERROR=' + ($result -match '認識されません|not recognized')
"""
    lines, stderr, code = powershell(tmp_path, body, cwd=work)
    assert code == 0, stderr
    assert "STAYED=True" in lines and "ERROR=True" in lines


def test_chpwd_lists_the_directory_after_cd_only_to_a_terminal(tmp_path: Path):
    work = tmp_path / "work"
    (work / "sub").mkdir(parents=True)
    (work / "sub" / "marker-file.txt").write_text("x", encoding="utf-8")
    body = rf"""
Set-Location '{work}'
Set-Location sub
'DONE'
"""
    # 標準出力がリダイレクトのとき (エージェント・パイプ) は、一覧を出さない
    lines, stderr, code = powershell(tmp_path, body, cwd=work)
    assert code == 0, stderr
    assert "marker-file.txt" not in "\n".join(lines)
    assert lines[-1] == "DONE"
