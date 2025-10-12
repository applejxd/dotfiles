function dls { docker ps -a }

function dim { docker images }

function dclean { docker container prune }

function drun {
  $selected_line = docker images | Select-Object -Skip 1 | fzf
  # null 文字を削除 & 空白区切り & 空の要素を削除
  $image_info = ($selected_line -replace "`0", "").Split(" ") -ne ""
  $image = $image_info[0] + ":" + $image_info[1]
  if (!([string]::IsNullOrEmpty($image))) {
    docker run -it --rm --gpus all "$image"
  }
}

function drmi {
  $selected_line = docker images | Select-Object -Skip 1 | fzf
  # null 文字を削除 & 空白区切り & 空の要素を削除
  $image_info = ($selected_line -replace "`0", "").Split(" ") -ne ""
  if (!([string]::IsNullOrEmpty($image_info))) {
    docker rmi $image_info[2]
  }
}

function dsh {
  $cid = (docker ps -a | Select-Object -Skip 1 | fzf).Split(" ")[0]
  if (!([string]::IsNullOrEmpty($cid))) {
    docker exec -it "$cid" /bin/bash
  }
}

function da {
  $cid = (docker ps -a | Select-Object -Skip 1 | fzf).Split(" ")[0]
  if (!([string]::IsNullOrEmpty($cid))) {
    docker start "$cid"
    docker attach "$cid"
  }
}

function ds {
  $cid = (docker ps -a | Select-Object -Skip 1 | fzf).Split(" ")[0]
  if (!([string]::IsNullOrEmpty($cid))) {
    docker stop "$cid"
  }
}

function drm {
  $cid = (docker ps -a | Select-Object -Skip 1 | fzf).Split(" ")[0]
  if (!([string]::IsNullOrEmpty($cid))) {
    docker rm "$cid"
  }
}

function dbuild() {
  $file_name = $(Get-ChildItem -Name | Where-Object { $_ -match '^.*[D|d]ockerfile' } | fzf)
  $date_tag = $(Get-Date -Format "yyyy.MM.dd")
  $cname = "local/" + $file_name.Split(".")[0] + ":" + "$date_tag"
  if (!([string]::IsNullOrEmpty($cname))) {
    docker build -t $cname.ToLower() -f "$file_name" .
  }
}

function dcom() {
  $file_name = $(Get-ChildItem -Recurse -Name -File *.yml | fzf)
  if (!([string]::IsNullOrEmpty($fine_name))) {
    docker-compose -f "$file_name" up -d
  }
}
