"""문서 손상 생성의 재현성·수정량·기술 분포와 전체 풀이를 검증한다."""

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
    _select_damage,
    generate_document_problem,
)
from vim_key_trainer.domain.document_display import compare_documents
from vim_key_trainer.domain.document_missions import (
    DocumentMission,
    DocumentPracticeSpec,
)
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
def test_practice_conditions_reject_fewer_than_seven_repairs(
    change_count: int,
) -> None:
    mission = MISSIONS[0]
    assert DocumentPracticeSpec(mission.id, 1).change_count == 7
    with pytest.raises(ValueError, match="7 이상"):
        DocumentPracticeSpec(mission.id, 1, change_count)


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
