"""Windows Terminal の settings.json へ LANG2 の無効化を足す modify_ を検証する。"""

from __future__ import annotations

import difflib
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (
    ROOT
    / "home"
    / "AppData"
    / "Local"
    / "Packages"
    / "Microsoft.WindowsTerminal_8wekyb3d8bbwe"
    / "LocalState"
    / "modify_settings.json.py"
)
_spec = importlib.util.spec_from_file_location("wt_modify", SCRIPT)
assert _spec and _spec.loader
wt = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(wt)

COMMAND = {"action": "adjustOpacity", "opacity": 0, "relative": True}

NEW_FORMAT = """{
    "$help": "https://aka.ms/terminal-documentation",
    "actions": [
        {
            "command": "paste",
            "id": "User.paste"
        }
    ],
    "keybindings": [
        {
            "id": "User.paste",
            "keys": "ctrl+shift+v"
        }
    ],
    "profiles": {}
}
"""

OLD_FORMAT = """{
  "actions": [
    { "command": "paste", "keys": "ctrl+shift+v" }
  ],
  "profiles": {}
}
"""

JSONC = """// user comment
{
    "actions": [
        // keep me
        { "command": "paste", "id": "User.paste", },
    ],
    /* block, with ] and } */
    "keybindings": [
        { "id": "User.paste", "keys": "ctrl+shift+v" }, // trailing
    ],
    "profiles": { "list": [], },
}
"""


def parse(text: str):
    start = wt._skip_ws(text, 0)
    return wt._parse(text, start, wt._scan_container(text, start)[0])


def added_lines(before: str, after: str) -> list[str]:
    diff = difflib.ndiff(before.splitlines(), after.splitlines())
    assert not [line for line in diff if line.startswith("- ")]
    return [
        line[2:]
        for line in difflib.ndiff(before.splitlines(), after.splitlines())
        if line.startswith("+ ")
    ]


def assert_idempotent(text: str) -> None:
    again, warning = wt.update(text)
    assert warning is None
    assert again == text


def test_new_format_adds_action_and_keybinding():
    after, warning = wt.update(NEW_FORMAT)
    assert warning is None
    data = parse(after)
    assert {"command": COMMAND, "id": "User.ignoreImeOff"} in data["actions"]
    assert {"id": "User.ignoreImeOff", "keys": "vk(26)"} in data["keybindings"]
    assert data["profiles"] == {}
    added = added_lines(NEW_FORMAT, after)
    assert '            "id": "User.ignoreImeOff"' in added
    assert_idempotent(after)


def test_old_format_adds_inline_keys():
    after, warning = wt.update(OLD_FORMAT)
    assert warning is None
    data = parse(after)
    assert data["actions"][-1] == {"command": COMMAND, "keys": "vk(26)"}
    assert "keybindings" not in data
    assert_idempotent(after)


def test_jsonc_comments_and_trailing_commas_are_kept():
    after, warning = wt.update(JSONC)
    assert warning is None
    for kept in ("// user comment", "// keep me", "/* block, with ] and } */", "// trailing"):
        assert kept in after
    data = parse(after)
    assert data["actions"][-1]["id"] == "User.ignoreImeOff"
    assert data["keybindings"][-1] == {"id": "User.ignoreImeOff", "keys": "vk(26)"}
    added_lines(JSONC, after)
    assert_idempotent(after)


@pytest.mark.parametrize(
    "entry",
    [
        '{ "id": "User.find", "keys": "vk(26)" }',
        '{ "id": null, "keys": "VK(26)" }',
        '{ "id": "User.find", "keys": ["ctrl+f", "vk(26)"] }',
    ],
)
def test_existing_binding_is_reported_and_left_alone(entry):
    text = NEW_FORMAT.replace(
        '"keys": "ctrl+shift+v"\n        }', '"keys": "ctrl+shift+v"\n        },\n        ' + entry
    )
    after, warning = wt.update(text)
    assert after == text
    assert warning and "vk(26)" in warning


def test_old_format_binding_to_other_command_is_reported():
    text = OLD_FORMAT.replace("ctrl+shift+v", "vk(26)")
    after, warning = wt.update(text)
    assert after == text
    assert warning


def test_partial_new_format_only_adds_missing_part():
    ours = '{ "id": "User.ignoreImeOff", "keys": "vk(26)" }'
    text = NEW_FORMAT.replace(
        '"keys": "ctrl+shift+v"\n        }',
        '"keys": "ctrl+shift+v"\n        },\n        ' + ours,
    )
    after, warning = wt.update(text)
    assert warning is None
    data = parse(after)
    assert sum(1 for k in data["keybindings"] if k["id"] == "User.ignoreImeOff") == 1
    assert {"command": COMMAND, "id": "User.ignoreImeOff"} in data["actions"]


def test_empty_arrays_and_missing_keys():
    after, _ = wt.update('{\n  "actions": [],\n  "keybindings": []\n}\n')
    data = parse(after)
    assert data["actions"] == [{"command": COMMAND, "id": "User.ignoreImeOff"}]
    assert data["keybindings"] == [{"id": "User.ignoreImeOff", "keys": "vk(26)"}]
    assert_idempotent(after)

    after, _ = wt.update('{\n  "profiles": {}\n}\n')
    assert parse(after)["actions"] == [{"command": COMMAND, "keys": "vk(26)"}]
    assert_idempotent(after)


def test_empty_input_creates_new_format():
    after, warning = wt.update("")
    assert warning is None
    data = parse(after)
    assert data["keybindings"] == [{"id": "User.ignoreImeOff", "keys": "vk(26)"}]
    assert_idempotent(after)


def run_script(data: bytes) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [sys.executable, str(SCRIPT)], input=data, capture_output=True, check=True
    )


def test_bom_and_crlf_are_preserved():
    source = ("\ufeff" + NEW_FORMAT.replace("\n", "\r\n")).encode("utf-8")
    out = run_script(source).stdout
    assert out.startswith("\ufeff".encode("utf-8"))
    assert b"\n" not in out.replace(b"\r\n", b"")
    assert run_script(out).stdout == out


def test_unparsable_input_passes_through():
    source = b'{ "actions": [ oops'
    result = run_script(source)
    assert result.stdout == source
    assert b"warning" in result.stderr
