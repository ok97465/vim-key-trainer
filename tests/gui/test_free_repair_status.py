"""부분 복구의 진행·되돌림·중복 갱신과 자유 풀이 완료 연출을 검증한다."""

# Standard library imports
from dataclasses import replace

# Third party imports
import pytest
from PySide6.QtCore import QAbstractAnimation, Qt
from PySide6.QtWidgets import QLineEdit, QVBoxLayout, QWidget
from pytestqt.qtbot import QtBot

# Local imports
from vim_key_trainer.content.edit_loader import get_edit_lesson
from vim_key_trainer.domain.free_repair_progress import (
    FreeRepairEvent,
    FreeRepairSnapshot,
)
from vim_key_trainer.domain.preferences import PresentationSettings
from vim_key_trainer.domain.sessions import SessionState
from vim_key_trainer.services.edit_session import EditingSession
from vim_key_trainer.ui.widgets.challenge_finale import ChallengeFinale
from vim_key_trainer.ui.widgets.free_repair_status import FreeRepairStatus


def _snapshot(
    solved: int,
    *,
    events: tuple[FreeRepairEvent, ...] = (),
    first_solved: int = 0,
    remaining: int | None = None,
) -> FreeRepairSnapshot:
    return FreeRepairSnapshot(
        total=3,
        solved=solved,
        first_solved=first_solved,
        events=events,
        marks=(),
        remaining_changes=3 - solved if remaining is None else remaining,
    )


def _event(identity: str, count: int) -> FreeRepairEvent:
    return FreeRepairEvent(identity, 0, 0, "old", "word", count)


def test_repair_animation_preserves_focus_geometry_and_duplicate_refresh(
    qtbot: QtBot,
) -> None:
    host = QWidget()
    qtbot.addWidget(host)
    layout = QVBoxLayout(host)
    status = FreeRepairStatus()
    layout.addWidget(status)
    focus = QLineEdit()
    layout.addWidget(focus)
    status.set_progress(_snapshot(0))
    host.resize(600, 120)
    host.show()
    host.activateWindow()
    focus.setFocus()
    qtbot.waitUntil(focus.hasFocus)
    geometry = focus.geometry()
    snapshot = _snapshot(2, events=(_event("a", 1), _event("b", 2)), first_solved=2)
    status.set_progress(snapshot)
    assert status.animation.state() == QAbstractAnimation.State.Running
    status.animation.pause()
    status.animation.setCurrentTime(280)
    painted = status.grab().toImage()
    status.set_progress(snapshot)
    assert status.animation.state() == QAbstractAnimation.State.Paused
    assert status.animation.currentTime() == 280
    assert status.grab().toImage() == painted
    assert focus.geometry() == geometry
    assert focus.hasFocus()
    assert status.focusPolicy() == Qt.FocusPolicy.NoFocus
    assert status.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    status.hide()
    assert status.animation.state() == QAbstractAnimation.State.Stopped


def test_undo_reduces_current_progress_without_replaying_first_repair(
    qtbot: QtBot,
) -> None:
    status = FreeRepairStatus()
    qtbot.addWidget(status)
    status.resize(520, 42)
    first = _snapshot(1, events=(_event("a", 1),), first_solved=1)
    status.set_progress(first)
    status.stop_effects()
    solved_image = status.grab().toImage()
    undone = _snapshot(0, first_solved=1)
    status.set_progress(undone)
    assert status.snapshot is undone
    assert status.grab().toImage() != solved_image
    assert status.animation.state() == QAbstractAnimation.State.Stopped
    redone = _snapshot(1, first_solved=1)
    status.set_progress(redone)
    assert status.snapshot is redone
    assert status.animation.state() == QAbstractAnimation.State.Stopped
    # 재도전은 시도 내 중복 기억을 지워 같은 지점에 다시 반응한다.
    status.clear()
    status.set_progress(first)
    assert status.animation.state() == QAbstractAnimation.State.Running
    status.stop_effects()


@pytest.mark.parametrize(
    "settings",
    [
        PresentationSettings(reduced_motion=True),
        PresentationSettings(effects=False),
    ],
)
def test_static_progress_survives_effect_preferences_and_extra_document_damage(
    qtbot: QtBot, settings: PresentationSettings
) -> None:
    status = FreeRepairStatus()
    qtbot.addWidget(status)
    status.configure_effects(settings)
    status.resize(340, 42)
    snapshot = _snapshot(3, events=(_event("a", 3),), first_solved=3, remaining=1)
    status.set_progress(snapshot)
    before = status.grab().toImage()
    qtbot.wait(30)
    assert status.grab().toImage() == before
    assert status.isVisible()
    assert status.animation.state() == QAbstractAnimation.State.Stopped
    assert status.snapshot is not None and status.snapshot.remaining_changes == 1
    assert "남은 문서 차이 1" in status.accessibleName()
    status.clear()
    assert status.isHidden() and status.snapshot is None


@pytest.mark.parametrize("reduced", [False, True])
def test_plain_free_completion_has_finale_without_fabricated_challenge_score(
    qtbot: QtBot, reduced: bool
) -> None:
    session = EditingSession(
        get_edit_lesson("editing_numbers"), "free", clock_ns=lambda: 0
    )
    for token in session.lesson.baseline:
        session.submit(token)
    result = session.result
    assert result is not None and result.state == SessionState.COMPLETED
    assert result.challenge is None
    finale = ChallengeFinale()
    qtbot.addWidget(finale)
    finale.configure_effects(PresentationSettings(reduced_motion=reduced))
    finale.resize(500, 132)
    finale.present(result)
    assert finale.isVisible()
    assert finale.result is result
    assert result.challenge is None
    assert "점수" not in finale.accessibleName()
    assert str(result.key_count) in finale.accessibleName()
    assert (finale.animation.state() == QAbstractAnimation.State.Running) is not reduced
    assert not finale.grab().isNull()
    finale.configure_effects(PresentationSettings(effects=False))
    assert finale.isHidden()
    assert finale.animation.state() == QAbstractAnimation.State.Stopped
    assert session.result is result
    finale.present(replace(result, mode="guided"))
    assert finale.result is None
