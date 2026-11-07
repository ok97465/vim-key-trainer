"""무작위 손상은 실제 키로 생성하고 새 엔진의 복원 풀이로 검증한다."""

# Standard library imports
from collections import Counter
from dataclasses import replace
from itertools import pairwise
from random import Random

# Third party imports
import pytest

# Local imports
from vim_key_trainer.content.document_missions import list_document_missions
from vim_key_trainer.content.edit_loader import validate_edit_replay
from vim_key_trainer.domain.document_corruption import (
    DOCUMENT_GENERATOR_VERSION,
    CorruptionKind,
    CorruptionOperation,
    _damage,
    _record_repair,
    _select_damage,
    _substitution_repairs,
    generate_document_problem,
)
from vim_key_trainer.domain.document_display import compare_documents
from vim_key_trainer.domain.document_missions import (
    DocumentMission,
    DocumentPracticeSpec,
)
from vim_key_trainer.domain.edit_builder import GuideBuilder
from vim_key_trainer.domain.edit_weights import EditTechniqueWeights
from vim_key_trainer.domain.keys import KeyToken
from vim_key_trainer.domain.sessions import InputResult, SessionState
from vim_key_trainer.engine import SUPPORTED_COMMANDS, EditEngine, EditorState
from vim_key_trainer.services.edit_session import EditingSession

MISSIONS = list_document_missions()
UNIFORM_DAMAGE_WEIGHTS = EditTechniqueWeights(
    movement=2,
    word=1,
    insertion=1,
    copy=0,
    structure=1,
    search=0,
    substitution=1,
    visual=1,
    repeat=0,
    numbers=1,
)


@pytest.mark.parametrize("mission", MISSIONS, ids=lambda mission: mission.id)
@pytest.mark.parametrize("change_count", [7, 8])
@pytest.mark.parametrize("seed", [0, 1, 42, 2**32 - 1])
def test_original_is_corrupted_by_real_keys_and_repaired_without_old_undo_history(
    mission: DocumentMission,
    change_count: int,
    seed: int,
) -> None:
    spec = DocumentPracticeSpec(mission.id, seed, change_count)
    plan = generate_document_problem(mission, spec)
    lesson = plan.lesson
    assert lesson.document_spec == spec
    assert lesson.generator_version == DOCUMENT_GENERATOR_VERSION
    assert lesson.goal_lines == mission.goal_lines
    assert lesson.initial.lines != mission.goal_lines
    assert len(lesson.initial.lines) == len(mission.goal_lines)
    assert len(plan.operations) == change_count
    rows = sorted(operation.row for operation in plan.operations)
    assert all(second - first >= 2 for first, second in pairwise(rows))
    assert len({operation.row for operation in plan.operations}) == change_count
    assert all(operation.before != operation.after for operation in plan.operations)
    assert (
        compare_documents(lesson.initial.lines, lesson.goal_lines).remaining_count
        >= change_count
    )

    forward = EditEngine(EditorState(mission.goal_lines))
    for key in plan.corruption_tokens:
        assert forward.submit(key).accepted
    assert forward.state == lesson.initial
    fresh = EditEngine(lesson.initial)
    fresh.submit(KeyToken("char", "u"))
    assert fresh.state == lesson.initial
    for key in lesson.baseline:
        outcome = fresh.submit(key)
        assert outcome.accepted
        assert outcome.command not in {"u", "ctrl+r"}
    assert fresh.state.lines == mission.goal_lines
    validate_edit_replay(lesson)
    guided = EditingSession(lesson)
    free = EditingSession(lesson, "free")
    for key in lesson.baseline:
        assert guided.submit(key) == InputResult.ACCEPTED
        assert free.submit(key) == InputResult.ACCEPTED
    assert guided.state == free.state == SessionState.COMPLETED
    assert guided.result is not None and free.result is not None
    assert guided.result.document_spec == spec
    assert free.result.key_count == lesson.baseline_keys
    assert guided.result.stars == free.result.stars == 3


def test_same_conditions_reproduce_both_damage_commands_and_repair_problem() -> None:
    mission = MISSIONS[0]
    spec = DocumentPracticeSpec(mission.id, 237)
    first = generate_document_problem(mission, spec)
    assert first == generate_document_problem(mission, spec)
    assert (
        first.lesson.signature
        == generate_document_problem(mission, spec).lesson.signature
    )
    different = generate_document_problem(mission, replace(spec, seed=238))
    assert different.corruption_tokens != first.corruption_tokens
    assert different.lesson.initial.lines != first.lesson.initial.lines
    assert different.lesson.signature != first.lesson.signature
    assert different.lesson.goal_lines == first.lesson.goal_lines


def test_document_repair_versions_the_extended_word_command_conditions() -> None:
    mission = MISSIONS[0]
    lesson = generate_document_problem(
        mission, DocumentPracticeSpec(mission.id, 13)
    ).lesson
    assert {"W", "B", "e", "E", "dW", "de", "dE", "diw", "diW"} <= (
        lesson.allowed_commands
    )
    assert lesson.content_version == mission.content_version == 6
    assert lesson.generator_version == DOCUMENT_GENERATOR_VERSION == 8
    assert lesson.baseline_version == 7


def test_each_document_has_many_actual_variants_and_damage_command_families() -> None:
    for mission in MISSIONS:
        plans = [
            generate_document_problem(mission, DocumentPracticeSpec(mission.id, seed))
            for seed in range(20)
        ]
        assert len({plan.lesson.initial.lines for plan in plans}) == 20
        assert len({plan.corruption_tokens for plan in plans}) == 20
        skills = {
            _damage_skill(operation.kind)
            for plan in plans
            for operation in plan.operations
        }
        assert {
            "insertion",
            "deletion",
            "replacement",
            "case",
            "object",
            "indent",
        } <= skills


def test_damage_amount_is_bounded_and_keeps_most_source_characters() -> None:
    for mission in MISSIONS:
        plan = generate_document_problem(
            mission, DocumentPracticeSpec(mission.id, 8, 8)
        )
        assert (
            sum(
                before == after
                for before, after in zip(
                    plan.lesson.goal_lines, plan.lesson.initial.lines, strict=True
                )
            )
            == len(mission.goal_lines) - 8
        )
        for operation in plan.operations:
            assert abs(len(operation.after) - len(operation.before)) <= 12


def test_blank_rows_can_be_damaged_and_restored_as_blank_rows() -> None:
    mission = replace(MISSIONS[0], goal_lines=("",) * 24)
    plan = generate_document_problem(mission, DocumentPracticeSpec(mission.id, 11, 8))
    validate_edit_replay(plan.lesson)
    assert len(plan.operations) == 8
    assert all(operation.after for operation in plan.operations)
    assert plan.lesson.goal_lines == ("",) * 24


def test_invalid_document_or_too_short_source_is_rejected() -> None:
    mission = MISSIONS[0]
    with pytest.raises(ValueError, match="ID"):
        generate_document_problem(mission, DocumentPracticeSpec("mission_other", 1))
    with pytest.raises(ValueError, match="길이"):
        generate_document_problem(
            replace(mission, goal_lines=("short",) * 3),
            DocumentPracticeSpec(mission.id, 1, 7),
        )


def test_minimum_length_source_still_keeps_each_damage_site_separate() -> None:
    mission = replace(MISSIONS[0], goal_lines=tuple(f"line {row}" for row in range(15)))
    plan = generate_document_problem(mission, DocumentPracticeSpec(mission.id, 17, 8))
    rows = sorted(operation.row for operation in plan.operations)
    assert rows == list(range(0, 15, 2))
    validate_edit_replay(plan.lesson)


def test_new_damage_families_have_independent_replay_verified_repairs() -> None:
    mission = replace(
        MISSIONS[0],
        goal_lines=tuple(
            f'config cache_{row} = "ready"; retries = 123' for row in range(24)
        ),
    )
    kinds: set[str] = set()
    repair_commands: set[str] = set()
    repair_chords: set[str] = set()
    for seed in range(12):
        plan = generate_document_problem(
            mission, DocumentPracticeSpec(mission.id, seed, 8)
        )
        kinds.update(operation.kind for operation in plan.operations)
        fresh = EditEngine(plan.lesson.initial, plan.lesson.allowed_commands)
        # 손상 생성기의 undo 이력이나 레지스터를 받지 않은 새 복원 엔진이다.
        assert fresh.submit(KeyToken("char", "u")).accepted
        assert fresh.state == plan.lesson.initial
        for key in plan.lesson.baseline:
            outcome = fresh.submit(key)
            assert outcome.accepted
            if outcome.command:
                repair_commands.add(outcome.command)
            if key.kind == "chord":
                repair_chords.add(key.value)
        assert fresh.state.lines == mission.goal_lines
        validate_edit_replay(plan.lesson)
    assert {
        "replace_char",
        "change_word",
        "quoted",
        "number",
        "indent",
        "case",
    } <= kinds
    assert {"r", "~", "<<"} <= repair_commands
    assert repair_commands & {"ciw", "cw", "ce", "cW", "cE"}
    assert "ctrl+x" in repair_chords


@pytest.mark.parametrize("change_count", [3, 5, 6])
def test_legacy_conditions_are_readable_but_new_practice_requires_seven_repairs(
    change_count: int,
) -> None:
    mission = MISSIONS[0]
    assert DocumentPracticeSpec(mission.id, 1).change_count == 7
    spec = DocumentPracticeSpec(mission.id, 1, change_count)
    with pytest.raises(ValueError, match="최소 7곳"):
        generate_document_problem(mission, spec)


@pytest.mark.parametrize(
    ("before", "after"),
    [
        ("alpha omega", "alpha duplicate omega"),
        ("same same done", "same same draftdraft done"),
        (r"path = a/b & c\d ~ end", r"path = a/b & c\draft ~ end"),
        ("literal [a.*] old end", "literal [a.*] draftdraft end"),
    ],
)
def test_long_repair_has_literal_substitution_without_large_character_counts(
    before: str, after: str
) -> None:
    operation = CorruptionOperation(0, "replace", (), before, after)
    guide = GuideBuilder(EditorState((after,)), SUPPORTED_COMMANDS)
    _record_repair(guide, operation)
    assert guide.engine.state.lines == (before,)
    keys, _ = min(
        _substitution_repairs(operation), key=lambda candidate: len(candidate[0])
    )
    assert keys[0] == KeyToken("char", ":")
    assert keys[-1] == KeyToken("special", "enter")
    substitute = EditEngine(EditorState((after,)), SUPPORTED_COMMANDS)
    for key in keys:
        assert substitute.submit(key).accepted
    assert substitute.state.lines == (before,)
    probe = EditEngine(EditorState((after,)), SUPPORTED_COMMANDS)
    for step in guide.steps:
        for key in step.keys:
            outcome = probe.submit(key)
            assert outcome.accepted
            assert outcome.command != "x"
    assert probe.state.lines == (before,)


def test_actual_document_guides_practice_readable_motion_and_word_repairs() -> None:
    commands: set[str] = set()
    for seed in range(8):
        lesson = generate_document_problem(
            MISSIONS[0], DocumentPracticeSpec(MISSIONS[0].id, seed)
        ).lesson
        probe = EditEngine(lesson.initial, lesson.allowed_commands)
        for key in lesson.baseline:
            pending = probe.state.pending
            outcome = probe.submit(key)
            assert outcome.accepted
            if outcome.command:
                commands.add(outcome.command)
            if outcome.command in {"x", "h", "l"}:
                assert int(pending or "1") <= 3
        assert probe.state.lines == lesson.goal_lines
    assert commands & {"w", "W", "e", "E"}
    assert commands & {"f", "F", "t", "T"}
    assert commands & {"dw", "dW", "de", "dE", "diw", "diW", "daw", "daW"}
    assert any(command.startswith(("ct", "cf", "dt", "df")) for command in commands)


def test_substitution_repair_needs_only_the_line_and_preserves_undo() -> None:
    before = "alpha beta gamma tail"
    after = "alpha beta draftdraft gamma tail"
    guide = GuideBuilder(EditorState((after,)), frozenset({":", "u"}))
    _record_repair(guide, CorruptionOperation(0, "insert", (), before, after))
    assert len(guide.steps) == 1
    assert guide.steps[0].keys[0] == KeyToken("char", ":")
    assert guide.engine.state.lines == (before,)
    assert guide.engine.submit(KeyToken("char", "u")).accepted
    assert guide.engine.state.lines == (after,)


def test_substitution_repair_does_not_require_unavailable_column_movements() -> None:
    before = "alpha beta gamma tail"
    after = "alpha beta draftdraft gamma tail"
    guide = GuideBuilder(EditorState((after,)), frozenset({":"}))
    _record_repair(guide, CorruptionOperation(0, "insert", (), before, after))
    assert guide.engine.state.lines == (before,)
    assert len(guide.steps) == 1


@pytest.mark.parametrize("quote", ['"', "'"])
def test_escaped_quotes_do_not_turn_small_damage_into_a_long_object_change(
    quote: str,
) -> None:
    line = "prefix " + quote + "a" * 100 + "\\" + quote + "tiny" + quote + " suffix"
    damage = _damage(line, "quoted", Random(1))
    engine = EditEngine(EditorState((line,), column=damage.column or 0))
    for key in damage.tokens:
        assert engine.submit(key).accepted
    assert engine.state.lines != (line,)
    assert abs(len(engine.state.lines[0]) - len(line)) <= 12
    assert "a" * 100 in engine.state.lines[0]


@pytest.mark.parametrize("quote", ['"', "'"])
def test_short_quoted_object_with_an_escaped_quote_has_a_replayable_repair(
    quote: str,
) -> None:
    line = "value = " + quote + "ab\\" + quote + "cd" + quote + " suffix"
    damage = _damage(line, "quoted", Random(1))
    assert damage.kind == "quoted"
    engine = EditEngine(EditorState((line,), column=damage.column or 0))
    for key in damage.tokens:
        assert engine.submit(key).accepted
    after = engine.state.lines[0]
    guide = GuideBuilder(engine.state, SUPPORTED_COMMANDS)
    _record_repair(guide, CorruptionOperation(0, "quoted", damage.tokens, line, after))
    assert guide.engine.state.lines == (line,)


def test_added_word_is_removed_as_a_word_without_typing_a_substitution() -> None:
    before = "alpha omega"
    after = "alpha duplicate omega"
    guide = GuideBuilder(EditorState((after,)), SUPPORTED_COMMANDS)
    _record_repair(guide, CorruptionOperation(0, "duplicate", (), before, after))
    probe = EditEngine(EditorState((after,)), SUPPORTED_COMMANDS)
    commands: set[str] = set()
    for step in guide.steps:
        for key in step.keys:
            outcome = probe.submit(key)
            assert outcome.accepted
            if outcome.command:
                commands.add(outcome.command)
    assert probe.state.lines == (before,)
    assert commands & {"dw", "dW", "de", "dE", "diw", "diW", "daw", "daW"}
    assert ":" not in commands


def test_repeated_repairs_offer_different_valid_command_families() -> None:
    before = "alpha omega"
    after = "alpha duplicate omega"
    state = EditorState((after,) * 7)
    guide = GuideBuilder(state, SUPPORTED_COMMANDS)
    used_families: Counter[str] = Counter()
    for row in range(7):
        _record_repair(
            guide,
            CorruptionOperation(row, "duplicate", (), before, after),
            used_families,
        )
    assert guide.engine.state.lines == (before,) * 7
    assert len(used_families) >= 3
    assert sum(used_families.values()) == 7


def test_repair_selection_includes_the_cost_of_reaching_the_damaged_column() -> None:
    # 가운데 문자에 도달하려고 반복 문자를 세는 대신 단어 전체를 바꿀 수 있다.
    before = "a" * 30 + "X" + "a" * 30
    after = "a" * 61
    guide = GuideBuilder(EditorState((after,)), SUPPORTED_COMMANDS)
    _record_repair(guide, CorruptionOperation(0, "replace_char", (), before, after))
    assert guide.engine.state.lines == (before,)
    # 큰 문자 count 또는 난해한 정규식 이동을 강요하지 않는다.
    probe = EditEngine(EditorState((after,)), SUPPORTED_COMMANDS)
    for step in guide.steps:
        for key in step.keys:
            pending = probe.state.pending
            outcome = probe.submit(key)
            assert outcome.accepted
            if outcome.command in {"h", "l"}:
                assert int(pending or "1") <= 2


def test_repeated_word_damage_has_a_short_global_substitution_repair() -> None:
    before = "alpha ready beta ready gamma ready tail; unready ready_state"
    damage = _damage(before, "substitute", Random(1))
    assert damage.kind == "substitute"
    engine = EditEngine(EditorState((before,)), SUPPORTED_COMMANDS)
    for key in damage.tokens:
        assert engine.submit(key).accepted
    after = engine.state.lines[0]
    assert after == before.replace(" ready ", " draft ")
    assert after.endswith("tail; unready ready_state")
    guide = GuideBuilder(EditorState((after,)), SUPPORTED_COMMANDS)
    _record_repair(
        guide, CorruptionOperation(0, damage.kind, damage.tokens, before, after)
    )
    assert guide.engine.state.lines == (before,)
    assert len(guide.steps) == 1
    assert guide.steps[0].keys[:3] == tuple(KeyToken("char", key) for key in ":s/")
    assert guide.steps[0].keys[-2] == KeyToken("char", "g")
    assert len(guide.steps[0].keys) < len(before)


def test_repeated_word_damage_does_not_reuse_an_existing_source_word() -> None:
    before = "alpha ready beta draft gamma ready tail"
    damage = _damage(before, "substitute", Random(1))
    assert damage.kind == "substitute"
    engine = EditEngine(EditorState((before,)), SUPPORTED_COMMANDS)
    for key in damage.tokens:
        assert engine.submit(key).accepted
    after = engine.state.lines[0]
    assert after == "alpha trace beta draft gamma trace tail"
    guide = GuideBuilder(EditorState((after,)), SUPPORTED_COMMANDS)
    _record_repair(
        guide, CorruptionOperation(0, damage.kind, damage.tokens, before, after)
    )
    assert guide.engine.state.lines == (before,)
    assert len(guide.steps) == 1
    assert guide.steps[0].keys[0] == KeyToken("char", ":")
    assert guide.steps[0].keys[-2] == KeyToken("char", "g")


@pytest.mark.parametrize(
    ("before", "after", "column", "command"),
    [
        ("alpha ready omega", "alpha obsolete omega", 9, "ciw"),
        ("endpoint prod/v2 ready", "endpoint old/path?x=1 ready", 13, "ciW"),
        ("alpha ready omega", "alpha obsolete omega", 6, "cw"),
    ],
)
def test_word_repair_uses_the_current_position_without_forcing_a_return_to_start(
    before: str, after: str, column: int, command: str
) -> None:
    initial = EditorState((after,), column=column)
    guide = GuideBuilder(initial, SUPPORTED_COMMANDS)
    _record_repair(guide, CorruptionOperation(0, "change_word", (), before, after))
    probe = EditEngine(initial, SUPPORTED_COMMANDS)
    commands: list[str] = []
    for step in guide.steps:
        for key in step.keys:
            outcome = probe.submit(key)
            assert outcome.accepted
            if outcome.command and outcome.command != "esc":
                commands.append(outcome.command)
    assert commands == [command]
    assert probe.state.lines == (before,)
    assert probe.state.mode == "normal" and not probe.state.pending
    assert probe.submit(KeyToken("char", "u")).accepted
    assert probe.state.lines == (after,)


@pytest.mark.parametrize(
    ("opening", "closing", "command"),
    [
        ("(", ")", "cib"),
        ("(", ")", "ci("),
        ("(", ")", "ci)"),
        ("[", "]", "ci["),
        ("[", "]", "ci]"),
        ("{", "}", "ciB"),
        ("{", "}", "ci{"),
        ("{", "}", "ci}"),
        ("<", ">", "ci<"),
        ("<", ">", "ci>"),
        ("`", "`", "ci`"),
    ],
)
def test_delimited_repair_offers_each_inner_object_and_preserves_its_surroundings(
    opening: str, closing: str, command: str
) -> None:
    prefix, suffix = "config ", " tail"
    before = prefix + opening + "verified value" + closing + suffix
    after = prefix + opening + "draft text" + closing + suffix
    initial = EditorState((after,), column=len(prefix) + 3)
    guide = GuideBuilder(initial, frozenset({command, "u"}))
    _record_repair(guide, CorruptionOperation(0, "block", (), before, after))
    assert len(guide.steps) == 1
    assert "".join(key.display for key in guide.steps[0].keys).startswith(command)
    assert guide.engine.state.lines == (before,)
    assert guide.engine.state.mode == "normal" and not guide.engine.state.pending
    assert guide.engine.submit(KeyToken("char", "u")).accepted
    assert guide.engine.state.lines == (after,)


@pytest.mark.parametrize(
    ("opening", "closing", "command"),
    [
        ("(", ")", "dab"),
        ("[", "]", "da]"),
        ("{", "}", "daB"),
        ("<", ">", "da>"),
    ],
)
def test_added_bracketed_fragment_can_be_removed_with_one_around_object(
    opening: str, closing: str, command: str
) -> None:
    before = "alpha omega"
    after = "alpha " + opening + "debug" + closing + "omega"
    guide = GuideBuilder(EditorState((after,), column=8), frozenset({command, "u"}))
    _record_repair(guide, CorruptionOperation(0, "bracketed", (), before, after))
    assert len(guide.steps) == 1
    assert "".join(key.display for key in guide.steps[0].keys) == command
    assert guide.engine.state.lines == (before,)
    assert guide.engine.submit(KeyToken("char", "u")).accepted
    assert guide.engine.state.lines == (after,)


@pytest.mark.parametrize("line", ["call((old) ok) tail", "call([old] ok) tail"])
def test_block_damage_and_repair_keep_nested_delimiters_in_one_undo_group(
    line: str,
) -> None:
    for seed in range(8):
        damage = _damage(line, "block", Random(seed))
        assert damage.kind == "block"
        forward = EditEngine(EditorState((line,), column=damage.column or 0))
        for key in damage.tokens:
            assert forward.submit(key).accepted
        after = forward.state.lines[0]
        assert after != line
        assert after.startswith("call(") and after.endswith(") tail")
        assert abs(len(after) - len(line)) <= 12
        guide = GuideBuilder(forward.state, SUPPORTED_COMMANDS)
        _record_repair(
            guide, CorruptionOperation(0, damage.kind, damage.tokens, line, after)
        )
        assert guide.engine.state.lines == (line,)
        assert guide.engine.submit(KeyToken("char", "u")).accepted
        assert guide.engine.state.lines == (after,)


@pytest.mark.parametrize(
    "line", ["prefix (unfinished [ tail", "prefix (" + "a" * 100 + ") tail"]
)
def test_block_damage_falls_back_when_no_small_complete_object_exists(
    line: str,
) -> None:
    damage = _damage(line, "block", Random(1))
    assert damage.kind != "block"
    engine = EditEngine(EditorState((line,), column=damage.column or 0))
    for key in damage.tokens:
        assert engine.submit(key).accepted
    assert engine.state.lines != (line,)
    assert len(engine.state.lines) == 1
    assert abs(len(engine.state.lines[0]) - len(line)) <= 12


def test_generated_document_repairs_include_inner_and_around_bracket_objects() -> None:
    mission = replace(
        MISSIONS[0],
        goal_lines=tuple(
            f"config cache_{row} = (ready now) [value set] {{active map}}; retries=123"
            for row in range(24)
        ),
    )
    kinds: set[str] = set()
    commands: set[str] = set()
    for seed in range(24):
        plan = generate_document_problem(
            mission, DocumentPracticeSpec(mission.id, seed, 8)
        )
        kinds.update(operation.kind for operation in plan.operations)
        probe = EditEngine(plan.lesson.initial, plan.lesson.allowed_commands)
        for key in plan.lesson.baseline:
            outcome = probe.submit(key)
            assert outcome.accepted
            if outcome.command:
                commands.add(outcome.command)
        assert probe.state.lines == mission.goal_lines
        assert probe.state.mode == "normal" and not probe.state.pending
        validate_edit_replay(plan.lesson)
    assert {"block", "bracketed"} <= kinds
    assert {"cib", "da]"} <= commands
    assert commands & {"ciw", "ciW", "cw", "cW", "ce", "cE"}


def _damage_skill(kind: str) -> str:
    if kind in {"insert", "prefix", "append", "duplicate"}:
        return "insertion"
    if kind in {"delete", "word"}:
        return "deletion"
    if kind in {"replace", "replace_char", "change_word"}:
        return "replacement"
    if kind in {"quoted", "block", "bracketed"}:
        return "object"
    return kind


@pytest.mark.parametrize("change_count", [7, 8])
@pytest.mark.parametrize("seed", range(8))
def test_rich_documents_balance_actual_damage_skills_in_every_problem(
    change_count: int, seed: int
) -> None:
    mission = replace(
        MISSIONS[0],
        goal_lines=tuple(
            f'config item_{row} = "ready" (value set); retries=123; ready again'
            for row in range(32)
        ),
    )
    plan = generate_document_problem(
        mission,
        DocumentPracticeSpec(mission.id, seed, change_count, UNIFORM_DAMAGE_WEIGHTS),
    )
    skills = Counter(_damage_skill(operation.kind) for operation in plan.operations)
    assert len(skills) == change_count
    assert set(skills.values()) == {1}
    rows = sorted(operation.row for operation in plan.operations)
    assert all(right - left >= 2 for left, right in pairwise(rows))
    assert len(plan.lesson.initial.lines) == len(mission.goal_lines)
    validate_edit_replay(plan.lesson)


@pytest.mark.parametrize("seed", range(12))
@pytest.mark.parametrize("number_line", ["alpha retries = 123 gamma", "42"])
def test_rare_numeric_and_repeated_word_rows_are_reserved_for_their_skills(
    seed: int, number_line: str
) -> None:
    lines = ["alpha beta gamma delta"] * 40
    lines[7] = number_line
    lines[27] = "alpha ready beta ready gamma"
    choices = _select_damage(tuple(lines), 8, Random(seed), UNIFORM_DAMAGE_WEIGHTS)
    by_kind = {choice.damage.kind: choice for choice in choices}
    assert by_kind["number"].row == 7
    assert by_kind["substitute"].row == 27
    assert len({_damage_skill(choice.damage.kind) for choice in choices}) == 8
    for choice in choices:
        before = lines[choice.row]
        probe = EditEngine(EditorState((before,), column=choice.damage.column or 0))
        for key in choice.damage.tokens:
            assert probe.submit(key).accepted
        assert probe.state.lines != (before,)
        assert len(probe.state.lines) == 1


@pytest.mark.parametrize("seed", range(8))
def test_unavailable_damage_skills_do_not_count_as_balanced_fallbacks(
    seed: int,
) -> None:
    choices = _select_damage(
        ("alpha beta gamma delta",) * 32, 8, Random(seed), UNIFORM_DAMAGE_WEIGHTS
    )
    kinds = {choice.damage.kind for choice in choices}
    assert not kinds & {"number", "substitute", "block", "quoted"}
    skills = Counter(_damage_skill(choice.damage.kind) for choice in choices)
    assert len(skills) == 6
    assert sorted(skills.values()) == [1, 1, 1, 1, 2, 2]
    assert "bracketed" in kinds


def test_blank_sources_use_only_real_insertion_skills() -> None:
    choices = _select_damage(("",) * 24, 8, Random(123), UNIFORM_DAMAGE_WEIGHTS)
    assert len(choices) == 8
    assert {_damage_skill(choice.damage.kind) for choice in choices} == {"insertion"}
    rows = sorted(choice.row for choice in choices)
    assert all(right - left >= 2 for left, right in pairwise(rows))
    for choice in choices:
        probe = EditEngine(EditorState(("",)))
        for key in choice.damage.tokens:
            assert probe.submit(key).accepted
        assert probe.state.lines != ("",)


@pytest.mark.parametrize(
    ("opening", "closing", "commands"),
    [
        ("(", ")", ("cib", "ci(", "ci)")),
        ("[", "]", ("ci[", "ci]")),
        ("{", "}", ("ciB", "ci{", "ci}")),
        ("<", ">", ("ci<", "ci>")),
    ],
)
def test_object_alias_repairs_share_one_usage_counter(
    opening: str, closing: str, commands: tuple[str, ...]
) -> None:
    before = "config " + opening + "verified value" + closing + " tail"
    after = "config " + opening + "draft text" + closing + " tail"
    used: Counter[str] = Counter()
    for command in commands:
        guide = GuideBuilder(EditorState((after,), column=10), frozenset({command}))
        _record_repair(guide, CorruptionOperation(0, "block", (), before, after), used)
        assert guide.engine.state.lines == (before,)
    assert len(used) == 1
    assert list(used.values()) == [len(commands)]


@pytest.mark.parametrize("second_value", ["ready", "active"])
def test_repeat_repairs_reuse_only_a_matching_previous_change(
    second_value: str,
) -> None:
    after = "alpha obsolete omega"
    first_goal = "alpha ready omega"
    second_goal = f"alpha {second_value} omega"
    initial = EditorState((after, after), column=6)
    guide = GuideBuilder(initial, SUPPORTED_COMMANDS)
    used: Counter[str] = Counter()
    _record_repair(
        guide, CorruptionOperation(0, "change_word", (), first_goal, after), used
    )
    start = len(guide.steps)
    _record_repair(
        guide, CorruptionOperation(1, "change_word", (), second_goal, after), used
    )
    repeats = [
        step for step in guide.steps[start:] if step.keys == (KeyToken("char", "."),)
    ]
    assert bool(repeats) == (second_value == "ready")
    assert guide.engine.state.lines == (first_goal, second_goal)
    assert guide.engine.state.mode == "normal" and not guide.engine.state.pending
    fresh = EditEngine(initial, SUPPORTED_COMMANDS)
    for step in guide.steps:
        for key in step.keys:
            assert fresh.submit(key).accepted
        assert fresh.state == step.expected
    assert fresh.submit(KeyToken("char", "u")).accepted
    assert fresh.state.lines == (first_goal, after)


@pytest.mark.parametrize(
    ("before", "after", "kind"),
    [
        ("call(verified value) tail", "call(draft text) tail", "block"),
        ("alpha omega", "alpha [debug]omega", "bracketed"),
    ],
)
def test_repeated_object_skills_offer_visual_selection_without_changing_the_goal(
    before: str, after: str, kind: CorruptionKind
) -> None:
    initial = EditorState((after,), column=8)
    guide = GuideBuilder(initial, SUPPORTED_COMMANDS)
    used: Counter[str] = Counter({"delimited_inner": 2, "delimited_around": 2})
    _record_repair(
        guide,
        CorruptionOperation(0, kind, (), before, after),
        used,
    )
    fresh = EditEngine(initial, SUPPORTED_COMMANDS)
    selected = False
    for step in guide.steps:
        for key in step.keys:
            outcome = fresh.submit(key)
            assert outcome.accepted
            selected |= outcome.command == "v"
    assert selected
    assert fresh.state.lines == (before,)
    assert fresh.state.mode == "normal" and not fresh.state.pending
    assert fresh.submit(KeyToken("char", "u")).accepted
    assert fresh.state.lines == (after,)
    assert used["visual"] == 1


@pytest.mark.parametrize("seed", [0, 1, 7])
def test_zero_substitution_weight_excludes_substitution_damage(seed: int) -> None:
    mission = replace(
        MISSIONS[0],
        goal_lines=tuple(
            f'config item_{row} = "ready" (value set); retries=123; ready again'
            for row in range(32)
        ),
    )
    weights = EditTechniqueWeights(substitution=0)
    plan = generate_document_problem(
        mission, DocumentPracticeSpec(mission.id, seed, 8, weights)
    )
    assert len(plan.operations) == 8
    assert all(operation.kind != "substitute" for operation in plan.operations)
    validate_edit_replay(plan.lesson)


@pytest.mark.parametrize("change_count", [7, 8])
def test_substitution_only_weight_creates_real_global_substitution_practice(
    change_count: int,
) -> None:
    mission = replace(
        MISSIONS[0],
        goal_lines=tuple(
            f"config item_{row} ready again ready end" for row in range(32)
        ),
    )
    weights = EditTechniqueWeights(
        **{
            name: int(name == "substitution")
            for name, _ in EditTechniqueWeights().items()
        }
    )
    plan = generate_document_problem(
        mission, DocumentPracticeSpec(mission.id, 21, change_count, weights)
    )
    assert len(plan.operations) == change_count
    assert {operation.kind for operation in plan.operations} == {"substitute"}
    for operation in plan.operations:
        assert operation.tokens[:3] == tuple(KeyToken("char", key) for key in ":s/")
        assert operation.tokens[-2:] == (
            KeyToken("char", "g"),
            KeyToken("special", "enter"),
        )
    damage = EditEngine(EditorState(mission.goal_lines), SUPPORTED_COMMANDS)
    for key in plan.corruption_tokens:
        assert damage.submit(key).accepted
    assert damage.state == plan.lesson.initial
    fresh = EditEngine(plan.lesson.initial, SUPPORTED_COMMANDS)
    commands: set[str] = set()
    for key in plan.lesson.baseline:
        outcome = fresh.submit(key)
        assert outcome.accepted
        if outcome.command:
            commands.add(outcome.command)
    assert ":" in commands
    assert fresh.state.lines == mission.goal_lines
    assert fresh.state.mode == "normal" and not fresh.state.pending
    validate_edit_replay(plan.lesson)


def test_impossible_document_weight_policy_preserves_the_source() -> None:
    mission = MISSIONS[0]
    original = mission.goal_lines
    weights = EditTechniqueWeights(
        **{name: int(name == "copy") for name, _ in EditTechniqueWeights().items()}
    )
    with pytest.raises(ValueError, match="기술 비중"):
        generate_document_problem(
            mission, DocumentPracticeSpec(mission.id, 21, 8, weights)
        )
    assert mission.goal_lines == original


@pytest.mark.parametrize("seed", [0, 1, 7])
def test_input_weight_trains_restoring_missing_text_instead_of_deleting_extra_text(
    seed: int,
) -> None:
    mission = replace(
        MISSIONS[0],
        goal_lines=tuple(f"alpha item_{row} ready omega" for row in range(32)),
    )
    weights = EditTechniqueWeights(
        **{name: int(name == "insertion") for name, _ in EditTechniqueWeights().items()}
    )
    plan = generate_document_problem(
        mission, DocumentPracticeSpec(mission.id, seed, 7, weights)
    )
    assert all(
        len(operation.after) < len(operation.before) for operation in plan.operations
    )
    fresh = EditEngine(plan.lesson.initial, plan.lesson.allowed_commands)
    insertions = 0
    for key in plan.lesson.baseline:
        before = fresh.state
        assert fresh.submit(key).accepted
        if before.mode == "insert" and key.kind == "char":
            insertions += 1
    assert insertions >= 7
    assert fresh.state.lines == mission.goal_lines
    validate_edit_replay(plan.lesson)
