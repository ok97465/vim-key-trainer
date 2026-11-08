"""긴 편집 문서의 재현성·수정량·다양성과 풀이 재생을 검증한다."""

# Standard library imports
import re
from collections import Counter
from dataclasses import FrozenInstanceError
from difflib import SequenceMatcher
from random import Random

# Third party imports
import pytest

# Local imports
from vim_key_trainer.content.edit_loader import validate_edit_replay
from vim_key_trainer.domain.edit_generator import (
    EDIT_DOCUMENT_LENGTHS,
    EDIT_GENERATOR_VERSION,
    EditPracticeSpec,
    generate_edit_lesson,
    get_edit_profile,
    list_edit_profiles,
)
from vim_key_trainer.domain.edit_templates import (
    DocumentPlan,
    EditRecipe,
    build_document_plan,
)
from vim_key_trainer.domain.edit_weights import EDIT_TECHNIQUES, EditTechniqueWeights
from vim_key_trainer.domain.editing import goal_matches
from vim_key_trainer.domain.keys import KeyToken
from vim_key_trainer.domain.sessions import SessionState
from vim_key_trainer.engine import SUPPORTED_COMMANDS, EditEngine, EditorState
from vim_key_trainer.services.edit_session import EditingSession

PROFILE_IDS = tuple(profile.id for profile in list_edit_profiles())


@pytest.mark.parametrize("profile_id", PROFILE_IDS)
@pytest.mark.parametrize("document_lines", EDIT_DOCUMENT_LENGTHS)
def test_generated_plans_keep_at_least_seven_independent_repairs(
    profile_id: str, document_lines: int
) -> None:
    for seed in range(64):
        plan = build_document_plan(profile_id, document_lines, Random(seed))
        required = max(7, document_lines // 4)
        assert len(plan.recipes) >= required
        if profile_id == "editing_undo":
            continue
        changed_lines = sum(
            max(i2 - i1, j2 - j1)
            for kind, i1, i2, j1, j2 in SequenceMatcher(
                a=plan.lines, b=plan.goal_lines, autojunk=False
            ).get_opcodes()
            if kind != "equal"
        )
        assert changed_lines >= required


@pytest.mark.parametrize("profile_id", PROFILE_IDS)
@pytest.mark.parametrize("document_lines", EDIT_DOCUMENT_LENGTHS)
@pytest.mark.parametrize("seed", [0, 1, 42, 2**32 - 1])
def test_all_profiles_lengths_and_seeds_replay_their_explicit_targets(
    profile_id: str, document_lines: int, seed: int
) -> None:
    spec = EditPracticeSpec(profile_id, seed, document_lines)
    lesson = generate_edit_lesson(spec)
    assert len(lesson.initial.lines) == document_lines
    assert lesson.practice_spec == spec
    assert lesson.generator_version == EDIT_GENERATOR_VERSION
    assert lesson.content_version == get_edit_profile(profile_id).content_version
    assert lesson.baseline_keys == len(lesson.baseline)
    assert all(line.isascii() for line in lesson.initial.lines + lesson.goal_lines)
    validate_edit_replay(lesson)
    guided = EditingSession(lesson)
    for step in lesson.guide:
        for key in step.keys:
            guided.submit(key)
    assert guided.state == SessionState.COMPLETED
    assert guided.result is not None and guided.result.stars == 3
    if lesson.free_enabled:
        free = EditingSession(lesson, "free")
        for key in lesson.baseline:
            free.submit(key)
        assert free.state == SessionState.COMPLETED
        assert free.key_count == lesson.baseline_keys
    else:
        assert lesson.initial.lines == lesson.goal_lines


@pytest.mark.parametrize("profile_id", PROFILE_IDS)
@pytest.mark.parametrize("document_lines", EDIT_DOCUMENT_LENGTHS)
def test_document_length_scales_required_work_not_only_unchanged_padding(
    profile_id: str, document_lines: int
) -> None:
    lesson = generate_edit_lesson(EditPracticeSpec(profile_id, 19, document_lines))
    required = max(7, document_lines // 4)
    if lesson.free_enabled:
        differences = SequenceMatcher(
            a=lesson.initial.lines, b=lesson.goal_lines, autojunk=False
        ).get_opcodes()
        changed_lines = sum(
            max(i2 - i1, j2 - j1)
            for kind, i1, i2, j1, j2 in differences
            if kind != "equal"
        )
        assert changed_lines >= required
    engine = EditEngine(lesson.initial, lesson.allowed_commands)
    modified_rows: set[int] = set()
    for key in lesson.baseline:
        row = engine.state.row
        outcome = engine.submit(key)
        if outcome.changed:
            modified_rows.add(row)
    assert len(modified_rows) >= required
    assert max(modified_rows) - min(modified_rows) >= document_lines - 7


@pytest.mark.parametrize("profile_id", PROFILE_IDS)
def test_each_profile_varies_documents_targets_and_command_patterns(
    profile_id: str,
) -> None:
    lessons = [
        generate_edit_lesson(EditPracticeSpec(profile_id, seed)) for seed in range(24)
    ]
    assert len({lesson.initial.lines for lesson in lessons}) == len(lessons)
    assert len({lesson.goal_lines for lesson in lessons}) == len(lessons)
    assert len({lesson.baseline for lesson in lessons}) >= 16
    contexts = {lesson.title.split(" · ", 1)[1] for lesson in lessons}
    assert len(contexts) == 5


def test_generation_repeats_same_conditions_and_separates_signatures() -> None:
    spec = EditPracticeSpec("editing_compound", 42)
    first = generate_edit_lesson(spec)
    assert first == generate_edit_lesson(spec)
    assert first.signature == generate_edit_lesson(spec).signature
    assert (
        first.signature
        != generate_edit_lesson(EditPracticeSpec(spec.profile_id, 43)).signature
    )
    assert (
        first.signature
        != generate_edit_lesson(
            EditPracticeSpec(spec.profile_id, spec.seed, 40)
        ).signature
    )


def test_number_replacements_cover_different_widths_and_positions() -> None:
    width_pairs: set[tuple[int, int]] = set()
    columns: set[int] = set()
    for seed in range(8):
        lesson = generate_edit_lesson(EditPracticeSpec("editing_numbers", seed))
        engine = EditEngine(lesson.initial, lesson.allowed_commands)
        for step in lesson.guide:
            if "기존 값" in step.text:
                columns.add(engine.state.column)
            for key in step.keys:
                engine.submit(key)
        for old, new in zip(lesson.initial.lines, lesson.goal_lines, strict=True):
            if old != new:
                old_value = "".join(char for char in old if char.isdigit())
                new_value = "".join(char for char in new if char.isdigit())
                width_pairs.add((len(old_value), len(new_value)))
    assert len(width_pairs) >= 8
    assert len(columns) >= 8


def test_profiles_use_counted_line_word_deletes_insert_enter_and_actual_redo() -> None:
    sequences: dict[str, set[tuple[KeyToken, ...]]] = {}
    for profile_id in PROFILE_IDS:
        sequences[profile_id] = {
            step.keys
            for seed in range(64 if profile_id == "editing_compound" else 16)
            for step in generate_edit_lesson(EditPracticeSpec(profile_id, seed)).guide
        }
    displays = {
        profile_id: {"".join(key.display for key in keys) for keys in values}
        for profile_id, values in sequences.items()
    }
    assert {"dd", "2dd", "d2d"} <= displays["editing_delete_line"]
    assert {"dw", "2dw", "d2w", "dt;"} <= displays["editing_delete_word"]
    assert {"dW", "d2W", "de", "dE", "diw", "diW"} <= displays["editing_delete_word"]
    assert any(
        KeyToken("special", "enter") in keys for keys in sequences["editing_append"]
    )
    assert (KeyToken("chord", "ctrl+r"),) in sequences["editing_undo"]
    assert "u" in displays["editing_undo"]
    compound = displays["editing_compound"]
    assert "dw" in compound
    assert any(display.startswith(("dW", "diW", "ciW")) for display in compound)
    assert any(display.startswith(("de", "diw", "ciw", "cw")) for display in compound)
    assert any(display.endswith("dE") for display in compound)
    assert "dd" in compound or "2dd" in compound or "d2d" in compound
    assert any("<Esc>" in display for display in compound)


@pytest.mark.parametrize("profile_id", PROFILE_IDS)
def test_generated_profiles_allow_word_and_word_object_alternative_solutions(
    profile_id: str,
) -> None:
    lesson = generate_edit_lesson(EditPracticeSpec(profile_id, 3))
    assert lesson.allowed_commands == SUPPORTED_COMMANDS
    assert {"W", "B", "e", "E", "dW", "de", "dE", "diw", "diW"} <= (
        lesson.allowed_commands
    )


def test_word_motion_guides_replay_and_inner_objects_preserve_adjacent_delimiters() -> (
    None
):
    motions: set[str] = set()
    inner_deletes: set[str] = set()
    for seed in range(16):
        lesson = generate_edit_lesson(EditPracticeSpec("editing_delete_word", seed))
        engine = EditEngine(lesson.initial, lesson.allowed_commands)
        for step in lesson.guide:
            before = engine.state
            for key in step.keys:
                outcome = engine.submit(key)
                assert outcome.accepted
                if outcome.command in {"W", "B", "e", "E"}:
                    motions.add(outcome.command)
                if outcome.command in {"diw", "diW"}:
                    inner_deletes.add(outcome.command)
                    assert engine.state.column < before.column
                    line = before.lines[before.row]
                    pattern = r"\w+" if outcome.command == "diw" else r"\S+"
                    word = next(
                        match
                        for match in re.finditer(pattern, line)
                        if match.start() <= before.column < match.end()
                    )
                    assert engine.state.lines[before.row] == (
                        line[: word.start()] + line[word.end() :]
                    )
            assert engine.state == step.expected
        assert engine.state.lines == lesson.goal_lines
    assert motions == {"W", "B", "e", "E"}
    assert inner_deletes == {"diw", "diW"}


def test_free_baseline_reaches_terminal_goal_at_its_last_key() -> None:
    for profile_id in PROFILE_IDS[:-1]:
        lesson = generate_edit_lesson(EditPracticeSpec(profile_id, 123, 40))
        engine = EditEngine(lesson.initial, lesson.allowed_commands)
        assert not goal_matches(lesson, engine.state)
        for index, key in enumerate(lesson.baseline):
            assert engine.submit(key).accepted
            assert goal_matches(lesson, engine.state) == (
                index == len(lesson.baseline) - 1
            )


@pytest.mark.parametrize("profile_id", ["missing", "", "editing_numbers "])
def test_unknown_profile_is_not_silently_replaced(profile_id: str) -> None:
    with pytest.raises(ValueError):
        generate_edit_lesson(EditPracticeSpec(profile_id, 0))


def test_profiles_and_spec_are_immutable() -> None:
    spec = EditPracticeSpec("editing_numbers", 0)
    profile = get_edit_profile(spec.profile_id)
    with pytest.raises(FrozenInstanceError):
        spec.seed = 1  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        profile.title = "changed"  # type: ignore[misc]


def test_rich_recipes_replay_objects_line_tools_copy_find_and_numeric_changes() -> None:
    commands: set[str] = set()
    chords: set[str] = set()
    for profile_id in (
        "editing_numbers",
        "editing_delete_word",
        "editing_append",
        "editing_compound",
    ):
        for seed in range(24):
            lesson = generate_edit_lesson(EditPracticeSpec(profile_id, seed, 40))
            engine = EditEngine(lesson.initial, lesson.allowed_commands)
            for step in lesson.guide:
                for key in step.keys:
                    outcome = engine.submit(key)
                    assert outcome.accepted
                    if outcome.command:
                        commands.add(outcome.command)
                    if key.kind == "chord":
                        chords.add(key.value)
            assert engine.state.lines == lesson.goal_lines
            assert engine.state.mode == "normal" and not engine.state.pending
    assert {"ciw", "ciW", "cw", 'ci"', "ci)", "ci]", "daw", "daW"} <= commands
    for operator in ("ci", "da"):
        for spellings in ('"', "'", "`", "()b", "[]", "{}B", "<>"):
            assert any(operator + selector in commands for selector in spellings)
    assert {"r", "o", "O", "yy", "p", "J", ">>", "<<", "C", "D", "gUiw"} <= commands
    assert {"ctrl+a", "ctrl+x"} <= chords


@pytest.mark.parametrize("command", ["bcw", "ciw", "cib", "da]"])
def test_generated_object_guides_cover_inner_change_and_around_delete(
    command: str,
) -> None:
    exercised = False
    for seed in range(48):
        lesson = generate_edit_lesson(EditPracticeSpec("editing_delete_word", seed, 40))
        engine = EditEngine(lesson.initial, lesson.allowed_commands)
        for step in lesson.guide:
            before = engine.state
            for key in step.keys:
                assert engine.submit(key).accepted
            if not "".join(key.display for key in step.keys).startswith(command):
                continue
            exercised = True
            line = before.lines[before.row]
            inserted = "".join(
                key.value for key in step.keys[len(command) :] if key.kind == "char"
            )
            if command in {"ciw", "bcw"}:
                word = next(
                    match
                    for match in re.finditer(r"\w+", line)
                    if match.start() <= before.column < match.end()
                )
                start, stop = word.span()
            elif command == "cib":
                start = line.rfind("(", 0, before.column + 1) + 1
                stop = line.index(")", before.column)
            else:
                start = line.rfind("[", 0, before.column + 1)
                stop = line.index("]", before.column) + 1
                assert inserted == ""
            assert (
                engine.state.lines[before.row] == line[:start] + inserted + line[stop:]
            )
            assert engine.state.mode == "normal" and not engine.state.pending
        assert goal_matches(lesson, engine.state)
        if exercised:
            break
    assert exercised


@pytest.mark.parametrize("document_lines", EDIT_DOCUMENT_LENGTHS)
def test_compound_problems_include_matching_search_and_substitution_across_seeds(
    document_lines: int,
) -> None:
    commands: set[str] = set()
    command_sets: list[set[str]] = []
    for seed in range(32):
        lesson = generate_edit_lesson(
            EditPracticeSpec("editing_compound", seed, document_lines)
        )
        engine = EditEngine(lesson.initial, lesson.allowed_commands)
        problem_commands: set[str] = set()
        for key in lesson.baseline:
            outcome = engine.submit(key)
            assert outcome.accepted
            if outcome.command:
                problem_commands.add(outcome.command)
        assert engine.state.lines == lesson.goal_lines
        commands.update(problem_commands)
        command_sets.append(problem_commands)
    assert "%" in commands
    assert {"/", "?", "*", "#"} & commands
    assert ":" in commands
    assert any("%" not in problem for problem in command_sets)
    assert any(":" not in problem for problem in command_sets)


def test_generated_search_recipes_cover_both_directions_and_all_occurrences() -> None:
    commands: set[str] = set()
    substitutions: set[str] = set()
    for seed in range(64):
        lesson = generate_edit_lesson(EditPracticeSpec("editing_compound", seed))
        engine = EditEngine(lesson.initial, lesson.allowed_commands)
        for key in lesson.baseline:
            before = engine.state
            outcome = engine.submit(key)
            assert outcome.accepted
            if outcome.command:
                commands.add(outcome.command)
            if outcome.command == ":":
                substitutions.add(before.command_line.rsplit("/", 1)[-1])
    assert {"/", "?", "n", "N", "*", "#"} <= commands
    assert {"", "g", "gi"} <= substitutions


@pytest.mark.parametrize("profile_id", PROFILE_IDS)
def test_generated_guides_do_not_require_large_character_or_word_counts(
    profile_id: str,
) -> None:
    for seed in range(8):
        lesson = generate_edit_lesson(EditPracticeSpec(profile_id, seed, 40))
        engine = EditEngine(lesson.initial, lesson.allowed_commands)
        for key in lesson.baseline:
            before = engine.state
            outcome = engine.submit(key)
            assert outcome.accepted
            if outcome.command == "x":
                assert int(before.pending or "1") <= 3
            if outcome.command in {"w", "W", "b", "B", "e", "E"}:
                assert int(before.pending or "1") <= 3


def test_numeric_guides_select_values_instead_of_counting_their_digits() -> None:
    widths: set[int] = set()
    commands: set[str] = set()
    for seed in range(16):
        lesson = generate_edit_lesson(EditPracticeSpec("editing_numbers", seed, 40))
        engine = EditEngine(lesson.initial, lesson.allowed_commands)
        for step in lesson.guide:
            for key in step.keys:
                before = engine.state
                outcome = engine.submit(key)
                assert outcome.accepted
                assert outcome.command not in {"x", "s"}
                if outcome.command in {"r", "ciw", "cw", "C"}:
                    commands.add(outcome.command)
                    value = before.lines[before.row][before.column :].split()[0]
                    widths.add(len(value))
                    if outcome.command == "r":
                        assert len(value) == 1
        assert goal_matches(lesson, engine.state)
    assert commands == {"r", "ciw", "cw", "C"}
    assert {1, 2, 3, 4} <= widths


def test_compound_guides_reuse_delimiters_and_preserve_neighboring_fields() -> None:
    commands: set[str] = set()
    phrase_lengths: dict[str, set[int]] = {"ct;": set(), "cf;": set()}
    find_repeats = 0
    # 구분자 포함/제외 각각에서 1·2·3단어 문구와 반복·대소문자 문맥을 재생한다.
    for seed in range(64):
        lesson = generate_edit_lesson(EditPracticeSpec("editing_compound", seed, 40))
        engine = EditEngine(lesson.initial, lesson.allowed_commands)
        for step in lesson.guide:
            before = engine.state
            step_commands: set[str] = set()
            for key in step.keys:
                outcome = engine.submit(key)
                assert outcome.accepted
                if outcome.command:
                    step_commands.add(outcome.command)
            commands.update(step_commands)
            if step_commands & {"ct;", "cf;"}:
                line = before.lines[before.row]
                phrase = line.split(" state=", 1)[1].split(";", 1)[0]
                command = "ct;" if "ct;" in step_commands else "cf;"
                phrase_lengths[command].add(len(phrase.split()))
                separator = ";" if command == "ct;" else ","
                new_value = "".join(
                    key.value for key in step.keys[3:-1] if key.kind == "char"
                ).removesuffix(",")
                expected = (
                    line[: before.column]
                    + new_value
                    + separator
                    + line.split(";", 1)[1]
                )
                assert engine.state.lines[before.row] == expected
            if step.keys[0] == KeyToken("char", ";") and "r" in step_commands:
                find_repeats += 1
                assert ";" in step_commands
                assert before.lines[before.row].count("=") == 3
                assert engine.state.lines[before.row].count("=") == 3
                assert len(before.lines[before.row]) == len(
                    engine.state.lines[before.row]
                )
        assert goal_matches(lesson, engine.state)
    assert {"ct;", "cf;", "gUiw", "guiw", "v", "U", ";", "."} <= commands
    assert phrase_lengths == {"ct;": {1, 2, 3}, "cf;": {1, 2, 3}}
    assert find_repeats >= 2


def _recipe_commands(plan: DocumentPlan, recipe: EditRecipe) -> set[str]:
    engine = EditEngine(
        EditorState(plan.lines, row=recipe.row, column=recipe.actions[0].column or 0)
    )
    commands: set[str] = set()
    for action in recipe.actions:
        for key in action.keys:
            outcome = engine.submit(key)
            assert outcome.accepted
            if outcome.command:
                commands.add(outcome.command)
    return commands


def _word_skill(commands: set[str]) -> str:
    for command in commands:
        if len(command) == 3 and command[:2] in {"ci", "da"}:
            if command[-1] not in "wW":
                return "inner" if command[1] == "i" else "around"
    if commands & {"x", "dt;"}:
        return "boundary"
    if commands & {"dw", "daw"}:
        return "word_remove"
    if commands & {"dW", "daW"}:
        return "WORD_remove"
    if commands & {"diw", "de", "ciw", "cw"}:
        return "word_change"
    assert commands & {"diW", "dE", "ciW"}
    return "WORD_change"


@pytest.mark.parametrize("document_lines", EDIT_DOCUMENT_LENGTHS)
def test_word_problems_balance_skills_instead_of_counting_aliases_as_new_skills(
    document_lines: int,
) -> None:
    expected = {
        "word_remove",
        "WORD_remove",
        "word_change",
        "WORD_change",
        "inner",
        "around",
        "boundary",
    }
    for seed in range(48):
        plan = build_document_plan("editing_delete_word", document_lines, Random(seed))
        skills = Counter(
            _word_skill(_recipe_commands(plan, recipe)) for recipe in plan.recipes
        )
        assert set(skills) == expected
        assert max(skills.values()) - min(skills.values()) <= 1
        assert skills["inner"] + skills["around"] <= 2 * len(plan.recipes) / 5


def _only_technique(name: str) -> EditTechniqueWeights:
    return EditTechniqueWeights(**{key: int(key == name) for key, _ in EDIT_TECHNIQUES})


def test_generated_word_and_object_edits_vary_the_changed_content() -> None:
    changes: dict[str, set[tuple[tuple[str, str], ...]]] = {
        command: set() for command in ("ciw", "ciW", 'ci"', "cis", "cip")
    }
    for profile, weights in (
        ("editing_delete_word", None),
        ("editing_compound", _only_technique("word")),
    ):
        for seed in range(48):
            plan = build_document_plan(profile, 40, Random(seed), weights)
            for recipe in plan.recipes:
                commands = _recipe_commands(plan, recipe)
                before = "\n".join(plan.lines[recipe.row : recipe.row + recipe.span])
                after = "\n".join(recipe.replacement)
                fragments = tuple(
                    (before[start:stop], after[new_start:new_stop])
                    for tag, start, stop, new_start, new_stop in SequenceMatcher(
                        a=before, b=after, autojunk=False
                    ).get_opcodes()
                    if tag != "equal"
                )
                for command in commands & changes.keys():
                    changes[command].add(fragments)
    # 주변 이름만 달라지는 고정 obsolete→stable 등의 과제를 검출한다.
    assert all(len(values) >= 8 for values in changes.values())


def test_generated_search_terms_vary_and_do_not_match_other_repairs() -> None:
    patterns: list[str] = []
    weights = _only_technique("search")
    for document_lines in EDIT_DOCUMENT_LENGTHS:
        for seed in range(12):
            spec = EditPracticeSpec("editing_compound", seed, document_lines, weights)
            lesson = generate_edit_lesson(spec)
            assert lesson == generate_edit_lesson(spec)
            engine = EditEngine(lesson.initial, lesson.allowed_commands)
            for key in lesson.baseline:
                before = engine.state
                outcome = engine.submit(key)
                assert outcome.accepted
                if outcome.command in {"/", "?"}:
                    pattern = before.command_line[1:]
                    patterns.append(pattern)
                    assert all(
                        pattern not in line
                        for row, line in enumerate(before.lines)
                        if row != before.row
                    )
                    assert all(pattern not in line for line in lesson.goal_lines)
            assert goal_matches(lesson, engine.state)
    assert len(set(patterns)) >= 48
    assert sum(pattern.isalpha() and pattern.islower() for pattern in patterns) > (
        len(patterns) * 0.6
    )
    assert all(not any(char.isdigit() for char in pattern) for pattern in patterns)


@pytest.mark.parametrize("technique", [name for name, _ in EDIT_TECHNIQUES])
@pytest.mark.parametrize("document_lines", EDIT_DOCUMENT_LENGTHS)
def test_exclusive_technique_settings_generate_replayable_complete_problems(
    technique: str, document_lines: int
) -> None:
    weights = _only_technique(technique)
    for seed in (0, 9):
        spec = EditPracticeSpec("editing_compound", seed, document_lines, weights)
        lesson = generate_edit_lesson(spec)
        assert lesson == generate_edit_lesson(spec)
        validate_edit_replay(lesson)
        assert lesson.practice_spec == spec
        if technique == "substitution":
            plan = build_document_plan(
                spec.profile_id, document_lines, Random(seed), weights
            )
            assert all(":" in _recipe_commands(plan, recipe) for recipe in plan.recipes)


def test_default_weighting_favors_movement_and_excludes_disabled_substitution() -> None:
    totals: Counter[str] = Counter()
    disabled = EditTechniqueWeights(substitution=0)
    for seed in range(64):
        plan = build_document_plan("editing_compound", 40, Random(seed))
        for recipe in plan.recipes:
            commands = _recipe_commands(plan, recipe)
            if ":" in commands:
                totals["substitution"] += 1
            if commands & {"%", "ct;", "cf;"} or {"f", "r"} <= commands:
                totals["movement"] += 1
        without_substitution = build_document_plan(
            "editing_compound", 40, Random(seed), disabled
        )
        assert all(
            ":" not in _recipe_commands(without_substitution, recipe)
            for recipe in without_substitution.recipes
        )
    assert totals["substitution"] > 0
    assert totals["movement"] >= 3 * totals["substitution"]


def test_weight_changes_alter_exercised_skills_without_affecting_focused_profiles() -> (
    None
):
    movement = _only_technique("movement")
    substitution = _only_technique("substitution")
    first = build_document_plan("editing_compound", 40, Random(42), movement)
    second = build_document_plan("editing_compound", 40, Random(42), substitution)
    assert first != second
    assert all(":" not in _recipe_commands(first, recipe) for recipe in first.recipes)
    assert all(":" in _recipe_commands(second, recipe) for recipe in second.recipes)
    for profile in PROFILE_IDS:
        if profile != "editing_compound":
            assert build_document_plan(profile, 24, Random(42), movement) == (
                build_document_plan(profile, 24, Random(42), substitution)
            )


def test_scaled_weights_produce_the_same_problems_for_the_same_proportions() -> None:
    low = EditTechniqueWeights(**{name: 1 for name, _ in EDIT_TECHNIQUES})
    high = EditTechniqueWeights(**{name: 3 for name, _ in EDIT_TECHNIQUES})
    for seed in range(8):
        plan = build_document_plan("editing_compound", 40, Random(seed), low)
        assert plan == (build_document_plan("editing_compound", 40, Random(seed), high))
        commands = [_recipe_commands(plan, recipe) for recipe in plan.recipes]
        assert sum(":" in group for group in commands) == 1
        assert sum(bool(group & {"/", "?", "*", "#"}) for group in commands) == 1
        assert (
            sum(bool(group & {"yy", "yiw"}) and "p" in group for group in commands) == 1
        )
        assert (
            sum(
                bool(group & {"v", "V", "ctrl+v", "gUiw", "guiw"}) for group in commands
            )
            == 1
        )
        assert (
            sum(
                bool(group & {"%", "ct;", "cf;"}) or {"f", "r"} <= group
                for group in commands
            )
            == 1
        )
