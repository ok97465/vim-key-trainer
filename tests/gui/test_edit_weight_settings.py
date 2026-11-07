"""기술 비중 설정을 새 문제에 고정하고 재도전 조건을 보존한다."""

from __future__ import annotations

# Standard library imports
from collections.abc import Iterator

# Third party imports
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QScrollArea
from pytestqt.qtbot import QtBot

# Local imports
from vim_key_trainer.domain.edit_weights import EditTechniqueWeights
from vim_key_trainer.domain.editing import EditPracticeSpec
from vim_key_trainer.domain.sessions import SessionState
from vim_key_trainer.ui.main_window import MainWindow


@pytest.fixture
def window(qtbot: QtBot, monkeypatch: pytest.MonkeyPatch) -> Iterator[MainWindow]:
    monkeypatch.setattr("vim_key_trainer.ui.main_window.randbelow", lambda _: 17)
    widget = MainWindow()
    qtbot.addWidget(widget)
    widget.show()
    widget.activateWindow()
    qtbot.waitUntil(widget.isActiveWindow)
    yield widget
    widget.close()


def set_weights(window: MainWindow, **values: int) -> None:
    for technique, spin in window.edit_weight_spins.items():
        spin.setValue(values.get(technique, 0))


def test_weight_keyboard_input_updates_ratios_and_defaults_can_be_restored(
    window: MainWindow, qtbot: QtBot
) -> None:
    assert window.edit_weight_spins["movement"].value() > (
        window.edit_weight_spins["substitution"].value()
    )
    window.show_settings()
    scroll = window.settings_page.findChild(QScrollArea)
    assert scroll is not None
    spin = window.edit_weight_spins["movement"]
    scroll.ensureWidgetVisible(spin)
    spin.setFocus()
    spin.selectAll()
    qtbot.keyClicks(spin, "12")
    qtbot.keyClick(spin, Qt.Key.Key_Tab)
    assert spin.value() == 12
    expected = (
        100 * 12 / sum(item.value() for item in window.edit_weight_spins.values())
    )
    assert window._edit_weight_percentages["movement"].text() == f"{expected:.1f}%"
    scroll.ensureWidgetVisible(window.reset_edit_weights_button)
    qtbot.mouseClick(window.reset_edit_weights_button, Qt.MouseButton.LeftButton)
    assert window._edit_weights() == EditTechniqueWeights()
    assert window.settings_apply_button.isEnabled()


def test_invalid_all_zero_weights_leave_the_prepared_problem_untouched(
    window: MainWindow,
) -> None:
    window.prepare_editing("editing_compound")
    session = window.edit_practice.session
    assert session is not None
    set_weights(window)
    assert not window.settings_apply_button.isEnabled()
    assert "0" in window.edit_weight_note.text()
    window.prepare_editing("editing_compound")
    assert window.edit_practice.session is session
    assert "과제 열기 실패" in window.statusBar().currentMessage()
    window.edit_practice.new_problem()
    assert window.edit_practice.session is session
    assert "과제 열기 실패" in window.edit_practice.feedback.text()


def test_retry_and_length_change_preserve_weights_but_new_problem_uses_settings(
    window: MainWindow, qtbot: QtBot
) -> None:
    set_weights(window, movement=10, word=5)
    original_weights = window._edit_weights()
    window.prepare_editing("editing_compound")
    page = window.edit_practice
    original = page.session
    assert original is not None and original.lesson.practice_spec is not None
    spec = original.lesson.practice_spec
    assert spec.technique_weights == original_weights
    set_weights(window, search=4, substitution=1)
    assert original.lesson.practice_spec == spec
    qtbot.mouseClick(page.retry_button, Qt.MouseButton.LeftButton)
    retried = page.session
    assert retried is not None and retried is not original
    assert retried.lesson.signature == original.lesson.signature
    assert retried.lesson.practice_spec == spec
    page.length_combo.setCurrentIndex(page.length_combo.findData(40))
    resized = page.session
    assert resized is not None and resized.lesson.practice_spec is not None
    assert resized.lesson.practice_spec.seed == spec.seed
    assert resized.lesson.practice_spec.technique_weights == original_weights
    qtbot.mouseClick(page.new_problem_button, Qt.MouseButton.LeftButton)
    fresh = page.session
    assert fresh is not None and fresh.lesson.practice_spec is not None
    assert fresh.lesson.practice_spec.seed != spec.seed
    assert fresh.lesson.practice_spec.document_lines == 40
    assert fresh.lesson.practice_spec.technique_weights == window._edit_weights()


def test_explicit_reproduction_spec_is_not_replaced_by_current_weights(
    window: MainWindow,
) -> None:
    set_weights(window, substitution=20)
    spec = EditPracticeSpec("editing_compound", 3)
    window.prepare_editing(spec.profile_id, spec)
    session = window.edit_practice.session
    assert session is not None
    assert session.lesson.practice_spec == spec
    assert session.lesson.practice_spec.technique_weights is None


def test_actual_document_retry_preserves_weights_and_new_selection_reads_settings(
    window: MainWindow, qtbot: QtBot
) -> None:
    original_weights = window._edit_weights()
    window.prepare_document_mission("mission_flask", seed=4)
    page = window.edit_practice
    original = page.session
    assert original is not None and original.lesson.document_spec is not None
    assert original.lesson.document_spec.technique_weights == original_weights
    set_weights(window, word=10, movement=5)
    qtbot.mouseClick(page.retry_button, Qt.MouseButton.LeftButton)
    retried = page.session
    assert retried is not None
    assert retried.lesson.document_spec == original.lesson.document_spec
    page.document_combo.setCurrentIndex(page.document_combo.findData("mission_attrs"))
    selected = page.session
    assert selected is not None and selected.lesson.document_spec is not None
    assert selected.lesson.document_spec.mission_id == "mission_attrs"
    assert selected.lesson.document_spec.technique_weights == window._edit_weights()


def test_substitution_only_setting_drives_a_complete_qt_practice(
    window: MainWindow, qtbot: QtBot
) -> None:
    set_weights(window, substitution=1)
    window.prepare_editing("editing_compound")
    page = window.edit_practice
    session = page.session
    assert session is not None and session.lesson.practice_spec is not None
    assert session.lesson.practice_spec.technique_weights == window._edit_weights()
    substitutions = [step for step in session.lesson.guide if step.keys[0].value == ":"]
    assert len(substitutions) == 7
    qtbot.mouseClick(page.start_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(page.practice_input.hasFocus)
    for token in session.lesson.baseline:
        if token.kind == "char":
            qtbot.keyClicks(page.practice_input, token.value)
        else:
            assert token.value == "enter"
            qtbot.keyClick(page.practice_input, Qt.Key.Key_Return)
    assert session.state == SessionState.COMPLETED
    assert session.engine.state.lines == session.lesson.goal_lines
    assert session.result is not None and session.result.stars == 3
    assert session.key_count == session.lesson.baseline_keys
