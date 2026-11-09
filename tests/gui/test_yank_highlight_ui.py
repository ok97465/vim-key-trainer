"""복사 강조는 실제 입력 결과를 잠시 표시하며 편집·포커스를 바꾸지 않는다."""

# Standard library imports
import sys
from collections.abc import Iterator
from dataclasses import replace

# Third party imports
import pytest
from PySide6.QtCore import Qt
from pytestqt.qtbot import QtBot

# Local imports
from vim_key_trainer.content.edit_loader import get_edit_lesson
from vim_key_trainer.domain.document_display import TextSpan
from vim_key_trainer.domain.editing import EditLesson, GuideStep
from vim_key_trainer.domain.keys import KeyToken
from vim_key_trainer.domain.preferences import PresentationSettings
from vim_key_trainer.domain.sessions import SessionState
from vim_key_trainer.engine import SUPPORTED_COMMANDS, EditorState, YankSpan
from vim_key_trainer.services.result_repository import MemoryResultRepository
from vim_key_trainer.ui.edit_practice import EditPracticePage
from vim_key_trainer.ui.widgets.edit_document import EditDocument


def _lesson() -> EditLesson:
    initial = EditorState(("alpha beta", "gamma delta", ""))
    goal = ("Alpha beta", "gamma delta", "")
    yank = tuple(KeyToken("char", value) for value in "yy")
    change = tuple(KeyToken("char", value) for value in "rA")
    return replace(
        get_edit_lesson("editing_numbers"),
        initial=initial,
        goal_lines=goal,
        goal_cursor=None,
        allowed_commands=SUPPORTED_COMMANDS,
        guide=(
            GuideStep(yank, initial, "현재 줄 복사"),
            GuideStep(change, EditorState(goal), "첫 글자 교체"),
        ),
        baseline=yank + change,
        baseline_keys=4,
    )


@pytest.fixture
def page(qtbot: QtBot) -> Iterator[EditPracticePage]:
    widget = EditPracticePage(MemoryResultRepository())
    qtbot.addWidget(widget)
    widget.resize(1100, 850)
    widget.show()
    widget.activateWindow()
    qtbot.waitUntil(widget.isActiveWindow)
    widget.prepare(_lesson(), "free")
    widget.start_practice()
    qtbot.waitUntil(widget.practice_input.hasFocus)
    yield widget
    widget.abort()
    widget.close()


@pytest.mark.parametrize(
    ("keys", "expected"),
    [
        ("yw", (YankSpan(0, 0, 6),)),
        ("yy", (YankSpan(0, 0, 10),)),
        ("Y", (YankSpan(0, 0, 10),)),
        ("2yy", (YankSpan(0, 0, 10), YankSpan(1, 0, 11))),
        ("3yy", (YankSpan(0, 0, 10), YankSpan(1, 0, 11), YankSpan(2, 0, 0))),
        ("vlly", (YankSpan(0, 0, 3),)),
        ("Vjy", (YankSpan(0, 0, 10), YankSpan(1, 0, 11))),
    ],
)
def test_actual_yank_keys_highlight_only_copied_text(
    page: EditPracticePage,
    qtbot: QtBot,
    keys: str,
    expected: tuple[YankSpan, ...],
) -> None:
    session = page.session
    assert session is not None
    before = session.engine.state.lines
    qtbot.keyClicks(page.practice_input, keys)
    assert page.practice_input.yank_spans == expected
    assert session.engine.state.lines == before
    assert session.key_count == len(keys)
    assert session.pause_count == 0
    assert page.practice_input.hasFocus()
    assert not page.goal_document.yank_spans


def test_visual_block_yank_highlights_separate_rows(
    page: EditPracticePage, qtbot: QtBot
) -> None:
    modifier = (
        Qt.KeyboardModifier.MetaModifier
        if sys.platform == "darwin"
        else Qt.KeyboardModifier.ControlModifier
    )
    qtbot.keyClick(page.practice_input, Qt.Key.Key_V, modifier)
    qtbot.keyClicks(page.practice_input, "ljy")
    assert page.practice_input.yank_spans == (
        YankSpan(0, 0, 2),
        YankSpan(1, 0, 2),
    )
    assert page.session is not None
    assert page.session.key_count == 4
    assert page.practice_input.hasFocus()


def test_movement_and_refresh_do_not_replay_or_extend_yank(
    page: EditPracticePage, qtbot: QtBot
) -> None:
    qtbot.keyClicks(page.practice_input, "yy")
    expected = page.practice_input.yank_spans
    assert expected
    qtbot.wait(180)
    qtbot.keyClicks(page.practice_input, "j")
    page._refresh()
    assert page.practice_input.yank_spans == expected
    qtbot.wait(280)
    assert not page.practice_input.yank_spans
    page._refresh()
    assert not page.practice_input.yank_spans
    assert page.session is not None
    assert page.session.key_count == 3
    assert page.session.engine.state.row == 1
    assert page.practice_input.hasFocus()


def test_repeated_identical_yank_gets_its_own_display_time(
    page: EditPracticePage, qtbot: QtBot
) -> None:
    qtbot.keyClicks(page.practice_input, "yy")
    qtbot.wait(230)
    qtbot.keyClicks(page.practice_input, "yy")
    qtbot.wait(220)
    assert page.practice_input.yank_spans == (YankSpan(0, 0, 10),)
    qtbot.waitUntil(lambda: not page.practice_input.yank_spans, timeout=500)


@pytest.mark.parametrize("keys", ["x", "i", "v", "V"])
def test_editing_or_new_selection_clears_old_yank(
    page: EditPracticePage, qtbot: QtBot, keys: str
) -> None:
    qtbot.keyClicks(page.practice_input, "yy")
    assert page.practice_input.yank_spans
    qtbot.keyClicks(page.practice_input, keys)
    assert not page.practice_input.yank_spans


@pytest.mark.parametrize("action", ["pause", "retry", "hide", "abort"])
def test_leaving_current_editing_state_clears_yank(
    page: EditPracticePage, qtbot: QtBot, action: str
) -> None:
    qtbot.keyClicks(page.practice_input, "yy")
    assert page.practice_input.yank_spans
    getattr(page, action)()
    assert not page.practice_input.yank_spans


def test_guided_step_return_clears_yank_without_reapplying_it(
    page: EditPracticePage, qtbot: QtBot
) -> None:
    page.prepare(_lesson())
    page.start_practice()
    qtbot.waitUntil(page.practice_input.hasFocus)
    qtbot.keyClicks(page.practice_input, "yy")
    assert page.practice_input.yank_spans
    assert page.session is not None and page.session.step_index == 1
    page.return_to_step()
    assert not page.practice_input.yank_spans
    assert page.session.step_index == 0
    assert page.session.key_count == 2
    assert page.practice_input.hasFocus()
    page._refresh()
    assert not page.practice_input.yank_spans


def test_disabling_effects_clears_yank_and_reduced_motion_remains_static(
    page: EditPracticePage, qtbot: QtBot
) -> None:
    qtbot.keyClicks(page.practice_input, "yy")
    assert page.practice_input.yank_spans
    page.configure_effects(PresentationSettings(effects=False))
    assert not page.practice_input.yank_spans
    qtbot.keyClicks(page.practice_input, "yy")
    assert not page.practice_input.yank_spans
    page.configure_effects(PresentationSettings(reduced_motion=True))
    page._refresh()
    assert not page.practice_input.yank_spans
    qtbot.keyClicks(page.practice_input, "yy")
    assert page.practice_input.yank_spans == (YankSpan(0, 0, 10),)
    assert page.session is not None
    assert page.session.key_count == 6
    assert page.session.state == SessionState.RUNNING
    assert page.practice_input.hasFocus()


def test_yank_paint_preserves_syntax_diff_markers_and_cursor(qtbot: QtBot) -> None:
    document = EditDocument()
    qtbot.addWidget(document)
    document.resize(650, 250)
    document.set_language("python")
    document.show_state(EditorState(("return 12 # note",)))
    document.show_highlights((TextSpan(0, 7, 9, "replace"),))
    document.show()
    qtbot.waitExposed(document)
    before = document.grab().toImage()
    document.show_yank((YankSpan(0, 0, 16),))
    after = document.grab().toImage()
    scale = after.devicePixelRatio()
    metrics = document.document_metrics
    top = round(16 * scale)
    bottom = round((16 + metrics.lineSpacing()) * scale)
    colors = {
        after.pixelColor(x, y).name()
        for y in range(top, bottom)
        for x in range(round(58 * scale), round(350 * scale))
    }
    assert {"#cda9ef", "#f3bc82", "#8fa0ad", "#f0c76d", "#c3ef85"} <= colors
    x = round((58 + metrics.horizontalAdvance("return 12 # not")) * scale)
    y = round((16 + metrics.lineSpacing() - 5) * scale)
    assert before.pixelColor(x, y) != after.pixelColor(x, y)
    assert document.editor_state.lines == ("return 12 # note",)


@pytest.mark.parametrize("line", ["", "x"])
def test_yank_remains_visible_when_block_cursor_covers_the_entire_span(
    qtbot: QtBot, line: str
) -> None:
    document = EditDocument()
    qtbot.addWidget(document)
    document.resize(250, 180)
    document.show_state(EditorState((line,)))
    document.show()
    qtbot.waitExposed(document)
    before = document.grab().toImage()
    document.show_yank((YankSpan(0, 0, len(line)),))
    after = document.grab().toImage()
    assert before != after
    scale = after.devicePixelRatio()
    cursor = document.cursor_rect
    x = round(cursor.center().x() * scale)
    y = round((cursor.bottom() - 3) * scale)
    assert before.pixelColor(x, y) == after.pixelColor(x, y)
