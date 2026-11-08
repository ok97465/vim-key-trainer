"""긴 편집 문서와 서로 다른 수정 패턴을 만드는 작은 레시피.

목표 행은 문자열 연산으로 명시하고, 풀이 키는 별도로 구성한다.
엔진 실행 결과를 목표로 삼지 않아 잘못된 레시피를 재생 검증으로 발견한다.
"""

# Standard library imports
import re
from collections.abc import Callable
from dataclasses import dataclass
from math import gcd
from random import Random

# Local imports
from vim_key_trainer.domain.code_samples import CodeExcerpt
from vim_key_trainer.domain.edit_weights import EditTechniqueWeights
from vim_key_trainer.domain.keys import KeyToken

ESC = KeyToken("special", "esc")
ENTER = KeyToken("special", "enter")
REDO = KeyToken("chord", "ctrl+r")
_STRUCTURE_VARIANTS = 28
_DELIMITED_OBJECTS = (
    ('"', '"', '"'),
    ("'", "'", "'"),
    ("`", "`", "`"),
    ("(", ")", "("),
    ("(", ")", ")"),
    ("(", ")", "b"),
    ("[", "]", "["),
    ("[", "]", "]"),
    ("{", "}", "{"),
    ("{", "}", "}"),
    ("{", "}", "B"),
    ("<", ">", "<"),
    ("<", ">", ">"),
)
_WORD_VARIANTS = 23 + 2 * len(_DELIMITED_OBJECTS)


def characters(text: str) -> tuple[KeyToken, ...]:
    return tuple(KeyToken("char", char) for char in text)


def counted(count: int, command: str) -> str:
    return command if count == 1 else f"{count}{command}"


@dataclass(frozen=True, slots=True)
class RecipeAction:
    column: int | None
    keys: tuple[KeyToken, ...]
    text: str


@dataclass(frozen=True, slots=True)
class EditRecipe:
    row: int
    span: int
    replacement: tuple[str, ...]
    actions: tuple[RecipeAction, ...]


@dataclass(frozen=True, slots=True)
class DocumentPlan:
    lines: tuple[str, ...]
    goal_lines: tuple[str, ...]
    recipes: tuple[EditRecipe, ...]
    context_title: str
    code_excerpt: CodeExcerpt | None = None


@dataclass(frozen=True, slots=True)
class _Context:
    title: str
    prefix: str
    names: tuple[str, ...]
    states: tuple[str, ...]


_CONTEXTS = (
    _Context(
        "서비스 설정",
        "service",
        ("cache", "proxy", "worker", "queue"),
        ("enabled", "stable", "local", "ready"),
    ),
    _Context(
        "재고 목록",
        "stock",
        ("cable", "screen", "sensor", "switch"),
        ("packed", "checked", "stored", "ready"),
    ),
    _Context(
        "배포 체크리스트",
        "release",
        ("api", "client", "assets", "docs"),
        ("tested", "signed", "staged", "verified"),
    ),
    _Context(
        "작업 기록",
        "task",
        ("backup", "report", "build", "cleanup"),
        ("daily", "weekly", "manual", "queued"),
    ),
    _Context(
        "관측 데이터",
        "sample",
        ("north", "south", "east", "west"),
        ("valid", "recent", "clean", "synced"),
    ),
)


def _name(context: _Context, rng: Random, row: int) -> str:
    return f"{rng.choice(context.names)}_{row + 1:02}"


def _context_line(context: _Context, rng: Random, row: int) -> str:
    name = _name(context, rng, row)
    value = rng.randrange(10, 900)
    status = rng.choice(context.states)
    layouts = (
        f"{context.prefix} {name} = {value} # {status}",
        f"  {name}: value={value}; state={status}",
        f"{name} | {value} | {status}",
        f"check {name} limit {value} {status}",
    )
    return layouts[row % len(layouts)]


def _number_recipe(
    lines: list[str], row: int, variant: int, context: _Context, rng: Random
) -> EditRecipe:
    name = _name(context, rng, row)
    width = 1 + variant % 4
    old = str(rng.randrange(10 ** (width - 1), 10**width))
    new = str(rng.randrange(1, 10 ** (1 + rng.randrange(4))))
    if new == old:
        new = str(int(old) + 1)
    formats = (
        (f"{name} = ", " # verified"),
        (f"  {context.prefix} {name} budget ", " units"),
        (f"{name} | count=", " | ready"),
        (f"set {name} retry=", ""),
    )
    prefix, suffix = formats[variant % len(formats)]
    if variant % 8 in {6, 7}:
        delta = rng.randrange(1, 10)
        increase = variant % 8 == 6
        # 값의 증감은 글자 수 대신 명시한 수치 차이를 count로 사용한다.
        if not increase:
            old = str(max(int(old), delta + 1))
        new = str(int(old) + (delta if increase else -delta))
        keys = characters(str(delta)) if delta > 1 else ()
        keys += (KeyToken("chord", "ctrl+a" if increase else "ctrl+x"),)
        text = (
            f"기존 값 {old}을 실제 Control+{'A' if increase else 'X'}로 "
            f"{delta}만큼 {'늘립니다' if increase else '줄입니다'}."
        )
    elif variant % 8 in {0, 5}:
        old = str(rng.randrange(10))
        new = str((int(old) + rng.randrange(1, 10)) % 10)
        keys = characters("r" + new)
        text = f"r로 기존 값 {old} 한 글자를 {new}로 교체합니다."
    else:
        command = "C" if variant % 8 == 3 else "cw" if variant % 8 == 2 else "ciw"
        if command == "C":
            suffix = ""
        keys = characters(command + new) + (ESC,)
        scope = "부터 줄 끝까지" if command == "C" else " 전체를"
        text = f"{command}로 기존 값 {old}{scope} {new}로 바꾸고 Esc로 마칩니다."
    lines[row] = prefix + old + suffix
    return EditRecipe(
        row,
        1,
        (prefix + new + suffix,),
        (RecipeAction(len(prefix), keys, text),),
    )


def _line_recipe(
    lines: list[str], row: int, variant: int, context: _Context, rng: Random
) -> EditRecipe:
    count = 2 if variant % 3 == 1 else 1
    markers = ("obsolete", "duplicate", "debug", "retired")
    for offset in range(count):
        lines[row + offset] = (
            f"{rng.choice(markers)} {context.prefix} "
            f"{_name(context, rng, row + offset)} remove"
        )
    command = f"d{count}d" if count > 1 and variant % 2 else counted(count, "dd")
    return EditRecipe(
        row,
        count,
        (),
        (
            RecipeAction(
                None,
                characters(command),
                f"{row + 1}행부터 불필요한 {count}개 줄을 삭제합니다.",
            ),
        ),
    )


def _word_recipe(
    lines: list[str], row: int, variant: int, context: _Context, rng: Random
) -> EditRecipe:
    name = _name(context, rng, row)
    variant %= _WORD_VARIANTS
    if variant >= 23:
        return _delimited_object_recipe(lines, row, variant - 23, context, name)
    if variant >= 14:
        return _change_object_recipe(lines, row, variant - 14, context, name)
    if variant >= 5:
        return _extended_word_recipe(lines, row, variant, context, name)
    recipes = (
        ("", "obsolete ", f"{name} ready", 1),
        (f"route {name} ", "temporary legacy ", "active", 2),
        (f"{context.prefix} ", "??? ", f"{name} verified", 1),
        ("  ", "TODO REMOVE ", f"{name} checked", 2),
        (f"check {name} ", "old stale draft unused ", "ready", 4),
    )
    prefix, removed, suffix, count = recipes[variant % len(recipes)]
    if count == 4:
        # 네 단어를 세는 대신 눈에 보이는 필드 구분자 앞까지만 지운다.
        suffix = "; " + suffix
        command = "dt;"
    elif count > 1 and variant == 1:
        command = f"d{count}w"
    else:
        command = counted(count, "dw")
    lines[row] = prefix + removed + suffix
    return EditRecipe(
        row,
        1,
        (prefix + suffix,),
        (
            RecipeAction(
                len(prefix),
                characters(command),
                f"{row + 1}행의 불필요한 {removed.rstrip()!r}을 "
                + (
                    "세미콜론 앞까지 dt;로 삭제합니다." if count == 4 else "삭제합니다."
                ),
            ),
        ),
    )


def _change_object_recipe(
    lines: list[str], row: int, variant: int, context: _Context, name: str
) -> EditRecipe:
    """구분자 보존과 around 공백 규칙이 다른 수정 과제를 명시한다."""
    prefix = f"{context.prefix} {name} "
    if variant in {0, 1, 2, 8}:
        old, new = (
            ("obsolete", "stable") if variant != 1 else ("old/path?x=1", "prod/v2")
        )
        command = "bcw" if variant == 8 else ("ciw", "ciW", "cw")[variant]
        suffix = " ready"
        column = len(prefix) + (0 if variant == 2 else 2)
    elif variant in {3, 4, 5}:
        left, right, command = (
            ('"', '"', 'ci"'),
            ("(", ")", "ci)"),
            ("[", "]", "ci]"),
        )[variant - 3]
        prefix += left
        old, new, suffix = "draft value", "verified", right + " ready"
        column = len(prefix) + 3
    else:
        old, new, suffix = "obsolete ", "", "ready"
        command = "daw" if variant == 6 else "daW"
        column = len(prefix) + 2
    lines[row] = prefix + old + suffix
    keys = characters(command + new)
    if command.startswith("c") or command == "bcw":
        keys += (ESC,)
    return EditRecipe(
        row,
        1,
        (prefix + new + suffix,),
        (
            RecipeAction(
                column,
                keys,
                f"{row + 1}행의 {old.rstrip()!r}을 {command}로 "
                + (
                    f"{new!r}로 바꾸고 Esc로 마칩니다."
                    if new
                    else "주변 공백과 함께 삭제합니다."
                ),
            ),
        ),
    )


def _delimited_object_recipe(
    lines: list[str], row: int, variant: int, context: _Context, name: str
) -> EditRecipe:
    """구분자를 남기는 inner와 구분자까지 지우는 around를 모두 연습한다."""
    opening, closing, selector = _DELIMITED_OBJECTS[variant // 2]
    inner = variant % 2 == 0
    prefix = f"{context.prefix} {name} value="
    old, new, suffix = "draft value", "verified", "; ready"
    lines[row] = prefix + opening + old + closing + suffix
    command = ("ci" if inner else "da") + selector
    keys = characters(command + (new if inner else "")) + ((ESC,) if inner else ())
    goal = prefix + (opening + new + closing if inner else "") + suffix
    return EditRecipe(
        row,
        1,
        (goal,),
        (
            RecipeAction(
                len(prefix) + len(opening) + 3,
                keys,
                f"{row + 1}행에서 {command}로 "
                + (
                    f"구분자를 남기고 내용만 {new!r}로 바꾼 뒤 Esc로 마칩니다."
                    if inner
                    else "내용과 양쪽 구분자를 함께 삭제합니다."
                ),
            ),
        ),
    )


def _extended_word_recipe(
    lines: list[str], row: int, variant: int, context: _Context, name: str
) -> EditRecipe:
    if variant in {11, 12}:
        prefix, old, new, suffix, command = (
            (f"{name} state=", "readys", "ready", "; verified", "ex")
            if variant == 11
            else ("endpoint ", "prod/v2?", "prod/v2", " ready", "Ex")
        )
        lines[row] = prefix + old + suffix
        return EditRecipe(
            row,
            1,
            (prefix + new + suffix,),
            (
                RecipeAction(
                    len(prefix),
                    characters(command),
                    f"{row + 1}행에서 {'e' if variant == 11 else 'E'}로 "
                    "끝에 이동하고 x로 잘못 붙은 문자를 삭제합니다.",
                ),
            ),
        )
    if variant == 13:
        prefix, old, new = (
            f"check endpoint for {name} use ",
            "staging/v1?debug=yes",
            "prod/v2",
        )
        lines[row] = prefix + old
        return EditRecipe(
            row,
            1,
            (prefix + new,),
            (
                RecipeAction(
                    None,
                    characters("$BdE"),
                    f"{row + 1}행 끝에서 B로 WORD 시작에 돌아와 dE로 삭제합니다.",
                ),
                RecipeAction(
                    None,
                    characters("a" + new) + (ESC,),
                    f"남은 공백 뒤에 {new!r}을 입력하고 Esc로 마칩니다.",
                ),
            ),
        )
    if variant in {5, 6}:
        removed = "old/path?debug=yes " if variant == 5 else "old/path legacy=value "
        prefix, suffix = f"{context.prefix} ", f"{name} ready"
        lines[row] = prefix + removed + suffix
        command = "dW" if variant == 5 else "d2W"
        return EditRecipe(
            row,
            1,
            (prefix + suffix,),
            (
                RecipeAction(
                    len(prefix),
                    characters(command),
                    f"{row + 1}행에서 기호를 포함한 WORD와 뒤 공백을 삭제합니다.",
                ),
            ),
        )
    if variant in {7, 9}:
        prefix, old, new, suffix = f"{name} state=", "obsolete", "stable", "; ready"
        command = "diw" if variant == 7 else "de"
    else:
        prefix, old, new, suffix = (
            "endpoint ",
            "staging/v1?debug=yes",
            "prod/v2",
            " ready",
        )
        command = "diW" if variant == 8 else "dE"
    lines[row] = prefix + old + suffix
    # inner object는 단어 중간에서도 전체 범위를 선택한다. e/E 범위는 시작점부터다.
    column = len(prefix) + (2 if command in {"diw", "diW"} else 0)
    scope = "WORD" if command in {"diW", "dE"} else "word"
    return EditRecipe(
        row,
        1,
        (prefix + new + suffix,),
        (
            RecipeAction(
                column,
                characters(command),
                f"{row + 1}행의 {scope} 값 {old!r}을 {command}로 삭제합니다.",
            ),
            RecipeAction(
                None,
                characters("i" + new) + (ESC,),
                f"값 {new!r}을 입력하고 Esc로 마칩니다. 주변 구분자는 유지합니다.",
            ),
        ),
    )


def _append_recipe(
    lines: list[str], row: int, variant: int, context: _Context, rng: Random
) -> EditRecipe:
    if variant == 8:
        word = re.findall(r"[A-Za-z0-9_]+", lines[row])[0]
        return EditRecipe(
            row,
            1,
            (lines[row] + " ; " + word,),
            (
                RecipeAction(
                    0,
                    characters("^yiwA ; ") + (ESC,) + characters("p"),
                    "yiw로 첫 단어를 복사하고 줄 끝에 p로 다시 붙입니다.",
                ),
            ),
        )
    owner = rng.choice(("alice", "bob", "cora", "dana", "erin"))
    additions = (
        f" # owner={owner}",
        f" ; checked={rng.randrange(10, 99)}",
        f" [{rng.choice(context.states)}]",
        f" // batch-{rng.randrange(10, 99)}",
    )
    replacement: tuple[str, ...]
    if variant % 8 in {4, 5, 6}:
        note = f"# {owner}: verify {_name(context, rng, row)}"
        command = "O" if variant % 8 == 5 else "o"
        replacement = (note, lines[row]) if command == "O" else (lines[row], note)
        keys = characters(command + note) + (ESC,)
        text = (
            f"{row + 1}행 {'위' if command == 'O' else '아래'}에 "
            f"{command}로 새 메모 줄을 추가합니다."
        )
    elif variant % 8 == 7:
        replacement = (lines[row], lines[row])
        keys = characters("yyp")
        text = f"{row + 1}행을 yy로 복사하고 p로 아래에 같은 줄을 추가합니다."
    elif variant % 8 == 3:
        note = f"# {owner}: verify {_name(context, rng, row)}"
        replacement = (lines[row], note)
        keys = characters("A") + (ENTER,) + characters(note) + (ESC,)
        text = f"{row + 1}행 끝에서 Enter로 새 메모 줄을 추가합니다."
    else:
        addition = additions[variant % len(additions)]
        replacement = (lines[row] + addition,)
        keys = characters("A" + addition) + (ESC,)
        text = f"{row + 1}행 끝에 {addition!r}을 추가합니다."
    return EditRecipe(row, 1, replacement, (RecipeAction(None, keys, text),))


def _structure_recipe(
    lines: list[str], row: int, variant: int, context: _Context, rng: Random
) -> EditRecipe:
    """한 구간 안에서만 줄·공백·문자 상태를 바꾸는 복합 기술."""
    name = _name(context, rng, row)
    variant %= _STRUCTURE_VARIANTS
    if variant == 0:
        lines[row] = f"{context.prefix} {name}"
        lines[row + 1] = "    ready"
        return EditRecipe(
            row,
            2,
            (lines[row] + " ready",),
            (
                RecipeAction(
                    None, characters("J"), "J로 두 줄 사이 공백을 정리하며 합칩니다."
                ),
            ),
        )
    if variant in {1, 2}:
        line = f"{name} = ready"
        lines[row] = line if variant == 1 else "    " + line
        goal = "    " + line if variant == 1 else line
        command = ">>" if variant == 1 else "<<"
        text = "들여씁니다" if variant == 1 else "내어씁니다"
        return EditRecipe(
            row,
            1,
            (goal,),
            (
                RecipeAction(
                    None, characters(command), f"{command}로 현재 줄을 네 칸 {text}."
                ),
            ),
        )
    if variant == 3:
        lines[row] = f"{name}=x; ready"
        return EditRecipe(
            row,
            1,
            (f"{name}=9; ready",),
            (
                RecipeAction(
                    0,
                    characters("f=lr9"),
                    "f=로 구분자를 찾고 l·r9로 잘못된 값을 교체합니다.",
                ),
            ),
        )
    if variant == 4:
        prefix = f"{context.prefix} {name} "
        lines[row] = prefix + "draft pending"
        return EditRecipe(
            row,
            1,
            (prefix + "ready",),
            (
                RecipeAction(
                    len(prefix),
                    characters("Cready") + (ESC,),
                    "C로 줄 끝의 상태를 한 번에 변경하고 Esc로 마칩니다.",
                ),
            ),
        )
    if variant == 5:
        prefix = f"{context.prefix} {name} ready"
        lines[row] = prefix + " # debug only"
        return EditRecipe(
            row,
            1,
            (prefix,),
            (
                RecipeAction(
                    len(prefix),
                    characters("D"),
                    "D로 불필요한 줄 끝 메모를 삭제합니다.",
                ),
            ),
        )
    if variant in {6, 7}:
        prefix = f"{context.prefix} {name} "
        status = rng.choice(context.states)
        old, new = (
            (status, status.upper()) if variant == 6 else (status.upper(), status)
        )
        command = "gUiw" if variant == 6 else "guiw"
        lines[row] = prefix + old
        return EditRecipe(
            row,
            1,
            (prefix + new,),
            (
                RecipeAction(
                    len(prefix),
                    characters(command),
                    f"{command}로 길이를 세지 않고 "
                    "상태 단어 전체의 대소문자를 바꿉니다.",
                ),
            ),
        )
    if variant == 8:
        prefix = f"{context.prefix} {name} "
        lines[row] = prefix + "obsolete"
        lines[row + 1] = prefix + "pending"
        return EditRecipe(
            row,
            2,
            (prefix + "ready", prefix + "ready"),
            (
                RecipeAction(
                    len(prefix),
                    characters("ciwready") + (ESC,),
                    "첫 상태를 ciw로 ready로 변경합니다.",
                ),
                RecipeAction(
                    None,
                    characters("j$b."),
                    "다음 줄의 단어로 이동하고 .으로 같은 변경을 반복합니다.",
                ),
            ),
        )
    if variant == 9:
        prefix = f"{context.prefix} {name} "
        lines[row] = prefix + "ready"
        return EditRecipe(
            row,
            1,
            (prefix + "READY",),
            (
                RecipeAction(
                    len(prefix),
                    characters("veU"),
                    "v로 시작해 e로 단어 끝까지 선택하고 U로 대문자로 바꿉니다.",
                ),
            ),
        )
    if variant == 23:
        prefix = f"{context.prefix} {name} "
        lines[row] = prefix + "obsolete; pending"
        keys = characters("ciwready") + (ESC,) + characters("f;w.")
        return EditRecipe(
            row,
            1,
            (prefix + "ready; ready",),
            (
                RecipeAction(
                    len(prefix),
                    keys,
                    "첫 상태를 바꾼 뒤 f;·w·.으로 다음 상태도 고칩니다.",
                ),
            ),
        )
    if variant == 24:
        lines[row] = f"{context.prefix} {name} ready"
        return EditRecipe(
            row,
            1,
            ("    " + lines[row],),
            (
                RecipeAction(
                    None, characters("V>"), "V로 행 전체를 선택하고 >로 들여씁니다."
                ),
            ),
        )
    if variant == 25:
        lines[row] = f"old {name} ready"
        lines[row + 1] = f"old {name} checked"
        return EditRecipe(
            row,
            2,
            (
                lines[row].replace("old", "OLD", 1),
                lines[row + 1].replace("old", "OLD", 1),
            ),
            (
                RecipeAction(
                    0,
                    (KeyToken("chord", "ctrl+v"),) + characters("j2lU"),
                    "실제 Control+V로 두 행의 old 열만 선택하고 U로 대문자로 바꿉니다.",
                ),
            ),
        )
    if variant == 26:
        prefix = f"{context.prefix} {name}. "
        lines[row] = prefix + "Old sentence. Keep this sentence."
        return EditRecipe(
            row,
            1,
            (prefix + "Verified sentence. Keep this sentence.",),
            (
                RecipeAction(
                    len(prefix),
                    characters("cisVerified sentence.") + (ESC,),
                    "cis로 첫 문장 전체를 바꾸고 다음 문장은 남깁니다.",
                ),
            ),
        )
    if variant == 27:
        lines[row : row + 3] = ("", f"Old paragraph for {name}.", "")
        return EditRecipe(
            row,
            3,
            ("", "Verified paragraph.", ""),
            (
                RecipeAction(
                    0,
                    characters("jcipVerified paragraph.") + (ESC,),
                    "빈 줄로 나뉜 문단으로 이동해 cip로 내용만 바꿉니다.",
                ),
            ),
        )
    if variant in {10, 11, 13, 14, 15, 16, 17, 18}:
        prefix = f"{context.prefix} {name} "
        old = f"broken_{row}_tag"
        lines[row] = prefix + old
        if variant == 10:
            keys = characters("0/" + old) + (ENTER,) + characters("ciwready") + (ESC,)
            text = "고유한 오류 표식을 /로 검색하고 Enter 확정 후 ciw로 고칩니다."
        elif variant == 11:
            keys = characters(f":s/{old}/ready/") + (ENTER,)
            text = "현재 줄의 오류 표식을 :s 치환으로 고치고 Enter로 확정합니다."
        elif variant == 13:
            lines[row] += " verified"
            keys = characters("$?" + old) + (ENTER,) + characters("ciwready") + (ESC,)
            text = "줄 끝에서 ?로 오류 표식을 뒤로 검색하고 ciw로 고칩니다."
        elif variant == 14:
            lines[row] += " " + old
            keys = (
                characters("0/" + old)
                + (ENTER,)
                + characters("nciwready")
                + (ESC,)
                + characters("N.")
            )
            text = "검색 뒤 n으로 다음 표식을 고치고 N·.으로 앞 표식도 고칩니다."
        elif variant in {15, 18}:
            lines[row] += " " + old
            search = "*" if variant == 15 else "#"
            keys = characters(search + "ciwready") + (ESC,) + characters("N.")
            text = f"{search}로 같은 단어를 찾아 고치고 N·.으로 다른 표식도 고칩니다."
        else:
            lines[row] += " " + old
            flags = "g" if variant == 16 else "gi"
            if variant == 17:
                lines[row] = prefix + old.upper() + " " + old
            keys = characters(f":s/{old}/ready/{flags}") + (ENTER,)
            text = (
                ":s의 g로 현재 줄의 모든 표식을 치환합니다."
                if variant == 16
                else ":s의 gi로 대소문자를 구분하지 않고 모든 표식을 치환합니다."
            )
        suffix = " verified" if variant == 13 else ""
        replacement = prefix + "ready" + suffix
        if variant in {14, 15, 16, 17, 18}:
            replacement += " ready"
        column = len(prefix) if variant == 15 else 0
        if variant == 18:
            column = len(prefix) + len(old) + 1
        return EditRecipe(
            row,
            1,
            (replacement,),
            (RecipeAction(column, keys, text),),
        )
    if variant == 12:
        prefix = f"{name} (draft (value) tag) "
        lines[row] = prefix + "obsolete"
        return EditRecipe(
            row,
            1,
            (prefix + "ready",),
            (
                RecipeAction(
                    0,
                    characters("f(%wciwready") + (ESC,),
                    "f(로 여는 괄호를 찾고 %로 중첩된 괄호짝을 넘어 상태를 고칩니다.",
                ),
            ),
        )
    if variant == 19:
        old_values = rng.sample("123456789", 3)
        new_values = old_values[1:] + old_values[:1]
        fields = ("limit", "retry", "delay")
        prefix = f"{name} "
        lines[row] = prefix + "; ".join(
            f"{field}={value}" for field, value in zip(fields, old_values, strict=True)
        )
        goal = prefix + "; ".join(
            f"{field}={value}" for field, value in zip(fields, new_values, strict=True)
        )
        actions = tuple(
            RecipeAction(
                0 if index == 0 else None,
                characters(("f=" if index == 0 else ";") + "lr" + value),
                (
                    "f=로 첫 필드의 구분자를 찾고 l·r로 한 자리 값을 바꿉니다."
                    if index == 0
                    else f";로 같은 방향의 다음 =를 찾아 {field} 값을 바꿉니다."
                ),
            )
            for index, (field, value) in enumerate(zip(fields, new_values, strict=True))
        )
        return EditRecipe(row, 1, (goal,), actions)
    # 남은 세 유형은 단어 수가 달라도 같은 구분자로 수정 범위를 정한다.
    prefix = f"{name} state="
    status = rng.choice(("draft", "needs review", "waiting for approval"))
    suffix = "; owner=team"
    lines[row] = prefix + status + suffix
    if variant == 22:
        keys = characters("vt;U")
        replacement = prefix + status.upper() + suffix
        text = "v·t;로 세미콜론 앞의 상태만 선택하고 U로 대문자로 바꿉니다."
    else:
        command = "ct;" if variant == 20 else "cf;"
        separator = ";" if variant == 20 else ","
        keys = characters(command + "ready" + ("," if variant == 21 else "")) + (ESC,)
        replacement = prefix + "ready" + separator + " owner=team"
        text = (
            "ct;로 세미콜론을 남기고 상태 문구만 ready로 바꿉니다."
            if variant == 20
            else "cf;로 세미콜론까지 바꾸어 상태를 ready,로 정리합니다."
        )
    return EditRecipe(row, 1, (replacement,), (RecipeAction(len(prefix), keys, text),))


def _undo_recipe(
    lines: list[str], row: int, variant: int, context: _Context, rng: Random
) -> EditRecipe:
    original = lines[row]
    if variant % 4 == 0:
        edit = characters(counted(rng.randrange(1, 4), "x"))
        text = "문자를 삭제"
    elif variant % 4 == 1:
        edit = characters("dw")
        text = "첫 단어를 삭제"
    elif variant % 4 == 2:
        edit = characters("A # trial") + (ESC,)
        text = "시험 메모를 추가"
    else:
        edit = characters("dd")
        text = "현재 줄을 삭제"
    actions = [
        RecipeAction(0, edit, f"{row + 1}행에서 {text}합니다."),
        RecipeAction(None, characters("u"), "u로 방금 변경을 복원합니다."),
    ]
    if variant % 2 == 0:
        actions.extend(
            (
                RecipeAction(None, (REDO,), "실제 Control+R로 변경을 다시 적용합니다."),
                RecipeAction(None, characters("u"), "다시 u로 원래 문서를 복원합니다."),
            )
        )
    return EditRecipe(row, 1, (original,), tuple(actions))


_RecipeFactory = Callable[[list[str], int, int, _Context, Random], EditRecipe]
_FACTORIES: dict[str, _RecipeFactory] = {
    "editing_numbers": _number_recipe,
    "editing_delete_line": _line_recipe,
    "editing_delete_word": _word_recipe,
    "editing_append": _append_recipe,
    "editing_undo": _undo_recipe,
}
_RecipeOption = tuple[_RecipeFactory, tuple[int, ...]]
_RecipeGroups = tuple[tuple[_RecipeOption, ...], ...]


def _options(factory: _RecipeFactory, *variants: int) -> tuple[_RecipeOption, ...]:
    return tuple((factory, (variant,)) for variant in variants)


# 같은 객체의 양쪽 괄호 표기와 b/B는 새 기술이 아닌 하위 표기다.
_OBJECT_SPELLINGS = ((0,), (1,), (2,), (3, 4, 5), (6, 7), (8, 9, 10), (11, 12))
_WORD_GROUPS: _RecipeGroups = (
    _options(_word_recipe, 0, 1, 2, 3, 20),
    _options(_word_recipe, 5, 6, 21),
    _options(_word_recipe, 7, 9, 14, 16, 22),
    _options(_word_recipe, 8, 10, 13, 15),
    tuple(
        (_word_recipe, tuple(23 + 2 * index for index in group))
        for group in _OBJECT_SPELLINGS
    ),
    tuple(
        (_word_recipe, tuple(24 + 2 * index for index in group))
        for group in _OBJECT_SPELLINGS
    ),
    _options(_word_recipe, 4, 11, 12),
)
_NUMBER_GROUPS: _RecipeGroups = (
    ((_number_recipe, (0, 5)),),
    ((_number_recipe, (1, 4)),),
    _options(_number_recipe, 2),
    _options(_number_recipe, 3),
    _options(_number_recipe, 6),
    _options(_number_recipe, 7),
)
_APPEND_GROUPS: _RecipeGroups = (
    _options(_append_recipe, 0, 1, 2),
    _options(_append_recipe, 3, 4, 5, 6),
    _options(_append_recipe, 7, 8),
)
_COMPOUND_GROUPS: _RecipeGroups = (
    tuple(option for group in _NUMBER_GROUPS for option in group),
    tuple(option for group in _WORD_GROUPS for option in group)
    + _options(_structure_recipe, 26, 27),
    _options(_append_recipe, 0, 1, 2, 3, 4, 5, 6),
    _options(_append_recipe, 7, 8),
    _options(_line_recipe, 0, 1, 2) + _options(_structure_recipe, 0, 1, 2, 4, 5),
    _options(_structure_recipe, 10, 13, 14, 15, 18),
    _options(_structure_recipe, 11, 16, 17),
    _options(_structure_recipe, 12, 3, 19, 20, 21),
    _options(_structure_recipe, 6, 7, 9, 22, 24, 25),
    _options(_structure_recipe, 8, 23),
)
_COMPOUND_TECHNIQUES = (
    "numbers",
    "word",
    "insertion",
    "copy",
    "structure",
    "search",
    "substitution",
    "movement",
    "visual",
    "repeat",
)


def _balanced_indices(size: int, count: int, rng: Random) -> list[int]:
    result: list[int] = []
    while len(result) < count:
        cycle = list(range(size))
        rng.shuffle(cycle)
        if result and size > 1 and cycle[0] == result[-1]:
            cycle[0], cycle[-1] = cycle[-1], cycle[0]
        result.extend(cycle)
    return result[:count]


def _recipe_schedule(
    profile_id: str, count: int, rng: Random, weights: EditTechniqueWeights | None
) -> list[tuple[_RecipeFactory, int]]:
    groups = {
        "editing_delete_word": _WORD_GROUPS,
        "editing_compound": _COMPOUND_GROUPS,
        "editing_numbers": _NUMBER_GROUPS,
        "editing_append": _APPEND_GROUPS,
    }.get(profile_id)
    if groups is None:
        factory = _FACTORIES[profile_id]
        size = 5 if factory is _line_recipe else 4
        return [(factory, variant) for variant in _balanced_indices(size, count, rng)]
    # 기술 계열을 먼저 고른다. 변형·별칭의 개수가 많은 기술이 더 자주
    # 뽑히지 않도록, 그 안의 문맥과 표기는 별도의 층에서 선택한다.
    selected = (
        _weighted_indices(weights or EditTechniqueWeights(), count, rng)
        if profile_id == "editing_compound"
        else _balanced_indices(len(groups), count, rng)
    )
    patterns = {
        group: iter(_balanced_indices(len(groups[group]), selected.count(group), rng))
        for group in set(selected)
    }
    schedule: list[tuple[_RecipeFactory, int]] = []
    word_scopes = _WORD_GROUPS + (_options(_structure_recipe, 26, 27),)
    word_order = iter(
        _balanced_indices(len(word_scopes), selected.count(1), rng)
        if profile_id == "editing_compound"
        else ()
    )
    movement_scopes = (
        _options(_structure_recipe, 12),
        _options(_structure_recipe, 3, 19, 20, 21),
    )
    movement_order = iter(
        _balanced_indices(2, selected.count(7), rng)
        if profile_id == "editing_compound"
        else ()
    )
    for group in selected:
        if profile_id == "editing_compound" and group == 1:
            # 복합의 객체 과제 안에서도 단어·구분자·문장/문단을 같은 비중으로 고른다.
            option = rng.choice(word_scopes[next(word_order)])
        elif profile_id == "editing_compound" and group == 7:
            option = rng.choice(movement_scopes[next(movement_order)])
        else:
            option = groups[group][next(patterns[group])]
        schedule.append((option[0], rng.choice(option[1])))
    return schedule


def _weighted_indices(
    weights: EditTechniqueWeights, count: int, rng: Random
) -> list[int]:
    proportions = tuple(
        getattr(weights, technique) for technique in _COMPOUND_TECHNIQUES
    )
    unit = gcd(*proportions)
    result: list[int] = []
    pool: list[int] = []
    while len(result) < count:
        if not pool:
            pool = [
                index
                for index, weight in enumerate(proportions)
                for _ in range(weight // unit)
            ]
            rng.shuffle(pool)
        if result and pool[-1] == result[-1]:
            alternative = next(
                (index for index, group in enumerate(pool) if group != result[-1]),
                None,
            )
            if alternative is not None:
                pool[-1], pool[alternative] = pool[alternative], pool[-1]
        result.append(pool.pop())
    return result


def _recipe_span(factory: _RecipeFactory, variant: int) -> int:
    if factory is _line_recipe and variant % 3 == 1:
        return 2
    if factory is _structure_recipe:
        if variant in {0, 8, 25}:
            return 2
        if variant == 27:
            return 3
    return 1


def build_document_plan(
    profile_id: str,
    line_count: int,
    rng: Random,
    weights: EditTechniqueWeights | None = None,
) -> DocumentPlan:
    """최소 7곳을 고치고 긴 문서는 수정량도 늘어나는 문서를 만든다."""
    context = rng.choice(_CONTEXTS)
    lines = [_context_line(context, rng, row) for row in range(line_count)]
    recipes: list[EditRecipe] = []
    repair_count = max(7, line_count // 4)
    for index, (factory, recipe_variant) in enumerate(
        _recipe_schedule(profile_id, repair_count, rng, weights)
    ):
        start = index * line_count // repair_count
        stop = (index + 1) * line_count // repair_count
        if _recipe_span(factory, recipe_variant) > stop - start:
            recipe_variant = (
                {0: 1, 8: 23, 25: 24, 27: 26}[recipe_variant]
                if factory is _structure_recipe
                else 0
            )
        span = _recipe_span(factory, recipe_variant)
        # 가능하면 다음 수정과 사이에 원문 한 줄을 남긴다. 줄 추가와
        # 다음 줄 삭제가 하나의 교체로 합쳐지는 과제도 줄인다.
        row = start + rng.randrange(max(1, stop - start - span))
        if recipes and recipes[-1].row + recipes[-1].span == row:
            previous = recipes[-1]
            previous_delta = len(previous.replacement) - previous.span
            decreases_lines = factory is _line_recipe or (
                factory is _structure_recipe and recipe_variant == 0
            )
            if previous_delta > 0 and decreases_lines:
                # 추가와 바로 뒤 삭제가 하나의 교체로 합쳐지지 않게 한다.
                factory, recipe_variant, span = _structure_recipe, 1, 1
            elif previous_delta < 0 and factory is _append_recipe:
                if recipe_variant == 7:
                    recipe_variant = 8
                elif recipe_variant in {3, 4, 5, 6}:
                    recipe_variant = 0
        recipes.append(factory(lines, row, recipe_variant, context, rng))
    initial = tuple(lines)
    goal = list(initial)
    # 뒤에서부터 적용하면 줄 삭제·추가 이후에도 앞쪽의 원본 좌표가 유지된다.
    ordered = tuple(reversed(recipes))
    for recipe in ordered:
        goal[recipe.row : recipe.row + recipe.span] = recipe.replacement
    return DocumentPlan(initial, tuple(goal), ordered, context.title)
