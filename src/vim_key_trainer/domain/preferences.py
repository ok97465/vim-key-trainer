"""판정과 독립적인 연출 설정. 기본은 무음이며 실행 중에도 바꿀 수 있다."""

# Standard library imports
import math
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class AppearanceSettings:
    mascot: Literal["classic", "cat"] = "classic"
    fuse: Literal["mint", "peach", "lilac"] = "mint"
    stamp: Literal["check", "star", "flower"] = "check"
    decorations: bool = True

    def __post_init__(self) -> None:
        if (
            self.mascot not in ("classic", "cat")
            or self.fuse not in ("mint", "peach", "lilac")
            or self.stamp not in ("check", "star", "flower")
            or type(self.decorations) is not bool
        ):
            raise ValueError("꾸미기 설정이 올바르지 않습니다.")


@dataclass(frozen=True, slots=True)
class PresentationSettings:
    effects: bool = True
    reduced_motion: bool = False
    success_sound: bool = False
    failure_sound: bool = False
    countdown_sound: bool = False
    volume: float = 0.5

    def __post_init__(self) -> None:
        if any(
            type(value) is not bool
            for value in (
                self.effects,
                self.reduced_motion,
                self.success_sound,
                self.failure_sound,
                self.countdown_sound,
            )
        ):
            raise ValueError("연출 선택은 참/거짓이어야 합니다.")
        if (
            type(self.volume) not in (float, int)
            or not math.isfinite(self.volume)
            or not 0 <= self.volume <= 1
        ):
            raise ValueError("음량은 0~1 사이여야 합니다.")
