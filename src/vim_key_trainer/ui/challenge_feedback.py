"""이미 확정된 구간 결과를 소리·그림으로 표현하기 위한 읽기 전용 분류."""

# Standard library imports
import re

# Local imports
from vim_key_trainer.domain.challenge import SegmentResult
from vim_key_trainer.services.edit_session import EditingSession


def chain_level(chain: int) -> int:
    """기존 연속 해체 수의 연출 단계. 점수 배수나 새 보상은 만들지 않는다."""
    return sum(chain >= threshold for threshold in (3, 5, 10))


def is_close_call(result: SegmentResult) -> bool:
    return (
        result.verdict == "direct"
        and 0
        <= result.limit_seconds - result.elapsed_seconds
        <= min(3.0, result.limit_seconds * 0.15)
    )


def segment_technique(session: EditingSession, segment_id: str) -> str:
    """검증된 가이드의 첫 문서 변경으로 음색을 고른다. Vim 명령 판정과 무관하다."""
    segment = next((item for item in session.segments if item.id == segment_id), None)
    if segment is None:
        return "precise"
    guide = session.lesson.guide
    before = (
        session.lesson.initial.lines
        if segment.start_step == 0
        else guide[segment.start_step - 1].expected.lines
    )
    for step in guide[segment.start_step : segment.end_step]:
        after = step.expected.lines
        if before == after:
            continue
        if len(after) != len(before):
            return "delete" if len(after) < len(before) else "insert"
        if any(
            token.kind == "chord" and token.value in {"ctrl+a", "ctrl+x"}
            for token in step.keys
        ):
            return "number"
        for old, new in zip(before, after, strict=True):
            if old == new:
                continue
            start = 0
            while start < min(len(old), len(new)) and old[start] == new[start]:
                start += 1
            end = 0
            while (
                end < min(len(old), len(new)) - start
                and old[len(old) - end - 1] == new[len(new) - end - 1]
            ):
                end += 1
            removed = old[start : len(old) - end if end else len(old)]
            inserted = new[start : len(new) - end if end else len(new)]
            if (
                removed
                and inserted
                and all(
                    re.fullmatch(r"[-+0-9a-fA-FxXbBoO.]+", value)
                    and any(char.isdigit() for char in value)
                    for value in (removed, inserted)
                )
            ):
                return "number"
            if not inserted:
                return "delete"
            if not removed:
                return "insert"
            return "word" if max(len(removed), len(inserted)) > 1 else "precise"
    return "precise"
