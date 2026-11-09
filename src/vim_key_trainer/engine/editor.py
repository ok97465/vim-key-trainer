"""메모리 문서에서 Vim 편집 명령을 실행하는 순수 Python 엔진.

단어는 기본 ASCII iskeyword, 줄 이동은 startofline/nowrap/whichwrap='',
삽입은 noautoindent/backspace=indent,eol,start 조건을 따른다. 실제 Vim이나
사용자의 파일에는 접근하지 않는다.
"""

# Standard library imports
import re
from bisect import bisect_left, bisect_right
from dataclasses import dataclass, replace
from typing import Literal

# Local imports
from vim_key_trainer.domain.keys import KeyToken
from vim_key_trainer.engine.patterns import find_match, substitute

_COUNT_LIMIT = 999
_END_COLUMN = 2**31 - 1

_MOTIONS = frozenset(
    {
        "h",
        "j",
        "k",
        "l",
        "w",
        "W",
        "b",
        "B",
        "e",
        "E",
        "ge",
        "gE",
        "0",
        "^",
        "$",
        "g_",
        "gg",
        "G",
        "|",
        "+",
        "-",
        "_",
        "{",
        "}",
        "(",
        ")",
        "%",
        "f",
        "F",
        "t",
        "T",
        ";",
        ",",
        "H",
        "M",
        "L",
        "gj",
        "gk",
        "g0",
        "g$",
        "n",
        "N",
        "*",
        "#",
        "'",
        "`",
    }
)
_OBJECTS = frozenset(prefix + obj for prefix in "ia" for obj in "wW\"'`()[]{}<>bpBs")
_OPERATORS = frozenset({"d", "c", "y", ">", "<", "g~", "gu", "gU"})
_VISUAL_ACTIONS = {
    "d": "dd",
    "x": "x",
    "X": "X",
    "c": "cc",
    "s": "s",
    "S": "S",
    "R": "R",
    "y": "yy",
    "Y": "Y",
    "D": "D",
    "C": "C",
    ">": ">>",
    "<": "<<",
    "~": "~",
    "u": "guu",
    "U": "gUU",
    "J": "J",
    "p": "p",
    "P": "P",
    "I": "I",
    "A": "A",
    "o": "o",
}
SUPPORTED_COMMANDS = (
    _MOTIONS
    | frozenset({op + motion for op in _OPERATORS for motion in _MOTIONS | _OBJECTS})
    | frozenset({op + op for op in ("d", "c", "y", ">", "<")})
    | frozenset(
        {
            "i",
            "a",
            "I",
            "A",
            "o",
            "O",
            "s",
            "S",
            "C",
            "D",
            "x",
            "X",
            "Y",
            "r",
            "R",
            "p",
            "P",
            "gp",
            "gP",
            "J",
            "gJ",
            "~",
            ".",
            "u",
            "ctrl+r",
            "ctrl+a",
            "ctrl+x",
            "ctrl+u",
            "ctrl+d",
            "ctrl+f",
            "ctrl+b",
            "ctrl+e",
            "ctrl+y",
            "ctrl+o",
            "ctrl+i",
            "v",
            "V",
            "ctrl+v",
            "m",
            '"',
            "/",
            "?",
            ":",
            "zz",
            "zt",
            "zb",
            "z.",
            "z-",
            "z+",
            "g~~",
            "guu",
            "gUU",
        }
    )
)


def _valid_pending(pending: str) -> bool:
    """Only incomplete parser prefixes are valid public state."""
    if re.fullmatch(r"(?:[1-9][0-9]*)?[/?:]", pending):
        return True
    value = re.sub(r'^".', "", pending)
    if pending == '"' or (pending.startswith('"') and not value):
        return True
    value = re.sub(r"^[1-9][0-9]*", "", value)
    if not value:
        return True
    if value in {"g", "z", "m", "'", "`", "f", "F", "t", "T", "r", "i", "a"}:
        return True
    match = re.fullmatch(r"(d|c|y|>|<|g[~uU])([1-9][0-9]*)?(.*)", value)
    return bool(match and match[3] in {"", "i", "a", "g", "f", "F", "t", "T", "'", "`"})


@dataclass(frozen=True, slots=True)
class EditorState:
    lines: tuple[str, ...]
    row: int = 0
    column: int = 0
    mode: Literal[
        "normal", "insert", "replace", "visual", "visual_line", "visual_block"
    ] = "normal"
    preferred_column: int | None = None
    pending: str = ""
    visual_anchor: tuple[int, int] | None = None
    command_line: str = ""
    viewport_top: int = 0
    viewport_rows: int = 20

    def __post_init__(self) -> None:
        if not isinstance(self.lines, tuple) or not self.lines:
            raise ValueError("문서는 한 줄 이상의 불변 행 배열이어야 합니다.")
        if any(
            not isinstance(line, str)
            or not line.isascii()
            or (line != "" and not line.isprintable())
            for line in self.lines
        ):
            raise ValueError("문서 행은 표시 가능한 ASCII 문자만 포함해야 합니다.")
        if self.mode not in {
            "normal",
            "insert",
            "replace",
            "visual",
            "visual_line",
            "visual_block",
        }:
            raise ValueError("모드는 normal 또는 insert여야 합니다.")
        if type(self.row) is not int or not 0 <= self.row < len(self.lines):
            raise ValueError("커서 행이 문서 범위를 벗어났습니다.")
        maximum = len(self.lines[self.row])
        if self.mode not in {"insert", "replace"}:
            maximum = max(0, maximum - 1)
        if type(self.column) is not int or not 0 <= self.column <= maximum:
            raise ValueError("커서 열이 모드의 허용 범위를 벗어났습니다.")
        if self.preferred_column is not None and (
            type(self.preferred_column) is not int or self.preferred_column < 0
        ):
            raise ValueError("선호 열은 0 이상의 정수여야 합니다.")
        if self.pending:
            if self.mode in {"insert", "replace"} or not _valid_pending(self.pending):
                raise ValueError("잘못된 대기 명령입니다.")
            counts = [
                int(value)
                for value in re.findall(
                    r"[0-9]+",
                    self.pending.removeprefix('"')
                    if len(self.pending) < 2
                    else re.sub(r'^".', "", self.pending),
                )
            ]
            if any(count > _COUNT_LIMIT for count in counts) or (
                len(counts) == 2 and counts[0] * counts[1] > _COUNT_LIMIT
            ):
                raise ValueError("대기 명령의 count 상한은 999입니다.")

        if self.visual_anchor is not None:
            anchor_row, anchor_column = self.visual_anchor
            if not 0 <= anchor_row < len(self.lines) or not 0 <= anchor_column <= max(
                0, len(self.lines[anchor_row]) - 1
            ):
                raise ValueError("선택 시작 위치가 문서 범위를 벗어났습니다.")
        if self.mode.startswith("visual") and self.visual_anchor is None:
            raise ValueError("Visual 모드에는 선택 시작 위치가 필요합니다.")
        if self.viewport_rows < 1 or self.viewport_top < 0:
            raise ValueError("표시 행 수와 보기 시작 행이 잘못되었습니다.")
        if self.command_line and self.command_line[0] not in "/?:":
            raise ValueError("명령행은 검색 또는 Ex 접두사로 시작해야 합니다.")


@dataclass(frozen=True, slots=True)
class YankSpan:
    """복사한 원본의 행·열 범위. end는 배타적이며 빈 줄은 start == end다."""

    row: int
    start: int
    end: int

    def __post_init__(self) -> None:
        if self.row < 0 or self.start < 0 or self.end < self.start:
            raise ValueError("잘못된 복사 범위입니다.")


@dataclass(frozen=True, slots=True)
class EditOutcome:
    accepted: bool
    message: str = ""
    command: str | None = None
    changed: bool = False
    yanked_spans: tuple[YankSpan, ...] = ()


@dataclass(frozen=True, slots=True)
class _HistoryEntry:
    before: EditorState
    after: EditorState
    insert_cursor: tuple[int, int] | None = None


@dataclass(frozen=True, slots=True)
class EditorSnapshot:
    state: EditorState
    undo: tuple[_HistoryEntry, ...]
    redo: tuple[_HistoryEntry, ...]
    insert_start: EditorState | None
    insert_changed: bool
    registers: tuple[tuple[str, tuple[str, ...], str], ...] = ()
    selected_register: str = '"'
    last_find: tuple[str, str] | None = None
    last_search: tuple[str, bool] | None = None
    marks: tuple[tuple[str, tuple[int, int]], ...] = ()
    jumps: tuple[tuple[int, int], ...] = ()
    jump_index: int = -1
    last_change: tuple[KeyToken, ...] = ()
    command_tokens: tuple[KeyToken, ...] = ()
    command_changed: bool = False
    insert_count: int = 1
    insert_tokens: tuple[KeyToken, ...] = ()
    replace_states: tuple[EditorState, ...] = ()
    block_insert: tuple[int, int, int] | None = None
    scroll_rows: int | None = None


def _first_nonblank(line: str) -> int:
    return min(len(line) - len(line.lstrip(" ")), max(0, len(line) - 1))


def _word_class(char: str, bigword: bool = False) -> int:
    if char == " ":
        return 0
    if bigword:
        return 1
    return 1 if char.isalnum() or char == "_" else 2


def _word_starts(
    lines: tuple[str, ...], bigword: bool = False
) -> list[tuple[int, int]]:
    starts: list[tuple[int, int]] = []
    for row, line in enumerate(lines):
        if not line:
            starts.append((row, 0))
        previous = 0
        for column, char in enumerate(line):
            category = _word_class(char, bigword)
            if category and category != previous:
                starts.append((row, column))
            previous = category
    return starts


def _word_ends(lines: tuple[str, ...], bigword: bool = False) -> list[tuple[int, int]]:
    ends: list[tuple[int, int]] = []
    for row, line in enumerate(lines):
        for column, char in enumerate(line):
            category = _word_class(char, bigword)
            if category and (
                column == len(line) - 1
                or category != _word_class(line[column + 1], bigword)
            ):
                ends.append((row, column))
    return ends


@dataclass(slots=True)
class _ObjectCursor:
    """객체 범위 계산 중에만 줄 끝의 가상 위치를 허용한다."""

    lines: tuple[str, ...]
    row: int
    column: int
    bigword: bool

    @property
    def position(self) -> tuple[int, int]:
        return self.row, self.column

    @property
    def category(self) -> int:
        line = self.lines[self.row]
        return (
            _word_class(line[self.column], self.bigword)
            if self.column < len(line)
            else 0
        )

    def advance(self, *, skip_eol: bool = False) -> int:
        if self.column < len(self.lines[self.row]):
            self.column += 1
            if self.column < len(self.lines[self.row]):
                return 0
            if not skip_eol:
                return 2
        if self.row == len(self.lines) - 1:
            return -1
        self.row += 1
        self.column = 0
        return 1

    def retreat(self, *, skip_eol: bool = False) -> None:
        if self.column:
            self.column -= 1
        elif self.row:
            self.row -= 1
            self.column = len(self.lines[self.row])
            if skip_eol and self.column:
                self.column -= 1

    def forward_start(self) -> bool:
        category = self.category
        last_line = self.row == len(self.lines) - 1
        crossed = self.advance()
        if crossed == -1 or (crossed >= 1 and last_line):
            return False
        if crossed >= 1:
            return True
        if category:
            while self.category == category:
                if self.advance() != 0:
                    return True
        while self.category == 0:
            if not self.lines[self.row]:
                break
            if self.advance() != 0:
                return True
        return True

    def current_end(self) -> bool:
        category = self.category
        if self.advance() == -1:
            return False
        if self.category == category and category:
            while self.category == category:
                if self.advance() == -1:
                    return False
        elif category == 0:
            while self.category == 0:
                if not self.lines[self.row]:
                    return True
                if self.advance() == -1:
                    return False
            category = self.category
            while self.category == category:
                if self.advance() == -1:
                    return False
        self.retreat()
        return True


class EditEngine:
    """Vim Normal/Insert/Visual commands over a private, ASCII memory buffer.

    Registers, marks, searches and dot-repeat are app-local. No command can open
    a file, execute a shell command, run a macro or read the OS clipboard.
    """

    def __init__(
        self, initial: EditorState, allowed_commands: frozenset[str] | None = None
    ) -> None:
        self.allowed_commands = (
            SUPPORTED_COMMANDS if allowed_commands is None else allowed_commands
        )
        unknown = self.allowed_commands - SUPPORTED_COMMANDS
        if unknown:
            raise ValueError(f"미지원 허용 명령: {', '.join(sorted(unknown))}")
        self._state = initial
        self._undo: list[_HistoryEntry] = []
        self._redo: list[_HistoryEntry] = []
        self._insert_start: EditorState | None = (
            initial if initial.mode in {"insert", "replace"} else None
        )
        self._insert_changed = False

        self._registers: dict[str, tuple[tuple[str, ...], str]] = {}
        self._selected_register = '"'
        self._last_find: tuple[str, str] | None = None
        self._last_search: tuple[str, bool] | None = None
        self._marks: dict[str, tuple[int, int]] = {}
        self._jumps: list[tuple[int, int]] = []
        self._jump_index = -1
        self._last_change: tuple[KeyToken, ...] = ()
        self._command_tokens: list[KeyToken] = []
        self._command_changed = False
        self._insert_count = 1
        self._insert_tokens: list[KeyToken] = []
        self._replace_states: list[EditorState] = []
        self._block_insert: tuple[int, int, int] | None = None
        self._replaying = False
        self._scroll_rows: int | None = None

    @property
    def state(self) -> EditorState:
        return self._state

    @property
    def last_find(self) -> tuple[str, str] | None:
        """가이드가 undo 이력을 복사하지 않고 문자 찾기를 재사용하게 한다."""
        return self._last_find

    def snapshot(self) -> EditorSnapshot:
        return EditorSnapshot(
            state=self._state,
            undo=tuple(self._undo),
            redo=tuple(self._redo),
            insert_start=self._insert_start,
            insert_changed=self._insert_changed,
            registers=tuple(
                (name, text, kind) for name, (text, kind) in self._registers.items()
            ),
            selected_register=self._selected_register,
            last_find=self._last_find,
            last_search=self._last_search,
            marks=tuple(self._marks.items()),
            jumps=tuple(self._jumps),
            jump_index=self._jump_index,
            last_change=self._last_change,
            command_tokens=tuple(self._command_tokens),
            command_changed=self._command_changed,
            insert_count=self._insert_count,
            insert_tokens=tuple(self._insert_tokens),
            replace_states=tuple(self._replace_states),
            block_insert=self._block_insert,
            scroll_rows=self._scroll_rows,
        )

    def restore(self, snapshot: EditorSnapshot) -> None:
        self._state = snapshot.state
        self._undo = list(snapshot.undo)
        self._redo = list(snapshot.redo)
        self._insert_start = snapshot.insert_start
        self._insert_changed = snapshot.insert_changed
        self._registers = {
            name: (text, kind) for name, text, kind in snapshot.registers
        }
        self._selected_register = snapshot.selected_register
        self._last_find = snapshot.last_find
        self._last_search = snapshot.last_search
        self._marks = dict(snapshot.marks)
        self._jumps = list(snapshot.jumps)
        self._jump_index = snapshot.jump_index
        self._last_change = snapshot.last_change
        self._command_tokens = list(snapshot.command_tokens)
        self._command_changed = snapshot.command_changed
        self._insert_count = snapshot.insert_count
        self._insert_tokens = list(snapshot.insert_tokens)
        self._replace_states = list(snapshot.replace_states)
        self._block_insert = snapshot.block_insert
        self._scroll_rows = snapshot.scroll_rows

    def _move_basic(self, command: str, count: int, has_count: bool) -> None:
        state = self._state
        row, column = state.row, state.column
        preference: int | None = None
        if command == "h":
            column = max(0, column - count)
        elif command == "l":
            column = min(max(0, len(state.lines[row]) - 1), column + count)
        elif command in {"j", "k"}:
            row = min(
                max(0, row + (count if command == "j" else -count)),
                len(state.lines) - 1,
            )
            preference = state.preferred_column
            if preference is None:
                preference = column
            column = min(preference, max(0, len(state.lines[row]) - 1))
        elif command == "0":
            column = 0
        elif command == "^":
            column = _first_nonblank(state.lines[row])
        elif command in {"gg", "G"}:
            row = min(
                count - 1 if has_count or command == "gg" else len(state.lines) - 1,
                len(state.lines) - 1,
            )
            column = _first_nonblank(state.lines[row])
        elif command in {"w", "b", "W", "B", "e", "E"}:
            ends = command in {"e", "E"}
            starts = (
                _word_ends(state.lines, command.isupper())
                if ends
                else _word_starts(state.lines, command.isupper())
            )
            position = (row, column)
            if command in {"w", "W", "e", "E"}:
                index = bisect_right(starts, position) + count - 1
                position = (
                    starts[index]
                    if index < len(starts)
                    else (len(state.lines) - 1, max(0, len(state.lines[-1]) - 1))
                )
            else:
                index = bisect_left(starts, position) - count
                position = starts[index] if index >= 0 else (0, 0)
            row, column = position
        self._state = replace(
            state, row=row, column=column, preferred_column=preference
        )

    def _delete_lines(self, count: int) -> None:
        state = self._state
        lines = state.lines[: state.row] + state.lines[state.row + count :]
        if not lines:
            lines = ("",)
        row = min(state.row, len(lines) - 1)
        self._state = EditorState(lines, row, _first_nonblank(lines[row]))

    def _delete_word_or_lines(self, command: str, count: int) -> None:
        state = self._state
        if command == "dd":
            self._delete_lines(count)
            return
        if command in {"diw", "diW"}:
            self._delete_inner_word(count, command == "diW")
            return
        if command in {"de", "dE"}:
            self._move(command[-1], count, True)
            end_row, end_column = self._state.row, self._state.column
            self._state = state
            self._delete_range(
                (state.row, state.column),
                (end_row, min(len(state.lines[end_row]), end_column + 1)),
                exclusive=False,
            )
            return
        starts = _word_starts(state.lines, command == "dW")
        position = (state.row, state.column)
        for step in range(count):
            row, column = position
            index = bisect_right(starts, position)
            following = starts[index] if index < len(starts) else None
            # Unlike normal w, the final operator w stops at this line's EOL
            # when its last word is the last word on the line (motion.txt).
            if (
                step == count - 1
                and state.lines[row]
                and (following is None or following[0] != row)
            ):
                position = (row, len(state.lines[row]))
            elif (
                step == count - 1
                and not state.lines[row]
                and row < len(state.lines) - 1
            ):
                position = (row + 1, 0)
            elif following is not None:
                position = following
            else:
                position = (len(state.lines) - 1, len(state.lines[-1]))
                break
        self._delete_range((state.row, state.column), position)

    def _delete_range(
        self, start: tuple[int, int], end: tuple[int, int], *, exclusive: bool = True
    ) -> None:
        state = self._state
        start_row, start_column = start
        end_row, end_column = end
        if exclusive and end_row > start_row and end_column == 0:
            if start_column <= _first_nonblank(state.lines[start_row]):
                self._state = replace(state, row=start_row, column=start_column)
                self._delete_lines(end_row - start_row)
                return
            end_row -= 1
            end_column = len(state.lines[end_row])
        elif (
            end_row > start_row
            and not state.lines[start_row][:start_column].strip(" ")
            and not state.lines[end_row][end_column:].strip(" ")
        ):
            self._state = replace(state, row=start_row, column=start_column)
            self._delete_lines(end_row - start_row + 1)
            return
        if (end_row, end_column) <= start:
            return
        new_line = (
            state.lines[start_row][:start_column] + state.lines[end_row][end_column:]
        )
        lines = state.lines[:start_row] + (new_line,) + state.lines[end_row + 1 :]
        column = min(start_column, max(0, len(new_line) - 1))
        self._state = EditorState(lines, start_row, column)

    def _delete_inner_word(self, count: int, bigword: bool) -> None:
        state = self._state
        line = state.lines[state.row]
        start = state.column
        if line:
            category = _word_class(line[start], bigword)
            while start and _word_class(line[start - 1], bigword) == category:
                start -= 1
        cursor = _ObjectCursor(state.lines, state.row, start, bigword)
        inclusive = True
        valid = True
        if cursor.category:
            valid = cursor.current_end()
        else:
            cursor.forward_start()
            if cursor.column == 0:
                cursor.retreat(skip_eol=True)
            else:
                cursor.column -= 1
        remaining = count - 1
        while valid and remaining:
            inclusive = True
            if cursor.advance(skip_eol=True) == -1:
                valid = False
                break
            if cursor.category == 0:
                if not cursor.forward_start() and remaining > 1:
                    valid = False
                    break
                if cursor.column:
                    cursor.column -= 1
                else:
                    inclusive = False
            else:
                valid = cursor.current_end()
            remaining -= 1
        if not valid:
            self._state = replace(
                state,
                row=cursor.row,
                column=min(cursor.column, max(0, len(state.lines[cursor.row]) - 1)),
                preferred_column=None,
            )
            return
        first, last = sorted(((state.row, start), cursor.position))
        end_row, end_column = last
        if inclusive:
            end_column = min(end_column + 1, len(state.lines[end_row]))
        self._delete_range(first, (end_row, end_column), exclusive=not inclusive)

    def set_viewport(self, rows: int, top: int | None = None) -> None:
        if (
            type(rows) is not int
            or rows < 1
            or (top is not None and (type(top) is not int or top < 0))
        ):
            raise ValueError("보기 행 수와 시작 행을 확인하세요.")
        if self._scroll_rows is not None:
            self._scroll_rows = min(rows, self._scroll_rows)
        self._state = replace(
            self._state,
            viewport_rows=rows,
            viewport_top=min(
                self._state.viewport_top if top is None else top,
                len(self._state.lines) - 1,
            ),
        )

    def _visible_cursor(self) -> None:
        state = self._state
        top = min(state.viewport_top, len(state.lines) - 1)
        if state.row < top:
            top = state.row
        elif state.row >= top + state.viewport_rows:
            top = state.row - state.viewport_rows + 1
        self._state = replace(state, viewport_top=top)

    def _reject(self, message: str) -> EditOutcome:
        self._selected_register = '"'
        self._state = replace(self._state, pending="", command_line="")
        return EditOutcome(False, message)

    def _check(self, command: str) -> EditOutcome | None:
        if command not in self.allowed_commands:
            return self._reject("이 과제에서 허용하지 않는 명령입니다.")
        return None

    def submit(self, token: KeyToken) -> EditOutcome:
        before = self._state
        if before.mode == "normal" and not before.pending and not before.command_line:
            self._command_tokens = []
            self._command_changed = False
        saved_command_tokens = list(self._command_tokens)
        saved_insert_tokens = list(self._insert_tokens)
        self._command_tokens.append(token)
        outcome = self._submit(token)
        if not outcome.accepted:
            self._command_tokens = saved_command_tokens
            self._insert_tokens = saved_insert_tokens
        self._command_changed |= before.lines != self._state.lines
        if before.lines != self._state.lines:
            self._track_marks(before, self._state)
        self._visible_cursor()
        if self._state.mode == "normal" and not self._state.pending:
            if (
                self._command_changed
                and not self._replaying
                and outcome.command not in {"u", "ctrl+r", ".", ":"}
            ):
                self._last_change = tuple(self._command_tokens)
            self._command_tokens = []
            self._command_changed = False
            self._selected_register = '"'
        return outcome

    def _submit(self, token: KeyToken) -> EditOutcome:
        state = self._state
        if token.kind == "special" and token.value == "esc":
            if state.command_line:
                self._state = replace(state, command_line="", pending="")
                return EditOutcome(True, command="esc")
            if state.mode in {"insert", "replace"}:
                return self._finish_insert()
            self._state = replace(state, mode="normal", pending="", visual_anchor=None)
            return EditOutcome(True, command="esc")
        if state.command_line:
            return self._prompt_input(token)
        if state.mode in {"insert", "replace"}:
            if self._block_insert is not None and token == KeyToken("special", "enter"):
                return self._reject("블록 삽입에서는 Enter를 지원하지 않습니다.")
            self._insert_tokens.append(token)
            return self._insert(token)
        if token.kind == "special":
            if state.pending.endswith("r") and re.fullmatch(
                r"[1-9][0-9]*r|r", state.pending
            ):
                if token.value != "enter":
                    return self._reject("r 뒤에는 문자 또는 Enter를 입력하세요.")
                if error := self._check("r"):
                    return error
                count = int(state.pending[:-1] or "1")
                line = state.lines[state.row]
                if state.column + count > len(line):
                    return self._reject("치환할 문자가 부족합니다.")
                before = replace(state, pending="")
                lines = (
                    state.lines[: state.row]
                    + (line[: state.column], line[state.column + count :])
                    + state.lines[state.row + 1 :]
                )
                self._set_lines(lines, state.row + 1, 0)
                self._save_change(before)
                return EditOutcome(True, command="r", changed=True)
            if token.value == "enter" and state.pending.endswith("z"):
                count_text = state.pending[:-1]
                result = self._execute("zt", int(count_text or "1"), bool(count_text))
                self._state = replace(
                    self._state,
                    column=_first_nonblank(self._state.lines[self._state.row]),
                )
                return result
            aliases = {
                "enter": "+",
                "backspace": "h",
                "left": "h",
                "right": "l",
                "up": "k",
                "down": "j",
                "home": "0",
                "end": "$",
                "tab": "ctrl+i",
            }
            if token.value in aliases:
                token = KeyToken(
                    "chord" if aliases[token.value].startswith("ctrl+") else "char",
                    aliases[token.value],
                )
            else:
                return self._reject(f"지원하지 않는 Normal 입력: {token.display}")
        if token.kind == "chord":
            if state.pending and not state.pending.isdigit():
                return self._reject("대기 명령을 먼저 마치세요.")
            count = int(state.pending or "1")
            if state.mode.startswith("visual") and token.value == "ctrl+v":
                return self._visual_toggle("visual_block", token.value)
            return self._execute(token.value, count, bool(state.pending))
        pending = state.pending
        char = (
            "l"
            if token.value == " " and re.fullmatch(r'(?:".)?[0-9]*', pending)
            else token.value
        )
        if state.mode.startswith("visual") and not pending:
            if char in _VISUAL_ACTIONS:
                return self._visual_action(char)
            if char in {"v", "V"}:
                return self._visual_toggle(
                    "visual" if char == "v" else "visual_line", char
                )
        value = pending + char
        register_prefix = ""
        if value.startswith('"'):
            if len(value) == 1:
                if error := self._check('"'):
                    return error
                self._state = replace(state, pending=value)
                return EditOutcome(True)
            register = value[1]
            if register not in (
                'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"_-'
            ):
                return self._reject("앱 내부 문자·숫자 레지스터만 사용할 수 있습니다.")
            self._selected_register = register
            register_prefix, value = value[:2], value[2:]
            if not value:
                self._state = replace(state, pending=register_prefix)
                return EditOutcome(True)
        match = re.fullmatch(r"([1-9][0-9]*)?(.*)", value)
        assert match is not None
        leading, body = match[1] or "", match[2]
        count = int(leading or "1")
        if count > _COUNT_LIMIT:
            return self._reject("count와 count의 곱은 999 이하여야 합니다.")
        if not body:
            return self._set_count(register_prefix + value)
        if state.mode.startswith("visual"):
            if body in {"i", "a"}:
                self._state = replace(state, pending=register_prefix + value)
                return EditOutcome(True)
            if body in _OBJECTS:
                try:
                    span = self._object_span(body, count)
                except ValueError as object_error:
                    return self._reject(str(object_error))
                if span is None:
                    return self._reject("텍스트 객체를 찾지 못했습니다.")
                start, end = span
                first = self._position(state.lines, start)
                last_row, last_column = self._position(state.lines, max(start, end - 1))
                self._state = replace(
                    state,
                    mode="visual_line" if body[-1] == "p" else "visual",
                    visual_anchor=first,
                    row=last_row,
                    column=min(last_column, max(0, len(state.lines[last_row]) - 1)),
                    pending="",
                )
                return EditOutcome(True, command=body)
            if body in {"gU", "gu", "g~"}:
                return self._visual_action({"gU": "U", "gu": "u", "g~": "~"}[body])
        if body in {"/", "?", ":"}:
            if error := self._check(body):
                return error
            if body == ":" and (leading or state.mode.startswith("visual")):
                return self._reject("Ex는 Normal 기본형으로 입력하세요.")
            self._state = replace(state, pending=leading + body, command_line=body)
            return EditOutcome(True)
        if body in {"g", "z", "m", "'", "`", "f", "F", "t", "T", "r"}:
            return self._pending(register_prefix + value)
        if len(body) == 2 and body[0] in "m'`fFtTr":
            command, target = body[0], body[1]
            if error := self._check(command):
                return error
            self._state = replace(state, pending="")
            if command == "m":
                if not target.isascii() or not target.isalpha() or not target.islower():
                    return self._reject("문서 내부 마크 a-z만 지원합니다.")
                self._marks[target] = (state.row, state.column)
            elif command in "'`":
                return self._mark_jump(command, target)
            elif command == "r":
                return self._replace_char(target, count)
            else:
                if not self._find(command, target, count):
                    return EditOutcome(True, "문자를 찾지 못했습니다.", command)
            return EditOutcome(True, command=command)
        operator = re.fullmatch(r"(d|c|y|>|<|g[~uU])([1-9][0-9]*)?(.*)", body)
        if operator:
            op, trailing, motion = operator[1], operator[2] or "", operator[3]
            count *= int(trailing or "1")
            if count > _COUNT_LIMIT:
                return self._reject("count와 count의 곱은 999 이하여야 합니다.")
            if motion in {"", "i", "a", "g", "f", "F", "t", "T", "'", "`"}:
                return self._pending(register_prefix + value)
            if (motion == op and len(op) == 1) or (
                op.startswith("g") and motion == op[-1]
            ):
                motion = "line"
            key = op + (
                op
                if motion == "line" and len(op) == 1
                else op[-1]
                if motion == "line"
                else motion[:1]
                if len(motion) == 2 and motion[0] in "fFtT'`"
                else motion
            )
            if error := self._check(key):
                return error
            self._state = replace(state, pending="")
            return self._operator(op, motion, count, bool(leading or trailing))
        return self._execute(body, count, bool(leading))

    def _pending(self, value: str) -> EditOutcome:
        # Check that at least one allowed command can complete this prefix.
        prefix = re.sub(r'^".', "", value)
        prefix = re.sub(r"^[1-9][0-9]*", "", prefix)
        prefix = re.sub(r"^([dcy><]|g[~uU])[1-9][0-9]*", r"\1", prefix)
        if not any(command.startswith(prefix) for command in self.allowed_commands):
            return self._reject("이 과제에서 허용하지 않는 명령입니다.")
        try:
            self._state = replace(self._state, pending=value)
        except ValueError:
            return self._reject("잘못된 명령 또는 count입니다.")
        return EditOutcome(True)

    def _execute(self, command: str, count: int, has_count: bool) -> EditOutcome:
        if command not in SUPPORTED_COMMANDS:
            return self._reject(f"지원하지 않는 편집 명령: {command}")
        if error := self._check(command):
            return error
        if command == "%" and has_count and count > 100:
            return self._reject("문서 백분율은 1~100이어야 합니다.")
        state = replace(self._state, pending="")
        self._state = state
        before = state
        if command in {"i", "a", "I", "A", "o", "O", "R"}:
            self._begin_insert(command, count)
        elif command in {"v", "V", "ctrl+v"}:
            return self._visual_toggle(
                {"v": "visual", "V": "visual_line", "ctrl+v": "visual_block"}[command],
                command,
            )
        elif command in {"x", "X", "s", "S", "D", "C", "Y"}:
            op, motion = {
                "x": ("d", "l"),
                "X": ("d", "h"),
                "s": ("c", "l"),
                "S": ("c", "line"),
                "D": ("d", "$"),
                "C": ("c", "$"),
                "Y": ("y", "line"),
            }[command]
            return self._operator(op, motion, count, has_count, command)
        elif command in {"p", "P", "gp", "gP"}:
            return self._put(command, count)
        elif command in {"u", "ctrl+r"}:
            return self._history(command, count)
        elif command == ".":
            return self._repeat(count if has_count else None)
        elif command in {"J", "gJ"}:
            self._join(count, command == "J")
            self._save_change(before)
        elif command == "~":
            end = min(len(state.lines[state.row]), state.column + count)
            line = state.lines[state.row]
            self._set_lines(
                state.lines[: state.row]
                + (
                    line[: state.column]
                    + line[state.column : end].swapcase()
                    + line[end:],
                )
                + state.lines[state.row + 1 :],
                state.row,
                min(end, max(0, len(line) - 1)),
            )
            self._save_change(before)
        elif command in {"ctrl+a", "ctrl+x"}:
            self._number(count if command == "ctrl+a" else -count)
            self._save_change(before)
        elif command.startswith("ctrl+") or command in {
            "zz",
            "zt",
            "zb",
            "z.",
            "z-",
            "z+",
        }:
            return self._view_or_jump(command, count, has_count)
        elif command in {"n", "N", "*", "#"}:
            return self._search(command, count)
        elif command in {";", ","}:
            if self._last_find is None:
                return EditOutcome(True, "이전 문자 찾기가 없습니다.", command)
            kind, target = self._last_find
            if command == ",":
                kind = {"f": "F", "F": "f", "t": "T", "T": "t"}[kind]
            self._find(kind, target, count, repeat=True)
        elif command in _MOTIONS:
            self._move(command, count, has_count)
        else:
            return self._reject("후속 입력이 필요한 명령입니다.")
        return EditOutcome(
            True, command=command, changed=before.lines != self._state.lines
        )

    def _set_lines(
        self, lines: tuple[str, ...], row: int, column: int, *, insert: bool = False
    ) -> None:
        lines = lines or ("",)
        row = min(max(0, row), len(lines) - 1)
        self._state = replace(
            self._state,
            lines=lines,
            row=row,
            column=min(
                max(0, column),
                len(lines[row]) if insert else max(0, len(lines[row]) - 1),
            ),
            mode="insert" if insert else "normal",
            visual_anchor=None,
            pending="",
            command_line="",
            preferred_column=None,
        )

    def _save_change(self, before: EditorState) -> None:
        if before.lines != self._state.lines:
            self._undo.append(
                _HistoryEntry(
                    self._normal_state(before), self._normal_state(self._state)
                )
            )
            self._redo.clear()

    @staticmethod
    def _normal_state(state: EditorState) -> EditorState:
        return replace(
            state,
            mode="normal",
            column=min(state.column, max(0, len(state.lines[state.row]) - 1)),
            visual_anchor=None,
            command_line="",
            pending="",
        )

    def _history(self, command: str, count: int) -> EditOutcome:
        before = self._state
        source, destination = (
            (self._undo, self._redo) if command == "u" else (self._redo, self._undo)
        )
        for _ in range(count):
            if not source:
                break
            entry = source.pop()
            destination.append(entry)
            result = entry.before if command == "u" else entry.after
            row, column = (
                (result.row, result.column)
                if entry.insert_cursor is None
                else entry.insert_cursor
            )
            row = min(row, len(result.lines) - 1)
            self._state = replace(
                result,
                row=row,
                column=min(column, max(0, len(result.lines[row]) - 1)),
                viewport_rows=before.viewport_rows,
                viewport_top=before.viewport_top,
            )
        return EditOutcome(
            True, command=command, changed=before.lines != self._state.lines
        )

    def _begin_insert(self, command: str, count: int = 1) -> None:
        self._insert_count = count
        self._insert_tokens = []
        self._replace_states = []
        self._block_insert = None
        before = self._state
        if command in {"o", "O"}:
            row = before.row + (command == "o")
            lines = before.lines[:row] + ("",) + before.lines[row:]
            self._set_lines(lines, row, 0, insert=True)
            self._insert_start = before
            self._insert_changed = True
        else:
            state = self._state
            line = state.lines[state.row]
            column = state.column
            if command == "a":
                column = min(len(line), column + 1)
            elif command == "I":
                column = len(line) - len(line.lstrip(" "))
            elif command == "A":
                column = len(line)
            self._insert_changed = False
            self._state = replace(
                state, mode="insert", column=column, preferred_column=None
            )
            self._insert_start = self._state
            if command == "R":
                self._state = replace(self._state, mode="replace")

    def _insert(self, token: KeyToken) -> EditOutcome:
        state = self._state
        if token.kind == "chord" and token.value in {"ctrl+h", "ctrl+w", "ctrl+u"}:
            if token.value == "ctrl+h":
                token = KeyToken("special", "backspace")
            else:
                line = state.lines[state.row]
                column = state.column
                start = 0
                if token.value == "ctrl+w":
                    start = column
                    while start and line[start - 1] == " ":
                        start -= 1
                    if start:
                        category = _word_class(line[start - 1])
                        while start and _word_class(line[start - 1]) == category:
                            start -= 1
                self._set_lines(
                    state.lines[: state.row]
                    + (line[:start] + line[column:],)
                    + state.lines[state.row + 1 :],
                    state.row,
                    start,
                    insert=True,
                )
                if state.mode == "replace":
                    self._state = replace(self._state, mode="replace")
                changed = self._state.lines != state.lines
                self._insert_changed |= changed
                if changed:
                    self._redo.clear()
                return EditOutcome(True, changed=changed)
        if state.mode == "replace":
            if token == KeyToken("special", "backspace") and self._replace_states:
                previous = self._replace_states.pop()
                self._state = previous
                return EditOutcome(True, changed=previous.lines != state.lines)
            if token.kind == "char":
                line = state.lines[state.row]
                self._replace_states.append(state)
                lines = (
                    state.lines[: state.row]
                    + (line[: state.column] + token.value + line[state.column + 1 :],)
                    + state.lines[state.row + 1 :]
                )
                self._state = replace(state, lines=lines, column=state.column + 1)
                self._insert_changed = True
                self._redo.clear()
                return EditOutcome(True, changed=True)
        state = self._state
        editable_lines = list(state.lines)
        row, column = state.row, state.column
        line = editable_lines[row]
        if token.kind == "char":
            editable_lines[row] = line[:column] + token.value + line[column:]
            column += 1
        elif token.kind == "special" and token.value == "enter":
            editable_lines[row : row + 1] = [line[:column], line[column:]]
            row += 1
            column = 0
        elif token.kind == "special" and token.value == "backspace":
            if column:
                editable_lines[row] = line[: column - 1] + line[column:]
                column -= 1
            elif row:
                column = len(editable_lines[row - 1])
                editable_lines[row - 1 : row + 1] = [editable_lines[row - 1] + line]
                row -= 1
        else:
            return self._reject(f"지원하지 않는 Insert 입력: {token.display}")
        changed = tuple(editable_lines) != state.lines
        if changed:
            self._insert_changed = True
            self._redo.clear()
        self._state = replace(
            state,
            lines=tuple(editable_lines),
            row=row,
            column=column,
            preferred_column=None,
        )
        return EditOutcome(True, changed=changed)

    def _finish_insert(self) -> EditOutcome:
        # Counted inserts repeat their actual token stream; a single undo restores
        # both the initial delete/open and every repeated insertion.
        tokens = tuple(self._insert_tokens)
        for _ in range(self._insert_count - 1):
            if (
                self._insert_start is not None
                and len(self._command_tokens)
                and self._command_tokens[0].kind == "char"
            ):
                command_chars = "".join(
                    token.value
                    for token in (
                        self._last_change if self._replaying else self._command_tokens
                    )
                    if token.kind == "char"
                )
                if re.match(r"[1-9][0-9]*[oO]", command_chars):
                    self._insert(KeyToken("special", "enter"))
            for token in tokens:
                self._insert(token)
        if self._block_insert is not None and self._insert_start is not None:
            first, last, column = self._block_insert
            first_cursor = (self._state.row, self._state.column)
            for row in range(first + 1, min(last + 1, len(self._state.lines))):
                lines = list(self._state.lines)
                lines[row] = lines[row].ljust(column)
                self._state = replace(
                    self._state, lines=tuple(lines), row=row, column=column
                )
                for token in tokens:
                    self._insert(token)
            self._state = replace(
                self._state, row=first_cursor[0], column=first_cursor[1]
            )
        self._block_insert = None
        self._insert_count = 1
        self._insert_tokens = []
        state = self._state
        self._state = replace(
            state,
            mode="normal",
            column=max(0, state.column - 1),
            preferred_column=None,
        )
        if self._insert_changed and self._insert_start is not None:
            self._undo.append(
                _HistoryEntry(
                    self._normal_state(self._insert_start),
                    self._state,
                    (self._insert_start.row, self._insert_start.column),
                )
            )
        self._insert_start = None
        self._insert_changed = False
        return EditOutcome(True, command="esc")

    def _repeat(self, count: int | None) -> EditOutcome:
        if not self._last_change:
            return EditOutcome(True, "반복할 변경이 없습니다.", ".")
        tokens = list(self._last_change)
        if count is not None:
            # A repeat count replaces the effective operator/motion count.
            # Keep a named register prefix and literal digits after f/r/Insert.
            command_text = "".join(
                token.value if token.kind == "char" else "\0" for token in tokens
            )
            prefix = re.match(
                r'(".)?(?:[1-9][0-9]*)?([dcy><]|g[~uU])?(?:[1-9][0-9]*)?',
                command_text,
            )
            assert prefix is not None
            replacement = (prefix[1] or "") + str(count) + (prefix[2] or "")
            tokens = [KeyToken("char", char) for char in replacement] + tokens[
                prefix.end() :
            ]
        before = self._state
        history_start = len(self._undo)
        self._replaying = True
        try:
            for token in tokens:
                result = self._submit(token)
                if not result.accepted:
                    return result
                if (
                    self._state.mode == "normal"
                    and not self._state.pending
                    and not self._state.command_line
                ):
                    # The recorded change is one command. If its motion cannot
                    # start Insert here, its saved text must not become Normal
                    # commands (in particular a literal dot must not recurse).
                    break
        finally:
            self._replaying = False
        if count is not None:
            self._last_change = tuple(tokens)
        if len(self._undo) > history_start + 1:
            self._undo[history_start:] = [_HistoryEntry(before, self._state)]
        return EditOutcome(True, command=".", changed=before.lines != self._state.lines)

    @staticmethod
    def _offset(lines: tuple[str, ...], position: tuple[int, int]) -> int:
        row, column = position
        return sum(len(line) + 1 for line in lines[:row]) + column

    @staticmethod
    def _line_span(lines: tuple[str, ...], first: int, last: int) -> tuple[int, int]:
        """Include a virtual final newline so a trailing empty line has a span."""
        start = EditEngine._offset(lines, (first, 0))
        end = EditEngine._offset(lines, (last, len(lines[last]) + 1))
        return start, end

    @staticmethod
    def _position(lines: tuple[str, ...], offset: int) -> tuple[int, int]:
        offset = max(0, offset)
        for row, line in enumerate(lines):
            if offset <= len(line) or row == len(lines) - 1:
                return row, min(offset, len(line))
            offset -= len(line) + 1
        return len(lines) - 1, len(lines[-1])

    def _write_register(
        self, text: tuple[str, ...], kind: str, *, yank: bool = False
    ) -> None:
        register = self._selected_register
        if register == "_":
            return
        if register.isupper():
            name = register.lower()
            previous = self._registers.get(name)
            if previous is not None:
                old, old_kind = previous
                text = (
                    old + text
                    if kind == "line"
                    else tuple(("\n".join(old) + "\n".join(text)).split("\n"))
                )
                kind = old_kind
            register = name
        if register != '"':
            self._registers[register] = (text, kind)
        self._registers['"'] = (text, kind)
        if yank:
            self._registers["0"] = (text, kind)
        elif kind == "line" or len(text) > 1:
            for index in range(9, 1, -1):
                if str(index - 1) in self._registers:
                    self._registers[str(index)] = self._registers[str(index - 1)]
            self._registers["1"] = (text, kind)
        else:
            self._registers["-"] = (text, kind)

    def _yank_outcome(
        self,
        text: tuple[str, ...],
        kind: str,
        spans: tuple[YankSpan, ...],
        command: str,
    ) -> EditOutcome:
        """명시적인 복사만 일회성 범위를 반환한다. 레지스터 내용과 독립적이다."""
        self._write_register(text, kind, yank=True)
        return EditOutcome(
            True,
            command=command,
            yanked_spans=spans if self._selected_register != "_" else (),
        )

    @staticmethod
    def _yank_spans(
        lines: tuple[str, ...], start: int, end: int, *, linewise: bool = False
    ) -> tuple[YankSpan, ...]:
        """엔진의 원본 offset을 표시 가능한 행별 범위로 나눈다."""
        if end <= start:
            return ()
        first, start_column = EditEngine._position(lines, start)
        last, end_column = EditEngine._position(lines, end - 1)
        if linewise:
            return tuple(
                YankSpan(row, 0, len(lines[row])) for row in range(first, last + 1)
            )
        return tuple(
            YankSpan(
                row,
                start_column if row == first else 0,
                min(len(lines[row]), end_column + 1)
                if row == last
                else len(lines[row]),
            )
            for row in range(first, last + 1)
        )

    @staticmethod
    def _difference(before: tuple[str, ...], after: tuple[str, ...]) -> tuple[int, str]:
        original, changed = "\n".join(before), "\n".join(after)
        prefix = 0
        while (
            prefix < min(len(original), len(changed))
            and original[prefix] == changed[prefix]
        ):
            prefix += 1
        suffix = 0
        while (
            suffix < min(len(original) - prefix, len(changed) - prefix)
            and original[-suffix - 1] == changed[-suffix - 1]
        ):
            suffix += 1
        return prefix, original[
            prefix : len(original) - suffix if suffix else len(original)
        ]

    def _operator(
        self,
        op: str,
        motion: str,
        count: int,
        has_count: bool,
        alias: str | None = None,
    ) -> EditOutcome:
        before = self._normal_state(self._state)
        if motion == "%" and has_count and count > 100:
            return self._reject("문서 백분율은 1~100이어야 합니다.")
        command = alias or (op + (op if motion == "line" else motion))
        self._state = before
        word_or_line = op in {"d", "c", "y"} and motion in {
            "w",
            "W",
            "e",
            "E",
            "iw",
            "iW",
            "line",
        }
        insertion: tuple[int, int] | None = None
        if word_or_line:
            actual = motion
            if op == "c" and motion in {"w", "W"}:
                line = before.lines[before.row]
                if line and line[before.column] != " ":
                    actual = "e" if motion == "w" else "E"
                    # ce at the final character must change that character.
                    if count == 1:
                        end = before.column
                        category = _word_class(line[end], motion == "W")
                        while (
                            end + 1 < len(line)
                            and _word_class(line[end + 1], motion == "W") == category
                        ):
                            end += 1
                        start_offset = self._offset(
                            before.lines, (before.row, before.column)
                        )
                        end_offset = self._offset(before.lines, (before.row, end + 1))
                        return self._apply_operator_span(
                            op, start_offset, end_offset, False, before, command
                        )
            self._delete_word_or_lines(
                "dd" if actual == "line" else "d" + actual, count
            )
            changed = self._state
            self._state = replace(
                before,
                lines=changed.lines,
                row=changed.row,
                column=changed.column,
                preferred_column=changed.preferred_column,
            )
            if motion == "line":
                text = before.lines[before.row : before.row + count]
                kind = "line"
                insertion = (min(before.row, len(self._state.lines) - 1), 0)
            else:
                offset, removed = self._difference(before.lines, self._state.lines)
                anchor_column = before.column
                if motion in {"iw", "iW"} and before.lines[before.row]:
                    category = _word_class(
                        before.lines[before.row][anchor_column], motion == "iW"
                    )
                    while (
                        anchor_column
                        and _word_class(
                            before.lines[before.row][anchor_column - 1], motion == "iW"
                        )
                        == category
                    ):
                        anchor_column -= 1
                anchor_offset = self._offset(before.lines, (before.row, anchor_column))
                original_text, changed_text = (
                    "\n".join(before.lines),
                    "\n".join(self._state.lines),
                )
                removed_length = len(original_text) - len(changed_text)
                if (
                    original_text[:anchor_offset]
                    + original_text[anchor_offset + removed_length :]
                    == changed_text
                ):
                    offset = anchor_offset
                    removed = original_text[offset : offset + removed_length]
                text, kind = tuple(removed.split("\n")), "char"
                insertion = self._position(self._state.lines, offset)
            if op == "y":
                self._state = before
                if kind == "line":
                    start, end = self._line_span(
                        before.lines,
                        before.row,
                        min(len(before.lines) - 1, before.row + count - 1),
                    )
                else:
                    start, end = offset, offset + len(removed)
                return self._yank_outcome(
                    text,
                    kind,
                    self._yank_spans(before.lines, start, end, linewise=kind == "line"),
                    command,
                )
            if before.lines != self._state.lines:
                self._write_register(text, kind)
            if op == "c":
                if motion == "line":
                    # A linewise change leaves a new empty line, retaining indent.
                    indent = ""
                    end = min(len(before.lines), before.row + count)
                    lines = before.lines[: before.row] + (indent,) + before.lines[end:]
                    self._set_lines(lines, before.row, len(indent), insert=True)
                else:
                    assert insertion is not None
                    self._set_lines(
                        self._state.lines, insertion[0], insertion[1], insert=True
                    )
                self._insert_start = before
                self._insert_changed = before.lines != self._state.lines
                self._insert_count = 1
                self._insert_tokens = []
            else:
                self._save_change(before)
            return EditOutcome(
                True, command=command, changed=before.lines != self._state.lines
            )
        if motion == "line":
            start, end = self._line_span(
                before.lines,
                before.row,
                min(len(before.lines) - 1, before.row + count - 1),
            )
            linewise = True
        elif motion in _OBJECTS:
            try:
                span = self._object_span(motion, count)
            except ValueError as object_error:
                return self._reject(str(object_error))
            if span is None:
                self._state = before
                return EditOutcome(True, "텍스트 객체를 찾지 못했습니다.", command)
            start, end = span
            linewise = motion[-1] == "p"
        else:
            start = self._offset(before.lines, (before.row, before.column))
            target: str | None = None
            kind = motion
            if len(motion) == 2 and motion[0] in "fFtT'`":
                kind, target = motion[0], motion[1]
            if target is not None:
                if kind in "fFtT":
                    if not self._find(kind, target, count):
                        self._state = before
                        return EditOutcome(True, "문자를 찾지 못했습니다.", command)
                else:
                    result = self._mark_jump(kind, target)
                    if not result.accepted:
                        self._state = before
                        return result
            elif kind in {";", ","}:
                if self._last_find is None:
                    return EditOutcome(True, "이전 문자 찾기가 없습니다.", command)
                find_kind, target = self._last_find
                if kind == ",":
                    find_kind = {"f": "F", "F": "f", "t": "T", "T": "t"}[find_kind]
                if not self._find(find_kind, target, count, repeat=True):
                    self._state = before
                    return EditOutcome(True, "문자를 찾지 못했습니다.", command)
                kind = find_kind
            elif kind in {"n", "N", "*", "#"}:
                result = self._search(kind, count)
                if not result.accepted:
                    return result
            elif kind in _MOTIONS:
                self._move(kind, count, has_count)
            else:
                return self._reject(f"지원하지 않는 motion: {motion}")
            target_state = self._state
            if (
                kind == "%"
                and not has_count
                and (target_state.row, target_state.column)
                == (before.row, before.column)
            ):
                self._state = before
                return EditOutcome(True, "대응하는 괄호를 찾지 못했습니다.", command)
            end = self._offset(before.lines, (target_state.row, target_state.column))
            linewise = kind in {
                "j",
                "k",
                "gg",
                "G",
                "H",
                "M",
                "L",
                "+",
                "-",
                "_",
                "'",
            } or (kind == "%" and has_count)
            if linewise:
                first, last = sorted((before.row, target_state.row))
                start, end = self._line_span(before.lines, first, last)
            elif kind in {"$", "g$", "g_", "e", "E", "ge", "gE", "%", "f", "t"}:
                start, end = min(start, end), max(start, end) + 1
            else:
                start, end = sorted((start, end))
                if kind == "l":
                    end = min(
                        self._offset(
                            before.lines, (before.row, len(before.lines[before.row]))
                        ),
                        start + count,
                    )
        self._state = before
        return self._apply_operator_span(op, start, end, linewise, before, command)

    def _apply_operator_span(
        self,
        op: str,
        start: int,
        end: int,
        linewise: bool,
        before: EditorState,
        command: str,
    ) -> EditOutcome:
        text = "\n".join(before.lines)
        start = max(0, start)
        first, start_column = self._position(before.lines, start)
        last, _ = self._position(before.lines, max(start, end - 1))
        end = min(len(text), end)
        if linewise:
            selected = before.lines[first : last + 1]
        else:
            selected = tuple(text[start:end].split("\n"))
        if op == "y":
            spans = (
                tuple(
                    YankSpan(row, 0, len(before.lines[row]))
                    for row in range(first, last + 1)
                )
                if linewise
                else self._yank_spans(before.lines, start, end)
            )
            return self._yank_outcome(
                selected, "line" if linewise else "char", spans, command
            )
        if op in {">", "<"}:
            shifted_lines = list(before.lines)
            for row in range(first, last + 1):
                if op == ">":
                    if shifted_lines[row]:
                        shifted_lines[row] = "    " + shifted_lines[row]
                else:
                    indent = len(shifted_lines[row]) - len(
                        shifted_lines[row].lstrip(" ")
                    )
                    shifted_lines[row] = shifted_lines[row][min(4, indent) :]
            self._set_lines(
                tuple(shifted_lines), first, _first_nonblank(shifted_lines[first])
            )
        elif op in {"g~", "gu", "gU"}:
            selected_text = text[start:end]
            replacement = (
                selected_text.swapcase()
                if op == "g~"
                else selected_text.lower()
                if op == "gu"
                else selected_text.upper()
            )
            lines = tuple((text[:start] + replacement + text[end:]).split("\n"))
            self._set_lines(lines, first, start_column)
        elif op in {"d", "c"}:
            if start == end and not linewise:
                if op == "c":
                    self._begin_insert("i")
                return EditOutcome(True, command=command)
            self._write_register(selected, "line" if linewise else "char")
            if linewise:
                lines = (
                    before.lines[:first]
                    + (("",) if op == "c" else ())
                    + before.lines[last + 1 :]
                )
                self._set_lines(lines, first, 0, insert=op == "c")
                if op == "d":
                    self._state = replace(
                        self._state,
                        column=_first_nonblank(self._state.lines[self._state.row]),
                    )
            else:
                lines = tuple((text[:start] + text[end:]).split("\n"))
                self._set_lines(lines, first, start_column, insert=op == "c")
            if op == "c":
                self._insert_start = before
                self._insert_changed = before.lines != self._state.lines
                self._insert_count = 1
                self._insert_tokens = []
        else:
            return self._reject("지원하지 않는 연산자입니다.")
        if op != "c":
            self._save_change(before)
        return EditOutcome(
            True, command=command, changed=before.lines != self._state.lines
        )

    @staticmethod
    def _escaped_quote(line: str, column: int) -> bool:
        backslashes = 0
        index = column - 1
        while index >= 0 and line[index] == "\\":
            backslashes += 1
            index -= 1
        return bool(backslashes % 2)

    def _object_span(self, motion: str, count: int) -> tuple[int, int] | None:
        state = self._state
        around, obj = motion[0] == "a", motion[1]
        line = state.lines[state.row]
        current = self._offset(state.lines, (state.row, state.column))
        text = "\n".join(state.lines)
        if obj in {"w", "W"}:
            has_next_line = state.row + 1 < len(state.lines)
            boundary_message = "줄을 넘는 aw/aW 텍스트 객체는 지원하지 않습니다."
            if not line:
                if around and has_next_line:
                    raise ValueError(boundary_message)
                return current, current
            start, end = state.column, state.column
            category = _word_class(line[start], obj == "W")
            started_in_space = category == 0
            while start and _word_class(line[start - 1], obj == "W") == category:
                start -= 1
            while end < len(line) and _word_class(line[end], obj == "W") == category:
                end += 1
            if around and started_in_space:
                if end == len(line) and has_next_line:
                    raise ValueError(boundary_message)
                if end < len(line):
                    category = _word_class(line[end], obj == "W")
                    while (
                        end < len(line)
                        and _word_class(line[end], obj == "W") == category
                    ):
                        end += 1
            for _ in range(count - 1):
                while end < len(line) and line[end] == " ":
                    end += 1
                if end < len(line):
                    category = _word_class(line[end], obj == "W")
                    while (
                        end < len(line)
                        and _word_class(line[end], obj == "W") == category
                    ):
                        end += 1
                elif around and has_next_line:
                    raise ValueError(boundary_message)
            if around and not started_in_space:
                following = end
                while following < len(line) and line[following] == " ":
                    following += 1
                if following == end:
                    while start and line[start - 1] == " ":
                        start -= 1
                end = following
            base = self._offset(state.lines, (state.row, 0))
            return base + start, base + end
        if obj == "p":
            first, last = state.row, state.row
            blank = not line.strip()
            while first and (not state.lines[first - 1].strip()) == blank:
                first -= 1
            while (
                last + 1 < len(state.lines)
                and (not state.lines[last + 1].strip()) == blank
            ):
                last += 1
            for _ in range(count - 1):
                while last + 1 < len(state.lines) and not state.lines[last + 1].strip():
                    last += 1
                while last + 1 < len(state.lines) and state.lines[last + 1].strip():
                    last += 1
            if around:
                if last + 1 < len(state.lines):
                    while (
                        last + 1 < len(state.lines)
                        and not state.lines[last + 1].strip()
                    ):
                        last += 1
                else:
                    while first and not state.lines[first - 1].strip():
                        first -= 1
            return self._line_span(state.lines, first, last)
        if obj == "s":
            boundaries = (
                [0]
                + [match.end() for match in re.finditer(r'[.!?][)\]"\']*\s+', text)]
                + [len(text)]
            )
            index = max(0, bisect_right(boundaries, current) - 1)
            start, end = (
                boundaries[index],
                boundaries[min(len(boundaries) - 1, index + count)],
            )
            if not around:
                while end > start and text[end - 1].isspace():
                    end -= 1
            return start, end
        if obj in {'"', "'", "`"}:
            positions = [
                i
                for i, char in enumerate(line)
                if char == obj and not self._escaped_quote(line, i)
            ]
            for index in range(0, len(positions) - 1, 2):
                left, right = positions[index : index + 2]
                if right >= state.column:
                    base = self._offset(state.lines, (state.row, 0))
                    if not around:
                        return base + left + (count == 1), base + right + (count > 1)
                    end = right + 1
                    while end < len(line) and line[end] == " ":
                        end += 1
                    if end == right + 1:
                        while left and line[left - 1] == " ":
                            left -= 1
                    return base + left, base + end
            return None
        pairs = {
            "(": ("(", ")"),
            ")": ("(", ")"),
            "b": ("(", ")"),
            "[": ("[", "]"),
            "]": ("[", "]"),
            "{": ("{", "}"),
            "}": ("{", "}"),
            "B": ("{", "}"),
            "<": ("<", ">"),
            ">": ("<", ">"),
        }
        if obj not in pairs:
            return None
        opening, closing = pairs[obj]
        stack: list[int] = []
        candidates: list[tuple[int, int]] = []
        for offset, char in enumerate(text):
            if char == opening:
                stack.append(offset)
            elif char == closing and stack:
                left = stack.pop()
                if left <= current <= offset:
                    candidates.append((left, offset))
        candidates.sort(key=lambda span: span[1] - span[0])
        if count > len(candidates):
            return None
        left, right = candidates[count - 1]
        return left + (not around), right + around

    def _move(self, command: str, count: int, has_count: bool) -> None:
        state = self._state
        if command in {
            "h",
            "j",
            "k",
            "l",
            "w",
            "W",
            "b",
            "B",
            "e",
            "E",
            "0",
            "^",
            "gg",
            "G",
        }:
            if command in {"gg", "G"}:
                self._push_jump()
            self._move_basic(command, count, has_count)
            return
        row, column = state.row, state.column
        preference: int | None = None
        if command in {"$", "g$", "g_"}:
            row = min(len(state.lines) - 1, row + count - 1)
            column = max(0, len(state.lines[row]) - 1)
            if command == "g_":
                column = max(0, len(state.lines[row].rstrip(" ")) - 1)
            preference = _END_COLUMN
        elif command in {"gj", "gk", "g0"}:
            self._move_basic(
                {"gj": "j", "gk": "k", "g0": "0"}[command], count, has_count
            )
            return
        elif command == "|":
            column = min(count - 1, max(0, len(state.lines[row]) - 1))
        elif command in {"+", "-", "_"}:
            row = min(
                len(state.lines) - 1,
                max(
                    0,
                    row
                    + (
                        count
                        if command == "+"
                        else -count
                        if command == "-"
                        else count - 1
                    ),
                ),
            )
            column = _first_nonblank(state.lines[row])
        elif command in {"ge", "gE"}:
            ends = _word_ends(state.lines, command == "gE")
            index = bisect_left(ends, (row, column)) - count
            row, column = ends[index] if index >= 0 else (0, 0)
        elif command in {"{", "}"}:
            direction = 1 if command == "}" else -1
            for _ in range(count):
                candidate = row + direction
                while (
                    0 <= candidate < len(state.lines)
                    and not state.lines[candidate].strip()
                ):
                    candidate += direction
                while (
                    0 <= candidate < len(state.lines) and state.lines[candidate].strip()
                ):
                    candidate += direction
                row = min(len(state.lines) - 1, max(0, candidate))
            column = 0
        elif command in {"(", ")"}:
            text = "\n".join(state.lines)
            starts = [0] + [
                match.end() for match in re.finditer(r'[.!?][)\]"\']*\s+|\n\n+', text)
            ]
            offset = self._offset(state.lines, (row, column))
            for _ in range(count):
                if command == ")":
                    index = bisect_right(starts, offset)
                    offset = (
                        starts[index] if index < len(starts) else max(0, len(text) - 1)
                    )
                else:
                    index = bisect_left(starts, offset) - 1
                    offset = starts[index] if index >= 0 else 0
            row, column = self._position(state.lines, offset)
            column = min(column, max(0, len(state.lines[row]) - 1))
        elif command == "%":
            if has_count:
                if count > 100:
                    return
                self._push_jump()
                row = max(0, (len(state.lines) * count + 99) // 100 - 1)
                column = _first_nonblank(state.lines[row])
            else:
                line = state.lines[row]
                found = next(
                    (
                        index
                        for index in range(column, len(line))
                        if line[index] in "()[]{}"
                    ),
                    None,
                )
                if found is None:
                    return
                text = "\n".join(state.lines)
                offset = self._offset(state.lines, (row, found))
                char = text[offset]
                pairs = {"(": ")", "[": "]", "{": "}", ")": "(", "]": "[", "}": "{"}
                direction = 1 if char in "([{" else -1
                depth = 1
                index = offset + direction
                while 0 <= index < len(text):
                    if text[index] == char:
                        depth += 1
                    elif text[index] == pairs[char]:
                        depth -= 1
                        if depth == 0:
                            row, column = self._position(state.lines, index)
                            break
                    index += direction
        elif command in {"H", "M", "L"}:
            last = min(
                len(state.lines) - 1, state.viewport_top + state.viewport_rows - 1
            )
            row = (
                min(last, state.viewport_top + count - 1)
                if command == "H"
                else max(state.viewport_top, last - count + 1)
                if command == "L"
                else (state.viewport_top + last) // 2
            )
            column = _first_nonblank(state.lines[row])
        self._state = replace(
            state, row=row, column=column, preferred_column=preference
        )

    def _find(
        self, command: str, target: str, count: int, *, repeat: bool = False
    ) -> bool:
        state = self._state
        line = state.lines[state.row]
        forward = command in {"f", "t"}
        position = state.column
        if repeat and command in {"t", "T"}:
            position += 1 if forward else -1
        for _ in range(count):
            position = (
                line.find(target, position + 1)
                if forward
                else line.rfind(target, 0, max(0, position))
            )
            if position < 0:
                if not repeat:
                    self._last_find = (command, target)
                return False
        if command in {"t", "T"}:
            position += -1 if forward else 1
        self._state = replace(state, column=position, preferred_column=None)
        if not repeat:
            self._last_find = (command, target)
        return True

    def _replace_char(self, target: str, count: int) -> EditOutcome:
        state = self._state
        line = state.lines[state.row]
        if state.column + count > len(line):
            return EditOutcome(True, "치환할 문자가 부족합니다.", "r")
        lines = (
            state.lines[: state.row]
            + (line[: state.column] + target * count + line[state.column + count :],)
            + state.lines[state.row + 1 :]
        )
        self._set_lines(lines, state.row, state.column + count - 1)
        self._save_change(state)
        return EditOutcome(True, command="r", changed=state.lines != self._state.lines)

    def _put(self, command: str, count: int) -> EditOutcome:
        state = self._normal_state(self._state)
        value = self._registers.get(self._selected_register.lower())
        if value is None:
            return EditOutcome(True, "레지스터가 비어 있습니다.", command)
        text, kind = value
        after = command in {"p", "gp"}
        if kind == "line":
            row = state.row + after
            inserted = text * count
            lines = state.lines[:row] + inserted + state.lines[row:]
            cursor_row = (
                min(len(lines) - 1, row + len(inserted))
                if command.startswith("g")
                else row
            )
            self._set_lines(lines, cursor_row, _first_nonblank(lines[cursor_row]))
        elif kind == "block":
            column = state.column + (after and bool(state.lines[state.row]))
            lines = self._put_block(state.lines, text, state.row, column, count)
            self._set_lines(lines, state.row, column)
        else:
            inserted_text = "\n".join(text) * count
            column = min(len(state.lines[state.row]), state.column + after)
            offset = self._offset(state.lines, (state.row, column))
            original = "\n".join(state.lines)
            lines = tuple(
                (original[:offset] + inserted_text + original[offset:]).split("\n")
            )
            cursor = offset + len(inserted_text) - 1
            if "\n" in inserted_text and not command.startswith("g"):
                cursor = offset
            elif command.startswith("g"):
                cursor += 1
            row, column = self._position(lines, cursor)
            self._set_lines(lines, row, column)
        self._save_change(state)
        return EditOutcome(
            True, command=command, changed=state.lines != self._state.lines
        )

    def _join(self, count: int, spaces: bool) -> None:
        state = self._state
        last = min(len(state.lines), state.row + max(2, count))
        if last <= state.row + 1:
            return
        line = state.lines[state.row]
        column = len(line)
        for following in state.lines[state.row + 1 : last]:
            if spaces:
                following = following.lstrip(" ")
                separator = (
                    " "
                    if line
                    and not line.endswith(" ")
                    and following
                    and not following.startswith(")")
                    else ""
                )
                column = len(line)
                line += separator + following
            else:
                column = len(line)
                line += following
        self._set_lines(
            state.lines[: state.row] + (line,) + state.lines[last:], state.row, column
        )

    def _number(self, delta: int) -> None:
        state = self._state
        line = state.lines[state.row]
        candidates = list(
            re.finditer(r"-?(?:0[xX][0-9a-fA-F]+|0[bB][01]+|[0-9]+)", line)
        )
        match = next((item for item in candidates if item.end() > state.column), None)
        if match is None:
            return
        raw = match[0]
        unsigned = raw.lstrip("-")
        base = (
            16
            if unsigned.lower().startswith("0x")
            else 2
            if unsigned.lower().startswith("0b")
            else 8
            if len(unsigned) > 1
            and unsigned.startswith("0")
            and all(char in "01234567" for char in unsigned)
            else 10
        )
        if base == 10:
            # With octal enabled 008/009 are decimal, without zero padding.
            value = (int(raw, 10) + delta + 2**63) % 2**64 - 2**63
            replacement = str(value)
        else:
            # Nondecimal numbers are unsigned, and a preceding minus remains
            # ordinary buffer text. Width and the last existing hex letter's
            # case follow Vim's nrformats=bin,octal,hex behavior.
            value = (int(unsigned, base) + delta) % 2**64
            sign = "-" if raw.startswith("-") else ""
            if base in {16, 2}:
                letters = [char for char in unsigned[2:] if char.lower() in "abcdef"]
                uppercase = bool(letters and letters[-1].isupper())
                digits = format(value, "b" if base == 2 else "X" if uppercase else "x")
                replacement = sign + unsigned[:2] + digits.zfill(len(unsigned) - 2)
            else:
                replacement = sign + "0" + format(value, "o").zfill(len(unsigned) - 1)
        self._set_lines(
            state.lines[: state.row]
            + (line[: match.start()] + replacement + line[match.end() :],)
            + state.lines[state.row + 1 :],
            state.row,
            match.start() + len(replacement) - 1,
        )

    def _track_marks(self, before: EditorState, after: EditorState) -> None:
        if not self._marks:
            return
        original, changed = "\n".join(before.lines), "\n".join(after.lines)
        start, removed = self._difference(before.lines, after.lines)
        removed_length = len(removed)
        inserted_length = len(changed) - len(original) + removed_length
        # Repeated text permits more than one diff. Favor the input cursor when
        # it describes the exact same single insertion/deletion.
        anchor = self._offset(before.lines, (before.row, before.column))
        if (
            inserted_length == 0
            and original[:anchor] + original[anchor + removed_length :] == changed
        ):
            start = anchor
        elif (
            removed_length == 0
            and changed[:anchor] + changed[anchor + inserted_length :] == original
        ):
            start = anchor
        end = start + removed_length
        for name, position in tuple(self._marks.items()):
            offset = self._offset(before.lines, position)
            if offset >= end:
                offset += inserted_length - removed_length
            elif offset >= start:
                offset = start
            row, column = self._position(after.lines, offset)
            self._marks[name] = (row, min(column, max(0, len(after.lines[row]) - 1)))

    def _set_count(self, pending: str) -> EditOutcome:
        counts = [
            int(value) for value in re.findall(r"[0-9]+", re.sub(r'^".', "", pending))
        ]
        if any(count > _COUNT_LIMIT for count in counts) or (
            len(counts) == 2 and counts[0] * counts[1] > _COUNT_LIMIT
        ):
            return self._reject("count와 count의 곱은 999 이하여야 합니다.")
        self._state = replace(self._state, pending=pending)
        return EditOutcome(True)

    def _push_jump(self) -> None:
        position = (self._state.row, self._state.column)
        if self._jump_index >= 0:
            self._jumps = self._jumps[: self._jump_index + 1]
        if not self._jumps or self._jumps[-1] != position:
            self._jumps.append(position)
        self._jumps = self._jumps[-100:]
        self._jump_index = -1

    def _mark_jump(self, command: str, target: str) -> EditOutcome:
        if target in {"'", "`"} and self._jumps:
            position = self._jumps[-1]
        elif target in self._marks:
            position = self._marks[target]
        else:
            return self._reject("설정되지 않은 문서 내부 마크입니다.")
        self._push_jump()
        row = min(position[0], len(self._state.lines) - 1)
        column = (
            _first_nonblank(self._state.lines[row])
            if command == "'"
            else min(position[1], max(0, len(self._state.lines[row]) - 1))
        )
        self._state = replace(
            self._state, row=row, column=column, pending="", preferred_column=None
        )
        return EditOutcome(True, command=command)

    def _view_or_jump(self, command: str, count: int, has_count: bool) -> EditOutcome:
        state = self._state
        row, column, top = state.row, state.column, state.viewport_top
        height = state.viewport_rows
        if command in {"ctrl+o", "ctrl+i"}:
            if not self._jumps:
                return EditOutcome(True, "이전 점프가 없습니다.", command)
            if self._jump_index < 0:
                self._jumps.append((row, column))
                self._jump_index = len(self._jumps) - 1
            self._jump_index = min(
                len(self._jumps) - 1,
                max(0, self._jump_index + (-count if command == "ctrl+o" else count)),
            )
            row, column = self._jumps[self._jump_index]
            row = min(row, len(state.lines) - 1)
            column = min(column, max(0, len(state.lines[row]) - 1))
        elif command in {"ctrl+u", "ctrl+d", "ctrl+f", "ctrl+b"}:
            forward = command in {"ctrl+d", "ctrl+f"}
            if command in {"ctrl+u", "ctrl+d"}:
                if has_count:
                    self._scroll_rows = min(height, count)
                distance = (
                    self._scroll_rows
                    if self._scroll_rows is not None
                    else max(1, height // 2)
                )
            else:
                distance = max(1, height - 2) * count
            direction = 1 if forward else -1
            if command in {"ctrl+u", "ctrl+d"} and row == (
                len(state.lines) - 1 if forward else 0
            ):
                return EditOutcome(True, command=command)
            row = min(len(state.lines) - 1, max(0, row + direction * distance))
            top = min(
                max(0, len(state.lines) - height), max(0, top + direction * distance)
            )
            column = _first_nonblank(state.lines[row])
        elif command in {"ctrl+e", "ctrl+y"}:
            top = min(
                len(state.lines) - 1,
                max(0, top + (count if command == "ctrl+e" else -count)),
            )
            row = min(top + height - 1, max(top, row))
            column = min(column, max(0, len(state.lines[row]) - 1))
        elif command in {"zz", "zt", "zb", "z.", "z-", "z+"}:
            if has_count:
                row = min(count - 1, len(state.lines) - 1)
                column = min(column, max(0, len(state.lines[row]) - 1))
            if command in {"zz", "z."}:
                top = max(0, row - height // 2)
            elif command in {"zt", "z+"}:
                if command == "z+" and not has_count:
                    row = min(len(state.lines) - 1, top + height)
                    column = _first_nonblank(state.lines[row])
                top = row
            else:
                top = max(0, row - height + 1)
            if command in {"z.", "z-"}:
                column = _first_nonblank(state.lines[row])
        else:
            return self._reject("지원하지 않는 Control 입력입니다.")
        self._state = replace(
            state, row=row, column=column, viewport_top=top, preferred_column=None
        )
        return EditOutcome(True, command=command)

    def _prompt_input(self, token: KeyToken) -> EditOutcome:
        state = self._state
        prompt = state.command_line
        if token.kind == "special" and token.value == "backspace":
            if len(prompt) == 1:
                self._state = replace(state, command_line="", pending="")
            else:
                self._state = replace(state, command_line=prompt[:-1])
            return EditOutcome(True)
        if token.kind == "char":
            if len(prompt) >= 512:
                return self._reject("검색·명령행은 511자 이하여야 합니다.")
            self._state = replace(state, command_line=prompt + token.value)
            return EditOutcome(True)
        if token.kind != "special" or token.value != "enter":
            return self._reject("검색·명령행에서 지원하지 않는 키입니다.")
        self._state = replace(state, pending="", command_line="")
        if prompt[0] in "/?":
            pattern = prompt[1:]
            if not pattern and self._last_search is not None:
                pattern = self._last_search[0]
            if not pattern:
                return self._reject("검색어가 없습니다.")
            return self._search_pattern(
                pattern, prompt[0] == "/", int(state.pending[:-1] or "1"), prompt[0]
            )
        return self._ex(prompt[1:])

    def _search_pattern(
        self,
        pattern: str,
        forward: bool,
        count: int,
        command: str,
        *,
        remember: bool = True,
    ) -> EditOutcome:
        state = self._state
        try:
            position = find_match(
                state.lines, state.row, state.column, pattern, forward, count
            )
        except ValueError as error:
            return self._reject(str(error))
        if remember:
            self._last_search = (pattern, forward)
        if position is None:
            return EditOutcome(True, "검색어를 찾지 못했습니다.", command)
        self._push_jump()
        row, column = position
        column = min(column, max(0, len(state.lines[row]) - 1))
        self._state = replace(state, row=row, column=column, preferred_column=None)
        return EditOutcome(True, command=command)

    def _search(self, command: str, count: int) -> EditOutcome:
        if command in {"*", "#"}:
            line = self._state.lines[self._state.row]
            column = self._state.column
            words = list(re.finditer(r"[A-Za-z0-9_]+", line))
            word = next((match for match in words if match.end() > column), None)
            if word is None:
                return EditOutcome(True, "현재 줄에 검색할 단어가 없습니다.", command)
            pattern = r"\<" + re.escape(word[0]) + r"\>"
            return self._search_pattern(pattern, command == "*", count, command)
        if self._last_search is None:
            return EditOutcome(True, "이전 검색이 없습니다.", command)
        pattern, forward = self._last_search
        return self._search_pattern(
            pattern,
            not forward if command == "N" else forward,
            count,
            command,
            remember=False,
        )

    def _ex(self, command: str) -> EditOutcome:
        before = self._state
        if re.fullmatch(r"[0-9]+|\$", command):
            row = (
                len(before.lines) - 1
                if command == "$"
                else min(max(0, int(command) - 1), len(before.lines) - 1)
            )
            self._push_jump()
            self._state = replace(
                before, row=row, column=_first_nonblank(before.lines[row])
            )
            return EditOutcome(True, command=":")
        try:
            lines, replacements = substitute(before.lines, command, before.row)
        except ValueError as error:
            return self._reject(str(error))
        if replacements:
            row = next(
                (
                    index
                    for index, (old, new) in enumerate(
                        zip(before.lines, lines, strict=True)
                    )
                    if old != new
                ),
                before.row,
            )
            self._set_lines(lines, row, _first_nonblank(lines[row]))
            self._save_change(before)
        return EditOutcome(
            True,
            f"{replacements}곳을 치환했습니다.",
            ":",
            before.lines != self._state.lines,
        )

    def _visual_toggle(self, mode: str, command: str) -> EditOutcome:
        if error := self._check(command):
            return error
        state = self._state
        if state.mode == mode:
            self._state = replace(state, mode="normal", visual_anchor=None, pending="")
        else:
            anchor = state.visual_anchor or (state.row, state.column)
            self._state = replace(state, mode=mode, visual_anchor=anchor, pending="")  # type: ignore[arg-type]
        return EditOutcome(True, command=command)

    def _visual_action(self, command: str) -> EditOutcome:
        state = self._state
        anchor = state.visual_anchor
        assert anchor is not None
        first, last = sorted((anchor, (state.row, state.column)))
        if command == "o":
            self._state = replace(
                state,
                row=anchor[0],
                column=anchor[1],
                visual_anchor=(state.row, state.column),
            )
            return EditOutcome(True, command="o")
        if error := self._check(_VISUAL_ACTIONS[command]):
            return error
        before = self._normal_state(state)
        if command in {"p", "P"}:
            return self._visual_put(command, first, last)
        if command in {"I", "A"} and state.mode != "visual_block":
            self._state = replace(before, row=first[0], column=first[1])
            self._begin_insert(command)
            return EditOutcome(True, command=command)
        if state.mode == "visual_block" and command in {
            "d",
            "x",
            "y",
            "c",
            "s",
            "I",
            "A",
            "~",
            "u",
            "U",
        }:
            top, bottom = sorted((anchor[0], state.row))
            left, right = sorted((anchor[1], state.column))
            lines = list(state.lines)
            pieces = tuple(line[left : right + 1] for line in lines[top : bottom + 1])
            self._state = before
            if command == "y":
                self._state = replace(
                    before, row=top, column=min(left, max(0, len(lines[top]) - 1))
                )
                spans = tuple(
                    YankSpan(row, left, min(right + 1, len(lines[row])))
                    for row in range(top, bottom + 1)
                    if left < len(lines[row])
                )
                return self._yank_outcome(pieces, "block", spans, command)
            if command in {"d", "x", "c", "s"}:
                self._write_register(pieces, "block")
                for row in range(top, bottom + 1):
                    lines[row] = lines[row][:left] + lines[row][right + 1 :]
            elif command in {"~", "u", "U"}:
                for row in range(top, bottom + 1):
                    piece = lines[row][left : right + 1]
                    replacement = (
                        piece.swapcase()
                        if command == "~"
                        else piece.lower()
                        if command == "u"
                        else piece.upper()
                    )
                    lines[row] = (
                        lines[row][:left] + replacement + lines[row][right + 1 :]
                    )
            insertion = command in {"c", "s", "I", "A"}
            column = right + 1 if command == "A" else left
            if insertion:
                lines[top] = lines[top].ljust(column)
            self._set_lines(tuple(lines), top, column, insert=insertion)
            if insertion:
                self._insert_start = before
                self._insert_changed = state.lines != self._state.lines
                self._insert_tokens = []
                self._insert_count = 1
                self._block_insert = (top, bottom, column)
            else:
                self._save_change(before)
            return EditOutcome(
                True, command=command, changed=state.lines != self._state.lines
            )
        self._state = before
        if command == "J":
            self._state = replace(before, row=first[0], column=first[1])
            self._join(last[0] - first[0] + 1, True)
            self._save_change(before)
            return EditOutcome(
                True, command=command, changed=before.lines != self._state.lines
            )
        linewise = state.mode == "visual_line" or command in {
            "Y",
            "D",
            "X",
            "C",
            "S",
            "R",
        }
        if linewise:
            start, end = self._line_span(state.lines, first[0], last[0])
        else:
            start = self._offset(state.lines, first)
            end = min(len("\n".join(state.lines)), self._offset(state.lines, last) + 1)
        op = {
            "d": "d",
            "x": "d",
            "D": "d",
            "X": "d",
            "c": "c",
            "s": "c",
            "C": "c",
            "S": "c",
            "R": "c",
            "y": "y",
            "Y": "y",
            ">": ">",
            "<": "<",
            "~": "g~",
            "u": "gu",
            "U": "gU",
        }[command]
        return self._apply_operator_span(op, start, end, linewise, before, command)

    def _visual_put(
        self, command: str, first: tuple[int, int], last: tuple[int, int]
    ) -> EditOutcome:
        state = self._state
        before = self._normal_state(state)
        value = self._registers.get(self._selected_register.lower())
        if value is None:
            return EditOutcome(True, "레지스터가 비어 있습니다.", command)
        contents, kind = value
        row, column = first
        if state.mode == "visual_line":
            removed, removed_kind = state.lines[first[0] : last[0] + 1], "line"
            lines = state.lines[:row] + contents + state.lines[last[0] + 1 :]
            column = _first_nonblank(contents[0])
        else:
            if state.mode == "visual_block":
                anchor = state.visual_anchor
                assert anchor is not None
                row, bottom = sorted((anchor[0], state.row))
                column, right = sorted((anchor[1], state.column))
                removed = tuple(
                    line[column : right + 1] for line in state.lines[row : bottom + 1]
                )
                removed_kind = "block"
                changed = list(state.lines)
                for index in range(row, bottom + 1):
                    changed[index] = (
                        changed[index][:column] + changed[index][right + 1 :]
                    )
                if kind == "line":
                    lines = (
                        tuple(changed[: bottom + 1])
                        + contents
                        + tuple(changed[bottom + 1 :])
                    )
                    row, column = bottom + 1, _first_nonblank(contents[0])
                elif kind == "char" and len(contents) == 1:
                    for index in range(row, bottom + 1):
                        changed[index] = (
                            changed[index][:column]
                            + contents[0]
                            + changed[index][column:]
                        )
                    lines = tuple(changed)
                    column += max(0, len(contents[0]) - 1)
                else:
                    lines = tuple(changed)
            else:
                original = "\n".join(state.lines)
                start = self._offset(state.lines, first)
                end = min(len(original), self._offset(state.lines, last) + 1)
                removed, removed_kind = tuple(original[start:end].split("\n")), "char"
                lines = tuple((original[:start] + original[end:]).split("\n"))
            if kind == "block":
                lines = self._put_block(lines, contents, row, column)
            elif kind == "char" and not (
                state.mode == "visual_block" and len(contents) == 1
            ):
                offset = self._offset(lines, (row, column))
                original = "\n".join(lines)
                inserted = "\n".join(contents)
                lines = tuple(
                    (original[:offset] + inserted + original[offset:]).split("\n")
                )
                if state.mode != "visual_block" and len(contents) == 1:
                    column += max(0, len(inserted) - 1)
            elif kind == "line" and state.mode != "visual_block":
                offset = self._offset(lines, (row, column))
                original = "\n".join(lines)
                lines = tuple(
                    (
                        original[:offset]
                        + "\n"
                        + "\n".join(contents)
                        + "\n"
                        + original[offset:]
                    ).split("\n")
                )
                row, column = row + 1, _first_nonblank(contents[0])
        if command == "p":
            # Visual p replaces the unnamed register; P preserves it.
            self._selected_register = '"'
            self._write_register(removed, removed_kind)
        self._set_lines(lines, row, column)
        self._save_change(before)
        return EditOutcome(
            True, command=command, changed=before.lines != self._state.lines
        )

    @staticmethod
    def _put_block(
        lines: tuple[str, ...],
        contents: tuple[str, ...],
        row: int,
        column: int,
        count: int = 1,
    ) -> tuple[str, ...]:
        result = list(lines)
        for index, piece in enumerate(contents, row):
            if index >= len(result):
                result.append("")
            line = result[index]
            result[index] = line.ljust(column)[:column] + piece * count + line[column:]
        return tuple(result)
