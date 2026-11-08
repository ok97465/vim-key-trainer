"""재생에 실패해도 연습을 멈추지 않는 선택형 Qt 효과음."""

from __future__ import annotations

# Standard library imports
from collections.abc import Callable
from time import monotonic_ns
from typing import TYPE_CHECKING, Literal

# Third party imports
from PySide6.QtCore import QObject, QUrl

# Local imports
from vim_key_trainer.domain.preferences import PresentationSettings
from vim_key_trainer.ui.game_resources import game_resource_path

if TYPE_CHECKING:
    # Third party imports
    from PySide6.QtMultimedia import QSoundEffect

SoundCue = Literal["success", "timeout", "countdown"]


class ChallengeAudio(QObject):
    def __init__(
        self,
        parent: QObject | None = None,
        *,
        clock_ns: Callable[[], int] = monotonic_ns,
    ) -> None:
        super().__init__(parent)
        self.settings = PresentationSettings()
        self._clock_ns = clock_ns
        self._last_played_ns: int | None = None
        self._effects: dict[SoundCue, QSoundEffect] = {}
        self._unavailable = False

    def configure(self, settings: PresentationSettings) -> None:
        self.settings = settings
        self.stop()

    def play(self, cue: SoundCue) -> None:
        enabled = {
            "success": self.settings.success_sound,
            "timeout": self.settings.failure_sound,
            "countdown": self.settings.countdown_sound,
        }[cue]
        if not enabled or not self.settings.volume or self._unavailable:
            return
        now = self._clock_ns()
        if self._last_played_ns is not None and now - self._last_played_ns < 90_000_000:
            return
        try:
            # 무음이 기본이며 필요할 때만 오디오 장치에 접근한다.
            # Third party imports
            from PySide6.QtMultimedia import QMediaDevices, QSoundEffect

            if not QMediaDevices.audioOutputs():
                self._unavailable = True
                return
            effect = self._effects.get(cue)
            if effect is None:
                effect = QSoundEffect(self)
                resource = game_resource_path(cue + ".wav")
                effect.setSource(QUrl.fromLocalFile(resource))
                effect.setLoopCount(1)
                self._effects[cue] = effect
            if effect.status() == QSoundEffect.Status.Error:
                return
            self.stop()
            effect.setVolume(float(self.settings.volume))
            effect.play()
            self._last_played_ns = now
        except (ImportError, OSError, ValueError, RuntimeError):
            self._unavailable = True

    def stop(self) -> None:
        for effect in self._effects.values():
            effect.stop()
