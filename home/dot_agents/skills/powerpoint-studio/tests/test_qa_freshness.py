from pathlib import Path

from scripts.validate_deck import sha256


def test_sha256_changes_with_file_content(tmp_path: Path) -> None:
    path = tmp_path / "artifact.bin"
    path.write_bytes(b"one")
    first = sha256(path)
    path.write_bytes(b"two")
    assert sha256(path) != first
