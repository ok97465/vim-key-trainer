"""의미·문맥·조합 규칙을 함께 가진 Vim 명령의 재현 가능한 생성기.

문자열을 무작위로 이어 붙이지 않는다. 연산자와 motion/text object의
count 정책을 확인한 뒤 토큰과 한국어 설명을 같은 규칙에서 만든다.
"""

# Standard library imports
import hashlib
from collections import deque
from dataclasses import dataclass
from random import Random
from string import ascii_letters, ascii_lowercase, digits
from typing import Literal

# Local imports
from vim_key_trainer.domain.commands import CommandItem
from vim_key_trainer.domain.keys import KeyToken
from vim_key_trainer.domain.practice_words import practice_word

GENERATOR_VERSION = 4
MAX_COUNT = 99
MAX_COMBINED_COUNT = 999
CommandFamily = Literal[
    "movement",
    "screen",
    "find",
    "operator_motion",
    "operator_object",
    "line_operator",
    "insert",
    "history",
    "context",
    "sequence",
    "simple_edit",
    "search",
    "normal_tools",
]
CountPolicy = Literal["repeat", "line", "end_line", "none"]
_MAX_GENERATION_ATTEMPTS = 24


@dataclass(frozen=True, slots=True)
class CommandProfile:
    id: str
    title: str
    description: str
    families: tuple[CommandFamily, ...]
    content_version: int = 1
    display_count: int = 10
    difficulty: str = "mixed"
    example: str = ""

    def __post_init__(self) -> None:
        if not all(text.strip() for text in (self.id, self.title, self.description)):
            raise ValueError("생성 프로필의 ID·제목·설명은 비어 있을 수 없습니다.")
        if self.content_version < 1 or not 8 <= self.display_count <= 12:
            raise ValueError("양수 콘텐츠 버전과 8~12개 표시량이 필요합니다.")
        if not self.families or len(set(self.families)) != len(self.families):
            raise ValueError("중복 없는 생성 명령 종류가 필요합니다.")
        if any(family not in _ALL_FAMILIES for family in self.families):
            raise ValueError("지원하지 않는 생성 명령 종류입니다.")
        if self.example and not self.example.strip():
            raise ValueError("명령 예시는 공백으로만 작성할 수 없습니다.")


_ALL_FAMILIES: tuple[CommandFamily, ...] = (
    "movement",
    "screen",
    "find",
    "operator_motion",
    "operator_object",
    "line_operator",
    "insert",
    "history",
    "context",
    "sequence",
    "simple_edit",
    "search",
    "normal_tools",
)
COMMAND_PROFILES = (
    CommandProfile(
        "commands_random",
        "명령 조합 · 전체",
        "이동·검색·연산자·텍스트 객체·입력과 복합 편집을 계속 생성합니다.",
        _ALL_FAMILIES,
        content_version=3,
        example="3j  ciw  dW  zz",
    ),
    CommandProfile(
        "commands_movement_random",
        "이동·화면 이동",
        "횟수·word/WORD 이동·문자 찾기·검색·화면 위치를 조합합니다.",
        ("movement", "screen", "find", "search"),
        content_version=3,
        example="W  B  2E  22gg  f,  zz",
    ),
    CommandProfile(
        "commands_operators_random",
        "삭제·변경·복사",
        "이동 범위와 줄을 지정해 삭제·변경·복사를 집중 연습합니다.",
        (
            "operator_motion",
            "line_operator",
            "simple_edit",
        ),
        content_version=3,
        example="dw  dW  de  dE  2dd  yy",
    ),
    CommandProfile(
        "commands_objects_random",
        "텍스트 객체",
        "diw·diW로 word/WORD 안쪽을 고르고 따옴표·괄호 범위도 연습합니다.",
        ("operator_object",),
        content_version=2,
        example='diw  diW  ciw  daw  di(  yi"',
    ),
    CommandProfile(
        "commands_insert_random",
        "문자 입력·특수키",
        "i·a·I·A와 실제 Esc·Enter·Backspace 입력을 반복합니다.",
        ("insert",),
        content_version=3,
        example="iab<Esc>  A!<Esc>",
    ),
    CommandProfile(
        "commands_context_random",
        "이력·레지스터·복합 명령",
        "undo·redo, 레지스터·검색 이력·줄 편집과 여러 명령의 연결을 연습합니다.",
        ("history", "context", "sequence", "normal_tools"),
        content_version=3,
        example='u<C-r>  qa  "+y  jdiw',
    ),
)


def list_command_profiles() -> tuple[CommandProfile, ...]:
    return COMMAND_PROFILES


def get_command_profile(profile_id: str) -> CommandProfile:
    for profile in COMMAND_PROFILES:
        if profile.id == profile_id:
            return profile
    raise ValueError(f"알 수 없는 명령 생성 프로필입니다: {profile_id}")


@dataclass(frozen=True, slots=True)
class Motion:
    keys: str
    meaning: str
    count_policy: CountPolicy = "repeat"


@dataclass(frozen=True, slots=True)
class TextObject:
    keys: str
    meaning: str
    max_count: int = MAX_COUNT
    note: str = ""
    short_scope: str = ""


@dataclass(frozen=True, slots=True)
class Operator:
    keys: str
    meaning: str
    enters_insert: bool = False
    register_allowed: bool = True


MOTIONS = (
    Motion("h", "왼쪽 문자 이동"),
    Motion("j", "아래 줄 이동"),
    Motion("k", "위 줄 이동"),
    Motion("l", "오른쪽 문자 이동"),
    Motion("w", "word의 다음 시작으로 이동"),
    Motion("W", "공백으로 구분한 WORD의 다음 시작으로 이동"),
    Motion("b", "word의 시작으로 뒤로 이동"),
    Motion("B", "공백으로 구분한 WORD의 시작으로 뒤로 이동"),
    Motion("e", "word의 끝으로 앞으로 이동"),
    Motion("E", "공백으로 구분한 WORD의 끝으로 앞으로 이동"),
    Motion("ge", "이전 word의 끝으로 이동"),
    Motion("gE", "이전 WORD의 끝으로 이동"),
    Motion("0", "현재 줄의 첫 문자로 이동", "none"),
    Motion("^", "현재 줄의 첫 공백 아닌 문자로 이동", "none"),
    Motion("$", "줄의 마지막 문자로 이동", "end_line"),
    Motion("gg", "문서 첫 줄로 이동", "line"),
    Motion("G", "문서 마지막 줄로 이동", "line"),
)
OPERATORS = (
    Operator("d", "삭제"),
    Operator("c", "변경", enters_insert=True),
    Operator("y", "yank하여 레지스터에 복사"),
    Operator("gu", "소문자로 변경", register_allowed=False),
    Operator("gU", "대문자로 변경", register_allowed=False),
    Operator("g~", "대소문자 전환", register_allowed=False),
)
_WORD_NOTE = "iw/iW의 횟수는 단어 사이 공백도 셉니다."
TEXT_OBJECTS = (
    TextObject("iw", "inner word 범위", note=_WORD_NOTE, short_scope="현재 단어"),
    TextObject(
        "iW",
        "공백으로 구분한 inner WORD 범위",
        note=_WORD_NOTE,
        short_scope="현재 WORD",
    ),
    TextObject("aw", "주변 공백을 포함한 word 범위", short_scope="단어와 공백"),
    TextObject("aW", "주변 공백을 포함한 WORD 범위", short_scope="WORD와 공백"),
    TextObject("is", "문장 내부 범위", short_scope="문장 내부"),
    TextObject("as", "공백을 포함한 문장 범위", short_scope="문장과 공백"),
    TextObject("ip", "문단 내부 범위", short_scope="문단 내부"),
    TextObject("ap", "주변 빈 줄을 포함한 문단 범위", short_scope="문단과 빈 줄"),
    *(
        TextObject(
            prefix + delimiter,
            f"{name}{' 내부' if prefix == 'i' else ' 포함'} 범위",
            3,
            short_scope=f"{name}{' 안쪽' if prefix == 'i' else ' 포함'}",
        )
        for prefix in ("i", "a")
        for delimiter, name in (
            ("(", "소괄호"),
            ("[", "대괄호"),
            ("{", "중괄호"),
            ("<", "꺾쇠괄호"),
        )
    ),
    *(
        TextObject(
            prefix + quote,
            f"{name}{' 내부' if prefix == 'i' else ' 포함'} 문자열 범위",
            1,
            "같은 줄에 대응하는 따옴표가 있어야 합니다.",
            short_scope=f"{name}{' 안쪽' if prefix == 'i' else ' 포함'}",
        )
        for prefix in ("i", "a")
        for quote, name in (('"', "큰따옴표"), ("'", "작은따옴표"), ("`", "백틱"))
    ),
)
_ESC = KeyToken("special", "esc")
_ENTER = KeyToken("special", "enter")
_BACKSPACE = KeyToken("special", "backspace")
_REDO = KeyToken("chord", "ctrl+r")
_COMPLETE = "여기서 완결됩니다. 다음 항목은 독립된 Normal 모드 문맥에서 시작합니다."
_INSERT_FOLLOW_UP = (
    "Insert 진입 조각입니다. 실제 Vim에서는 바꿀 문자 입력과 Esc 복귀가 더 필요합니다."
)


def _characters(text: str) -> tuple[KeyToken, ...]:
    return tuple(KeyToken("char", character) for character in text)


def _item(
    tokens: tuple[KeyToken, ...],
    meaning: str,
    follow_up: str = _COMPLETE,
    *,
    short_meaning: str = "",
) -> CommandItem:
    signature = "|".join(f"{token.kind}:{token.value}" for token in tokens)
    item_id = "generated_" + hashlib.sha256(signature.encode("ascii")).hexdigest()[:20]
    return CommandItem(
        item_id, tokens, meaning, "Normal", follow_up, "typing_only", short_meaning
    )


def _prefix(count: int) -> str:
    return str(count) if count > 1 else ""


def _motion_description(motion: Motion, count: int) -> str:
    if motion.count_policy == "line" and count > 1:
        return f"문서의 {count}번째 줄로 이동"
    if motion.count_policy == "end_line":
        return (
            "현재 줄의 끝으로 이동"
            if count == 1
            else f"현재 줄부터 {count}번째 줄의 끝으로 이동"
        )
    return motion.meaning if count == 1 else f"{motion.meaning}을 {count}회 적용"


def _motion_brief(motion: Motion, count: int, *, operation: bool = False) -> str:
    """선택된 motion과 횟수에서 짧은 이동/연산 범위를 함께 만든다."""
    if motion.keys in {"h", "j", "k", "l"}:
        direction, unit = {
            "h": ("왼쪽", "문자"),
            "j": ("아래", "줄"),
            "k": ("위", "줄"),
            "l": ("오른쪽", "문자"),
        }[motion.keys]
        # 수직 operator motion은 현재 줄도 포함한다.
        distance = count + 1 if operation and unit == "줄" else count
        return f"{direction} {distance}{unit}" + ("" if operation else " 이동")
    if motion.keys in {"0", "^", "$"}:
        place = {"0": "줄 맨 앞", "^": "첫 글자(공백 제외)", "$": "줄 끝"}[motion.keys]
        if motion.keys == "$" and count > 1:
            place = f"{count}번째 줄 끝"
        return place + ("까지" if operation else "으로 이동")
    if motion.keys in {"gg", "G"}:
        place = (
            f"{count}번째 줄"
            if count > 1
            else ("문서 첫 줄" if motion.keys == "gg" else "문서 마지막 줄")
        )
        return place + ("까지" if operation else "로 이동")
    word = "WORD" if motion.keys in {"W", "B", "E", "gE"} else "단어"
    places = {
        "w": "다음 {word} 앞",
        "W": "다음 {word} 앞",
        "b": "{word} 시작으로 뒤로",
        "B": "{word} 시작으로 뒤로",
        "e": "{word} 끝",
        "E": "{word} 끝",
        "ge": "이전 {word} 끝",
        "gE": "이전 {word} 끝",
    }
    place = places[motion.keys].format(word=word)
    if motion.keys in {"b", "B"}:
        result = place + (" 간 범위" if operation else " 이동")
    else:
        result = place + ("까지" if operation else "으로 이동")
    return result if count == 1 else f"{result}({count}회)"


def _operation_brief(operator: Operator, scope: str, destination: str) -> str:
    action = {
        "d": "삭제",
        "c": "변경 → 입력 모드",
        "y": "복사",
        "gu": "소문자로",
        "gU": "대문자로",
        "g~": "대소문자 전환",
    }[operator.keys]
    result = f"{scope} {action}"
    if destination:
        result += f" → {destination} 보관"
    return result


class CommandGenerator:
    def __init__(self, profile: CommandProfile, seed: int = 0) -> None:
        if seed < 0:
            raise ValueError("명령 생성 seed는 0 이상이어야 합니다.")
        self.profile = profile
        self._random = Random(seed)
        self._family_bag: list[CommandFamily] = []
        self._recent: deque[tuple[KeyToken, ...]] = deque(maxlen=2)

    def next_item(self) -> CommandItem:
        """가족별 셔플 묶음으로 편중을 줄이고 직전과 다른 명령을 만든다."""
        if not self._family_bag:
            self._family_bag = list(self.profile.families)
            self._random.shuffle(self._family_bag)
        family = self._family_bag.pop()
        fallback: CommandItem | None = None
        for _ in range(_MAX_GENERATION_ATTEMPTS):
            candidate = self._generate(family)
            if not self._recent or candidate.tokens != self._recent[-1]:
                fallback = candidate
            if candidate.tokens not in self._recent:
                break
        else:
            candidate = fallback or self._fallback(family)
        self._recent.append(candidate.tokens)
        return candidate

    def _fallback(self, family: CommandFamily) -> CommandItem:
        """독립된 난수 흐름으로 기존 문법과 설명을 재사용한다."""
        # 원래 난수의 상태를 보존하고, 직전 명령만 피하도록 제한을 완화한다.
        fallback = CommandGenerator(self.profile, seed=0)
        for _ in range(_MAX_GENERATION_ATTEMPTS):
            candidate = fallback._generate(family)
            if not self._recent or candidate.tokens != self._recent[-1]:
                return candidate
        raise RuntimeError(f"서로 다른 명령을 생성할 수 없습니다: {family}")

    def _count(self, maximum: int = MAX_COUNT) -> int:
        if maximum == 1 or self._random.random() < 0.55:
            return 1
        if maximum > 9 and self._random.random() < 0.8:
            return self._random.randint(2, 9)
        return self._random.randint(2, maximum)

    def _counts(
        self, maximum: int = MAX_COUNT, *, combined_maximum: int = MAX_COMBINED_COUNT
    ) -> tuple[int, int]:
        first = self._count(maximum)
        second = self._count(min(maximum, combined_maximum // first))
        return first, second

    def _generate(self, family: CommandFamily) -> CommandItem:
        builders = {
            "movement": self._movement,
            "screen": self._screen,
            "find": self._find,
            "operator_motion": self._operator_motion,
            "operator_object": self._operator_object,
            "line_operator": self._line_operator,
            "insert": self._insert,
            "history": self._history,
            "context": self._context,
            "sequence": self._sequence,
            "simple_edit": self._simple_edit,
            "search": self._search,
            "normal_tools": self._normal_tools,
        }
        return builders[family]()

    def _movement(self) -> CommandItem:
        motion = self._random.choice(MOTIONS)
        count = self._count() if motion.count_policy != "none" else 1
        return _item(
            _characters(_prefix(count) + motion.keys),
            _motion_description(motion, count) + "합니다.",
            short_meaning=_motion_brief(motion, count),
        )

    def _screen(self) -> CommandItem:
        keys, position = self._random.choice(
            (("zz", "가운데"), ("zt", "맨 위"), ("zb", "맨 아래"))
        )
        return _item(
            _characters(keys),
            f"현재 커서 줄이 화면 {position}에 보이도록 스크롤합니다. "
            "커서 열은 유지합니다.",
            short_meaning=f"커서 줄을 화면 {position}로",
        )

    def _find(self) -> CommandItem:
        command = self._random.choice(("f", "F", "t", "T"))
        target = self._random.choice(ascii_letters + digits + "_.,;:()[]{}<>/='\"")
        count = self._count()
        direction = "오른쪽" if command.islower() else "왼쪽"
        stop = "문자 위" if command in "fF" else "찾은 문자의 바로 앞(진행 방향 기준)"
        return _item(
            _characters(_prefix(count) + command + target),
            f"같은 줄 {direction}의 {count}번째 {target!r}를 찾아 {stop}에 멈춥니다.",
            "해당 방향에 찾는 문자가 있어야 이동합니다. 다음 항목은 독립된 문맥입니다.",
            short_meaning=(
                f"{direction} {count}번째 {target!r} "
                + ("위로 이동" if command in "fF" else "직전까지 이동")
            ),
        )

    def _register(self, operator: Operator) -> tuple[str, str, str]:
        if not operator.register_allowed or self._random.random() < 0.85:
            return "", "", ""
        register = self._random.choice(ascii_lowercase + "+")
        note = f" {register} 레지스터를 지정합니다."
        if register == "+":
            note += " 실제 Vim의 클립보드 지원이 필요하며 "
            note += "이 앱은 클립보드에 접근하지 않습니다."
        destination = "클립보드" if register == "+" else f"{register} 레지스터"
        return '"' + register, note, destination

    def _operator_motion(self) -> CommandItem:
        operator = self._random.choices(OPERATORS, weights=(4, 4, 3, 1, 1, 1))[0]
        motion = self._random.choices(
            MOTIONS, weights=tuple(4 if motion.keys == "w" else 2 for motion in MOTIONS)
        )[0]
        if motion.count_policy == "none":
            first, second = 1, 1
        else:
            first, second = self._counts()
        count = first * second
        register, register_note, destination = self._register(operator)
        text = register + _prefix(first) + operator.keys + _prefix(second) + motion.keys
        meaning = (
            f"{_motion_description(motion, count)}의 범위를 {operator.meaning}합니다."
        )
        if operator.keys == "c" and motion.keys in {"w", "W"}:
            meaning = (
                f"커서가 단어 안에 있으면 현재 위치부터 {count}번째 "
                f"{'WORD' if motion.keys == 'W' else 'word'} 끝까지 바꾸고 "
                "Insert로 진입합니다. "
                "cw/cW는 뒤따르는 공백을 포함하지 않는 특별 규칙이 있습니다."
            )
        elif operator.enters_insert:
            meaning += " 이후 Insert 모드로 진입합니다."
        if first > 1 and second > 1:
            meaning += f" 횟수 {first}×{second}={count}를 적용합니다."
        scope = _motion_brief(motion, count, operation=True)
        if operator.keys == "c" and motion.keys in {"w", "W"}:
            word = "WORD" if motion.keys == "W" else "단어"
            scope = "커서부터 " + (f"{count}번째 " if count > 1 else "") + word + " 끝"
        return _item(
            _characters(text),
            meaning + register_note,
            _INSERT_FOLLOW_UP if operator.enters_insert else _COMPLETE,
            short_meaning=_operation_brief(operator, scope, destination),
        )

    def _operator_object(self) -> CommandItem:
        operator = self._random.choices(OPERATORS, weights=(4, 4, 3, 1, 1, 1))[0]
        target = self._random.choices(
            TEXT_OBJECTS, weights=(4, 2, 3, 2) + (1,) * (len(TEXT_OBJECTS) - 4)
        )[0]
        first, second = self._counts(
            target.max_count, combined_maximum=target.max_count
        )
        count = first * second
        register, register_note, destination = self._register(operator)
        text = register + _prefix(first) + operator.keys + _prefix(second) + target.keys
        meaning = f"{target.meaning}에 횟수 {count}를 적용해 {operator.meaning}합니다."
        if operator.enters_insert:
            meaning += " 이후 Insert 모드로 진입합니다."
        if target.note:
            meaning += " " + target.note
        if target.max_count == 3 and count > 1:
            meaning += " 괄호 횟수는 바깥쪽 중첩 범위를 선택합니다."
        if first > 1 and second > 1:
            meaning += f" 횟수 {first}×{second}={count}입니다."
        scope = target.short_scope
        if count > 1:
            scope = (
                f"{count}겹 바깥 {scope}"
                if target.max_count == 3
                else f"{scope} {count}단위"
            )
        return _item(
            _characters(text),
            meaning + register_note,
            _INSERT_FOLLOW_UP if operator.enters_insert else _COMPLETE,
            short_meaning=_operation_brief(operator, scope, destination),
        )

    def _line_operator(self) -> CommandItem:
        operator = self._random.choice(OPERATORS[:3])
        first, second = self._counts()
        count = first * second
        register, register_note, destination = self._register(operator)
        text = (
            register + _prefix(first) + operator.keys + _prefix(second) + operator.keys
        )
        meaning = f"현재 줄부터 {count}줄을 {operator.meaning}합니다."
        if operator.enters_insert:
            meaning += " 이후 Insert 모드로 진입합니다."
        if first > 1 and second > 1:
            meaning += f" 횟수 {first}×{second}={count}입니다."
        return _item(
            _characters(text),
            meaning + register_note,
            _INSERT_FOLLOW_UP if operator.enters_insert else _COMPLETE,
            short_meaning=_operation_brief(
                operator, f"현재부터 {count}줄", destination
            ),
        )

    def _text(self) -> str:
        variant = self._random.randrange(6)
        if variant == 0:
            return self._random.choice(ascii_letters + digits + "_!#")
        word = practice_word(self._random)
        if variant == 1:
            return word + " " + practice_word(self._random, exclude=(word,))
        if variant == 2:
            return word.capitalize()
        return word

    def _simple_edit(self) -> CommandItem:
        command = self._random.choice(("x", "X", "D", "C", "s", "S", "p", "P", "r"))
        count = self._count()
        text = _prefix(count) + command
        meanings = {
            "x": f"커서 아래부터 오른쪽으로 {count}문자를 삭제합니다.",
            "X": f"커서 앞의 {count}문자를 삭제합니다.",
            "D": (
                "커서부터 현재 줄 끝까지 삭제합니다."
                if count == 1
                else f"커서부터 줄 끝과 다음 {count - 1}줄을 삭제합니다."
            ),
            "C": (
                "커서부터 현재 줄 끝까지 바꾸고 Insert로 진입합니다."
                if count == 1
                else f"커서부터 줄 끝과 다음 {count - 1}줄을 바꾸고 "
                "Insert로 진입합니다."
            ),
            "s": f"커서 아래부터 {count}문자를 바꾸고 Insert로 진입합니다.",
            "S": f"현재 줄부터 {count}줄을 바꾸고 Insert로 진입합니다.",
            "p": f"레지스터 내용을 {count}회 커서 뒤에 붙입니다. "
            "줄 단위 내용이면 다음 줄에 붙입니다.",
            "P": f"레지스터 내용을 {count}회 커서 앞에 붙입니다. "
            "줄 단위 내용이면 이전 줄에 붙입니다.",
        }
        if command == "r":
            character = self._random.choice(ascii_letters + digits + "_.,;:!?=+-")
            text += character
            meaning = (
                f"커서 아래부터 같은 줄의 {count}문자를 "
                f"각각 {character!r}로 교체합니다."
            )
            brief = f"{count}문자를 {character!r}로 교체"
        else:
            meaning = meanings[command]
            brief = {
                "x": f"커서부터 {count}문자 삭제",
                "X": f"커서 앞 {count}문자 삭제",
                "D": "줄 끝까지 삭제" if count == 1 else f"{count}번째 줄 끝까지 삭제",
                "C": "줄 끝 변경 → 입력 모드"
                if count == 1
                else f"{count}번째 줄 끝 변경 → 입력 모드",
                "s": f"{count}문자 변경 → 입력 모드",
                "S": f"{count}줄 변경 → 입력 모드",
                "p": f"레지스터 내용을 뒤에 {count}회 붙이기",
                "P": f"레지스터 내용을 앞에 {count}회 붙이기",
            }[command]
        follow_up = _INSERT_FOLLOW_UP if command in {"C", "s", "S"} else _COMPLETE
        if command in {"p", "P"}:
            follow_up = (
                "실제 Vim에서는 레지스터 내용이 필요합니다. "
                "이 앱의 명령 타이핑 연습은 내용을 읽거나 붙이지 않습니다."
            )
        return _item(_characters(text), meaning, follow_up, short_meaning=brief)

    def _insert(self) -> CommandItem:
        command, location = self._random.choice(
            (
                ("i", "커서 앞"),
                ("a", "커서 뒤"),
                ("I", "줄의 첫 공백 아닌 문자 앞"),
                ("A", "줄 끝"),
                ("o", "현재 줄 아래의 새 줄"),
                ("O", "현재 줄 위의 새 줄"),
            )
        )
        tokens = _characters(command + self._text())
        variant = self._random.randrange(4)
        detail = ""
        brief_detail = ""
        if variant == 1:
            tokens += (KeyToken("char", " "),) + _characters(self._text())
            detail = " 실제 Space도 입력합니다."
            brief_detail = "·공백"
        elif variant == 2:
            tokens += (_ENTER,) + _characters(self._text())
            detail = " 실제 Enter로 줄을 나누어 입력합니다."
            brief_detail = "·줄바꿈"
        elif variant == 3:
            tokens += (_BACKSPACE,) + _characters(self._text())
            detail = (
                " 실제 Backspace로 방금 입력한 문자 하나를 지운 후 이어 입력합니다."
            )
            brief_detail = "·한 글자 지우기"
        return _item(
            tokens + (_ESC,),
            f"{command}로 {location}에 문자를 입력하고 "
            "실제 Esc로 Normal 모드에 돌아옵니다." + detail,
            short_meaning=f"{location}에 입력{brief_detail} → Esc",
        )

    def _history(self) -> CommandItem:
        tokens, meaning, brief = self._random.choice(
            (
                (
                    _characters("u"),
                    "마지막 변경 하나를 되돌립니다.",
                    "마지막 변경 되돌리기",
                ),
                (
                    (_REDO,),
                    "실제 Control+R로 되돌렸던 변경 하나를 다시 적용합니다.",
                    "되돌린 변경 다시 적용",
                ),
                (
                    _characters("u") + (_REDO,),
                    "u로 변경 하나를 되돌리고 실제 Control+R로 다시 적용합니다.",
                    "변경 되돌리기 → 다시 적용",
                ),
            )
        )
        return _item(
            tokens,
            meaning,
            "실제 Vim에서는 undo 이력이 필요합니다. 항목 간 이력은 이어지지 않습니다.",
            short_meaning=brief,
        )

    def _search(self) -> CommandItem:
        command = self._random.choice(("/", "?", "n", "N", "*", "#"))
        count = self._count()
        if command in {"/", "?"}:
            pattern = practice_word(self._random)
            variant = self._random.randrange(6)
            if variant == 0:
                pattern += " " + practice_word(self._random, exclude=(pattern,))
            elif variant == 1 and len(pattern) > 4:
                pattern = pattern[: self._random.randrange(3, len(pattern))]
            elif variant == 2:
                pattern = pattern.capitalize()
            direction = "앞" if command == "/" else "뒤"
            return _item(
                _characters(command + pattern) + (_ENTER,),
                f"{command}로 {pattern!r}을 {direction}으로 검색하고 "
                "실제 Enter로 확정합니다.",
                "검색어가 있는 문맥을 가정합니다. 문서 끝에서는 처음으로 순환합니다.",
                short_meaning=f"{pattern!r} {direction}으로 검색 → Enter",
            )
        if command in {"*", "#"}:
            direction = "앞" if command == "*" else "뒤"
            meaning = (
                f"현재 word와 같은 단어의 {count}번째 위치를 {direction}으로 찾습니다."
            )
            note = "커서 아래에 ASCII word가 있는 독립된 문맥입니다."
            brief = f"현재 단어 {direction}으로 검색 · {count}회"
        else:
            direction = "같은 방향" if command == "n" else "반대 방향"
            meaning = f"마지막 검색을 {direction}으로 {count}회 반복합니다."
            note = "이전에 확정한 검색어와 방향이 있는 독립된 문맥입니다."
            brief = f"검색 {direction}으로 반복 · {count}회"
        return _item(
            _characters(_prefix(count) + command), meaning, note, short_meaning=brief
        )

    def _normal_tools(self) -> CommandItem:
        variant = self._random.randrange(10)
        count = self._count()
        prefix = _prefix(count)
        note = _COMPLETE
        if variant == 0:
            chord = self._random.choice(("ctrl+a", "ctrl+x"))
            action = "증가" if chord == "ctrl+a" else "감소"
            tokens = _characters(prefix) + (KeyToken("chord", chord),)
            brief = f"숫자 {count}만큼 {action}"
            note = "커서 위치나 같은 줄 오른쪽에 수정할 10진수가 있어야 합니다."
        elif variant == 1:
            command = self._random.choice((">>", "<<"))
            tokens = _characters(prefix + command)
            brief = f"현재부터 {count}줄 " + (
                "들여쓰기" if command == ">>" else "내어쓰기"
            )
        elif variant == 2:
            tokens = _characters(prefix + "J")
            brief = f"{max(2, count)}줄을 공백을 정리하며 합치기"
        elif variant == 3:
            tokens = _characters(prefix + "~")
            brief = f"{count}문자 대소문자 전환"
        elif variant == 4:
            tokens = _characters(prefix + ".")
            brief = "마지막 변경 반복" + (f" · 횟수 {count}" if count > 1 else "")
            note = "앞서 반복 가능한 문서 변경이 있는 독립된 문맥입니다."
        elif variant == 5:
            chord, brief = self._random.choice(
                (
                    ("ctrl+u", "반 화면 위로 이동"),
                    ("ctrl+d", "반 화면 아래로 이동"),
                    ("ctrl+f", "다음 페이지로 이동"),
                    ("ctrl+b", "이전 페이지로 이동"),
                    ("ctrl+e", "보기를 한 줄 아래로 스크롤"),
                    ("ctrl+y", "보기를 한 줄 위로 스크롤"),
                )
            )
            tokens = (KeyToken("chord", chord),)
        elif variant == 6:
            action, verb = self._random.choice(
                (("d", "삭제"), ("y", "복사"), ("~", "대소문자 전환"))
            )
            tokens = _characters("v" + prefix + "l" + action)
            brief = f"Visual로 오른쪽 {count}칸 선택 후 {verb}"
            note = "선택 범위가 같은 줄 안에 있는 독립된 문맥입니다."
        elif variant == 7:
            tokens = _characters("R" + self._text()) + (_ESC,)
            brief = "Replace 모드에서 덮어쓰기 → Esc"
        elif variant == 8:
            name = self._random.choice(ascii_lowercase)
            command = self._random.choice(("m", "'", "`"))
            tokens = _characters(command + name)
            brief = f"{name} 마크 " + ("설정" if command == "m" else "위치로 이동")
            if command != "m":
                note = (
                    "해당 마크가 설정된 독립된 문맥입니다. "
                    "'는 첫 비공백, `는 정확한 열로 이동합니다."
                )
        else:
            chord = self._random.choice(("ctrl+o", "ctrl+i"))
            tokens = (KeyToken("chord", chord),)
            brief = "점프 이력 " + (
                "이전 위치로" if chord == "ctrl+o" else "다음 위치로"
            )
            note = "이전에 문서 안에서 점프한 이력이 있는 독립된 문맥입니다."
        return _item(tokens, brief + "합니다.", note, short_meaning=brief)

    def _context(self) -> CommandItem:
        if self._random.random() < 0.5:
            register = self._random.choice(ascii_lowercase)
            return _item(
                _characters("q" + register),
                f"{register} 레지스터에 매크로 기록을 시작합니다.",
                "이후 명령을 기록하고 q로 종료합니다. "
                "이 항목은 기록 시작 조각이며 앱은 매크로를 실행하지 않습니다.",
                short_meaning=f"{register}에 매크로 기록 시작 · q로 종료",
            )
        register = self._random.choice(ascii_lowercase + "+")
        clipboard_note = ""
        if register == "+":
            clipboard_note = " 실제 Vim의 클립보드 지원이 필요합니다."
        return _item(
            _characters('"' + register + "y"),
            f"{register} 레지스터를 지정하고 yank 연산을 시작합니다.",
            "선택 영역이 없는 Normal 문맥입니다. "
            "motion·text object 또는 y가 더 필요합니다. "
            "이 앱의 명령 타이핑 연습은 레지스터·OS 클립보드에 접근하지 않습니다."
            + clipboard_note,
            short_meaning=(
                ("클립보드" if register == "+" else f"{register} 레지스터")
                + " 복사 시작 · 범위 입력 필요"
            ),
        )

    def _sequence(self) -> CommandItem:
        movement = self._movement()
        operation = (
            self._operator_object()
            if self._random.random() < 0.5
            else self._operator_motion()
        )
        tokens = movement.tokens + operation.tokens
        meaning = "순서대로: " + movement.meaning + " " + operation.meaning
        brief = (
            movement.brief_meaning.removesuffix(" 이동")
            + " → "
            + operation.brief_meaning
        )
        if operation.follow_up == _INSERT_FOLLOW_UP:
            tokens += _characters(self._text()) + (_ESC,)
            meaning += " 표시된 문자를 입력하고 실제 Esc로 Normal에 돌아옵니다."
            brief += " → 입력 후 Esc"
        elif self._random.random() < 0.5:
            screen = self._screen()
            tokens += screen.tokens
            meaning += " " + screen.meaning
            brief += " → " + screen.brief_meaning
        return _item(tokens, meaning, short_meaning=brief)
