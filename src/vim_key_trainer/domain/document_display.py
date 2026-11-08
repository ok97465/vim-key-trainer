"""Qt와 독립적인 문서 차이·구문 색상 범위. 문서나 코드를 실행하지 않는다."""

# Standard library imports
import hashlib
import io
import keyword
import re
import token
import tokenize
from bisect import bisect_right
from collections.abc import Sequence
from dataclasses import dataclass
from difflib import SequenceMatcher
from functools import lru_cache
from typing import Literal

# Local imports
from vim_key_trainer.domain.document_types import DocumentLanguage as DocumentLanguage

ChangeKind = Literal["replace", "insert", "delete"]
_ALIGNMENT_BUDGET = 100_000
type _Opcode = tuple[str, int, int, int, int]


@dataclass(frozen=True, slots=True)
class TextSpan:
    row: int
    start: int
    end: int
    role: str

    def __post_init__(self) -> None:
        if self.row < 0 or self.start < 0 or self.end < self.start or not self.role:
            raise ValueError("잘못된 문서 표시 범위입니다.")


@dataclass(frozen=True, slots=True)
class ChangeRegion:
    id: str
    kind: ChangeKind
    current_spans: tuple[TextSpan, ...]
    goal_spans: tuple[TextSpan, ...]


@dataclass(frozen=True, slots=True)
class DocumentDiff:
    regions: tuple[ChangeRegion, ...]
    # 현재 문서의 각 행에 대응하는 목표 행. 강조와 스크롤은 같은 정렬을 쓴다.
    goal_rows: tuple[int, ...]

    @property
    def remaining_count(self) -> int:
        """표시용 남은 차이 수이며 과제 완료·채점 기준으로 사용하지 않는다."""
        return len(self.regions)

    @property
    def current_spans(self) -> tuple[TextSpan, ...]:
        return tuple(span for region in self.regions for span in region.current_spans)

    @property
    def goal_spans(self) -> tuple[TextSpan, ...]:
        return tuple(span for region in self.regions for span in region.goal_spans)


def _anchor(lines: tuple[str, ...], row: int, kind: ChangeKind) -> TextSpan:
    """글자가 없는 추가/삭제 지점도 가까운 줄의 경계에 표시한다."""
    column = 0
    if row >= len(lines):
        row = len(lines) - 1
        column = len(lines[row])
    column = min(column, len(lines[row]))
    return TextSpan(row, column, column, kind)


def _region(
    kind: ChangeKind,
    current: tuple[TextSpan, ...],
    goal: tuple[TextSpan, ...],
) -> ChangeRegion:
    identity = hashlib.blake2s(repr((kind, current, goal)).encode(), digest_size=6)
    return ChangeRegion(identity.hexdigest(), kind, current, goal)


def _line_changes(
    current: tuple[str, ...], goal: tuple[str, ...], row: int, goal_row: int
) -> list[ChangeRegion]:
    regions: list[ChangeRegion] = []
    for kind, start, end, goal_start, goal_end in _changes(
        current[row], goal[goal_row]
    ):
        if kind == "equal":
            continue
        change: ChangeKind = (
            "insert"
            if kind == "insert"
            else "delete"
            if kind == "delete"
            else "replace"
        )
        regions.append(
            _region(
                change,
                (TextSpan(row, start, end, change),),
                (TextSpan(goal_row, goal_start, goal_end, change),),
            )
        )
    return regions


def _changes(current: Sequence[str], goal: Sequence[str]) -> tuple[_Opcode, ...]:
    """행과 문자 모두 같은 양끝을 제외하고 내부 정렬 비용을 제한한다."""
    prefix = 0
    overlap = min(len(current), len(goal))
    while prefix < overlap and current[prefix] == goal[prefix]:
        prefix += 1
    suffix = 0
    while (
        suffix < overlap - prefix
        and current[len(current) - suffix - 1] == goal[len(goal) - suffix - 1]
    ):
        suffix += 1
    current_end, goal_end = len(current) - suffix, len(goal) - suffix
    current_middle, goal_middle = current[prefix:current_end], goal[prefix:goal_end]
    opcodes: list[_Opcode] = []
    if prefix:
        opcodes.append(("equal", 0, prefix, 0, prefix))
    if len(current_middle) * len(goal_middle) > _ALIGNMENT_BUDGET:
        # SequenceMatcher는 반복 행·문자에서 O(n²)까지 커진다. 큰 내부 차이는
        # 한 범위로 표시하고 동일한 접두·접미사는 보존해 GUI 지연을 제한한다.
        opcodes.append(("replace", prefix, current_end, prefix, goal_end))
    elif current_middle or goal_middle:
        opcodes.extend(
            (kind, start + prefix, end + prefix, goal_start + prefix, goal_end + prefix)
            for kind, start, end, goal_start, goal_end in SequenceMatcher(
                None, current_middle, goal_middle, autojunk=False
            ).get_opcodes()
        )
    if suffix:
        opcodes.append(("equal", current_end, len(current), goal_end, len(goal)))
    return tuple(opcodes)


@lru_cache(maxsize=16)
def compare_documents(current: tuple[str, ...], goal: tuple[str, ...]) -> DocumentDiff:
    """줄 정렬 후 바뀐 줄 안의 문자 범위를 구한다.

    한쪽에 없는 줄은 반대편에 길이 0인 anchor를 두어 빈 줄·EOF 삭제도 보인다.
    값은 불변이며, 같은 문서에서 커서만 이동할 때에는 계산 결과를 재사용한다.
    같은 양끝은 행·문자 정렬에서 제외하고 큰 내부 차이의 정렬 비용도 제한한다.
    """
    if not current or not goal:
        raise ValueError("비교 문서는 최소 한 줄이어야 합니다.")
    regions: list[ChangeRegion] = []
    goal_rows = [0] * len(current)
    for kind, start, end, goal_start, goal_end in _changes(current, goal):
        for row in range(start, end):
            # 행끼리 대응시키고 남는 현재 행은 가장 가까운 목표 행에 붙인다.
            offset = min(row - start, max(0, goal_end - goal_start - 1))
            goal_rows[row] = min(len(goal) - 1, goal_start + offset)
        if kind == "equal":
            continue
        paired = min(end - start, goal_end - goal_start)
        for offset in range(paired):
            regions.extend(
                _line_changes(current, goal, start + offset, goal_start + offset)
            )
        for row in range(start + paired, end):
            regions.append(
                _region(
                    "delete",
                    (TextSpan(row, 0, len(current[row]), "delete"),),
                    (_anchor(goal, goal_end, "delete"),),
                )
            )
        for row in range(goal_start + paired, goal_end):
            regions.append(
                _region(
                    "insert",
                    (_anchor(current, end, "insert"),),
                    (TextSpan(row, 0, len(goal[row]), "insert"),),
                )
            )
    return DocumentDiff(tuple(regions), tuple(goal_rows))


def _multiline_span(
    lines: tuple[str, ...], start: tuple[int, int], end: tuple[int, int], role: str
) -> tuple[TextSpan, ...]:
    spans: list[TextSpan] = []
    for row in range(max(0, start[0]), min(len(lines), end[0] + 1)):
        left = start[1] if row == start[0] else 0
        right = end[1] if row == end[0] else len(lines[row])
        left, right = min(left, len(lines[row])), min(right, len(lines[row]))
        if right > left:
            spans.append(TextSpan(row, left, right, role))
    return tuple(spans)


def _python_spans(lines: tuple[str, ...]) -> tuple[TextSpan, ...]:
    spans: list[TextSpan] = []
    roles = {
        token.STRING: "string",
        token.NUMBER: "number",
        token.COMMENT: "comment",
        token.OP: "operator",
    }
    source = io.StringIO("\n".join(lines) + "\n")
    line_starts = [0]
    for line in lines[:-1]:
        line_starts.append(line_starts[-1] + len(line) + 1)
    row_offset = 0
    while row_offset < len(lines):
        try:
            for item in tokenize.generate_tokens(source.readline):
                role = roles.get(item.type)
                if item.type == token.NAME and (
                    keyword.iskeyword(item.string) or keyword.issoftkeyword(item.string)
                ):
                    role = "keyword"
                if role is not None:
                    spans.extend(
                        _multiline_span(
                            lines,
                            (item.start[0] - 1 + row_offset, item.start[1]),
                            (item.end[0] - 1 + row_offset, item.end[1]),
                            role,
                        )
                    )
        except (IndentationError, SyntaxError) as error:
            # 발췌의 잘못된 dedent부터 새 블록으로 읽되 이후 여러 줄 문자열의
            # 문맥은 유지한다. 행마다 따로 읽으면 문자열 안의 코드가 색칠된다.
            row_offset += max(1, (error.lineno or 1) - 1)
            if row_offset < len(lines):
                source.seek(line_starts[row_offset])
        except tokenize.TokenError:
            # 입력 중인 불완전한 코드는 지금까지 읽은 토큰만 표시한다.
            break
        else:
            break
    return tuple(spans)


_CPP_KEYWORDS = frozenset(
    "alignas alignof asm auto bool break case catch char char8_t char16_t char32_t "
    "class concept const consteval constexpr constinit const_cast continue co_await "
    "co_return co_yield decltype default delete do double dynamic_cast else enum "
    "explicit export extern false float for friend goto if inline int long mutable "
    "namespace new noexcept nullptr operator private protected public register "
    "reinterpret_cast requires return short signed sizeof static static_assert "
    "static_cast struct switch template this thread_local throw true try typedef "
    "typeid typename union unsigned using virtual void volatile wchar_t while "
    "and and_eq bitand bitor compl not not_eq or or_eq xor xor_eq".split()
)
_CPP_TOKENS = re.compile(
    r"(?P<comment>//[^\n]*|/\*[\s\S]*?(?:\*/|\Z))"
    r'|(?P<string>(?:u8|u|U|L)?R"(?P<delimiter>[^\s()\\]{0,16})\([\s\S]*?\)'
    r'(?P=delimiter)"|(?:u8|u|U|L)?(?:"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'))'
    r"|(?P<preprocessor>^[ \t]*\#[^\n]*)"
    r"|(?P<number>\b(?:0x[0-9a-fA-F]+|\d+(?:\.\d*)?(?:[eE][+-]?\d+)?)[uUlLfF]*\b)"
    r"|(?P<name>\b[A-Za-z_]\w*\b)"
    r"|(?P<operator>[{}()[\];=:+*/<>!&|%\-]+)",
    re.MULTILINE,
)


def _cpp_spans(lines: tuple[str, ...]) -> tuple[TextSpan, ...]:
    text = "\n".join(lines)
    starts = [0]
    for line in lines[:-1]:
        starts.append(starts[-1] + len(line) + 1)
    spans: list[TextSpan] = []
    for match in _CPP_TOKENS.finditer(text):
        role = match.lastgroup
        if role == "name":
            role = "keyword" if match.group() in _CPP_KEYWORDS else None
        if role is None:
            continue
        first = bisect_right(starts, match.start()) - 1
        last = bisect_right(starts, match.end()) - 1
        spans.extend(
            _multiline_span(
                lines,
                (first, match.start() - starts[first]),
                (last, match.end() - starts[last]),
                role,
            )
        )
    return tuple(spans)


_JSON_TOKENS = re.compile(
    r'(?P<property>"(?:\\.|[^"\\])*")(?=\s*:)'
    r'|(?P<string>"(?:\\.|[^"\\])*(?:"|\\?$))'
    r"|(?P<keyword>\b(?:true|false|null)\b)"
    r"|(?P<number>(?<![\w.])-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?(?![\w.]))"
    r"|(?P<operator>[{}\[\]:,])"
)


def _json_spans(lines: tuple[str, ...]) -> tuple[TextSpan, ...]:
    """완전한 JSON을 요구하지 않고 편집 중인 행의 어휘만 구분한다."""
    spans: list[TextSpan] = []
    for row, line in enumerate(lines):
        for match in _JSON_TOKENS.finditer(line):
            role = match.lastgroup
            if role is not None:
                spans.append(TextSpan(row, match.start(), match.end(), role))
    return tuple(spans)


_FENCE_LANGUAGES: dict[str, DocumentLanguage] = {
    "py": "python",
    "python": "python",
    "cpp": "cpp",
    "c++": "cpp",
    "json": "json",
}


def _markdown_spans(lines: tuple[str, ...]) -> tuple[TextSpan, ...]:
    spans: list[TextSpan] = []
    fenced: DocumentLanguage | None = None
    code_start = 0
    for row, line in enumerate(lines):
        if line.lstrip().startswith("```"):
            if fenced is not None:
                for span in lexical_spans(lines[code_start:row], fenced):
                    spans.append(
                        TextSpan(span.row + code_start, span.start, span.end, span.role)
                    )
                fenced = None
            else:
                name = line.lstrip()[3:].strip().lower()
                fenced = _FENCE_LANGUAGES.get(name, "text")
                code_start = row + 1
            spans.append(TextSpan(row, 0, len(line), "comment"))
        elif fenced is None:
            if re.match(r"^\s{0,3}#{1,6}\s", line):
                spans.append(TextSpan(row, 0, len(line), "heading"))
            for match in re.finditer(r"`[^`]+`|\[[^\]]+\]\([^)]*\)", line):
                role = "string" if match.group().startswith("`") else "link"
                spans.append(TextSpan(row, match.start(), match.end(), role))
    if fenced is not None:
        for span in lexical_spans(lines[code_start:], fenced):
            spans.append(
                TextSpan(span.row + code_start, span.start, span.end, span.role)
            )
    return tuple(spans)


@lru_cache(maxsize=16)
def lexical_spans(
    lines: tuple[str, ...], language: DocumentLanguage
) -> tuple[TextSpan, ...]:
    """문자색만 반환한다. Python은 tokenize, C++·JSON은 어휘 강조를 제공한다.

    언어 범위는 diff 배경·밑줄과 독립적이다. 파서·컴파일러나 코드를 실행하지 않는다.
    """
    if language == "python":
        return _python_spans(lines)
    if language == "cpp":
        return _cpp_spans(lines)
    if language == "json":
        return _json_spans(lines)
    if language == "markdown":
        return _markdown_spans(lines)
    if language != "text":
        raise ValueError(f"지원하지 않는 표시 언어입니다: {language}")
    return ()
