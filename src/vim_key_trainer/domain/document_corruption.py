"""원문에 실제 Vim 키를 재생해 손상시키고 독립적인 복원 풀이를 만든다.

손상 엔진의 undo 이력은 학습 세션에 넘기지 않는다. 각 구간의 원문과 바뀐 행을
비교해 삭제·삽입으로 되돌리는 기준 풀이를 새 엔진에서 검증한다.
"""

# Standard library imports
import re
from collections import Counter
from dataclasses import dataclass
from math import gcd
from random import Random
from typing import Literal

# Local imports
from vim_key_trainer.domain.document_missions import (
    DocumentMission,
    DocumentPracticeSpec,
)
from vim_key_trainer.domain.edit_builder import (
    GuideBuilder,
    literal_search_pattern,
    navigation_cost,
    navigation_keys,
)
from vim_key_trainer.domain.edit_templates import ESC, characters, counted
from vim_key_trainer.domain.edit_weights import EditTechniqueWeights
from vim_key_trainer.domain.editing import EditLesson
from vim_key_trainer.domain.keys import KeyToken
from vim_key_trainer.engine import SUPPORTED_COMMANDS, EditEngine, EditorState

DOCUMENT_GENERATOR_VERSION = 8
CorruptionKind = Literal[
    "insert",
    "prefix",
    "append",
    "delete",
    "word",
    "replace",
    "case",
    "duplicate",
    "replace_char",
    "change_word",
    "substitute",
    "quoted",
    "block",
    "bracketed",
    "number",
    "indent",
]
_DAMAGE_GROUPS: tuple[tuple[str, tuple[CorruptionKind, ...]], ...] = (
    ("insertion", ("insert", "prefix", "append", "duplicate")),
    ("deletion", ("delete", "word")),
    ("replacement", ("replace", "replace_char", "change_word")),
    ("case", ("case",)),
    ("object", ("quoted", "block", "bracketed")),
    ("number", ("number",)),
    ("indent", ("indent",)),
    ("substitution", ("substitute",)),
)
_DAMAGE_TECHNIQUES = {
    # 손상 동작의 이름이 아니라 학습자가 복원할 때 수행하는 기술로 분류한다.
    "insertion": "movement",
    "deletion": "insertion",
    "replacement": "movement",
    "case": "visual",
    "object": "word",
    "number": "numbers",
    "indent": "structure",
    "substitution": "substitution",
}
_WORDS = ("temp", "draft", "cache", "trace", "extra", "local", "debug", "old")
_WORD = re.compile(r"[A-Za-z_][A-Za-z_0-9]*")
_BLOCKS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("(", ")", ("b", ")", "(")),
    ("[", "]", ("]", "[")),
    ("{", "}", ("B", "}", "{")),
    ("<", ">", (">", "<")),
)


@dataclass(frozen=True, slots=True)
class CorruptionOperation:
    row: int
    kind: CorruptionKind
    tokens: tuple[KeyToken, ...]
    before: str
    after: str


@dataclass(frozen=True, slots=True)
class DocumentCorruptionPlan:
    lesson: EditLesson
    corruption_tokens: tuple[KeyToken, ...]
    operations: tuple[CorruptionOperation, ...]


@dataclass(frozen=True, slots=True)
class _Damage:
    column: int | None
    tokens: tuple[KeyToken, ...]
    kind: CorruptionKind


@dataclass(frozen=True, slots=True)
class _DamageChoice:
    row: int
    damage: _Damage


@dataclass(frozen=True, slots=True)
class _Repair:
    keys: tuple[KeyToken, ...]
    text: str
    family: str
    column: int | None
    cognitive_cost: int = 0


def _fragment(rng: Random) -> str:
    word = rng.choice(_WORDS)
    return rng.choice((f"_{word}", f" {word} ", str(rng.randrange(1, 100)), "??"))


def _row_regions(lines: tuple[str, ...], count: int) -> list[tuple[int, ...]]:
    """구간마다 후보 행을 두고 구간 사이 한 줄은 손상시키지 않는다."""
    line_count = len(lines)
    if line_count < count * 2 - 1:
        raise ValueError("요청한 수정 구간을 서로 떨어뜨릴 문서 길이가 부족합니다.")
    available = line_count - count + 1
    regions: list[tuple[int, ...]] = []
    for index in range(count):
        start = index * available // count + index
        stop = (index + 1) * available // count + index
        candidates = tuple(range(start, stop))
        regions.append(candidates)
    return regions


def _replacement(line: str, column: int, count: int, text: str) -> _Damage:
    suffix = line[column + count :]
    insertion = "i" if suffix or column == 0 else "a"
    keys = characters(counted(count, "x") + insertion + text) + (ESC,)
    return _Damage(column, keys, "replace")


def _word_damage(line: str, rng: Random) -> _Damage | None:
    candidates = [match for match in _WORD.finditer(line) if len(match.group()) <= 10]
    rng.shuffle(candidates)
    for match in candidates:
        engine = EditEngine(EditorState((line,), column=match.start()))
        for token in characters("dw"):
            engine.submit(token)
        after = engine.state.lines
        if len(after) == 1 and 0 < len(line) - len(after[0]) <= 12:
            return _Damage(match.start(), characters("dw"), "word")
    return None


def _quoted_ranges(line: str, quote: str) -> tuple[tuple[int, int], ...]:
    """백슬래시로 이스케이프하지 않은 따옴표 쌍의 내부 범위를 구한다."""
    positions = [
        match.start()
        for match in re.finditer(r"\\.|" + re.escape(quote), line)
        if match.group() == quote
    ]
    return tuple(
        (left + 1, right)
        for left, right in zip(positions[::2], positions[1::2], strict=False)
    )


def _block_ranges(line: str, opening: str, closing: str) -> list[tuple[int, int]]:
    """한 줄의 같은 종류 괄호를 중첩 순서대로 짝짓는다. 실행은 엔진이 검증한다."""
    stack: list[int] = []
    ranges: list[tuple[int, int]] = []
    for column, character in enumerate(line):
        if character == opening:
            stack.append(column)
        elif character == closing and stack:
            ranges.append((stack.pop(), column))
    return ranges


def _damage(line: str, kind: CorruptionKind, rng: Random) -> _Damage:
    fragment = _fragment(rng)
    if kind == "prefix":
        return _Damage(None, characters("I" + fragment) + (ESC,), kind)
    if kind == "append" or not line:
        return _Damage(None, characters("A" + fragment) + (ESC,), "append")
    if kind == "indent":
        return _Damage(None, characters(">>"), kind)
    if kind == "bracketed":
        opening, closing, _ = rng.choice(_BLOCKS)
        column = rng.choice([match.start() for match in _WORD.finditer(line)] or [0])
        return _Damage(
            column,
            characters("i" + opening + rng.choice(_WORDS) + closing) + (ESC,),
            kind,
        )
    if kind == "block":
        block_ranges = [
            (left, right, selectors)
            for opening, closing, selectors in _BLOCKS
            for left, right in _block_ranges(line, opening, closing)
            if 1 <= right - left - 1 <= 10
        ]
        if block_ranges:
            left, right, selectors = rng.choice(block_ranges)
            replacement = rng.choice(_WORDS)
            if replacement == line[left + 1 : right]:
                replacement = "draft" if replacement != "draft" else "temp"
            return _Damage(
                left,
                characters("ci" + rng.choice(selectors) + replacement) + (ESC,),
                kind,
            )
        kind = "change_word"
    if kind == "number":
        numbers = list(re.finditer(r"(?<![A-Za-z0-9_])\d{1,4}(?![A-Za-z0-9_])", line))
        if numbers:
            match = rng.choice(numbers)
            return _Damage(
                match.start(),
                characters(str(rng.randrange(2, 10))) + (KeyToken("chord", "ctrl+a"),),
                kind,
            )
        kind = "change_word"
    if kind == "quoted":
        ranges = [
            (start, end, quote)
            for quote in ('"', "'", "`")
            for start, end in _quoted_ranges(line, quote)
            if 1 <= end - start <= 10
        ]
        if ranges:
            start, end, quote = rng.choice(ranges)
            replacement = rng.choice(_WORDS)
            if replacement == line[start:end]:
                replacement = "draft" if replacement != "draft" else "temp"
            return _Damage(
                start,
                characters("ci" + quote + replacement) + (ESC,),
                kind,
            )
        kind = "change_word"
    if kind == "substitute":
        frequencies = Counter(match.group() for match in _WORD.finditer(line))
        repeated = [
            word
            for word, count in frequencies.items()
            if 2 <= count <= 3 and len(word) <= 6
        ]
        if repeated:
            word = rng.choice(repeated)
            replacements = (
                (fragment * 2)[: len(word)]
                for fragment in ("draft", "trace", "local", "cache", "temp")
            )
            replacement_word = next(
                (
                    candidate
                    for candidate in replacements
                    if candidate not in frequencies
                ),
                None,
            )
            if replacement_word is not None:
                pattern = r"\<" + word + r"\>"
                return _Damage(
                    None,
                    characters(f":s/{pattern}/{replacement_word}/g")
                    + (KeyToken("special", "enter"),),
                    kind,
                )
        kind = "change_word"
    if kind == "change_word":
        words = [match for match in _WORD.finditer(line) if len(match.group()) <= 10]
        if words:
            match = rng.choice(words)
            replacement = rng.choice(_WORDS)
            if replacement == match.group():
                replacement = "draft" if replacement != "draft" else "temp"
            return _Damage(
                match.start(), characters("ciw" + replacement) + (ESC,), kind
            )
        kind = "replace_char"
    if kind == "replace_char":
        column = rng.randrange(len(line))
        character = rng.choice("!?_xyz012")
        if character == line[column]:
            character = "?" if character != "?" else "!"
        return _Damage(column, characters("r" + character), kind)
    if kind == "word":
        word_damage = _word_damage(line, rng)
        if word_damage is not None:
            return word_damage
        kind = "delete"
    if kind == "duplicate":
        words = list(_WORD.finditer(line))
        if words:
            match = rng.choice(words)
            duplicate = match.group()[:10] + " "
            return _Damage(match.start(), characters("i" + duplicate) + (ESC,), kind)
        kind = "insert"
    if kind == "case":
        letters = [index for index, char in enumerate(line) if char.isalpha()]
        if letters:
            column = rng.choice(letters)
            return _Damage(column, characters("~"), "case")
        kind = "replace"
    if kind in {"delete", "replace"}:
        columns = [index for index, char in enumerate(line) if char != " "]
        column = rng.choice(columns or list(range(len(line))))
        count = rng.randint(1, min(4, len(line) - column))
        if kind == "delete":
            return _Damage(column, characters(counted(count, "x")), kind)
        old = line[column : column + count]
        if fragment == old:
            fragment += "?"
        return _replacement(line, column, count, fragment)
    position = rng.randrange(len(line) + 1)
    if position == len(line):
        return _Damage(None, characters("A" + fragment) + (ESC,), "insert")
    if position > 0 and rng.choice((False, True)):
        return _Damage(position - 1, characters("a" + fragment) + (ESC,), "insert")
    return _Damage(position, characters("i" + fragment) + (ESC,), "insert")


def _changed_text(before: str, after: str) -> tuple[int, str, str, bool]:
    """원문과 손상 행의 공통 양끝을 남기고 복원해야 할 조각을 구한다."""
    start = 0
    while start < min(len(before), len(after)) and before[start] == after[start]:
        start += 1
    tail = 0
    while (
        tail < len(before) - start
        and tail < len(after) - start
        and before[len(before) - tail - 1] == after[len(after) - tail - 1]
    ):
        tail += 1
    old_end = len(before) - tail
    new_end = len(after) - tail
    return start, before[start:old_end], after[start:new_end], bool(tail)


def _select_damage(
    lines: tuple[str, ...],
    count: int,
    rng: Random,
    weights: EditTechniqueWeights | None = None,
) -> list[_DamageChoice]:
    """적용 가능한 행·손상 쌍에서 기술을 먼저 고르고 표기는 그 안에서 고른다.

    숫자나 객체가 없는 행의 fallback을 그 기술을 연습한 것으로 세지 않는다.
    적용할 곳이 적은 기술부터 배정해 유연한 행이 먼저 소진되지 않게 한다.
    """
    policy = dict((weights or EditTechniqueWeights()).items())
    # 이동의 두 하위 유형이 종류 수 때문에 더 자주 뽑히지 않게 비중을 나눈다.
    group_weights = {
        skill: policy[technique] * (1 if technique == "movement" else 2)
        for skill, technique in _DAMAGE_TECHNIQUES.items()
    }
    if not any(group_weights.values()):
        raise ValueError(
            "선택한 기술 비중은 복합 문서 수정에서 연습할 수 있습니다. "
            "실제 문서는 검색·복사·반복만으로 손상 과제를 만들지 않습니다."
        )
    options: list[dict[str, list[_DamageChoice]]] = []
    for region in _row_regions(lines, count):
        groups: dict[str, list[_DamageChoice]] = {}
        for skill, kinds in _DAMAGE_GROUPS:
            if not group_weights[skill]:
                continue
            choices: list[_DamageChoice] = []
            for row in region:
                for kind in rng.sample(kinds, len(kinds)):
                    damage = _damage(lines[row], kind, rng)
                    if damage.kind == kind:
                        choices.append(_DamageChoice(row, damage))
                        break
            if choices:
                groups[skill] = choices
        if not groups:
            raise ValueError(
                "선택한 기술 비중으로 이 원문의 모든 수정 구간을 만들 수 없습니다. "
                "다른 원문·복합 연습을 선택하거나 이동·입력 비중도 늘려 주세요."
            )
        options.append(groups)
    divisor = gcd(*group_weights.values())
    pool = [
        skill
        for skill, _ in _DAMAGE_GROUPS
        if any(skill in groups for groups in options)
        for _ in range(group_weights[skill] // divisor)
    ]
    targets: list[str] = []
    while len(targets) < count:
        rng.shuffle(pool)
        targets.extend(pool)
    wanted = Counter(targets[:count])
    selected: list[_DamageChoice] = []
    used: Counter[str] = Counter()
    while options:
        skills = list({skill for groups in options for skill in groups})
        # set 순서가 seed 재현성에 영향을 주지 않게 정렬한 뒤 섞는다.
        skills.sort()
        rng.shuffle(skills)
        skill = min(
            skills,
            key=lambda item: (
                used[item] >= wanted[item],
                sum(item in groups for groups in options),
                used[item] / group_weights[item],
            ),
        )
        regions = [index for index, groups in enumerate(options) if skill in groups]
        rng.shuffle(regions)
        region_index = min(regions, key=lambda index: len(options[index]))
        choices = options.pop(region_index)[skill]
        readable = [choice for choice in choices if len(lines[choice.row].strip()) >= 3]
        selected.append(rng.choice(readable or choices))
        used[skill] += 1
    rng.shuffle(selected)
    return selected


def _substitution_repairs(
    operation: CorruptionOperation,
) -> list[tuple[tuple[KeyToken, ...], str]]:
    """문자 수를 세는 대신 손상 조각과 짧은 주변 문맥을 지정해 치환한다."""
    column, original, damaged, _ = _changed_text(operation.before, operation.after)
    if not damaged:
        return []
    candidates: list[tuple[tuple[KeyToken, ...], str]] = []
    before_words = _WORD.findall(operation.before)
    after_words = _WORD.findall(operation.after)
    if len(before_words) == len(after_words):
        changed_words = sorted(
            {
                (before, after)
                for before, after in zip(before_words, after_words, strict=True)
                if before != after
            }
        )
        for before, after in changed_words:
            pattern = r"\<" + after + r"\>"
            keys = characters(f":s/{pattern}/{before}/g") + (
                KeyToken("special", "enter"),
            )
            candidates.append(
                (keys, f":s의 g로 이 줄의 '{after}'를 '{before}'로 함께 복원합니다.")
            )
    for context in (0, 1, 4, 12, len(operation.after)):
        start = max(0, column - context)
        stop = min(len(operation.after), column + len(damaged) + context)
        left = operation.after[start:column]
        right = operation.after[column + len(damaged) : stop]
        pattern = literal_search_pattern(left + damaged + right)
        if len(pattern) > 256:
            continue
        replacement = "".join(
            "\\" + char if char in r"\&~/" else char for char in left + original + right
        )
        keys = characters(f":s/{pattern}/{replacement}/") + (
            KeyToken("special", "enter"),
        )
        candidates.append((keys, ":s로 현재 줄의 손상된 문구를 원문으로 치환합니다."))
    return candidates


def _repair_candidates(
    operation: CorruptionOperation, preferred_column: int | None = None
) -> list[_Repair]:
    column, original, damaged, has_suffix = _changed_text(
        operation.before, operation.after
    )
    line = operation.after
    target_column = min(column, max(0, len(line) - 1))
    insertion = "i" if has_suffix or column == 0 else "a"
    candidates: list[_Repair] = []
    if len(original) == len(damaged) == 1:
        if original == damaged.swapcase():
            candidates.append(
                _Repair(
                    characters("~"),
                    "~로 원래 대소문자를 복원합니다.",
                    "~",
                    target_column,
                )
            )
        candidates.append(
            _Repair(
                characters("r" + original),
                "r로 잘못된 한 문자를 교체합니다.",
                "r",
                target_column,
            )
        )
    if operation.after == "    " + operation.before:
        candidates.append(
            _Repair(
                characters("<<"),
                "<<로 잘못 들어간 네 칸 들여쓰기를 제거합니다.",
                "<<",
                None,
            )
        )
    if not has_suffix and damaged:
        command = "C" if original else "D"
        keys = characters("C" + original) + (ESC,) if original else characters("D")
        candidates.append(
            _Repair(
                keys,
                f"{command}로 줄 끝의 손상된 내용을 복원합니다.",
                command,
                target_column,
            )
        )
    if damaged and not original:
        for command in ("dw", "dW", "de", "dE", "diw", "diW", "daw", "daW"):
            candidates.append(
                _Repair(
                    characters(command),
                    f"{command}로 추가된 단어·공백을 지웁니다.",
                    command,
                    target_column,
                )
            )
    object_repairs = _object_repairs(operation, column, preferred_column)
    candidates.extend(object_repairs)
    candidates.extend(
        _Repair(
            characters("v") + repair.keys[1:3] + repair.keys[:1] + repair.keys[3:],
            "v와 텍스트 객체로 범위를 선택한 뒤 "
            + (
                "c로 바꾸고 Esc로 마칩니다."
                if repair.keys[0].value == "c"
                else "d로 지웁니다."
            ),
            "visual",
            repair.column,
        )
        for repair in object_repairs
        if repair.keys[1].value in "ia"
    )
    candidates.extend(
        _Repair(keys, text, "number", target_column)
        for keys, text in _numeric_repairs(operation, column)
    )
    candidates.extend(_range_repairs(operation, column, original, damaged))
    candidates.extend(
        _Repair(keys, text, ":s", None)
        for keys, text in _substitution_repairs(operation)
    )
    if original and len(original) == len(damaged):
        candidates.append(
            _Repair(
                characters("R" + original) + (ESC,),
                "R로 같은 길이의 조각을 덮어쓰고 Esc로 마칩니다.",
                "R",
                target_column,
            )
        )
    # 문자 수를 직접 세는 수정은 세 글자까지만 허용한다.
    if damaged and len(damaged) <= 3:
        if original:
            candidates.append(
                _Repair(
                    characters(counted(len(damaged), "s") + original) + (ESC,),
                    f"{counted(len(damaged), 's')}로 짧은 조각을 바꾸고 "
                    "Esc로 마칩니다.",
                    "s",
                    target_column,
                )
            )
        else:
            candidates.append(
                _Repair(
                    characters(counted(len(damaged), "x")),
                    f"{counted(len(damaged), 'x')}로 추가된 짧은 조각을 지웁니다.",
                    "x",
                    target_column,
                )
            )
    elif not damaged:
        candidates.append(
            _Repair(
                characters(insertion + original) + (ESC,),
                f"{insertion}로 빠진 원문 조각을 입력하고 Esc로 마칩니다.",
                insertion,
                target_column,
            )
        )
    return candidates


def _record_repair(
    guide: GuideBuilder,
    operation: CorruptionOperation,
    used_families: Counter[str] | None = None,
    technique_weights: EditTechniqueWeights | None = None,
) -> None:
    candidates = _repair_candidates(operation, guide.engine.state.column)
    snapshot = guide.engine.snapshot()
    if snapshot.last_change and "." in guide.engine.allowed_commands:
        candidates.extend(
            _Repair(
                characters("."),
                ".으로 앞서 수행한 변경을 같은 문맥에 반복합니다.",
                ".",
                position,
            )
            for position in dict.fromkeys(candidate.column for candidate in candidates)
        )
    target = list(guide.engine.state.lines)
    target[operation.row] = operation.before
    movements: dict[int | None, tuple[KeyToken, ...] | None] = {}
    ranked: list[tuple[float, int, _Repair]] = []
    policy = dict(technique_weights.items()) if technique_weights is not None else {}
    for candidate in candidates:
        if candidate.column not in movements:
            try:
                movements[candidate.column] = navigation_keys(
                    guide.engine.state,
                    operation.row,
                    candidate.column,
                    guide.engine.allowed_commands,
                    last_find=guide.engine.last_find,
                )
            except ValueError:
                movements[candidate.column] = None
        movement = movements[candidate.column]
        if movement is None:
            continue
        cost = (
            navigation_cost(movement) + len(candidate.keys) + candidate.cognitive_cost
        )
        if candidate.family == ":s":
            cost += sum(key.value == "\\" for key in candidate.keys)
        skill = _repair_skill(candidate.family)
        repeated = min(2, used_families[skill]) if used_families else 0
        preference = 0.0
        if policy:
            technique = _repair_technique(skill)
            preference = 2 * (1 - policy[technique] / max(policy.values()))
            if not policy[technique] and technique in {
                "substitution",
                "visual",
                "repeat",
            }:
                preference += 1000
        ranked.append((cost + 2 * repeated + preference, cost, candidate))
    # 전체 비용이 낮은 후보부터 검증한다. 긴 치환·덮어쓰기까지 매번 재생할
    # 필요 없이, 첫 유효 후보가 읽기 쉬운 전체 풀이 중 가장 낮은 비용이다.
    for _, _, candidate in sorted(
        ranked,
        key=lambda item: (item[0], item[1]),
    ):
        probe = EditEngine(guide.engine.state, guide.engine.allowed_commands)
        probe.restore(snapshot)
        movement = movements[candidate.column]
        assert movement is not None
        if not all(probe.submit(key).accepted for key in movement + candidate.keys) or (
            probe.state.lines != tuple(target)
            or probe.state.mode != "normal"
            or probe.state.pending
        ):
            continue
        guide.navigate(operation.row, candidate.column)
        guide.record(candidate.keys, f"{operation.row + 1}행: {candidate.text}")
        if used_families is not None:
            used_families[_repair_skill(candidate.family)] += 1
        return
    raise ValueError("원문의 복원 명령 후보를 재생할 수 없습니다.")


def _repair_skill(command: str) -> str:
    """별칭이나 word/WORD 표기 차이로 기술 다양성을 부풀리지 않는다."""
    if command in {"cw", "cW", "ce", "cE"}:
        return "word_motion_change"
    if command in {"dw", "dW", "de", "dE"}:
        return "word_motion_delete"
    if command in {"ciw", "ciW", "diw", "diW"}:
        return "word_inner"
    if command in {"daw", "daW"}:
        return "word_around"
    if len(command) == 3 and command[0] in "cd" and command[1] in "ia":
        return "delimited_inner" if command[1] == "i" else "delimited_around"
    if command in {"ct", "cf", "dt", "df"}:
        return "delimiter_range"
    if command in {"r", "R", "s"}:
        return "character_change"
    if command in {"C", "D"}:
        return "line_tail"
    if command in {"i", "a"}:
        return "insert"
    return command


def _repair_technique(skill: str) -> str:
    if skill.startswith(("word_", "delimited_")):
        return "word"
    return {
        "insert": "insertion",
        "<<": "structure",
        "~": "visual",
        "visual": "visual",
        "number": "numbers",
        ":s": "substitution",
        ".": "repeat",
    }.get(skill, "movement")


def _range_repairs(
    operation: CorruptionOperation, column: int, original: str, damaged: str
) -> list[_Repair]:
    """눈에 보이는 경계 문자까지 d/c를 적용하는 짧은 범위 수정 후보."""
    if not damaged:
        return []
    candidates: list[_Repair] = []
    stop = column + len(damaged)
    for motion, target in (("t", stop), ("f", stop - 1)):
        if not column < target < len(operation.after):
            continue
        character = operation.after[target]
        count = operation.after[column + 1 : target + 1].count(character)
        if count > 3:
            continue
        operator = "c" if original else "d"
        command = operator + counted(count, motion) + character
        keys = characters(command + original) + ((ESC,) if original else ())
        display = "".join(key.display for key in characters(command))
        candidates.append(
            _Repair(
                keys,
                f"{display}로 보이는 경계까지 손상 조각을 "
                + ("바꾸고 Esc로 마칩니다." if original else "지웁니다."),
                operator + motion,
                column,
                3 * (count - 1) + int(character.isalnum()),
            )
        )
    return candidates


def _object_columns(
    start: int, end: int, changed_column: int, preferred_column: int | None
) -> tuple[int, ...]:
    """객체는 시작으로 돌아가지 않고 현재 위치·변경 위치·끝에서도 수정한다."""
    return tuple(
        dict.fromkeys(
            position
            for position in (preferred_column, changed_column, start, end - 1)
            if position is not None and start <= position < end
        )
    )


def _object_repairs(
    operation: CorruptionOperation, column: int, preferred_column: int | None = None
) -> list[_Repair]:
    candidates: list[_Repair] = []
    before, after = operation.before, operation.after
    for pattern, commands in (
        (r"[A-Za-z0-9_]+", ("ciw", "cw", "ce")),
        (r"\S+", ("ciW", "cW", "cE")),
    ):
        for changed in re.finditer(pattern, after):
            if not changed.start() <= column < changed.end():
                continue
            for original in re.finditer(pattern, before):
                if original.start() == changed.start() and (
                    before[: original.start()] == after[: changed.start()]
                    and before[original.end() :] == after[changed.end() :]
                ):
                    for command in commands:
                        columns = (
                            _object_columns(
                                changed.start(), changed.end(), column, preferred_column
                            )
                            if command in {"ciw", "ciW"}
                            else (changed.start(),)
                        )
                        for position in columns:
                            candidates.append(
                                _Repair(
                                    characters(command + original.group()) + (ESC,),
                                    f"{command}로 "
                                    + (
                                        "WORD"
                                        if "W" in command or "E" in command
                                        else "단어"
                                    )
                                    + " 전체를 바꾸고 Esc로 마칩니다.",
                                    command,
                                    position,
                                )
                            )
    ranges = [
        (left, right, selectors)
        for opening, closing, selectors in _BLOCKS
        for left, right in _block_ranges(after, opening, closing)
    ]
    ranges.extend(
        (start - 1, end, (quote,))
        for quote in ('"', "'", "`")
        for start, end in _quoted_ranges(after, quote)
    )
    for left, right, selectors in ranges:
        for scope in ("i", "a"):
            start, end = (left + 1, right) if scope == "i" else (left, right + 1)
            suffix = after[end:]
            original_end = len(before) - len(suffix)
            if (
                original_end < start
                or before[:start] != after[:start]
                or before[original_end:] != suffix
            ):
                continue
            original_text = before[start:original_end]
            if original_text == after[start:end]:
                continue
            for selector in selectors:
                command = ("c" if original_text else "d") + scope + selector
                keys = characters(command + original_text)
                if original_text:
                    keys += (ESC,)
                for position in _object_columns(
                    left, right + 1, column, preferred_column
                ):
                    candidates.append(
                        _Repair(
                            keys,
                            f"{command}로 "
                            + ("구분자 안을" if scope == "i" else "구분자까지")
                            + " 원문으로 복원합니다."
                            + (" Esc로 마칩니다." if original_text else ""),
                            command,
                            position,
                        )
                    )
    return candidates


def _numeric_repairs(
    operation: CorruptionOperation, column: int
) -> list[tuple[tuple[KeyToken, ...], str]]:
    before, after = operation.before, operation.after
    for changed in re.finditer(r"\d+", after):
        if not changed.start() <= column < changed.end():
            continue
        for original in re.finditer(r"\d+", before):
            if original.start() != changed.start() or (
                before[: original.start()] != after[: changed.start()]
                or before[original.end() :] != after[changed.end() :]
            ):
                continue
            delta = int(original.group()) - int(changed.group())
            if delta and abs(delta) <= 999:
                prefix = characters(str(abs(delta))) if abs(delta) > 1 else ()
                chord = "ctrl+a" if delta > 0 else "ctrl+x"
                return [
                    (
                        prefix + (KeyToken("chord", chord),),
                        f"실제 Control+{'A' if delta > 0 else 'X'}로 "
                        f"숫자를 {abs(delta)}만큼 복원합니다.",
                    )
                ]
    return []


def generate_document_problem(
    mission: DocumentMission, spec: DocumentPracticeSpec
) -> DocumentCorruptionPlan:
    """같은 문서·seed·구간 수는 같은 손상 키와 복원 풀이를 만든다."""
    if mission.id != spec.mission_id:
        raise ValueError("문서와 문제 생성 조건의 ID가 다릅니다.")
    if spec.change_count < 7:
        raise ValueError("새 문서 복구 연습에는 최소 7곳의 수정 구간이 필요합니다.")
    rng = Random(spec.seed)
    original = EditorState(mission.goal_lines)
    damage = GuideBuilder(original, SUPPORTED_COMMANDS)
    weights = spec.technique_weights or EditTechniqueWeights()
    selected = _select_damage(original.lines, spec.change_count, rng, weights)
    operations: list[CorruptionOperation] = []
    for choice in selected:
        row, plan = choice.row, choice.damage
        before = damage.engine.state.lines[row]
        # 비공개 재현 로그는 위치를 기계적으로 지정한다. 이 이동은 사용자
        # 가이드·기준 입력 수에 들어가지 않으므로 단어 수를 세게 하지 않는다.
        position = f"{row + 1}G"
        if plan.column is not None:
            position += "0" + (counted(plan.column, "l") if plan.column else "")
        damage.record(characters(position), "손상 재현 위치로 이동합니다.")
        damage.record(plan.tokens, "원문에 손상 키를 재생합니다.")
        after = damage.engine.state.lines[row]
        if before == after or len(damage.engine.state.lines) != len(original.lines):
            raise ValueError("손상 구간은 한 행의 내용을 실제로 바꿔야 합니다.")
        operations.append(
            CorruptionOperation(row, plan.kind, plan.tokens, before, after)
        )
    # 세션 시작 커서도 임의 상태가 아닌 실제 이동 키로 맞춘다.
    damage.record(characters("gg0"), "손상된 문서의 처음으로 돌아갑니다.")
    initial = damage.engine.state
    guide = GuideBuilder(initial, SUPPORTED_COMMANDS)
    used_families: Counter[str] = Counter()
    for operation in reversed(operations):
        _record_repair(guide, operation, used_families, weights)
    if guide.engine.state.lines != mission.goal_lines:
        raise ValueError("손상 문서의 복원 풀이가 원문과 다릅니다.")
    baseline = tuple(key for step in guide.steps for key in step.keys)
    lesson = EditLesson(
        schema_version=1,
        content_version=mission.content_version,
        id=mission.id,
        title=mission.title,
        description=(
            f"{mission.source.project} 원문 · 무작위 손상 {spec.change_count}곳 복구"
        ),
        initial=initial,
        goal_lines=mission.goal_lines,
        goal_cursor=None,
        allowed_commands=SUPPORTED_COMMANDS,
        guide=tuple(guide.steps),
        baseline_version=7,
        baseline=baseline,
        baseline_keys=len(baseline),
        generator_version=DOCUMENT_GENERATOR_VERSION,
        document_spec=spec,
    )
    return DocumentCorruptionPlan(
        lesson,
        tuple(key for step in damage.steps for key in step.keys),
        tuple(operations),
    )
