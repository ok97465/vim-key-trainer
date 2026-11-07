"""편집 과제 JSON의 경계 검증과 엔진 재생 검사."""

from __future__ import annotations

# Standard library imports
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import Literal

# Third party imports
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    ValidationError,
    field_validator,
    model_validator,
)

# Local imports
from vim_key_trainer.content.schemas import KeyTokenSchema
from vim_key_trainer.domain.editing import (
    EditLesson,
    GuideStep,
    expected_states_match,
    goal_matches,
)
from vim_key_trainer.engine import SUPPORTED_COMMANDS, EditEngine, EditorState


class EditorStateSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    lines: tuple[StrictStr, ...] = Field(min_length=1, max_length=1_000)
    row: StrictInt = Field(ge=0)
    column: StrictInt = Field(ge=0)
    mode: Literal["normal", "insert"] = "normal"
    preferred_column: StrictInt | None = Field(default=None, ge=0)
    pending: StrictStr = Field(default="", max_length=9)

    @field_validator("pending")
    @classmethod
    def validate_pending(cls, pending: str) -> str:
        # 엔진과 같은 문법·count 상한을 쓰되 오류의 pending 필드 위치를 보존한다.
        EditorState(lines=("",), pending=pending)
        return pending

    @model_validator(mode="after")
    def validate_state(self) -> EditorStateSchema:
        _validate_lines(self.lines)
        _validate_cursor(self.lines, self.row, self.column, self.mode)
        if self.mode == "insert" and self.pending:
            raise ValueError("Insert 상태에는 대기 명령을 둘 수 없습니다.")
        return self

    def to_domain(self) -> EditorState:
        return EditorState(
            lines=self.lines,
            row=self.row,
            column=self.column,
            mode=self.mode,
            preferred_column=self.preferred_column,
            pending=self.pending,
        )


def _validate_lines(lines: tuple[str, ...]) -> None:
    if any(
        len(line) > 10_000
        or not line.isascii()
        or any(not character.isprintable() for character in line)
        for line in lines
    ):
        raise ValueError("문서는 줄당 10,000자 이하의 표시 가능한 ASCII여야 합니다.")


def _validate_cursor(lines: tuple[str, ...], row: int, column: int, mode: str) -> None:
    if row >= len(lines):
        raise ValueError("커서 행이 문서 범위를 벗어났습니다.")
    maximum = len(lines[row]) if mode == "insert" else max(0, len(lines[row]) - 1)
    if column > maximum:
        raise ValueError("커서 열이 해당 모드의 문서 범위를 벗어났습니다.")


class GoalSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    lines: tuple[StrictStr, ...] = Field(min_length=1, max_length=1_000)
    cursor: tuple[StrictInt, StrictInt] | None = None

    @model_validator(mode="after")
    def validate_goal(self) -> GoalSchema:
        _validate_lines(self.lines)
        if self.cursor is not None:
            if min(self.cursor) < 0:
                raise ValueError("목표 커서 좌표는 0 이상이어야 합니다.")
            _validate_cursor(self.lines, *self.cursor, "normal")
        return self


class GuideStepSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    text: StrictStr = Field(min_length=1)
    keys: tuple[KeyTokenSchema, ...] = Field(min_length=1, max_length=10_000)
    expected: EditorStateSchema

    @model_validator(mode="after")
    def validate_text(self) -> GuideStepSchema:
        if not self.text.strip():
            raise ValueError("가이드 안내가 비어 있습니다.")
        return self


class BaselineSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: StrictInt = Field(ge=1)
    keys: tuple[KeyTokenSchema, ...] = Field(min_length=1, max_length=10_000)
    key_count: StrictInt = Field(ge=1)

    @model_validator(mode="after")
    def validate_count(self) -> BaselineSchema:
        if len(self.keys) != self.key_count:
            raise ValueError("기준 입력 수 B가 기준 풀이의 논리 키 수와 다릅니다.")
        return self


class EditLessonSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: StrictInt = Field(ge=1, le=1)
    content_version: StrictInt = Field(ge=1)
    stage: Literal["editing"]
    id: StrictStr = Field(pattern=r"^[a-z][a-z0-9_]*$")
    title: StrictStr = Field(min_length=1)
    description: StrictStr = Field(min_length=1)
    initial: EditorStateSchema
    goal: GoalSchema
    allowed_commands: tuple[StrictStr, ...] = Field(min_length=1)
    guide: tuple[GuideStepSchema, ...] = Field(min_length=1, max_length=1_000)
    baseline: BaselineSchema
    free_enabled: StrictBool = True

    @model_validator(mode="after")
    def validate_lesson(self) -> EditLessonSchema:
        if not self.title.strip() or not self.description.strip():
            raise ValueError("과제 제목과 설명이 비어 있습니다.")
        if self.initial.pending:
            raise ValueError("초기 상태에는 미완성 명령을 둘 수 없습니다.")
        if len(self.allowed_commands) != len(set(self.allowed_commands)):
            raise ValueError("허용 명령이 중복되었습니다.")
        unsupported = set(self.allowed_commands) - SUPPORTED_COMMANDS
        if unsupported:
            raise ValueError(
                f"미지원 허용 명령입니다: {', '.join(sorted(unsupported))}"
            )
        if self.free_enabled and self.initial.lines == self.goal.lines:
            raise ValueError("초기 문서와 목표가 같은 과제는 가이드 전용이어야 합니다.")
        return self

    def to_domain(self) -> EditLesson:
        return EditLesson(
            schema_version=self.schema_version,
            content_version=self.content_version,
            id=self.id,
            title=self.title,
            description=self.description,
            initial=self.initial.to_domain(),
            goal_lines=self.goal.lines,
            goal_cursor=self.goal.cursor,
            allowed_commands=frozenset(self.allowed_commands),
            guide=tuple(
                GuideStep(
                    keys=tuple(key.to_domain() for key in step.keys),
                    expected=step.expected.to_domain(),
                    text=step.text,
                )
                for step in self.guide
            ),
            baseline_version=self.baseline.version,
            baseline=tuple(key.to_domain() for key in self.baseline.keys),
            baseline_keys=self.baseline.key_count,
            free_enabled=self.free_enabled,
        )


class EditContentError(ValueError):
    def __init__(self, field: str, message: str) -> None:
        super().__init__(f"{field}: {message}")
        self.field = field


@dataclass(frozen=True, slots=True)
class EditLoadIssue:
    file: str
    field: str
    message: str

    def __str__(self) -> str:
        return f"{self.file} · {self.field}: {self.message}"


@dataclass(frozen=True, slots=True)
class EditLoadReport:
    lessons: tuple[EditLesson, ...]
    issues: tuple[EditLoadIssue, ...]


def validate_edit_replay(lesson: EditLesson) -> None:
    """전체 가이드 기대 상태와 동일 조건의 기준 풀이를 실행 검증한다."""
    engine = EditEngine(lesson.initial, allowed_commands=lesson.allowed_commands)
    for step_index, step in enumerate(lesson.guide):
        for key_index, key in enumerate(step.keys):
            outcome = engine.submit(key)
            if not outcome.accepted:
                raise EditContentError(
                    f"guide.{step_index}.keys.{key_index}",
                    outcome.message or "가이드 입력이 거부되었습니다.",
                )
        if not expected_states_match(step.expected, engine.state):
            raise EditContentError(
                f"guide.{step_index}.expected",
                "가이드 재생 상태가 기대 상태와 다릅니다.",
            )
    if not goal_matches(lesson, engine.state):
        raise EditContentError(
            "guide", "전체 가이드가 Normal·대기 없음의 목표로 끝나지 않습니다."
        )
    engine = EditEngine(lesson.initial, allowed_commands=lesson.allowed_commands)
    for index, key in enumerate(lesson.baseline):
        outcome = engine.submit(key)
        if not outcome.accepted:
            raise EditContentError(
                f"baseline.keys.{index}",
                outcome.message or "기준 풀이 입력이 거부되었습니다.",
            )
        if (
            lesson.free_enabled
            and index < len(lesson.baseline) - 1
            and goal_matches(lesson, engine.state)
        ):
            raise EditContentError(
                f"baseline.keys.{index}",
                "자유 풀이가 여기서 완료되어 기준 풀이의 남은 키를 입력할 수 없습니다.",
            )
    if not goal_matches(lesson, engine.state):
        raise EditContentError(
            "baseline", "기준 풀이가 Normal·대기 없음의 목표로 끝나지 않습니다."
        )
    if lesson.baseline_keys != len(lesson.baseline):
        raise EditContentError(
            "baseline.key_count", "기준 입력 수 B가 실제 키 수와 다릅니다."
        )


def load_edit_lesson_json(data: str | bytes) -> EditLesson:
    lesson = EditLessonSchema.model_validate_json(data).to_domain()
    validate_edit_replay(lesson)
    return lesson


def load_edit_lessons(directory: Path | None = None) -> EditLoadReport:
    """잘못된 파일을 제외하고 나머지 과제와 파일·필드 진단을 반환한다."""
    resources = (
        directory
        if directory is not None
        else files("vim_key_trainer").joinpath("resources", "lessons", "editing")
    )
    lessons: list[EditLesson] = []
    issues: list[EditLoadIssue] = []
    ids: set[str] = set()
    try:
        entries = sorted(resources.iterdir(), key=lambda item: item.name)
    except OSError as error:
        return EditLoadReport((), (EditLoadIssue(str(resources), "$", str(error)),))
    for resource in entries:
        if not resource.name.endswith(".json"):
            continue
        try:
            lesson = load_edit_lesson_json(resource.read_text(encoding="utf-8"))
            if lesson.id in ids:
                raise EditContentError("id", f"과제 ID가 중복되었습니다: {lesson.id}")
        except ValidationError as error:
            for detail in error.errors(include_url=False):
                field = ".".join(str(part) for part in detail["loc"]) or "$"
                issues.append(EditLoadIssue(resource.name, field, detail["msg"]))
        except (ValueError, OSError) as error:
            field = error.field if isinstance(error, EditContentError) else "$"
            issues.append(EditLoadIssue(resource.name, field, str(error)))
        else:
            lessons.append(lesson)
            ids.add(lesson.id)
    if not lessons and not issues:
        issues.append(EditLoadIssue(str(resources), "$", "편집 과제 파일이 없습니다."))
    return EditLoadReport(tuple(lessons), tuple(issues))


def get_edit_lesson(lesson_id: str) -> EditLesson:
    report = load_edit_lessons()
    for lesson in report.lessons:
        if lesson.id == lesson_id:
            return lesson
    details = "\n".join(str(issue) for issue in report.issues)
    message = f"알 수 없거나 검증에 실패한 편집 과제입니다: {lesson_id}"
    raise ValueError(f"{message}\n{details}" if details else message)
