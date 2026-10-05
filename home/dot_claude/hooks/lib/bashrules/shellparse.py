"""シェルのコマンド文字列を、規則が使う単位 (単純コマンド) へ分ける。

bash の完全な文法ではない。規則が要る範囲 (区切り・引用・エスケープ・リダイレクト) に絞る。
``cd`` の除去や ``bash -c`` の展開は ``command_policy.normalize`` が担うので、ここは
正規化済みのセグメント (``_shared._segments``) に当てる。ヒアドキュメントの本文は
読み飛ばさない (実行されない本文は ``split_heredoc_body`` が先に取り除く)。
see docs/change/0012-bash-hook-shared-parser.md
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Word:
    """1 語。``raw`` は書かれたまま、``value`` は引用とエスケープを外した値。

    ``$VAR`` / ``$(...)`` / バッククォートは展開せず、書かれたまま ``value`` に残す。
    """

    raw: str
    value: str

    @property
    def expandable(self) -> str:
        """シェルが ``$`` を展開する部分だけを残した ``raw``。

        単引用符と ``$'...'`` の中身を除く (二重引用符の中の ``'`` は引用ではない)。
        エスケープ (``\\$X``) は残すので、呼び出し側は ``\\$`` を展開しない形として扱う。
        """
        return _drop_single_quoted(self.raw)


def _drop_single_quoted(raw: str) -> str:
    out: list[str] = []
    i, n = 0, len(raw)
    in_double = False
    while i < n:
        ch = raw[i]
        if ch == "\\" and i + 1 < n:
            out.append(raw[i : i + 2])
            i += 2
            continue
        if ch == "'" and not in_double:
            end = raw.find("'", i + 1)
            if end != -1:
                i = end + 1
                continue
        if ch == '"':
            in_double = not in_double
        out.append(ch)
        i += 1
    return "".join(out)


@dataclass(frozen=True)
class Redirect:
    fd: str
    """明示した fd (``2>`` の ``2``)。``&>`` / ``&>>`` は ``&``。無ければ空。"""
    op: str
    """``>`` ``>>`` ``>|`` ``>&`` ``<`` ``<<`` ``<<-`` ``<<<`` ``<&`` ``<>`` のどれか。"""
    target: Word | None
    """対象。fd の複製・クローズ (``2>&1`` / ``>&-``) と、対象が欠けた形は ``None``。"""

    @property
    def writes(self) -> bool:
        return self.target is not None and self.op in _WRITE_OPS


@dataclass(frozen=True)
class Command:
    words: tuple[Word, ...]
    redirects: tuple[Redirect, ...]

    @property
    def argv(self) -> tuple[str, ...]:
        return tuple(w.value for w in self.words)


_WRITE_OPS = frozenset({">", ">>", ">|", ">&", "<>"})
# 長いものを先に置く (前方一致で最初に当たったものを使う)
_SEPARATORS = ("&&", "||", "|&", ";;", ";", "|", "&", "\n", "(", ")")
_REDIRECT_OPS = ("<<<", "<<-", "<<", "<>", "<&", ">>", ">|", ">&", "<", ">")
_WORD_END = frozenset(" \t\n;&|()<>")
# 単独の語として現れても実行するものを変えない記号
_GROUPING_WORDS = frozenset({"{", "}", "!"})


def parse(text: str) -> tuple[Command, ...]:
    """``text`` を単純コマンドの並びにする。区切り (``;`` ``&&`` ``|`` 改行など) で分ける。"""
    return _Parser(text).run()


class _Parser:
    def __init__(self, text: str) -> None:
        self.s = text
        self.n = len(text)
        self.i = 0
        self.commands: list[Command] = []
        self.words: list[Word] = []
        self.redirects: list[Redirect] = []

    def run(self) -> tuple[Command, ...]:
        s = self.s
        while self.i < self.n:
            ch = s[self.i]
            if ch in " \t":
                self.i += 1
                continue
            if s.startswith("\\\n", self.i):
                self.i += 2
                continue
            if ch == "#":
                end = s.find("\n", self.i)
                self.i = self.n if end == -1 else end
                continue
            if s.startswith(("<(", ">("), self.i):
                end = self._skip_parens(self.i + 1)
                text = s[self.i : end]
                self.words.append(Word(text, text))
                self.i = end
                continue
            redirect = self._redirect()
            if redirect is not None:
                self.redirects.append(redirect)
                continue
            sep = next((op for op in _SEPARATORS if s.startswith(op, self.i)), None)
            if sep is not None:
                self._finish()
                self.i += len(sep)
                continue
            self.words.append(self._word())
        self._finish()
        return tuple(self.commands)

    def _finish(self) -> None:
        words = list(self.words)
        while words and words[0].raw in _GROUPING_WORDS:
            words.pop(0)
        if words or self.redirects:
            self.commands.append(Command(tuple(words), tuple(self.redirects)))
        self.words = []
        self.redirects = []

    def _redirect(self) -> Redirect | None:
        s = self.s
        j = self.i
        while j < self.n and s[j].isdigit():
            j += 1
        fd = s[self.i : j]
        if not fd and s.startswith("&>", j):
            fd = "&"
            j += 1
        op = next((o for o in _REDIRECT_OPS if s.startswith(o, j)), None)
        if op is None or (fd == "&" and op not in (">", ">>")):
            return None
        self.i = j + len(op)
        while self.i < self.n and s[self.i] in " \t":
            self.i += 1
        target = None
        if self.i < self.n and s[self.i] not in _WORD_END:
            target = self._word()
        if (
            op in (">&", "<&")
            and target is not None
            and (target.value.isdigit() or target.value == "-")
        ):
            target = None
        return Redirect(fd, op, target)

    def _word(self) -> Word:
        s = self.s
        start = self.i
        value: list[str] = []
        i = self.i
        while i < self.n:
            c = s[i]
            if c in _WORD_END:
                break
            if c == "\\":
                if i + 1 >= self.n:
                    value.append(c)
                    i += 1
                elif s[i + 1] == "\n":
                    i += 2
                else:
                    value.append(s[i + 1])
                    i += 2
                continue
            if c == "'":
                end = s.find("'", i + 1)
                end = self.n if end == -1 else end
                value.append(s[i + 1 : end])
                i = end + 1
                continue
            if c == '"':
                i = self._double_quoted(i, value)
                continue
            if s.startswith("$'", i):
                end = self._ansi_c_end(i + 2)
                value.append(s[i + 2 : end])
                i = end + 1
                continue
            if s.startswith("$(", i):
                end = self._skip_parens(i + 1)
                value.append(s[i:end])
                i = end
                continue
            if c == "`":
                end = self._skip_backtick(i)
                value.append(s[i:end])
                i = end
                continue
            value.append(c)
            i += 1
        if i == start:
            # 区切りの文字だけが残った形。進めないと呼び出し側が止まる
            value.append(s[i])
            i += 1
        self.i = i
        return Word(s[start:i], "".join(value))

    def _double_quoted(self, i: int, value: list[str]) -> int:
        """``"`` の中を読み、閉じ ``"`` の次の位置を返す。"""
        s = self.s
        j = i + 1
        while j < self.n and s[j] != '"':
            if s[j] == "\\" and j + 1 < self.n:
                nxt = s[j + 1]
                if nxt in '"\\$`':
                    value.append(nxt)
                elif nxt != "\n":
                    value.append(s[j : j + 2])
                j += 2
                continue
            if s.startswith("$(", j):
                end = self._skip_parens(j + 1)
                value.append(s[j:end])
                j = end
                continue
            if s[j] == "`":
                end = self._skip_backtick(j)
                value.append(s[j:end])
                j = end
                continue
            value.append(s[j])
            j += 1
        return min(j + 1, self.n)

    def _ansi_c_end(self, j: int) -> int:
        """``$'...'`` の閉じ ``'`` の位置 (``\\'`` は閉じない)。"""
        while j < self.n and self.s[j] != "'":
            j += 2 if self.s[j] == "\\" else 1
        return min(j, self.n)

    def _skip_parens(self, j: int) -> int:
        """``j`` の ``(`` に対応する ``)`` の次の位置。引用の中の括弧は数えない。"""
        s = self.s
        depth = 0
        while j < self.n:
            c = s[j]
            if c == "\\":
                j += 2
                continue
            if c == "'":
                end = s.find("'", j + 1)
                j = self.n if end == -1 else end + 1
                continue
            if c == '"':
                j = self._double_quoted(j, [])
                continue
            if c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
                if depth == 0:
                    return j + 1
            j += 1
        return self.n

    def _skip_backtick(self, j: int) -> int:
        """``j`` のバッククォートに対応する閉じの次の位置。"""
        k = j + 1
        while k < self.n and self.s[k] != "`":
            k += 2 if self.s[k] == "\\" else 1
        return min(k + 1, self.n)
