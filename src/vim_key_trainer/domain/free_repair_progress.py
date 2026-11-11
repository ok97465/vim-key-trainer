"""자유 풀이의 부분 복구를 읽기만 하는 표시 모델. 완료·채점에 쓰지 않는다."""

# Standard library imports
import re
from collections import Counter
from dataclasses import dataclass

# Local imports
from vim_key_trainer.domain.document_display import (
    ChangeRegion,
    DocumentDiff,
    TextSpan,
    compare_documents,
)
from vim_key_trainer.engine import EditorState


@dataclass(frozen=True, slots=True)
class FreeRepairEvent:
    id: str
    row: int
    column: int
    old_text: str
    technique: str
    first_solved_total: int
    source_column: int | None = None


@dataclass(frozen=True, slots=True)
class FreeRepairSnapshot:
    total: int
    solved: int
    first_solved: int
    events: tuple[FreeRepairEvent, ...]
    marks: tuple[tuple[int, str], ...]
    remaining_changes: int


@dataclass(frozen=True, slots=True)
class _RepairTarget:
    region: ChangeRegion
    context: tuple[int, int] | None
    old_text: str
    technique: str


def _touches(first: TextSpan, second: TextSpan) -> bool:
    if first.row != second.row:
        return False
    if first.start == first.end and second.start == second.end:
        return first.start == second.start
    if first.start == first.end:
        return second.start < first.start < second.end
    if second.start == second.end:
        return first.start < second.start < first.end
    return max(first.start, second.start) < min(first.end, second.end)


def _technique(
    region: ChangeRegion, initial: tuple[str, ...], goal: tuple[str, ...]
) -> str:
    if region.kind == "delete":
        return "delete"
    if region.kind == "insert":
        return "insert"
    before = "".join(
        initial[span.row][span.start : span.end] for span in region.current_spans
    )
    after = "".join(goal[span.row][span.start : span.end] for span in region.goal_spans)
    if all(
        value
        and re.fullmatch(r"[-+0-9a-fA-FxXbBoO.]+", value)
        and any(char.isdigit() for char in value)
        for value in (before, after)
    ):
        return "number"
    return "word" if max(len(before), len(after)) > 1 else "precise"


def _boundary_matches(goal: str, point: int, current: str, column: int) -> bool:
    """삭제 경계 양쪽의 WORD를 확인해 남겨야 할 단어의 일부 삭제도 거부한다."""
    if not goal:
        return not current
    start = point
    while start and goal[start - 1].isspace():
        start -= 1
    while start and not goal[start - 1].isspace():
        start -= 1
    end = point
    while end < len(goal) and goal[end].isspace():
        end += 1
    while end < len(goal) and not goal[end].isspace():
        end += 1
    before, after = goal[start:point], goal[point:end]
    return (
        column >= len(before)
        and current[column - len(before) : column] == before
        and current[column : column + len(after)] == after
    )


class FreeRepairProgress:
    """초기 차이의 목표 좌표를 고정하고 현재 diff에서 일치 여부를 추적한다.

    정렬이 모호한 반복 행은 유일한 목표 문맥 전체가 일치할 때까지 보류한다.
    최초 해결 집합은 시도 동안만 보관한다. undo로 표식은 사라지지만 같은
    지점을 다시 맞추어도 효과를 반복하지 않는다.
    """

    def __init__(
        self, initial_lines: tuple[str, ...], goal_lines: tuple[str, ...]
    ) -> None:
        initial = compare_documents(initial_lines, goal_lines)
        self._goal = goal_lines
        counts = Counter(goal_lines)
        contexts: dict[int, tuple[int, int]] = {}
        targets: list[_RepairTarget] = []
        for region in initial.regions:
            row = region.goal_spans[0].row
            context = None
            if counts[goal_lines[row]] > 1:
                if row not in contexts:
                    contexts[row] = self._unique_context(row)
                context = contexts[row]
            targets.append(
                _RepairTarget(
                    region,
                    context,
                    initial_lines[region.current_spans[0].row],
                    _technique(region, initial_lines, goal_lines),
                )
            )
        self._targets = tuple(targets)
        self._settled: set[str] = set()
        self._first_solved = 0
        self._cached_lines: tuple[str, ...] | None = None
        self._cached_solved: tuple[tuple[int, int, int], ...] = ()

    def _unique_context(self, row: int) -> tuple[int, int]:
        width = 2
        count = len(self._goal)
        while True:
            width = min(count, width)
            starts = dict.fromkeys(
                min(count - width, max(0, start))
                for start in (row - width + 1, row, row - width // 2)
            )
            for start in starts:
                end = start + width
                context = self._goal[start:end]
                matches = 0
                for candidate in range(count - width + 1):
                    if self._goal[candidate : candidate + width] == context:
                        matches += 1
                        if matches > 1:
                            break
                if matches == 1:
                    return start, end
            width = width * 2 - 1

    def _location(
        self, target: _RepairTarget, lines: tuple[str, ...], diff: DocumentDiff
    ) -> tuple[int, int] | None:
        span = target.region.goal_spans[0]
        candidates = tuple(
            row for row, goal_row in enumerate(diff.goal_rows) if goal_row == span.row
        )
        for row in candidates:
            if any(
                region.kind == "delete"
                and current_span.row == row
                and current_span.start == 0
                and current_span.end == len(lines[row])
                and goal_span.start == goal_span.end
                and lines[row] != self._goal[span.row]
                for region in diff.regions
                for current_span, goal_span in zip(
                    region.current_spans, region.goal_spans, strict=True
                )
            ):
                continue
            if target.context is not None:
                start, end = target.context
                current_start = row - (span.row - start)
                if (
                    current_start < 0
                    or lines[current_start : current_start + end - start]
                    != self._goal[start:end]
                ):
                    continue
            column = span.start
            for region in diff.regions:
                for current_span, goal_span in zip(
                    region.current_spans, region.goal_spans, strict=True
                ):
                    if (
                        current_span.row == row
                        and goal_span.row == span.row
                        and goal_span.end <= span.start
                    ):
                        column += (current_span.end - current_span.start) - (
                            goal_span.end - goal_span.start
                        )
            column = min(len(lines[row]), max(0, column))
            expected = self._goal[span.row][span.start : span.end]
            if lines[row][column : column + len(expected)] != expected:
                continue
            if not expected:
                # 삭제 목표의 빈 범위만 비교하면 문서 전체를 지워도 일치한다.
                # 양쪽에 남아야 할 목표 단어를 실제 현재 경계에서 확인한다.
                if not _boundary_matches(
                    self._goal[span.row], span.start, lines[row], column
                ):
                    continue
            return row, column
        return None

    def _solutions(
        self, lines: tuple[str, ...], diff: DocumentDiff
    ) -> tuple[tuple[int, int, int], ...]:
        if lines == self._cached_lines:
            return self._cached_solved
        residual = diff.goal_spans
        solved: list[tuple[int, int, int]] = []
        for index, target in enumerate(self._targets):
            if any(
                _touches(goal_span, span)
                for goal_span in target.region.goal_spans
                for span in residual
            ):
                continue
            location = self._location(target, lines, diff)
            if location is not None:
                solved.append((index, *location))
        self._cached_lines = lines
        self._cached_solved = tuple(solved)
        return self._cached_solved

    def update(
        self,
        state: EditorState,
        *,
        diff: DocumentDiff | None = None,
        celebrate: bool = True,
    ) -> FreeRepairSnapshot:
        current = (
            diff if diff is not None else compare_documents(state.lines, self._goal)
        )
        solved = self._solutions(state.lines, current)
        stable = state.mode == "normal" and not state.pending and not state.command_line
        events: list[FreeRepairEvent] = []
        if stable:
            for index, row, column in solved:
                target = self._targets[index]
                if target.region.id in self._settled:
                    continue
                # 숨겨진 화면에서 지나간 성공도 소비해 이후 편집·redo에서
                # 뒤늦게 재생하지 않는다. 연출 누적 수에는 포함하지 않는다.
                self._settled.add(target.region.id)
                if not celebrate:
                    continue
                self._first_solved += 1
                events.append(
                    FreeRepairEvent(
                        target.region.id,
                        row,
                        column,
                        target.old_text,
                        target.technique,
                        self._first_solved,
                        source_column=target.region.current_spans[0].start,
                    )
                )
        return FreeRepairSnapshot(
            total=len(self._targets),
            solved=len(solved),
            first_solved=self._first_solved,
            events=tuple(events),
            marks=tuple(
                (row, f"자유 복구 · {index + 1}번 목표 일치")
                for index, row, _ in solved
            ),
            remaining_changes=current.remaining_count,
        )
