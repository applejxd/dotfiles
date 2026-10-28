"""状態ファイルの窓口(state_store): 更新の契約を表駆動で確かめる。

契約: プロセス間ロック → 読む → 検証 → キー単位の比較交換 → 置換。
ADR-0003 / CHANGE-0004 の「更新の契約」を参照。
"""

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import state_store as ss  # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="状態 試験 ")
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        self.path = self.dir / "yomi.json"
        self.store = ss.Store(self.path, lock_timeout=2.0, lock_stale=30.0)

    def raw(self):
        return self.path.read_bytes() if self.path.exists() else None

    def leftovers(self):
        """正本・.lock・試験の補助ファイル以外の残骸(一時ファイル)。"""
        ok = {self.path.name, "worker.py"}
        return sorted(
            p.name
            for p in self.dir.iterdir()
            if p.name not in ok and not p.name.endswith(".lock")
        )


class ReadTests(Base):
    def test_missing_file_reads_as_empty(self):
        snap = self.store.read()
        self.assertEqual(snap.entries, {})
        self.assertEqual(snap.version, self.store.read().version)

    def test_value_version_ignores_key_order_and_is_stable(self):
        a = ss.value_version({"a": 1, "b": [1, 2]})
        b = ss.value_version({"b": [1, 2], "a": 1})
        self.assertEqual(a, b)
        self.assertNotEqual(a, ss.value_version({"a": 2, "b": [1, 2]}))

    def test_japanese_keys_and_values_are_written_as_utf8(self):
        self.store.update("単眼 SLAM", None, {"読み": "タンガン"})
        text = self.raw().decode("utf-8")
        self.assertIn("単眼 SLAM", text)
        self.assertNotIn("\\u", text)
        self.assertEqual(self.store.read().entries["単眼 SLAM"], {"読み": "タンガン"})

    def test_file_is_lf_only_and_ends_with_newline(self):
        self.store.update("k", None, "v")
        raw = self.raw()
        self.assertNotIn(b"\r", raw)
        self.assertTrue(raw.endswith(b"\n"))


class CompareAndSwapTests(Base):
    """キー単位の比較交換。表: (名前, 事前の値, expected, new, 期待)。"""

    CASES = [
        ("create new key", None, None, {"v": 1}, "ok"),
        ("create but already exists", {"v": 0}, None, {"v": 1}, "conflict"),
        ("update with same value seen", {"v": 0}, {"v": 0}, {"v": 1}, "ok"),
        ("update with stale value", {"v": 2}, {"v": 0}, {"v": 1}, "conflict"),
        ("update a key that vanished", None, {"v": 0}, {"v": 1}, "conflict"),
        ("delete with value seen", {"v": 0}, {"v": 0}, None, "ok"),
        ("delete with stale value", {"v": 2}, {"v": 0}, None, "conflict"),
        ("delete a missing key is a no-op", None, None, None, "ok"),
    ]

    def test_table(self):
        for i, (name, before, expected, new, outcome) in enumerate(self.CASES):
            with self.subTest(name):
                p = self.dir / f"case{i}.json"
                store = ss.Store(p)
                if before is not None:
                    store.update("k", None, before)
                    store.update("other", None, {"keep": True})
                raw_before = p.read_bytes() if p.exists() else None
                if outcome == "ok":
                    snap = store.update("k", expected, new)
                    if new is None:
                        self.assertNotIn("k", snap.entries)
                    else:
                        self.assertEqual(snap.entries["k"], new)
                    if before is not None:
                        self.assertEqual(snap.entries["other"], {"keep": True})
                else:
                    with self.assertRaises(ss.Conflict) as cm:
                        store.update("k", expected, new)
                    self.assertEqual(cm.exception.current, before)
                    raw_after = p.read_bytes() if p.exists() else None
                    self.assertEqual(
                        raw_after, raw_before, "conflict must not touch the file"
                    )

    def test_update_does_not_disturb_other_keys_changed_meanwhile(self):
        self.store.update("a", None, 1)
        self.store.update("b", None, 1)
        # 別の書き手が b を変える。a の更新は、a の値を見た版で成功する
        self.store.update("b", 1, 2)
        snap = self.store.update("a", 1, 10)
        self.assertEqual(snap.entries, {"a": 10, "b": 2})

    def test_update_returns_snapshot_with_new_version(self):
        s1 = self.store.update("a", None, 1)
        s2 = self.store.update("a", 1, 2)
        self.assertNotEqual(s1.version, s2.version)
        self.assertEqual(s2.version, self.store.read().version)


class GuardTests(Base):
    def test_guard_runs_inside_lock_and_can_refuse(self):
        self.store.update("a", None, 1)
        before = self.raw()

        def guard():
            raise ss.Conflict({"target": "changed"})

        with self.assertRaises(ss.Conflict):
            self.store.update("a", 1, 2, guard=guard)
        self.assertEqual(self.raw(), before)
        self.assertEqual(self.leftovers(), [])

    def test_guard_sees_the_lock_held(self):
        seen = []
        self.store.update(
            "a",
            None,
            1,
            guard=lambda: seen.append((self.dir / "yomi.json.lock").exists()),
        )
        self.assertEqual(seen, [True])

    def test_lock_is_released_after_guard_failure(self):
        def guard():
            raise ss.Conflict(None)

        with self.assertRaises(ss.Conflict):
            self.store.update("a", None, 1, guard=guard)
        self.assertFalse((self.dir / "yomi.json.lock").exists())
        self.store.update("a", None, 1)  # 続けて更新できる


class CorruptionTests(Base):
    BAD = [
        ("not json", b"{ this is not json"),
        ("empty file", b""),
        ("json but not an object", b"[1, 2, 3]"),
        ("missing entries", b'{"schema": 1}'),
        ("entries not an object", b'{"schema": 1, "entries": []}'),
        ("unknown schema", b'{"schema": 99, "entries": {}}'),
        ("binary garbage", b"\xff\xfe\x00\x01"),
    ]

    def test_read_and_update_refuse_without_touching_the_file(self):
        for name, data in self.BAD:
            with self.subTest(name):
                self.path.write_bytes(data)
                with self.assertRaises(ss.Corrupt):
                    self.store.read()
                with self.assertRaises(ss.Corrupt):
                    self.store.update("k", None, 1)
                self.assertEqual(self.raw(), data)
                self.assertEqual(self.leftovers(), [])

    def test_validator_rejects_bad_entries_on_read_and_before_write(self):
        def validate(key, value):
            if not isinstance(value, dict) or "reading" not in value:
                raise ValueError("reading が必要")

        store = ss.Store(self.path, validate=validate)
        store.update("ok", None, {"reading": "オーケー"})
        before = self.raw()
        with self.assertRaises(ss.Invalid):
            store.update("bad", None, {"no": 1})
        self.assertEqual(self.raw(), before)
        # 手で壊された正本は Corrupt(どのキーかを示す)
        self.path.write_bytes(json.dumps({"schema": 1, "entries": {"x": 5}}).encode())
        with self.assertRaises(ss.Corrupt) as cm:
            store.read()
        self.assertIn("x", str(cm.exception))


class WriteFailureTests(Base):
    def test_replace_failure_keeps_original_and_explains(self):
        self.store.update("a", None, 1)
        before = self.raw()
        with mock.patch.object(ss, "REPLACE_RETRY_DELAY", 0.001):
            with mock.patch(
                "state_store.os.replace", side_effect=PermissionError(13, "denied")
            ):
                with self.assertRaises(ss.WriteFailed) as cm:
                    self.store.update("a", 1, 2)
        msg = str(cm.exception)
        for hint in ("他のアプリ", "読み取り専用", "権限"):
            self.assertIn(hint, msg)
        self.assertEqual(self.raw(), before)
        self.assertEqual(self.leftovers(), [])
        self.assertFalse((self.dir / "yomi.json.lock").exists())

    def test_transient_replace_failure_is_retried(self):
        self.store.update("a", None, 1)
        real = os.replace
        calls = []

        def flaky(src, dst):
            calls.append(1)
            if len(calls) < 3:
                raise PermissionError(13, "busy")
            return real(src, dst)

        with mock.patch.object(ss, "REPLACE_RETRY_DELAY", 0.001):
            with mock.patch("state_store.os.replace", side_effect=flaky):
                snap = self.store.update("a", 1, 2)
        self.assertEqual(snap.entries["a"], 2)
        self.assertEqual(len(calls), 3)
        self.assertEqual(self.leftovers(), [])

    def test_failure_while_writing_leaves_no_temp_file(self):
        self.store.update("a", None, 1)
        before = self.raw()
        with mock.patch("state_store.os.fsync", side_effect=OSError(28, "disk full")):
            with self.assertRaises(ss.WriteFailed):
                self.store.update("a", 1, 2)
        self.assertEqual(self.raw(), before)
        self.assertEqual(self.leftovers(), [])

    @unittest.skipIf(os.name == "nt", "POSIX の権限ビット")
    def test_existing_file_mode_is_preserved(self):
        self.store.update("a", None, 1)
        os.chmod(self.path, 0o600)
        self.store.update("a", 1, 2)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)


class LockTests(Base):
    def test_fresh_lock_blocks_until_timeout_and_file_is_untouched(self):
        self.store.update("a", None, 1)
        before = self.raw()
        lock = self.dir / "yomi.json.lock"
        lock.write_text("someone")
        store = ss.Store(self.path, lock_timeout=0.3, lock_stale=30.0)
        t0 = time.time()
        with self.assertRaises(ss.LockTimeout):
            store.update("a", 1, 2)
        self.assertGreaterEqual(time.time() - t0, 0.25)
        self.assertEqual(self.raw(), before)
        self.assertTrue(lock.exists(), "他人のロックは消さない")

    def test_stale_lock_is_broken(self):
        self.store.update("a", None, 1)
        lock = self.dir / "yomi.json.lock"
        lock.write_text("crashed")
        old = time.time() - 120
        os.utime(lock, (old, old))
        snap = self.store.update("a", 1, 2)
        self.assertEqual(snap.entries["a"], 2)
        self.assertFalse(lock.exists())

    def test_lock_is_released_after_success(self):
        self.store.update("a", None, 1)
        self.assertFalse((self.dir / "yomi.json.lock").exists())

    def test_read_does_not_need_the_lock(self):
        self.store.update("a", None, 1)
        (self.dir / "yomi.json.lock").write_text("someone")
        self.assertEqual(self.store.read().entries, {"a": 1})


WORKER = r"""
import sys
sys.path.insert(0, sys.argv[1])
import state_store as ss
path, n, name, start = sys.argv[2], int(sys.argv[3]), sys.argv[4], float(sys.argv[5])
import time
while time.time() < start:
    pass
store = ss.Store(path, lock_timeout=20.0)
for i in range(n):
    while True:
        snap = store.read()
        cur = snap.entries.get("counter")
        try:
            store.update("counter", cur, (cur or 0) + 1)
            break
        except ss.Conflict:
            continue
    # 自分専用のキーにも書く(別キーの更新が消えないこと)
    mine = store.read().entries.get(name)
    store.update(name, mine, (mine or 0) + 1)
print("done")
"""


class ProcessRaceTests(Base):
    def test_concurrent_processes_lose_no_update(self):
        procs, n = 5, 15
        start = time.time() + 1.5
        script = self.dir / "worker.py"
        script.write_text(WORKER, encoding="utf-8")
        ps = [
            subprocess.Popen(
                [
                    sys.executable,
                    str(script),
                    str(SCRIPTS),
                    str(self.path),
                    str(n),
                    f"w{i}",
                    str(start),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            for i in range(procs)
        ]
        for p in ps:
            _, err = p.communicate(timeout=120)
            self.assertEqual(p.returncode, 0, err)
        entries = self.store.read().entries
        self.assertEqual(entries["counter"], procs * n)
        for i in range(procs):
            self.assertEqual(entries[f"w{i}"], n)
        self.assertEqual(self.leftovers(), [])


if __name__ == "__main__":
    unittest.main()
