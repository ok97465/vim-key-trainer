"""Vim 명령 타이핑 콘텐츠와 재현 가능한 연습 조건."""

# Standard library imports
from dataclasses import dataclass
from typing import Literal

# Local imports
from vim_key_trainer.domain.keys import KeyToken

ExecutionSupport = Literal["typing_only", "editing"]


@dataclass(frozen=True, slots=True)
class CommandItem:
    id: str
    tokens: tuple[KeyToken, ...]
    meaning: str
    start_mode: str
    follow_up: str
    execution_support: ExecutionSupport = "typing_only"
    short_meaning: str = ""

    def __post_init__(self) -> None:
        if not all(value.strip() for value in (self.id, self.meaning, self.start_mode)):
            raise ValueError("명령 ID·의미·시작 모드는 비어 있을 수 없습니다.")
        if not self.tokens:
            raise ValueError("명령에는 하나 이상의 목표 키가 필요합니다.")
        if self.execution_support not in {"typing_only", "editing"}:
            raise ValueError("알 수 없는 명령 실행 지원 범위입니다.")
        if self.short_meaning and not self.short_meaning.strip():
            raise ValueError("짧은 명령 의미는 공백으로만 작성할 수 없습니다.")

    @property
    def display(self) -> str:
        return "".join(token.display for token in self.tokens)

    @property
    def brief_meaning(self) -> str:
        """기존 JSON 예제는 첫 문장을 쓰고 생성 명령은 전용 요약을 쓴다."""
        return self.short_meaning or self.meaning.partition(".")[0].strip()


@dataclass(frozen=True, slots=True)
class CommandLesson:
    schema_version: int
    content_version: int
    id: str
    title: str
    description: str
    difficulty: str
    tags: tuple[str, ...]
    display_count: int
    items: tuple[CommandItem, ...]

    def __post_init__(self) -> None:
        if self.schema_version != 1 or self.content_version < 1:
            raise ValueError("지원하는 스키마와 양수 콘텐츠 버전이 필요합니다.")
        if not all(
            value.strip()
            for value in (self.id, self.title, self.description, self.difficulty)
        ):
            raise ValueError("레슨 ID·제목·설명·난이도는 비어 있을 수 없습니다.")
        if not 8 <= self.display_count <= 12:
            raise ValueError("명령 표시량은 8~12개여야 합니다.")
        if not self.items:
            raise ValueError("레슨에는 하나 이상의 명령이 필요합니다.")
        if len({item.id for item in self.items}) != len(self.items):
            raise ValueError("레슨 내 명령 ID가 중복되었습니다.")


@dataclass(frozen=True, slots=True)
class CommandSpec:
    lesson_id: str
    seed: int = 0

    def __post_init__(self) -> None:
        if not self.lesson_id.strip():
            raise ValueError("명령 레슨 ID는 비어 있을 수 없습니다.")
        if self.seed < 0:
            raise ValueError("명령 문제 seed는 0 이상이어야 합니다.")
