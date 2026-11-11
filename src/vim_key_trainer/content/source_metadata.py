"""문서·코드의 출처 표기와 패키지 파일 경로를 읽는 공통 구조."""

from __future__ import annotations

# Standard library imports
from pathlib import PurePosixPath
from typing import Literal

# Third party imports
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)

# Local imports
from vim_key_trainer.domain.document_missions import MissionSource


class SourceSchema(BaseModel):
    """출처는 표시용이며 파일 접근에는 안전한 패키지 상대 경로만 사용한다."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: StrictStr = Field(pattern=r"^[a-z][a-z0-9_]*$")
    project: StrictStr
    title: StrictStr = Field(min_length=1)
    url: StrictStr
    raw_url: StrictStr
    revision: StrictStr
    license_id: StrictStr
    license_url: StrictStr
    license_raw_url: StrictStr
    language: Literal["text", "markdown", "python", "cpp"]
    source_path: StrictStr
    license_path: StrictStr
    excerpt_start: StrictInt = Field(ge=1)
    excerpt_end: StrictInt = Field(ge=1)
    transformation: StrictStr
    retrieved_on: StrictStr

    @field_validator("source_path", "license_path")
    @classmethod
    def validate_package_path(cls, value: str) -> str:
        path = PurePosixPath(value)
        if (
            path.is_absolute()
            or not path.parts
            or ".." in path.parts
            or "\\" in value
            or ":" in value
        ):
            raise ValueError("패키지 경로 범위를 벗어났습니다.")
        return value

    @model_validator(mode="after")
    def validate_excerpt(self) -> SourceSchema:
        if self.excerpt_end < self.excerpt_start:
            raise ValueError("원문 발췌 구간의 끝이 시작보다 작습니다.")
        return self

    def to_domain(self) -> MissionSource:
        return MissionSource(**self.model_dump())
