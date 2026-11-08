"""앱 DB 경로와 원문 메타데이터 등록은 임시 디렉터리에서 검증한다."""

# Standard library imports
import sqlite3
from pathlib import Path

# Third party imports
import pytest

# Local imports
from vim_key_trainer.content.document_missions import (
    create_document_lesson,
    list_document_missions,
)
from vim_key_trainer.services.application_storage import open_application_repository
from vim_key_trainer.services.edit_session import EditingSession
from vim_key_trainer.services.sqlite_repository import SqliteResultRepository
from vim_key_trainer.services.storage_version import STORAGE_VERSION


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
