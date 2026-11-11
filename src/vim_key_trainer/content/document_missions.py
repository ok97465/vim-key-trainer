"""앱에 포함된 목표 문서·수정 지점을 오프라인 과제로 읽는다."""

from __future__ import annotations

# Standard library imports
import json
from dataclasses import dataclass
from functools import lru_cache
from importlib.resources import files
from importlib.resources.abc import Traversable
from pathlib import Path, PurePosixPath

# Third party imports
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    model_validator,
)

# Local imports
from vim_key_trainer.content.edit_loader import validate_edit_replay
from vim_key_trainer.content.source_metadata import SourceSchema
from vim_key_trainer.domain.document_missions import (
    DocumentCollection,
    DocumentMission,
    DocumentRepair,
)
from vim_key_trainer.domain.edit_builder import GuideBuilder
from vim_key_trainer.domain.edit_templates import ESC, characters, counted
from vim_key_trainer.domain.editing import EditLesson
from vim_key_trainer.engine import SUPPORTED_COMMANDS, EditorState


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
    source: SourceSchema
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
            source=self.source.to_domain(),
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


def _resource_root() -> Traversable:
    return files("vim_key_trainer").joinpath("resources", "documents")


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
            or not isinstance(data.get("collections"), list)
            or not isinstance(data.get("missions"), list)
        ):
            raise ValueError("collections/missions: 목록이 필요합니다.")
    except (OSError, ValueError) as error:
        return DocumentCatalogReport((), (), (f"manifest.json · {error}",))
    collections: list[DocumentCollection] = []
    missions: list[DocumentMission] = []
    issues: list[str] = []
    collection_ids: set[str] = set()
    mission_ids: set[str] = set()
    for index, raw_collection in enumerate(data["collections"]):
        try:
            model = _CollectionSchema.model_validate(raw_collection)
            if model.id in collection_ids:
                raise ValueError("id: 중복된 컬렉션입니다.")
            collections.append(DocumentCollection(**model.model_dump()))
            collection_ids.add(model.id)
        except ValueError as error:
            issues.append(f"manifest.json · collections.{index}: {error}")
    for index, raw_mission in enumerate(data["missions"]):
        try:
            mission_model = _MissionSchema.model_validate(raw_mission)
            if mission_model.id in mission_ids:
                raise ValueError("id: 중복된 미션입니다.")
            if mission_model.collection_id not in collection_ids:
                raise ValueError("collection_id: 등록되지 않은 컬렉션입니다.")
            mission = mission_model.to_domain()
            missions.append(mission)
            mission_ids.add(mission.id)
        except ValueError as error:
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
    """등록된 source ID로 번들에 포함된 전체 라이선스를 읽는다."""
    for mission in _bundled_catalog().missions:
        source = mission.source
        if source.id == source_id:
            return (
                _resource_root()
                .joinpath(*PurePosixPath(source.license_path).parts)
                .read_text(encoding="utf-8")
            )
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
