"""손상 seed와 문제 생성 조건의 기록을 검증한다."""

# Standard library imports
import json
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

# Third party imports
import pytest

# Local imports
from vim_key_trainer.content.document_missions import create_document_lesson
from vim_key_trainer.domain.document_missions import DocumentPracticeSpec
from vim_key_trainer.domain.editing import EditMode, EditPracticeSpec
from vim_key_trainer.domain.sessions import EditingSessionResult, InputResult
from vim_key_trainer.services.document_problem_factory import (
    create_random_document_problem,
)
from vim_key_trainer.services.edit_session import EditingSession
from vim_key_trainer.services.result_codec import (
    comparison_digest,
    decode_result,
    encode_result,
)
from vim_key_trainer.services.result_repository import MemoryResultRepository
from vim_key_trainer.services.sqlite_repository import SqliteResultRepository
from vim_key_trainer.services.storage_version import STORAGE_VERSION


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
    assert replace(lesson, document_spec=None).signature == expected
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
