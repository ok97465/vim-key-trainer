"""문서 손상별 복원 명령·객체 경계·검색·이력의 정확성을 검증한다."""

# Standard library imports
from collections import Counter
from dataclasses import replace
from random import Random

# Third party imports
import pytest

# Local imports
from vim_key_trainer.content.document_missions import list_document_missions
from vim_key_trainer.content.edit_loader import validate_edit_replay
from vim_key_trainer.domain.document_corruption import (
    CorruptionKind,
    CorruptionOperation,
    _damage,
    _record_repair,
    _substitution_repairs,
    generate_document_problem,
)
from vim_key_trainer.domain.document_missions import (
    DocumentPracticeSpec,
)
from vim_key_trainer.domain.edit_builder import GuideBuilder
from vim_key_trainer.domain.keys import KeyToken
from vim_key_trainer.engine import SUPPORTED_COMMANDS, EditEngine, EditorState

MISSIONS = list_document_missions()


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
    replacement = after.split()[1]
    assert replacement not in before.split()
    assert after == before.replace(" ready ", f" {replacement} ")
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
    replacement = after.split()[1]
    assert replacement not in before.split()
    assert after == before.replace(" ready ", f" {replacement} ")
    guide = GuideBuilder(EditorState((after,)), SUPPORTED_COMMANDS)
    _record_repair(
        guide, CorruptionOperation(0, damage.kind, damage.tokens, before, after)
    )
    assert guide.engine.state.lines == (before,)
    assert len(guide.steps) == 1
    assert guide.steps[0].keys[0] == KeyToken("char", ":")
    assert guide.steps[0].keys[-2] == KeyToken("char", "g")


@pytest.mark.parametrize(
    ("line", "needs_boundaries"),
    [
        ("alpha ready beta ready gamma", False),
        ("alpha ready beta ready unready ready_state", True),
    ],
)
def test_substitution_uses_word_boundaries_only_for_partial_word_conflicts(
    line: str, needs_boundaries: bool
) -> None:
    damage = _damage(line, "substitute", Random(7))
    command = "".join(key.value for key in damage.tokens)
    assert (r"\<" in command or r"\>" in command) == needs_boundaries
    engine = EditEngine(EditorState((line,)), SUPPORTED_COMMANDS)
    for key in damage.tokens:
        assert engine.submit(key).accepted
    after = engine.state.lines[0]
    if needs_boundaries:
        assert after.endswith("unready ready_state")
    guide = GuideBuilder(EditorState((after,)), SUPPORTED_COMMANDS)
    _record_repair(
        guide, CorruptionOperation(0, damage.kind, damage.tokens, line, after)
    )
    assert guide.engine.state.lines == (line,)


@pytest.mark.parametrize(
    ("kind", "line"),
    [
        ("change_word", "alpha ready omega"),
        ("quoted", 'config "ready" tail'),
        ("block", "config (ready) tail"),
        ("bracketed", "alpha ready omega"),
        ("substitute", "alpha ready beta ready gamma"),
    ],
)
def test_word_damage_varies_its_content_and_keeps_independent_repairs(
    kind: CorruptionKind, line: str
) -> None:
    damaged_lines: set[str] = set()
    for seed in range(32):
        damage = _damage(line, kind, Random(seed))
        assert damage.kind == kind
        engine = EditEngine(EditorState((line,), column=damage.column or 0))
        for key in damage.tokens:
            assert engine.submit(key).accepted
        after = engine.state.lines[0]
        assert after != line
        assert abs(len(after) - len(line)) <= 12
        damaged_lines.add(after)
        guide = GuideBuilder(EditorState((after,)), SUPPORTED_COMMANDS)
        _record_repair(
            guide, CorruptionOperation(0, damage.kind, damage.tokens, line, after)
        )
        assert guide.engine.state.lines == (line,)
        assert guide.engine.state.mode == "normal" and not guide.engine.state.pending
    assert len(damaged_lines) >= 28


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
