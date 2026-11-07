"""문서 수정에서 주요 기술 과제를 선택하는 상대 비중. 필수 입력 수와 구분한다."""

# Standard library imports
from dataclasses import dataclass, fields

EDIT_TECHNIQUES: tuple[tuple[str, str], ...] = (
    ("movement", "이동·문자 찾기"),
    ("word", "단어·텍스트 객체"),
    ("insertion", "입력·추가"),
    ("copy", "복사·붙이기"),
    ("structure", "줄·문단 정리"),
    ("search", "검색·검색 재사용"),
    ("substitution", "치환"),
    ("visual", "범위 선택·대소문자"),
    ("repeat", "변경 반복"),
    ("numbers", "숫자·설정값"),
)


@dataclass(frozen=True, slots=True)
class EditTechniqueWeights:
    movement: int = 6
    word: int = 5
    insertion: int = 3
    copy: int = 2
    structure: int = 3
    search: int = 3
    substitution: int = 1
    visual: int = 2
    repeat: int = 2
    numbers: int = 2

    def __post_init__(self) -> None:
        values = [getattr(self, field.name) for field in fields(self)]
        if any(type(value) is not int or not 0 <= value <= 20 for value in values):
            raise ValueError("기술 비중은 0 이상 20 이하의 정수여야 합니다.")
        if not any(values):
            raise ValueError("한 가지 이상의 기술 비중을 1 이상으로 설정하세요.")

    def items(self) -> tuple[tuple[str, int], ...]:
        return tuple((name, int(getattr(self, name))) for name, _ in EDIT_TECHNIQUES)
