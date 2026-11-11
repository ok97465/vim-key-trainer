"""앱에 포함된 코드를 오프라인 연습 원문으로 읽는다."""

from __future__ import annotations

# Standard library imports
import json
import unicodedata
from functools import lru_cache
from importlib.resources import files
from importlib.resources.abc import Traversable
from pathlib import Path, PurePosixPath
from typing import Literal

# Third party imports
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    model_validator,
)

# Local imports
from vim_key_trainer.content.source_metadata import SourceSchema
from vim_key_trainer.domain.code_samples import CodeSource


class _CodeSourceSchema(SourceSchema):
    language: Literal["python", "cpp"]

    @model_validator(mode="after")
    def validate_excerpt_length(self) -> _CodeSourceSchema:
        if self.excerpt_end - self.excerpt_start + 1 < 500:
            raise ValueError("코드 원문은 최소 500줄이어야 합니다.")
        return self


class _ManifestSchema(BaseModel):
    model_config = ConfigDict(frozen=True)

    sources: tuple[_CodeSourceSchema, ...] = Field(min_length=1)


def normalize_code_lines(raw: str) -> tuple[str, ...]:
    """개행·탭·비ASCII만 변환하며 원문 물리 행과 일대일 대응을 유지한다."""
    raw = raw.replace("\r\n", "\n").replace("\r", "\n")
    lines = raw.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    result = tuple(
        unicodedata.normalize("NFKD", line.expandtabs(4))
        .encode("ascii", errors="replace")
        .decode("ascii")
        for line in lines
    )
    if any(not char.isprintable() for line in result for char in line):
        raise ValueError("코드 원문에 지원하지 않는 제어 문자가 있습니다.")
    return result


def _resource_root() -> Traversable:
    return files("vim_key_trainer").joinpath("resources", "code_corpus")


def _load_manifest(root: Traversable) -> _ManifestSchema:
    return _ManifestSchema.model_validate(
        json.loads(root.joinpath("manifest.json").read_text(encoding="utf-8"))
    )


def _load(root: Traversable) -> tuple[CodeSource, ...]:
    manifest = _load_manifest(root)
    result: list[CodeSource] = []
    ids: set[str] = set()
    for entry in manifest.sources:
        if entry.id in ids:
            raise ValueError(f"중복 코드 원문 ID: {entry.id}")
        ids.add(entry.id)
        source = entry.to_domain()
        raw = root.joinpath(*PurePosixPath(source.source_path).parts).read_text(
            encoding="utf-8"
        )
        lines = normalize_code_lines(raw)
        if source.excerpt_end > len(lines):
            raise ValueError(f"{source.id}: 발췌 범위가 실제 원문을 벗어났습니다.")
        selected = lines[source.excerpt_start - 1 : source.excerpt_end]
        result.append(CodeSource(source, selected))
    return tuple(sorted(result, key=lambda item: item.source.id))


@lru_cache(maxsize=1)
def _load_builtin() -> tuple[CodeSource, ...]:
    return _load(_resource_root())


def load_code_sources(root: Path | None = None) -> tuple[CodeSource, ...]:
    """번들은 한 번 읽고, 주입한 임시 경로는 매번 읽는다."""
    return _load_builtin() if root is None else _load(root)


def read_code_license(source_id: str) -> str:
    """등록된 원문 ID로 번들에 포함된 전체 라이선스를 읽는다."""
    root = _resource_root()
    for source in _load_manifest(root).sources:
        if source.id == source_id:
            return root.joinpath(*PurePosixPath(source.license_path).parts).read_text(
                encoding="utf-8"
            )
    raise ValueError(f"알 수 없는 코드 원문 ID입니다: {source_id}")
