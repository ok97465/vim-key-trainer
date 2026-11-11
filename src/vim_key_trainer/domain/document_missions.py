"""실제 문서 발췌와 고정된 복원 지점. 외부 문서를 실행하지 않는다."""

# Standard library imports
import re
from dataclasses import dataclass

# Local imports
from vim_key_trainer.domain.document_types import DocumentLanguage as DocumentLanguage
from vim_key_trainer.domain.edit_weights import EditTechniqueWeights


@dataclass(frozen=True, slots=True)
class DocumentPracticeSpec:
    """원문과 손상 생성 조건을 고정해 같은 복구 문제를 재현한다."""

    mission_id: str
    seed: int
    change_count: int = 7
    technique_weights: EditTechniqueWeights | None = None

    def __post_init__(self) -> None:
        if (
            type(self.mission_id) is not str
            or re.fullmatch(r"mission_[a-z][a-z0-9_]*", self.mission_id) is None
        ):
            raise ValueError("문서 미션 ID의 형식이 올바르지 않습니다.")
        if type(self.seed) is not int or not 0 <= self.seed <= 2**32 - 1:
            raise ValueError("seed는 0 이상 2**32 - 1 이하의 정수여야 합니다.")
        if type(self.change_count) is not int or not 7 <= self.change_count <= 8:
            raise ValueError("수정 구간 수는 7 이상 8 이하의 정수여야 합니다.")
        if self.technique_weights is not None and not isinstance(
            self.technique_weights, EditTechniqueWeights
        ):
            raise ValueError("편집 기술 비중의 형식이 올바르지 않습니다.")


@dataclass(frozen=True, slots=True)
class MissionSource:
    id: str
    project: str
    title: str
    url: str
    raw_url: str
    revision: str
    license_id: str
    license_url: str
    license_raw_url: str
    language: DocumentLanguage
    source_path: str
    license_path: str
    excerpt_start: int
    excerpt_end: int
    transformation: str
    retrieved_on: str


@dataclass(frozen=True, slots=True)
class DocumentCollection:
    id: str
    title: str
    description: str


@dataclass(frozen=True, slots=True)
class DocumentRepair:
    row: int
    column: int
    broken: str
    correct: str
    description: str


@dataclass(frozen=True, slots=True)
class DocumentMission:
    id: str
    title: str
    brief: str
    collection_id: str
    content_version: int
    source: MissionSource
    goal_lines: tuple[str, ...]
    repairs: tuple[DocumentRepair, ...]

    @property
    def repair_count(self) -> int:
        return len(self.repairs)

    @property
    def language(self) -> DocumentLanguage:
        return self.source.language

    @property
    def initial_lines(self) -> tuple[str, ...]:
        lines = list(self.goal_lines)
        for repair in self.repairs:
            line = lines[repair.row]
            lines[repair.row] = (
                line[: repair.column]
                + repair.broken
                + line[repair.column + len(repair.correct) :]
            )
        return tuple(lines)
