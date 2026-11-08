"""Qt·저장 방식과 독립적인 결과 비교 조건과 개인 기록 우선순위."""

# Local imports
from vim_key_trainer.domain.sessions import (
    CommandSessionResult,
    EditingSessionResult,
    SessionState,
    StoredResult,
)

ComparisonKey = tuple[object, ...]


def comparison_key(result: StoredResult) -> ComparisonKey:
    if isinstance(result, EditingSessionResult):
        return (
            "editing",
            result.lesson_id,
            result.lesson_signature,
            result.baseline_keys,
            result.practice_spec,
            result.document_spec,
            result.mode,
            result.guide_level,
            result.extra_hints,
            result.step_returns,
            result.pause_count > 0,
            (
                result.challenge.options,
                result.challenge.time_rule_version,
                result.challenge.revenge_of,
                tuple(segment.segment_id for segment in result.challenge.segments),
            )
            if result.challenge is not None
            else None,
            result.activity,
        )
    if isinstance(result, CommandSessionResult):
        return (
            "commands",
            result.spec.lesson_id,
            result.spec.seed,
            result.lesson_signature,
            result.item_ids,
            result.display_count,
            result.target,
            result.completed_commands,
            result.transcript_digest,
            result.pause_count > 0,
        )
    spec = result.spec
    return (
        "symbols",
        spec.exercise_id,
        spec.seed,
        spec.target_length,
        spec.display_width,
        result.target,
        result.pause_count > 0,
    )


def is_better_result(candidate: StoredResult, previous: StoredResult) -> bool:
    """같은 비교 조건의 완료 결과를 입력 효율·정확도·시간 순으로 비교한다."""
    if (
        type(candidate) is not type(previous)
        or comparison_key(candidate) != comparison_key(previous)
        or not record_eligible(candidate)
    ):
        return False
    if isinstance(candidate, EditingSessionResult):
        assert isinstance(previous, EditingSessionResult)
        if candidate.challenge is not None:
            assert previous.challenge is not None
            if candidate.challenge.score != previous.challenge.score:
                return candidate.challenge.score > previous.challenge.score
            if candidate.elapsed_seconds != previous.elapsed_seconds:
                return _has_better_time(candidate, previous)
            return candidate.key_count < previous.key_count
        if candidate.mode != previous.mode:
            return False
        if candidate.mode == "free":
            if candidate.key_count != previous.key_count:
                return candidate.key_count < previous.key_count
            return _has_better_time(candidate, previous)
    assert candidate.correct is not None and candidate.incorrect is not None
    assert previous.correct is not None and previous.incorrect is not None
    # 완료 시도끼리 비교하므로 correct는 양수다. 반올림 전 정수 비율로 비교한다.
    candidate_ratio = candidate.correct * (previous.correct + previous.incorrect)
    previous_ratio = previous.correct * (candidate.correct + candidate.incorrect)
    if candidate_ratio != previous_ratio:
        return candidate_ratio > previous_ratio
    return _has_better_time(candidate, previous)


def record_eligible(result: StoredResult) -> bool:
    """부분 실패·자동 복구·복수전은 전체 완료 개인 기록을 갱신하지 않는다."""
    if isinstance(result, EditingSessionResult):
        return result.completion_eligible and result.efficiency_eligible
    return result.state == SessionState.COMPLETED


def _has_better_time(candidate: StoredResult, previous: StoredResult) -> bool:
    return candidate.elapsed_seconds > 0 and (
        previous.elapsed_seconds <= 0
        or candidate.elapsed_seconds < previous.elapsed_seconds
    )
