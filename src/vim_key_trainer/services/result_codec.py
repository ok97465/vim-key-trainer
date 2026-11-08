"""현재 저장 형식의 JSON을 검증해 학습 결과로 변환한다."""

# Standard library imports
import hashlib
import json
import math
import re
from collections.abc import Mapping
from dataclasses import fields, is_dataclass, replace
from types import MappingProxyType
from typing import Any, Literal, cast

# Third party imports
from pydantic import BaseModel, ConfigDict, StrictInt, TypeAdapter

# Local imports
from vim_key_trainer.domain.activities import evaluate_objectives
from vim_key_trainer.domain.challenge import TIME_RULE_VERSION, TIME_RULES
from vim_key_trainer.domain.game_rules import bomb_score
from vim_key_trainer.domain.sessions import (
    CommandSessionResult,
    EditingSessionResult,
    SessionResult,
    SessionState,
    StoredResult,
)
from vim_key_trainer.services.result_comparison import comparison_key
from vim_key_trainer.services.storage_version import STORAGE_VERSION

ResultKind = Literal["symbols", "commands", "editing"]


class _Envelope(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: StrictInt
    kind: ResultKind
    data: dict[str, Any]


_RESULT_TYPES = {
    "symbols": SessionResult,
    "commands": CommandSessionResult,
    "editing": EditingSessionResult,
}
_ADAPTERS: dict[str, TypeAdapter[Any]] = {
    kind: TypeAdapter(result_type) for kind, result_type in _RESULT_TYPES.items()
}


def result_kind(result: StoredResult) -> ResultKind:
    if isinstance(result, EditingSessionResult):
        return "editing"
    return "commands" if isinstance(result, CommandSessionResult) else "symbols"


def _json_value(value: object) -> object:
    if is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: _json_value(getattr(value, field.name))
            for field in fields(value)
        }
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise ValueError(f"JSON 결과에 저장할 수 없는 값입니다: {type(value).__name__}")


def _dumps(value: object) -> str:
    return json.dumps(
        _json_value(value),
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def encode_result(result: StoredResult) -> str:
    return _dumps(
        {
            "schema_version": STORAGE_VERSION,
            "kind": result_kind(result),
            "data": result,
        }
    )


def _reject_unknown_fields(data: object, value: object) -> None:
    """Pydantic이 버리는 추가 필드도 중첩 결과 구조 전체에서 거부한다."""
    if isinstance(data, dict) and is_dataclass(value) and not isinstance(value, type):
        unknown = set(data) - {field.name for field in fields(value)}
        if unknown:
            raise ValueError("저장된 결과에 알 수 없는 필드가 있습니다.")
        for name, item in data.items():
            _reject_unknown_fields(item, getattr(value, name))
    elif isinstance(data, list) and isinstance(value, (tuple, list)):
        for item, parsed in zip(data, value, strict=True):
            _reject_unknown_fields(item, parsed)


def _validate_accuracy(
    correct: int, incorrect: int, accuracy: float | None, max_combo: int
) -> None:
    if correct < 0 or incorrect < 0 or not 0 <= max_combo <= correct:
        raise ValueError("저장된 입력 수와 콤보가 올바르지 않습니다.")
    total = correct + incorrect
    if not total:
        if accuracy is not None:
            raise ValueError("채점 입력이 없는 결과의 정확도는 미측정이어야 합니다.")
        return
    expected = 100 * correct / total
    if (
        accuracy is None
        or not math.isfinite(accuracy)
        or not math.isclose(accuracy, expected, rel_tol=1e-12, abs_tol=1e-9)
    ):
        raise ValueError("저장된 정확도가 정답·오답 입력 수와 다릅니다.")


def _validate_editing_statistics(result: EditingSessionResult) -> None:
    if (
        result.key_count < 0
        or result.baseline_keys < 1
        or result.extra_hints < 0
        or result.step_returns < 0
    ):
        raise ValueError("편집 입력·보조 사용 횟수가 올바르지 않습니다.")
    if (
        result.practice_spec is not None
        and result.practice_spec.profile_id != result.lesson_id
    ):
        raise ValueError("편집 생성 조건이 결과의 레슨과 다릅니다.")
    if result.document_spec is not None and (
        result.document_spec.mission_id != result.lesson_id
        or result.practice_spec is not None
    ):
        raise ValueError("문서 손상 생성 조건이 결과의 미션과 다릅니다.")
    if result.code_source_id is not None and (
        re.fullmatch(r"[a-z][a-z0-9_]*", result.code_source_id) is None
        or result.lesson_id not in {"code_python", "code_cpp"}
        or result.practice_spec is None
    ):
        raise ValueError("완료한 코드 원문의 ID·연습 유형이 올바르지 않습니다.")
    if (
        result.practice_spec is not None
        and result.practice_spec.code_source_id is not None
        and result.practice_spec.code_source_id != result.code_source_id
    ):
        raise ValueError("완료한 코드 원문이 시작 시 선택한 원문과 다릅니다.")
    if result.state == SessionState.COMPLETED and result.key_count == 0:
        raise ValueError("완료한 편집 결과에는 채점 입력이 필요합니다.")
    if result.mode == "free":
        if any(
            value is not None
            for value in (
                result.correct,
                result.incorrect,
                result.accuracy,
                result.max_combo,
            )
        ):
            raise ValueError("자유 풀이에는 가이드 정확도·콤보를 저장할 수 없습니다.")
        return
    if (
        result.correct is None
        or result.incorrect is None
        or result.max_combo is None
        or result.correct + result.incorrect != result.key_count
        or (
            result.state == SessionState.COMPLETED
            and result.correct == 0
            and (result.challenge is None or not result.challenge.timeout_count)
        )
    ):
        raise ValueError("가이드 입력 통계가 누적 입력 수와 다릅니다.")
    _validate_accuracy(
        result.correct, result.incorrect, result.accuracy, result.max_combo
    )


def _validate_challenge(result: EditingSessionResult) -> None:
    challenge = result.challenge
    if challenge is None:
        return
    if (
        challenge.options.kind != "bomb"
        or challenge.time_rule_version != TIME_RULE_VERSION
        or not challenge.segments
        or len(challenge.segments) > 1000
        or (
            challenge.revenge_of is not None
            and challenge.revenge_of != result.lesson_signature
        )
    ):
        raise ValueError("폭탄 도전의 종류·시간 규칙·구간 조건이 올바르지 않습니다.")
    if result.mode == "free" and (
        len(challenge.segments) != 1
        or challenge.segments[0].segment_id != "document"
        or challenge.auto_repair_count
        or challenge.revenge_of is not None
    ):
        raise ValueError(
            "자유 풀이 폭탄 도전은 자동 복구·복수전 없이 문서 전체를 잽니다."
        )
    maximum_ms = (
        TIME_RULES.free_maximum_ms if result.mode == "free" else TIME_RULES.maximum_ms
    )
    seen: set[str] = set()
    pending = False
    chain = 0
    max_chain = 0
    for segment in challenge.segments:
        if (
            not segment.segment_id
            or segment.segment_id in seen
            or not math.isfinite(segment.limit_seconds)
            or not (
                TIME_RULES.minimum_ms / 1000
                <= segment.limit_seconds
                <= maximum_ms / 1000
            )
            or not math.isclose(
                segment.limit_seconds * 1000 / TIME_RULES.rounding_ms,
                round(segment.limit_seconds * 1000 / TIME_RULES.rounding_ms),
                rel_tol=0,
                abs_tol=1e-9,
            )
            or not math.isfinite(segment.elapsed_seconds)
            or segment.elapsed_seconds < 0
            or segment.elapsed_seconds > segment.limit_seconds
            or (segment.auto_repaired and segment.verdict != "timeout")
            or (segment.auto_repaired and not challenge.options.auto_repair)
        ):
            raise ValueError("폭탄 구간의 ID·시간·자동 복구 판정이 올바르지 않습니다.")
        seen.add(segment.segment_id)
        if segment.verdict == "pending":
            if pending and segment.elapsed_seconds != 0:
                raise ValueError("아직 활성화되지 않은 구간에 활성 시간이 있습니다.")
            pending = True
        elif pending:
            raise ValueError("대기 중인 폭탄 구간 뒤에 정산된 구간이 있습니다.")
        if segment.verdict == "timeout":
            if not math.isclose(
                segment.elapsed_seconds, segment.limit_seconds, abs_tol=1e-9
            ):
                raise ValueError("시간 초과 구간의 활성 시간이 제한시간과 다릅니다.")
            chain = 0
        elif segment.verdict == "direct":
            if segment.elapsed_seconds >= segment.limit_seconds:
                raise ValueError("직접 해결한 구간이 제한시간에 도달했습니다.")
            chain += 1
            max_chain = max(max_chain, chain)
        elif segment.elapsed_seconds >= segment.limit_seconds:
            raise ValueError("대기 중인 구간이 제한시간에 도달했습니다.")
    completed = result.state == SessionState.COMPLETED
    full_clear = completed and challenge.direct_count == challenge.segment_count
    if (
        (completed and pending)
        or challenge.full_clear != full_clear
        or challenge.max_chain != max_chain
        or sum(segment.elapsed_seconds for segment in challenge.segments)
        > result.elapsed_seconds + 1e-8
        or challenge.score
        != bomb_score(
            segments=challenge.segments,
            extra_hints=result.extra_hints,
            step_returns=result.step_returns,
        )
        or (not result.completion_eligible and result.stars != 0)
    ):
        raise ValueError("폭탄 도전의 완료·점수·시간·연속 해체 합계가 다릅니다.")


def _validate_activity(result: EditingSessionResult) -> None:
    activity = result.activity
    if activity is None:
        if result.bonus_objectives:
            raise ValueError("선택 목표는 시작 시 확정한 미션 조건이 필요합니다.")
        return
    if activity.kind == "daily":
        spec = result.practice_spec
        if (
            spec is None
            or result.lesson_id != activity.profile_id
            or spec.profile_id != activity.profile_id
            or spec.seed != activity.seed
            or spec.document_lines != activity.document_lines
            or spec.technique_weights is not None
            or spec.code_source_id is not None
            or result.document_spec is not None
        ):
            raise ValueError("오늘의 미션 조건이 원래 문제와 다릅니다.")
    elif (
        result.lesson_id != "boss_observatory"
        or result.practice_spec is not None
        or result.document_spec is not None
    ):
        raise ValueError("보스 미션 조건이 원래 문제와 다릅니다.")
    expected = evaluate_objectives(
        activity.objectives,
        eligible=result.completion_eligible,
        extra_hints=result.extra_hints,
        key_count=result.key_count,
        baseline_keys=result.baseline_keys,
        efficiency_eligible=result.efficiency_eligible,
        all_direct=result.challenge is not None and result.challenge.full_clear,
    )
    if result.bonus_objectives != expected:
        raise ValueError("선택 목표의 판정이 완료 상태·입력 조건과 다릅니다.")


def _validate_typing_statistics(result: SessionResult | CommandSessionResult) -> None:
    _validate_accuracy(
        result.correct, result.incorrect, result.accuracy, result.max_combo
    )
    if result.keypad_errors < 0 or any(count < 0 for count in result.errors.values()):
        raise ValueError("타이핑 오류 통계가 올바르지 않습니다.")
    if sum(result.errors.values()) + result.keypad_errors != result.incorrect:
        raise ValueError("타이핑 오류 통계가 오답 입력 수와 다릅니다.")
    speeds = [result.cpm]
    durations = [seconds for _, seconds in result.reaction_times]
    if isinstance(result, CommandSessionResult):
        speeds.append(result.commands_per_minute)
        durations.extend(seconds for _, seconds in result.command_times)
        durations.extend(sample.seconds for sample in result.command_samples)
    if any(not math.isfinite(seconds) or seconds < 0 for seconds in durations) or any(
        speed is not None and (not math.isfinite(speed) or speed < 0)
        for speed in speeds
    ):
        raise ValueError("저장된 속도·반응 시간·명령 시간이 올바르지 않습니다.")
    if isinstance(result, CommandSessionResult):
        if (
            not 0 <= result.completed_commands <= result.correct
            or result.display_count < 1
        ):
            raise ValueError("명령 완료 수·표시량이 올바르지 않습니다.")
        if result.state == SessionState.COMPLETED and not result.completed_commands:
            raise ValueError("완료한 명령 결과에는 완료 명령이 필요합니다.")
    elif (
        len(result.target) != result.spec.target_length
        or result.correct > len(result.target)
        or (
            result.state == SessionState.COMPLETED
            and result.correct != len(result.target)
        )
    ):
        raise ValueError("숫자·기호 정답 입력 수가 목표 길이와 다릅니다.")


def decode_result(payload: str) -> StoredResult:
    if len(payload) > 4_000_000:
        raise ValueError("저장된 결과가 허용 크기를 초과했습니다.")
    envelope = _Envelope.model_validate_json(payload)
    if envelope.schema_version != STORAGE_VERSION:
        raise ValueError("지원하지 않는 결과 JSON 스키마 버전입니다.")
    result = cast(
        StoredResult,
        _ADAPTERS[envelope.kind].validate_json(_dumps(envelope.data), strict=True),
    )
    _reject_unknown_fields(envelope.data, result)
    if (
        not result.attempt_id
        or result.state not in {SessionState.COMPLETED, SessionState.ABORTED}
        or not math.isfinite(result.elapsed_seconds)
        or result.elapsed_seconds < 0
        or not 0 <= result.stars <= 3
        or result.pause_count < 0
        or (result.state == SessionState.ABORTED and result.stars != 0)
    ):
        raise ValueError("저장된 결과의 상태·시간·별·시도 ID가 올바르지 않습니다.")
    if isinstance(result, EditingSessionResult):
        _validate_editing_statistics(result)
        _validate_challenge(result)
        _validate_activity(result)
    else:
        _validate_typing_statistics(result)
        result = replace(result, errors=MappingProxyType(dict(result.errors)))
    return result


def comparison_digest(result: StoredResult) -> str:
    return hashlib.sha256(_dumps(comparison_key(result)).encode("utf-8")).hexdigest()
