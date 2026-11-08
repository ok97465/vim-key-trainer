"""현재 형식의 SQLite 기록·출처·미션 카탈로그와 실패 시 메모리 보존.

원문은 패키지 자원에 보관한다. DB에는 고정 revision/hash의 출처와 미션 메타데이터,
시도별 결과 및 비교 기록만 둔다. 시도 INSERT와 별/최고 기록 반영은 한 트랜잭션이다.
"""

# Standard library imports
import re
import sqlite3
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

# Local imports
from vim_key_trainer.domain.sessions import (
    CommandSessionResult,
    EditingSessionResult,
    SessionState,
    StoredResult,
)
from vim_key_trainer.services.result_codec import (
    comparison_digest,
    decode_result,
    encode_result,
    result_kind,
)
from vim_key_trainer.services.result_comparison import is_better_result, record_eligible
from vim_key_trainer.services.result_repository import MemoryResultRepository
from vim_key_trainer.services.storage_version import STORAGE_VERSION


@dataclass(frozen=True, slots=True)
class SourceDocumentRecord:
    id: str
    project: str
    title: str
    url: str
    revision: str
    license_id: str
    sha256: str
    language: str

    def __post_init__(self) -> None:
        if (
            not all((self.id, self.project, self.title, self.revision, self.license_id))
            or not self.url.startswith("https://")
            or re.fullmatch(r"[0-9a-f]{64}", self.sha256) is None
        ):
            raise ValueError(
                "문서 출처의 ID·주소·버전·라이선스·해시가 올바르지 않습니다."
            )


@dataclass(frozen=True, slots=True)
class MissionRecord:
    id: str
    source_id: str
    collection_id: str
    title: str
    repair_count: int
    signature: str

    def __post_init__(self) -> None:
        if (
            not all(
                (
                    self.id,
                    self.source_id,
                    self.collection_id,
                    self.title,
                    self.signature,
                )
            )
            or self.repair_count < 3
        ):
            raise ValueError("미션은 출처와 3곳 이상의 수정 구간이 필요합니다.")


_SCHEMA = (
    """CREATE TABLE source_documents (
        id TEXT PRIMARY KEY, project TEXT NOT NULL, title TEXT NOT NULL,
        url TEXT NOT NULL, revision TEXT NOT NULL, license_id TEXT NOT NULL,
        sha256 TEXT NOT NULL, language TEXT NOT NULL,
        UNIQUE(url, revision, sha256)
    )""",
    """CREATE TABLE mission_catalog (
        id TEXT PRIMARY KEY,
        source_id TEXT NOT NULL REFERENCES source_documents(id),
        collection_id TEXT NOT NULL, title TEXT NOT NULL,
        repair_count INTEGER NOT NULL CHECK(repair_count >= 3), signature TEXT NOT NULL
    )""",
    """CREATE TABLE attempts (
        attempt_id TEXT PRIMARY KEY, result_kind TEXT NOT NULL,
        state TEXT NOT NULL CHECK(state IN ('completed', 'aborted')),
        lesson_id TEXT NOT NULL,
        mode TEXT NOT NULL, comparison_key TEXT NOT NULL,
        result_json TEXT NOT NULL, recorded_at_utc TEXT NOT NULL
    )""",
    """CREATE TABLE comparison_bests (
        comparison_key TEXT PRIMARY KEY,
        attempt_id TEXT NOT NULL REFERENCES attempts(attempt_id)
    )""",
    """CREATE TABLE lesson_progress (
        result_kind TEXT NOT NULL, lesson_id TEXT NOT NULL,
        mode TEXT NOT NULL, guide_level TEXT NOT NULL,
        completed_count INTEGER NOT NULL CHECK(completed_count >= 1),
        best_stars INTEGER NOT NULL CHECK(best_stars BETWEEN 0 AND 3),
        PRIMARY KEY(result_kind, lesson_id, mode, guide_level)
    )""",
    "CREATE INDEX attempts_lesson ON attempts(lesson_id, mode)",
    "CREATE INDEX missions_collection ON mission_catalog(collection_id)",
)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _lesson_conditions(result: StoredResult) -> tuple[str, str, str]:
    if isinstance(result, EditingSessionResult):
        return result.lesson_id, result.mode, result.guide_level
    if isinstance(result, CommandSessionResult):
        return result.spec.lesson_id, "typing", "none"
    return result.spec.exercise_id, "typing", "none"


class SqliteResultRepository(MemoryResultRepository):
    def __init__(self, path: Path, *, clock: Callable[[], datetime] = _utc_now) -> None:
        super().__init__()
        self.path = path
        self._clock = clock
        self._pending: dict[str, StoredResult] = {}
        self._quarantined_attempts: set[str] = set()
        self._persistence_error: str | None = None
        self.load_issues: tuple[str, ...] = ()
        path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(path, timeout=0.2)
        try:
            self._initialize_database()
            self._connection.execute("PRAGMA foreign_keys = ON")
            self._load_results()
        except (ValueError, sqlite3.DatabaseError):
            self._connection.close()
            raise

    @property
    def persistence_error(self) -> str | None:
        return self._persistence_error

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    def _initialize_database(self) -> None:
        version = self._connection.execute("PRAGMA user_version").fetchone()[0]
        if version == STORAGE_VERSION:
            return
        self._connection.execute("PRAGMA foreign_keys = OFF")
        with self._connection:
            # 이 DB는 앱 기록 전용이다. 버전이 다르면 변환 없이 모두 초기화한다.
            # 삭제·생성·버전 변경을 함께 롤백할 수 있게 트랜잭션을 명시한다.
            self._connection.execute("BEGIN IMMEDIATE")
            objects = self._connection.execute(
                "SELECT type, name FROM sqlite_schema WHERE type IN ('table', 'view') "
                "AND name NOT GLOB 'sqlite_*'"
            ).fetchall()
            for kind, name in objects:
                quoted_name = name.replace('"', '""')
                self._connection.execute(f'DROP {kind.upper()} "{quoted_name}"')
            for statement in _SCHEMA:
                self._connection.execute(statement)
            self._connection.execute(f"PRAGMA user_version = {STORAGE_VERSION}")

    def _load_results(self) -> None:
        issues: list[str] = []
        for row in self._connection.execute(
            """SELECT attempt_id, result_kind, state, lesson_id,
                      mode, comparison_key, result_json FROM attempts ORDER BY rowid"""
        ):
            attempt_id, *_, payload = row
            try:
                result = decode_result(payload)
                lesson_id, mode, _guide = _lesson_conditions(result)
                expected = (
                    result.attempt_id,
                    result_kind(result),
                    result.state.value,
                    lesson_id,
                    mode,
                    comparison_digest(result),
                )
                if tuple(row[:-1]) != expected:
                    raise ValueError(
                        "시도 인덱스의 종류·상태·조건이 결과 JSON과 다릅니다."
                    )
                self._record_result(result)
            except ValueError as error:
                self._quarantined_attempts.add(attempt_id)
                issues.append(f"{attempt_id}: {error}")
        self.load_issues = tuple(issues)

    def save(self, result: StoredResult) -> bool:
        if result.attempt_id in self._results:
            return False
        # 검증에 실패한 결과는 메모리의 완료 수·별·최고 기록도 바꾸지 않는다.
        result = decode_result(encode_result(result))
        new_best = self._record_result(result)
        self._pending[result.attempt_id] = result
        self._persist_pending(result)
        return new_best

    def _persist_pending(self, result: StoredResult) -> bool:
        try:
            self._write_result(result)
        except (ValueError, sqlite3.DatabaseError) as error:
            self._persistence_error = str(error)
            return False
        self._pending.pop(result.attempt_id, None)
        self._persistence_error = None if not self._pending else self._persistence_error
        return True

    def _write_result(self, result: StoredResult) -> None:
        payload = encode_result(result)
        kind = result_kind(result)
        lesson_id, mode, guide_level = _lesson_conditions(result)
        digest = comparison_digest(result)
        timestamp = self._clock().astimezone(UTC).isoformat()
        with self._connection:
            inserted = self._connection.execute(
                """INSERT OR IGNORE INTO attempts VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    result.attempt_id,
                    kind,
                    result.state.value,
                    lesson_id,
                    mode,
                    digest,
                    payload,
                    timestamp,
                ),
            )
            if not inserted.rowcount or not record_eligible(result):
                return
            self._connection.execute(
                """INSERT INTO lesson_progress VALUES (?, ?, ?, ?, 1, ?)
                ON CONFLICT(result_kind, lesson_id, mode, guide_level) DO UPDATE SET
                    completed_count = completed_count + 1,
                    best_stars = MAX(best_stars, excluded.best_stars)""",
                (
                    kind,
                    lesson_id,
                    mode,
                    guide_level,
                    result.stars,
                ),
            )
            previous = self._connection.execute(
                """SELECT comparison_bests.attempt_id, attempts.state,
                          attempts.comparison_key, attempts.result_json
                FROM comparison_bests
                LEFT JOIN attempts USING(attempt_id)
                WHERE comparison_bests.comparison_key=?""",
                (digest,),
            ).fetchone()
            best: StoredResult | None = result
            if previous is None or (
                previous[0] in self._quarantined_attempts
                or previous[1] != SessionState.COMPLETED.value
                or previous[2] != digest
                or not record_eligible(decode_result(previous[3]))
            ):
                # 누락·손상된 참조를 복구할 때 기존의 더 좋은 기록을 보존한다.
                best = None
                for attempt_id, stored_payload in self._connection.execute(
                    """SELECT attempt_id, result_json FROM attempts
                    WHERE comparison_key=? AND state='completed' ORDER BY rowid""",
                    (digest,),
                ):
                    if attempt_id in self._quarantined_attempts:
                        continue
                    candidate = decode_result(stored_payload)
                    if record_eligible(candidate) and (
                        best is None or is_better_result(candidate, best)
                    ):
                        best = candidate
            elif previous is not None and not is_better_result(
                result, decode_result(previous[3])
            ):
                return
            assert best is not None  # 현재 시도도 같은 트랜잭션에 삽입되어 있다.
            self._connection.execute(
                """INSERT INTO comparison_bests VALUES (?, ?)
                ON CONFLICT(comparison_key) DO UPDATE SET
                    attempt_id=excluded.attempt_id""",
                (digest, best.attempt_id),
            )

    def retry_pending(self) -> int:
        return sum(
            self._persist_pending(result) for result in tuple(self._pending.values())
        )

    def register_document_catalog(
        self, sources: Iterable[SourceDocumentRecord], missions: Iterable[MissionRecord]
    ) -> None:
        with self._connection:
            for source in sources:
                values = (
                    source.id,
                    source.project,
                    source.title,
                    source.url,
                    source.revision,
                    source.license_id,
                    source.sha256,
                    source.language,
                )
                previous = self._connection.execute(
                    "SELECT * FROM source_documents WHERE id=?",
                    (source.id,),
                ).fetchone()
                if previous is not None and previous != values:
                    raise ValueError(
                        "고정 출처 ID의 메타데이터가 바뀌었습니다. 새 ID가 필요합니다."
                    )
                self._connection.execute(
                    """INSERT INTO source_documents VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO NOTHING""",
                    values,
                )
            for mission in missions:
                self._connection.execute(
                    """INSERT INTO mission_catalog VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        source_id=excluded.source_id,
                        collection_id=excluded.collection_id,
                        title=excluded.title, repair_count=excluded.repair_count,
                        signature=excluded.signature""",
                    (
                        mission.id,
                        mission.source_id,
                        mission.collection_id,
                        mission.title,
                        mission.repair_count,
                        mission.signature,
                    ),
                )

    def close(self) -> None:
        self._connection.close()
