"""문서 차이·구문 강조·대응 행과 독립 스크롤을 검증한다."""

from __future__ import annotations

# Standard library imports
from dataclasses import replace
from difflib import SequenceMatcher

# Third party imports
import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QFontMetricsF
from pytestqt.qtbot import QtBot

# Local imports
from vim_key_trainer.domain.document_display import TextSpan
from vim_key_trainer.domain.edit_templates import characters
from vim_key_trainer.engine import EditEngine, EditorState
from vim_key_trainer.ui.qt_input import NormalizedKey
from vim_key_trainer.ui.widgets.edit_comparison import EditComparison
from vim_key_trainer.ui.widgets.edit_document import EditDocument


def test_long_documents_have_bounded_viewports_and_follow_cursor(qtbot: QtBot) -> None:
    comparison = EditComparison()
    qtbot.addWidget(comparison)
    comparison.resize(800, 300)
    lines = tuple(f"record_{index:02} = {index}" for index in range(40))
    goal = EditorState(lines[:-1] + ("record_39 = done",))
    comparison.show_documents(EditorState(lines), goal)
    comparison.show()
    qtbot.waitExposed(comparison)
    assert comparison.height() == 300

    assert comparison.practice_input.height() > comparison.current_scroll.height()
    comparison.show_current(EditorState(lines, row=39))
    qtbot.waitUntil(lambda: comparison.current_scroll.verticalScrollBar().value() > 0)
    assert comparison.goal_scroll.verticalScrollBar().value() > 0
    position = comparison.current_scroll.verticalScrollBar().value()
    assert (
        position
        <= comparison.practice_input.cursor_rect.y()
        < (position + comparison.current_scroll.viewport().height())
    )
    assert comparison.goal_document.editor_state is goal
    assert comparison.height() == 300


def test_scroll_row_round_trip_preserves_fractional_font_metrics(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    class FractionalMetrics(QFontMetricsF):
        def lineSpacing(self) -> float:
            return 21.3

    monkeypatch.setattr(
        EditDocument,
        "document_metrics",
        property(lambda document: FractionalMetrics(document.font())),
    )
    comparison = EditComparison()
    qtbot.addWidget(comparison)
    comparison.resize(800, 300)
    lines = tuple(f"line {i}" for i in range(100))
    comparison.show_documents(EditorState(lines), EditorState(lines))
    comparison.show()
    qtbot.waitExposed(comparison)
    for top in (1, 3, 10, 31):
        comparison.current_scroll.verticalScrollBar().setValue(round(top * 21.3))
        assert comparison.viewport_top == top


def test_font_and_viewport_shrink_keep_cursor_visible_without_editing(
    qtbot: QtBot,
) -> None:
    comparison = EditComparison()
    qtbot.addWidget(comparison)
    comparison.resize(800, 300)
    state = EditorState(tuple(f"line {i}" for i in range(100)), row=20, viewport_top=13)
    comparison.show_documents(state, state)
    comparison.show()
    qtbot.waitExposed(comparison)
    comparison.show_current(state, follow_viewport=True)

    def cursor_visible() -> bool:
        top = comparison.current_scroll.verticalScrollBar().value()
        cursor = comparison.practice_input.cursor_rect
        return (
            top <= cursor.top()
            and cursor.bottom() <= top + comparison.current_scroll.viewport().height()
        )

    assert cursor_visible()
    comparison.set_font_size(28)
    comparison.show_current(state, follow_viewport=True)
    qtbot.waitUntil(cursor_visible)
    comparison.resize(800, 180)
    qtbot.waitUntil(cursor_visible)
    assert comparison.practice_input.editor_state is state
    assert comparison.goal_document.editor_state is state


def test_comparison_keeps_goal_fixed_after_line_deletion(qtbot: QtBot) -> None:
    comparison = EditComparison()
    qtbot.addWidget(comparison)
    comparison.resize(760, 250)
    original = tuple(f"line {index}" for index in range(40))
    goal = EditorState(original[:10] + original[15:])
    comparison.show_documents(EditorState(original), goal)
    comparison.show()
    qtbot.waitExposed(comparison)
    comparison.show_current(EditorState(goal.lines, row=34))
    qtbot.waitUntil(lambda: comparison.goal_scroll.verticalScrollBar().value() > 0)
    assert comparison.goal_document.editor_state is goal
    comparison.set_paused(True)
    assert comparison.practice_input.paused
    comparison.set_paused(False)
    assert comparison.practice_input.editor_state.lines == goal.lines
    assert comparison.goal_document.editor_state is goal


def test_scrolling_and_font_changes_only_affect_view(qtbot: QtBot) -> None:
    comparison = EditComparison()
    qtbot.addWidget(comparison)
    comparison.resize(760, 250)
    initial = EditorState(tuple(f"record {index}" for index in range(40)))
    comparison.show_documents(initial, initial)
    comparison.show()
    qtbot.waitExposed(comparison)
    events: list[NormalizedKey] = []
    comparison.practice_input.key_received.connect(events.append)
    comparison.current_scroll.verticalScrollBar().setValue(300)
    comparison.set_font_size(18)
    assert comparison.practice_input.editor_state is initial
    assert comparison.goal_document.editor_state is initial
    assert not events
    comparison.activateWindow()
    comparison.practice_input.setFocus()
    qtbot.waitUntil(comparison.practice_input.hasFocus)
    qtbot.keyClick(comparison.practice_input, Qt.Key.Key_Tab)
    assert len(events) == 1
    assert comparison.practice_input.hasFocus()
    assert events[0].token is not None and events[0].token.value == "tab"


def test_manual_scroll_keeps_other_document_position(qtbot: QtBot) -> None:
    comparison = EditComparison()
    qtbot.addWidget(comparison)
    comparison.resize(760, 250)
    lines = tuple(f"line {index} " + "long text " * 20 for index in range(100))
    state = EditorState(lines)
    comparison.show_documents(state, state)
    comparison.show()
    qtbot.waitExposed(comparison)
    current_bars = (
        comparison.current_scroll.verticalScrollBar(),
        comparison.current_scroll.horizontalScrollBar(),
    )
    goal_bars = (
        comparison.goal_scroll.verticalScrollBar(),
        comparison.goal_scroll.horizontalScrollBar(),
    )
    for bar in goal_bars:
        bar.setValue(bar.maximum() // 2)
    goal_position = tuple(bar.value() for bar in goal_bars)
    for bar in current_bars:
        assert bar.maximum() > 0
        bar.setValue(bar.maximum())
    assert tuple(bar.value() for bar in goal_bars) == goal_position
    current_position = tuple(bar.value() for bar in current_bars)
    for bar in goal_bars:
        bar.setValue(0)
    assert tuple(bar.value() for bar in current_bars) == current_position
    assert comparison.practice_input.editor_state is state
    assert comparison.goal_document.editor_state is state


def test_stationary_cursor_updates_preserve_manual_goal_scroll(qtbot: QtBot) -> None:
    comparison = EditComparison()
    qtbot.addWidget(comparison)
    comparison.resize(760, 250)
    lines = tuple(f"line {index} " + "long text " * 20 for index in range(100))
    state = EditorState(lines)
    comparison.show_documents(state, state)
    comparison.show()
    qtbot.waitExposed(comparison)
    bars = (
        comparison.goal_scroll.verticalScrollBar(),
        comparison.goal_scroll.horizontalScrollBar(),
    )
    for bar in bars:
        bar.setValue(bar.maximum())
    position = tuple(bar.value() for bar in bars)

    comparison.show_current(state)
    comparison.show_current(EditorState(lines, pending="d"))
    assert tuple(bar.value() for bar in bars) == position

    comparison.show_current(EditorState(lines, row=1))
    assert bars[0].value() < position[0]
    assert bars[1].value() < position[1]


def test_manual_scroll_past_file_end_tracks_viewport_and_replacement_document(
    qtbot: QtBot,
) -> None:
    comparison = EditComparison()
    qtbot.addWidget(comparison)
    comparison.resize(760, 900)
    lines = tuple(f"line {index}" for index in range(100))
    state = EditorState(lines, row=99)
    comparison.show_documents(state, state)
    comparison.show()
    qtbot.waitExposed(comparison)
    document = comparison.practice_input
    viewport = comparison.current_scroll.viewport()
    scroll_bar = comparison.current_scroll.verticalScrollBar()

    def final_line_is_at_top() -> bool:
        origin = document.mapTo(viewport, QPoint())
        return abs(document.cursor_rect.translated(origin).top() - 16) <= 1

    assert not comparison.guide_overlay.isVisible()
    scroll_bar.setValue(scroll_bar.maximum())
    qtbot.waitUntil(final_line_is_at_top)
    original_height = viewport.height()
    comparison.resize(760, 420)
    qtbot.waitUntil(lambda: viewport.height() < original_height)
    scroll_bar.setValue(scroll_bar.maximum())
    qtbot.waitUntil(final_line_is_at_top)
    assert document.editor_state is state
    assert comparison.goal_document.editor_state is state

    current, goal = EditorState(("new",)), EditorState(("goal",))
    comparison.show_documents(current, goal)
    qtbot.waitUntil(lambda: scroll_bar.maximum() == 0)
    assert scroll_bar.value() == 0
    assert document.editor_state is current
    assert comparison.goal_document.editor_state is goal


def test_target_highlights_update_as_repair_is_completed_without_mutating_goal(
    qtbot: QtBot,
) -> None:
    comparison = EditComparison()
    qtbot.addWidget(comparison)
    target = EditorState(("a=11", "keep", "b=21", "keep again", "c=31"))
    current = EditorState(("a=10", "keep", "b=20", "keep again", "c=30"))
    changed: list[int] = []
    comparison.changes_changed.connect(changed.append)
    comparison.show_documents(current, target)
    assert comparison.remaining_changes == 3
    assert len(comparison.goal_document.change_spans) == 3
    comparison.show_current(EditorState(target.lines[:1] + current.lines[1:]))
    assert comparison.remaining_changes == 2
    assert all(span.row != 0 for span in comparison.goal_document.change_spans)
    comparison.show_current(target)
    assert comparison.remaining_changes == 0
    assert not comparison.goal_document.change_spans
    assert comparison.goal_document.editor_state is target
    assert changed == [3, 2, 0]


def test_python_foreground_and_target_diff_background_survive_font_changes(
    qtbot: QtBot,
) -> None:
    comparison = EditComparison()
    qtbot.addWidget(comparison)
    comparison.set_language("python")
    target = EditorState(("return 34",))
    comparison.show_documents(EditorState(("return 12",)), target)
    document = comparison.goal_document
    assert TextSpan(0, 7, 9, "replace") in document.change_spans
    assert TextSpan(0, 7, 9, "number") in document.syntax_spans
    comparison.set_font_size(18)
    assert TextSpan(0, 7, 9, "replace") in document.change_spans
    assert TextSpan(0, 7, 9, "number") in document.syntax_spans
    assert document.editor_state is target


def test_deleted_and_empty_lines_have_goal_anchors(qtbot: QtBot) -> None:
    comparison = EditComparison()
    qtbot.addWidget(comparison)
    comparison.show_documents(
        EditorState(("keep", "remove", "")), EditorState(("keep",))
    )
    assert comparison.remaining_changes == 2
    assert all(span.start == span.end for span in comparison.goal_document.change_spans)
    assert all(span.row == 0 for span in comparison.goal_document.change_spans)


def test_repeated_documents_share_one_bounded_alignment_for_scroll_and_highlights(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    aligned: list[tuple[object, object]] = []
    original = SequenceMatcher.get_opcodes

    def trace_alignment(
        matcher: SequenceMatcher[str],
    ) -> list[tuple[str, int, int, int, int]]:
        if not isinstance(matcher.a, str):
            aligned.append((matcher.a, matcher.b))
        return original(matcher)

    monkeypatch.setattr(SequenceMatcher, "get_opcodes", trace_alignment)
    comparison = EditComparison()
    qtbot.addWidget(comparison)
    comparison.resize(800, 300)
    edges = ("repeated GUI context",) * 600
    current = edges + ("old",) + edges
    goal = EditorState(edges + ("new", "added") + edges)
    comparison.show_documents(EditorState(current), goal)
    comparison.show()
    qtbot.waitExposed(comparison)
    comparison.show_current(EditorState(current, row=900))

    assert aligned == [(("old",), ("new", "added"))]
    assert comparison.diff.goal_rows[900] == 901
    spacing = comparison.goal_document.document_metrics.lineSpacing()
    center = 16 + (901 + 0.5) * spacing
    top = comparison.goal_scroll.verticalScrollBar().value()
    assert top <= center <= top + comparison.goal_scroll.viewport().height()
    assert comparison.goal_document.editor_state is goal


def test_target_repair_has_painted_background_under_syntax_text(qtbot: QtBot) -> None:
    comparison = EditComparison()
    qtbot.addWidget(comparison)
    comparison.resize(850, 300)
    comparison.set_language("python")
    comparison.show_documents(EditorState(("return 12",)), EditorState(("return 34",)))
    comparison.show()
    qtbot.waitExposed(comparison)
    document = comparison.goal_document
    metrics = document.document_metrics
    image = document.grab().toImage()
    scale = image.devicePixelRatio()
    y = round((16 + metrics.lineSpacing() - 4) * scale)
    changed_x = round(
        (58 + metrics.horizontalAdvance("return ") + metrics.horizontalAdvance("3") / 2)
        * scale
    )
    unchanged_x = round((58 + metrics.horizontalAdvance("ret")) * scale)
    assert image.pixelColor(changed_x, y) != image.pixelColor(unchanged_x, y)
    assert document.syntax_spans and document.change_spans
    assert document.editor_state.lines == ("return 34",)


def test_empty_target_anchor_is_painted_for_line_deletion(qtbot: QtBot) -> None:
    comparison = EditComparison()
    qtbot.addWidget(comparison)
    comparison.resize(850, 300)
    comparison.show_documents(EditorState(("remove",)), EditorState(("",)))
    comparison.show()
    qtbot.waitExposed(comparison)
    document = comparison.goal_document
    image = document.grab().toImage()
    scale = image.devicePixelRatio()
    assert image.pixelColor(round(58 * scale), round(25 * scale)) != image.pixelColor(
        round(100 * scale), round(25 * scale)
    )
    assert document.change_spans[0].start == document.change_spans[0].end == 0


def test_json_syntax_colors_remain_while_repairs_update(qtbot: QtBot) -> None:
    comparison = EditComparison()
    qtbot.addWidget(comparison)
    comparison.resize(850, 300)
    comparison.set_language("json")
    comparison.set_font_size(18)
    goal = EditorState(('{"name": "ready", "enabled": true}',))
    comparison.show_documents(
        EditorState(('{"name": "pending", "enabled": false}',)), goal
    )
    comparison.show()
    qtbot.waitExposed(comparison)
    document = comparison.goal_document
    image = document.grab().toImage()
    scale = image.devicePixelRatio()
    metrics = document.document_metrics
    colors = {
        image.pixelColor(x, y).name()
        for y in range(round(16 * scale), round((16 + metrics.lineSpacing()) * scale))
        for x in range(round(58 * scale), min(image.width(), round(800 * scale)))
    }
    assert {"#86c9e8", "#b9de91", "#cda9ef"} <= colors
    assert document.change_spans
    comparison.show_current(goal)
    assert comparison.practice_input.syntax_spans
    assert not document.change_spans
    assert not comparison.practice_input.change_spans


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
