"""pi の配布物（adapters/dotfiles/dist.py）の試験。ダミーの秘密を置いて、複製後に残らないことを走査で確かめる。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from box.adapters.dotfiles import dist

DUMMY_GH = "ghp_" + "D" * 30
DUMMY_AWS = "AKIA" + "D" * 16
DUMMY_HF = "hf_" + "d" * 30


def write(root: Path, rel: str, text: str = "x", mode: int = 0o644) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    p.chmod(mode)


@pytest.fixture
def home(tmp_path: Path) -> Path:
    h = tmp_path / "home"
    # 入れてよいもの
    write(h, ".pi/agent/extensions/todo/index.ts", "export {}")
    write(h, ".pi/agent/prompts/fleet.md", "prompt")
    write(h, ".pi/agent/AGENTS.md", "rules")
    write(h, ".config/pi/harness/index.ts", "harness")
    write(h, ".config/pi/harness/run.py", "#!/usr/bin/env python3", mode=0o755)
    # 入れてはいけないもの（許可リストの中にあっても、外にあっても）
    write(h, ".pi/agent/auth.json", json.dumps({"token": DUMMY_GH}))
    write(h, ".pi/agent/sessions/a.jsonl", DUMMY_GH)
    write(h, ".pi/agent/mcp.json", json.dumps({"env": {"KEY": DUMMY_AWS}}))
    write(h, ".pi/agent/models.json", "{}")
    write(h, ".pi/agent/extensions/todo/.env", f"TOKEN={DUMMY_HF}")
    write(h, ".pi/agent/extensions/todo/.env.local", f"TOKEN={DUMMY_HF}")
    write(h, ".pi/agent/extensions/todo/trace.jsonl", DUMMY_GH)
    write(h, ".ssh/id_ed25519", "-----BEGIN OPENSSH " + "PRIVATE KEY-----")
    write(h, ".aws/credentials", DUMMY_AWS)
    write(h, ".config/gh/hosts.yml", DUMMY_GH)
    write(h, ".bash_history", "history")
    return h


def all_files(root: Path) -> list[str]:
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())


def test_許可リストの名前だけを複製する(home, tmp_path):
    copied = dist.build_dist(home, tmp_path / "out")
    assert ".pi/agent/extensions/todo/index.ts" in copied
    assert ".pi/agent/prompts/fleet.md" in copied
    assert ".pi/agent/AGENTS.md" in copied
    assert ".config/pi/harness/index.ts" in copied
    assert all_files(tmp_path / "out") == copied


def test_認証_履歴_箱用に生成するものは複製しない(home, tmp_path):
    out = tmp_path / "out"
    dist.build_dist(home, out)
    files = all_files(out)
    for banned in (
        "auth.json",
        "mcp.json",
        "models.json",
        ".env",
        "sessions",
        ".jsonl",
        "id_ed25519",
        "credentials",
        "hosts.yml",
        "history",
    ):
        assert not any(banned in f for f in files), banned


def test_複製後の走査でダミーの秘密が残っていない(home, tmp_path):
    out = tmp_path / "out"
    dist.build_dist(home, out)
    assert dist.scan_secrets(out) == []
    blob = "".join(
        p.read_text(encoding="utf-8", errors="replace") for p in out.rglob("*") if p.is_file()
    )
    for secret in (DUMMY_GH, DUMMY_AWS, DUMMY_HF):
        assert secret not in blob


def test_許可リストの中に秘密らしい内容があれば止まり配布物を消す(home, tmp_path):
    write(home, ".pi/agent/extensions/todo/leak.ts", f'const t = "{DUMMY_GH}"')
    out = tmp_path / "out"
    with pytest.raises(dist.DistError) as err:
        dist.build_dist(home, out)
    assert "leak.ts" in str(err.value)
    assert DUMMY_GH not in str(err.value)  # 値は報告に出さない
    assert not out.exists()


@pytest.mark.parametrize(
    "content",
    [
        DUMMY_AWS,
        DUMMY_HF,
        "sk-" + "a" * 30,
        "-----BEGIN RSA " + "PRIVATE KEY-----",
        '"refresh_token": "' + "r" * 30 + '"',
        "Authorization: Bearer " + "b" * 30,
    ],
)
def test_秘密らしい文字列の検出(tmp_path, content):
    write(tmp_path, "a/file.txt", content)
    assert dist.scan_secrets(tmp_path)


def test_普通のコードは誤検出しない(tmp_path):
    write(tmp_path, "a/code.ts", "const task = 'disk-usage'; // ghp_ の説明だけ\nconst x = 'sk-'")
    assert dist.scan_secrets(tmp_path) == []


def test_許可リストの外は入れない(home, tmp_path):
    out = tmp_path / "out"
    dist.build_dist(home, out)
    assert not (out / ".ssh").exists()
    assert not (out / ".aws").exists()
    assert not (out / ".config/gh").exists()


def test_許可リストを狭めるとその分だけ入る(home, tmp_path):
    copied = dist.build_dist(home, tmp_path / "out", allow=(".pi/agent/prompts",))
    assert copied == [".pi/agent/prompts/fleet.md"]


def test_symlinkは辿らず外のファイルを引き込まない(home, tmp_path):
    secret = tmp_path / "outside.txt"
    secret.write_text("outside", encoding="utf-8")
    (home / ".pi/agent/prompts/link.md").symlink_to(secret)
    out = tmp_path / "out"
    copied = dist.build_dist(home, out)
    assert ".pi/agent/prompts/link.md" not in copied


def test_不正な許可名は拒否する(home, tmp_path):
    for bad in ("../x", "/etc"):
        with pytest.raises(dist.DistError):
            dist.build_dist(home, tmp_path / "out", allow=(bad,))


def test_実行権限は保たれ_それ以外は0644(home, tmp_path):
    out = tmp_path / "out"
    dist.build_dist(home, out)
    assert (out / ".config/pi/harness/run.py").stat().st_mode & 0o777 == 0o755
    assert (out / ".pi/agent/AGENTS.md").stat().st_mode & 0o777 == 0o644


def test_再生成は前回の残りを消す(home, tmp_path):
    out = tmp_path / "out"
    write(out, "stale.txt", "old")
    dist.build_dist(home, out)
    assert not (out / "stale.txt").exists()


def test_箱用のsettingsは秘密を含まない最小のもの():
    s = json.loads(dist.settings_json())
    assert set(s) <= {"theme", "defaultThinkingLevel"}
    assert json.loads(dist.settings_json({"httpProxy": "http://127.0.0.1:3128"}))["httpProxy"]


def test_実リポジトリの元ファイルが許可リストに一致する():
    """許可リストの名前が chezmoi の source state に実在する（取り違えの検出）。"""
    root = Path(__file__).resolve().parents[2] / "home"
    assert (root / "dot_pi/agent/extensions").is_dir()
    assert (root / "dot_config/pi/harness").is_dir()
    assert ".pi/agent/extensions" in dist.DEFAULT_ALLOW
    assert ".config/pi/harness" in dist.DEFAULT_ALLOW
