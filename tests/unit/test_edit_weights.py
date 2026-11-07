"""기술 비중의 검증·재현 조건·구형 결과 호환성을 확인한다."""

# Standard library imports
import hashlib
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


def _legacy_digest(result: EditingSessionResult) -> str:
    spec = result.practice_spec
    key: tuple[object, ...] = (
        "editing",
        result.lesson_id,
        result.content_version,
        result.lesson_signature,
        result.baseline_version,
        result.baseline_keys,
        {
            "profile_id": spec.profile_id,
            "seed": spec.seed,
            "document_lines": spec.document_lines,
        }
        if spec is not None
        else None,
        result.generator_version,
        result.mode,
        result.guide_level,
        result.extra_hints,
        result.step_returns,
        result.pause_count > 0,
        result.game_rules_version,
    )
    document = result.document_spec
    if document is not None:
        key += (
            (
                "document",
                {
                    "mission_id": document.mission_id,
                    "seed": document.seed,
                    "change_count": document.change_count,
                },
            ),
        )
    payload = json.dumps(key, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


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
    assert json.loads(encoded)["schema_version"] == 3
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


@pytest.mark.parametrize("schema_version", [1, 2])
def test_legacy_results_keep_their_original_comparison_digest_without_weights(
    unweighted_result: EditingSessionResult, schema_version: int
) -> None:
    if schema_version == 1 and unweighted_result.document_spec is not None:
        pytest.skip("결과 v1에는 실제 문서 생성 조건이 없습니다.")
    payload = json.loads(encode_result(unweighted_result))
    assert "technique_weights" not in payload["data"][_spec_field(unweighted_result)]
    payload["schema_version"] = schema_version
    if schema_version == 1:
        payload["data"].pop("document_spec")
    restored = decode_result(json.dumps(payload))
    assert restored == unweighted_result
    assert comparison_digest(restored) == _legacy_digest(unweighted_result)
    assert restored.lesson_signature == unweighted_result.lesson_signature


@pytest.mark.parametrize(
    ("document", "expected"),
    [
        (False, "b0368769738faf4862da5572c42243c4360d75f9aef7658da597cfcf582668e0"),
        (True, "8e2bac2bfd5f8f10ec813dbcfce7d07ecc995975e1644488ad692cf755b7d86d"),
    ],
)
def test_missing_weights_keep_the_pre_weight_lesson_signatures(
    document: bool, expected: str
) -> None:
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
    assert lesson.signature == expected
    field = "document_spec" if document else "practice_spec"
    spec = getattr(lesson, field)
    weighted = replace(spec, technique_weights=EditTechniqueWeights())
    assert replace(lesson, **{field: weighted}).signature != expected


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


@pytest.mark.parametrize("schema_version", [1, 2])
def test_legacy_schema_cannot_claim_weighted_conditions(
    unweighted_result: EditingSessionResult, schema_version: int
) -> None:
    payload = json.loads(encode_result(unweighted_result))
    payload["schema_version"] = schema_version
    if schema_version == 1:
        payload["data"].pop("document_spec")
        if unweighted_result.document_spec is not None:
            payload["data"]["practice_spec"] = {
                "profile_id": "editing_compound",
                "seed": 81,
                "document_lines": 24,
            }
    field = "practice_spec" if schema_version == 1 else _spec_field(unweighted_result)
    payload["data"][field]["technique_weights"] = asdict(EditTechniqueWeights())
    with pytest.raises(ValueError, match="버전 3"):
        decode_result(json.dumps(payload))
