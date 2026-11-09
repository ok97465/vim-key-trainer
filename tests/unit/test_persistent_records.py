"""임시 SQLite의 재시작·초기화·원자성·손상 격리와 앱 카탈로그 등록을 검증한다."""

# Standard library imports
import sqlite3
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

# Third party imports
import pytest
from record_factories import command_result, editing_result, typing_result

# Local imports
from vim_key_trainer.content.document_missions import (
    create_document_lesson,
    list_document_missions,
)
from vim_key_trainer.domain.editing import EditPracticeSpec
from vim_key_trainer.domain.sessions import (
    EditingSessionResult,
    SessionState,
    StoredResult,
)
from vim_key_trainer.services import sqlite_repository
from vim_key_trainer.services.application_storage import open_application_repository
from vim_key_trainer.services.edit_problem_factory import create_edit_problem
from vim_key_trainer.services.edit_session import EditingSession
from vim_key_trainer.services.result_codec import decode_result, encode_result
from vim_key_trainer.services.sqlite_repository import (
    MissionRecord,
    SourceDocumentRecord,
    SqliteResultRepository,
)
from vim_key_trainer.services.storage_version import STORAGE_VERSION


@pytest.mark.parametrize("make_result", [typing_result, command_result, editing_result])
def test_result_json_and_database_roundtrip_all_practice_types(
    tmp_path: Path,
    make_result: Callable[[], StoredResult],
) -> None:
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
    first = typing_result(mistakes=1)
    accurate = typing_result(seconds=7)
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
    result = replace(typing_result(), state=SessionState.ABORTED, stars=0)
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


@pytest.mark.parametrize(
    ("profile_id", "document_lines"),
    [
        ("editing_compound", 40),
        ("code_python", 300),
        ("code_cpp", 500),
        ("code_json", 60),
    ],
)
def test_generated_free_result_keeps_conditions_and_nonapplicable_stats(
    tmp_path: Path,
    profile_id: str,
    document_lines: int,
) -> None:
    spec = EditPracticeSpec(profile_id, seed=2**32 - 1, document_lines=document_lines)
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
    assert result == session.result
    assert reopened.best_for(session.result) == session.result
    assert not reopened.save(session.result)
    assert reopened.completed_count == 1
    assert result.practice_spec == spec
    assert (
        result.correct
        is result.incorrect
        is result.accuracy
        is result.max_combo
        is None
    )
    assert reopened.best_edit_stars(lesson.id, "free") == 3
    assert reopened.best_edit_stars(lesson.id, "guided") == 0
    reopened.close()


@pytest.mark.parametrize("version", [0, STORAGE_VERSION - 1, STORAGE_VERSION + 1])
def test_different_storage_version_clears_all_history_and_can_save_again(
    tmp_path: Path, version: int
) -> None:
    path = tmp_path / "reset.sqlite3"
    repository = SqliteResultRepository(path)
    previous = typing_result()
    repository.save(previous)
    repository.register_document_catalog((source_record(),), (mission_record(),))
    repository.close()
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE sqlitex_history(value TEXT)")
        connection.execute("INSERT INTO sqlitex_history VALUES ('old record')")
        connection.execute("UPDATE attempts SET result_json='unreadable old format'")
        connection.execute(f"PRAGMA user_version={version}")
    repository = SqliteResultRepository(path)
    assert repository.load_issues == ()
    assert repository.results == ()
    assert repository.completed_count == 0
    assert repository.best_stars("numbers") == 0
    assert repository.best_for(previous) is None
    assert repository.pending_count == 0
    with sqlite3.connect(path) as connection:
        assert (
            connection.execute("PRAGMA user_version").fetchone()[0] == STORAGE_VERSION
        )
        for table in (
            "attempts",
            "lesson_progress",
            "comparison_bests",
            "mission_catalog",
            "source_documents",
        ):
            assert (
                connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
            )
        assert (
            connection.execute(
                "SELECT name FROM sqlite_schema WHERE name='sqlitex_history'"
            ).fetchone()
            is None
        )
    current = typing_result()
    assert repository.save(current)
    repository.close()
    reopened = SqliteResultRepository(path)
    assert reopened.results == (current,)
    assert reopened.best_for(current) == current
    assert reopened.best_stars("numbers") == 3
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
    result = typing_result()
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
    best = typing_result(seconds=1)
    repository.save(best)
    with sqlite3.connect(path) as connection:
        connection.execute("DROP TRIGGER reject_attempt")
    worse = typing_result(seconds=4)
    repository.save(worse)
    assert repository.best_for(worse) == best
    assert repository.retry_pending() == 1
    repository.close()
    reopened = SqliteResultRepository(path)
    assert reopened.best_for(worse) == best
    assert reopened.completed_count == 2
    reopened.close()


def test_failed_reset_rolls_back_deleted_history_and_storage_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "reset_failure.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE old_history(value TEXT)")
        connection.execute("INSERT INTO old_history VALUES ('preserve on failure')")
        connection.execute("PRAGMA user_version=1")
    monkeypatch.setattr(
        sqlite_repository, "_SCHEMA", sqlite_repository._SCHEMA + ("INVALID SQL",)
    )
    with pytest.raises(sqlite3.DatabaseError):
        SqliteResultRepository(path)
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 1
        assert connection.execute("SELECT value FROM old_history").fetchone() == (
            "preserve on failure",
        )
        assert (
            connection.execute(
                "SELECT name FROM sqlite_schema WHERE name='attempts'"
            ).fetchone()
            is None
        )


@pytest.mark.parametrize(
    ("column", "changed"),
    [
        ("result_kind", "wrong-kind"),
        ("state", "aborted"),
        ("lesson_id", "other_lesson"),
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
    result = editing_result()
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
    corrupted = typing_result(seconds=1)
    repository.save(corrupted)
    repository.close()
    with sqlite3.connect(path) as connection:
        connection.execute("UPDATE attempts SET mode='wrong'")
    reopened = SqliteResultRepository(path)
    valid = typing_result(seconds=5)
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
    original = typing_result(seconds=5)
    unrelated = typing_result(seconds=1)
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
    candidate = typing_result(seconds=seconds)
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
    good = typing_result()
    bad = typing_result(mistakes=1)
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


def test_invalid_result_does_not_award_or_reserve_its_attempt_id(
    tmp_path: Path,
) -> None:
    repository = SqliteResultRepository(tmp_path / "training.sqlite3")
    result = typing_result()
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
        title="설명 복구",
        repair_count=4,
        signature="goal_signature",
    )


def test_document_catalog_keeps_only_current_metadata_and_is_idempotent(
    tmp_path: Path,
) -> None:
    path = tmp_path / "training.sqlite3"
    repository = SqliteResultRepository(path)
    source = source_record()
    mission = mission_record()
    repository.register_document_catalog((source,), (mission,))
    repository.register_document_catalog((source,), (mission,))
    repository.register_document_catalog((), (replace(mission, signature="new_goal"),))
    with sqlite3.connect(path) as connection:
        assert (
            connection.execute("SELECT COUNT(*) FROM source_documents").fetchone()[0]
            == 1
        )
        assert (
            connection.execute("SELECT COUNT(*) FROM mission_catalog").fetchone()[0]
            == 1
        )
        assert connection.execute(
            "SELECT signature FROM mission_catalog"
        ).fetchone() == ("new_goal",)
        assert connection.execute(
            "SELECT license_id,sha256 FROM source_documents"
        ).fetchone() == ("MIT", "a" * 64)
    with pytest.raises(ValueError, match="새 ID"):
        repository.register_document_catalog((replace(source, revision="mutated"),), ())
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


def test_application_registers_corpus_and_restores_mission_progress(
    tmp_path: Path,
) -> None:
    repository, warning = open_application_repository(tmp_path)
    assert isinstance(repository, SqliteResultRepository)
    assert warning is None
    missions = list_document_missions()
    session = EditingSession(create_document_lesson(missions[0].id), "free")
    for key in session.lesson.baseline:
        session.submit(key)
    assert session.result is not None
    assert repository.save(session.result)
    repository.close()
    reopened, warning = open_application_repository(tmp_path)
    assert isinstance(reopened, SqliteResultRepository)
    assert warning is None
    assert reopened.best_edit_stars(missions[0].id, "free") == 3
    assert reopened.results[0] == session.result
    assert not reopened.save(session.result)
    reopened.close()
    with sqlite3.connect(tmp_path / "training.sqlite3") as database:
        assert database.execute("SELECT COUNT(*) FROM mission_catalog").fetchone()[
            0
        ] == len(missions)
        assert database.execute("SELECT COUNT(*) FROM attempts").fetchone()[0] == 1
        assert database.execute("SELECT COUNT(*) FROM source_documents").fetchone()[
            0
        ] == len({m.source.id for m in missions})


@pytest.mark.parametrize("version", [0, STORAGE_VERSION - 1, STORAGE_VERSION + 1])
def test_other_storage_version_is_reset_and_current_catalog_is_registered(
    tmp_path: Path,
    version: int,
) -> None:
    path = tmp_path / "training.sqlite3"
    with sqlite3.connect(path) as database:
        database.execute("CREATE TABLE old_history(value TEXT)")
        database.execute("INSERT INTO old_history VALUES ('discarded')")
        database.execute(f"PRAGMA user_version={version}")
    repository, warning = open_application_repository(tmp_path)
    assert isinstance(repository, SqliteResultRepository)
    assert warning is None
    assert repository.results == ()
    assert repository.completed_count == 0
    assert repository.best_edit_stars(list_document_missions()[0].id, "free") == 0
    repository.close()
    with sqlite3.connect(path) as database:
        assert database.execute("PRAGMA user_version").fetchone()[0] == STORAGE_VERSION
        assert (
            database.execute(
                "SELECT name FROM sqlite_schema WHERE name='old_history'"
            ).fetchone()
            is None
        )
        assert database.execute("SELECT COUNT(*) FROM mission_catalog").fetchone()[
            0
        ] == len(list_document_missions())
