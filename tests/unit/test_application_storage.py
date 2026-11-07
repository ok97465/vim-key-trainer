"""앱 DB 경로와 원문 메타데이터 등록은 임시 디렉터리에서 검증한다."""

# Standard library imports
import sqlite3
from pathlib import Path

# Local imports
from vim_key_trainer.content.document_missions import (
    create_document_lesson,
    list_document_missions,
)
from vim_key_trainer.services.application_storage import open_application_repository
from vim_key_trainer.services.edit_session import EditingSession
from vim_key_trainer.services.result_repository import MemoryResultRepository
from vim_key_trainer.services.sqlite_repository import SqliteResultRepository


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
    assert (
        reopened.best_edit_stars(missions[0].id, missions[0].content_version, "free")
        == 3
    )
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


def test_newer_database_is_preserved_and_application_can_still_run(
    tmp_path: Path,
) -> None:
    path = tmp_path / "training.sqlite3"
    with sqlite3.connect(path) as database:
        database.execute("CREATE TABLE important(value TEXT)")
        database.execute("INSERT INTO important VALUES ('preserved')")
        database.execute("PRAGMA user_version=999")
    repository, warning = open_application_repository(tmp_path)
    assert isinstance(repository, MemoryResultRepository)
    assert not isinstance(repository, SqliteResultRepository)
    assert warning is not None
    with sqlite3.connect(path) as database:
        assert database.execute("PRAGMA user_version").fetchone()[0] == 999
        assert (
            database.execute("SELECT value FROM important").fetchone()[0] == "preserved"
        )
