"""편집 과제의 불변 콘텐츠와 목표 판정. Qt에 의존하지 않는다."""

# Standard library imports
import hashlib
import json
import re
from dataclasses import asdict, dataclass
from random import Random
from typing import Literal

# Local imports
from vim_key_trainer.domain.activities import ActivitySpec
from vim_key_trainer.domain.code_samples import CodeExcerpt
from vim_key_trainer.domain.document_missions import DocumentPracticeSpec
from vim_key_trainer.domain.edit_weights import EditTechniqueWeights
from vim_key_trainer.domain.keys import KeyToken
from vim_key_trainer.engine import EditorState

EditMode = Literal["guided", "free"]
EDIT_DOCUMENT_LENGTHS = (12, 24, 40)
CODE_DOCUMENT_LENGTHS: dict[str, tuple[int, ...]] = {
    "code_python": tuple(range(300, 501)),
    "code_cpp": tuple(range(300, 501)),
    "code_json": (60,),
}


def random_edit_document_lines(profile_id: str, seed: int) -> int:
    """길이 옵션 없이 seed로 같은 길이의 새 코드 발췌를 재현한다."""
    lengths = CODE_DOCUMENT_LENGTHS.get(profile_id)
    return Random(seed).choice(lengths) if lengths is not None else 24


@dataclass(frozen=True, slots=True)
class EditPracticeSpec:
    """유형·길이·seed를 고정하면 같은 편집 문제를 다시 만들 수 있다."""

    profile_id: str
    seed: int
    document_lines: int = 24
    technique_weights: EditTechniqueWeights | None = None
    code_source_id: str | None = None

    def __post_init__(self) -> None:
        if (
            type(self.profile_id) is not str
            or re.fullmatch(r"[a-z][a-z0-9_]*", self.profile_id) is None
        ):
            raise ValueError("편집 유형 ID의 형식이 올바르지 않습니다.")
        if type(self.seed) is not int or not 0 <= self.seed <= 2**32 - 1:
            raise ValueError("seed는 0 이상 2**32 - 1 이하의 정수여야 합니다.")
        allowed_lengths = CODE_DOCUMENT_LENGTHS.get(
            self.profile_id, EDIT_DOCUMENT_LENGTHS
        )
        if (
            type(self.document_lines) is not int
            or self.document_lines not in allowed_lengths
        ):
            raise ValueError("편집 문서 길이가 해당 연습의 지원 범위에 없습니다.")
        if self.technique_weights is not None and not isinstance(
            self.technique_weights, EditTechniqueWeights
        ):
            raise ValueError("편집 기술 비중의 형식이 올바르지 않습니다.")
        if self.code_source_id is not None:
            if (
                type(self.code_source_id) is not str
                or re.fullmatch(r"[a-z][a-z0-9_]*", self.code_source_id) is None
            ):
                raise ValueError("코드 원문 ID의 형식이 올바르지 않습니다.")
            if self.profile_id not in {"code_python", "code_cpp"}:
                raise ValueError("코드 원문 선택은 Python·C++ 연습에서만 가능합니다.")


@dataclass(frozen=True, slots=True)
class GuideStep:
    keys: tuple[KeyToken, ...]
    expected: EditorState
    text: str


@dataclass(frozen=True, slots=True)
class EditSegment:
    """이동부터 수정 종료까지의 가이드 범위. end_step/target_end_row는 배타적이다."""

    id: str
    start_step: int
    end_step: int
    target_start_row: int
    target_end_row: int
    prerequisite_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if (
            type(self.id) is not str
            or not self.id
            or type(self.start_step) is not int
            or type(self.end_step) is not int
            or not 0 <= self.start_step < self.end_step
        ):
            raise ValueError("수정 구간의 ID 또는 가이드 범위가 잘못되었습니다.")
        if (
            type(self.target_start_row) is not int
            or type(self.target_end_row) is not int
            or not 0 <= self.target_start_row < self.target_end_row
        ):
            raise ValueError("수정 구간의 대상 범위가 잘못되었습니다.")
        if (
            type(self.prerequisite_ids) is not tuple
            or any(
                type(value) is not str or not value for value in self.prerequisite_ids
            )
            or len(set(self.prerequisite_ids)) != len(self.prerequisite_ids)
            or self.id in self.prerequisite_ids
        ):
            raise ValueError("수정 구간의 선행 조건이 잘못되었습니다.")


@dataclass(frozen=True, slots=True)
class EditLesson:
    schema_version: int
    content_version: int
    id: str
    title: str
    description: str
    initial: EditorState
    goal_lines: tuple[str, ...]
    goal_cursor: tuple[int, int] | None
    allowed_commands: frozenset[str]
    guide: tuple[GuideStep, ...]
    baseline_version: int
    baseline: tuple[KeyToken, ...]
    baseline_keys: int
    free_enabled: bool = True
    practice_spec: EditPracticeSpec | None = None
    generator_version: int = 0
    document_spec: DocumentPracticeSpec | None = None
    code_excerpt: CodeExcerpt | None = None
    segments: tuple[EditSegment, ...] = ()
    activity: ActivitySpec | None = None

    @property
    def signature(self) -> str:
        """동일한 시작·목표·허용 범위·가이드·기준 풀이끼리만 비교한다."""

        def state_data(state: EditorState) -> tuple[object, ...]:
            return (
                state.lines,
                state.row,
                state.column,
                state.mode,
                state.preferred_column,
                state.pending,
            )

        excerpt = self.code_excerpt
        data = (
            self.schema_version,
            self.content_version,
            state_data(self.initial),
            self.goal_lines,
            self.goal_cursor,
            sorted(self.allowed_commands),
            tuple(
                (
                    tuple((key.kind, key.value) for key in step.keys),
                    state_data(step.expected),
                )
                for step in self.guide
            ),
            self.baseline_version,
            tuple((key.kind, key.value) for key in self.baseline),
            self.baseline_keys,
            self.free_enabled,
            asdict(self.practice_spec) if self.practice_spec is not None else None,
            asdict(self.document_spec) if self.document_spec is not None else None,
            self.generator_version,
            tuple(asdict(segment) for segment in self.segments),
            asdict(self.activity) if self.activity is not None else None,
            (
                excerpt.source.id,
                excerpt.source.revision,
                excerpt.source.sha256,
                excerpt.source.transformation,
                excerpt.start_line,
                excerpt.end_line,
            )
            if excerpt is not None
            else None,
        )
        return hashlib.sha256(
            json.dumps(data, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()


def expected_states_match(expected: EditorState, actual: EditorState) -> bool:
    """문서·커서·모드·대기와 명시된 선호 열을 검사한다."""
    return (
        expected.lines == actual.lines
        and expected.row == actual.row
        and expected.column == actual.column
        and expected.mode == actual.mode
        and expected.pending == actual.pending
        and (
            expected.preferred_column is None
            or expected.preferred_column == actual.preferred_column
        )
    )


def goal_matches(lesson: EditLesson, state: EditorState) -> bool:
    return (
        state.lines == lesson.goal_lines
        and state.mode == "normal"
        and not state.pending
        and not state.command_line
        and (
            lesson.goal_cursor is None
            or lesson.goal_cursor == (state.row, state.column)
        )
    )
