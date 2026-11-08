"""손상 seed 기록과 결과 JSON 버전 간 호환성을 검증한다."""

# Standard library imports
import hashlib
import json
import sqlite3
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
from vim_key_trainer.services.edit_problem_factory import create_edit_problem
from vim_key_trainer.services.edit_session import EditingSession
from vim_key_trainer.services.result_codec import (
    RESULT_SCHEMA_VERSION,
    comparison_digest,
    decode_result,
    encode_result,
)
from vim_key_trainer.services.result_repository import MemoryResultRepository
from vim_key_trainer.services.sqlite_repository import SqliteResultRepository


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


def legacy_comparison_digest(result: EditingSessionResult) -> str:
    """v1 필드 배열을 명시해 기존 DB 인덱스 해시를 독립적으로 재구성한다."""
    spec = result.practice_spec
    key = (
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
    payload = json.dumps(key, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


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


@pytest.mark.parametrize("change_count", [3, 5, 8])
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
    assert result.generator_version == 1
    encoded = encode_result(result)
    assert json.loads(encoded)["schema_version"] == RESULT_SCHEMA_VERSION == 4
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


@pytest.mark.parametrize("generated", [False, True])
@pytest.mark.parametrize("schema_version", [1, 2, 3])
def test_legacy_database_records_keep_comparison_index_and_original_payload(
    tmp_path: Path,
    generated: bool,
    schema_version: int,
) -> None:
    if generated:
        lesson = create_edit_problem(EditPracticeSpec("editing_numbers", 81, 24))
        session = EditingSession(lesson, "free")
        for key in lesson.baseline:
            session.submit(key)
        assert session.result is not None
        result = session.result
    else:
        result = finished_document()
    assert result.document_spec is None
    old_digest = legacy_comparison_digest(result)
    assert comparison_digest(result) == old_digest
    old_payload = json.loads(encode_result(result))
    old_payload["schema_version"] = schema_version
    if schema_version == 1:
        old_payload["data"].pop("document_spec")
    serialized = json.dumps(old_payload)
    assert decode_result(serialized) == result
    path = tmp_path / "legacy.sqlite3"
    repository = SqliteResultRepository(path)
    repository.save(result)
    repository.close()
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE attempts SET result_json=?, comparison_key=?",
            (serialized, old_digest),
        )
        connection.execute(
            "UPDATE comparison_bests SET comparison_key=?", (old_digest,)
        )
    reopened = SqliteResultRepository(path)
    assert reopened.load_issues == ()
    assert reopened.results == (result,)
    assert reopened.best_for(result) == result
    assert (
        reopened.best_edit_stars(result.lesson_id, result.content_version, "free") == 3
    )
    assert not reopened.save(result)
    reopened.close()
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 1
        assert (
            connection.execute("SELECT result_json FROM attempts").fetchone()[0]
            == serialized
        )


def test_random_document_seeds_and_change_counts_compare_separately() -> None:
    repository = MemoryResultRepository()
    result = finished_document(DocumentPracticeSpec("mission_flask", 1, 5))
    repository.save(result)
    for spec in (
        DocumentPracticeSpec("mission_flask", 2, 5),
        DocumentPracticeSpec("mission_flask", 1, 3),
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


def test_document_spec_changes_lesson_signature_without_changing_legacy_signature() -> (
    None
):
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


def test_json_version_one_cannot_claim_new_document_generation_fields() -> None:
    payload = json.loads(
        encode_result(finished_document(DocumentPracticeSpec("mission_flask", 7)))
    )
    payload["schema_version"] = 1
    with pytest.raises(ValueError, match="버전 1"):
        decode_result(json.dumps(payload))


def test_document_condition_requires_matching_mission_and_generator_version() -> None:
    result = finished_document(DocumentPracticeSpec("mission_flask", 7))
    for invalid in (
        replace(result, lesson_id="mission_click"),
        replace(result, generator_version=0),
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
    assert restored.generator_version == lesson.generator_version
    assert reopened.best_for(session.result) == session.result
    reopened.close()
