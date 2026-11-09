"""원문·손상 seed·기술 비중을 기록하고 재현·비교 조건으로 검증한다."""

# Standard library imports
import json
from dataclasses import asdict, replace
from pathlib import Path
from uuid import uuid4

# Third party imports
import pytest

# Local imports
from vim_key_trainer.content.code_corpus import load_code_sources
from vim_key_trainer.content.document_missions import create_document_lesson
from vim_key_trainer.content.edit_loader import get_edit_lesson
from vim_key_trainer.domain.decorations import summarize_decorations
from vim_key_trainer.domain.document_missions import DocumentPracticeSpec
from vim_key_trainer.domain.edit_weights import EDIT_TECHNIQUES, EditTechniqueWeights
from vim_key_trainer.domain.editing import EditMode, EditPracticeSpec
from vim_key_trainer.domain.sessions import EditingSessionResult, InputResult
from vim_key_trainer.services.document_problem_factory import (
    create_random_document_problem,
)
from vim_key_trainer.services.edit_problem_factory import create_edit_problem
from vim_key_trainer.services.edit_session import EditingSession
from vim_key_trainer.services.recorded_practice import reconstruct_recorded_lesson
from vim_key_trainer.services.result_codec import (
    comparison_digest,
    decode_result,
    encode_result,
)
from vim_key_trainer.services.result_repository import MemoryResultRepository
from vim_key_trainer.services.sqlite_repository import SqliteResultRepository
from vim_key_trainer.services.storage_version import STORAGE_VERSION


@pytest.fixture(scope="module")
def selected_result() -> EditingSessionResult:
    source = next(
        entry for entry in load_code_sources() if entry.source.language == "python"
    )
    spec = EditPracticeSpec("code_python", 91, 300, code_source_id=source.source.id)
    lesson = create_edit_problem(spec)
    session = EditingSession(lesson, "free", clock_ns=lambda: 0)
    for key in lesson.baseline:
        assert session.submit(key) == InputResult.ACCEPTED
    assert session.result is not None
    return session.result


def test_selected_source_round_trips_through_json_and_database(
    selected_result: EditingSessionResult, tmp_path: Path
) -> None:
    payload = encode_result(selected_result)
    data = json.loads(payload)
    assert data["schema_version"] == STORAGE_VERSION
    spec = selected_result.practice_spec
    assert spec is not None
    assert data["data"]["practice_spec"]["code_source_id"] == spec.code_source_id
    assert selected_result.code_source_id == spec.code_source_id
    assert data["data"]["code_source_id"] == spec.code_source_id
    assert decode_result(payload) == selected_result
    path = tmp_path / "selected.sqlite3"
    repository = SqliteResultRepository(path)
    assert repository.save(selected_result)
    repository.close()
    reopened = SqliteResultRepository(path)
    assert reopened.load_issues == ()
    assert reopened.results == (selected_result,)
    assert reopened.best_for(selected_result) == selected_result
    assert not reopened.save(selected_result)
    reopened.close()


def test_document_selection_has_a_distinct_comparison_key(
    selected_result: EditingSessionResult,
) -> None:
    spec = selected_result.practice_spec
    assert spec is not None
    versions = (
        selected_result,
        replace(selected_result, practice_spec=replace(spec, code_source_id=None)),
        replace(
            selected_result,
            practice_spec=replace(spec, code_source_id="other_source"),
        ),
    )
    assert len({comparison_digest(result) for result in versions}) == 3
    random_data = json.loads(encode_result(versions[1]))
    assert random_data["data"]["practice_spec"]["code_source_id"] is None


def test_random_code_source_is_recorded_and_repeated_sources_share_unlock_credit(
    selected_result: EditingSessionResult,
) -> None:
    lesson = create_edit_problem(EditPracticeSpec("code_python", 14, 300))
    assert lesson.code_excerpt is not None
    session = EditingSession(lesson, "free", clock_ns=lambda: 0)
    for key in lesson.baseline:
        session.submit(key)
    result = session.result
    assert result is not None and result.practice_spec is not None
    assert result.practice_spec.code_source_id is None
    assert result.code_source_id == lesson.code_excerpt.source.id
    assert decode_result(encode_result(result)) == result
    assert result.code_source_id != selected_result.code_source_id
    assert reconstruct_recorded_lesson(result).signature == lesson.signature
    with pytest.raises(ValueError, match="문제 서명·원문"):
        reconstruct_recorded_lesson(replace(result, code_source_id="other_source"))
    selected_again = replace(
        result,
        attempt_id=str(uuid4()),
        practice_spec=replace(
            result.practice_spec, code_source_id=result.code_source_id
        ),
    )
    assert (
        summarize_decorations(
            (selected_result, result, selected_again)
        ).completed_lessons
        == 2
    )


@pytest.mark.parametrize("source_id", [None, "../source", "other_source"])
def test_saved_source_must_match_the_fixed_selection(
    selected_result: EditingSessionResult, source_id: str | None
) -> None:
    with pytest.raises(ValueError, match="원문"):
        decode_result(encode_result(replace(selected_result, code_source_id=source_id)))


def test_non_code_lesson_cannot_claim_a_source(
    selected_result: EditingSessionResult,
) -> None:
    changed = replace(
        selected_result,
        lesson_id="editing_numbers",
        practice_spec=EditPracticeSpec("editing_numbers", 14),
    )
    with pytest.raises(ValueError, match="원문"):
        decode_result(encode_result(changed))


def finished_document(
    spec: DocumentPracticeSpec | None = None,
    mode: EditMode = "free",
) -> EditingSessionResult:
    lesson = create_document_lesson(spec.mission_id if spec else "mission_flask")
    if spec is not None:
        lesson = replace(lesson, document_spec=spec, generator_version=1)
    session = EditingSession(lesson, mode)
    for key in lesson.baseline:
        assert session.submit(key) == InputResult.ACCEPTED
    assert session.result is not None
    return session.result


@pytest.mark.parametrize(
    "arguments",
    [
        {"mission_id": "editing_numbers", "seed": 0},
        {"mission_id": "mission_", "seed": 0},
        {"mission_id": "mission_flask", "seed": -1},
        {"mission_id": "mission_flask", "seed": 2**32},
        {"mission_id": "mission_flask", "seed": True},
        {"mission_id": "mission_flask", "seed": "1"},
        {"mission_id": "mission_flask", "seed": 0, "change_count": 2},
        {"mission_id": "mission_flask", "seed": 0, "change_count": 9},
        {"mission_id": "mission_flask", "seed": 0, "change_count": True},
        {"mission_id": "mission_flask", "seed": 0, "change_count": 5.0},
    ],
)
def test_document_practice_conditions_reject_invalid_or_coerced_values(
    arguments: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        DocumentPracticeSpec(**arguments)  # type: ignore[arg-type]


@pytest.mark.parametrize("change_count", [7, 8])
@pytest.mark.parametrize("mode", ["guided", "free"])
def test_document_metadata_survives_session_json_and_database_reopen(
    tmp_path: Path,
    change_count: int,
    mode: EditMode,
) -> None:
    spec = DocumentPracticeSpec("mission_flask", 2**32 - 1, change_count)
    result = finished_document(spec, mode)
    assert result.document_spec == spec
    assert result.practice_spec is None
    encoded = encode_result(result)
    assert json.loads(encoded)["schema_version"] == STORAGE_VERSION
    assert decode_result(encoded) == result
    path = tmp_path / "records.sqlite3"
    repository = SqliteResultRepository(path)
    assert repository.save(result)
    repository.close()
    reopened = SqliteResultRepository(path)
    assert reopened.load_issues == ()
    assert reopened.results == (result,)
    assert reopened.best_for(result) == result
    assert not reopened.save(result)
    reopened.close()


def test_random_document_seeds_and_change_counts_compare_separately() -> None:
    repository = MemoryResultRepository()
    result = finished_document(DocumentPracticeSpec("mission_flask", 1, 7))
    repository.save(result)
    for spec in (
        DocumentPracticeSpec("mission_flask", 2, 7),
        DocumentPracticeSpec("mission_flask", 1, 8),
    ):
        changed = replace(
            result,
            attempt_id=str(uuid4()),
            document_spec=spec,
            elapsed_seconds=result.elapsed_seconds + 100,
        )
        assert comparison_digest(changed) != comparison_digest(result)
        assert repository.save(changed)
        assert repository.best_for(changed) == changed
    assert repository.best_for(result) == result


def test_document_spec_is_included_in_lesson_signature() -> None:
    lesson = create_document_lesson("mission_flask")
    assert lesson.document_spec is None
    expected = lesson.signature
    with_spec = replace(lesson, document_spec=DocumentPracticeSpec(lesson.id, 1))
    assert with_spec.signature != expected
    assert (
        with_spec.signature
        != replace(
            with_spec,
            document_spec=DocumentPracticeSpec(lesson.id, 2),
        ).signature
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [("seed", True), ("seed", -1), ("change_count", 2), ("change_count", "5")],
)
def test_json_rejects_invalid_nested_document_conditions(
    field: str, value: object
) -> None:
    payload = json.loads(
        encode_result(finished_document(DocumentPracticeSpec("mission_flask", 7)))
    )
    payload["data"]["document_spec"][field] = value
    with pytest.raises(ValueError):
        decode_result(json.dumps(payload))


def test_document_condition_requires_matching_mission() -> None:
    result = finished_document(DocumentPracticeSpec("mission_flask", 7))
    for invalid in (
        replace(result, lesson_id="mission_click"),
        replace(result, practice_spec=EditPracticeSpec("editing_numbers", 0)),
    ):
        with pytest.raises(ValueError, match="생성 조건"):
            decode_result(encode_result(invalid))


def test_actual_random_document_result_keeps_reproduction_conditions_after_reopen(
    tmp_path: Path,
) -> None:
    spec = DocumentPracticeSpec("mission_flask_python", 2**32 - 1, 8)
    lesson = create_random_document_problem(spec)
    session = EditingSession(lesson, "free")
    for key in lesson.baseline:
        assert session.submit(key) == InputResult.ACCEPTED
    assert session.result is not None
    path = tmp_path / "actual_random.sqlite3"
    repository = SqliteResultRepository(path)
    assert repository.save(session.result)
    repository.close()
    reopened = SqliteResultRepository(path)
    assert reopened.load_issues == ()
    assert reopened.results == (session.result,)
    restored = reopened.results[0]
    assert isinstance(restored, EditingSessionResult)
    assert restored.document_spec == spec
    assert restored.lesson_signature == lesson.signature
    assert reopened.best_for(session.result) == session.result
    reopened.close()


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
