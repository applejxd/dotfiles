"""`harness/session-tmp.ts` (セッションごとの一時置き場。CHG-0042 段 3) の表試験。

``test/agents/pi/session_tmp_driver.mjs`` が使い捨ての作業ツリーで動かし、結果を JSON で出す。
node の型除去を使うので、22.18 未満の node では飛ばす。
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from test_pi_judge_ts import _node

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DRIVER = HERE / "pi" / "session_tmp_driver.mjs"
HARNESS_INDEX = ROOT / "home" / "dot_config" / "pi" / "harness" / "index.ts"

pytestmark = pytest.mark.skipif(_node() is None, reason="型除去に対応した node (22.18 以上) が無い")


@pytest.fixture(scope="module")
def table() -> dict:
    proc = subprocess.run(
        [_node(), str(DRIVER)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
        timeout=120,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-1500:]
    return json.loads(proc.stdout)


def test_the_directory_is_named_by_the_random_tail_of_the_session_id(table) -> None:
    c = table["create"]
    # UUIDv7 の先頭 8 文字は時刻 (約 65 秒は同じ) なので、末尾を使う
    assert c["dir_rel"] == "/.tmp/s/deadbeef"
    assert c["id_tail"] == "0a7bf075"
    assert c["id_tail_short"] == "000000ab"


def test_it_points_tmpdir_to_the_directory_and_records_the_owner(table) -> None:
    c = table["create"]
    assert c["tmpdir_is_dir"] is True
    assert c["owner_pid_is_self"] is True
    assert c["owner_keys"] == ["host", "pid", "pidns", "start"]
    assert (c["mode_dir"], c["mode_owner"]) == ("700", "600")


def test_it_does_nothing_without_a_real_tmp_directory_or_when_disabled(table) -> None:
    s = table["skip"]
    assert s["no_tmp"] is None  # `.tmp` を勝手に作らない
    assert s["tmp_symlink"] is None
    assert s["disabled"] is None  # 子・pis の内側・Windows
    assert s["s_symlink"] is None
    assert s["tmpdir_unchanged"] is True
    assert s["elsewhere_empty"] is True  # リンク先へ書かない


def test_only_quit_removes_and_it_removes_every_directory_this_process_made(table) -> None:
    lc = table["lifecycle"]
    assert lc["reload_same"] is True  # reload は同じセッションなので、同じ置き場
    assert lc["distinct"] is True
    for reason in ("reload", "new", "resume", "fork"):
        # 会話が旧置き場のパスを参照し続けるので、消さない
        assert lc["kept"][reason] == {"removed": 0, "d1": True, "d2": True}, reason
    assert lc["quit_removed"] == 2
    assert lc["d1_after"] is False and lc["d2_after"] is False
    assert lc["kept_after"] == 0


def test_a_colliding_name_of_another_session_is_never_touched(table) -> None:
    c = table["collision"]
    assert c["tail_len"] == 12  # 末尾を伸ばした
    assert c["other_intact"] is True
    assert c["own_removed"] is True


def test_a_too_long_path_is_not_used(table) -> None:
    assert table["long_path"]["dir"] is None  # ソケットのパス長の上限


def test_it_does_not_remove_a_directory_a_live_process_still_uses(table) -> None:
    s = table["survivors"]
    assert s["found"] is True
    assert s["blocked_removed"] == 0
    assert s["dir_kept_while_alive"] is True
    assert s["removed_after_exit"] == 1
    assert s["dir_after"] is False


def test_startup_sweep_removes_only_what_it_can_prove_is_dead(table) -> None:
    w = table["sweep"]
    assert w["started"] is True
    assert w["dead_removed"] is True
    assert w["live_kept"] is True
    assert w["unknown_kept"] is True  # `.owner` が無いものは、死亡を確証できないので残す
    assert w["unknown_name_kept"] is True  # 未知の名前は消さない
    assert w["stamp"] is True
    assert w["disposable_kept_on_second_run"] is True  # 1 日に 1 回までは、s/ の回収だけ
    assert w["disposable_removed_when_stamp_old"] is True


def test_the_harness_wires_it_for_the_parent_only_and_only_quit_removes() -> None:
    src = HARNESS_INDEX.read_text(encoding="utf-8")
    assert 'import { SessionTmp } from "./session-tmp.ts";' in src
    # 子・pis の内側 (TMPDIR=/tmp)・Windows では何もしない
    assert '!CHILD && process.env.PI_HARNESS_BOUNDARY !== "1" && !isWindows()' in src
    assert "sessionTmp.teardown(" in src
    assert 'event?.reason === "startup"' in src
