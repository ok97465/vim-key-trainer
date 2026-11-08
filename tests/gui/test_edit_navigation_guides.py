"""문서 가이드의 괄호 이동·검색·치환을 실제 Qt 키로 완주한다."""

from __future__ import annotations

# Standard library imports
import sys
from dataclasses import replace

# Third party imports
import pytest
from PySide6.QtCore import Qt
from pytestqt.qtbot import QtBot

# Local imports
from vim_key_trainer.content.edit_loader import get_edit_lesson
from vim_key_trainer.domain.document_missions import DocumentPracticeSpec
from vim_key_trainer.domain.edit_builder import GuideBuilder
from vim_key_trainer.domain.edit_generator import generate_edit_lesson
from vim_key_trainer.domain.edit_templates import characters
from vim_key_trainer.domain.editing import EditPracticeSpec
from vim_key_trainer.domain.keys import KeyToken
from vim_key_trainer.domain.sessions import SessionState
from vim_key_trainer.engine import SUPPORTED_COMMANDS, EditEngine, EditorState
from vim_key_trainer.services.document_problem_factory import (
    create_random_document_problem,
)
from vim_key_trainer.ui.main_window import MainWindow
from vim_key_trainer.ui.qt_input import NormalizedKey


def press(window: MainWindow, qtbot: QtBot, token: KeyToken) -> None:
    widget = window.edit_practice.practice_input
    if token.kind == "char":
        qtbot.keyClicks(widget, token.value)
    elif token.kind == "special":
        qtbot.keyClick(
            widget,
            {
                "esc": Qt.Key.Key_Escape,
                "enter": Qt.Key.Key_Return,
                "backspace": Qt.Key.Key_Backspace,
            }[token.value],
        )
    else:
        modifier = (
            Qt.KeyboardModifier.MetaModifier
            if sys.platform == "darwin"
            else Qt.KeyboardModifier.ControlModifier
        )
        qtbot.keyClick(
            widget, Qt.Key(ord(token.value.rsplit("+", 1)[1].upper())), modifier
        )


def play_guide(window: MainWindow, qtbot: QtBot) -> set[str]:
    """한 과제를 완주하고 실제 키로 수행한 기술을 반환한다."""
    page = window.edit_practice
    session = page.session
    assert session is not None
    received: list[NormalizedKey] = []
    page.practice_input.key_received.connect(received.append)
    qtbot.mouseClick(page.start_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(page.practice_input.hasFocus)
    features: set[str] = set()

    for step in session.lesson.guide:
        for token in step.keys:
            before = session.engine.state
            press(window, qtbot, token)
            after = session.engine.state
            if (
                token == KeyToken("char", "%")
                and before.mode == "normal"
                and not before.pending
                and not before.command_line
            ):
                assert before.lines == after.lines
                assert (before.row, before.column) != (after.row, after.column)
                bracket = next(
                    char
                    for char in before.lines[before.row][before.column :]
                    if char in "()[]{}"
                )
                pairs = {"(": ")", ")": "(", "[": "]", "]": "[", "{": "}", "}": "{"}
                assert after.lines[after.row][after.column] == pairs[bracket]
                features.add("pair")
            if token == KeyToken("special", "enter"):
                assert not page.command_prompt.text() and not after.pending
                if before.command_line.startswith(("/", "?")):
                    assert before.lines == after.lines
                    assert (before.row, before.column) != (after.row, after.column)
                    features.add("search")
                elif before.command_line.startswith(":s"):
                    assert before.lines != after.lines
                    features.add("substitution")
            elif after.command_line:
                assert page.command_prompt.text() == after.command_line
        expected = step.expected
        assert (
            session.engine.state.lines,
            session.engine.state.row,
            session.engine.state.column,
            session.engine.state.mode,
            session.engine.state.pending,
        ) == (
            expected.lines,
            expected.row,
            expected.column,
            expected.mode,
            expected.pending,
        )

    assert session.state == SessionState.COMPLETED
    assert session.engine.state.lines == session.lesson.goal_lines
    assert session.key_count == session.lesson.baseline_keys
    assert sum(key.token is not None for key in received) == session.key_count
    assert session.result is not None and session.result.stars == 3
    assert page.stack.currentWidget() is page.result_page
    page.practice_input.key_received.disconnect(received.append)
    return features


@pytest.mark.parametrize("real_document", [False, True])
def test_document_guides_cover_pair_search_and_substitution_across_problems(
    qtbot: QtBot,
    real_document: bool,
) -> None:
    expected_features = {"pair", "substitution"}
    if not real_document:
        expected_features.add("search")
    covered: set[str] = set()
    cases: list[tuple[str, int]] = []
    lesson_ids = (
        ("mission_fmt_cpp", "mission_attrs") if real_document else ("editing_compound",)
    )
    for seed in range(48):
        for lesson_id in lesson_ids:
            lesson = (
                create_random_document_problem(DocumentPracticeSpec(lesson_id, seed))
                if real_document
                else generate_edit_lesson(EditPracticeSpec(lesson_id, seed))
            )
            engine = EditEngine(lesson.initial, lesson.allowed_commands)
            available: set[str] = set()
            for key in lesson.baseline:
                before = engine.state
                outcome = engine.submit(key)
                assert outcome.accepted
                if outcome.command == "%":
                    available.add("pair")
                elif outcome.command in {"/", "?"}:
                    available.add("search")
                elif outcome.command == ":" and before.command_line.startswith(":s"):
                    available.add("substitution")
            if available & (expected_features - covered):
                cases.append((lesson_id, seed))
                covered.update(available)
            if expected_features <= covered:
                break
        if expected_features <= covered:
            break
    assert expected_features <= covered
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    window.activateWindow()
    qtbot.waitUntil(window.isActiveWindow)
    features: set[str] = set()
    for lesson_id, seed in cases:
        if real_document:
            window.prepare_document_mission(lesson_id, seed=seed)
        else:
            window.prepare_editing(lesson_id, EditPracticeSpec(lesson_id, seed=seed))
        features.update(play_guide(window, qtbot))

    # 기술은 여러 과제에서 고루 연습한다. 한 과제에 모두 들어갈 필요는 없다.
    assert expected_features <= features


@pytest.mark.parametrize("command", ["bcw", "ciw", "cib", "da]"])
def test_word_and_block_object_guides_complete_through_qt_keys(
    qtbot: QtBot, command: str
) -> None:
    keys = characters(command)
    for seed in range(48):
        spec = EditPracticeSpec("editing_delete_word", seed, 40)
        lesson = generate_edit_lesson(spec)
        if any(step.keys[: len(keys)] == keys for step in lesson.guide):
            break
    else:
        pytest.fail(f"{command} 명령을 포함한 생성 과제가 없습니다.")
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    window.activateWindow()
    qtbot.waitUntil(window.isActiveWindow)
    window.prepare_editing(spec.profile_id, spec)
    session = window.edit_practice.session
    assert session is not None
    assert any(step.keys[: len(keys)] == keys for step in session.lesson.guide)
    play_guide(window, qtbot)


def test_generated_find_reuse_survives_returning_to_a_guide_step(qtbot: QtBot) -> None:
    initial = EditorState(("a,b,c,d",))
    guide = GuideBuilder(initial, SUPPORTED_COMMANDS)
    guide.record(characters("f,"), "첫 쉼표를 찾습니다.")
    guide.navigate(0, 3)
    guide.record(characters("r;"), "두 번째 쉼표를 세미콜론으로 바꿉니다.")
    guide.navigate(0, 5)
    guide.record(characters("r;"), "다음 쉼표도 바꿉니다.")
    assert guide.steps[1].keys == guide.steps[3].keys == characters(";")
    baseline = tuple(key for step in guide.steps for key in step.keys)
    lesson = replace(
        get_edit_lesson("editing_numbers"),
        initial=initial,
        goal_lines=("a,b;c;d",),
        goal_cursor=None,
        allowed_commands=SUPPORTED_COMMANDS,
        guide=tuple(guide.steps),
        baseline=baseline,
        baseline_keys=len(baseline),
    )
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    window.activateWindow()
    qtbot.waitUntil(window.isActiveWindow)
    window.prepare_editing_lesson(lesson)
    page = window.edit_practice
    session = page.session
    assert session is not None
    qtbot.mouseClick(page.start_button, Qt.MouseButton.LeftButton)
    for key in guide.steps[0].keys + guide.steps[1].keys:
        press(window, qtbot, key)
    assert session.step_index == 2
    assert session.engine.state.column == 3
    count = session.key_count
    qtbot.mouseClick(page.return_button, Qt.MouseButton.LeftButton)
    assert session.step_index == 1
    assert session.engine.state.column == 1
    assert session.engine.last_find == ("f", ",")
    assert session.key_count == count
    for step in guide.steps[1:]:
        for key in step.keys:
            press(window, qtbot, key)
    assert session.state == SessionState.COMPLETED
    assert session.engine.state.lines == lesson.goal_lines
    assert session.key_count == len(baseline) + 1
    assert session.step_returns == 1
