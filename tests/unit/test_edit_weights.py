"""기술 비중의 검증·재현 조건·결과 저장을 확인한다."""

# Standard library imports
import json
from dataclasses import asdict, replace
from pathlib import Path
from uuid import uuid4

# Third party imports
import pytest

# Local imports
from vim_key_trainer.content.edit_loader import get_edit_lesson
from vim_key_trainer.domain.document_missions import DocumentPracticeSpec
from vim_key_trainer.domain.edit_weights import EDIT_TECHNIQUES, EditTechniqueWeights
from vim_key_trainer.domain.editing import EditPracticeSpec
from vim_key_trainer.domain.sessions import EditingSessionResult, InputResult
from vim_key_trainer.services.document_problem_factory import (
    create_random_document_problem,
)
from vim_key_trainer.services.edit_problem_factory import create_edit_problem
from vim_key_trainer.services.edit_session import EditingSession
from vim_key_trainer.services.result_codec import (
    comparison_digest,
    decode_result,
    encode_result,
)
from vim_key_trainer.services.result_repository import MemoryResultRepository
from vim_key_trainer.services.sqlite_repository import SqliteResultRepository
from vim_key_trainer.services.storage_version import STORAGE_VERSION


def _finished_result(
    document: bool, weights: EditTechniqueWeights | None = None
) -> EditingSessionResult:
    lesson = (
        create_random_document_problem(
            DocumentPracticeSpec("mission_flask_python", 81, technique_weights=weights)
        )
        if document
        else create_edit_problem(
            EditPracticeSpec("editing_compound", 81, technique_weights=weights)
        )
    )
    session = EditingSession(lesson, "free")
    for key in lesson.baseline:
        assert session.submit(key) == InputResult.ACCEPTED
    assert session.result is not None
    return session.result


@pytest.fixture(scope="module", params=[False, True], ids=["technique", "document"])
def unweighted_result(request: pytest.FixtureRequest) -> EditingSessionResult:
    return _finished_result(request.param)


def _spec_field(result: EditingSessionResult) -> str:
    return "document_spec" if result.document_spec is not None else "practice_spec"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("movement", True),
        ("word", -1),
        ("search", 21),
        ("copy", 1.5),
        ("visual", "3"),
        ("repeat", None),
    ],
)
def test_weights_reject_invalid_values_without_coercion(
    field: str, value: object
) -> None:
    with pytest.raises(ValueError):
        EditTechniqueWeights(**{field: value})  # type: ignore[arg-type]


def test_weights_require_at_least_one_enabled_technique() -> None:
    with pytest.raises(ValueError):
        EditTechniqueWeights(**dict.fromkeys((name for name, _ in EDIT_TECHNIQUES), 0))
    assert EditTechniqueWeights(movement=0, substitution=20).substitution == 20


@pytest.mark.parametrize("document", [False, True])
@pytest.mark.parametrize("value", [True, {}, [], "uniform", 3])
def test_specifications_require_a_validated_weight_object(
    document: bool, value: object
) -> None:
    with pytest.raises(ValueError):
        if document:
            DocumentPracticeSpec("mission_flask", 1, technique_weights=value)  # type: ignore[arg-type]
        else:
            EditPracticeSpec("editing_compound", 1, technique_weights=value)  # type: ignore[arg-type]


@pytest.mark.parametrize("document", [False, True])
def test_weighted_generation_conditions_round_trip_through_json_and_database(
    tmp_path: Path, document: bool
) -> None:
    weights = EditTechniqueWeights(movement=9, word=8, insertion=4, substitution=2)
    result = _finished_result(document, weights)
    spec = result.document_spec if document else result.practice_spec
    assert spec is not None and spec.technique_weights == weights
    encoded = encode_result(result)
    assert json.loads(encoded)["schema_version"] == STORAGE_VERSION
    assert decode_result(encoded) == result
    path = tmp_path / "weights.sqlite3"
    repository = SqliteResultRepository(path)
    assert repository.save(result)
    repository.close()
    reopened = SqliteResultRepository(path)
    assert reopened.load_issues == ()
    assert reopened.results == (result,)
    assert reopened.best_for(result) == result
    reopened.close()


def test_changing_only_weights_separates_personal_record_comparisons(
    unweighted_result: EditingSessionResult,
) -> None:
    field = _spec_field(unweighted_result)
    spec = getattr(unweighted_result, field)
    assert spec is not None
    repository = MemoryResultRepository()
    versions = []
    for weights in (
        None,
        EditTechniqueWeights(),
        EditTechniqueWeights(search=20),
    ):
        changed = replace(
            unweighted_result,
            attempt_id=str(uuid4()),
            **{field: replace(spec, technique_weights=weights)},
        )
        assert repository.save(changed)
        assert repository.best_for(changed) == changed
        versions.append(changed)
    assert len({comparison_digest(result) for result in versions}) == 3
    assert all(repository.best_for(result) == result for result in versions)


@pytest.mark.parametrize("document", [False, True])
def test_weights_are_included_in_the_lesson_signature(document: bool) -> None:
    lesson = get_edit_lesson("editing_numbers")
    if document:
        lesson = replace(
            lesson,
            id="mission_example",
            document_spec=DocumentPracticeSpec("mission_example", 81),
            generator_version=1,
        )
    else:
        lesson = replace(
            lesson,
            practice_spec=EditPracticeSpec("editing_numbers", 81),
            generator_version=1,
        )
    field = "document_spec" if document else "practice_spec"
    spec = getattr(lesson, field)
    weighted = replace(spec, technique_weights=EditTechniqueWeights())
    assert replace(lesson, **{field: weighted}).signature != lesson.signature


@pytest.mark.parametrize(
    "weights",
    [
        {"movement": True},
        {"word": -1},
        {"search": 21},
        dict.fromkeys((name for name, _ in EDIT_TECHNIQUES), 0),
        True,
        [],
        "uniform",
        {"unknown": 1},
        asdict(EditTechniqueWeights()) | {"unknown": 1},
    ],
)
def test_result_json_rejects_invalid_or_unknown_nested_weights(
    unweighted_result: EditingSessionResult, weights: object
) -> None:
    payload = json.loads(encode_result(unweighted_result))
    payload["data"][_spec_field(unweighted_result)]["technique_weights"] = weights
    with pytest.raises(ValueError):
        decode_result(json.dumps(payload))
