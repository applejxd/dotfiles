# git と fzf を組み合わせた関数 (bash / zsh の fzf/git.sh と fzf/core.sh の gwq 関数に相当)。
# Windows PowerShell 5.1 と PowerShell 7 の両方で動かす。対話セッションだけで読み込む。
# fzf・git・gwq は呼び出し時に使うので、無い機でも読み込みは成功する。
# see docs/spec/shell.md#bashzsh-と-powershell-の対応

function Test-GitRepository {
  git rev-parse --git-dir *> $null
  $LASTEXITCODE -eq 0
}

# fbr: ブランチを選んで checkout する
function fbr {
  $branch = git branch -vv | fzf +m
  if ($branch) {
    # 現在のブランチ (`* `) と他の worktree のブランチ (`+ `) の印だけを除く
    git checkout ((($branch -replace '^[*+ ] ', '') -split '\s+')[0])
  }
}

# fbrm: リモートのブランチも含めて選び、checkout する
function fbrm {
  $branch = git branch --all | Where-Object { $_ -notmatch 'HEAD' } | fzf +m
  if ($branch) {
    git checkout ((($branch.Trim() -split '\s+')[-1]) -replace '^remotes/[^/]+/', '')
  }
}

# fshow: コミットのグラフから選び、Enter で内容を見る。閉じると一覧へ戻る (Esc で終わる)
function fshow {
  $esc = [char]27
  while ($true) {
    $line = git log --graph --color=always --format='%C(auto)%h%d %s %C(black)%C(bold)%cr' @args |
      fzf --ansi --no-sort --reverse --tiebreak=index --bind=ctrl-s:toggle-sort
    # Esc で終わると何も出力されない (終了コードは、パイプラインの形によっては取れないので見ない)
    if (-not $line) {
      break
    }
    $hash = [regex]::Match(($line -replace "$esc\[[0-9;]*m", ''), '[0-9a-f]{7,}').Value
    if ($hash) {
      git show --color=always $hash
    }
  }
}

# cdworktree: worktree を選んで移動する
function cdworktree {
  if (-not (Test-GitRepository)) {
    Write-Warning 'fatal: Not a git repository.'
    return
  }
  # `git worktree list --porcelain` の `worktree <パス>` の行からパスを取る (表示の行を切り出すと、
  # 空白を含むパスを取り違える)。fzf には `<番号><TAB><パス> [<ブランチ>]` を渡し、番号から対応付ける
  $records = [System.Collections.Generic.List[object]]::new()
  foreach ($row in @(git -c core.quotepath=off worktree list --porcelain)) {
    if ($row.StartsWith('worktree ')) {
      $records.Add([pscustomobject]@{ Path = $row.Substring(9); Label = '' })
    } elseif ($records.Count -and $row.StartsWith('branch ')) {
      $records[$records.Count - 1].Label = '[' + ($row.Substring(7) -replace '^refs/heads/', '') + ']'
    } elseif ($records.Count -and $row -eq 'detached') {
      $records[$records.Count - 1].Label = '(detached HEAD)'
    } elseif ($records.Count -and $row -eq 'bare') {
      $records[$records.Count - 1].Label = '(bare)'
    }
  }
  if (-not $records.Count) {
    return
  }
  $candidates = for ($index = 0; $index -lt $records.Count; $index++) {
    "$index`t$($records[$index].Path)  $($records[$index].Label)"
  }
  $line = $candidates | fzf --delimiter "`t" --with-nth '2..'
  if (-not $line) {
    return
  }
  Set-Location -LiteralPath $records[[int]($line.Split("`t")[0])].Path
}

# fadd: 変更したファイルを選んで git add する。Ctrl-D で差分を見る。Esc で終わる
function fadd {
  while ($true) {
    # --expect の出力は、1 行目が押されたキー (Enter は空)、2 行目以降が選択
    $out = @(
      git -c core.quotepath=off ls-files -m -o --exclude-standard |
        fzf --exit-0 --expect=ctrl-d
    )
    if ($out.Count -lt 2) {
      break
    }
    $files = @($out[1..($out.Count - 1)] | Where-Object { $_ })
    if (-not $files) {
      continue
    }
    if ($out[0] -eq 'ctrl-d') {
      # --literal-pathspecs: `[ab].txt` のような名前を、パターンとして解釈させない
      git --literal-pathspecs diff --color=always -- $files
    } else {
      git --literal-pathspecs add -- $files
    }
  }
}

# xgw: gwq の worktree を選んで移動する
function xgw {
  if (-not (Test-ExternalCommand gwq)) {
    Write-Error 'gwq が PATH に無い'
    return
  }
  $selected = gwq list | fzf
  if ($selected) {
    Set-Location -LiteralPath (gwq get $selected)
  }
}

# gwcode: gwq の worktree を選んで VS Code で開く
function gwcode {
  if (-not (Test-ExternalCommand gwq)) {
    Write-Error 'gwq が PATH に無い'
    return
  }
  $selected = gwq list | fzf
  if ($selected) {
    gwq exec $selected -- code .
  }
}
