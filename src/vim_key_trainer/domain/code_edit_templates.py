"""실행하지 않는 코드 예제와 언어별 Vim 수정 레시피."""

# Standard library imports
import re
from collections import defaultdict
from dataclasses import dataclass
from math import gcd
from random import Random

# Local imports
from vim_key_trainer.domain.code_samples import (
    CodeExcerpt,
    CodeSource,
    choose_code_excerpt,
)
from vim_key_trainer.domain.edit_templates import (
    ENTER,
    ESC,
    DocumentPlan,
    EditRecipe,
    RecipeAction,
    characters,
)
from vim_key_trainer.domain.edit_weights import EditTechniqueWeights
from vim_key_trainer.domain.keys import KeyToken
from vim_key_trainer.engine import SUPPORTED_COMMANDS, EditEngine, EditorState

CODE_GENERATOR_VERSION = 5


@dataclass(frozen=True, slots=True)
class _Candidate:
    technique: str
    recipe: EditRecipe
    broken: tuple[str, ...]


def _json_source(count: int, rng: Random) -> list[str]:
    project = rng.choice(("warehouse", "inventory", "shipment"))
    port = rng.randrange(8000, 9000)
    lines = f'''{{
    "project": "{project}",
    "version": 3,
    "enabled": true,
    "environment": "production",
    "server": {{
        "host": "127.0.0.1",
        "port": {port},
        "timeout": 30,
        "workers": 4
    }},
    "logging": {{
        "level": "info",
        "format": "structured",
        "targets": ["console", "file"]
    }},
    "limits": {{"requests": 120, "burst": 20}},
    "regions": ["north", "south", "west"],
    "services": [
        {{
            "name": "catalog",
            "path": "/api/catalog",
            "retries": 3,
            "cache": true
        }},
        {{
            "name": "shipping",
            "path": "/api/shipping",
            "retries": 5,
            "cache": false
        }}
    ],
    "health": {{
        "path": "/health",
        "interval": 15,
        "expected": "ready"
    }},
    "fallback": null
}}'''.splitlines()
    for name in ("reporting", "billing", "notifications", "search", "analytics"):
        addition = f'''        {{
            "name": "{name}",
            "path": "/api/{name}",
            "retries": 3,
            "cache": true
        }},'''.splitlines()
        if len(lines) + len(addition) <= count:
            index = lines.index('            "name": "catalog",') - 1
            lines[index:index] = addition
    return lines


def _candidate(
    technique: str,
    row: int,
    correct: tuple[str, ...],
    broken: tuple[str, ...],
    column: int | None,
    keys: tuple[KeyToken, ...],
    text: str,
) -> _Candidate:
    return _Candidate(
        technique,
        EditRecipe(row, len(correct), correct, (RecipeAction(column, keys, text),)),
        broken,
    )


def _candidates(
    lines: tuple[str, ...], rng: Random, *, include_zero: bool = True
) -> list[_Candidate]:
    result: list[_Candidate] = []
    first_rows: dict[str, int] = {}
    number_pattern = (
        r"(?<![\w.-])(0|[1-9][0-9]*)(?![\w.])"
        if include_zero
        else r"(?<![\w.-])([1-9][0-9]*)(?![\w.])"
    )
    for row, line in enumerate(lines):
        if not line.strip():
            continue
        words = list(re.finditer(r"\b[a-z][a-z_]{2,}\b", line))
        if words:
            word = rng.choice(words)
            old = f"draft_{row}"
            broken = line[: word.start()] + old + line[word.end() :]
            for technique in ("word", "search", "substitution", "visual"):
                keys = characters("ciw" + word.group()) + (ESC,)
                column: int | None = word.start()
                if technique == "search":
                    keys = characters("/\\<" + old + "\\>") + (ENTER,) + keys
                    column = None
                elif technique == "substitution":
                    keys = characters(":s/" + old + "/" + word.group() + "/g") + (
                        ENTER,
                    )
                    column = None
                elif technique == "visual":
                    broken = (
                        line[: word.start()] + word.group().upper() + line[word.end() :]
                    )
                    keys = characters("viwu")
                result.append(
                    _candidate(
                        technique,
                        row,
                        (line,),
                        (broken,),
                        column,
                        keys,
                        {
                            "word": "ciw로 식별자 전체를 고칩니다.",
                            "search": "검색으로 잘못된 식별자를 찾아 ciw로 고칩니다.",
                            "substitution": ":s로 현재 줄의 잘못된 이름을 치환합니다.",
                            "visual": "viw로 식별자를 선택하고 u로 소문자로 바꿉니다.",
                        }[technique],
                    )
                )
        # 문자열과 같은 줄의 괄호 내용은 코드를 편집할 때 자주 쓰는 객체다.
        for pattern, obj in (
            (r'"([^"\\]*)"', '"'),
            (r"'([^'\\]*)'", "'"),
            (r"\(([^()]*)\)", "("),
            (r"\[([^\[\]]*)\]", "["),
            (r"\{([^{}]*)\}", "{"),
        ):
            if obj in {"'", '"'} and obj * 3 in line:
                continue
            matches = [match for match in re.finditer(pattern, line) if match.group(1)]
            if not matches:
                continue
            match = rng.choice(matches)
            old = "draft_value"
            broken = line[: match.start(1)] + old + line[match.end(1) :]
            use_pair = obj not in {'"', "'"} and rng.choice((True, False))
            command = ("%" if use_pair else "") + "ci" + obj
            result.append(
                _candidate(
                    "word",
                    row,
                    (line,),
                    (broken,),
                    match.start(),
                    characters(command + match.group(1)) + (ESC,),
                    ("%로 괄호짝을 확인하고 " if use_pair else "")
                    + f"ci{obj}로 구분자 내부를 고칩니다.",
                )
            )
        indent = len(line) - len(line.lstrip(" "))
        if indent >= 4:
            broken = line[4:]
            result.append(
                _candidate(
                    "structure",
                    row,
                    (line,),
                    (broken,),
                    None,
                    characters(">>"),
                    ">>로 코드 블록의 들여쓰기를 네 칸 복원합니다.",
                )
            )
            if row + 1 < len(lines) and lines[row + 1].startswith(" " * 4):
                pair = (line, lines[row + 1])
                result.append(
                    _candidate(
                        "repeat",
                        row,
                        pair,
                        tuple(item[4:] for item in pair),
                        None,
                        characters(">>j."),
                        ">>로 들여쓰기를 고친 뒤 다음 줄에서 .으로 반복합니다.",
                    )
                )
        numbers = list(re.finditer(number_pattern, line))
        if numbers:
            number = rng.choice(numbers)
            old_value = str(int(number.group()) - 1)
            broken = line[: number.start()] + old_value + line[number.end() :]
            result.append(
                _candidate(
                    "numbers",
                    row,
                    (line,),
                    (broken,),
                    number.start(),
                    (KeyToken("chord", "ctrl+a"),),
                    "실제 Control+A로 숫자 설정값을 1 늘립니다.",
                )
            )
        if line.rstrip().endswith((";", ",", ":", ")", "]", "}")):
            position = len(line.rstrip()) - 1
            broken = line[:position] + "?" + line[position + 1 :]
            result.append(
                _candidate(
                    "movement",
                    row,
                    (line,),
                    (broken,),
                    position,
                    characters("r" + line[position]),
                    "r로 줄 끝의 구분자 한 글자를 복원합니다.",
                )
            )
        # 줄 끝의 누락된 문자는 A로 복구한다. 줄 수는 고정해 다른 레시피와 독립이다.
        if len(line.rstrip()) > indent + 3:
            position = len(line.rstrip()) - rng.randrange(1, 3)
            result.append(
                _candidate(
                    "insertion",
                    row,
                    (line,),
                    (line[:position],),
                    None,
                    characters("A" + line[position:]) + (ESC,),
                    "A로 줄 끝에 빠진 코드를 덧붙입니다.",
                )
            )
        source = first_rows.setdefault(line, row)
        if source != row and len(line) >= 4:
            # 마지막 줄 삭제 후 커서는 이전 줄로 이동하므로 그 뒤에 붙인다.
            put = "p" if row == len(lines) - 1 else "P"
            result.append(
                _candidate(
                    "copy",
                    row,
                    (line,),
                    ("    obsolete_line",),
                    None,
                    characters(f'{source + 1}G"ayy{row + 1}Gdd"a{put}'),
                    f'a 레지스터에 줄을 복사하고 잘못된 줄을 dd·"a{put}로 교체합니다.',
                )
            )
    return result


def build_code_document_plan(
    profile_id: str,
    line_count: int,
    rng: Random,
    weights: EditTechniqueWeights | None = None,
    *,
    code_sources: tuple[CodeSource, ...] = (),
) -> DocumentPlan:
    """정상 코드를 먼저 구성하고 서로 겹치지 않는 수정 구간을 만든다."""
    excerpt: CodeExcerpt | None = None
    if profile_id == "code_json":
        lines = _json_source(line_count, rng)
        if len(lines) > line_count:
            raise ValueError("코드 예제가 요청한 문서 길이를 초과합니다.")
        while len(lines) < line_count:
            choices = [row for row, line in enumerate(lines) if not line]
            lines.insert(rng.choice(choices) if choices else len(lines) - 1, "")
        goal = tuple(lines)
    else:
        languages = {"code_python": "python", "code_cpp": "cpp"}
        try:
            language = languages[profile_id]
        except KeyError as error:
            raise ValueError("알 수 없는 코드 연습 유형입니다.") from error
        excerpt = choose_code_excerpt(code_sources, language, line_count, rng)
        goal = excerpt.lines
    candidates = _candidates(goal, rng, include_zero=profile_id != "code_json")
    groups: dict[str, list[_Candidate]] = defaultdict(list)
    effective = weights or EditTechniqueWeights()
    for candidate in candidates:
        if getattr(effective, candidate.technique):
            groups[candidate.technique].append(candidate)
    # 언어의 흔한 수정에 기본 선호를 더하되 사용자가 끈 기술은 다시 켜지 않는다.
    affinities = {
        "code_python": {"word": 3, "structure": 3, "search": 2},
        "code_cpp": {"word": 3, "movement": 2, "structure": 2},
        "code_json": {"word": 3, "numbers": 3, "substitution": 2},
    }[profile_id]
    count = max(7, min(20, line_count // 20))
    selected: list[_Candidate] = []
    used: set[int] = set()
    deck: list[str] = []
    while len(selected) < count:
        eligible = {
            name: [
                candidate
                for candidate in options
                if used.isdisjoint(
                    range(
                        candidate.recipe.row,
                        candidate.recipe.row + candidate.recipe.span,
                    )
                )
            ]
            for name, options in groups.items()
        }
        eligible = {name: options for name, options in eligible.items() if options}
        if not eligible:
            if profile_id == "code_json":
                raise ValueError(
                    "선택한 기술 비중으로 코드의 수정 구간을 만들 수 없습니다."
                )
            # 실제 원문의 숫자·복사 가능 행은 유한하다. 선택한 기술을 유지한 채
            # 적용 가능한 구간만 사용하며 부족분을 가짜 코드로 채우지 않는다.
            if selected:
                break
            raise ValueError(
                "이 코드 구간에는 선택한 기술로 수정할 곳이 없습니다. "
                "다른 문제를 고르거나 문서 수정의 기술 비중을 조절하세요."
            )
        deck = [name for name in deck if name in eligible]
        if not deck:
            # 첫 묶음은 활성 기술을 한 번씩 경험하고 이후에는 상대 비중을 반영한다.
            proportions = {
                name: getattr(effective, name) * affinities.get(name, 1)
                for name in eligible
            }
            unit = gcd(*proportions.values())
            deck = (
                list(eligible)
                if not selected and count >= 10
                else [
                    name for name in eligible for _ in range(proportions[name] // unit)
                ]
            )
            rng.shuffle(deck)
        technique = deck.pop()
        # 문서 전체에 펼치되 기술별 가능한 행이 없으면 가까운 구간을 쓴다.
        start = len(selected) * line_count // count
        stop = (len(selected) + 1) * line_count // count
        local = [
            item for item in eligible[technique] if start <= item.recipe.row < stop
        ]
        candidate = rng.choice(
            local
            or sorted(
                eligible[technique], key=lambda item: abs(item.recipe.row - start)
            )[:4]
        )
        if candidate.technique != "copy":
            # 손상된 문자열/괄호의 문맥이 객체 의미를 바꿀 수 있다. 선택한 복원을
            # 작은 독립 버퍼에서 먼저 재생하고 맞지 않는 후보는 제외한다.
            action = candidate.recipe.actions[0]
            probe = EditEngine(
                EditorState(candidate.broken, column=action.column or 0),
                SUPPORTED_COMMANDS,
            )
            accepted = all(probe.submit(key).accepted for key in action.keys)
            if (
                not accepted
                or probe.state.lines != candidate.recipe.replacement
                or probe.state.mode != "normal"
                or probe.state.pending
            ):
                groups[candidate.technique].remove(candidate)
                continue
        selected.append(candidate)
        used.update(
            range(candidate.recipe.row, candidate.recipe.row + candidate.recipe.span)
        )
    initial = list(goal)
    for candidate in selected:
        recipe = candidate.recipe
        initial[recipe.row : recipe.row + recipe.span] = candidate.broken
    # 줄 수를 유지하므로 위에서부터 읽으며 고친다. 복사 원본도 항상 대상보다
    # 위에 있어 손상된 원본을 먼저 복구한 뒤 아래 행에 복사할 수 있다.
    ordered = sorted(selected, key=lambda candidate: candidate.recipe.row)
    return DocumentPlan(
        tuple(initial),
        goal,
        tuple(item.recipe for item in ordered),
        (
            f"{excerpt.source.project} · {excerpt.source.title} "
            f"L{excerpt.start_line}–{excerpt.end_line}"
            if excerpt is not None
            else "service_config.json"
        ),
        code_excerpt=excerpt,
    )
