"""긴 문서도 입력·가이드를 밀어내지 않고 내부에서 이동한다."""

# Standard library imports
from difflib import SequenceMatcher

# Third party imports
import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QFontMetricsF
from pytestqt.qtbot import QtBot

# Local imports
from vim_key_trainer.domain.document_display import TextSpan
from vim_key_trainer.engine import EditorState
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


def test_new_document_discards_padding_for_previous_viewport(qtbot: QtBot) -> None:
    comparison = EditComparison()
    qtbot.addWidget(comparison)
    comparison.resize(760, 900)
    lines = tuple(f"line {index}" for index in range(100))
    state = EditorState(lines, row=99, viewport_top=99)
    comparison.show_documents(state, state)
    comparison.show()
    qtbot.waitExposed(comparison)
    comparison.show_current(state, follow_viewport=True)
    assert comparison.practice_input.bottom_padding > 0
    comparison.show_documents(EditorState(("new",)), EditorState(("goal",)))
    assert comparison.practice_input.bottom_padding == 0
    assert comparison.practice_input.minimumHeight() == 240


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
