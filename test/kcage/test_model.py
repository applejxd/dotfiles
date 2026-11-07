"""scripts/kcage/model.py の試験。型の不変条件と、固定値・厳しさの規則。"""

from __future__ import annotations

import dataclasses

import pytest
from kcage import model


def test_secret_ref_repr_hides_source_details() -> None:
    ref = model.SecretRef("gh-pat", "file", path="/etc/kcage/secret/gh-pat")
    text = repr(ref)
    assert "gh-pat" in text
    assert "/etc/kcage/secret" not in text


def test_types_are_frozen() -> None:
    op = model.Op("host", ("incus", "list"), "一覧")
    with pytest.raises(dataclasses.FrozenInstanceError):
        op.desc = "変更"  # type: ignore[misc]


def test_port_range_contains() -> None:
    r = model.PortRange(9000, 9099)
    assert r.contains(9000) and r.contains(9099)
    assert not r.contains(8999) and not r.contains(9100)


@pytest.mark.parametrize(
    ("policy", "requested", "expected"),
    [
        ("nat", None, "nat"),
        ("nat", "proxy-only", "proxy-only"),
        ("nat", "offline", "offline"),
        ("proxy-only", "nat", "proxy-only"),  # 緩める要求は効かない
        ("proxy-only", "offline", "offline"),
        ("offline", "nat", "offline"),
        ("offline", "proxy-only", "offline"),
    ],
)
def test_effective_network_only_tightens(policy: str, requested: str | None, expected: str) -> None:
    assert model.effective_network(policy, requested) == expected  # type: ignore[arg-type]


def test_box_name_prefix() -> None:
    assert model.box_name("slam") == "kcage-slam"


def test_fixed_values_are_loopback_and_wsl_paths() -> None:
    assert model.LOOPBACK == "127.0.0.1"
    assert model.GPU_LIB == "/usr/lib/wsl/lib"
    assert model.GPU_DRIVERS == "/usr/lib/wsl/drivers"
    assert model.GPU_DEVICE == "/dev/dxg"


def test_model_has_no_dotfiles_imports() -> None:
    """切り出しを見据えて、標準ライブラリ以外を import しない。"""
    import ast
    from pathlib import Path

    tree = ast.parse(Path(model.__file__).read_text(encoding="utf-8"))
    mods = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    mods |= {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    assert mods <= {"__future__", "collections.abc", "dataclasses", "typing"}
