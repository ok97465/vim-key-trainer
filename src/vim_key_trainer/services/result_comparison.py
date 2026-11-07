"""Qt·저장 방식과 독립적인 결과 비교 조건과 개인 기록 우선순위."""

# Local imports
from vim_key_trainer.domain.sessions import (
    CommandSessionResult,
    EditingSessionResult,
    StoredResult,
)

ComparisonKey = tuple[object, ...]


def comparison_key(result: StoredResult) -> ComparisonKey:
    if isinstance(result, EditingSessionResult):
        key: ComparisonKey = (
            "editing",
            result.lesson_id,
            result.content_version,
            result.lesson_signature,
            result.baseline_version,
            result.baseline_keys,
            result.practice_spec,
            result.generator_version,
            result.mode,
            result.guide_level,
            result.extra_hints,
            result.step_returns,
            result.pause_count > 0,
            result.game_rules_version,
        )
        # 구형 결과의 비교 해시는 보존하고 새 생성 조건만 별도로 확장한다.
        if result.document_spec is not None:
            key += (("document", result.document_spec),)
        return key
    if isinstance(result, CommandSessionResult):
        return (
            "commands",
            result.spec.lesson_id,
            result.spec.seed,
            result.lesson_version,
            result.lesson_signature,
            result.item_ids,
            result.display_count,
            result.target,
            result.generator_version,
            result.completed_commands,
            result.transcript_digest,
            result.pause_count > 0,
            result.game_rules_version,
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
        result.game_rules_version,
    )


def is_better_result(candidate: StoredResult, previous: StoredResult) -> bool:
    """같은 비교 조건의 완료 결과를 입력 효율·정확도·시간 순으로 비교한다."""
    if type(candidate) is not type(previous):
        return False
    if isinstance(candidate, EditingSessionResult):
        assert isinstance(previous, EditingSessionResult)
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


def _has_better_time(candidate: StoredResult, previous: StoredResult) -> bool:
    return candidate.elapsed_seconds > 0 and (
        previous.elapsed_seconds <= 0
        or candidate.elapsed_seconds < previous.elapsed_seconds
    )
