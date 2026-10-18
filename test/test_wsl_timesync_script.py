"""WSL 用スクリプト (120_wsl) の時刻同期まわりの回帰テスト (静的)。

see docs/spec/structure.md#wsl-の時刻同期
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "home/.chezmoiscripts/100_linux/run_once_after_120_wsl.sh.tmpl"


def _text() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def test_wsl_script_masks_timesyncd_not_just_disables_it():
    # disable だけでは動いているサービスは止まらない。止めて mask する (Canonical の推奨 + 実測)
    text = _text()
    assert "systemctl mask --now systemd-timesyncd.service" in text
    assert "systemctl disable" not in text


def test_wsl_script_restores_a_skewed_tick_to_the_nominal_value():
    # timesyncd を止めても、偏った tick は誰かが戻すまで残る
    text = _text()
    assert "ADJ_TICK" in text
    assert "SC_CLK_TCK" in text


def test_wsl_script_only_touches_the_clock_when_systemd_is_running():
    # 初回は systemd=true を書いた直後で、systemd が動いていないことがある
    text = _text()
    assert text.count("-d /run/systemd/system") >= 2


def test_wsl_script_skips_the_clock_handling_for_isolated_distros():
    # 隔離ディストロ ([automount] enabled=false) は早期終了。sandbox は guest/setup.sh が mask する
    text = _text()
    assert text.index("exit 0") < text.index("systemctl mask --now")
