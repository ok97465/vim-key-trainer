"""프로젝트별로 공평하게 고르는 코드 원문과 재현 가능한 연속 발췌."""

# Standard library imports
from dataclasses import dataclass
from random import Random

# Local imports
from vim_key_trainer.domain.document_missions import MissionSource


@dataclass(frozen=True, slots=True)
class CodeSource:
    """출처 정보와 ASCII 변환 원문. 코드를 실행하거나 파일을 수정하지 않는다."""

    source: MissionSource
    lines: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CodeExcerpt:
    source: MissionSource
    lines: tuple[str, ...]
    start_line: int

    @property
    def end_line(self) -> int:
        return self.start_line + len(self.lines) - 1


def choose_code_excerpt(
    sources: tuple[CodeSource, ...], language: str, count: int, rng: Random
) -> CodeExcerpt:
    """프로젝트 → 파일 → 시작 행 순서로 선택해 파일 수에 따른 편향을 막는다."""
    if language not in {"python", "cpp"}:
        raise ValueError("지원하지 않는 코드 언어입니다.")
    if type(count) is not int or not 300 <= count <= 500:
        raise ValueError("코드 발췌 길이는 300~500줄이어야 합니다.")
    projects: dict[str, list[CodeSource]] = {}
    for source in sources:
        if source.source.language == language and len(source.lines) >= count:
            projects.setdefault(source.source.project, []).append(source)
    if not projects:
        raise ValueError("요청한 길이의 코드 원문이 없습니다.")
    project = rng.choice(sorted(projects))
    source = rng.choice(sorted(projects[project], key=lambda item: item.source.id))
    start = rng.randrange(len(source.lines) - count + 1)
    return CodeExcerpt(
        source.source,
        source.lines[start : start + count],
        source.source.excerpt_start + start,
    )
