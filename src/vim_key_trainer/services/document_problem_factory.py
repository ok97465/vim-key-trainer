"""실제 문서를 고르고 손상·복원 키 재생을 검증하는 서비스 경계."""

# Local imports
from vim_key_trainer.content.document_missions import get_document_mission
from vim_key_trainer.content.edit_loader import validate_edit_replay
from vim_key_trainer.domain.document_corruption import (
    DOCUMENT_GENERATOR_VERSION,
    DocumentCorruptionPlan,
    generate_document_problem,
)
from vim_key_trainer.domain.document_missions import DocumentPracticeSpec
from vim_key_trainer.domain.editing import EditLesson
from vim_key_trainer.engine import EditEngine, EditorState


def create_document_corruption(spec: DocumentPracticeSpec) -> DocumentCorruptionPlan:
    mission = get_document_mission(spec.mission_id)
    plan = generate_document_problem(mission, spec)
    lesson = plan.lesson
    if (
        lesson.id != mission.id
        or lesson.content_version != mission.content_version
        or lesson.document_spec != spec
        or lesson.generator_version != DOCUMENT_GENERATOR_VERSION
        or lesson.goal_lines != mission.goal_lines
        or len(plan.operations) != spec.change_count
    ):
        raise ValueError("문서 손상 문제의 원문·재현 조건이 요청과 다릅니다.")
    engine = EditEngine(EditorState(mission.goal_lines))
    for token in plan.corruption_tokens:
        if not engine.submit(token).accepted:
            raise ValueError("문서 손상 입력을 재생할 수 없습니다.")
    if engine.state != lesson.initial:
        raise ValueError("손상 입력과 초기 문서가 일치하지 않습니다.")
    validate_edit_replay(lesson)
    return plan


def create_random_document_problem(spec: DocumentPracticeSpec) -> EditLesson:
    return create_document_corruption(spec).lesson
