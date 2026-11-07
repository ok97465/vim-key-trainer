"""생성 문제의 검증 경계와 시도별 재현 조건 전달을 확인한다."""

# Standard library imports
from dataclasses import replace

# Third party imports
import pytest

# Local imports
from vim_key_trainer.content.edit_loader import EditContentError, get_edit_lesson
from vim_key_trainer.domain.edit_generator import (
    EDIT_GENERATOR_VERSION,
    list_edit_profiles,
)
from vim_key_trainer.domain.editing import EditMode, EditPracticeSpec
from vim_key_trainer.domain.sessions import InputResult, SessionState
from vim_key_trainer.services import edit_problem_factory
from vim_key_trainer.services.edit_problem_factory import create_edit_problem
from vim_key_trainer.services.edit_session import EditingSession


@pytest.mark.parametrize(
    ("profile_id", "mode"),
    [
        (profile.id, mode)
        for profile in list_edit_profiles()
        for mode in ("guided", "free")
        if profile.free_enabled or mode == "guided"
    ],
)
def test_generated_problem_completes_and_records_reproduction_conditions(
    profile_id: str,
    mode: EditMode,
) -> None:
    spec = EditPracticeSpec(profile_id, seed=847, document_lines=24)
    lesson = create_edit_problem(spec)
    session = EditingSession(lesson, mode)
    keys = (
        tuple(key for step in lesson.guide for key in step.keys)
        if mode == "guided"
        else lesson.baseline
    )
    for key in keys:
        assert session.submit(key) == InputResult.ACCEPTED
    assert session.state == SessionState.COMPLETED
    assert session.result is not None
    assert session.result.practice_spec == spec
    assert session.result.generator_version == EDIT_GENERATOR_VERSION
    assert session.result.lesson_signature == lesson.signature
    assert session.result.key_count == len(keys)


def test_same_generated_problem_can_be_replayed_as_a_new_attempt() -> None:
    spec = EditPracticeSpec("editing_compound", seed=913, document_lines=40)
    first = create_edit_problem(spec)
    second = create_edit_problem(spec)
    assert first == second
    assert first.signature == second.signature
    assert EditingSession(first).attempt_id != EditingSession(second).attempt_id


def test_factory_rejects_generated_content_that_does_not_match_requested_conditions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = EditPracticeSpec("editing_numbers", seed=78)
    valid = create_edit_problem(spec)
    monkeypatch.setattr(
        edit_problem_factory,
        "generate_edit_lesson",
        lambda _spec: replace(valid, practice_spec=replace(spec, seed=79)),
    )
    with pytest.raises(ValueError, match="재현 조건"):
        create_edit_problem(spec)


def test_factory_replays_baseline_instead_of_trusting_generator_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = EditPracticeSpec("editing_numbers", seed=78)
    valid = create_edit_problem(spec)
    monkeypatch.setattr(
        edit_problem_factory,
        "generate_edit_lesson",
        lambda _spec: replace(valid, baseline=valid.baseline[:-1]),
    )
    with pytest.raises(EditContentError):
        create_edit_problem(spec)


def test_reproduction_metadata_changes_comparison_signature() -> None:
    spec = EditPracticeSpec("editing_numbers", seed=78)
    lesson = create_edit_problem(spec)
    assert (
        lesson.signature
        != replace(lesson, practice_spec=replace(spec, seed=79)).signature
    )
    assert (
        lesson.signature
        != replace(lesson, practice_spec=replace(spec, document_lines=40)).signature
    )
    assert (
        lesson.signature
        != replace(lesson, generator_version=lesson.generator_version + 1).signature
    )


def test_introductory_lesson_keeps_its_previous_signature() -> None:
    lesson = get_edit_lesson("editing_numbers")
    assert lesson.practice_spec is None
    assert lesson.generator_version == 0
    assert (
        lesson.signature
        == "e5764227eb962c9db1a67f94ae7b552160558b21f3d0898f9d1c0d59c4c96162"
    )
