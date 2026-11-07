"""commit으로 고정한 문서·라이선스·수정 지점을 검증해 오프라인 과제로 읽는다."""

from __future__ import annotations

# Standard library imports
import hashlib
import json
import textwrap
from dataclasses import dataclass, replace
from functools import lru_cache
from importlib.resources import files
from importlib.resources.abc import Traversable
from pathlib import Path, PurePosixPath
from typing import Literal
from urllib.parse import urlparse

# Third party imports
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    ValidationError,
    model_validator,
)

# Local imports
from vim_key_trainer.content.edit_loader import validate_edit_replay
from vim_key_trainer.domain.document_missions import (
    DocumentCollection,
    DocumentMission,
    DocumentRepair,
    MissionSource,
)
from vim_key_trainer.domain.edit_builder import GuideBuilder
from vim_key_trainer.domain.edit_templates import ESC, characters, counted
from vim_key_trainer.domain.editing import EditLesson
from vim_key_trainer.engine import SUPPORTED_COMMANDS, EditorState


class _SourceSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: StrictStr = Field(pattern=r"^[a-z][a-z0-9_]*$")
    project: StrictStr = Field(pattern=r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
    title: StrictStr = Field(min_length=1)
    url: StrictStr
    raw_url: StrictStr
    revision: StrictStr = Field(pattern=r"^[a-f0-9]{40}$")
    license_id: Literal["MIT", "BSD-3-Clause"]
    license_url: StrictStr
    license_raw_url: StrictStr
    sha256: StrictStr = Field(pattern=r"^[a-f0-9]{64}$")
    license_sha256: StrictStr = Field(pattern=r"^[a-f0-9]{64}$")
    language: Literal["text", "markdown", "python", "cpp"]
    source_path: StrictStr
    license_path: StrictStr
    excerpt_start: StrictInt = Field(ge=1)
    excerpt_end: StrictInt = Field(ge=1)
    transformation: StrictStr = Field(min_length=1)
    retrieved_on: StrictStr = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")

    @model_validator(mode="after")
    def validate_source(self) -> _SourceSchema:
        for name in ("source_path", "license_path"):
            raw_path = getattr(self, name)
            path = PurePosixPath(raw_path)
            if (
                path.is_absolute()
                or ".." in path.parts
                or len(path.parts) != 2
                or path.parts[0] != self.id
                # POSIX 경로 검사 뒤에도 Windows가 구분자·드라이브로
                # 재해석할 수 있는 문자는 패키지 경로에서 받지 않는다.
                or "\\" in raw_path
                or ":" in raw_path
            ):
                raise ValueError(f"{name}: 패키지 문서 경로 범위를 벗어났습니다.")
        for name in ("url", "license_url", "raw_url", "license_raw_url"):
            url = urlparse(getattr(self, name))
            raw = "raw" in name
            host = "raw.githubusercontent.com" if raw else "github.com"
            prefix = f"/{self.project}/{'' if raw else 'blob/'}{self.revision}/"
            if (
                url.scheme != "https"
                or url.netloc != host
                or not url.path.startswith(prefix)
                or not url.path.removeprefix(prefix)
            ):
                raise ValueError(f"{name}: 원문 URL은 동일 commit으로 고정해야 합니다.")
        if self.excerpt_end < self.excerpt_start:
            raise ValueError("원문 발췌 구간의 끝이 시작보다 작습니다.")
        return self


class _RepairSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    row: StrictInt = Field(ge=0)
    column: StrictInt = Field(ge=0)
    broken: StrictStr = Field(max_length=128)
    correct: StrictStr = Field(min_length=1, max_length=64)
    description: StrictStr = Field(min_length=1)


class _MissionSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: StrictStr = Field(pattern=r"^mission_[a-z][a-z0-9_]*$")
    title: StrictStr = Field(min_length=1)
    brief: StrictStr = Field(min_length=1)
    collection_id: StrictStr = Field(pattern=r"^[a-z][a-z0-9_]*$")
    content_version: StrictInt = Field(ge=1)
    source: _SourceSchema
    goal_lines: tuple[StrictStr, ...] = Field(min_length=24, max_length=100)
    repairs: tuple[_RepairSchema, ...] = Field(min_length=3, max_length=12)

    @model_validator(mode="after")
    def validate_repairs(self) -> _MissionSchema:
        if any(
            len(line) > 256 or not _printable_ascii(line) for line in self.goal_lines
        ):
            raise ValueError("goal_lines: 문서는 256열 이하의 ASCII 행이어야 합니다.")
        used_rows: list[int] = []
        for repair in self.repairs:
            if not _printable_ascii(repair.broken + repair.correct):
                raise ValueError("repairs: 삽입 텍스트는 표시 가능한 ASCII여야 합니다.")
            if repair.broken == repair.correct:
                raise ValueError("repairs: 실제로 바뀌는 수정 지점이 필요합니다.")
            if repair.row >= len(self.goal_lines):
                raise ValueError("repairs.row: 문서 범위를 벗어났습니다.")
            line = self.goal_lines[repair.row]
            if (
                line[repair.column : repair.column + len(repair.correct)]
                != repair.correct
            ):
                raise ValueError("repairs.correct: 원문의 지정 위치와 다릅니다.")
            if any(abs(repair.row - row) < 2 for row in used_rows):
                raise ValueError(
                    "repairs.row: 수정 구간은 서로 다른 위치로 나눠야 합니다."
                )
            used_rows.append(repair.row)
        return self

    def to_domain(self) -> DocumentMission:
        return DocumentMission(
            id=self.id,
            title=self.title,
            brief=self.brief,
            collection_id=self.collection_id,
            content_version=self.content_version,
            source=MissionSource(**self.source.model_dump()),
            goal_lines=self.goal_lines,
            repairs=tuple(
                DocumentRepair(**repair.model_dump()) for repair in self.repairs
            ),
        )


class _CollectionSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: StrictStr = Field(pattern=r"^[a-z][a-z0-9_]*$")
    title: StrictStr = Field(min_length=1)
    description: StrictStr = Field(min_length=1)


def _printable_ascii(value: str) -> bool:
    return all(char.isascii() and char.isprintable() for char in value)


def extract_source_lines(
    raw: str, start: int, end: int, language: str
) -> tuple[str, ...]:
    """번들에 기록된 변환만 적용한다. Python·C++ 원문은 실행하지 않는다."""
    lines = raw.splitlines()[start - 1 : end]
    if language in {"python", "cpp"}:
        return tuple(line.expandtabs(4) for line in lines)
    excerpt: list[str] = []
    for line in lines:
        if not line.isascii() or line.lstrip().startswith(("<", "![", "[!")):
            continue
        expanded = line.expandtabs(4)
        if len(expanded) > 76 and not expanded.startswith(("    ", "```")):
            excerpt.extend(
                textwrap.wrap(
                    expanded,
                    width=76,
                    break_long_words=False,
                    break_on_hyphens=False,
                    replace_whitespace=False,
                    drop_whitespace=True,
                )
            )
        else:
            excerpt.append(expanded)
    return tuple(excerpt)


def _resource_root() -> Traversable:
    return files("vim_key_trainer").joinpath("resources", "documents")


def _read_verified(root: Traversable, path: str, digest: str) -> bytes:
    value = root.joinpath(*PurePosixPath(path).parts).read_bytes()
    if len(value) > 512_000 or hashlib.sha256(value).hexdigest() != digest:
        raise ValueError(f"{path}: 원문 또는 라이선스의 SHA-256 검증에 실패했습니다.")
    return value


def _validate_source(root: Traversable, mission: DocumentMission) -> None:
    source = mission.source
    raw = _read_verified(root, source.source_path, source.sha256).decode("utf-8")
    license_text = _read_verified(
        root, source.license_path, source.license_sha256
    ).decode("utf-8")
    if "Permission is hereby granted" not in license_text and (
        "Redistribution and use" not in license_text
    ):
        raise ValueError(
            f"{source.license_path}: 허용 라이선스 원문을 확인할 수 없습니다."
        )
    if source.excerpt_end > len(raw.splitlines()):
        raise ValueError("source.excerpt_end: 실제 원문 길이를 벗어났습니다.")
    expected = extract_source_lines(
        raw, source.excerpt_start, source.excerpt_end, source.language
    )
    if expected != mission.goal_lines:
        raise ValueError("goal_lines: 출처에 기록한 발췌·변환 결과와 다릅니다.")


@dataclass(frozen=True, slots=True)
class DocumentCatalogReport:
    collections: tuple[DocumentCollection, ...]
    missions: tuple[DocumentMission, ...]
    issues: tuple[str, ...]


def load_document_catalog(directory: Path | None = None) -> DocumentCatalogReport:
    """잘못된 미션은 파일·필드 진단과 함께 제외하고 유효한 미션은 유지한다."""
    root: Traversable = directory if directory is not None else _resource_root()
    try:
        data = json.loads(root.joinpath("manifest.json").read_text(encoding="utf-8"))
        if (
            not isinstance(data, dict)
            or type(data.get("schema_version")) is not int
            or data["schema_version"] != 1
        ):
            raise ValueError("schema_version: 지원하지 않는 문서 코퍼스입니다.")
        if not isinstance(data.get("collections"), list) or not isinstance(
            data.get("missions"), list
        ):
            raise ValueError("collections/missions: 목록이 필요합니다.")
    except (OSError, ValueError) as error:
        return DocumentCatalogReport((), (), (f"manifest.json · {error}",))
    collections: list[DocumentCollection] = []
    missions: list[DocumentMission] = []
    issues: list[str] = []
    collection_ids: set[str] = set()
    mission_ids: set[str] = set()
    source_records: dict[str, MissionSource] = {}
    for index, raw_collection in enumerate(data["collections"]):
        try:
            model = _CollectionSchema.model_validate(raw_collection)
            if model.id in collection_ids:
                raise ValueError("id: 중복된 컬렉션입니다.")
            collections.append(DocumentCollection(**model.model_dump()))
            collection_ids.add(model.id)
        except (ValidationError, ValueError) as error:
            issues.append(f"manifest.json · collections.{index}: {error}")
    for index, raw_mission in enumerate(data["missions"]):
        try:
            mission_model = _MissionSchema.model_validate(raw_mission)
            if mission_model.id in mission_ids:
                raise ValueError("id: 중복된 미션입니다.")
            if mission_model.collection_id not in collection_ids:
                raise ValueError("collection_id: 등록되지 않은 컬렉션입니다.")
            mission = mission_model.to_domain()
            # 같은 원문을 여러 구간으로 발췌할 수 있으나 물리 출처 정보는 같아야 한다.
            physical_source = replace(
                mission.source, excerpt_start=1, excerpt_end=1, transformation=""
            )
            registered = source_records.get(mission.source.id)
            if registered is not None and registered != physical_source:
                raise ValueError(
                    "source.id: 동일 출처 ID의 불변 메타데이터가 다릅니다."
                )
            _validate_source(root, mission)
            missions.append(mission)
            mission_ids.add(mission.id)
            source_records.setdefault(mission.source.id, physical_source)
        except (OSError, ValueError) as error:
            issues.append(f"manifest.json · missions.{index}: {error}")
    if not missions and not issues:
        issues.append("manifest.json · missions: 문서 미션이 없습니다.")
    return DocumentCatalogReport(tuple(collections), tuple(missions), tuple(issues))


@lru_cache(maxsize=1)
def _bundled_catalog() -> DocumentCatalogReport:
    return load_document_catalog()


def list_document_collections() -> tuple[DocumentCollection, ...]:
    return _bundled_catalog().collections


def list_document_missions(
    collection_id: str | None = None,
) -> tuple[DocumentMission, ...]:
    report = _bundled_catalog()
    if collection_id is not None and collection_id not in {
        collection.id for collection in report.collections
    }:
        raise ValueError(f"알 수 없는 문서 컬렉션입니다: {collection_id}")
    return tuple(
        mission
        for mission in report.missions
        if collection_id is None or mission.collection_id == collection_id
    )


def get_document_mission(mission_id: str) -> DocumentMission:
    for mission in _bundled_catalog().missions:
        if mission.id == mission_id:
            return mission
    details = "\n".join(_bundled_catalog().issues)
    raise ValueError(f"알 수 없거나 검증에 실패한 문서 미션: {mission_id}\n{details}")


def document_catalog_issues() -> tuple[str, ...]:
    return _bundled_catalog().issues


def read_document_license(source_id: str) -> str:
    """임의 경로 대신 검증한 source ID로 전체 라이선스를 조회한다."""
    for mission in _bundled_catalog().missions:
        source = mission.source
        if source.id == source_id:
            return _read_verified(
                _resource_root(), source.license_path, source.license_sha256
            ).decode("utf-8")
    raise ValueError(f"등록되지 않은 문서 출처입니다: {source_id}")


@lru_cache(maxsize=32)
def create_document_lesson(mission_id: str) -> EditLesson:
    """명시한 손상을 초기 문서에 적용하고 실제 키로 복원 풀이를 검증한다."""
    mission = get_document_mission(mission_id)
    initial = EditorState(mission.initial_lines)
    guide = GuideBuilder(initial, SUPPORTED_COMMANDS)
    for repair in reversed(mission.repairs):
        line = guide.engine.state.lines[repair.row]
        prefix = line[: repair.column]
        suffix = line[repair.column + len(repair.broken) :]
        if not repair.broken and not suffix:
            guide.navigate(repair.row, None)
            insertion = "A"
        else:
            guide.navigate(repair.row, min(repair.column, max(0, len(line) - 1)))
            if repair.broken:
                guide.record(
                    characters(counted(len(repair.broken), "x")),
                    f"{repair.row + 1}행의 잘못된 조각을 삭제합니다.",
                )
            insertion = "i" if suffix or not prefix else "a"
        guide.record(
            characters(insertion + repair.correct) + (ESC,), repair.description
        )
    baseline = tuple(key for step in guide.steps for key in step.keys)
    lesson = EditLesson(
        schema_version=1,
        content_version=mission.content_version,
        id=mission.id,
        title=mission.title,
        description=f"{mission.brief} · {mission.repair_count}곳 복원",
        initial=initial,
        goal_lines=mission.goal_lines,
        goal_cursor=None,
        allowed_commands=SUPPORTED_COMMANDS,
        guide=tuple(guide.steps),
        baseline_version=2,
        baseline=baseline,
        baseline_keys=len(baseline),
    )
    validate_edit_replay(lesson)
    return lesson
