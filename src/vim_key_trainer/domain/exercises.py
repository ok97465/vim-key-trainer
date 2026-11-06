"""숫자·기호 연습 정의와 재현 가능한 문제 생성."""

# Standard library imports
from dataclasses import dataclass
from random import Random

NUMBERS = "1234567890"
SHIFT_SYMBOLS = "!@#$%^&*()"
OTHER_SYMBOLS = "-_ =+[]{}\\|;:'\",.<>/?`~".replace(" ", "")
BRACKETS = "()[]{}<>"
QUOTES = "'\"`\\|"


@dataclass(frozen=True, slots=True)
class Exercise:
    id: str
    title: str
    description: str
    characters: str
    example: str = ""


EXERCISES = (
    Exercise(
        "numbers",
        "숫자 무작위",
        "상단 숫자열의 0부터 9까지 익혀 보세요.",
        NUMBERS,
        "1234567890",
    ),
    Exercise(
        "shift_symbols",
        "Shift 기호",
        "Shift와 숫자 키로 입력하는 특수기호를 익혀 보세요.",
        SHIFT_SYMBOLS,
        "!@#$%^&*()",
    ),
    Exercise(
        "bracket_pairs",
        "괄호쌍",
        "여는 괄호와 닫는 괄호, 중첩 괄호를 연속 입력해 보세요.",
        BRACKETS + NUMBERS,
        "()[{}]<>",
    ),
    Exercise(
        "quotes",
        "따옴표·역슬래시",
        "작은·큰따옴표, 백틱과 역슬래시·파이프를 집중 연습하세요.",
        QUOTES,
        "'\"`\\|",
    ),
    Exercise(
        "symbols",
        "기타 기호",
        "괄호와 구두점 등 자주 쓰는 기호를 연습하세요.",
        OTHER_SYMBOLS,
        "-_=+;:,./?",
    ),
    Exercise(
        "mixed",
        "숫자·기호 혼합",
        "숫자와 기호 사이를 자연스럽게 오가며 입력하세요.",
        NUMBERS + SHIFT_SYMBOLS + OTHER_SYMBOLS,
        "3$7[2!9]0%",
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
    if spec.exercise_id == "bracket_pairs":
        return _bracket_pairs(rng, spec.target_length)
    characters = get_exercise(spec.exercise_id).characters
    return "".join(rng.choice(characters) for _ in range(spec.target_length))


def _bracket_pairs(rng: Random, length: int) -> str:
    pairs_left = length // 2
    characters: list[str] = []
    closing: list[str] = []
    while pairs_left or closing:
        if pairs_left and (not closing or (len(closing) < 3 and rng.random() < 0.6)):
            index = rng.randrange(0, len(BRACKETS), 2)
            characters.append(BRACKETS[index])
            closing.append(BRACKETS[index + 1])
            pairs_left -= 1
        else:
            characters.append(closing.pop())
    if length % 2:
        characters.insert(1 if characters else 0, rng.choice(NUMBERS))
    return "".join(characters)
