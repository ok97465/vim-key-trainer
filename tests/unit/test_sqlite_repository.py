"""임시 DB로 재실행·원자성·중복 저장·스키마와 오류 복구를 검증한다."""

# Standard library imports
import json
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

# Third party imports
import pytest

# Local imports
from vim_key_trainer.content.edit_loader import get_edit_lesson
from vim_key_trainer.domain.commands import CommandSpec
from vim_key_trainer.domain.document_missions import DocumentPracticeSpec
from vim_key_trainer.domain.editing import EditPracticeSpec
from vim_key_trainer.domain.exercises import PracticeSpec
from vim_key_trainer.domain.keys import KeyToken
from vim_key_trainer.domain.sessions import (
    CommandSessionResult,
    CommandTiming,
    EditingSessionResult,
    SessionResult,
    SessionState,
    StoredResult,
)
from vim_key_trainer.services.edit_problem_factory import create_edit_problem
from vim_key_trainer.services.edit_session import EditingSession
from vim_key_trainer.services.result_codec import (
    RESULT_SCHEMA_VERSION,
    decode_result,
    encode_result,
)
from vim_key_trainer.services.session_service import PracticeSession
from vim_key_trainer.services.sqlite_repository import (
    DATABASE_SCHEMA_VERSION,
    MissionRecord,
    SourceDocumentRecord,
    SqliteResultRepository,
)


def symbols(*, mistakes: int = 0, seconds: float = 3) -> SessionResult:
    clock = [0]
    session = PracticeSession(PracticeSpec(target_length=2), clock_ns=lambda: clock[0])
    for _ in range(mistakes):
        session.submit(KeyToken("char", "a"))
    session.submit(KeyToken("char", session.target[0]))
    clock[0] = round(seconds * 1_000_000_000)
    session.submit(KeyToken("char", session.target[1]))
    assert session.result is not None
    return session.result


def commands() -> CommandSessionResult:
    return CommandSessionResult(
        attempt_id=str(uuid4()),
        spec=CommandSpec("test_commands", seed=44),
        target=(KeyToken("char", "h"), KeyToken("chord", "ctrl+r")),
        state=SessionState.COMPLETED,
        correct=2,
        incorrect=1,
        elapsed_seconds=4,
        accuracy=200 / 3,
        cpm=30,
        max_combo=2,
        stars=1,
        errors={"h": 1},
        keypad_errors=0,
        pause_count=1,
        reaction_times=(("h", 0.2),),
        lesson_version=2,
        lesson_signature="command-condition",
        item_ids=("one",),
        display_count=10,
        completed_commands=1,
        command_times=(("one", 4.0),),
        commands_per_minute=15,
        generator_version=3,
        transcript_digest="digest",
        command_samples=(CommandTiming("one", "h<C-r>", 4.0),),
    )


def editing() -> EditingSessionResult:
    session = EditingSession(get_edit_lesson("editing_numbers"))
    for step in session.lesson.guide:
        for key in step.keys:
            session.submit(key)
    assert session.result is not None
    return session.result


@pytest.mark.parametrize("make_result", [symbols, commands, editing])
def test_result_json_and_database_roundtrip_all_practice_types(
    tmp_path: Path,
    make_result: object,
) -> None:
    assert callable(make_result)
    result: StoredResult = make_result()
    assert decode_result(encode_result(result)) == result
    path = tmp_path / "training.sqlite3"
    repository = SqliteResultRepository(path)
    assert repository.save(result)
    assert repository.persistence_error is None
    repository.close()
    reopened = SqliteResultRepository(path)
    assert reopened.results == (result,)
    assert reopened.best_for(result) == result
    assert reopened.completed_count == 1
    assert not reopened.save(result)
    reopened.close()


def test_save_updates_attempt_progress_and_best_in_same_transaction(
    tmp_path: Path,
) -> None:
    path = tmp_path / "training.sqlite3"
    repository = SqliteResultRepository(
        path, clock=lambda: datetime(2026, 1, 2, tzinfo=UTC)
    )
    first = symbols(mistakes=1)
    accurate = symbols(seconds=7)
    assert repository.save(first)
    assert repository.save(accurate)
    assert not repository.save(accurate)
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM attempts").fetchone()[0] == 2
        assert connection.execute(
            "SELECT completed_count,best_stars FROM lesson_progress"
        ).fetchone() == (2, 3)
        assert (
            connection.execute("SELECT attempt_id FROM comparison_bests").fetchone()[0]
            == accurate.attempt_id
        )
        assert (
            connection.execute(
                "SELECT recorded_at_utc FROM attempts LIMIT 1"
            ).fetchone()[0]
            == "2026-01-02T00:00:00+00:00"
        )
    repository.close()
    reopened = SqliteResultRepository(path)
    assert reopened.best_for(first) == accurate
    assert reopened.best_stars("numbers") == 3
    reopened.close()


def test_aborted_attempt_persists_without_progress_or_rewards(tmp_path: Path) -> None:
    repository = SqliteResultRepository(tmp_path / "training.sqlite3")
    result = replace(symbols(), state=SessionState.ABORTED, stars=0)
    assert not repository.save(result)
    repository.close()
    reopened = SqliteResultRepository(tmp_path / "training.sqlite3")
    assert reopened.results == (result,)
    assert reopened.completed_count == 0
    assert reopened.best_for(result) is None
    assert reopened.best_stars("numbers") == 0
    with sqlite3.connect(reopened.path) as connection:
        assert (
            connection.execute("SELECT COUNT(*) FROM lesson_progress").fetchone()[0]
            == 0
        )
    reopened.close()


def test_generated_free_result_keeps_seed_length_versions_and_nonapplicable_stats(
    tmp_path: Path,
) -> None:
    spec = EditPracticeSpec("editing_compound", seed=2**32 - 1, document_lines=40)
    lesson = create_edit_problem(spec)
    session = EditingSession(lesson, "free")
    for key in lesson.baseline:
        session.submit(key)
    assert session.result is not None
    repository = SqliteResultRepository(tmp_path / "training.sqlite3")
    repository.save(session.result)
    repository.close()
    reopened = SqliteResultRepository(tmp_path / "training.sqlite3")
    result = reopened.results[0]
    assert isinstance(result, EditingSessionResult)
    assert result.practice_spec == spec
    assert result.content_version == lesson.content_version
    assert result.generator_version == lesson.generator_version
    assert (
        result.correct
        is result.incorrect
        is result.accuracy
        is result.max_combo
        is None
    )
    assert reopened.best_edit_stars(lesson.id, lesson.content_version, "free") == 3
    assert reopened.best_edit_stars(lesson.id, lesson.content_version, "guided") == 0
    reopened.close()


def test_storage_failure_retains_result_and_retry_cannot_double_award(
    tmp_path: Path,
) -> None:
    path = tmp_path / "training.sqlite3"
    repository = SqliteResultRepository(path)
    with sqlite3.connect(path) as connection:
        connection.execute("""CREATE TRIGGER reject_progress
            BEFORE INSERT ON lesson_progress
            BEGIN SELECT RAISE(ABORT, 'test storage failure'); END""")
    result = symbols()
    assert repository.save(result)
    assert repository.results == (result,)
    assert repository.best_for(result) == result
    assert repository.completed_count == 1
    assert repository.persistence_error is not None
    assert repository.pending_count == 1
    assert not repository.save(result)
    with sqlite3.connect(path) as connection:
        # 앞선 attempt INSERT도 진행도 실패와 함께 롤백되어야 한다.
        assert connection.execute("SELECT COUNT(*) FROM attempts").fetchone()[0] == 0
        assert (
            connection.execute("SELECT COUNT(*) FROM comparison_bests").fetchone()[0]
            == 0
        )
        connection.execute("DROP TRIGGER reject_progress")
    assert repository.retry_pending() == 1
    assert repository.retry_pending() == 0
    assert repository.persistence_error is None
    repository.close()
    reopened = SqliteResultRepository(path)
    assert reopened.results == (result,)
    assert reopened.completed_count == 1
    with sqlite3.connect(path) as connection:
        assert (
            connection.execute(
                "SELECT completed_count FROM lesson_progress"
            ).fetchone()[0]
            == 1
        )
    reopened.close()


def test_pending_better_result_wins_when_retried_after_another_save(
    tmp_path: Path,
) -> None:
    path = tmp_path / "training.sqlite3"
    repository = SqliteResultRepository(path)
    with sqlite3.connect(path) as connection:
        connection.execute("""CREATE TRIGGER reject_attempt BEFORE INSERT ON attempts
            BEGIN SELECT RAISE(ABORT, 'retry later'); END""")
    best = symbols(seconds=1)
    repository.save(best)
    with sqlite3.connect(path) as connection:
        connection.execute("DROP TRIGGER reject_attempt")
    worse = symbols(seconds=4)
    repository.save(worse)
    assert repository.best_for(worse) == best
    assert repository.retry_pending() == 1
    repository.close()
    reopened = SqliteResultRepository(path)
    assert reopened.best_for(worse) == best
    assert reopened.completed_count == 2
    reopened.close()


def test_future_database_version_is_rejected_without_modification(
    tmp_path: Path,
) -> None:
    path = tmp_path / "future.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE valuable(note TEXT)")
        connection.execute("INSERT INTO valuable VALUES ('preserve')")
        connection.execute(f"PRAGMA user_version={DATABASE_SCHEMA_VERSION + 1}")
    with pytest.raises(ValueError, match="새로운"):
        SqliteResultRepository(path)
    with sqlite3.connect(path) as connection:
        assert (
            connection.execute("SELECT note FROM valuable").fetchone()[0] == "preserve"
        )
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 2
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE name='attempts'"
            ).fetchone()[0]
            == 0
        )


def test_schema_creation_preserves_unrelated_existing_data(tmp_path: Path) -> None:
    path = tmp_path / "version_zero.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE marker(value TEXT)")
        connection.execute("INSERT INTO marker VALUES ('original')")
    repository = SqliteResultRepository(path)
    repository.close()
    with sqlite3.connect(path) as connection:
        assert (
            connection.execute("PRAGMA user_version").fetchone()[0]
            == DATABASE_SCHEMA_VERSION
        )
        assert (
            connection.execute("SELECT value FROM marker").fetchone()[0] == "original"
        )


def test_failed_schema_migration_rolls_back_all_new_tables(tmp_path: Path) -> None:
    path = tmp_path / "partial.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE attempts(original TEXT)")
        connection.execute("INSERT INTO attempts VALUES ('preserve')")
    with pytest.raises(sqlite3.DatabaseError):
        SqliteResultRepository(path)
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 0
        assert (
            connection.execute("SELECT original FROM attempts").fetchone()[0]
            == "preserve"
        )
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE name='source_documents'"
            ).fetchone()[0]
            == 0
        )


@pytest.mark.parametrize(
    "change", ["future_version", "unknown_field", "bad_number", "active_state"]
)
def test_invalid_result_json_is_rejected(change: str) -> None:
    payload = json.loads(encode_result(symbols()))
    if change == "future_version":
        payload["schema_version"] = RESULT_SCHEMA_VERSION + 1
    elif change == "unknown_field":
        payload["data"]["executable"] = "never execute"
    elif change == "bad_number":
        payload["data"]["correct"] = "2"
    else:
        payload["data"]["state"] = "running"
    with pytest.raises(ValueError):
        decode_result(json.dumps(payload))


@pytest.mark.parametrize("field", ["spec", "target", "command_samples"])
def test_command_result_rejects_unknown_fields_in_nested_records(field: str) -> None:
    payload = json.loads(encode_result(commands()))
    nested = payload["data"][field]
    if isinstance(nested, list):
        nested = nested[0]
    nested["unknown_setting"] = 1
    with pytest.raises(ValueError, match="알 수 없는 필드"):
        decode_result(json.dumps(payload))


@pytest.mark.parametrize("document", [False, True])
def test_edit_result_rejects_unknown_fields_in_generation_conditions(
    document: bool,
) -> None:
    result = editing()
    if document:
        result = replace(
            result,
            lesson_id="mission_test",
            document_spec=DocumentPracticeSpec("mission_test", 7),
            generator_version=1,
        )
    else:
        result = replace(
            result,
            practice_spec=EditPracticeSpec(result.lesson_id, 7),
            generator_version=1,
        )
    payload = json.loads(encode_result(result))
    field = "document_spec" if document else "practice_spec"
    payload["data"][field]["unknown_setting"] = 1
    with pytest.raises(ValueError, match="알 수 없는 필드"):
        decode_result(json.dumps(payload))


@pytest.mark.parametrize("make_result", [symbols, commands, editing])
def test_result_json_version_one_still_reads_existing_practice_records(
    make_result: object,
) -> None:
    assert callable(make_result)
    result: StoredResult = make_result()
    payload = json.loads(encode_result(result))
    payload["schema_version"] = 1
    payload["data"].pop("document_spec", None)
    assert decode_result(json.dumps(payload)) == result


@pytest.mark.parametrize(
    ("field", "invalid"),
    [
        ("max_combo", -1),
        ("max_combo", 999),
        ("extra_hints", -1),
        ("step_returns", -1),
        ("content_version", -1),
        ("content_version", 0),
        ("baseline_version", -1),
        ("game_rules_version", 0),
        ("generator_version", -1),
        ("accuracy", 0),
        ("accuracy", None),
    ],
)
def test_guided_result_rejects_inconsistent_counts_versions_and_accuracy(
    field: str,
    invalid: object,
) -> None:
    payload = json.loads(encode_result(editing()))
    payload["data"][field] = invalid
    with pytest.raises(ValueError):
        decode_result(json.dumps(payload))


def test_accuracy_consistency_allows_only_roundoff_tolerance() -> None:
    payload = json.loads(encode_result(editing()))
    payload["data"]["accuracy"] -= 1e-10
    decoded = decode_result(json.dumps(payload))
    assert decoded.accuracy == pytest.approx(100)


@pytest.mark.parametrize(
    ("column", "changed"),
    [
        ("result_kind", "wrong-kind"),
        ("state", "aborted"),
        ("lesson_id", "other_lesson"),
        ("content_version", -1),
        ("mode", "wrong-mode"),
        ("comparison_key", "wrong-digest"),
    ],
)
def test_saved_index_mismatch_is_quarantined_without_deleting_attempt(
    tmp_path: Path,
    column: str,
    changed: object,
) -> None:
    path = tmp_path / "training.sqlite3"
    repository = SqliteResultRepository(path)
    result = editing()
    repository.save(result)
    repository.close()
    with sqlite3.connect(path) as connection:
        # column은 위 고정 매개변수 목록으로 한정한다.
        connection.execute(f"UPDATE attempts SET {column}=?", (changed,))
    reopened = SqliteResultRepository(path)
    assert reopened.results == ()
    assert reopened.completed_count == 0
    assert reopened.best_for(result) is None
    assert reopened.load_issues and "인덱스" in reopened.load_issues[0]
    reopened.close()
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM attempts").fetchone()[0] == 1


def test_quarantined_best_cannot_block_a_later_valid_result(tmp_path: Path) -> None:
    path = tmp_path / "training.sqlite3"
    repository = SqliteResultRepository(path)
    corrupted = symbols(seconds=1)
    repository.save(corrupted)
    repository.close()
    with sqlite3.connect(path) as connection:
        connection.execute("UPDATE attempts SET mode='wrong'")
    reopened = SqliteResultRepository(path)
    valid = symbols(seconds=5)
    assert reopened.save(valid)
    assert reopened.persistence_error is None
    reopened.close()
    final = SqliteResultRepository(path)
    assert final.results == (valid,)
    assert final.best_for(valid) == valid
    assert final.completed_count == 1
    final.close()


@pytest.mark.parametrize(
    "wrong_condition", ["aborted", "other_seed", "missing_attempt", "missing_entry"]
)
@pytest.mark.parametrize("seconds", [0, 3, 5, 8])
def test_best_reference_to_an_unrelated_attempt_cannot_block_a_new_record(
    tmp_path: Path, wrong_condition: str, seconds: float
) -> None:
    path = tmp_path / "training.sqlite3"
    repository = SqliteResultRepository(path)
    original = symbols(seconds=5)
    unrelated = symbols(seconds=1)
    if wrong_condition == "aborted":
        unrelated = replace(
            unrelated, state=SessionState.ABORTED, stars=0, elapsed_seconds=0.1
        )
    else:
        unrelated = replace(unrelated, spec=replace(unrelated.spec, seed=123))
    repository.save(original)
    repository.save(unrelated)
    repository.close()
    with sqlite3.connect(path) as connection:
        if wrong_condition == "missing_entry":
            connection.execute(
                "DELETE FROM comparison_bests WHERE attempt_id=?",
                (original.attempt_id,),
            )
        else:
            connection.execute(
                """UPDATE comparison_bests SET attempt_id=? WHERE attempt_id=?""",
                (
                    "missing-attempt"
                    if wrong_condition == "missing_attempt"
                    else unrelated.attempt_id,
                    original.attempt_id,
                ),
            )

    reopened = SqliteResultRepository(path)
    candidate = symbols(seconds=seconds)
    improved = 0 < seconds < 5
    expected = candidate if improved else original
    assert reopened.save(candidate) == improved
    assert reopened.pending_count == 0
    assert reopened.best_for(original) == expected
    with sqlite3.connect(path) as connection:
        assert connection.execute(
            "SELECT attempt_id FROM comparison_bests WHERE comparison_key="
            "(SELECT comparison_key FROM attempts WHERE attempt_id=?)",
            (candidate.attempt_id,),
        ).fetchone() == (expected.attempt_id,)
    reopened.close()


def test_bad_saved_json_is_reported_without_hiding_valid_results(
    tmp_path: Path,
) -> None:
    path = tmp_path / "training.sqlite3"
    repository = SqliteResultRepository(path)
    good = symbols()
    bad = symbols(mistakes=1)
    repository.save(good)
    repository.save(bad)
    repository.close()
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE attempts SET result_json='{}' WHERE attempt_id=?", (bad.attempt_id,)
        )
    reopened = SqliteResultRepository(path)
    assert reopened.results == (good,)
    assert reopened.load_issues and bad.attempt_id in reopened.load_issues[0]
    reopened.close()


@pytest.mark.parametrize(
    "changes",
    [
        {"target": "123"},
        {"correct": 1, "accuracy": 100, "max_combo": 1},
        {"correct": 3, "accuracy": 100, "max_combo": 3},
        {"incorrect": 1, "accuracy": 200 / 3},
        {"errors": {"1": 1}},
        {"keypad_errors": 1},
    ],
)
def test_symbol_result_rejects_inconsistent_target_and_error_counts(
    changes: dict[str, object],
) -> None:
    invalid = replace(symbols(), **changes)
    with pytest.raises(ValueError):
        decode_result(encode_result(invalid))


def test_command_result_requires_a_completed_command_to_claim_completion() -> None:
    invalid = replace(commands(), completed_commands=0)
    with pytest.raises(ValueError, match="완료 명령"):
        decode_result(encode_result(invalid))


def test_command_result_cannot_complete_more_commands_than_accepted_keys() -> None:
    invalid = replace(commands(), completed_commands=3)
    with pytest.raises(ValueError, match="명령 완료 수"):
        decode_result(encode_result(invalid))


@pytest.mark.parametrize("free", [False, True])
def test_editing_result_cannot_claim_completion_without_input(free: bool) -> None:
    invalid = replace(
        editing(),
        key_count=0,
        mode="free" if free else "guided",
        correct=None if free else 0,
        incorrect=None if free else 0,
        accuracy=None,
        max_combo=None if free else 0,
    )
    with pytest.raises(ValueError, match="채점 입력"):
        decode_result(encode_result(invalid))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("cpm", -1),
        ("reaction_times", [["h", -0.1]]),
        ("commands_per_minute", -1),
        ("command_times", [["one", -0.1]]),
        ("command_samples", [{"item_id": "one", "display": "h", "seconds": -0.1}]),
    ],
)
def test_negative_speed_and_timing_samples_are_rejected(
    field: str, value: object
) -> None:
    payload = json.loads(encode_result(commands()))
    payload["data"][field] = value
    with pytest.raises(ValueError, match="시간"):
        decode_result(json.dumps(payload))


def test_invalid_result_does_not_award_or_reserve_its_attempt_id(
    tmp_path: Path,
) -> None:
    repository = SqliteResultRepository(tmp_path / "training.sqlite3")
    result = symbols()
    invalid = replace(result, max_combo=result.correct + 1)
    with pytest.raises(ValueError, match="콤보"):
        repository.save(invalid)
    assert repository.results == ()
    assert repository.completed_count == 0
    assert repository.best_stars(result.spec.exercise_id) == 0
    assert repository.best_for(result) is None
    assert repository.pending_count == 0
    assert repository.save(result)
    repository.close()
    reopened = SqliteResultRepository(tmp_path / "training.sqlite3")
    assert reopened.results == (result,)
    assert reopened.completed_count == 1
    reopened.close()


def source_record() -> SourceDocumentRecord:
    return SourceDocumentRecord(
        id="source_pinned",
        project="sample",
        title="Sample README",
        url="https://example.test/revision/README.md",
        revision="immutable",
        license_id="MIT",
        sha256="a" * 64,
        language="markdown",
    )


def mission_record() -> MissionRecord:
    return MissionRecord(
        id="mission_readme",
        source_id="source_pinned",
        collection_id="web",
        content_version=1,
        title="설명 복구",
        repair_count=4,
        signature="goal_signature",
    )


def test_document_catalog_is_normalized_versioned_and_idempotent(
    tmp_path: Path,
) -> None:
    path = tmp_path / "training.sqlite3"
    repository = SqliteResultRepository(path)
    source = source_record()
    mission = mission_record()
    repository.register_document_catalog((source,), (mission,))
    repository.register_document_catalog((source,), (mission,))
    repository.register_document_catalog(
        (), (replace(mission, content_version=2, signature="new_goal"),)
    )
    with sqlite3.connect(path) as connection:
        assert (
            connection.execute("SELECT COUNT(*) FROM source_documents").fetchone()[0]
            == 1
        )
        assert (
            connection.execute("SELECT COUNT(*) FROM mission_catalog").fetchone()[0]
            == 2
        )
        assert connection.execute(
            "SELECT license_id,sha256 FROM source_documents"
        ).fetchone() == ("MIT", "a" * 64)
    with pytest.raises(ValueError, match="새 ID"):
        repository.register_document_catalog((replace(source, revision="mutated"),), ())
    with pytest.raises(ValueError, match="콘텐츠 버전"):
        repository.register_document_catalog(
            (), (replace(mission, signature="mutated"),)
        )
    repository.close()


def test_catalog_registration_failure_rolls_back_new_source(tmp_path: Path) -> None:
    path = tmp_path / "training.sqlite3"
    repository = SqliteResultRepository(path)
    with pytest.raises(sqlite3.IntegrityError):
        repository.register_document_catalog(
            (source_record(),),
            (replace(mission_record(), source_id="missing"),),
        )
    with sqlite3.connect(path) as connection:
        assert (
            connection.execute("SELECT COUNT(*) FROM source_documents").fetchone()[0]
            == 0
        )
    repository.close()


def test_mission_with_fewer_than_three_repairs_is_not_registered() -> None:
    with pytest.raises(ValueError, match="3곳"):
        replace(mission_record(), repair_count=1)


@pytest.mark.parametrize("change", ["lesson_id", "generator_version"])
def test_generated_edit_result_requires_matching_profile_and_generator_version(
    change: str,
) -> None:
    result = replace(
        editing(),
        practice_spec=EditPracticeSpec("editing_numbers", 7),
        generator_version=1,
    )
    invalid = replace(
        result, **{change: "editing_words" if change == "lesson_id" else 0}
    )
    with pytest.raises(ValueError, match="생성 조건"):
        decode_result(encode_result(invalid))
