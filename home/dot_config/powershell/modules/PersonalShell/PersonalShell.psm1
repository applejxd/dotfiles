# 個人 PC (applejxd) だけの関数。bash / zsh の shellrc.sh の同名の関数に相当する。
# profile.ps1.tmpl が、個人 PC のときだけ読み込む (他の PC には配らない。.chezmoiignore.tmpl)。
# see docs/spec/shell.md#bashzsh-と-powershell-の対応

# コーディング試験の練習用。初回のプロファイル設定は
# see docs/spec/dev-environment.md#コーディング試験の練習用-vs-codecode-exam
function code-exam {
  $directory = [System.IO.Path]::Combine($HOME, 'coding-test', (Get-Date -Format 'yyyy-MM-dd'))
  $null = New-Item -ItemType Directory -Path $directory -Force
  code --disable-extensions --profile coding-test $directory
}

# yt-dlp (mise が入れる) で ~/Downloads へ保存する
function audio-dl {
  param([Parameter(Mandatory, Position = 0)][string]$Url)

  yt-dlp --ignore-errors --output "$HOME\Downloads\%(title)s.%(ext)s" --extract-audio --audio-format mp3 --embed-thumbnail $Url
}

function video-dl {
  param([Parameter(Mandatory, Position = 0)][string]$Url)

  yt-dlp --ignore-errors --output "$HOME\Downloads\%(title)s.%(ext)s" --recode-video mp4 --add-metadata $Url
}
