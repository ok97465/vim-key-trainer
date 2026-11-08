"""생성 문제의 검증 경계와 시도별 재현 조건 전달을 확인한다."""

# Standard library imports
from dataclasses import replace

# Third party imports
import pytest

# Local imports
from vim_key_trainer.content.code_corpus import load_code_sources
from vim_key_trainer.content.edit_loader import EditContentError, get_edit_lesson
from vim_key_trainer.domain.edit_generator import (
    CODE_SOURCE_SELECTION_VERSION,
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


@pytest.mark.parametrize(
    "profile_id,line_count", [("editing_numbers", 24), ("code_json", 60)]
)
def test_local_document_problem_does_not_require_code_corpus(
    monkeypatch: pytest.MonkeyPatch, profile_id: str, line_count: int
) -> None:
    def unavailable() -> None:
        pytest.fail("일반 문서·JSON 연습에서 코드 코퍼스를 읽었습니다.")

    monkeypatch.setattr(edit_problem_factory, "load_code_sources", unavailable)
    assert (
        create_edit_problem(EditPracticeSpec(profile_id, 78, line_count)).code_excerpt
        is None
    )


@pytest.mark.parametrize("field", ["source", "range", "lines"])
def test_factory_rejects_code_whose_provenance_disagrees_with_goal(
    field: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = EditPracticeSpec("code_python", seed=78, document_lines=300)
    valid = create_edit_problem(spec)
    excerpt = valid.code_excerpt
    assert excerpt is not None
    if field == "source":
        excerpt = replace(excerpt, source=replace(excerpt.source, sha256="0" * 64))
    elif field == "range":
        excerpt = replace(excerpt, start_line=excerpt.start_line + 1)
    else:
        excerpt = replace(excerpt, lines=("changed",) + excerpt.lines[1:])
    monkeypatch.setattr(
        edit_problem_factory,
        "generate_edit_lesson",
        lambda _spec, **_kwargs: replace(valid, code_excerpt=excerpt),
    )
    with pytest.raises(ValueError, match="출처"):
        create_edit_problem(spec)


def test_factory_rejects_another_registered_source_for_fixed_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    random_spec = EditPracticeSpec("code_python", seed=78, document_lines=300)
    random_lesson = create_edit_problem(random_spec)
    assert random_lesson.code_excerpt is not None
    other_source = next(
        entry.source.id
        for entry in load_code_sources()
        if entry.source.language == "python"
        and entry.source.id != random_lesson.code_excerpt.source.id
    )
    fixed_spec = replace(random_spec, code_source_id=other_source)
    wrong = replace(
        random_lesson,
        practice_spec=fixed_spec,
        generator_version=CODE_SOURCE_SELECTION_VERSION,
    )
    monkeypatch.setattr(
        edit_problem_factory, "generate_edit_lesson", lambda _spec, **_kwargs: wrong
    )
    with pytest.raises(ValueError, match="출처"):
        create_edit_problem(fixed_spec)
