function dls { docker ps -a }

function dim { docker images }

function dclean { docker container prune }

function drun {
  $image = docker image ls --format '{{.Repository}}:{{.Tag}}' | fzf
  if (-not [string]::IsNullOrWhiteSpace($image)) {
    docker run -it --rm --gpus all $image
  }
}

function drmi {
  $selectedLine = docker image ls --format "{{.ID}}`t{{.Repository}}:{{.Tag}}" | fzf
  if (-not [string]::IsNullOrWhiteSpace($selectedLine)) {
    $imageId = $selectedLine.Split("`t", 2)[0]
    docker rmi $imageId
  }
}

function dsh {
  $selectedLine = docker ps -a --format "{{.ID}}`t{{.Names}}`t{{.Image}}`t{{.Status}}" | fzf
  if (-not [string]::IsNullOrWhiteSpace($selectedLine)) {
    $containerId = $selectedLine.Split("`t", 2)[0]
    docker exec -it $containerId /bin/bash
  }
}

function da {
  $selectedLine = docker ps -a --format "{{.ID}}`t{{.Names}}`t{{.Image}}`t{{.Status}}" | fzf
  if (-not [string]::IsNullOrWhiteSpace($selectedLine)) {
    $containerId = $selectedLine.Split("`t", 2)[0]
    docker start $containerId
    docker attach $containerId
  }
}

function ds {
  $selectedLine = docker ps -a --format "{{.ID}}`t{{.Names}}`t{{.Image}}`t{{.Status}}" | fzf
  if (-not [string]::IsNullOrWhiteSpace($selectedLine)) {
    docker stop $selectedLine.Split("`t", 2)[0]
  }
}

function drm {
  $selectedLine = docker ps -a --format "{{.ID}}`t{{.Names}}`t{{.Image}}`t{{.Status}}" | fzf
  if (-not [string]::IsNullOrWhiteSpace($selectedLine)) {
    docker rm $selectedLine.Split("`t", 2)[0]
  }
}

function dbuild {
  $fileName = Get-ChildItem -File | Where-Object Name -Match '(?i)dockerfile' |
    Select-Object -ExpandProperty Name | fzf
  if (-not [string]::IsNullOrWhiteSpace($fileName)) {
    $dateTag = Get-Date -Format "yyyy.MM.dd"
    $imageName = "local/$([IO.Path]::GetFileNameWithoutExtension($fileName)):$dateTag"
    docker build -t $imageName.ToLowerInvariant() -f $fileName .
  }
}

function dcom {
  $fileName = Get-ChildItem -Recurse -File -Include (
    'compose.yaml', 'compose.yml', 'docker-compose.yaml', 'docker-compose.yml'
  ) -ErrorAction Ignore | Select-Object -ExpandProperty FullName | fzf
  if (-not [string]::IsNullOrWhiteSpace($fileName)) {
    docker compose -f $fileName up -d
  }
}
