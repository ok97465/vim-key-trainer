"""메모리 문서를 위한 명시적인 Vim magic 패턴·치환 부분집합.

Python 정규식을 그대로 노출하지 않는다. 그룹·선택·역참조와 여러 반복
원자를 거부해 GUI에서 실행하는 검색의 역추적 비용을 제한한다.
"""

# Standard library imports
import re
from bisect import bisect_left, bisect_right

_MAX_PATTERN = 256


def compile_pattern(pattern: str, *, ignore_case: bool = False) -> re.Pattern[str]:
    """지원하는 Vim magic 패턴을 검증하고 ASCII 정규식으로 바꾼다."""
    if not pattern:
        raise ValueError("검색어가 비어 있습니다. 이전 검색어를 먼저 지정하세요.")
    if len(pattern) > _MAX_PATTERN or any(
        not char.isascii() or not char.isprintable() for char in pattern
    ):
        raise ValueError("검색어는 ASCII 256자 이하여야 합니다.")
    output: list[str] = []
    index = 0
    repeats = 0
    can_repeat = False
    flags = re.ASCII | (re.IGNORECASE if ignore_case else re.NOFLAG)
    force_ignore = False
    force_match = False
    while index < len(pattern):
        char = pattern[index]
        if char == "\\":
            index += 1
            if index == len(pattern):
                raise ValueError("검색어 끝의 역슬래시에는 다음 문자가 필요합니다.")
            escaped = pattern[index]
            if escaped in "cC":
                force_ignore |= escaped == "c"
                force_match |= escaped == "C"
            elif escaped in "<>":
                output.append(r"(?<!\w)(?=\w)" if escaped == "<" else r"(?<=\w)(?!\w)")
                can_repeat = False
            elif escaped in "dDsSwW":
                output.append("\\" + escaped)
                can_repeat = True
            elif escaped in "+?{":
                if not can_repeat:
                    raise ValueError("반복 기호 앞에 반복할 문자가 필요합니다.")
                repeats += 1
                if escaped == "{":
                    end = pattern.find("}", index + 1)
                    if end < 0:
                        raise ValueError("반복 횟수의 닫는 괄호가 없습니다.")
                    amount = pattern[index + 1 : end]
                    if not re.fullmatch(r"\d+(?:,\d*)?", amount):
                        raise ValueError("반복은 \\{n}, \\{n,m}, \\{n,}만 지원합니다.")
                    values = [int(value) for value in amount.split(",") if value]
                    if any(value > 999 for value in values):
                        raise ValueError("패턴 반복 횟수는 999 이하여야 합니다.")
                    output.append("{" + amount + "}")
                    index = end
                else:
                    output.append(escaped)
                can_repeat = False
            elif escaped.isalnum() or escaped in "()|&@%_=":
                raise ValueError(f"지원하지 않는 Vim 패턴: \\{escaped}")
            else:
                output.append(re.escape(escaped))
                can_repeat = True
        elif char == "[":
            end = index + 1
            if end < len(pattern) and pattern[end] == "^":
                end += 1
            if end < len(pattern) and pattern[end] == "]":
                end += 1
            while end < len(pattern):
                if pattern[end] == "\\":
                    end += 2
                elif pattern[end] == "]":
                    break
                else:
                    end += 1
            if end >= len(pattern):
                raise ValueError("문자 집합의 닫는 괄호가 없습니다.")
            collection = pattern[index : end + 1]
            if "[:" in collection or "[." in collection or "[=" in collection:
                raise ValueError("POSIX 문자 집합은 지원하지 않습니다.")
            # Python-only escapes must not acquire a different Vim meaning.
            if re.search(r"\\[A-Za-z0-9]", collection):
                raise ValueError(
                    "문자 집합 안의 문자 클래스 이스케이프는 지원하지 않습니다."
                )
            output.append(collection)
            index = end
            can_repeat = True
        elif char == "*":
            if not can_repeat:
                raise ValueError("반복 기호 앞에 반복할 문자가 필요합니다.")
            output.append("*")
            repeats += 1
            can_repeat = False
        elif char == ".":
            output.append(".")
            can_repeat = True
        elif char == "^" and not output:
            output.append("^")
            can_repeat = False
        elif char == "$" and re.fullmatch(r"(?:\\[cC])*", pattern[index + 1 :]):
            output.append("$")
            can_repeat = False
        elif char == "~":
            raise ValueError(
                "이전 치환 패턴 ~는 미지원입니다. 문자 ~는 \\~로 검색하세요."
            )
        else:
            output.append(re.escape(char))
            can_repeat = True
        index += 1
    if repeats > 1:
        raise ValueError("빠른 로컬 검색을 위해 패턴당 반복 원자는 하나만 지원합니다.")
    # Vim's regexp engines apply \c before \C when both are present;
    # inline case directives also override :s/i and :s/I.
    if force_ignore:
        flags |= re.IGNORECASE
    elif force_match:
        flags &= ~re.IGNORECASE
    try:
        return re.compile("".join(output), flags)
    except re.error as error:
        raise ValueError(f"잘못된 검색 패턴: {error}") from error


def find_match(
    lines: tuple[str, ...],
    row: int,
    column: int,
    pattern: str,
    forward: bool = True,
    count: int = 1,
) -> tuple[int, int] | None:
    """현재 위치 다음/이전에서 count번째 일치를 찾고 문서 끝에서 순환한다."""
    if not lines or not 0 <= row < len(lines) or count < 1:
        raise ValueError("검색의 문서·시작 행·횟수가 잘못되었습니다.")
    expression = compile_pattern(pattern)
    matches: set[tuple[int, int]] = set()
    for line_row, line in enumerate(lines):
        start = 0
        while (match := expression.search(line, start)) is not None:
            matches.add((line_row, min(match.start(), max(0, len(line) - 1))))
            # Search repeats can overlap (e.g. /ana in banana), unlike :s.
            start = match.start() + 1
            if start > len(line):
                break
    positions = sorted(matches)
    if not positions:
        return None
    if forward:
        index = bisect_right(positions, (row, column)) + count - 1
    else:
        index = bisect_left(positions, (row, column)) - count
    return positions[index % len(positions)]


def _field(
    command: str, start: int, delimiter: str, *, literal_escapes: str
) -> tuple[str, int]:
    result: list[str] = []
    index = start
    while index < len(command):
        char = command[index]
        if char == delimiter:
            return "".join(result), index + 1
        if char == "\\" and index + 1 < len(command):
            following = command[index + 1]
            # Escaping a delimiter also makes it literal in its field. Keep
            # the slash when removing it would create a pattern/replacement atom.
            result.append(
                following
                if following == delimiter and following not in literal_escapes
                else char + following
            )
            index += 2
        else:
            result.append(char)
            index += 1
    raise ValueError("치환 명령의 구분자를 닫아 주세요.")


def _replacement(value: str, matched: str) -> str:
    result: list[str] = []
    index = 0
    while index < len(value):
        char = value[index]
        if char == "&":
            result.append(matched)
        elif char == "~":
            raise ValueError(
                "이전 치환 문자열 ~는 지원하지 않습니다. 문자 ~는 \\~로 입력하세요."
            )
        elif char == "\\":
            index += 1
            if index >= len(value) or value[index] not in "&\\~":
                raise ValueError("치환 이스케이프는 \\&, \\~, \\\\만 지원합니다.")
            result.append(value[index])
        else:
            result.append(char)
        index += 1
    return "".join(result)


def substitute(
    lines: tuple[str, ...], command: str, current_row: int
) -> tuple[tuple[str, ...], int]:
    """안전한 :[range]s/pattern/replacement/[giI]를 메모리에서 실행한다."""
    if not lines or not 0 <= current_row < len(lines):
        raise ValueError("치환의 문서·현재 행이 잘못되었습니다.")
    command = command.removeprefix(":")
    if any(not char.isascii() or not char.isprintable() for char in command):
        raise ValueError("치환 명령은 표시 가능한 ASCII 문자만 지원합니다.")
    prefix = re.match(r"(?P<range>%|(?:\d+|\.|\$)(?:,(?:\d+|\.|\$))?)?s", command)
    if prefix is None or prefix.end() == len(command):
        raise ValueError("지원하는 Ex 치환은 :[range]s/검색/치환/[giI]입니다.")
    delimiter = command[prefix.end()]
    if delimiter.isalnum() or delimiter.isspace() or delimiter in '\\"|':
        raise ValueError("치환 구분자는 영숫자·공백·역슬래시 이외의 기호를 사용하세요.")
    pattern, position = _field(
        command, prefix.end() + 1, delimiter, literal_escapes=".*[^$~"
    )
    replacement, position = _field(command, position, delimiter, literal_escapes="&~")
    flags = command[position:]
    if any(flag not in "giI" for flag in flags) or len(set(flags)) != len(flags):
        raise ValueError("치환 플래그는 g, i, I만 지원합니다.")
    if "i" in flags and "I" in flags:
        raise ValueError("i와 I 플래그를 동시에 사용할 수 없습니다.")
    # Validate even when no text matches; no unsupported replacement is ignored.
    _replacement(replacement, "")
    expression = compile_pattern(pattern, ignore_case="i" in flags)
    address = prefix.group("range")

    def line_index(value: str) -> int:
        number = (
            current_row
            if value == "."
            else len(lines) - 1
            if value == "$"
            else int(value) - 1
        )
        if not 0 <= number < len(lines):
            raise ValueError("치환 범위의 행 번호가 문서를 벗어났습니다.")
        return number

    if address == "%":
        first, last = 0, len(lines) - 1
    elif address:
        values = address.split(",")
        first, last = line_index(values[0]), line_index(values[-1])
    else:
        first = last = current_row
    if first > last:
        raise ValueError("치환 시작 행은 끝 행보다 클 수 없습니다.")
    result = list(lines)
    total = 0
    for row_index in range(first, last + 1):
        result[row_index], changed = expression.subn(
            lambda match: _replacement(replacement, match.group()),
            lines[row_index],
            count=0 if "g" in flags else 1,
        )
        total += changed
    return tuple(result), total
