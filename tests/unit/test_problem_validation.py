"""생성 서비스의 재현 조건·손상·기준 풀이와 실제 완료를 검증한다."""

# Standard library imports
from dataclasses import replace

# Third party imports
import pytest

# Local imports
from vim_key_trainer.content.document_missions import list_document_missions
from vim_key_trainer.content.edit_loader import EditContentError
from vim_key_trainer.domain.document_missions import DocumentPracticeSpec
from vim_key_trainer.domain.edit_generator import list_edit_profiles
from vim_key_trainer.domain.editing import EditMode, EditPracticeSpec
from vim_key_trainer.domain.keys import KeyToken
from vim_key_trainer.domain.sessions import InputResult, SessionState
from vim_key_trainer.services import document_problem_factory, edit_problem_factory
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
    assert session.result.lesson_signature == lesson.signature
    assert session.result.key_count == len(keys)


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


def test_factory_verifies_original_damage_and_exact_repair() -> None:
    spec = DocumentPracticeSpec(list_document_missions()[0].id, 42, 7)
    plan = document_problem_factory.create_document_corruption(spec)
    lesson = document_problem_factory.create_random_document_problem(spec)
    assert lesson == plan.lesson
    assert lesson.document_spec == spec
    assert lesson.baseline_keys == len(lesson.baseline)


def test_factory_rejects_corruption_log_that_does_not_create_initial_document(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = DocumentPracticeSpec(list_document_missions()[0].id, 1)
    plan = document_problem_factory.create_document_corruption(spec)
    invalid = replace(plan, corruption_tokens=(KeyToken("char", "h"),))
    monkeypatch.setattr(
        document_problem_factory, "generate_document_problem", lambda *args: invalid
    )
    with pytest.raises(ValueError, match="초기 문서"):
        document_problem_factory.create_document_corruption(spec)


def test_factory_rejects_bad_repair_baseline_from_generator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = DocumentPracticeSpec(list_document_missions()[0].id, 1)
    plan = document_problem_factory.create_document_corruption(spec)
    invalid = replace(plan, lesson=replace(plan.lesson, baseline=(), baseline_keys=0))
    monkeypatch.setattr(
        document_problem_factory, "generate_document_problem", lambda *args: invalid
    )
    with pytest.raises(ValueError, match="baseline"):
        document_problem_factory.create_document_corruption(spec)


def test_factory_does_not_mutate_original_catalog_document() -> None:
    mission = list_document_missions()[0]
    original = mission.goal_lines
    document_problem_factory.create_random_document_problem(
        DocumentPracticeSpec(mission.id, 22)
    )
    assert mission.goal_lines is original
    assert mission == list_document_missions()[0]


@pytest.mark.parametrize("field", ["goal_lines", "document_spec", "generator_version"])
def test_factory_rejects_wrong_source_or_reproduction_metadata(
    field: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = DocumentPracticeSpec(list_document_missions()[0].id, 9)
    plan = document_problem_factory.create_document_corruption(spec)
    values = {
        "goal_lines": ("changed source",),
        "document_spec": replace(spec, seed=10),
        "generator_version": 99,
    }
    invalid = replace(plan, lesson=replace(plan.lesson, **{field: values[field]}))
    monkeypatch.setattr(
        document_problem_factory, "generate_document_problem", lambda *args: invalid
    )
    with pytest.raises(ValueError, match="재현 조건"):
        document_problem_factory.create_document_corruption(spec)
