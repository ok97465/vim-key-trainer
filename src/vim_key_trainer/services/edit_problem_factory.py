"""문제 생성과 재생 검증을 묶는 Qt 독립 서비스 경계."""

# Local imports
from vim_key_trainer.content.edit_loader import validate_edit_replay
from vim_key_trainer.domain.edit_generator import (
    EDIT_GENERATOR_VERSION,
    generate_edit_lesson,
    get_edit_profile,
)
from vim_key_trainer.domain.editing import EditLesson, EditPracticeSpec


def create_edit_problem(spec: EditPracticeSpec) -> EditLesson:
    """요청 조건과 가이드·기준 풀이가 일치하는 문제만 세션에 전달한다."""
    profile = get_edit_profile(spec.profile_id)
    lesson = generate_edit_lesson(spec)
    if (
        lesson.id != spec.profile_id
        or lesson.practice_spec != spec
        or lesson.generator_version != EDIT_GENERATOR_VERSION
        or lesson.content_version != profile.content_version
        or len(lesson.initial.lines) != spec.document_lines
    ):
        raise ValueError("생성된 편집 문제의 재현 조건이 요청과 다릅니다.")
    validate_edit_replay(lesson)
    return lesson
