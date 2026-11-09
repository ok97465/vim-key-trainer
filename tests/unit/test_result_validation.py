"""결과 코덱이 잘못된 버전·타입·완료 상태·통계를 거부하는지 검증한다."""

# Standard library imports
import json
from dataclasses import replace

# Third party imports
import pytest
from record_factories import command_result, editing_result, typing_result

# Local imports
from vim_key_trainer.domain.document_missions import DocumentPracticeSpec
from vim_key_trainer.domain.editing import EditPracticeSpec
from vim_key_trainer.services.result_codec import decode_result, encode_result
from vim_key_trainer.services.storage_version import STORAGE_VERSION


@pytest.mark.parametrize("change", ["unknown_field", "bad_number", "active_state"])
def test_invalid_result_json_is_rejected(change: str) -> None:
    payload = json.loads(encode_result(typing_result()))
    if change == "unknown_field":
        payload["data"]["executable"] = "never execute"
    elif change == "bad_number":
        payload["data"]["correct"] = "2"
    else:
        payload["data"]["state"] = "running"
    with pytest.raises(ValueError):
        decode_result(json.dumps(payload))


@pytest.mark.parametrize("field", ["spec", "target", "command_samples"])
def test_command_result_rejects_unknown_fields_in_nested_records(field: str) -> None:
    payload = json.loads(encode_result(command_result()))
    nested = payload["data"][field]
    if isinstance(nested, list):
        nested = nested[0]
    nested["unknown_setting"] = 1
    with pytest.raises(ValueError, match="알 수 없는 필드"):
        decode_result(json.dumps(payload))


@pytest.mark.parametrize("document", [False, True])
def test_edit_result_rejects_unknown_fields_in_generation_conditions(
    document: bool,
) -> None:
    result = editing_result()
    if document:
        result = replace(
            result,
            lesson_id="mission_test",
            document_spec=DocumentPracticeSpec("mission_test", 7),
        )
    else:
        result = replace(
            result,
            practice_spec=EditPracticeSpec(result.lesson_id, 7),
        )
    payload = json.loads(encode_result(result))
    field = "document_spec" if document else "practice_spec"
    payload["data"][field]["unknown_setting"] = 1
    with pytest.raises(ValueError, match="알 수 없는 필드"):
        decode_result(json.dumps(payload))


@pytest.mark.parametrize("version", [0, STORAGE_VERSION - 1, STORAGE_VERSION + 1])
def test_result_json_rejects_other_storage_versions(version: int) -> None:
    payload = json.loads(encode_result(typing_result()))
    payload["schema_version"] = version
    with pytest.raises(ValueError, match="버전"):
        decode_result(json.dumps(payload))


@pytest.mark.parametrize(
    ("field", "invalid"),
    [
        ("max_combo", -1),
        ("max_combo", 999),
        ("extra_hints", -1),
        ("step_returns", -1),
        ("accuracy", 0),
        ("accuracy", None),
    ],
)
def test_guided_result_rejects_inconsistent_counts_and_accuracy(
    field: str,
    invalid: object,
) -> None:
    payload = json.loads(encode_result(editing_result()))
    payload["data"][field] = invalid
    with pytest.raises(ValueError):
        decode_result(json.dumps(payload))


def test_accuracy_consistency_allows_only_roundoff_tolerance() -> None:
    payload = json.loads(encode_result(editing_result()))
    payload["data"]["accuracy"] -= 1e-10
    decoded = decode_result(json.dumps(payload))
    assert decoded.accuracy == pytest.approx(100)


@pytest.mark.parametrize(
    "changes",
    [
        {"target": "123"},
        {"correct": 1, "accuracy": 100, "max_combo": 1},
        {"correct": 3, "accuracy": 100, "max_combo": 3},
        {"incorrect": 1, "accuracy": 200 / 3},
        {"errors": {"1": 1}},
        {"keypad_errors": 1},
    ],
)
def test_symbol_result_rejects_inconsistent_target_and_error_counts(
    changes: dict[str, object],
) -> None:
    invalid = replace(typing_result(), **changes)
    with pytest.raises(ValueError):
        decode_result(encode_result(invalid))


def test_command_result_requires_a_completed_command_to_claim_completion() -> None:
    invalid = replace(command_result(), completed_commands=0)
    with pytest.raises(ValueError, match="완료 명령"):
        decode_result(encode_result(invalid))


def test_command_result_cannot_complete_more_commands_than_accepted_keys() -> None:
    invalid = replace(command_result(), completed_commands=3)
    with pytest.raises(ValueError, match="명령 완료 수"):
        decode_result(encode_result(invalid))


@pytest.mark.parametrize("free", [False, True])
def test_editing_result_cannot_claim_completion_without_input(free: bool) -> None:
    invalid = replace(
        editing_result(),
        key_count=0,
        mode="free" if free else "guided",
        correct=None if free else 0,
        incorrect=None if free else 0,
        accuracy=None,
        max_combo=None if free else 0,
    )
    with pytest.raises(ValueError, match="채점 입력"):
        decode_result(encode_result(invalid))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("cpm", -1),
        ("reaction_times", [["h", -0.1]]),
        ("commands_per_minute", -1),
        ("command_times", [["one", -0.1]]),
        ("command_samples", [{"item_id": "one", "display": "h", "seconds": -0.1}]),
    ],
)
def test_negative_speed_and_timing_samples_are_rejected(
    field: str, value: object
) -> None:
    payload = json.loads(encode_result(command_result()))
    payload["data"][field] = value
    with pytest.raises(ValueError, match="시간"):
        decode_result(json.dumps(payload))


def test_generated_edit_result_requires_matching_profile() -> None:
    result = replace(
        editing_result(),
        practice_spec=EditPracticeSpec("editing_numbers", 7),
    )
    invalid = replace(result, lesson_id="editing_words")
    with pytest.raises(ValueError, match="생성 조건"):
        decode_result(encode_result(invalid))
