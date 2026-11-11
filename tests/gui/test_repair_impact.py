"""절단의 잔흔·정적 대체·중복 방지가 문서나 시계를 바꾸지 않는지 검증한다."""

# Standard library imports
from dataclasses import replace

# Third party imports
import pytest
from PySide6.QtCore import QAbstractAnimation, Qt
from PySide6.QtGui import QImage
from pytestqt.qtbot import QtBot

# Local imports
from vim_key_trainer.content.edit_loader import get_edit_lesson
from vim_key_trainer.domain.challenge import ChallengeOptions
from vim_key_trainer.domain.editing import EditLesson, EditSegment, GuideStep
from vim_key_trainer.domain.keys import KeyToken
from vim_key_trainer.domain.preferences import PresentationSettings
from vim_key_trainer.engine import SUPPORTED_COMMANDS, EditorState
from vim_key_trainer.services.edit_session import EditingSession
from vim_key_trainer.ui.widgets.edit_comparison import EditComparison
from vim_key_trainer.ui.widgets.repair_effects import RepairEffects


def _lesson() -> EditLesson:
    first = tuple(KeyToken("char", key) for key in "rA")
    second = tuple(KeyToken("char", key) for key in "jrB")
    return replace(
        get_edit_lesson("editing_numbers"),
        initial=EditorState(("alpha", "bravo")),
        goal_lines=("Alpha", "Bravo"),
        goal_cursor=None,
        allowed_commands=SUPPORTED_COMMANDS,
        guide=(
            GuideStep(first, EditorState(("Alpha", "bravo")), "첫 글자 교체"),
            GuideStep(second, EditorState(("Alpha", "Bravo"), 1, 0), "다음 줄 교체"),
        ),
        baseline=first + second,
        baseline_keys=5,
        segments=(
            EditSegment("first", 0, 1, 0, 1),
            EditSegment("second", 1, 2, 1, 2, ("first",)),
        ),
    )


def _surface(
    qtbot: QtBot, session: EditingSession, *, reduced: bool = False
) -> tuple[EditComparison, RepairEffects]:
    comparison = EditComparison()
    qtbot.addWidget(comparison)
    comparison.resize(750, 340)
    comparison.show_documents(
        session.engine.state, EditorState(session.lesson.goal_lines)
    )
    comparison.show()
    comparison.activateWindow()
    comparison.practice_input.setFocus()
    qtbot.waitUntil(comparison.practice_input.hasFocus)
    overlay = RepairEffects(comparison)
    overlay.configure_effects(PresentationSettings(reduced_motion=reduced))
    overlay.set_session(session)
    return comparison, overlay


def _paint(overlay: RepairEffects, milliseconds: int) -> QImage:
    overlay.animation.setCurrentTime(milliseconds)
    return overlay.grab().toImage()


def test_success_has_visible_fragments_and_retains_the_stamp_after_motion(
    qtbot: QtBot,
) -> None:
    session = EditingSession(
        _lesson(), challenge=ChallengeOptions("bomb"), clock_ns=lambda: 0
    )
    comparison, overlay = _surface(qtbot, session)
    for token in session.lesson.guide[0].keys:
        session.submit(token)
    comparison.show_current(session.engine.state)
    overlay.set_session(session)
    overlay.animation.pause()
    assert overlay._events[0].old_text == "alpha"
    state = session.engine.snapshot()
    time = session.remaining_seconds
    early = _paint(overlay, 150)
    late = _paint(overlay, 850)
    settled = _paint(overlay, 1100)
    # 기존 620ms를 넘겨도 그림이 이어지고, 1초 뒤에도 성공을 확인할 수 있다.
    assert overlay.isVisible()
    assert early != late and late != settled
    assert session.engine.snapshot() == state
    assert session.remaining_seconds == time
    assert comparison.practice_input.hasFocus()
    assert overlay.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    overlay.animation.setCurrentTime(1250)
    assert not overlay.isVisible()


def test_next_input_runs_during_the_impact_and_refresh_does_not_replay_it(
    qtbot: QtBot,
) -> None:
    session = EditingSession(
        _lesson(), challenge=ChallengeOptions("bomb"), clock_ns=lambda: 0
    )
    comparison, overlay = _surface(qtbot, session)
    for token in session.lesson.guide[0].keys:
        session.submit(token)
    comparison.show_current(session.engine.state)
    overlay.set_session(session)
    overlay.animation.pause()
    overlay.animation.setCurrentTime(650)
    before = overlay.animation.currentTime()
    overlay.set_session(session)
    assert overlay.animation.currentTime() == before
    token = session.expected_token
    assert token is not None
    session.submit(token)
    comparison.show_current(session.engine.state)
    overlay.set_session(session)
    assert session.engine.state.row == 1
    assert session.key_count == 3
    assert overlay.isVisible()
    assert comparison.practice_input.hasFocus()
    session.pause()
    overlay.set_session(session)
    assert not overlay.isVisible()
    assert overlay.animation.state() == QAbstractAnimation.State.Stopped


@pytest.mark.parametrize("reduced", [False, True])
def test_close_call_and_revenge_do_not_change_the_awarded_result(
    qtbot: QtBot, reduced: bool
) -> None:
    now = 0
    session = EditingSession(
        _lesson(), challenge=ChallengeOptions("bomb"), clock_ns=lambda: now
    )
    comparison, overlay = _surface(qtbot, session, reduced=reduced)
    session.submit(session.expected_token)
    limit = session.segment_limit_seconds
    assert limit is not None
    now = round((limit - 0.5) * 1_000_000_000)
    session.submit(session.expected_token)
    comparison.show_current(session.engine.state)
    awarded = session.segment_results
    overlay.set_session(session)
    assert "간발의 해체" in overlay.accessibleName()
    assert session.segment_results == awarded
    if reduced:
        assert overlay.animation.state() == QAbstractAnimation.State.Stopped
        image = overlay.grab().toImage()
        qtbot.wait(30)
        assert overlay.grab().toImage() == image
    overlay.stop_effects()
    session.submit(session.expected_token)
    now += 100_000_000_000
    session.check_deadline()
    revenge = session.create_revenge()
    comparison.show_current(revenge.engine.state)
    overlay.set_session(revenge)
    for token in revenge.lesson.guide[1].keys:
        revenge.submit(token)
    awarded = revenge.result
    overlay.set_session(revenge)
    assert "복수 성공" in overlay.accessibleName()
    assert revenge.result is awarded
    assert overlay._events[0].revenge
    overlay.configure_effects(PresentationSettings(effects=False))
    assert not overlay.isVisible()
    assert not overlay._clear_timer.isActive()
