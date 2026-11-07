"""문서 손상과 복원은 서비스 경계에서도 독립적으로 재생 검증한다."""

# Standard library imports
from dataclasses import replace

# Third party imports
import pytest

# Local imports
from vim_key_trainer.content.document_missions import list_document_missions
from vim_key_trainer.domain.document_missions import DocumentPracticeSpec
from vim_key_trainer.domain.keys import KeyToken
from vim_key_trainer.services import document_problem_factory


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
