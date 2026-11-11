"""피날레와 해금 연출이 결과·입력·새 시도의 경계를 보존하는지 검증한다."""

# Standard library imports
from dataclasses import replace

# Third party imports
import pytest
from PySide6.QtCore import QAbstractAnimation, Qt
from pytestqt.qtbot import QtBot

# Local imports
from vim_key_trainer.content.edit_loader import get_edit_lesson
from vim_key_trainer.domain.achievements import LearningSummary
from vim_key_trainer.domain.challenge import ChallengeOptions
from vim_key_trainer.domain.decorations import DecorationProgress
from vim_key_trainer.domain.editing import EditLesson, EditSegment, GuideStep
from vim_key_trainer.domain.keys import KeyToken
from vim_key_trainer.domain.preferences import AppearanceSettings, PresentationSettings
from vim_key_trainer.domain.sessions import SessionState
from vim_key_trainer.engine import SUPPORTED_COMMANDS, EditorState
from vim_key_trainer.services.edit_session import EditingSession
from vim_key_trainer.services.result_repository import MemoryResultRepository
from vim_key_trainer.ui.edit_practice import EditPracticePage
from vim_key_trainer.ui.widgets.collection_workshop import CollectionWorkshop


def _lesson() -> EditLesson:
    initial = EditorState(("alpha", "beta"))
    middle = EditorState(("Alpha", "beta"))
    goal = ("Alpha", "Beta")
    first = tuple(KeyToken("char", value) for value in "rA")
    second = tuple(KeyToken("char", value) for value in "jrB")
    return replace(
        get_edit_lesson("editing_numbers"),
        initial=initial,
        goal_lines=goal,
        goal_cursor=None,
        allowed_commands=SUPPORTED_COMMANDS,
        guide=(
            GuideStep(first, middle, "첫 줄 교체"),
            GuideStep(second, EditorState(goal, row=1), "둘째 줄 교체"),
        ),
        baseline=first + second,
        baseline_keys=5,
        segments=(
            EditSegment("first", 0, 1, 0, 1),
            EditSegment("second", 1, 2, 1, 2, ("first",)),
        ),
    )


def _page(qtbot: QtBot, settings: PresentationSettings) -> EditPracticePage:
    lesson = _lesson()
    page = EditPracticePage(MemoryResultRepository(), presentation=settings)
    qtbot.addWidget(page)
    page.resize(1100, 850)
    page.show()
    page.activateWindow()
    session = EditingSession(
        lesson, challenge=ChallengeOptions("bomb"), clock_ns=lambda: 0
    )
    page.prepare(lesson, prepared_session=session)
    page.start_practice()
    qtbot.waitUntil(page.practice_input.hasFocus)
    return page


@pytest.mark.parametrize("reduced", [False, True])
def test_finale_keeps_result_available_and_retry_immediate(
    qtbot: QtBot, reduced: bool
) -> None:
    page = _page(qtbot, PresentationSettings(reduced_motion=reduced))
    qtbot.keyClicks(page.practice_input, "rAjrB")
    session = page.session
    assert session is not None and session.state == SessionState.COMPLETED
    result = session.result
    assert result is not None and result.challenge is not None
    assert result.challenge.full_clear
    assert page.stack.currentWidget() is page.result_page
    assert page.result_finale.result == result
    assert page.result_finale.isVisible()
    assert page.result_finale.testAttribute(
        Qt.WidgetAttribute.WA_TransparentForMouseEvents
    )
    assert (
        page.result_finale.animation.state() == QAbstractAnimation.State.Running
    ) is not reduced
    # 장식이 진행 중이어도 새 시도로 이동하며 결과 정산을 반복하지 않는다.
    if not reduced:
        page.result_finale.animation.setCurrentTime(650)
    animation_time = page.result_finale.animation.currentTime()
    before = session.engine.snapshot()
    page._finish()
    assert page.result_finale.animation.currentTime() == animation_time
    assert session.result == result
    assert session.engine.snapshot() == before
    assert len(page.repository.results) == 1
    qtbot.mouseClick(page.result_retry_button, Qt.MouseButton.LeftButton)
    fresh = page.session
    assert fresh is not None and fresh.attempt_id != session.attempt_id
    assert fresh.state == SessionState.READY and fresh.key_count == 0
    assert page.result_finale.result is None
    assert page.result_finale.animation.state() == QAbstractAnimation.State.Stopped
    assert page.pressure_frame.isHidden()
    page.abort()


def test_turning_effects_off_mid_finale_stops_motion_without_changing_result(
    qtbot: QtBot,
) -> None:
    page = _page(qtbot, PresentationSettings())
    qtbot.keyClicks(page.practice_input, "rAjrB")
    result = page.last_result
    assert result is not None
    page.configure_effects(PresentationSettings(effects=False))
    assert page.result_finale.isHidden()
    assert page.result_finale.animation.state() == QAbstractAnimation.State.Stopped
    assert page.session is not None and page.session.result == result
    assert len(page.repository.results) == 1
    page.abort()


def test_pressure_overlay_keeps_viewport_and_keyboard_input(qtbot: QtBot) -> None:
    page = _page(qtbot, PresentationSettings())
    session = page.session
    assert session is not None
    viewport = page.document_scroll.viewport().size()
    page.pressure_frame.set_pressure(1.0)
    assert page.pressure_frame.isVisible()
    assert page.document_scroll.viewport().size() == viewport
    assert page.practice_input.hasFocus()
    qtbot.keyClicks(page.practice_input, "rA")
    assert session.key_count == 2 and session.direct_count == 1
    assert page.practice_input.hasFocus()
    assert session.elapsed_seconds == 0
    page.pause()
    assert page.pressure_frame.isHidden()
    assert not page.challenge_status.motion_timer.isActive()
    page.abort()


def _learning(count: int) -> LearningSummary:
    return LearningSummary(16, count, 0, count, frozenset(), ())


@pytest.mark.parametrize("reduced", [False, True])
def test_workshop_only_celebrates_new_unlock_once(qtbot: QtBot, reduced: bool) -> None:
    workshop = CollectionWorkshop()
    qtbot.addWidget(workshop)
    workshop.configure_effects(PresentationSettings(reduced_motion=reduced))
    # 기존 기록을 읽는 시작 시점에는 해금 연출을 재생하지 않는다.
    workshop.set_progress(_learning(0), DecorationProgress(0, 0))
    workshop.show()
    workshop.set_progress(_learning(1), DecorationProgress(1, 1))
    assert workshop.unlock_notice.isVisible()
    assert (
        workshop.art.animation.state() == QAbstractAnimation.State.Running
    ) is not reduced
    if not reduced:
        workshop.art.animation.pause()
        workshop.art.animation.setCurrentTime(500)
    animation_time = workshop.art.animation.currentTime()
    before = workshop.art.grab().toImage()
    workshop.set_progress(_learning(1), DecorationProgress(1, 1))
    assert workshop.art.animation.currentTime() == animation_time
    assert workshop.art.grab().toImage() == before
    workshop.hide()
    assert workshop.art.animation.state() == QAbstractAnimation.State.Stopped
    workshop.show()
    assert workshop.art.animation.state() == QAbstractAnimation.State.Stopped
    assert workshop.art.progress == 1


def test_existing_workshop_collection_does_not_replay_unlock(qtbot: QtBot) -> None:
    workshop = CollectionWorkshop()
    qtbot.addWidget(workshop)
    workshop.set_progress(_learning(6), DecorationProgress(6, 20))
    workshop.show()
    assert workshop.unlock_notice.isHidden()
    assert workshop.art.animation.state() == QAbstractAnimation.State.Stopped
    workshop.set_progress(_learning(12), DecorationProgress(12, 25))
    assert workshop.art.animation.state() == QAbstractAnimation.State.Running
    workshop.configure_effects(PresentationSettings(effects=False))
    assert workshop.art.animation.state() == QAbstractAnimation.State.Stopped
    assert workshop.art.progress == 12


def test_workshop_does_not_queue_celebration_while_decorations_are_hidden(
    qtbot: QtBot,
) -> None:
    workshop = CollectionWorkshop()
    qtbot.addWidget(workshop)
    workshop.set_progress(_learning(0), DecorationProgress(0, 0))
    workshop.configure_appearance(AppearanceSettings(decorations=False))
    workshop.show()
    workshop.set_progress(_learning(1), DecorationProgress(1, 1))
    assert workshop.art.isHidden()
    workshop.configure_appearance(AppearanceSettings())
    assert workshop.art.isVisible()
    assert workshop.art.animation.state() == QAbstractAnimation.State.Stopped
    assert workshop.art.arrival == 1.0
    assert workshop.art.progress == 1
