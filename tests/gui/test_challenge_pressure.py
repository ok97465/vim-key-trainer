"""위험·추격 연출이 세션을 바꾸지 않고 멈춤 상태를 따르는지 확인한다."""

# Third party imports
import pytest
from PySide6.QtCore import QAbstractAnimation, Qt
from PySide6.QtWidgets import QLineEdit, QVBoxLayout, QWidget
from pytestqt.qtbot import QtBot

# Local imports
from vim_key_trainer.domain.challenge import ChallengeOptions
from vim_key_trainer.domain.editing import EditPracticeSpec
from vim_key_trainer.domain.preferences import AppearanceSettings, PresentationSettings
from vim_key_trainer.domain.sessions import SessionState
from vim_key_trainer.services.activity_problem_factory import create_boss_problem
from vim_key_trainer.services.challenge_rival import RivalProgress
from vim_key_trainer.services.edit_problem_factory import create_edit_problem
from vim_key_trainer.services.edit_session import EditingSession
from vim_key_trainer.services.result_repository import MemoryResultRepository
from vim_key_trainer.ui.theme import STYLESHEET
from vim_key_trainer.ui.widgets.challenge_rival import ChallengeRivalStatus
from vim_key_trainer.ui.widgets.challenge_status import ChallengeStatus


def _running_status(
    qtbot: QtBot,
) -> tuple[QWidget, QLineEdit, ChallengeStatus, EditingSession, list[int]]:
    now = [0]
    session = EditingSession(
        create_edit_problem(EditPracticeSpec("editing_numbers", 42, 12)),
        challenge=ChallengeOptions("bomb"),
        clock_ns=lambda: now[0],
    )
    host = QWidget()
    qtbot.addWidget(host)
    layout = QVBoxLayout(host)
    focus = QLineEdit()
    layout.addWidget(focus)
    status = ChallengeStatus(host)
    layout.addWidget(status)
    host.resize(850, 150)
    host.show()
    host.activateWindow()
    focus.setFocus()
    qtbot.waitUntil(focus.hasFocus)
    token = session.expected_token
    assert token is not None
    session.submit(token)
    status.set_session(session)
    return host, focus, status, session, now


def test_pressure_approaches_bomb_without_advancing_or_changing_input(
    qtbot: QtBot,
) -> None:
    host, focus, status, session, now = _running_status(qtbot)
    limit = session.segment_limit_seconds
    assert limit is not None
    initial_ratio = status.fuse.ratio
    initial_pressure = status.pressure
    now[0] = round(limit * 0.85 * 1_000_000_000)
    snapshot = session.engine.snapshot()
    keys = session.key_count
    elapsed = session.elapsed_seconds
    with qtbot.waitSignal(status.pressure_changed, timeout=200):
        status.set_session(session)
    assert status.pressure > initial_pressure
    assert status.fuse.ratio < initial_ratio
    assert status.motion_timer.isActive()
    for _ in range(6):
        status._advance_motion()
    status.grab()
    assert session.engine.snapshot() == snapshot
    assert session.key_count == keys
    assert session.elapsed_seconds == elapsed
    assert session.state == SessionState.RUNNING
    assert focus.hasFocus()
    assert host.isVisible()


@pytest.mark.parametrize("action", ["pause", "disable", "reduce", "hide"])
def test_pressure_resources_stop_when_motion_is_not_visible(
    qtbot: QtBot, action: str
) -> None:
    host, _focus, status, session, now = _running_status(qtbot)
    limit = session.segment_limit_seconds
    assert limit is not None
    now[0] = round(limit * 0.85 * 1_000_000_000)
    status.set_session(session)
    assert status.motion_timer.isActive() and status.pressure > 0
    before = session.engine.snapshot()
    keys = session.key_count
    if action == "pause":
        session.pause()
        status.set_session(session)
    elif action == "disable":
        status.configure_effects(PresentationSettings(effects=False))
    elif action == "reduce":
        status.configure_effects(PresentationSettings(reduced_motion=True))
    else:
        status.hide()
    assert not status.motion_timer.isActive()
    assert not status.fuse.spark
    assert status.pressure > 0 if action == "reduce" else status.pressure == 0
    assert session.engine.snapshot() == before
    assert session.key_count == keys
    assert host.isVisible()


def test_hidden_mascot_releases_animation_without_replaying_success(
    qtbot: QtBot,
) -> None:
    _host, focus, status, session, _now = _running_status(qtbot)
    while session.direct_count < 1:
        token = session.expected_token
        assert token is not None
        session.submit(token)
    status.set_session(session)
    assert status.mascot.animation.state() == QAbstractAnimation.State.Running
    status.configure_appearance(AppearanceSettings(decorations=False))
    assert status.mascot.animation.state() == QAbstractAnimation.State.Stopped
    while session.direct_count < 2:
        token = session.expected_token
        assert token is not None
        session.submit(token)
    status.set_session(session)
    assert status.mascot.animation.state() == QAbstractAnimation.State.Stopped
    status.configure_appearance(AppearanceSettings())
    assert status.mascot.animation.state() == QAbstractAnimation.State.Stopped
    assert session.direct_count == 2
    assert focus.hasFocus()
    status.stop_effects()


def test_fuse_spark_moves_toward_left_bomb(qtbot: QtBot) -> None:
    host = QWidget()
    qtbot.addWidget(host)
    status = ChallengeStatus(host)
    fuse = status.fuse
    fuse.resize(300, 12)
    fuse.spark = True

    def spark_center(ratio: float) -> float:
        fuse.ratio = ratio
        image = fuse.grab().toImage()
        points = [
            x
            for x in range(image.width())
            for y in range(image.height())
            if image.pixelColor(x, y).name() == "#ffe4a2"
        ]
        assert points
        return sum(points) / len(points)

    assert spark_center(0.2) < spark_center(0.8)


def test_two_runners_keep_current_and_reference_progress_separate(qtbot: QtBot) -> None:
    status = ChallengeRivalStatus(MemoryResultRepository())
    qtbot.addWidget(status)
    status.resize(760, 40)
    status.show()
    near = RivalProgress(2, 4, 1, 0.45, 10, 12, -2, True)
    behind = RivalProgress(2, 4, 3, 0.85, 10, 12, -2, True)
    status.set_progress(near, enabled=True)
    first = status.race_track.grab().toImage()
    status.set_progress(behind, enabled=True)
    second = status.race_track.grab().toImage()
    # 개인 기록 주자만 움직여도 내 정산 진도는 같은 행에 그대로 남아야 한다.
    assert first != second
    scale = first.devicePixelRatio()
    own_top = round(2 * scale)
    own_bottom = round(15 * scale)
    assert first.copy(0, own_top, first.width(), own_bottom - own_top) == second.copy(
        0, own_top, second.width(), own_bottom - own_top
    )
    assert status.race_track.focusPolicy() == Qt.FocusPolicy.NoFocus
    assert status.race_track.testAttribute(
        Qt.WidgetAttribute.WA_TransparentForMouseEvents
    )


def test_boss_damage_uses_settled_segments_without_replaying_engine(
    qtbot: QtBot,
) -> None:
    session = EditingSession(
        create_boss_problem(42),
        challenge=ChallengeOptions("bomb"),
        clock_ns=lambda: 0,
    )
    status = ChallengeStatus()
    qtbot.addWidget(status)
    status.resize(850, 70)
    status.set_session(session)
    before = status.mascot.grab().toImage()
    while session.direct_count == 0:
        token = session.expected_token
        assert token is not None
        session.submit(token)
    snapshot = session.engine.snapshot()
    status.set_session(session)
    status.mascot.animation.stop()
    status.mascot.progress = 1.0
    after = status.mascot.grab().toImage()
    assert status.mascot.boss_progress is not None
    assert status.mascot.boss_progress > 0
    assert before != after
    assert session.engine.snapshot() == snapshot
    assert session.direct_count == 1
    status.stop_effects()


def test_narrow_status_contains_long_chain_and_close_call_without_overlap(
    qtbot: QtBot,
) -> None:
    now = [0]
    session = EditingSession(
        create_edit_problem(EditPracticeSpec("code_python", 12, 300)),
        challenge=ChallengeOptions("bomb"),
        clock_ns=lambda: now[0],
    )
    while session.direct_count < 9:
        token = session.expected_token
        assert token is not None
        session.submit(token)
    remaining = session.remaining_seconds
    assert remaining is not None
    now[0] += round((remaining - 0.5) * 1_000_000_000)
    while session.direct_count < 10:
        token = session.expected_token
        assert token is not None
        session.submit(token)
    host = QWidget()
    qtbot.addWidget(host)
    host.setStyleSheet(STYLESHEET)
    layout = QVBoxLayout(host)
    status = ChallengeStatus(host)
    layout.addWidget(status)
    # 실제 760px 창에서 사이드바·여백을 제외한 상태 줄의 폭이다.
    host.setFixedWidth(543)
    host.show()
    status.set_session(session)
    qtbot.waitUntil(
        lambda: (
            status.chain_badge.width() >= status.chain_badge.minimumSizeHint().width()
        )
    )
    assert status.width() <= 525
    for widget in (status.mascot, status.title, status.chain_badge, status.countdown):
        assert status.rect().contains(widget.geometry())
    assert status.title.geometry().right() < status.chain_badge.geometry().left()
    assert status.chain_badge.geometry().right() < status.countdown.geometry().left()
    assert status.chain_badge.width() >= status.chain_badge.minimumSizeHint().width()
    assert session.chain == 10
    assert session.state == SessionState.RUNNING
    status.stop_effects()
