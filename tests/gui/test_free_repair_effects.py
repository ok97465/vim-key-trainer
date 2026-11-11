"""자유 복구의 동시 타격과 수명이 입력·시도 경계를 보존하는지 검증한다."""

# Standard library imports
from dataclasses import replace

# Third party imports
import pytest
from PySide6.QtCore import QAbstractAnimation, QRectF, Qt
from PySide6.QtGui import QPainter
from pytestqt.qtbot import QtBot

# Local imports
from vim_key_trainer.content.edit_loader import get_edit_lesson
from vim_key_trainer.domain.challenge import ChallengeOptions
from vim_key_trainer.domain.editing import EditLesson, GuideStep
from vim_key_trainer.domain.free_repair_progress import FreeRepairEvent
from vim_key_trainer.domain.keys import KeyToken
from vim_key_trainer.domain.preferences import PresentationSettings
from vim_key_trainer.engine import SUPPORTED_COMMANDS, EditorState
from vim_key_trainer.services.edit_session import EditingSession
from vim_key_trainer.ui.widgets.edit_comparison import EditComparison
from vim_key_trainer.ui.widgets.repair_effects import RepairEffects


def _lesson() -> EditLesson:
    initial = EditorState(("alpha", "bravo", "charlie"))
    goal = ("Alpha", "Bravo", "Charlie")
    guides = []
    lines = list(initial.lines)
    baseline: tuple[KeyToken, ...] = ()
    for index, letter in enumerate("ABC"):
        keys = tuple(
            KeyToken("char", char) for char in ("j" if index else "") + "r" + letter
        )
        lines[index] = goal[index]
        guides.append(
            GuideStep(keys, EditorState(tuple(lines), index, 0), "첫 문자 교체")
        )
        baseline += keys
    return replace(
        get_edit_lesson("editing_numbers"),
        initial=initial,
        goal_lines=goal,
        goal_cursor=None,
        allowed_commands=SUPPORTED_COMMANDS,
        guide=tuple(guides),
        baseline=baseline,
        baseline_keys=len(baseline),
        segments=(),
    )


def _surface(
    qtbot: QtBot, session: EditingSession
) -> tuple[EditComparison, RepairEffects]:
    comparison = EditComparison()
    qtbot.addWidget(comparison)
    comparison.resize(1050, 650)
    comparison.show_documents(
        session.engine.state, EditorState(session.lesson.goal_lines)
    )
    comparison.show()
    comparison.activateWindow()
    comparison.practice_input.setFocus()
    qtbot.waitUntil(comparison.practice_input.hasFocus)
    comparison.practice_input.key_received.connect(
        lambda key: session.submit(key.token)
    )
    overlay = RepairEffects(comparison)
    overlay.set_session(session)
    return comparison, overlay


@pytest.mark.parametrize("bomb", [False, True])
def test_free_repair_survives_refresh_and_next_key_without_replaying(
    qtbot: QtBot, bomb: bool
) -> None:
    session = EditingSession(
        _lesson(),
        "free",
        challenge=ChallengeOptions("bomb" if bomb else "normal"),
        clock_ns=lambda: 0,
    )
    comparison, overlay = _surface(qtbot, session)
    qtbot.keyClicks(comparison.practice_input, "rA")
    comparison.show_current(session.engine.state)
    overlay.set_session(session)
    events = (FreeRepairEvent("first", 0, 0, "alpha", "precise", 1),)
    before = session.engine.snapshot()
    overlay.show_free_repairs(events)
    overlay.animation.pause()
    overlay.animation.setCurrentTime(700)
    assert overlay.isVisible()
    assert session.engine.snapshot() == before
    qtbot.keyClicks(comparison.practice_input, "j")
    comparison.show_current(session.engine.state)
    overlay.set_session(session)
    overlay.show_free_repairs(events)
    assert overlay.animation.currentTime() == 700
    assert session.engine.state.row == 1 and session.key_count == 3
    assert session.elapsed_seconds == 0
    assert comparison.practice_input.hasFocus()
    assert overlay.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    session.pause()
    overlay.set_session(session)
    assert overlay.isHidden()
    assert overlay.animation.state() == QAbstractAnimation.State.Stopped


@pytest.mark.parametrize("reduced", [False, True])
def test_batch_repairs_draw_separate_visible_locations_without_scrolling(
    qtbot: QtBot, reduced: bool
) -> None:
    session = EditingSession(_lesson(), "free", clock_ns=lambda: 0)
    comparison, overlay = _surface(qtbot, session)
    lines = tuple(f"row {index:02d}" for index in range(40))
    comparison.show_documents(EditorState(lines), EditorState(lines))
    comparison.clear_guide()
    metrics = comparison.practice_input.document_metrics
    before = comparison.grab().toImage()
    events = tuple(
        FreeRepairEvent(f"repair-{row}", row, 0, lines[row], "word", index + 1)
        for index, row in enumerate((0, 5, 10, 15, 32, 39))
    )
    snapshot = session.engine.snapshot()
    offset = comparison.current_scroll.verticalScrollBar().value()
    overlay.configure_effects(PresentationSettings(reduced_motion=reduced))
    overlay.show_free_repairs(events)
    if not reduced:
        overlay.animation.pause()
        overlay.animation.setCurrentTime(140)
    after = comparison.grab().toImage()
    viewport = comparison.current_scroll.viewport()
    origin = viewport.mapTo(comparison, viewport.rect().topLeft())
    scale = after.devicePixelRatio()
    for row in (0, 5, 10, 15):
        x = round((origin.x() + 45) * scale)
        y = round((origin.y() + 16 + row * metrics.lineSpacing()) * scale)
        width = round(170 * scale)
        height = round(metrics.lineSpacing() * scale)
        assert before.copy(x, y, width, height) != after.copy(x, y, width, height)
    assert len(overlay._events) == 6
    assert comparison.current_scroll.verticalScrollBar().value() == offset
    assert session.engine.snapshot() == snapshot
    assert comparison.practice_input.hasFocus()
    overlay.stop_effects()


def test_reduced_motion_is_static_and_disabled_events_do_not_replay(
    qtbot: QtBot,
) -> None:
    session = EditingSession(_lesson(), "free", clock_ns=lambda: 0)
    comparison, overlay = _surface(qtbot, session)
    qtbot.keyClicks(comparison.practice_input, "rA")
    comparison.show_current(session.engine.state)
    overlay.configure_effects(PresentationSettings(reduced_motion=True))
    first = (FreeRepairEvent("first", 0, 0, "alpha", "precise", 1),)
    overlay.show_free_repairs(first)
    assert overlay.isVisible()
    assert overlay.animation.state() == QAbstractAnimation.State.Stopped
    before = comparison.grab().toImage()
    qtbot.wait(35)
    assert comparison.grab().toImage() == before
    overlay.configure_effects(PresentationSettings(effects=False))
    second = (FreeRepairEvent("second", 1, 0, "bravo", "word", 2),)
    overlay.show_free_repairs(second)
    assert overlay.isHidden()
    assert not overlay._clear_timer.isActive()
    overlay.configure_effects(PresentationSettings())
    overlay.show_free_repairs(first + second)
    assert overlay.isHidden()


def test_free_bomb_timeout_stops_unrelated_line_effect_without_auto_repair(
    qtbot: QtBot,
) -> None:
    now = 0
    session = EditingSession(
        _lesson(), "free", challenge=ChallengeOptions("bomb"), clock_ns=lambda: now
    )
    comparison, overlay = _surface(qtbot, session)
    qtbot.keyClicks(comparison.practice_input, "rA")
    comparison.show_current(session.engine.state)
    overlay.set_session(session)
    overlay.show_free_repairs((FreeRepairEvent("first", 0, 0, "alpha", "precise", 1),))
    snapshot = session.engine.snapshot()
    now = 10**15
    session.check_deadline()
    overlay.set_session(session)
    assert not overlay._events and overlay.isHidden()
    assert overlay.animation.state() == QAbstractAnimation.State.Stopped
    assert session.timeout_count == 1 and session.auto_repair_count == 0
    assert session.engine.snapshot() == snapshot
    overlay.stop_effects()


@pytest.mark.parametrize(
    ("old_text", "current_text", "source_column", "current_column", "marker"),
    [
        ("x ... bad", "supercalifragilistic ... GOOD", 6, 24, "bad"),
        ("p" * 40 + "aXc", "abc", 41, 1, "X"),
    ],
)
def test_fragment_keeps_correct_original_text_after_prefix_length_changes(
    qtbot: QtBot,
    monkeypatch: pytest.MonkeyPatch,
    old_text: str,
    current_text: str,
    source_column: int,
    current_column: int,
    marker: str,
) -> None:
    drawn_text: list[str] = []

    class RecordingPainter(QPainter):
        def drawText(
            self, rectangle: QRectF, flags: Qt.AlignmentFlag, text: str
        ) -> QRectF:
            drawn_text.append(text)
            return super().drawText(rectangle, flags, text)

    monkeypatch.setattr(
        "vim_key_trainer.ui.widgets.repair_effects.QPainter", RecordingPainter
    )
    session = EditingSession(_lesson(), "free", clock_ns=lambda: 0)
    comparison, overlay = _surface(qtbot, session)
    comparison.set_font_size(12)
    comparison.show_documents(
        EditorState((current_text,)), EditorState((current_text,))
    )
    snapshot = session.engine.snapshot()
    overlay.show_free_repairs(
        (
            FreeRepairEvent(
                "shifted-original",
                0,
                current_column,
                old_text,
                "word",
                1,
                source_column=source_column,
            ),
        )
    )
    overlay.animation.pause()
    overlay.animation.setCurrentTime(450)
    image = overlay.grab().toImage()
    assert not image.isNull()
    # 실제 두 반쪽에 그리는 글자에 고친 원문이 남아 있어야 한다.
    assert sum(marker in text for text in drawn_text) >= 2
    assert session.engine.snapshot() == snapshot
    assert comparison.practice_input.hasFocus()
    overlay.stop_effects()
