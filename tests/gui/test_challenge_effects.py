"""연출은 수동 상태 표시이며 입력·시간·채점을 바꾸지 않는다."""

# Standard library imports
import sys
from dataclasses import replace
from importlib.resources import files

# Third party imports
import pytest
from PySide6.QtCore import QAbstractAnimation, Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QLineEdit, QVBoxLayout, QWidget
from pytestqt.qtbot import QtBot

# Local imports
from vim_key_trainer.content.edit_loader import get_edit_lesson
from vim_key_trainer.domain.challenge import ChallengeOptions
from vim_key_trainer.domain.editing import EditPracticeSpec
from vim_key_trainer.domain.preferences import PresentationSettings
from vim_key_trainer.services.edit_problem_factory import create_edit_problem
from vim_key_trainer.services.edit_session import EditingSession
from vim_key_trainer.ui.challenge_audio import ChallengeAudio
from vim_key_trainer.ui.widgets.challenge_status import ChallengeStatus
from vim_key_trainer.ui.widgets.edit_comparison import EditComparison
from vim_key_trainer.ui.widgets.repair_effects import RepairEffects


@pytest.mark.parametrize("reduced", [False, True])
def test_effects_do_not_change_session_or_keyboard_focus(
    qtbot: QtBot, reduced: bool
) -> None:
    now = 0
    lesson = get_edit_lesson("editing_numbers")
    sessions = [
        EditingSession(lesson, challenge=ChallengeOptions("bomb"), clock_ns=lambda: now)
        for _ in range(2)
    ]
    host = QWidget()
    qtbot.addWidget(host)
    layout = QVBoxLayout(host)
    focus = QLineEdit()
    layout.addWidget(focus)
    statuses = [ChallengeStatus(host), ChallengeStatus(host)]
    for index, status in enumerate(statuses):
        layout.addWidget(status)
        status.configure_effects(
            PresentationSettings(effects=bool(index), reduced_motion=reduced)
        )
    host.resize(800, 240)
    host.show()
    host.activateWindow()
    focus.setFocus()
    qtbot.waitUntil(focus.hasFocus)
    for token in lesson.baseline:
        now += 10_000_000
        for session, status in zip(sessions, statuses, strict=True):
            session.submit(token)
            status.set_session(session)
        assert sessions[0].engine.snapshot() == sessions[1].engine.snapshot()
        assert focus.hasFocus()
    first, second = (session.result for session in sessions)
    assert first is not None and second is not None
    assert replace(first, attempt_id=second.attempt_id) == second
    for status in statuses:
        status.stop_effects()
        assert status.mascot.animation.state() == QAbstractAnimation.State.Stopped
        assert status.focusPolicy() == Qt.FocusPolicy.NoFocus
        assert status.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)


def test_missing_audio_backend_is_optional(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    host = QWidget()
    qtbot.addWidget(host)
    audio = ChallengeAudio(host)
    monkeypatch.setitem(sys.modules, "PySide6.QtMultimedia", None)
    audio.play("success")
    assert not audio._unavailable  # 기본 무음은 장치나 백엔드에 접근하지 않는다.
    audio.configure(PresentationSettings(success_sound=True))
    audio.play("success")
    assert audio._unavailable
    audio.play("success")
    audio.stop()


def test_mascot_is_packaged_high_resolution_with_transparency() -> None:
    path = files("vim_key_trainer").joinpath("resources/game/bomb-mascot.png")
    image = QImage(str(path))
    assert not image.isNull()
    assert min(image.width(), image.height()) >= 1024
    assert image.hasAlphaChannel()
    assert image.pixelColor(0, 0).alpha() == 0


def test_offscreen_failed_fragment_still_renders_without_scrolling_engine(
    qtbot: QtBot,
) -> None:
    now = 0
    lesson = create_edit_problem(EditPracticeSpec("code_python", 12, 300))
    session = EditingSession(
        lesson, challenge=ChallengeOptions("bomb"), clock_ns=lambda: now
    )
    comparison = EditComparison()
    qtbot.addWidget(comparison)
    comparison.resize(850, 430)
    comparison.show_documents(session.engine.state, lesson.initial)
    comparison.show()
    qtbot.waitUntil(lambda: comparison.current_scroll.viewport().width() > 100)
    overlay = RepairEffects(comparison)
    session.submit(session.expected_token)
    now = 10**15
    session.check_deadline()
    comparison.show_current(session.engine.state)
    overlay.set_session(session)
    overlay.animation.stop()
    overlay._progress = 0.4
    bar = comparison.current_scroll.verticalScrollBar()
    bar.setValue(bar.maximum())
    offset = bar.value()
    snapshot = session.engine.snapshot()
    image = overlay.grab().toImage()
    # 실제 잘라내기 궤적이 뷰포트 안에 그려져야 한다. 원문은 스크롤 밖이다.
    assert any(
        image.pixelColor(x, y).name() == "#fb9d86"
        for y in range(image.height())
        for x in range(0, image.width(), 2)
    )
    assert bar.value() == offset
    assert session.engine.snapshot() == snapshot
    overlay.stop_effects()
