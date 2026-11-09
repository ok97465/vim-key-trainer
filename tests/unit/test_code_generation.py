"""코드 문제의 발췌·수정 기술과 가이드·자유 풀이 재생을 검증한다."""

# Standard library imports
import json
import re
from dataclasses import replace
from random import Random

# Third party imports
import pytest

# Local imports
from vim_key_trainer.content.code_corpus import load_code_sources
from vim_key_trainer.domain.code_edit_templates import (
    CODE_GENERATOR_VERSION,
    build_code_document_plan,
)
from vim_key_trainer.domain.edit_generator import (
    CODE_SOURCE_SELECTION_VERSION,
    generate_edit_lesson,
    get_edit_profile,
)
from vim_key_trainer.domain.edit_weights import EDIT_TECHNIQUES, EditTechniqueWeights
from vim_key_trainer.domain.editing import (
    EditPracticeSpec,
    expected_states_match,
    random_edit_document_lines,
)
from vim_key_trainer.domain.sessions import InputResult, SessionState
from vim_key_trainer.engine import EditEngine
from vim_key_trainer.services.edit_problem_factory import create_edit_problem
from vim_key_trainer.services.edit_session import EditingSession
from vim_key_trainer.services.result_codec import decode_result, encode_result


@pytest.mark.parametrize("profile_id", ["code_python", "code_cpp", "code_json"])
@pytest.mark.parametrize("seed", [0, 23])
def test_code_problem_replays_guided_and_free_and_preserves_result(
    profile_id: str,
    seed: int,
) -> None:
    count = random_edit_document_lines(profile_id, seed)
    spec = EditPracticeSpec(profile_id, seed, count)
    lesson = create_edit_problem(spec)
    assert len(lesson.initial.lines) == count
    assert len(lesson.goal_lines) == count
    assert lesson == create_edit_problem(spec)
    assert all(line.isascii() for line in lesson.initial.lines + lesson.goal_lines)
    changed = [
        row
        for row, pair in enumerate(
            zip(lesson.initial.lines, lesson.goal_lines, strict=True)
        )
        if pair[0] != pair[1]
    ]
    if profile_id == "code_json":
        assert len(changed) >= 7
        assert isinstance(json.loads("\n".join(lesson.goal_lines)), dict)
        assert lesson.code_excerpt is None
    else:
        assert len(changed) >= 15
        assert max(changed) - min(changed) > count * 0.65
        excerpt = lesson.code_excerpt
        assert excerpt is not None and lesson.goal_lines == excerpt.lines
        assert excerpt.source.language == get_edit_profile(profile_id).language
    for mode in ("guided", "free"):
        session = EditingSession(lesson, mode)
        for key in lesson.baseline:
            assert session.submit(key) == InputResult.ACCEPTED
        assert session.state == SessionState.COMPLETED
        assert session.result is not None
        assert decode_result(encode_result(session.result)) == session.result


@pytest.mark.parametrize("profile_id", ["code_python", "code_cpp"])
def test_code_lengths_are_seeded_and_at_least_three_hundred(profile_id: str) -> None:
    lengths = {random_edit_document_lines(profile_id, seed) for seed in range(32)}
    assert len(lengths) > 16
    assert min(lengths) >= 300 and max(lengths) <= 500
    assert random_edit_document_lines(profile_id, 42) == random_edit_document_lines(
        profile_id, 42
    )
    for count in (299, 501, True):
        with pytest.raises(ValueError):
            EditPracticeSpec(profile_id, 0, count)


@pytest.mark.parametrize("profile_id", ["code_python", "code_cpp", "code_json"])
def test_code_uses_objects_search_and_structure_as_actual_engine_commands(
    profile_id: str,
) -> None:
    commands: set[str] = set()
    for seed in range(24):
        count = random_edit_document_lines(profile_id, seed)
        plan = build_code_document_plan(
            profile_id, count, Random(seed), code_sources=load_code_sources()
        )
        commands.update(
            "".join(key.value for key in action.keys)
            for recipe in plan.recipes
            for action in recipe.actions
        )
    assert any(
        'ci"' in command or "ci(" in command or "ci[" in command or "ci{" in command
        for command in commands
    )
    assert any(command.startswith("/") for command in commands)
    assert ">>" in commands
    assert any(command.startswith(":s/") for command in commands)


@pytest.mark.parametrize("profile_id", ["code_python", "code_cpp", "code_json"])
@pytest.mark.parametrize("technique", [name for name, _ in EDIT_TECHNIQUES])
def test_single_technique_weight_still_produces_replayable_code(
    profile_id: str,
    technique: str,
) -> None:
    weights = EditTechniqueWeights(
        **{name: int(name == technique) for name, _ in EDIT_TECHNIQUES}
    )
    count = random_edit_document_lines(profile_id, 42)
    lesson = create_edit_problem(EditPracticeSpec(profile_id, 42, count, weights))
    assert lesson.goal_lines != lesson.initial.lines
    assert (
        lesson.practice_spec is not None
        and lesson.practice_spec.technique_weights == weights
    )


@pytest.mark.parametrize(
    "profile_id,line_count",
    [("code_python", 300), ("code_cpp", 300), ("code_json", 60)],
)
def test_search_repairs_use_varied_unambiguous_words_and_replay_both_modes(
    profile_id: str, line_count: int
) -> None:
    weights = EditTechniqueWeights(
        **{name: int(name == "search") for name, _ in EDIT_TECHNIQUES}
    )
    sources = load_code_sources()
    markers: set[str] = set()
    directions: set[str] = set()
    full_or_partial: set[bool] = set()
    for seed in range(8):
        spec = EditPracticeSpec(profile_id, seed, line_count, weights)
        lesson = generate_edit_lesson(spec, code_sources=sources)
        if seed == 0:
            assert lesson == generate_edit_lesson(spec, code_sources=sources)
        guided = EditingSession(lesson, "guided", clock_ns=lambda: 0)
        for step in lesson.guide:
            is_search = step.keys[0].value in {"/", "?"}
            if is_search:
                directions.add(step.keys[0].value)
            for key in step.keys:
                before = guided.engine.state
                confirms_search = (
                    is_search and before.command_line and key.value == "enter"
                )
                assert guided.submit(key) == InputResult.ACCEPTED
                if confirms_search:
                    state = guided.engine.state
                    pattern = before.command_line[1:]
                    assert re.fullmatch(r"[A-Za-z_]{3,}", pattern)
                    assert state.row == step.expected.row
                    assert state.lines[state.row].startswith(pattern, state.column)
                    assert (
                        sum(
                            len(re.findall(r"(?=" + re.escape(pattern) + r")", line))
                            for line in before.lines
                        )
                        == 1
                    )
                    marker = next(
                        match.group()
                        for match in re.finditer(r"[A-Za-z_]+", state.lines[state.row])
                        if match.start() <= state.column < match.end()
                    )
                    assert pattern in marker
                    assert not any(marker in line for line in lesson.goal_lines)
                    markers.add(marker)
                    full_or_partial.add(pattern == marker)
            assert expected_states_match(step.expected, guided.engine.state)
        assert guided.state == SessionState.COMPLETED
        assert guided.engine.state.lines == lesson.goal_lines
        free = EditingSession(lesson, "free", clock_ns=lambda: 0)
        for key in lesson.baseline:
            assert free.submit(key) == InputResult.ACCEPTED
        assert free.state == SessionState.COMPLETED
        assert free.engine.state.lines == lesson.goal_lines
    assert directions == {"/", "?"}
    assert full_or_partial == {False, True}
    assert len(markers) >= (30 if profile_id == "code_json" else 70)
    assert len({marker[:3] for marker in markers}) >= 25


def test_json_goals_vary_settings_and_service_groups_without_breaking_schema() -> None:
    projects: set[str] = set()
    environments: set[str] = set()
    hosts: set[str] = set()
    timeouts: set[int] = set()
    workers: set[int] = set()
    log_levels: set[str] = set()
    health_states: set[str] = set()
    service_groups: set[tuple[str, ...]] = set()
    service_names: set[str] = set()
    for seed in range(24):
        plan = build_code_document_plan("code_json", 60, Random(seed))
        document = json.loads("\n".join(plan.goal_lines))
        projects.add(document["project"])
        environments.add(document["environment"])
        hosts.add(document["server"]["host"])
        timeouts.add(document["server"]["timeout"])
        workers.add(document["server"]["workers"])
        log_levels.add(document["logging"]["level"])
        health_states.add(document["health"]["expected"])
        services = document["services"]
        names = tuple(service["name"] for service in services)
        assert len(names) == len(set(names))
        assert all(service["path"] == "/api/" + service["name"] for service in services)
        service_groups.add(names)
        service_names.update(names)
    assert len(projects) >= 20
    assert len(environments) >= 3
    assert len(hosts) >= 5
    assert len(timeouts) >= 5
    assert len(workers) >= 8
    assert len(log_levels) >= 3
    assert len(health_states) >= 3
    assert len(service_groups) == 24
    assert len(service_names) >= 12


def test_copy_recipe_restores_the_last_line_after_deleting_it() -> None:
    # 반복된 마지막 줄을 포함하는 작은 원문으로 EOF 붙이기 경계를 검증한다.
    source = next(item for item in load_code_sources() if item.source.language == "cpp")
    lines = [f"    entry_{index};" for index in range(500)]
    for index in range(1, 499, 30):
        lines[index] = lines[index - 1]
    lines[-1] = lines[0]
    repeated = replace(source, lines=tuple(lines))
    weights = EditTechniqueWeights(
        **{name: int(name == "copy") for name, _ in EDIT_TECHNIQUES}
    )
    lesson = generate_edit_lesson(
        EditPracticeSpec("code_cpp", 7, 500, weights), code_sources=(repeated,)
    )
    assert lesson.initial.lines[-1] != lesson.goal_lines[-1]
    engine = EditEngine(lesson.initial, lesson.allowed_commands)
    for step in lesson.guide:
        for key in step.keys:
            assert engine.submit(key).accepted
        assert engine.state == step.expected
    assert engine.state.lines == lesson.goal_lines


@pytest.mark.parametrize(
    "profile_id,count",
    [
        ("code_python", 300),
        ("code_python", 500),
        ("code_cpp", 300),
        ("code_cpp", 500),
        ("code_json", 60),
    ],
)
def test_supported_code_length_boundaries_generate_replayable_guides(
    profile_id: str, count: int
) -> None:
    lesson = create_edit_problem(EditPracticeSpec(profile_id, 0, count))
    assert len(lesson.initial.lines) == len(lesson.goal_lines) == count


@pytest.mark.parametrize("line_count", [300, 500])
def test_each_bundled_project_has_replayable_code_and_preserves_exact_excerpt(
    line_count: int,
) -> None:
    for source in load_code_sources():
        profile_id = "code_" + source.source.language
        lesson = generate_edit_lesson(
            EditPracticeSpec(profile_id, 19, line_count), code_sources=(source,)
        )
        assert lesson.code_excerpt is not None
        assert lesson.goal_lines == lesson.code_excerpt.lines
        assert lesson.code_excerpt.source == source.source
        session = EditingSession(lesson, "free")
        for key in lesson.baseline:
            assert session.submit(key) == InputResult.ACCEPTED
        assert session.state == SessionState.COMPLETED


def test_json_practice_remains_available_without_downloaded_sources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_corpus_load() -> None:
        raise AssertionError("JSON 연습은 다운로드 원문을 읽지 않습니다.")

    monkeypatch.setattr(
        "vim_key_trainer.services.edit_problem_factory.load_code_sources",
        unexpected_corpus_load,
    )
    spec = EditPracticeSpec("code_json", 0, 60)
    lesson = create_edit_problem(spec)
    assert lesson.content_version == 3 and lesson.generator_version == 5
    assert lesson.code_excerpt is None
    assert len(lesson.goal_lines) == 60
    assert lesson == generate_edit_lesson(spec)


def test_code_source_identity_is_included_in_lesson_signature() -> None:
    source = load_code_sources()[0]
    spec = EditPracticeSpec("code_" + source.source.language, 8, 300)
    original = generate_edit_lesson(spec, code_sources=(source,))
    changed = replace(source, source=replace(source.source, revision="f" * 40))
    revised = generate_edit_lesson(spec, code_sources=(changed,))
    assert original.goal_lines == revised.goal_lines
    assert original.signature != revised.signature


def test_sparse_numeric_source_keeps_available_real_repairs() -> None:
    source = load_code_sources()[0]
    lines = ("    return value",) * 496 + tuple(
        f"    limit = {number}" for number in (0, 20, 30, 40)
    )
    sparse = replace(source, lines=lines)
    weights = EditTechniqueWeights(
        **{name: int(name == "numbers") for name, _ in EDIT_TECHNIQUES}
    )
    lesson = generate_edit_lesson(
        EditPracticeSpec("code_" + source.source.language, 5, 500, weights),
        code_sources=(sparse,),
    )
    assert lesson.goal_lines == lines
    assert sum(a != b for a, b in zip(lesson.initial.lines, lines, strict=True)) == 4
    session = EditingSession(lesson, "free")
    for token in lesson.baseline:
        assert session.submit(token) == InputResult.ACCEPTED
    assert session.state == SessionState.COMPLETED


def test_source_without_selected_technique_explains_how_to_continue() -> None:
    source = load_code_sources()[0]
    plain = replace(source, lines=("    return value",) * 500)
    weights = EditTechniqueWeights(
        **{name: int(name == "numbers") for name, _ in EDIT_TECHNIQUES}
    )
    with pytest.raises(ValueError, match="다른 문제.*기술 비중"):
        generate_edit_lesson(
            EditPracticeSpec("code_" + source.source.language, 5, 500, weights),
            code_sources=(plain,),
        )


@pytest.mark.parametrize("language", ["python", "cpp"])
@pytest.mark.parametrize("seed", [5, 21])
def test_selected_code_source_replays_and_survives_catalog_changes(
    language: str, seed: int
) -> None:
    sources = load_code_sources()
    source = next(item for item in sources if item.source.language == language)
    spec = EditPracticeSpec(
        "code_" + language, seed, 300, code_source_id=source.source.id
    )
    lesson = generate_edit_lesson(spec, code_sources=sources)
    assert lesson == generate_edit_lesson(spec, code_sources=(source,))
    assert lesson.practice_spec == spec
    assert lesson.generator_version == CODE_SOURCE_SELECTION_VERSION
    assert lesson.code_excerpt is not None
    assert lesson.code_excerpt.source == source.source
    for mode in ("guided", "free"):
        session = EditingSession(lesson, mode)
        for key in lesson.baseline:
            assert session.submit(key) == InputResult.ACCEPTED
        assert session.state == SessionState.COMPLETED


@pytest.mark.parametrize("language", ["python", "cpp"])
def test_fixed_and_random_source_conditions_have_distinct_signatures(
    language: str,
) -> None:
    source = next(
        item for item in load_code_sources() if item.source.language == language
    )
    spec = EditPracticeSpec("code_" + language, 17, 300)
    random_lesson = generate_edit_lesson(spec, code_sources=(source,))
    selected_lesson = generate_edit_lesson(
        replace(spec, code_source_id=source.source.id), code_sources=(source,)
    )
    assert random_lesson.goal_lines == selected_lesson.goal_lines
    assert random_lesson.guide == selected_lesson.guide
    assert random_lesson.generator_version == CODE_GENERATOR_VERSION
    assert selected_lesson.generator_version == CODE_SOURCE_SELECTION_VERSION
    assert random_lesson.signature != selected_lesson.signature
    assert (
        random_lesson.signature
        != replace(selected_lesson, generator_version=CODE_GENERATOR_VERSION).signature
    )


@pytest.mark.parametrize("code_source_id", ["", "../source", "UPPER", "source-id", 1])
def test_invalid_selected_source_ids_are_rejected(code_source_id: object) -> None:
    with pytest.raises(ValueError, match="코드 원문 ID"):
        EditPracticeSpec("code_python", 1, 300, code_source_id=code_source_id)


@pytest.mark.parametrize(
    "profile_id,line_count", [("editing_numbers", 24), ("code_json", 60)]
)
def test_source_selection_is_only_available_for_downloaded_code(
    profile_id: str, line_count: int
) -> None:
    with pytest.raises(ValueError, match=r"Python.*C\+\+"):
        EditPracticeSpec(profile_id, 1, line_count, code_source_id="source")


@pytest.mark.parametrize("language", ["python", "cpp"])
def test_missing_or_wrong_language_source_is_rejected(language: str) -> None:
    sources = load_code_sources()
    other = next(item for item in sources if item.source.language != language)
    with pytest.raises(ValueError, match="찾을 수 없습니다"):
        generate_edit_lesson(
            EditPracticeSpec("code_" + language, 1, 300, code_source_id="missing"),
            code_sources=sources,
        )
    with pytest.raises(ValueError, match="언어.*다릅니다"):
        generate_edit_lesson(
            EditPracticeSpec(
                "code_" + language, 1, 300, code_source_id=other.source.id
            ),
            code_sources=sources,
        )


def test_guide_restores_a_damaged_copy_source_and_its_targets() -> None:
    source = next(item for item in load_code_sources() if item.source.language == "cpp")
    # 숫자 수정은 복사 원본·대상에만 가능하게 해 두 수정을 함께 선택한다.
    # 나머지 행은 서로 달라 별도의 복사 후보가 생기지 않는다.
    middle = tuple(
        f"    return value_{chr(97 + index // 26)}{chr(97 + index % 26)};"
        for index in range(498)
    )
    source = replace(source, lines=("    limit = 40;",) + middle + ("    limit = 40;",))
    weights = EditTechniqueWeights(
        **{name: int(name in {"numbers", "copy"}) for name, _ in EDIT_TECHNIQUES}
    )
    lesson = generate_edit_lesson(
        EditPracticeSpec("code_cpp", 0, 500, weights), code_sources=(source,)
    )
    assert lesson.initial.lines[0] == "    limit = 39;"
    assert lesson.goal_lines == source.lines
    session = EditingSession(lesson, "guided", clock_ns=lambda: 0)
    copied_targets: list[int] = []
    for step in lesson.guide:
        command = "".join(key.value for key in step.keys)
        match = re.fullmatch(r'(\d+)G"ayy(\d+)Gdd"a[pP]', command)
        if match is not None:
            source_row, target_row = (int(value) - 1 for value in match.groups())
            assert source_row == 0
            assert session.engine.state.lines[source_row] == source.lines[source_row]
            assert session.engine.state.lines[target_row] != source.lines[target_row]
            copied_targets.append(target_row)
        for key in step.keys:
            assert session.submit(key) == InputResult.ACCEPTED
        assert expected_states_match(step.expected, session.engine.state)
    assert copied_targets
    assert session.engine.state.lines == source.lines
    assert session.engine.state.mode == "normal"
    assert not session.engine.state.pending
    assert session.state == SessionState.COMPLETED
