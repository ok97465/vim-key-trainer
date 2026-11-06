"""패키지에 포함된 UTF-8 명령 레슨을 검증해 읽는다."""

# Standard library imports
from functools import lru_cache
from importlib.resources import files

# Local imports
from vim_key_trainer.content.schemas import CommandLessonSchema
from vim_key_trainer.domain.commands import CommandLesson


def load_command_lesson_json(data: str | bytes) -> CommandLesson:
    """표시 문자열을 다시 파싱하지 않고 명시된 논리 키 배열을 읽는다."""
    return CommandLessonSchema.model_validate_json(data).to_domain()


@lru_cache(maxsize=1)
def list_command_lessons() -> tuple[CommandLesson, ...]:
    directory = files("vim_key_trainer").joinpath("resources", "lessons", "commands")
    lessons: list[CommandLesson] = []
    for resource in sorted(directory.iterdir(), key=lambda item: item.name):
        if resource.name.endswith(".json"):
            try:
                lessons.append(
                    load_command_lesson_json(resource.read_text(encoding="utf-8"))
                )
            except ValueError as error:
                raise ValueError(
                    f"명령 레슨 {resource.name} 검증 실패: {error}"
                ) from error
    if not lessons:
        raise ValueError("명령 레슨이 없습니다.")
    ids = [lesson.id for lesson in lessons]
    if len(ids) != len(set(ids)):
        raise ValueError("명령 레슨 ID는 고유해야 합니다.")
    return tuple(lessons)


def get_command_lesson(lesson_id: str) -> CommandLesson:
    for lesson in list_command_lessons():
        if lesson.id == lesson_id:
            return lesson
    raise ValueError(f"알 수 없는 명령 레슨입니다: {lesson_id}")
