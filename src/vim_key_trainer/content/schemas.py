"""명령 레슨 JSON을 읽는 경계의 검증 모델."""

from __future__ import annotations

# Third party imports
from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, model_validator

# Local imports
from vim_key_trainer.domain.commands import CommandItem, CommandLesson, ExecutionSupport
from vim_key_trainer.domain.keys import KeyKind, KeyToken


class KeyTokenSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: KeyKind
    value: StrictStr

    @model_validator(mode="after")
    def validate_token(self) -> KeyTokenSchema:
        KeyToken(kind=self.kind, value=self.value)
        if self.kind == "special" and self.value not in {
            "esc",
            "enter",
            "backspace",
            "tab",
            "delete",
            "insert",
            "left",
            "right",
            "up",
            "down",
            "home",
            "end",
            "pageup",
            "pagedown",
        }:
            raise ValueError("레슨에서 지원하지 않는 특수 키입니다.")
        if self.kind == "chord" and self.value != "ctrl+r":
            raise ValueError("명령 레슨의 조합 키는 ctrl+r만 지원합니다.")
        return self

    def to_domain(self) -> KeyToken:
        return KeyToken(kind=self.kind, value=self.value)


class CommandItemSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: StrictStr = Field(pattern=r"^[a-z][a-z0-9_]*$")
    tokens: tuple[KeyTokenSchema, ...] = Field(min_length=1, max_length=100)
    meaning: StrictStr = Field(min_length=1)
    start_mode: StrictStr = Field(min_length=1)
    follow_up: StrictStr
    execution_support: ExecutionSupport

    @model_validator(mode="after")
    def validate_text(self) -> CommandItemSchema:
        if not self.meaning.strip() or not self.start_mode.strip():
            raise ValueError("명령 의미와 시작 모드는 비어 있을 수 없습니다.")
        return self

    def to_domain(self) -> CommandItem:
        return CommandItem(
            id=self.id,
            tokens=tuple(token.to_domain() for token in self.tokens),
            meaning=self.meaning,
            start_mode=self.start_mode,
            follow_up=self.follow_up,
            execution_support=self.execution_support,
        )


class CommandLessonSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: StrictInt = Field(ge=1, le=1)
    content_version: StrictInt = Field(ge=1)
    stage: StrictStr = Field(pattern=r"^commands$")
    id: StrictStr = Field(pattern=r"^[a-z][a-z0-9_]*$")
    title: StrictStr = Field(min_length=1)
    description: StrictStr = Field(min_length=1)
    difficulty: StrictStr = Field(min_length=1)
    tags: tuple[StrictStr, ...]
    display_count: StrictInt = Field(ge=8, le=12)
    items: tuple[CommandItemSchema, ...] = Field(min_length=1, max_length=1_000)

    @model_validator(mode="after")
    def validate_lesson(self) -> CommandLessonSchema:
        if not all(
            text.strip() for text in (self.title, self.description, self.difficulty)
        ):
            raise ValueError("레슨 안내 문구는 비어 있을 수 없습니다.")
        if any(not tag.strip() for tag in self.tags):
            raise ValueError("레슨 태그는 비어 있을 수 없습니다.")
        ids = [item.id for item in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("명령 항목 ID는 레슨 안에서 고유해야 합니다.")
        return self

    def to_domain(self) -> CommandLesson:
        return CommandLesson(
            schema_version=self.schema_version,
            content_version=self.content_version,
            id=self.id,
            title=self.title,
            description=self.description,
            difficulty=self.difficulty,
            tags=self.tags,
            display_count=self.display_count,
            items=tuple(item.to_domain() for item in self.items),
        )
