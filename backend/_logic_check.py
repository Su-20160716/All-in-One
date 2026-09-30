# -*- coding: utf-8 -*-
"""临时逻辑自检（无 DB 访问），运行后即删"""
from notes.views import (
    count_words, _split_markdown_into_notes, _scan_todos,
    TODO_LINE_RE, SOURCE_LABELS, NOTE_COLORS, _qp_int,
)
import files.views as fv

assert count_words("你好 world 123") == 4, count_words("你好 world 123")
parts = _split_markdown_into_notes("# A\n\naaa\n# B\n\nbbb")
assert len(parts) == 2 and parts[0]["title"] == "A", parts


class N:
    content = "- [ ] task1\n- [x] done2\nno task"


todos = _scan_todos(N)
assert len(todos) == 2 and todos[0]["done"] is False and todos[1]["done"] is True, todos
assert TODO_LINE_RE.match("  * [X] upper")
assert fv._folder_label(None) == "根目录"
assert len(SOURCE_LABELS) == 7 and len(NOTE_COLORS) == 6


class QP(dict):
    pass


try:
    _qp_int(QP(bad="x"), "bad", 3)
    raise SystemExit("should raise")
except ValueError:
    pass
assert _qp_int(QP(), "missing", 3) == 3
assert _qp_int(QP(n="10"), "n", 3, lo=1, hi=20) == 10


class Req:
    query_params = QP()
    data = {}


assert fv._int_param(Req(), "x", 7) == 7
print("logic self-check OK")
