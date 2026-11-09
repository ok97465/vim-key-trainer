"""폭탄 도전의 시간 경계·복구·설정·재도전을 검증한다."""

from __future__ import annotations

# Standard library imports
from dataclasses import dataclass, replace
from pathlib import Path

# Third party imports
import pytest
from PySide6.QtCore import QRect, Qt
from pytestqt.qtbot import QtBot

# Local imports
from vim_key_trainer.content.edit_loader import get_edit_lesson
from vim_key_trainer.domain.challenge import ChallengeOptions
from vim_key_trainer.domain.editing import EditPracticeSpec
from vim_key_trainer.domain.preferences import PresentationSettings
from vim_key_trainer.domain.sessions import SessionState, StoredResult
from vim_key_trainer.engine import EditorState
from vim_key_trainer.services.edit_problem_factory import create_edit_problem
from vim_key_trainer.services.edit_session import EditingSession
from vim_key_trainer.services.result_repository import MemoryResultRepository
from vim_key_trainer.services.settings_repository import SettingsRepository
from vim_key_trainer.ui.main_window import MainWindow
from vim_key_trainer.ui.theme import STYLESHEET

from ._support import press_edit_key


@dataclass
class Clock:
    nanoseconds: int = 0

    def __call__(self) -> int:
        return self.nanoseconds

    def advance(self, seconds: float) -> None:
        self.nanoseconds += round(seconds * 1_000_000_000)


def setup(
    qtbot: QtBot,
    *,
    auto_repair: bool = True,
) -> tuple[MainWindow, EditingSession, Clock]:
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    window.activateWindow()
    qtbot.waitUntil(window.isActiveWindow)
    lesson = create_edit_problem(EditPracticeSpec("editing_numbers", 42, 12))
    window.prepare_editing_lesson(lesson)
    clock = Clock()
    options = ChallengeOptions("bomb", "normal", auto_repair)
    session = EditingSession(lesson, challenge=options, clock_ns=clock)
    window.edit_practice.prepare(lesson, prepared_session=session)
    qtbot.mouseClick(window.edit_practice.start_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(window.edit_practice.practice_input.hasFocus)
    return window, session, clock


def test_deadline_tick_redraws_atomic_repair_and_does_not_consume_next_key(
    qtbot: QtBot,
) -> None:
    window, session, clock = setup(qtbot)
    page = window.edit_practice
    clock.advance(100)
    page._tick()
    assert session.state == SessionState.READY
    assert session.timeout_count == 0
    token = session.expected_token
    assert token is not None
    press_edit_key(window, qtbot, token)
    limit = session.remaining_seconds
    assert limit is not None
    clock.advance(limit)
    page._tick()
    assert session.timeout_count == session.auto_repair_count == 1
    assert page.practice_input.editor_state == session.engine.state
    assert page.practice_input.recovery_marks
    assert session.key_count == 1
    assert session.active_segment_index == 1
    next_token = session.expected_token
    assert next_token is not None
    press_edit_key(window, qtbot, next_token)
    assert session.key_count == 2
    assert page.practice_input.hasFocus()
    assert page.challenge_status.testAttribute(
        Qt.WidgetAttribute.WA_TransparentForMouseEvents
    )


def test_timeout_keeps_failure_result_and_revenge_is_new_attempt(qtbot: QtBot) -> None:
    window, session, clock = setup(qtbot)
    page = window.edit_practice
    token = session.expected_token
    assert token is not None
    press_edit_key(window, qtbot, token)
    while session.state != SessionState.COMPLETED:
        remaining = session.remaining_seconds
        assert remaining is not None
        clock.advance(remaining)
        page._tick()
    assert page.stack.currentWidget() is page.result_page
    result = page.last_result
    assert result is not None and result.stars == 0
    assert "클리어" not in page.result_title.text()
    assert "시간 초과" in page.failure_examples.toPlainText()
    assert window.repository.completed_count == 0
    assert page.revenge_button.isVisible()
    count = len(window.repository.results)
    qtbot.mouseClick(page.revenge_button, Qt.MouseButton.LeftButton)
    fresh = page.session
    assert fresh is not None and fresh.attempt_id != session.attempt_id
    assert fresh.revenge_segments
    assert fresh.challenge == session.challenge
    assert len(window.repository.results) == count
    qtbot.mouseClick(page.start_button, Qt.MouseButton.LeftButton)
    while fresh.state != SessionState.COMPLETED:
        expected = fresh.expected_token
        assert expected is not None
        press_edit_key(window, qtbot, expected)
    assert fresh.result is not None and fresh.result.challenge is not None
    assert fresh.result.challenge.full_clear
    assert fresh.result.stars == 0
    assert window.repository.completed_count == 0


def test_no_repair_timeout_remains_manual_and_pause_excludes_wait(qtbot: QtBot) -> None:
    window, session, clock = setup(qtbot, auto_repair=False)
    page = window.edit_practice
    first = session.expected_token
    assert first is not None
    press_edit_key(window, qtbot, first)
    before = session.engine.state
    remaining = session.remaining_seconds
    assert remaining is not None
    clock.advance(remaining)
    qtbot.mouseClick(page.pause_button, Qt.MouseButton.LeftButton)
    assert session.state == SessionState.PAUSED
    assert session.timeout_count == 1 and session.auto_repair_count == 0
    assert session.engine.state == before
    elapsed = session.elapsed_seconds
    clock.advance(100)
    qtbot.mouseClick(page.pause_button, Qt.MouseButton.LeftButton)
    assert session.elapsed_seconds == elapsed
    assert page.practice_input.hasFocus()
    assert "직접 마무리" in page.challenge_status.countdown.text()
    expected = session.expected_token
    assert expected is not None
    press_edit_key(window, qtbot, expected)
    assert session.timeout_count == 1


def test_step_return_at_failed_repair_stops_timer_and_disables_resume(
    qtbot: QtBot,
) -> None:
    window, session, clock = setup(qtbot)
    page = window.edit_practice
    token = session.expected_token
    assert token is not None
    press_edit_key(window, qtbot, token)
    before = session.engine.snapshot()
    endpoint = session.segments[0].end_step
    session._prepared_steps[endpoint] = replace(
        session._prepared_steps[endpoint], state=EditorState(("wrong",))
    )
    remaining = session.remaining_seconds
    assert remaining is not None
    clock.advance(remaining)
    qtbot.mouseClick(page.return_button, Qt.MouseButton.LeftButton)
    assert session.state == SessionState.PAUSED and session.recovery_error
    assert session.engine.snapshot() == before
    assert not page.timer.isActive()
    assert not page.pause_button.isEnabled()
    assert page.pause_button.text() == "복구 오류"
    key_count = session.key_count
    press_edit_key(window, qtbot, token)
    assert session.key_count == key_count


def test_timer_reads_rival_records_only_when_comparison_conditions_change(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    window, session, _ = setup(qtbot)
    page = window.edit_practice
    reads = 0

    def read_results(_repository: MemoryResultRepository) -> tuple[StoredResult, ...]:
        nonlocal reads
        reads += 1
        return ()

    monkeypatch.setattr(MemoryResultRepository, "results", property(read_results))
    for _ in range(5):
        page._tick()
    assert reads == 0
    page.personal_record_check.setChecked(True)
    assert reads == 1
    for _ in range(5):
        page._tick()
    assert reads == 1
    page.pause()
    assert session.state == SessionState.PAUSED
    assert reads == 2


@pytest.mark.parametrize(
    "presentation",
    [
        PresentationSettings(),
        PresentationSettings(effects=False),
        PresentationSettings(reduced_motion=True),
    ],
)
def test_effect_choices_keep_same_input_document_and_score(
    qtbot: QtBot,
    presentation: PresentationSettings,
) -> None:
    window, session, _ = setup(qtbot)
    page = window.edit_practice
    page.configure_effects(presentation)
    while session.state != SessionState.COMPLETED:
        token = session.expected_token
        assert token is not None
        press_edit_key(window, qtbot, token)
    result = session.result
    assert result is not None and result.challenge is not None
    assert session.engine.state.lines == session.lesson.goal_lines
    assert result.key_count == session.lesson.baseline_keys
    assert result.challenge.score == 1500 * len(session.segments)
    assert result.stars == 3


def test_undo_exclusion_and_retry_preserve_conditions(qtbot: QtBot) -> None:
    window, session, _ = setup(qtbot)
    page = window.edit_practice
    page.retry()
    fresh = page.session
    assert fresh is not None and fresh.attempt_id != session.attempt_id
    assert fresh.challenge == session.challenge
    assert fresh.lesson.signature == session.lesson.signature
    page.prepare(get_edit_lesson("editing_undo"))
    assert page.session is not None and not page.session.bomb_enabled
    assert "지원하지" in page.challenge_combo.toolTip()
    assert not page.challenge_status.isVisible()


def test_settings_persist_without_mutating_running_attempt(
    qtbot: QtBot,
    tmp_path: Path,
) -> None:
    repository = SettingsRepository(tmp_path / "settings.json")
    window = MainWindow(settings_repository=repository)
    qtbot.addWidget(window)
    window.show()
    window.prepare_editing(
        "editing_numbers", EditPracticeSpec("editing_numbers", 42, 12)
    )
    page = window.edit_practice
    page.challenge_combo.setCurrentIndex(1)
    session = page.session
    assert session is not None and session.bomb_enabled
    page.start_practice()
    snapshot = session.engine.snapshot()
    options = session.challenge
    window.effects_check.setChecked(False)
    window.reduced_motion_check.setChecked(True)
    window.volume_slider.setValue(25)
    loaded = repository.load()
    assert loaded.presentation.effects is False
    assert loaded.presentation.reduced_motion is True
    assert loaded.presentation.volume == 0.25
    assert loaded.challenge == options
    assert session.challenge == options
    assert session.engine.snapshot() == snapshot


def test_documents_grow_and_small_work_area_keeps_controls_accessible(
    qtbot: QtBot,
) -> None:
    window = MainWindow()
    window.setStyleSheet(STYLESHEET)
    qtbot.addWidget(window)
    window.show()
    window.prepare_editing(
        "editing_numbers", EditPracticeSpec("editing_numbers", 42, 12)
    )
    page = window.edit_practice
    window.resize(1200, 800)
    qtbot.waitUntil(lambda: page.width() > 900)
    before = page.document_scroll.viewport().size()
    page.challenge_combo.setCurrentIndex(1)
    window.resize(1440, 900)
    qtbot.waitUntil(lambda: page.width() > 1100)
    after = page.document_scroll.viewport().size()
    assert after.width() >= before.width()
    assert after.height() >= before.height()
    window.fit_to_work_area(QRect(20, 30, 960, 680))
    qtbot.waitUntil(lambda: window.width() <= 960)
    qtbot.waitUntil(
        lambda: page.rect().contains(
            page.leave_button.mapTo(page, page.leave_button.rect().bottomRight())
        )
    )
    assert window.frameGeometry().top() >= 30
    for widget in (page.start_button, page.retry_button, page.leave_button):
        assert widget.isVisible()
        assert page.rect().contains(widget.mapTo(page, widget.rect().topLeft()))
        assert page.rect().contains(widget.mapTo(page, widget.rect().bottomRight()))
    qtbot.mouseClick(page.start_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(page.practice_input.hasFocus)
    assert page.document_scroll.viewport().height() >= 120
    work_area = QRect(20, 30, 760, 560)
    window.fit_to_work_area(work_area)
    qtbot.waitUntil(lambda: window.width() <= 760)
    qtbot.waitUntil(
        lambda: page.rect().contains(
            page.leave_button.mapTo(page, page.leave_button.rect().bottomRight())
        )
    )
    assert work_area.contains(window.frameGeometry())
    for widget in (page.pause_button, page.retry_button, page.leave_button):
        assert page.rect().contains(widget.mapTo(page, widget.rect().bottomRight()))


def test_document_effects_and_rival_toggle_leave_input_focus_and_scores(
    qtbot: QtBot,
) -> None:
    window, session, clock = setup(qtbot)
    page = window.edit_practice
    while session.direct_count == 0:
        token = session.expected_token
        assert token is not None
        press_edit_key(window, qtbot, token)
    assert page.practice_input.success_marks
    assert page.repair_effects.isVisible()
    assert "직접 해체 성공" in page.repair_effects.accessibleName()
    assert page.repair_effects.focusPolicy() == Qt.FocusPolicy.NoFocus
    assert page.repair_effects.testAttribute(
        Qt.WidgetAttribute.WA_TransparentForMouseEvents
    )
    before = session.engine.snapshot()
    score = session.direct_count
    rival_geometry = page.rival_status.geometry()
    qtbot.mouseClick(page.personal_record_check, Qt.MouseButton.LeftButton)
    assert session.state == SessionState.RUNNING
    assert session.engine.snapshot() == before
    assert session.direct_count == score
    assert page.practice_input.hasFocus()
    assert page.rival_status.geometry() == rival_geometry
    remaining = session.remaining_seconds
    assert remaining is not None
    clock.advance(remaining)
    page._tick()
    assert "시간 초과" in page.repair_effects.accessibleName()
    assert page.practice_input.hasFocus()
    key_count = session.key_count
    page._tick()
    assert session.timeout_count == 1 and session.key_count == key_count
    page.configure_effects(PresentationSettings(effects=False))
    assert not page.repair_effects.isVisible()


def test_settings_return_to_same_paused_attempt_and_apply_effects(qtbot: QtBot) -> None:
    window, session, _ = setup(qtbot)
    page = window.edit_practice
    token = session.expected_token
    assert token is not None
    press_edit_key(window, qtbot, token)
    snapshot = session.engine.snapshot()
    window.show_settings()
    assert session.state == SessionState.PAUSED
    window.effects_check.setChecked(False)
    window.return_from_settings()
    assert window.stack.currentWidget() is page
    assert page.session is session
    assert session.engine.snapshot() == snapshot
    assert session.state == SessionState.PAUSED
    assert page.pause_button.hasFocus()
    qtbot.mouseClick(page.pause_button, Qt.MouseButton.LeftButton)
    assert session.state == SessionState.RUNNING
    assert page.practice_input.hasFocus()
    assert page.presentation.effects is False


def test_daily_and_boss_buttons_fix_bonus_goals_and_preserve_activity(
    qtbot: QtBot,
) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    window.activateWindow()
    qtbot.waitUntil(window.isActiveWindow)
    window.show_editing()
    qtbot.mouseClick(window.editing_menu_page.daily_button, Qt.MouseButton.LeftButton)
    page = window.edit_practice
    daily = page.session
    assert daily is not None and daily.lesson.activity is not None
    assert daily.lesson.activity.kind == "daily"
    assert daily.lesson.activity.local_date is not None
    assert not page.new_problem_button.isEnabled()
    signature = daily.lesson.signature
    page.retry()
    assert page.session is not None and page.session.lesson.signature == signature
    window.show_editing()
    qtbot.mouseClick(window.editing_menu_page.boss_button, Qt.MouseButton.LeftButton)
    page.challenge_combo.setCurrentIndex(1)
    for check in page._bonus_checks.values():
        check.setChecked(True)
    boss = page.session
    assert boss is not None and boss.lesson.activity is not None
    assert boss.lesson.activity.kind == "boss"
    assert len(boss.lesson.activity.objectives) == 3
    page.start_practice()
    assert all(not check.isEnabled() for check in page._bonus_checks.values())
    while boss.state != SessionState.COMPLETED:
        token = boss.expected_token
        assert token is not None
        press_edit_key(window, qtbot, token)
    assert boss.result is not None
    assert boss.result.stars == 3 and boss.result.bonus_points == 1000
    assert "1,000점" in page.result_bonus.text()
    original_seed = boss.lesson.activity.seed
    page.new_problem()
    fresh = page.session
    assert fresh is not None and fresh.lesson.activity is not None
    assert fresh.lesson.activity.seed != original_seed
    assert fresh.lesson.activity.objectives == boss.lesson.activity.objectives
