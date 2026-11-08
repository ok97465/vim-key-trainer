"""저장된 문제 조건으로 복습을 재구성한다. 실패 당시 문서·원시 키는 필요 없다."""

# Standard library imports
from collections.abc import Callable
from time import perf_counter_ns

# Local imports
from vim_key_trainer.content.edit_loader import get_edit_lesson
from vim_key_trainer.domain.editing import EditLesson
from vim_key_trainer.domain.sessions import EditingSessionResult
from vim_key_trainer.services.activity_problem_factory import create_activity_problem
from vim_key_trainer.services.document_problem_factory import (
    create_random_document_problem,
)
from vim_key_trainer.services.edit_problem_factory import create_edit_problem
from vim_key_trainer.services.edit_session import EditingSession
from vim_key_trainer.services.result_codec import decode_result, encode_result


def reconstruct_recorded_lesson(result: EditingSessionResult) -> EditLesson:
    """현재 규칙으로 재생성한 문제의 서명까지 같은 기록만 복습한다."""
    validated = decode_result(encode_result(result))
    if not isinstance(validated, EditingSessionResult):
        raise ValueError("편집 연습 기록이 필요합니다.")
    if validated.activity is not None:
        lesson = create_activity_problem(validated.activity)
    elif validated.practice_spec is not None:
        lesson = create_edit_problem(validated.practice_spec)
    elif validated.document_spec is not None:
        lesson = create_random_document_problem(validated.document_spec)
    else:
        lesson = get_edit_lesson(validated.lesson_id)
    if (
        lesson.id != validated.lesson_id
        or lesson.signature != validated.lesson_signature
        or validated.code_source_id
        != (lesson.code_excerpt.source.id if lesson.code_excerpt is not None else None)
    ):
        raise ValueError("저장된 문제 서명·원문이 현재 재구성한 문제와 다릅니다.")
    return lesson


def create_recorded_revenge(
    result: EditingSessionResult,
    *,
    clock_ns: Callable[[], int] = perf_counter_ns,
) -> EditingSession:
    """실패 구간의 선행 조건을 검증한 새 시도를 만들며 원래 기록은 보존한다."""
    challenge = result.challenge
    if result.mode != "guided" or challenge is None or not challenge.timeout_count:
        raise ValueError("시간 초과가 있는 가이드 폭탄 기록을 선택하세요.")
    lesson = reconstruct_recorded_lesson(result)
    failed = tuple(
        segment.segment_id
        for segment in challenge.segments
        if segment.verdict == "timeout"
    )
    return EditingSession(
        lesson,
        result.mode,
        clock_ns=clock_ns,
        challenge=challenge.options,
        revenge_segments=failed,
    )
