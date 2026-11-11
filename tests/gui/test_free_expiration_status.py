"""자유 풀이의 시간 종료가 실패 폭발 대신 계속 연습 안내로 남는지 검증한다."""

# Third party imports
import pytest
from PySide6.QtCore import QAbstractAnimation
from PySide6.QtWidgets import QLineEdit, QVBoxLayout, QWidget
from pytestqt.qtbot import QtBot

# Local imports
from vim_key_trainer.content.edit_loader import get_edit_lesson
from vim_key_trainer.domain.challenge import ChallengeOptions
from vim_key_trainer.domain.preferences import PresentationSettings
from vim_key_trainer.domain.sessions import SessionState
from vim_key_trainer.services.edit_session import EditingSession
from vim_key_trainer.ui.widgets.challenge_finale import ChallengeFinale
from vim_key_trainer.ui.widgets.challenge_status import ChallengeStatus


def _expired_session() -> EditingSession:
    now = [0]
    lesson = get_edit_lesson("editing_numbers")
    session = EditingSession(
        lesson,
        "free",
        challenge=ChallengeOptions("bomb", auto_repair=False),
        clock_ns=lambda: now[0],
    )
    session.submit(lesson.baseline[0])
    remaining = session.remaining_seconds
    assert remaining is not None
    now[0] += round(remaining * 1_000_000_000)
    session.check_deadline()
    assert session.timeout_count == 1
    assert session.state == SessionState.RUNNING
    return session


@pytest.mark.parametrize("reduced", [False, True])
def test_expired_free_uses_one_soft_cue_and_a_static_clock_without_losing_focus(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, reduced: bool
) -> None:
    session = _expired_session()
    host = QWidget()
    qtbot.addWidget(host)
    layout = QVBoxLayout(host)
    status = ChallengeStatus(host)
    layout.addWidget(status)
    focus = QLineEdit()
    layout.addWidget(focus)
    status.configure_effects(PresentationSettings(reduced_motion=reduced))
    cues: list[str] = []
    monkeypatch.setattr(status.audio, "play", lambda cue, **kwargs: cues.append(cue))
    host.resize(700, 150)
    host.show()
    host.activateWindow()
    focus.setFocus()
    qtbot.waitUntil(focus.hasFocus)
    engine = session.engine.snapshot()
    results = session.segment_results
    status.set_session(session)
    assert cues == ["expired"]
    assert status.mascot.expired
    assert not status.mascot.verdict
    assert status.pressure == 0
    assert status.fuse.ratio == 0
    assert not status.fuse.spark
    assert not status.motion_timer.isActive()
    assert status.mascot.animation.state() == QAbstractAnimation.State.Stopped
    before = status.mascot.grab().toImage()
    qtbot.wait(70)
    for _ in range(3):
        status.set_session(session)
    assert status.mascot.grab().toImage() == before
    assert cues == ["expired"]
    assert session.engine.snapshot() == engine
    assert session.segment_results == results
    assert session.direct_count == 0
    assert focus.hasFocus()
    session.pause()
    status.set_session(session)
    assert not status.mascot.expired
    session.resume()
    status.set_session(session)
    assert status.mascot.expired
    assert cues == ["expired"]
    status.configure_effects(PresentationSettings(effects=False))
    assert not status.mascot.expired
    assert not status.motion_timer.isActive()
    status.configure_effects(PresentationSettings(reduced_motion=True))
    assert status.mascot.expired
    assert not status.motion_timer.isActive()
    assert cues == ["expired"]
    status.hide()
    assert not status.mascot.expired


def test_guided_timeout_keeps_its_existing_failure_cue(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = [0]
    lesson = get_edit_lesson("editing_numbers")
    session = EditingSession(
        lesson,
        challenge=ChallengeOptions("bomb", auto_repair=False),
        clock_ns=lambda: now[0],
    )
    session.submit(lesson.baseline[0])
    remaining = session.remaining_seconds
    assert remaining is not None
    now[0] += round(remaining * 1_000_000_000)
    session.check_deadline()
    status = ChallengeStatus()
    qtbot.addWidget(status)
    cues: list[str] = []
    monkeypatch.setattr(status.audio, "play", lambda cue, **kwargs: cues.append(cue))
    status.set_session(session)
    assert cues == ["timeout"]
    assert not status.mascot.expired
    assert status.mascot.verdict == "timeout"
    status.stop_effects()


def test_completing_expired_free_practice_does_not_claim_a_clear_or_offer_revenge(
    qtbot: QtBot,
) -> None:
    session = _expired_session()
    for token in session.lesson.baseline[1:]:
        session.submit(token)
    result = session.result
    assert result is not None and result.challenge is not None
    assert result.state == SessionState.COMPLETED
    assert not result.challenge.full_clear and result.stars == 0
    finale = ChallengeFinale()
    qtbot.addWidget(finale)
    finale.resize(520, 132)
    finale.present(result)
    assert finale.isVisible()
    assert finale.animation.state() == QAbstractAnimation.State.Stopped
    assert finale.result is result
    assert "제한시간 초과" in finale.accessibleName()
    assert "복수전" not in finale.accessibleName()
    assert not finale.grab().isNull()
    assert session.result is result
    assert result.challenge.timeout_count == 1
