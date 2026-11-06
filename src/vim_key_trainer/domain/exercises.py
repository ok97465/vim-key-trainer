"""숫자·기호 연습 정의와 재현 가능한 문제 생성."""

# Standard library imports
from dataclasses import dataclass
from random import Random

NUMBERS = "1234567890"
SHIFT_SYMBOLS = "!@#$%^&*()"
OTHER_SYMBOLS = "-_ =+[]{}\\|;:'\",.<>/?`~".replace(" ", "")


@dataclass(frozen=True, slots=True)
class Exercise:
    id: str
    title: str
    description: str
    characters: str


EXERCISES = (
    Exercise("numbers", "숫자", "상단 숫자열의 0부터 9까지 익혀 보세요.", NUMBERS),
    Exercise(
        "shift_symbols",
        "Shift 기호",
        "Shift와 숫자 키로 입력하는 특수기호를 익혀 보세요.",
        SHIFT_SYMBOLS,
    ),
    Exercise(
        "symbols",
        "기타 기호",
        "괄호와 구두점 등 자주 쓰는 기호를 연습하세요.",
        OTHER_SYMBOLS,
    ),
    Exercise(
        "mixed",
        "숫자·기호 혼합",
        "숫자와 기호 사이를 자연스럽게 오가며 입력하세요.",
        NUMBERS + SHIFT_SYMBOLS + OTHER_SYMBOLS,
    ),
)


def get_exercise(exercise_id: str) -> Exercise:
    for exercise in EXERCISES:
        if exercise.id == exercise_id:
            return exercise
    raise ValueError(f"알 수 없는 연습입니다: {exercise_id}")


@dataclass(frozen=True, slots=True)
class PracticeSpec:
    exercise_id: str = "numbers"
    target_length: int = 100
    display_width: int = 20
    seed: int = 0

    def __post_init__(self) -> None:
        get_exercise(self.exercise_id)
        if not 1 <= self.target_length <= 10_000:
            raise ValueError("총 목표 길이는 1~10000자여야 합니다.")
        if not 1 <= self.display_width <= 80:
            raise ValueError("표시량은 1~80자여야 합니다.")


def generate_target(spec: PracticeSpec) -> str:
    rng = Random(spec.seed)
    characters = get_exercise(spec.exercise_id).characters
    return "".join(rng.choice(characters) for _ in range(spec.target_length))
