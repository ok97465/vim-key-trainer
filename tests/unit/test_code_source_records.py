"""선택한 코드 원문의 결과 저장과 비교 조건을 검증한다."""

# Standard library imports
import json
from dataclasses import replace
from pathlib import Path

# Third party imports
import pytest

# Local imports
from vim_key_trainer.content.code_corpus import load_code_sources
from vim_key_trainer.domain.editing import EditPracticeSpec
from vim_key_trainer.domain.sessions import EditingSessionResult, InputResult
from vim_key_trainer.services.edit_problem_factory import create_edit_problem
from vim_key_trainer.services.edit_session import EditingSession
from vim_key_trainer.services.result_codec import (
    comparison_digest,
    decode_result,
    encode_result,
)
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


@pytest.mark.parametrize("version", [0, STORAGE_VERSION - 1, STORAGE_VERSION + 1])
def test_result_requires_the_current_storage_version(
    selected_result: EditingSessionResult, version: int
) -> None:
    payload = json.loads(encode_result(selected_result))
    payload["schema_version"] = version
    with pytest.raises(ValueError, match="스키마 버전"):
        decode_result(json.dumps(payload))
