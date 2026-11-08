"""복사 원본도 손상된 코드 문제를 가이드대로 복원하는지 검증한다."""

# Standard library imports
import re
from dataclasses import replace

# Local imports
from vim_key_trainer.content.code_corpus import load_code_sources
from vim_key_trainer.domain.edit_generator import generate_edit_lesson
from vim_key_trainer.domain.edit_weights import EDIT_TECHNIQUES, EditTechniqueWeights
from vim_key_trainer.domain.editing import EditPracticeSpec, expected_states_match
from vim_key_trainer.domain.sessions import InputResult, SessionState
from vim_key_trainer.services.edit_session import EditingSession


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
