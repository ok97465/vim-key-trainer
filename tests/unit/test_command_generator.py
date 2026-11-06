"""고정 예제 순열이 아닌 명령 문법 생성·문맥·재현성 검증."""

# Standard library imports
import hashlib
import json
import re
from collections import Counter
from dataclasses import replace

# Third party imports
import pytest

# Local imports
from vim_key_trainer.domain.command_generator import (
    COMMAND_PROFILES,
    MAX_COMBINED_COUNT,
    MAX_COUNT,
    MOTIONS,
    OPERATORS,
    TEXT_OBJECTS,
    CommandFamily,
    CommandGenerator,
    CommandProfile,
    get_command_profile,
    list_command_profiles,
)
from vim_key_trainer.domain.commands import CommandItem
from vim_key_trainer.domain.keys import KeyToken


def profile_for(family: CommandFamily) -> CommandProfile:
    return replace(COMMAND_PROFILES[0], families=(family,))


def test_seed_reproduces_stream_and_new_seed_changes_generated_content() -> None:
    first = CommandGenerator(COMMAND_PROFILES[0], seed=42)
    same = CommandGenerator(COMMAND_PROFILES[0], seed=42)
    different = CommandGenerator(COMMAND_PROFILES[0], seed=43)
    sequence = [first.next_item() for _ in range(200)]
    assert sequence == [same.next_item() for _ in range(200)]
    assert [item.tokens for item in sequence] != [
        different.next_item().tokens for _ in range(200)
    ]
    assert len({item.id for item in sequence}) > 100
    assert all(item.execution_support == "typing_only" for item in sequence)
    assert all(item.start_mode == "Normal" and item.meaning for item in sequence)


def test_mixed_profile_covers_requested_commands_and_thousands_of_combinations() -> (
    None
):
    generator = CommandGenerator(COMMAND_PROFILES[0], seed=23)
    items = [generator.next_item() for _ in range(10_000)]
    displays = Counter(item.display for item in items)
    assert len(displays) > 2_000
    assert all(displays[command] >= 2 for command in ("ciw", "cw", "dW", "zz"))
    assert any("×" in item.meaning for item in items)
    assert any("레지스터" in item.meaning for item in items)
    assert any("순서대로" in item.meaning for item in items)
    assert all(
        first.tokens != second.tokens
        for first, second in zip(items, items[1:], strict=False)
    )


@pytest.mark.parametrize("profile", COMMAND_PROFILES, ids=lambda profile: profile.id)
def test_profile_generation_remains_varied_after_many_display_windows(
    profile: CommandProfile,
) -> None:
    generator = CommandGenerator(profile, seed=177)
    first_window = [generator.next_item().tokens for _ in range(10)]
    later = [generator.next_item().tokens for _ in range(2_000)]
    assert len(set(later)) > 100
    assert set(later) - set(first_window)
    assert all(left != right for left, right in zip(later, later[1:], strict=False))
    assert len(generator._recent) <= 2
    assert len(generator._family_bag) <= len(profile.families)


def test_count_operator_motion_grammar_preserves_multiplication_and_zero_rules() -> (
    None
):
    generator = CommandGenerator(profile_for("operator_motion"), seed=21)
    operators = "|".join(re.escape(operator.keys) for operator in OPERATORS)
    motions = "|".join(re.escape(motion.keys) for motion in MOTIONS)
    pattern = re.compile(
        rf'^(?:"[abcxyz+])?([1-9][0-9]?)?({operators})([1-9][0-9]?)?({motions})$'
    )
    for _ in range(3_000):
        item = generator.next_item()
        matched = pattern.fullmatch(item.display)
        assert matched is not None, item.display
        first, operator, second, motion = matched.groups()
        count = int(first or "1") * int(second or "1")
        assert int(first or "1") <= MAX_COUNT
        assert int(second or "1") <= MAX_COUNT
        assert count <= MAX_COMBINED_COUNT
        if motion in {"0", "^"}:
            assert first is second is None
        if operator == "c":
            assert "Insert" in item.follow_up
        if operator == "c" and motion in {"w", "W"}:
            assert "공백을 포함하지" in item.meaning


def test_text_objects_require_an_operator_and_quote_counts_are_restricted() -> None:
    generator = CommandGenerator(profile_for("operator_object"), seed=19)
    operators = "|".join(re.escape(operator.keys) for operator in OPERATORS)
    objects = "|".join(re.escape(target.keys) for target in TEXT_OBJECTS)
    pattern = re.compile(
        rf'^(?:"[abcxyz+])?([1-9][0-9]?)?({operators})([1-9][0-9]?)?({objects})$'
    )
    seen = set()
    for _ in range(3_000):
        item = generator.next_item()
        matched = pattern.fullmatch(item.display)
        assert matched is not None, item.display
        first, _, second, target = matched.groups()
        seen.add(target)
        count = int(first or "1") * int(second or "1")
        if target[-1] in "\"'`":
            assert first is second is None
            assert "같은 줄" in item.meaning
        elif target[-1] in "([{<":
            assert count <= 3
        if target in {"iw", "iW"}:
            assert "사이 공백도" in item.meaning
    assert {"iw", "iW", "aw", "aW", "i(", "a[", 'i"', "a'"} <= seen


def test_insertions_use_real_special_tokens_and_ascii_payloads() -> None:
    generator = CommandGenerator(profile_for("insert"), seed=7)
    special = set()
    entries = set()
    for _ in range(200):
        item = generator.next_item()
        entries.add(item.tokens[0].value)
        assert item.tokens[-1] == KeyToken("special", "esc")
        assert all(token.kind != "chord" for token in item.tokens)
        special.update(token.value for token in item.tokens if token.kind == "special")
        assert all(
            len(token.value) == 1 and token.value.isascii()
            for token in item.tokens
            if token.kind == "char"
        )
    assert entries == set("iaIAoO")
    assert special == {"esc", "enter", "backspace"}
    history = CommandGenerator(profile_for("history"), seed=4)
    assert any(
        KeyToken("chord", "ctrl+r") in history.next_item().tokens for _ in range(20)
    )


def test_simple_edits_keep_character_replacement_and_insert_fragments_distinct() -> (
    None
):
    generator = CommandGenerator(profile_for("simple_edit"), seed=17)
    seen = set()
    for _ in range(300):
        item = generator.next_item()
        matched = re.fullmatch(
            r"([1-9][0-9]?)?([xXDCsSpPr])([abcxyz012_!#])?", item.display
        )
        assert matched is not None, item.display
        count, command, character = matched.groups()
        seen.add(command)
        assert int(count or "1") <= MAX_COUNT
        assert (character is not None) == (command == "r")
        if command in {"C", "s", "S"}:
            assert "Insert" in item.follow_up
        elif command in {"p", "P"}:
            assert "레지스터 내용" in item.follow_up
    assert seen == set("xXDCsSpPr")


def test_screen_and_incomplete_context_keep_their_own_semantics() -> None:
    screen = CommandGenerator(profile_for("screen"), seed=11)
    items = [screen.next_item() for _ in range(30)]
    assert {item.display for item in items} == {"zz", "zt", "zb"}
    assert all("커서 열" in item.meaning for item in items)
    context = CommandGenerator(profile_for("context"), seed=11)
    items = [context.next_item() for _ in range(200)]
    assert {item.display for item in items} >= {"qa", '"+y'}
    for item in items:
        assert "매크로" in item.follow_up or "더 필요" in item.follow_up
        assert "이 앱" in item.follow_up or "앱은" in item.follow_up


@pytest.mark.parametrize("family", COMMAND_PROFILES[0].families)
def test_rejection_backoff_reuses_grammar_without_advancing_seeded_random(
    family: CommandFamily,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    generator = CommandGenerator(profile_for(family), seed=2)
    first = generator.next_item()
    random_state = generator._random.getstate()
    attempts = 0

    def repeated(family: CommandFamily) -> CommandItem:
        nonlocal attempts
        attempts += 1
        return first

    monkeypatch.setattr(generator, "_generate", repeated)
    second = generator.next_item()
    assert second.tokens != first.tokens
    assert attempts == 24
    assert generator._random.getstate() == random_state
    # 재추첨 실패 후에도 정상 생성 명령처럼 명시적인 문맥·짧은 요약을 제공한다.
    assert second.short_meaning
    assert second.start_mode == "Normal"
    assert second.execution_support == "typing_only"


@pytest.mark.parametrize(("keys", "word"), (("b", "단어"), ("B", "WORD")))
def test_backward_word_summary_allows_the_start_of_the_current_word(
    keys: str,
    word: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # b/B는 단어 중간에서 현재 단어의 시작으로 간다. 이전 단어로 단정하지 않는다.
    # https://github.com/vim/vim/blob/master/runtime/doc/motion.txt#L378
    generator = CommandGenerator(profile_for("movement"), seed=1)
    motion = next(motion for motion in MOTIONS if motion.keys == keys)
    monkeypatch.setattr(generator._random, "choice", lambda choices: motion)
    monkeypatch.setattr(generator, "_count", lambda: 1)
    item = generator.next_item()
    assert item.display == keys
    assert item.brief_meaning == f"{word} 시작으로 뒤로 이동"


def test_profile_lookup_and_invalid_metadata_fail_at_the_boundary() -> None:
    assert list_command_profiles() == COMMAND_PROFILES
    assert get_command_profile("commands_random") is COMMAND_PROFILES[0]
    with pytest.raises(ValueError):
        get_command_profile("missing")
    with pytest.raises(ValueError):
        CommandGenerator(COMMAND_PROFILES[0], seed=-1)
    for values in ({"families": ()}, {"display_count": 7}, {"content_version": 0}):
        with pytest.raises(ValueError):
            replace(COMMAND_PROFILES[0], **values)


def test_clipboard_delete_summary_uses_selected_scope_and_register(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    generator = CommandGenerator(profile_for("operator_motion"), seed=1)
    selections = iter(
        (OPERATORS[0], next(motion for motion in MOTIONS if motion.keys == "0"))
    )
    monkeypatch.setattr(
        generator._random, "choices", lambda *args, **kwargs: [next(selections)]
    )
    monkeypatch.setattr(generator._random, "random", lambda: 0.99)
    monkeypatch.setattr(generator._random, "choice", lambda values: "+")
    item = generator._operator_motion()
    assert item.display == '"+d0'
    assert item.brief_meaning == "줄 맨 앞까지 삭제 → 클립보드 보관"
    assert "입력 모드" not in item.brief_meaning


def test_counted_summary_preserves_effective_count_and_change_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    generator = CommandGenerator(profile_for("operator_object"), seed=1)
    selections = iter((OPERATORS[1], TEXT_OBJECTS[0]))
    monkeypatch.setattr(
        generator._random, "choices", lambda *args, **kwargs: [next(selections)]
    )
    monkeypatch.setattr(generator, "_counts", lambda *args, **kwargs: (2, 3))
    monkeypatch.setattr(generator, "_register", lambda operator: ("", "", ""))
    item = generator._operator_object()
    assert item.display == "2c3iw"
    assert item.brief_meaning == "현재 단어 6단위 변경 → 입력 모드"
    assert "6개" not in item.brief_meaning  # iw는 단어 사이 공백도 센다.


def test_short_summaries_distinguish_word_scope_and_screen_position() -> None:
    generator = CommandGenerator(COMMAND_PROFILES[0], seed=23)
    expected = {
        "ciw": "현재 단어 변경 → 입력 모드",
        "cw": "커서부터 단어 끝 변경 → 입력 모드",
        "dW": "다음 WORD 앞까지 삭제",
        "zz": "커서 줄을 화면 가운데로",
    }
    found = {}
    for _ in range(10_000):
        item = generator.next_item()
        assert item.brief_meaning.strip()
        if item.display in expected:
            found[item.display] = item.brief_meaning
        if len(found) == len(expected):
            break
    assert found == expected


def test_incomplete_context_summary_does_not_claim_the_operation_is_finished() -> None:
    generator = CommandGenerator(profile_for("context"), seed=11)
    items = [generator.next_item() for _ in range(200)]
    for item in items:
        if item.display.startswith("q"):
            assert (
                "기록 시작" in item.brief_meaning and "q로 종료" in item.brief_meaning
            )
        else:
            assert (
                "복사 시작" in item.brief_meaning
                and "범위 입력 필요" in item.brief_meaning
            )
            assert ("클립보드" in item.brief_meaning) == (item.display[1] == "+")


@pytest.mark.parametrize(
    ("profile_id", "version", "digest"),
    (
        (
            "commands_random",
            1,
            "0b94218bbaca1b61386c13bb0713bb296eb73ed1f2727cd81c0db3d209dadc38",
        ),
        (
            "commands_movement_random",
            1,
            "ed987d4b116f5d65b7f4f996a308e4f112480ad0f2188b4a260b3808d2eb514a",
        ),
        (
            "commands_operators_random",
            2,
            "6d87d4f3669559682c922b920def39ec7b4f64fda3f396df5a590327b9d8b968",
        ),
        (
            "commands_objects_random",
            1,
            "6f76d2566c5f05fb6d8552d07769320175d1af25bd0a353c59827410a1303085",
        ),
        (
            "commands_insert_random",
            2,
            "fa1ab90df7f4e9a5bace2dbbeeeaf553796083278d6f83c7bacbd37152669ae2",
        ),
        (
            "commands_context_random",
            1,
            "7e5d39a73951d44b1014fd2818de3d0fca43ec5521b8cc7abe27dce9e14ae490",
        ),
    ),
)
def test_profile_version_pins_seeded_token_stream(
    profile_id: str,
    version: int,
    digest: str,
) -> None:
    profile = get_command_profile(profile_id)
    assert profile.content_version == version
    generator = CommandGenerator(profile, seed=42)
    tokens = [
        [(token.kind, token.value) for token in generator.next_item().tokens]
        for _ in range(200)
    ]
    actual = hashlib.sha256(
        json.dumps(tokens, separators=(",", ":")).encode()
    ).hexdigest()
    assert actual == digest


def test_focused_insert_profile_practices_only_complete_insert_sequences() -> None:
    generator = CommandGenerator(get_command_profile("commands_insert_random"), seed=13)
    items = [generator.next_item() for _ in range(300)]
    assert {item.tokens[0].value for item in items} == set("iaIAoO")
    assert all(item.tokens[-1] == KeyToken("special", "esc") for item in items)
    special_keys = {
        token.value
        for item in items
        for token in item.tokens
        if token.kind == "special"
    }
    assert special_keys == {"esc", "enter", "backspace"}
    assert all(token.kind != "chord" for item in items for token in item.tokens)


def test_focused_object_profile_always_pairs_an_operator_with_a_text_object() -> None:
    generator = CommandGenerator(
        get_command_profile("commands_objects_random"), seed=31
    )
    operators = "|".join(re.escape(operator.keys) for operator in OPERATORS)
    objects = "|".join(re.escape(target.keys) for target in TEXT_OBJECTS)
    pattern = re.compile(
        rf'^(?:"[abcxyz+])?(?:[1-9][0-9]?)?(?:{operators})'
        rf"(?:[1-9][0-9]?)?({objects})$"
    )
    seen = set()
    for _ in range(300):
        item = generator.next_item()
        matched = pattern.fullmatch(item.display)
        assert matched is not None, item.display
        seen.add(matched.group(1))
    assert {"iw", "aw", "i(", 'i"'} <= seen


def test_context_profile_keeps_history_fragments_and_composed_sequences() -> None:
    generator = CommandGenerator(
        get_command_profile("commands_context_random"), seed=53
    )
    items = [generator.next_item() for _ in range(120)]
    assert any(KeyToken("chord", "ctrl+r") in item.tokens for item in items)
    assert any(item.display.startswith("q") for item in items)
    assert any(
        item.display.startswith('"') and item.display.endswith("y") for item in items
    )
    assert any("순서대로" in item.meaning for item in items)


def test_legacy_item_uses_first_sentence_and_rejects_blank_short_meaning() -> None:
    item = CommandItem(
        "legacy",
        (KeyToken("char", "h"),),
        "왼쪽으로 이동합니다. 후속 설명입니다.",
        "Normal",
        "",
    )
    assert item.brief_meaning == "왼쪽으로 이동합니다"
    assert (
        replace(item, short_meaning="왼쪽 한 칸 이동").brief_meaning
        == "왼쪽 한 칸 이동"
    )
    with pytest.raises(ValueError):
        replace(item, short_meaning="   ")
