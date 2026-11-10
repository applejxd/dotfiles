#!/usr/bin/env python3
"""閉じたモジュールの範囲を、どの試験が実際に開いたかを記録する pytest プラグイン (監査)。

    VERIFY_AUDIT_OUT=<ログ> PYTHONPATH=scripts pytest -p verify_audit test/ -n 8
    python3 scripts/verify_audit.py report <ログ>     # モジュール外の試験が開いたものを一覧 (あれば終了コード 1)

環境変数 VERIFY_AUDIT_OUT が無いときは何もしない (-p で明示したときだけ有効)。
ログは worker (プロセス) ごとに <ログ>.<pid> へ書く。subprocess の中の open は拾えない。
see docs/spec/development.md#閉じたモジュールの規則
"""

from __future__ import annotations

import os
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import verify

ENV_OUT = "VERIFY_AUDIT_OUT"
EVENTS = {"open", "os.listdir", "os.scandir"}  # open と、ディレクトリの走査
ROOT = verify.ROOT
_ROOT_STR = str(ROOT.resolve())


def module_paths(modules: Sequence[verify.ClosedModule] | None = None) -> tuple[str, ...]:
    modules = verify.CLOSED_MODULES if modules is None else modules
    return tuple(p for m in modules for p in m.paths)


class Recorder:
    """audit hook から呼ばれる。現在の試験ファイルごとに、モジュールの範囲のパスを覚える。"""

    def __init__(self, root: str = _ROOT_STR, patterns: Sequence[str] | None = None) -> None:
        self.root = root
        self.patterns = module_paths() if patterns is None else tuple(patterns)
        self.current: str | None = None
        self.opened: set[tuple[str, str]] = set()

    def _relative(self, raw: object) -> str | None:
        if isinstance(raw, bytes):
            raw = os.fsdecode(raw)
        if not isinstance(raw, (str, os.PathLike)):
            return None  # fd (int) など
        try:
            real = os.path.realpath(raw)
        except (OSError, ValueError):
            return None
        if real != self.root and not real.startswith(self.root + os.sep):
            return None
        return real[len(self.root) + 1 :].replace(os.sep, "/")

    def on_event(self, event: str, args: tuple) -> None:
        if self.current is None or event not in EVENTS or not args:
            return
        rel = self._relative(args[0])
        if rel is None:
            return
        if any(verify._match(p, rel) or verify._match(p, rel + "/") for p in self.patterns):
            self.opened.add((self.current, rel))

    def dump(self, out: Path) -> None:
        lines = sorted(f"{t}\t{p}" for t, p in self.opened)
        out.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


_recorder: Recorder | None = None


def pytest_configure(config) -> None:
    global _recorder
    if not os.environ.get(ENV_OUT) or _recorder is not None:
        return
    _recorder = Recorder()
    rec = _recorder
    sys.addaudithook(rec.on_event)


def pytest_runtest_logstart(nodeid, location) -> None:
    if _recorder is not None:
        _recorder.current = str(nodeid).split("::", 1)[0]


def pytest_runtest_logfinish(nodeid, location) -> None:
    if _recorder is not None:
        _recorder.current = None


def pytest_sessionfinish(session, exitstatus) -> None:
    out = os.environ.get(ENV_OUT)
    if _recorder is None or not out:
        return
    _recorder.current = None
    _recorder.dump(Path(f"{out}.{os.getpid()}"))


def read_logs(out: Path) -> set[tuple[str, str]]:
    """<ログ> と <ログ>.<pid> をすべて読み、(試験ファイル, 開いたパス) の集合にする。"""
    out = Path(out)
    files = [p for p in out.parent.glob(out.name + "*") if p.is_file()]
    found: set[tuple[str, str]] = set()
    for f in files:
        for line in f.read_text(encoding="utf-8").splitlines():
            test, _, path = line.partition("\t")
            if test and path:
                found.add((test, path))
    return found


def outside_opens(
    opened: Iterable[tuple[str, str]],
    test_files: Sequence[str],
    modules: Sequence[verify.ClosedModule] | None = None,
) -> list[tuple[str, str, str]]:
    """モジュールの範囲のパスを、そのモジュール外の試験が開いた記録 → (モジュール名, 試験, パス)。"""
    modules = verify.CLOSED_MODULES if modules is None else modules
    owners = {m.name: verify.module_test_files(m, test_files) for m in modules}
    bad: list[tuple[str, str, str]] = []
    for test, path in sorted(opened):
        for m in modules:
            hit = any(verify._match(p, path) or verify._match(p, path + "/") for p in m.paths)
            if hit and test not in owners[m.name]:
                bad.append((m.name, test, path))
    return bad


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 2 or args[0] != "report":
        sys.stderr.write("使い方: verify_audit.py report <ログ>\n")
        return 2
    opened = read_logs(Path(args[1]))
    bad = outside_opens(opened, verify.discover_test_files())
    for name, test, path in bad:
        print(f"{name}: {test} が {path} を開いた")
    print(f"記録 {len(opened)} 件、モジュール外の試験による参照 {len(bad)} 件")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
