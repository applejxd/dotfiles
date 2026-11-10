"""ツールが所有する状態ファイル(JSON)の窓口。

読み辞書・素材台帳・指摘・承認など、ツール(確認サーバと CLI)が書く状態は、すべてこの窓口を
通す(ADR-0003)。更新は次の一連の手順で行う。

    プロセス間ロック → 読む → 検証 → キー単位の比較交換 → 一時ファイルを閉じて置換 → 解放

- ロックは `<ファイル>.lock` を `O_CREAT|O_EXCL` で作る。fcntl / msvcrt を使わないので、Ubuntu と
  Windows で同じコードになる。プロセスが落ちて残ったロックは、`lock_stale` 秒たつと解除される
  (解除の競合は、ロックを持ったまま落ちた直後に 2 つのプロセスが同時に検出する場合だけで、
  起きても更新が 1 件失敗する範囲。許容する)。
- 版は「キー単位の比較交換」にする。呼び出し側は、見たそのキーの値(`expected`、新規は None)を
  渡す。ロックの中で現在の値と違えば `Conflict`。無関係なキーの変更では失敗しない。
- 判断の対象が別ファイル(承認の対象の台本など)のときは、`guard` を渡す。ロックの中で呼ばれ、
  版が違えば `Conflict` を投げる。
- 正本が壊れていれば `Corrupt`、新しい値が検証に通らなければ `Invalid`、置換に失敗すれば
  `WriteFailed`(原因の候補を含む)、ロックが取れなければ `LockTimeout`。いずれもファイルを変えない。
- 形式: `{"schema": 1, "entries": {キー: 値}}`。UTF-8、LF、末尾に改行、日本語は \\u にしない。
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

SCHEMA = 1
REPLACE_RETRIES = 5
REPLACE_RETRY_DELAY = (
    0.05  # 秒。Windows でウイルス対策などが一瞬ファイルを開く場合の再試行
)


class StoreError(Exception):
    """窓口のエラーの基底。"""


class Conflict(StoreError):
    """利用者が見た値と、現在の値が違う(409)。`current` に現在の値を持つ。"""

    def __init__(self, current: Any = None, message: str = "見た後に変更されています"):
        super().__init__(message)
        self.current = current


class Corrupt(StoreError):
    """正本が壊れている(手で編集された、途中で切れたなど)。書かずに止める。"""


class Invalid(StoreError):
    """新しい値が検証に通らない。"""


class WriteFailed(StoreError):
    """置換・書き込みに失敗した。元のファイルは変わっていない。"""


class LockTimeout(StoreError):
    """他のプロセスが更新中で、ロックが取れなかった。"""


@dataclass
class Snapshot:
    entries: dict
    version: str


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def value_version(value: Any) -> str:
    """値の版(キーの順序に依存しない)。"""
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()[:16]


def _normalize(value: Any) -> Any:
    """JSON を通した値にそろえる(tuple と list の違いなどを消す)。"""
    return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))


def _cause(e: BaseException) -> str:
    """例外の原因だけ(ファイル名・絶対パスを含めない)。API の応答にパスを漏らさない。"""
    return getattr(e, "strerror", None) or type(e).__name__


def _reject_constant(name: str):
    raise ValueError(f"JSON ではない値: {name}")


class Store:
    def __init__(
        self,
        path: str | Path,
        validate: Callable[[str, Any], None] | None = None,
        lock_timeout: float = 5.0,
        lock_stale: float = 120.0,
    ):
        self.path = Path(path)
        self.lock_path = self.path.with_name(self.path.name + ".lock")
        self.validate = validate
        self.lock_timeout = lock_timeout
        self.lock_stale = lock_stale

    # ── 読む ──

    def read(self) -> Snapshot:
        """ロックなしで読む(置換は原子的なので、途中の状態は見えない)。"""
        try:
            raw = self.path.read_bytes()
        except FileNotFoundError:
            return Snapshot({}, value_version({}))
        return self._parse(raw)

    def _parse(self, raw: bytes) -> Snapshot:
        name = self.path.name
        try:
            doc = json.loads(raw.decode("utf-8"), parse_constant=_reject_constant)
        except (UnicodeDecodeError, ValueError) as e:
            raise Corrupt(f"{name} を読めません(JSON として壊れています): {e}") from e
        if not isinstance(doc, dict) or "entries" not in doc:
            raise Corrupt(f"{name} の形式が違います(schema と entries が必要)")
        if doc.get("schema") != SCHEMA:
            raise Corrupt(f"{name} の schema が未対応です: {doc.get('schema')!r}")
        entries = doc["entries"]
        if not isinstance(entries, dict):
            raise Corrupt(f"{name} の entries が辞書ではありません")
        if self.validate:
            for key, value in entries.items():
                try:
                    self.validate(key, value)
                except ValueError as e:
                    raise Corrupt(f"{name} の項目「{key}」が不正です: {e}") from e
        return Snapshot(entries, value_version(entries))

    # ── 更新 ──

    def update(
        self,
        key: str,
        expected: Any,
        new: Any,
        guard: Callable[[], None] | None = None,
    ) -> Snapshot:
        """`key` を `expected`(見た値。新規は None)から `new` へ。`new` が None なら削除。"""
        if not isinstance(key, str):
            raise Invalid(f"キーは文字列: {key!r}")
        try:
            expected = _normalize(expected)
            new = _normalize(new)
        except (TypeError, ValueError) as e:  # NaN / 無限大 / JSON にできない値
            raise Invalid(f"項目「{key}」の値を JSON にできません: {e}") from e
        with self._locked():
            snap = self.read()
            entries = dict(snap.entries)
            current = entries.get(key)
            if current != expected:
                raise Conflict(current)
            if guard is not None:
                guard()
            if new is None:
                if key not in entries:
                    return snap
                del entries[key]
            else:
                if self.validate:
                    try:
                        self.validate(key, new)
                    except ValueError as e:
                        raise Invalid(f"項目「{key}」が不正です: {e}") from e
                entries[key] = new
            self._write(entries)
            return Snapshot(entries, value_version(entries))

    def initialize(self) -> bool:
        """ファイルが無ければ空の状態を作る(存在確認と作成を同じロックの中で行う)。
        既にあれば(壊れていても)何もしない。作ったときだけ True。"""
        with self._locked():
            if self.path.exists():
                return False
            self._write({})
            return True

    # ── 書く ──

    def _write(self, entries: dict) -> None:
        data = (
            json.dumps(
                {"schema": SCHEMA, "entries": entries}, ensure_ascii=False, indent=2
            )
            + "\n"
        ).encode("utf-8")
        parent = self.path.parent
        parent.mkdir(parents=True, exist_ok=True)
        tmp = None
        try:
            fd, tmp_name = tempfile.mkstemp(
                dir=parent, prefix="." + self.path.name + ".", suffix=".tmp"
            )
            tmp = Path(tmp_name)
            with os.fdopen(fd, "wb") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            try:
                os.chmod(tmp, self.path.stat().st_mode & 0o777)  # 既存の権限を引き継ぐ
            except OSError:
                pass
            self._replace(tmp)
            tmp = None
        except WriteFailed:
            raise
        except OSError as e:
            raise WriteFailed(
                f"{self.path.name} に書き込めません(空き容量・権限を確認してください): {_cause(e)}"
            ) from e
        finally:
            if tmp is not None:
                try:
                    tmp.unlink()
                except OSError:
                    pass

    def _replace(self, tmp: Path) -> None:
        last: OSError | None = None
        for i in range(REPLACE_RETRIES):
            try:
                os.replace(tmp, self.path)
                return
            except (
                OSError
            ) as e:  # Windows では、他のアプリが開いていると PermissionError
                last = e
                if i + 1 < REPLACE_RETRIES:
                    time.sleep(REPLACE_RETRY_DELAY)
        raise WriteFailed(
            f"{self.path.name} を置き換えられません。他のアプリで開いている、読み取り専用になっている、"
            f"権限がない、のいずれかの可能性があります。({_cause(last)})"
        ) from last

    # ── ロック ──

    @contextmanager
    def _locked(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        token = f"{os.getpid()}:{uuid.uuid4().hex}"
        deadline = time.monotonic() + self.lock_timeout
        delay = 0.005
        denied: PermissionError | None = None
        while True:
            try:
                fd = os.open(
                    self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644
                )
            except FileExistsError:
                pass
            except PermissionError as e:
                denied = e  # Windows: 削除待ちのファイルと衝突している間は待てば取れる。続くなら期限で案内する
            else:
                try:
                    os.write(fd, token.encode("ascii"))
                except OSError as e:  # トークンを書けないロックを残さない
                    os.close(fd)
                    try:
                        self.lock_path.unlink()
                    except OSError:
                        pass
                    raise WriteFailed(
                        f"{self.lock_path.name} を初期化できません(空き容量・権限を確認してください): {_cause(e)}"
                    ) from e
                os.close(fd)
                break
            if self._break_if_stale():
                continue
            if time.monotonic() >= deadline:
                if denied is not None:
                    raise LockTimeout(
                        f"{self.lock_path.name} を作れません(権限を確認してください): {_cause(denied)}"
                    )
                raise LockTimeout(
                    f"{self.path.name} は他のプロセスが更新中です。しばらくして再試行してください"
                    f"(続くときは古いロック {self.lock_path.name} を確認)"
                )
            time.sleep(delay)
            delay = min(delay * 2, 0.05)
        try:
            yield
        finally:
            self._release(token)

    def _break_if_stale(self) -> bool:
        try:
            age = time.time() - self.lock_path.stat().st_mtime
        except FileNotFoundError:
            return False  # 消えた(取り直す前に期限判定と待機を通す。空回ししない)
        except OSError:
            return False
        if age <= self.lock_stale:
            return False
        try:
            self.lock_path.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            return False
        return True

    def _release(self, token: str) -> None:
        # 自分のロックだけを消す(長く止まって解除された後に、他人のロックを消さない)
        for i in range(3):
            try:
                if (
                    self.lock_path.read_text(encoding="ascii", errors="replace")
                    != token
                ):
                    return
                self.lock_path.unlink()
                return
            except FileNotFoundError:
                return
            except OSError:
                time.sleep(0.02)
