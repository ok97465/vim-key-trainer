"""대응 행을 같은 높이에 그리며 원거리 수정 예고와 독립 스크롤을 보존한다."""

# Standard library imports
from dataclasses import replace

# Third party imports
import pytest
from PySide6.QtCore import QPoint
from pytestqt.qtbot import QtBot

# Local imports
from vim_key_trainer.domain.edit_templates import characters
from vim_key_trainer.engine import EditEngine, EditorState
from vim_key_trainer.ui.qt_input import NormalizedKey
from vim_key_trainer.ui.widgets.edit_comparison import EditComparison


def _row_y(comparison: EditComparison, row: int, *, goal: bool = False) -> float:
    document = comparison.goal_document if goal else comparison.practice_input
    area = comparison.goal_scroll if goal else comparison.current_scroll
    origin = document.mapTo(area.viewport(), QPoint())
    return origin.y() + 16 + row * document.document_metrics.lineSpacing()


def _aligned(comparison: EditComparison, row: int, goal_row: int) -> bool:
    return abs(_row_y(comparison, row) - _row_y(comparison, goal_row, goal=True)) <= 1


def _show_guide(comparison: EditComparison) -> None:
    comparison.show_guide(
        characters("ciw"), 0, description="단어를 수정합니다.", progress="단계 1/3"
    )


def _open_comparison(
    qtbot: QtBot, current: EditorState, goal: EditorState
) -> EditComparison:
    comparison = EditComparison()
    qtbot.addWidget(comparison)
    comparison.resize(800, 360)
    comparison.show_documents(current, goal)
    comparison.show()
    qtbot.waitExposed(comparison)
    return comparison


def test_guide_font_resize_and_resume_keep_corresponding_rows_aligned(
    qtbot: QtBot,
) -> None:
    lines = tuple(f"record {index}" for index in range(100))
    goal = EditorState(lines)
    comparison = _open_comparison(qtbot, EditorState(lines), goal)
    state = EditorState(lines, row=60)
    engine = EditEngine(state)
    snapshot = engine.snapshot()
    received: list[NormalizedKey] = []
    comparison.practice_input.key_received.connect(received.append)
    comparison.show_current(state)
    qtbot.waitUntil(lambda: _aligned(comparison, 60, 60))

    def aligned_above_guide() -> bool:
        origin = comparison.practice_input.mapTo(
            comparison.current_scroll.viewport(), QPoint()
        )
        cursor = comparison.practice_input.cursor_rect.translated(origin)
        return (
            _aligned(comparison, 60, 60)
            and cursor.top() >= 0
            and cursor.bottom() <= comparison.guide_overlay.y() - 8
        )

    _show_guide(comparison)
    qtbot.waitUntil(aligned_above_guide)
    comparison.set_font_size(28)
    qtbot.waitUntil(aligned_above_guide)
    comparison.resize(800, 240)
    qtbot.waitUntil(aligned_above_guide)
    comparison.clear_guide()
    qtbot.waitUntil(lambda: _aligned(comparison, 60, 60))
    _show_guide(comparison)
    comparison.set_paused(True)
    comparison.set_paused(False)
    qtbot.waitUntil(aligned_above_guide)
    assert comparison.practice_input.editor_state is state
    assert comparison.goal_document.editor_state is goal
    assert engine.snapshot() == snapshot
    assert received == []


def test_last_row_can_align_at_top_of_both_documents(qtbot: QtBot) -> None:
    lines = tuple(f"record {index}" for index in range(100))
    state = EditorState(lines, row=99, viewport_top=99)
    goal = EditorState(lines)
    comparison = _open_comparison(qtbot, state, goal)
    _show_guide(comparison)
    comparison.show_current(state, follow_viewport=True)
    qtbot.waitUntil(lambda: _aligned(comparison, 99, 99))
    assert abs(_row_y(comparison, 99) - 16) <= 1
    assert abs(_row_y(comparison, 99, goal=True) - 16) <= 1
    comparison.set_font_size(24)
    comparison.show_current(state, follow_viewport=True)
    qtbot.waitUntil(lambda: _aligned(comparison, 99, 99))
    assert abs(_row_y(comparison, 99, goal=True) - 16) <= 1
    comparison.resize(800, 480)
    qtbot.waitUntil(lambda: _aligned(comparison, 99, 99))
    assert comparison.practice_input.editor_state is state
    assert comparison.goal_document.editor_state is goal


@pytest.mark.parametrize("extra_rows", [-3, 2])
def test_line_insertions_and_deletions_align_mapped_content(
    qtbot: QtBot, extra_rows: int
) -> None:
    goal_lines = tuple(f"unchanged record {index}" for index in range(100))
    current_lines = (
        goal_lines[:10] + ("extra one", "extra two") + goal_lines[10:]
        if extra_rows > 0
        else goal_lines[:10] + goal_lines[13:]
    )
    goal_row = 60
    row = goal_row + extra_rows
    state = EditorState(current_lines, row=row, viewport_top=row - 4)
    goal = EditorState(goal_lines)
    comparison = _open_comparison(qtbot, EditorState(current_lines), goal)
    _show_guide(comparison)
    comparison.show_current(state, follow_viewport=True)
    assert state.lines[row] == goal.lines[goal_row]
    assert comparison.diff.goal_rows[row] == goal_row
    qtbot.waitUntil(lambda: _aligned(comparison, row, goal_row))
    comparison.set_font_size(26)
    qtbot.waitUntil(lambda: _aligned(comparison, row, goal_row))
    assert comparison.practice_input.editor_state is state
    assert comparison.goal_document.editor_state is goal


def test_fixed_far_preview_aligns_on_arrival_and_subsequent_page_movement(
    qtbot: QtBot,
) -> None:
    lines = tuple(f"record {index}" for index in range(150))
    initial = EditorState(lines)
    goal = EditorState(lines)
    comparison = _open_comparison(qtbot, initial, goal)
    _show_guide(comparison)
    target = (80, 0)
    comparison.show_current(initial, goal_position=target)
    target_y = _row_y(comparison, target[0], goal=True)
    spacing = comparison.goal_document.document_metrics.lineSpacing()
    assert 0 <= target_y <= comparison.goal_scroll.viewport().height() - spacing
    assert comparison.current_scroll.verticalScrollBar().value() == 0
    assert comparison.practice_input.editor_state is initial

    arrived = EditorState(lines, row=80, viewport_top=76)
    comparison.show_current(arrived, follow_viewport=True, goal_position=target)
    qtbot.waitUntil(lambda: _aligned(comparison, 80, 80))
    first_y = _row_y(comparison, 80)
    shifted = replace(arrived, viewport_top=78)
    comparison.show_current(shifted, follow_viewport=True, goal_position=target)
    qtbot.waitUntil(lambda: _aligned(comparison, 80, 80))
    assert _row_y(comparison, 80) < first_y - spacing
    assert comparison.practice_input.editor_state is shifted
    assert comparison.goal_document.editor_state is goal


def test_manual_target_scroll_survives_pending_and_same_preview_page_movement(
    qtbot: QtBot,
) -> None:
    lines = tuple(f"record {index}" for index in range(150))
    state = EditorState(lines, row=80, viewport_top=78)
    comparison = _open_comparison(qtbot, EditorState(lines), EditorState(lines))
    _show_guide(comparison)
    comparison.show_current(state, follow_viewport=True, goal_position=(80, 0))
    qtbot.waitUntil(lambda: _aligned(comparison, 80, 80))
    target_bar = comparison.goal_scroll.verticalScrollBar()
    target_bar.setValue(0)
    current_position = comparison.current_scroll.verticalScrollBar().value()
    comparison.show_current(
        replace(state, pending="d"), follow_viewport=True, goal_position=(80, 0)
    )
    assert target_bar.value() == 0
    assert comparison.current_scroll.verticalScrollBar().value() == current_position
    shifted = replace(state, viewport_top=77)
    comparison.show_current(shifted, follow_viewport=True, goal_position=(80, 0))
    assert target_bar.value() == 0
    assert comparison.current_scroll.verticalScrollBar().value() != current_position
    assert comparison.practice_input.editor_state is shifted
    comparison.show_current(shifted, follow_viewport=True, goal_position=(81, 0))
    qtbot.waitUntil(lambda: _aligned(comparison, 80, 80))
