"""앱 시작 시 로컬 DB와 오프라인 문서 카탈로그를 연결한다."""

# Standard library imports
import sqlite3
from pathlib import Path

# Third party imports
from platformdirs import user_data_path

# Local imports
from vim_key_trainer.content.document_missions import (
    create_document_lesson,
    list_document_missions,
)
from vim_key_trainer.services.result_repository import (
    MemoryResultRepository,
    ResultRepository,
)
from vim_key_trainer.services.sqlite_repository import (
    MissionRecord,
    SourceDocumentRecord,
    SqliteResultRepository,
)


def open_application_repository(
    directory: Path | None = None,
) -> tuple[ResultRepository, str | None]:
    """기존 DB를 보존하며, 열기 실패 시 학습 가능한 메모리 저장소를 제공한다."""
    directory = (
        directory
        if directory is not None
        else user_data_path(
            "vim-key-trainer",
            appauthor=False,
        )
    )
    repository: SqliteResultRepository | None = None
    try:
        repository = SqliteResultRepository(directory / "training.sqlite3")
        _register_catalog(repository)
    except (OSError, sqlite3.Error, ValueError) as error:
        if repository is not None:
            repository.close()
        return MemoryResultRepository(), f"로컬 기록 DB를 열지 못했습니다: {error}"
    warning = (
        "일부 기록은 형식 오류로 제외했습니다.\n" + "\n".join(repository.load_issues)
        if repository.load_issues
        else None
    )
    return repository, warning


def _register_catalog(repository: SqliteResultRepository) -> None:
    sources: dict[str, SourceDocumentRecord] = {}
    missions: list[MissionRecord] = []
    for mission in list_document_missions():
        source = mission.source
        sources[source.id] = SourceDocumentRecord(
            id=source.id,
            project=source.project,
            title=source.title,
            url=source.url,
            revision=source.revision,
            license_id=source.license_id,
            sha256=source.sha256,
            language=mission.language,
        )
        lesson = create_document_lesson(mission.id)
        missions.append(
            MissionRecord(
                id=mission.id,
                source_id=source.id,
                collection_id=mission.collection_id,
                content_version=mission.content_version,
                title=mission.title,
                repair_count=mission.repair_count,
                signature=lesson.signature,
            )
        )
    repository.register_document_catalog(tuple(sources.values()), tuple(missions))
