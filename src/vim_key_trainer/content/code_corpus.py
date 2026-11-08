"""고정 commit 코드·전체 라이선스를 검증하고 오프라인 연습 원문으로 읽는다."""

from __future__ import annotations

# Standard library imports
import hashlib
import json
import unicodedata
from datetime import date
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
    model_validator,
)

# Local imports
from vim_key_trainer.domain.code_samples import CodeSource
from vim_key_trainer.domain.document_missions import MissionSource

TRANSFORMATION = "ascii_nfkd_expandtabs4_v1"
_MAX_BYTES = 512_000


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
    language: Literal["python", "cpp"]
    source_path: StrictStr
    license_path: StrictStr
    excerpt_start: StrictInt = Field(ge=1)
    excerpt_end: StrictInt = Field(ge=500)
    transformation: Literal["ascii_nfkd_expandtabs4_v1"]
    retrieved_on: StrictStr

    @model_validator(mode="after")
    def validate_source(self) -> _SourceSchema:
        for name in ("source_path", "license_path"):
            value = getattr(self, name)
            path = PurePosixPath(value)
            if (
                path.is_absolute()
                or len(path.parts) != 2
                or path.parts[0] != self.id
                or ".." in path.parts
                or "\\" in value
                or ":" in value
            ):
                raise ValueError(f"{name}: 패키지 코드 경로 범위를 벗어났습니다.")
        if self.source_path == self.license_path:
            raise ValueError("원문과 라이선스 경로는 달라야 합니다.")
        for name in ("url", "raw_url", "license_url", "license_raw_url"):
            url = urlparse(getattr(self, name))
            raw = "raw" in name
            prefix = f"/{self.project}/{'' if raw else 'blob/'}{self.revision}/"
            remainder = url.path.removeprefix(prefix)
            if (
                url.scheme != "https"
                or url.netloc != ("raw.githubusercontent.com" if raw else "github.com")
                or not url.path.startswith(prefix)
                or not remainder
                or ".." in PurePosixPath(remainder).parts
                or url.query
                or url.fragment
            ):
                raise ValueError(f"{name}: 원문 URL은 동일 commit으로 고정해야 합니다.")
        if self.raw_url.rsplit(self.revision + "/", 1)[1] != self.title:
            raise ValueError("title: 원문 저장소의 파일 경로와 다릅니다.")
        if self.url.rsplit(self.revision + "/", 1)[1] != self.title:
            raise ValueError("url: 표시 URL과 원문 파일 경로가 다릅니다.")
        if (
            self.license_url.rsplit(self.revision + "/", 1)[1]
            != (self.license_raw_url.rsplit(self.revision + "/", 1)[1])
        ):
            raise ValueError("license_url: 표시 URL과 라이선스 파일 경로가 다릅니다.")
        if self.excerpt_end - self.excerpt_start + 1 < 500:
            raise ValueError("코드 원문은 최소 500줄이어야 합니다.")
        date.fromisoformat(self.retrieved_on)
        return self


class _ManifestSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: StrictInt = Field(ge=1, le=1)
    content_version: StrictInt = Field(ge=1)
    sources: tuple[_SourceSchema, ...] = Field(min_length=1)


def normalize_code_lines(raw: str) -> tuple[str, ...]:
    """개행·탭·비ASCII만 변환하며 원문 물리 행과 일대일 대응을 유지한다."""
    if any(ord(char) < 32 and char not in "\r\n\t" for char in raw):
        raise ValueError("코드 원문에 지원하지 않는 제어 문자가 있습니다.")
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
    if any(any(not char.isprintable() for char in line) for line in result):
        raise ValueError("코드 변환 결과는 표시 가능한 ASCII여야 합니다.")
    return result


def _resource_root() -> Traversable:
    return files("vim_key_trainer").joinpath("resources", "code_corpus")


def _read_verified(root: Traversable, path: str, digest: str) -> bytes:
    data = root.joinpath(*PurePosixPath(path).parts).read_bytes()
    if len(data) > _MAX_BYTES or hashlib.sha256(data).hexdigest() != digest:
        raise ValueError(f"{path}: 원문 또는 라이선스의 SHA-256 검증에 실패했습니다.")
    return data


def _license_text(root: Traversable, source: MissionSource) -> str:
    text = _read_verified(root, source.license_path, source.license_sha256).decode(
        "utf-8"
    )
    marker = (
        "Permission is hereby granted"
        if source.license_id == "MIT"
        else "Redistribution and use"
    )
    if marker not in text:
        raise ValueError(
            f"{source.license_path}: 허용 라이선스 원문을 확인할 수 없습니다."
        )
    return text


def _load(root: Traversable) -> tuple[CodeSource, ...]:
    manifest = _ManifestSchema.model_validate(
        json.loads(root.joinpath("manifest.json").read_text(encoding="utf-8"))
    )
    result: list[CodeSource] = []
    ids: set[str] = set()
    upstream_paths: set[tuple[str, str, str]] = set()
    for entry in manifest.sources:
        if entry.id in ids:
            raise ValueError(f"중복 코드 원문 ID: {entry.id}")
        location = (entry.project.casefold(), entry.revision, entry.title)
        if location in upstream_paths:
            raise ValueError(f"중복 코드 원문 파일: {entry.title}")
        ids.add(entry.id)
        upstream_paths.add(location)
        source = MissionSource(**entry.model_dump())
        raw = _read_verified(root, source.source_path, source.sha256).decode("utf-8")
        _license_text(root, source)
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
    """번들은 한 번 검증하고, 주입한 임시 경로는 매번 검증한다."""
    return _load_builtin() if root is None else _load(root)


def read_code_license(source_id: str) -> str:
    """등록된 원문 ID만 허용하고 전체 라이선스의 무결성을 다시 검사한다."""
    for entry in load_code_sources():
        if entry.source.id == source_id:
            return _license_text(_resource_root(), entry.source)
    raise ValueError(f"알 수 없는 코드 원문 ID입니다: {source_id}")
