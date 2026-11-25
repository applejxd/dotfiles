# 競技プログラミング用: C++ の単一ファイルを debug / release でコンパイルして実行する (runcpp)。
# bash / zsh の functions/cpp.sh に相当する。Windows PowerShell 5.1 と PowerShell 7 の両方で動かす。
# 対話セッションだけで読み込む。コンパイラは scoop の mingw-winlibs (g++)。
# MinGW は AddressSanitizer / UBSan を持たないので、debug は警告と STL のデバッグモードだけにする
# (使えるコンパイラのときだけ sanitizer を足す。判定はコンパイルを 1 回試し、結果を覚える)。
# スタックは、Linux の `ulimit -s 1048576` の代わりにリンク時に 1 GiB へ広げる。
# 標準入力は、リダイレクト (`<`) が無いので、パイプで渡す: `Get-Content in.txt | runcpp a.cpp`
# see docs/spec/dev-environment.md#c-の単一ファイル実行runcpp

function Test-RuncppSanitizer {
  param([Parameter(Mandatory)][string]$Compiler)

  $key = "RuncppSanitizer_$($Compiler -replace '[^A-Za-z0-9]', '_')"
  $known = Get-Variable -Name $key -Scope Global -ValueOnly -ErrorAction Ignore
  if ($null -ne $known) {
    return $known
  }
  $source = [System.IO.Path]::Combine([System.IO.Path]::GetTempPath(), "runcpp-probe-$PID.cpp")
  $binary = [System.IO.Path]::ChangeExtension($source, '.exe')
  try {
    [System.IO.File]::WriteAllText($source, 'int main() { return 0; }')
    & $Compiler '-fsanitize=address,undefined' $source -o $binary *> $null
    $supported = ($LASTEXITCODE -eq 0)
  } finally {
    Remove-Item -LiteralPath $source, $binary -Force -ErrorAction Ignore
  }
  Set-Variable -Name $key -Scope Global -Value $supported
  $supported
}

# Usage: runcpp [options] <src.cpp> [options] [-- program args...]
function runcpp {
  $mode = if ($env:RUNCPP_MODE) { $env:RUNCPP_MODE } else { 'debug' }
  $std = if ($env:RUNCPP_STD) { $env:RUNCPP_STD } else { 'gnu++20' }
  $compileOnly = $false
  $timing = $false
  $source = ''
  $programArguments = @()
  $positional = @($args)
  for ($i = 0; $i -lt $positional.Count; $i++) {
    $argument = [string]$positional[$i]
    switch -CaseSensitive -Regex ($argument) {
      '^(-h|--help)$' {
        @'
Usage: runcpp [options] <src.cpp> [options] [-- program args...]

  -d, --debug         warnings + STL debug mode (+ ASan/UBSan if the compiler has them) (default)
  -r, --release       -O2, no sanitizer (judge-like)
  -c, --compile-only  compile only
  -t, --time          show elapsed time
      --std=STD       language standard (default: gnu++20)
  -h, --help          show this help

Environment:
  RUNCPP_MODE   debug | release (default mode)
  RUNCPP_CXX    compiler (default: g++)
  RUNCPP_STD    default for --std
  RUNCPP_FLAGS  extra compiler flags (e.g. "-IC:\ac-library")

Standard input: pass it through the pipeline (Get-Content in.txt | runcpp a.cpp).
'@
        return
      }
      '^(-d|--debug)$' { $mode = 'debug'; break }
      '^(-r|--release)$' { $mode = 'release'; break }
      '^(-c|--compile-only)$' { $compileOnly = $true; break }
      '^(-t|--time)$' { $timing = $true; break }
      '^--std=' { $std = $argument.Substring(6); break }
      '^--$' {
        if ($i + 1 -lt $positional.Count) {
          $programArguments += $positional[($i + 1)..($positional.Count - 1)]
        }
        $i = $positional.Count
        break
      }
      '^-' {
        Write-Error "runcpp: unknown option: $argument (pass program args after --)"
        return
      }
      default {
        if (-not $source) { $source = $argument } else { $programArguments += $argument }
      }
    }
  }
  if ($mode -ne 'debug' -and $mode -ne 'release') {
    Write-Error "runcpp: invalid mode: $mode (debug | release)"
    return
  }
  if (-not $source) {
    Write-Error 'Usage: runcpp [options] <src.cpp> [-- args...] (see: runcpp --help)'
    return
  }
  if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
    Write-Error "runcpp: $source : No such file"
    return
  }
  $compiler = if ($env:RUNCPP_CXX) { $env:RUNCPP_CXX } else { 'g++' }
  if (-not (Get-Command $compiler -CommandType Application -ErrorAction Ignore)) {
    Write-Error "runcpp: $compiler が PATH に無い (scoop install mingw-winlibs)"
    return
  }

  $flags = @("-std=$std", '-Wall', '-Wextra', '-Wl,--stack,1073741824')
  if ($mode -eq 'debug') {
    $flags += '-O0', '-g', '-fno-omit-frame-pointer', '-Wshadow', '-Wformat=2', '-Wfloat-equal', '-Wcast-qual',
      '-D_GLIBCXX_DEBUG', '-D_GLIBCXX_DEBUG_PEDANTIC', '-D_LIBCPP_HARDENING_MODE=_LIBCPP_HARDENING_MODE_DEBUG', '-DLOCAL'
    if (Test-RuncppSanitizer -Compiler $compiler) {
      $flags += '-fsanitize=address,undefined', '-fno-sanitize-recover=all'
    }
    # gcc 専用の警告 (clang に渡すと unknown warning になる)
    if ((& $compiler --version 2>&1 | Out-String) -notmatch 'clang') {
      $flags += '-Wduplicated-cond', '-Wlogical-op'
    }
  } else {
    $flags += '-O2', '-DONLINE_JUDGE'
  }
  $extra = @()
  if ($env:RUNCPP_FLAGS) {
    $extra = @($env:RUNCPP_FLAGS -split '\s+' | Where-Object { $_ })
  }

  $name = [System.IO.Path]::GetFileNameWithoutExtension($source)
  $cacheRoot = if ($env:XDG_CACHE_HOME) { $env:XDG_CACHE_HOME } else { $env:LOCALAPPDATA }
  $outputDirectory = [System.IO.Path]::Combine($cacheRoot, 'runcpp')
  $binary = [System.IO.Path]::Combine($outputDirectory, "$name-$mode.exe")
  $null = New-Item -ItemType Directory -Path $outputDirectory -Force
  & $compiler @flags $source @extra -o $binary
  if ($LASTEXITCODE -ne 0) {
    return
  }
  if ($compileOnly) {
    return
  }

  $stopwatch = [System.Diagnostics.Stopwatch]::StartNew()
  if ($MyInvocation.ExpectingInput) {
    $input | & $binary @programArguments
  } else {
    & $binary @programArguments
  }
  $exitCode = $LASTEXITCODE
  if ($timing) {
    $stopwatch.Stop()
    Write-Host ('real {0:N3}s' -f $stopwatch.Elapsed.TotalSeconds)
  }
  $global:LASTEXITCODE = $exitCode
}
