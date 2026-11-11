"""마지막 사용자 선택과 과제별 제약·복습 조건을 구분해 저장한다."""

# Standard library imports
from pathlib import Path

# Third party imports
import pytest
from pytestqt.qtbot import QtBot

# Local imports
from vim_key_trainer.content.edit_loader import get_edit_lesson
from vim_key_trainer.domain.challenge import ChallengeDifficulty, ChallengeOptions
from vim_key_trainer.domain.editing import EditMode, EditPracticeSpec
from vim_key_trainer.domain.sessions import SessionState
from vim_key_trainer.services.settings_repository import AppSettings, SettingsRepository
from vim_key_trainer.ui.main_window import MainWindow


def _window(qtbot: QtBot, path: Path) -> MainWindow:
    window = MainWindow(settings_repository=SettingsRepository(path))
    qtbot.addWidget(window)
    window.show()
    window.activateWindow()
    qtbot.waitUntil(window.isActiveWindow)
    return window


def _prepare(window: MainWindow, profile: str = "editing_numbers") -> None:
    window.prepare_editing(profile, EditPracticeSpec(profile, 42, 12))


@pytest.mark.parametrize("mode", ["guided", "free"])
@pytest.mark.parametrize("difficulty", ["relaxed", "normal", "challenge"])
def test_last_selection_returns_after_app_restart_before_practice_starts(
    qtbot: QtBot,
    tmp_path: Path,
    mode: EditMode,
    difficulty: ChallengeDifficulty,
) -> None:
    path = tmp_path / "settings.json"
    first = _window(qtbot, path)
    _prepare(first)
    page = first.edit_practice
    page.mode_combo.setCurrentIndex(page.mode_combo.findData(mode))
    page.challenge_combo.setCurrentIndex(page.challenge_combo.findData("bomb"))
    page.difficulty_combo.setCurrentIndex(page.difficulty_combo.findData(difficulty))
    stored = SettingsRepository(path).load()
    assert stored.edit_mode == mode
    assert stored.challenge == ChallengeOptions("bomb", difficulty, True)
    assert page.session is not None and page.session.state == SessionState.READY
    first.close()

    second = _window(qtbot, path)
    _prepare(second, "editing_append")
    restored = second.edit_practice
    session = restored.session
    assert session is not None and session.mode == mode
    assert restored.mode_combo.currentData() == mode
    assert restored.challenge_combo.currentData() == "bomb"
    assert restored.difficulty_combo.currentData() == difficulty
    assert restored.default_challenge == stored.challenge
    assert session.challenge.auto_repair is (mode == "guided")
    assert not second.repository.results


def test_normal_bomb_and_mode_switches_keep_user_preferences_across_categories(
    qtbot: QtBot, tmp_path: Path
) -> None:
    path = tmp_path / "settings.json"
    window = _window(qtbot, path)
    _prepare(window)
    page = window.edit_practice
    page.mode_combo.setCurrentIndex(1)
    page.challenge_combo.setCurrentIndex(1)
    page.difficulty_combo.setCurrentIndex(page.difficulty_combo.findData("challenge"))
    page.challenge_combo.setCurrentIndex(0)
    assert SettingsRepository(path).load().challenge == ChallengeOptions(
        "normal", "challenge", True
    )
    window.show_numbers()
    _prepare(window, "editing_append")
    assert page.session is not None and page.session.mode == "free"
    assert page.challenge_combo.currentData() == "normal"
    assert page.difficulty_combo.currentData() == "challenge"
    page.challenge_combo.setCurrentIndex(1)
    assert page.session is not None
    assert page.session.challenge == ChallengeOptions("bomb", "challenge", False)
    page.mode_combo.setCurrentIndex(0)
    assert page.session is not None and page.session.mode == "guided"
    assert page.session.challenge == ChallengeOptions("bomb", "challenge", True)
    stored = SettingsRepository(path).load()
    assert stored.edit_mode == "guided"
    assert stored.challenge == page.session.challenge


def test_guide_only_lesson_does_not_overwrite_remembered_free_bomb_choice(
    qtbot: QtBot, tmp_path: Path
) -> None:
    path = tmp_path / "settings.json"
    repository = SettingsRepository(path)
    preference = AppSettings(
        edit_mode="free", challenge=ChallengeOptions("bomb", "relaxed")
    )
    assert repository.save(preference)
    window = _window(qtbot, path)
    _prepare(window, "editing_undo")
    page = window.edit_practice
    session = page.session
    assert session is not None and session.mode == "guided"
    assert not session.bomb_enabled
    assert page.default_mode == "free"
    assert page.default_challenge == preference.challenge
    assert page.mode_combo.currentData() == "guided"
    assert page.mode_combo.toolTip()
    page.document_font_spin.setValue(16)
    stored = repository.load()
    assert stored.edit_mode == "free" and stored.challenge == preference.challenge
    _prepare(window)
    assert page.session is not None and page.session.mode == "free"
    assert page.session.challenge == ChallengeOptions("bomb", "relaxed", False)
    assert not page.mode_combo.toolTip()


def test_explicit_review_and_retry_conditions_do_not_change_default_preferences(
    qtbot: QtBot, tmp_path: Path
) -> None:
    path = tmp_path / "settings.json"
    repository = SettingsRepository(path)
    preference = AppSettings(
        edit_mode="free", challenge=ChallengeOptions("bomb", "challenge")
    )
    assert repository.save(preference)
    window = _window(qtbot, path)
    page = window.edit_practice
    explicit = ChallengeOptions("normal", "relaxed", False)
    page.prepare(get_edit_lesson("editing_numbers"), "guided", challenge=explicit)
    page.document_font_spin.setValue(15)
    page.retry()
    assert page.session is not None and page.session.mode == "guided"
    assert page.session.challenge == explicit
    assert page.default_mode == "free"
    stored = repository.load()
    assert stored.edit_mode == "free" and stored.challenge == preference.challenge
    _prepare(window)
    assert page.session is not None and page.session.mode == "free"
    assert page.session.challenge == ChallengeOptions("bomb", "challenge", False)


def test_failed_problem_generation_keeps_current_session_and_saved_preferences(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "settings.json"
    window = _window(qtbot, path)
    _prepare(window)
    page = window.edit_practice
    page.mode_combo.setCurrentIndex(1)
    page.challenge_combo.setCurrentIndex(1)
    page.difficulty_combo.setCurrentIndex(page.difficulty_combo.findData("relaxed"))
    session = page.session
    raw = path.read_bytes()

    def fail(spec: EditPracticeSpec) -> None:
        raise ValueError("generation failed")

    monkeypatch.setattr("vim_key_trainer.ui.main_window.create_edit_problem", fail)
    _prepare(window, "editing_append")
    assert page.session is session
    assert path.read_bytes() == raw
    assert page.default_mode == "free"
    assert page.default_challenge == ChallengeOptions("bomb", "relaxed", True)
