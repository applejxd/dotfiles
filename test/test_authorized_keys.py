"""Bitwarden の SSH 鍵項目から公開鍵を authorized_keys へ追加するスクリプトの静的検査。

実際の鍵・Bitwarden には触れない。see docs/spec/security.md#ssh-公開鍵の-authorized_keys-への追加
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = {
    "unix": ROOT / "home/.chezmoiscripts/400_unix/run_after_440_authorized_keys.sh.tmpl",
    "windows": ROOT / "home/.chezmoiscripts/300_windows/run_after_348_authorized_keys.ps1.tmpl",
}
BACKSLASH = chr(92)
# テンプレートの Go 文字列では、正規表現のバックスラッシュ 1 文字を 4 文字で書く
APPLEJXD_GATE = 'regexMatch "(?i)(^|' + BACKSLASH * 4 + ')applejxd$" .chezmoi.username'


def _read(name: str) -> str:
    return SCRIPTS[name].read_text(encoding="utf-8-sig")


def test_scripts_are_limited_to_applejxd_and_skip_without_a_session():
    for name in SCRIPTS:
        script = _read(name)
        assert APPLEJXD_GATE in script, name
        assert "BW_SESSION" in script, name
        assert ".chezmoi.hostname" in script, name


def test_scripts_never_read_or_emit_the_private_key():
    for name in SCRIPTS:
        script = _read(name)
        assert "privateKey" not in script, name
        assert "publicKey" in script, name
        # 追記だけ。既存の authorized_keys を作り直さない
        assert "Set-Content" not in script and "Out-File" not in script, name


def test_scripts_require_exactly_one_ssh_key_item():
    unix = _read("unix")
    windows = _read("windows")

    assert ".type == 5" in unix and '"$count" != "1"' in unix
    assert "$_.type -eq 5" in windows and "$items.Count -ne 1" in windows


def test_unix_script_appends_without_rewriting_existing_keys():
    script = _read("unix")

    assert '>>"$auth_file"' in script
    assert "chmod 600" in script and "chmod 700" in script


def test_windows_script_writes_utf8_without_bom_and_notes_admin_group():
    script = SCRIPTS["windows"].read_bytes()

    assert script.startswith(b"\xef\xbb\xbf")  # PowerShell 5.1 用の BOM 付き保存
    text = script.decode("utf-8-sig")
    assert "UTF8Encoding($false)" in text
    assert "administrators_authorized_keys" in text
