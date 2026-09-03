#!/usr/bin/env python3
"""Fetch arXiv metadata, abstract HTML, and source into a local directory."""

from __future__ import annotations

import argparse
import io
import re
import tarfile
import urllib.request
from pathlib import Path, PurePosixPath

ARXIV_ID = re.compile(
    r"(?:arxiv\.org/(?:abs|pdf|html|src)/)?"
    r"(?P<id>(?:\d{4}\.\d{4,5}|[a-z-]+(?:\.[A-Z]{2})?/\d{7})(?:v\d+)?)"
    r"(?:\.pdf)?$",
    re.IGNORECASE,
)


def parse_arxiv_id(value: str) -> str:
    match = ARXIV_ID.search(value.strip().rstrip("/"))
    if not match:
        raise ValueError(f"arXiv ID を抽出できません: {value}")
    return match.group("id")


def download(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "arxiv-paper-ja/1.0"})
    with urllib.request.urlopen(request, timeout=120) as response:
        return response.read()


def safe_extract_tar(data: bytes, destination: Path) -> None:
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:*") as archive:
        for member in archive.getmembers():
            path = PurePosixPath(member.name)
            if path.is_absolute() or ".." in path.parts:
                raise ValueError(f"安全でないアーカイブパス: {member.name}")
            if member.issym() or member.islnk():
                raise ValueError(f"リンクを含むアーカイブは展開しません: {member.name}")
        archive.extractall(destination, filter="data")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("url_or_id")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    arxiv_id = parse_arxiv_id(args.url_or_id)
    output = args.output.resolve()
    source = output / "source"
    source.mkdir(parents=True, exist_ok=True)

    (output / "metadata.xml").write_bytes(
        download(f"https://export.arxiv.org/api/query?id_list={arxiv_id}")
    )
    (output / "abs.html").write_bytes(download(f"https://arxiv.org/abs/{arxiv_id}"))
    source_data = download(f"https://export.arxiv.org/e-print/{arxiv_id}")
    (output / "source.download").write_bytes(source_data)

    try:
        safe_extract_tar(source_data, source)
    except tarfile.TarError:
        (source / "source.tex").write_bytes(source_data)

    print(f"arXiv ID: {arxiv_id}")
    print(f"Output: {output}")


if __name__ == "__main__":
    main()
