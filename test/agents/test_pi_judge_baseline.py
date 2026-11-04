"""判定の退行検知 (``golden/ts_baseline.jsonl`` と意図した差の台帳) の試験。

現行の TS 判定器の出力が baseline と一致すること、差が出たときに強さで分類して台帳に無ければ落ちること、
真理値表の入力が baseline に入っていること、コーパスの出力にコマンド文字列を出さないことを確かめる。

see docs/spec/guard/pi-decide.md#判定の退行検知baseline-と意図した差の台帳
"""

from __future__ import annotations

import hashlib
import json
import subprocess

import pytest
from agents_common import ROOT
from test_pi_judge_ts import _node

pytestmark = pytest.mark.skipif(_node() is None, reason="型除去に対応した node (22.18 以上) が無い")

PI = ROOT / "test" / "agents" / "pi"
GOLDEN = ROOT / "test" / "agents" / "golden"
BASELINE = GOLDEN / "ts_baseline.jsonl"
LEDGER = GOLDEN / "intended_changes.jsonl"
LEDGER_KEYS = {"kind", "input", "role", "mode", "old", "new", "class", "reason", "approver"}
LEDGER_CLASSES = {"relax", "tighten", "false-positive", "neutral"}
MODES = {"ask", "bypass", "boundary", "bypass+boundary"}


def _run(script, *args):
    return subprocess.run(
        [_node(), "--experimental-strip-types", "--no-warnings", str(PI / script), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
        timeout=300,
        check=False,
    )


def _rows(path=BASELINE):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _label(row):
    kind = "mustConfirm" if row["decision"] == "ask" and row.get("mustConfirm") else row["decision"]
    return f"{kind}/{row['source']}/{hashlib.sha1(row['reason'].encode()).hexdigest()[:8]}"


def _check_ledger_format(entries):
    seen = set()
    for e in entries:
        assert set(e) >= LEDGER_KEYS, e
        assert e["class"] in LEDGER_CLASSES, e
        if e["class"] == "relax":
            assert e["approver"], f"relax は承認者が要る: {e}"
        key = json.dumps(
            [e["kind"], e.get("id", ""), e["role"], e["mode"], e["input"], e["old"], e["new"]]
        )
        assert key not in seen, f"台帳の重複: {e}"
        seen.add(key)


def test_current_output_equals_the_baseline():
    proc = _run("judge_baseline.mjs", "--check")
    assert proc.returncode == 0, (proc.stdout + proc.stderr)[-2000:]
    proc = _run("judge_diff.mjs")
    assert proc.returncode == 0, (proc.stdout + proc.stderr)[-2000:]
    assert "台帳に無い 0 件" in proc.stdout


def test_ledger_format_is_valid():
    text = LEDGER.read_text(encoding="utf-8") if LEDGER.exists() else ""
    _check_ledger_format([json.loads(line) for line in text.splitlines() if line])
    with pytest.raises(AssertionError):
        _check_ledger_format([{"kind": "decide", "class": "bogus"}])
    dup = dict.fromkeys(LEDGER_KEYS, "a") | {"class": "neutral"}
    with pytest.raises(AssertionError):
        _check_ledger_format([dup, dup])


def test_the_baseline_has_the_three_kinds_with_short_rows():
    rows = _rows()
    kinds = {r["kind"] for r in rows}
    assert kinds == {"decide", "truth", "check"}
    assert len(rows) > 9000
    for r in rows:
        if r["kind"] == "check":
            assert set(r) == {"kind", "id", "input", "result"}
        else:
            assert {"kind", "input", "role", "mode", "decision", "reason", "source"} <= set(r)
            assert r["mode"] in MODES or r["mode"].startswith("bypass="), r["mode"]


TRUTH_SAMPLES = [
    "git clean -fd && gh api -X POST repos/o/r/issues -f title=x",
    "git status && git branch -D x",
    "FOO=1 git clean -fd",
    "cd sub && git tag -d v1",
    "git log; unknown_command_xyz",
    "git status && unknown_command_xyz",
    "git log | unknown_command_xyz",
    "git log --output=x.txt",
    "git diff --output=x",
    "git log --exec-path=/tmp",
    "git push",
    "git branch -D x",
    "git worktree remove .tmp/worktrees/x",
    "git restore --staged a.txt",
    "git worktree remove -f .tmp/worktrees/x",
    "ssh h git worktree remove x",
    "env git push",
    "bash -c 'git push'",
    "sudo git push",
    "ssh h 'git push'",
    "echo x | xargs git push",
    "find . -exec git push ;",
    "git $x",
    "$(echo git) push",
    "`echo git` push",
    "g=git; $g push",
    'echo "git push"',
    "cat <<EOF\ngit push\nEOF",
    'git commit -m "git push を直した"',
    "echo x > ../other",
    "echo x | tee ../other",
    "cat > f <<EOF\nx\nEOF",
]


def test_truth_table_covers_every_role_and_mode():
    common = json.loads((GOLDEN / "common.json").read_text(encoding="utf-8"))
    roles = set(common["pi"]["profiles"])
    assert {"explorer", "reader", "worker", "implementer"} <= roles
    seen = {}
    for r in _rows():
        if r["kind"] == "truth":
            seen.setdefault(r["input"], set()).add((r["role"], r["mode"]))
    for command in TRUTH_SAMPLES:
        assert seen.get(command) == {(role, mode) for role in roles for mode in MODES}, command


def _mutate(tmp_path):
    """baseline を、強さを下げた行・上げた行・理由だけ変えた行を含む形に書き換える (現行から見て relax / tighten / reason)。"""
    rows = _rows()
    picked = {}
    for i, r in enumerate(rows):
        if r["kind"] != "decide":
            continue
        if "relax" not in picked and r["decision"] == "allow":
            picked["relax"] = i
        elif "tighten" not in picked and r["decision"] == "deny":
            picked["tighten"] = i
        elif "reason" not in picked and r["decision"] == "ask" and not r.get("mustConfirm"):
            picked["reason"] = i
    assert set(picked) == {"relax", "tighten", "reason"}
    old = {}
    for cls, i in picked.items():
        row = dict(rows[i])
        cur = dict(row)
        if cls == "relax":
            row["decision"] = "deny"
            row.pop("mustConfirm", None)
        elif cls == "tighten":
            row["decision"] = "allow"
        else:
            row["reason"] += " (古い理由)"
        rows[i] = row
        old[cls] = (row, cur)
    path = tmp_path / "baseline.jsonl"
    path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8"
    )
    return path, old


def test_diff_classifies_by_strength_and_the_ledger_lets_them_through(tmp_path):
    base, old = _mutate(tmp_path)
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text("", encoding="utf-8")
    proc = _run("judge_diff.mjs", "--baseline", str(base), "--ledger", str(ledger))
    assert proc.returncode == 1, proc.stdout[-2000:]
    assert "差 3 件 (台帳に無い 3 件" in proc.stdout
    for cls in ("relax", "tighten", "reason"):
        assert f'"{cls}":1' in proc.stdout, proc.stdout
        assert f'"class":"{cls}"' in proc.stdout

    entries = []
    for cls, (before, now) in old.items():
        entries.append(
            {
                "kind": before["kind"],
                "input": before["input"],
                "role": before["role"],
                "mode": before["mode"],
                "old": _label(before),
                "new": _label(now),
                "class": "neutral" if cls == "reason" else cls,
                "reason": "試験",
                "approver": "user",
            }
        )
    _check_ledger_format(entries)
    ledger.write_text(
        "\n".join(json.dumps(e, ensure_ascii=False) for e in entries) + "\n", encoding="utf-8"
    )
    proc = _run("judge_diff.mjs", "--baseline", str(base), "--ledger", str(ledger))
    assert proc.returncode == 0, proc.stdout[-2000:]

    # 差の出ていない台帳の行は警告 (古い台帳)。終了コードは変えない
    stale = dict(entries[0], new="allow/default/00000000")
    ledger.write_text(json.dumps(stale) + "\n", encoding="utf-8")
    proc = _run("judge_diff.mjs", "--baseline", str(base), "--ledger", str(ledger))
    assert proc.returncode == 1
    assert "古い台帳" in proc.stderr


def test_corpus_prints_only_a_distribution_without_commands(tmp_path):
    marker = "echo corpus_marker_qzv9"
    corpus = tmp_path / "corpus.json"
    corpus.write_text(json.dumps([marker, "git push"]), encoding="utf-8")
    proc = _run("judge_diff.mjs", "--corpus", str(corpus))
    assert proc.returncode == 0, proc.stderr[-2000:]
    assert "corpus_marker_qzv9" not in proc.stdout + proc.stderr
    assert "baseline に無い入力 1 件" in proc.stdout
    assert "implementer/ask/" in proc.stdout
