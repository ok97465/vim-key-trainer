"""동일한 엔진으로 사람이 읽을 수 있는 이동과 단계별 기대 상태를 만든다."""

# Standard library imports
import re
from collections.abc import Iterator
from dataclasses import replace
from functools import lru_cache

# Local imports
from vim_key_trainer.domain.edit_templates import ENTER, characters, counted
from vim_key_trainer.domain.editing import GuideStep
from vim_key_trainer.domain.keys import KeyToken
from vim_key_trainer.engine import EditEngine, EditorState

# 줄의 상대 거리는 줄 번호로 읽지만 문자 수는 눈으로 세기 어렵다.
_MAX_CHARACTER_CORRECTION = 2
_MAX_WORD_COUNT = 9
_MAX_FIND_COUNT = 3


def _navigation_parts(keys: tuple[KeyToken, ...]) -> Iterator[tuple[str, int, str]]:
    """이동의 count·명령·대상을 구분해 찾을 문자나 검색어를 다시 해석하지 않는다."""
    index = 0
    while index < len(keys):
        if keys[index].kind != "char":
            index += 1
            continue
        digits = ""
        while (
            index < len(keys)
            and keys[index].kind == "char"
            and keys[index].value.isdigit()
            and (digits or keys[index].value != "0")
        ):
            digits += keys[index].value
            index += 1
        if index >= len(keys):
            break
        command = keys[index].value
        count = int(digits or "1")
        index += 1
        target = ""
        if command in {"/", "?"}:
            while index < len(keys) and keys[index] != ENTER:
                target += keys[index].value
                index += 1
        elif command in {"f", "F", "t", "T"} and index < len(keys):
            target = keys[index].value
            index += 1
        yield command, count, target


def navigation_cost(keys: tuple[KeyToken, ...]) -> int:
    """입력 수에 눈으로 세어야 하는 부담을 더한 이동 선택용 휴리스틱.

    상대 줄 번호는 화면에서 읽을 수 있다. word/WORD 개수와 문자 찾기 순번은
    직접 세어야 하므로 큰 count를 더 비싸게 본다. 채점의 입력 수 B와는 다르다.
    """
    cost = len(keys)
    for command, count, target in _navigation_parts(keys):
        if command in {"/", "?"}:
            cost += 2 + 2 * target.count("\\")
            if target and target[0].isdigit():
                cost += 3
        elif command in {"w", "W", "b", "B", "e", "E"}:
            cost += (count - 1) ** 2
        elif command in {"h", "l"}:
            cost += 4 * max(0, count - _MAX_CHARACTER_CORRECTION)
        elif command in {"f", "F", "t", "T"}:
            cost += 3 * (count - 1) + int(target.isalnum())
    return cost


def _rank(keys: tuple[KeyToken, ...]) -> tuple[int, int, tuple[str, ...]]:
    return navigation_cost(keys), len(keys), tuple(key.display for key in keys)


def _run_navigation(
    state: EditorState,
    keys: tuple[KeyToken, ...],
    allowed: frozenset[str],
    last_find: tuple[str, str] | None = None,
) -> EditorState | None:
    engine = EditEngine(state, allowed)
    if last_find is not None:
        # 새 probe의 비어 있는 이력에 찾기 문맥만 주입한다.
        engine.restore(replace(engine.snapshot(), last_find=last_find))
    for token in keys:
        if not engine.submit(token).accepted:
            return None
    return engine.state


def _position(state: EditorState) -> tuple[int, int]:
    return state.row, state.column


def _find_keys(
    command: str, target: str, count: int, allowed: frozenset[str]
) -> tuple[tuple[KeyToken, ...], ...]:
    choices = [characters(counted(count, command) + target)]
    if count > 1 and ";" in allowed:
        choices.append(characters(command + target + ";" * (count - 1)))
    return tuple(choices)


@lru_cache(maxsize=256)
def _column_moves(
    line: str,
    start: int,
    column: int,
    allowed: frozenset[str],
    last_find: tuple[str, str] | None = None,
) -> tuple[tuple[KeyToken, ...], ...]:
    """줄 경계·보이는 구분자·찾기 재사용에 작은 word/문자 보정을 붙인다."""
    # 후보는 한 행 안에서 계산하고 선택된 입력만 전체 문서에서 재생한다.
    state = EditorState((line,), column=start)
    anchors: dict[int, tuple[tuple[KeyToken, ...], EditorState]] = {}

    def consider_anchor(keys: tuple[KeyToken, ...]) -> None:
        moved = _run_navigation(state, keys, allowed, last_find)
        if moved is None:
            return
        previous = anchors.get(moved.column)
        if previous is None or _rank(keys) < _rank(previous[0]):
            anchors[moved.column] = keys, moved

    for text in ("", "0", "^", "$") + (("%",) if "%" in allowed else ()):
        consider_anchor(characters(text))

    if last_find is not None:
        for repeat in (";", ","):
            if repeat not in allowed:
                continue
            for count in range(1, _MAX_FIND_COUNT + 1):
                consider_anchor(characters(repeat * count))

    # 6W보다 f; 뒤 ;나 w로 눈에 보이는 필드 경계를 따라갈 수 있게 한다.
    # 가까운 구분자 네 곳만 조사해 긴 원문에서도 후보 수를 제한한다.
    landmarks = sorted(
        (
            index
            for index, char in enumerate(line)
            if not char.isalnum() and char not in " _"
        ),
        key=lambda index: (abs(index - column), index),
    )[:4]
    boundary_anchors = tuple(anchors.values())
    for prefix, anchored in boundary_anchors:
        for target in landmarks:
            for command in ("f", "F", "t", "T"):
                if command not in allowed:
                    continue
                if command in {"f", "t"} and target > anchored.column:
                    count = line[anchored.column + 1 : target + 1].count(line[target])
                elif command in {"F", "T"} and target < anchored.column:
                    count = line[target : anchored.column].count(line[target])
                else:
                    continue
                if not 1 <= count <= _MAX_FIND_COUNT:
                    continue
                for suffix in _find_keys(command, line[target], count, allowed):
                    keys = prefix + suffix
                    choices: tuple[tuple[KeyToken, ...], ...] = (keys,)
                    if "%" in allowed and line[target] in "()[]{}":
                        choices += (keys + characters("%"),)
                    for movement in choices:
                        consider_anchor(movement)
    starts = list(anchors.values())
    for prefix, anchored in anchors.values():
        for motion in ("w", "W", "b", "B", "e", "E"):
            if motion not in allowed:
                continue
            forward = motion in {"w", "W", "e", "E"}
            if (forward and anchored.column > column + 2) or (
                not forward and anchored.column < column - 2
            ):
                continue
            probe = EditEngine(anchored, allowed)
            for count in range(1, _MAX_WORD_COUNT + 1):
                previous_position = _position(probe.state)
                if not probe.submit(KeyToken("char", motion)).accepted:
                    break
                moved = probe.state
                if moved.row != state.row or _position(moved) == previous_position:
                    break
                starts.append((prefix + characters(counted(count, motion)), moved))
                if (forward and moved.column >= column) or (
                    not forward and moved.column <= column
                ):
                    break
    options: set[tuple[KeyToken, ...]] = set()
    for prefix, moved in starts:
        distance = column - moved.column
        if abs(distance) <= _MAX_CHARACTER_CORRECTION:
            motion = counted(abs(distance), "l" if distance > 0 else "h")
            if not distance:
                options.add(prefix)
            elif motion[-1] in allowed:
                options.add(prefix + characters(motion))
        for command, target in (
            ("f", column),
            ("F", column),
            ("t", column + 1),
            ("T", column - 1),
        ):
            if command not in allowed or not 0 <= target < len(line):
                continue
            forward = command in {"f", "t"}
            if forward and target > moved.column:
                count = line[moved.column + 1 : target + 1].count(line[target])
            elif not forward and target < moved.column:
                count = line[target : moved.column].count(line[target])
            else:
                continue
            if count <= _MAX_FIND_COUNT:
                options.update(
                    prefix + suffix
                    for suffix in _find_keys(command, line[target], count, allowed)
                )
    return tuple(sorted(options, key=_rank))


def literal_search_pattern(text: str) -> str:
    """Vim magic 검색과 / 구분자 치환에 쓸 문자열을 이스케이프한다."""
    return "".join("\\" + char if char in r"\/.*[~^$" else char for char in text)


def _search_moves(
    line: str, column: int, allowed: frozenset[str]
) -> tuple[tuple[KeyToken, ...], ...]:
    if not allowed.intersection({"/", "?"}):
        return ()
    start = column
    if column < len(line) and (line[column].isalnum() or line[column] == "_"):
        while start and (line[start - 1].isalnum() or line[start - 1] == "_"):
            start -= 1
    suffix = line[start:]
    if not suffix:
        return ()
    corrections = (
        _column_moves(line, start, column, allowed)[:3] if start != column else ((),)
    )
    patterns: set[str] = set()
    # 고정 길이로 자른 손상 조각 대신 단어·구분자 경계까지 읽을 수 있게 찾는다.
    # 글자 수를 알아야 만드는 .\{N} 같은 패턴은 가이드에 사용하지 않는다.
    for match in re.finditer(r"[A-Za-z0-9_]+|[^A-Za-z0-9_\s]+", suffix):
        end = match.end()
        if end > 32:
            break
        if end >= 3:
            patterns.add(literal_search_pattern(suffix[:end]))
    if len(suffix) <= 32:
        patterns.add(literal_search_pattern(suffix) + "$")
    return tuple(
        sorted(
            (
                characters(command + pattern) + (ENTER,) + correction
                for command in ("/", "?")
                if command in allowed
                for pattern in patterns
                if len(pattern) <= 256 and (command != "?" or "?" not in pattern)
                for correction in corrections
            ),
            key=_rank,
        )
    )


def navigation_keys(
    state: EditorState,
    row: int,
    column: int | None,
    allowed: frozenset[str],
    *,
    last_find: tuple[str, str] | None = None,
) -> tuple[KeyToken, ...]:
    """이동 후보를 실제 허용 명령으로 재생해 정확한 도착 위치를 확인한다."""
    if state.row == row and (column is None or state.column == column):
        return ()
    relative = row - state.row
    row_moves = [f"{row + 1}G"]
    if row == 0:
        row_moves.append("gg")
    if row == len(state.lines) - 1:
        row_moves.append("G")
    row_moves.append(
        counted(abs(relative), "j" if relative > 0 else "k") if relative else ""
    )
    candidates: set[tuple[KeyToken, ...]] = set()
    destinations: dict[tuple[int, int], tuple[tuple[KeyToken, ...], EditorState]] = {}
    for text in row_moves:
        keys = characters(text)
        moved = _run_navigation(state, keys, allowed, last_find)
        if moved is None or moved.row != row:
            continue
        if column is None:
            candidates.add(keys)
        else:
            position = _position(moved)
            previous = destinations.get(position)
            if previous is None or len(keys) < len(previous[0]):
                destinations[position] = keys, moved
    if column is not None:
        if "%" in allowed:
            candidates.add(characters("%"))
        # 검색 후보는 출발 커서와 무관하다. 행 이동 접두사마다 다시 만들지 않는다.
        searches = _search_moves(state.lines[row], column, allowed)
        candidates.update(searches)
        for row_move, moved in destinations.values():
            candidates.update(
                row_move + move
                for move in _column_moves(
                    moved.lines[moved.row], moved.column, column, allowed, last_find
                )
            )
            candidates.update(row_move + move for move in searches)
            if "%" in allowed:
                candidates.add(row_move + characters("%"))
    for keys in sorted(candidates, key=_rank):
        moved = _run_navigation(state, keys, allowed, last_find)
        if (
            moved is not None
            and moved.row == row
            and (column is None or moved.column == column)
        ):
            return keys
    raise ValueError("허용 명령으로 읽기 쉬운 가이드 이동을 만들 수 없습니다.")


class GuideBuilder:
    """가이드 단계를 재생하고 그 종료 상태를 기록한다."""

    def __init__(self, initial: EditorState, allowed_commands: frozenset[str]) -> None:
        self.engine = EditEngine(initial, allowed_commands)
        self.steps: list[GuideStep] = []

    def record(self, keys: tuple[KeyToken, ...], text: str) -> None:
        for key in keys:
            outcome = self.engine.submit(key)
            if not outcome.accepted:
                raise ValueError(
                    f"편집 레시피의 키가 거부되었습니다: {outcome.message}"
                )
        self.steps.append(GuideStep(keys, self.engine.state, text))

    def navigate(self, row: int, column: int | None) -> None:
        movement = navigation_keys(
            self.engine.state,
            row,
            column,
            self.engine.allowed_commands,
            last_find=self.engine.last_find,
        )
        if movement:
            location = f"{row + 1}행"
            if column is not None:
                line = self.engine.state.lines[row]
                word = next(
                    (
                        match
                        for match in re.finditer(r"[A-Za-z0-9_]+", line)
                        if match.start() <= column < match.end()
                    ),
                    None,
                )
                if word is not None:
                    part = (
                        "시작"
                        if column == word.start()
                        else "끝"
                        if column == word.end() - 1
                        else f"안의 {line[column]!r}"
                    )
                    location += f"의 {word.group()!r} {part}"
                else:
                    character = line[column : column + 1]
                    target = (
                        KeyToken("char", character).display if character else "빈 줄"
                    )
                    location += f"의 {target!r}"
            reminder = ""
            finding = self.engine.last_find
            for command, _, target in _navigation_parts(movement):
                if command in {"f", "F", "t", "T"}:
                    finding = (command, target)
                elif command in {";", ","} and finding is not None:
                    character = KeyToken("char", finding[1]).display
                    direction = "같은" if command == ";" else "반대"
                    reminder = (
                        f"{finding[0]}{character} 찾기를 {command}로 "
                        f"{direction} 방향으로 반복해 "
                    )
                    break
            self.record(movement, f"{reminder}{location} 위치로 이동합니다.")
