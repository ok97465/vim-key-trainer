"""입력과 독립적으로 겹쳐 재생하는 선택형 Qt 칼질·박동 효과음."""

from __future__ import annotations

# Standard library imports
from collections.abc import Callable
from time import monotonic_ns
from typing import TYPE_CHECKING, Literal

# Third party imports
from PySide6.QtCore import QObject, QTimer, QUrl

# Local imports
from vim_key_trainer.domain.preferences import PresentationSettings
from vim_key_trainer.ui.game_resources import game_resource_path

if TYPE_CHECKING:
    # Third party imports
    from PySide6.QtMultimedia import QSoundEffect

SoundCue = Literal["success", "timeout", "countdown", "finale", "expired"]
_MAX_VOICES = 3


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
        self._effects: dict[str, QSoundEffect] = {}
        self._playing: dict[str, tuple[int, int]] = {}
        self._last_started: dict[int, int] = {}
        self._success_serial = 0
        self._unavailable = False
        self._pressure_level = 0
        self._pressure_timer = QTimer(self)
        self._pressure_timer.timeout.connect(self._pulse)

    def configure(self, settings: PresentationSettings) -> None:
        self.stop()
        self.settings = settings

    def play(
        self,
        cue: SoundCue,
        *,
        chain: int = 0,
        technique: str = "precise",
        close_call: bool = False,
    ) -> None:
        enabled = {
            "success": self.settings.success_sound,
            "timeout": self.settings.failure_sound,
            "expired": self.settings.failure_sound,
            "countdown": self.settings.countdown_sound,
            "finale": self.settings.success_sound,
        }[cue]
        if not enabled:
            return
        priority = {
            "countdown": 0,
            "success": 2,
            "timeout": 3,
            "expired": 3,
            "finale": 4,
        }[cue]
        resource: str = cue
        if cue == "success":
            style = (
                "heavy"
                if technique == "delete"
                else "soft"
                if technique in {"word", "insert"}
                else "precise"
            )
            level = 3 if chain >= 10 else 2 if chain >= 5 else 1 if chain >= 3 else 0
            if close_call:
                level = min(3, level + 1)
            variation = self._success_serial % 4
            self._success_serial += 1
            resource = f"success-{style}-{level}-{variation}"
        if cue == "finale":
            self._pressure_timer.stop()
        self._play_resource(resource, priority)

    def set_pressure(self, remaining: float | None, ratio: float, active: bool) -> None:
        """실제 남은 시간은 읽기만 하며 박동 간격만 바꾼다."""
        enabled = (
            active
            and self.settings.countdown_sound
            and self.settings.volume > 0
            and not self._unavailable
            and remaining is not None
            and remaining > 0
            and (remaining <= 8 or ratio <= 0.25)
        )
        if not enabled or remaining is None:
            self._stop_pressure()
            return
        self._pressure_level = (
            2
            if remaining <= 3 or ratio <= 0.1
            else 1
            if remaining <= 5 or ratio <= 0.17
            else 0
        )
        interval = (900, 560, 280)[self._pressure_level]
        if self._pressure_timer.interval() != interval:
            self._pressure_timer.setInterval(interval)
        if not self._pressure_timer.isActive():
            self._pressure_timer.start()
            self._pulse()

    def _pulse(self) -> None:
        if self.settings.countdown_sound:
            self._play_resource(f"pressure-{self._pressure_level}", 0)

    def _play_resource(self, resource: str, priority: int) -> None:
        if not self.settings.volume or self._unavailable:
            return
        now = self._clock_ns()
        last = self._last_started.get(priority)
        if last is not None and now - last < 70_000_000 and priority < 4:
            return
        try:
            # 무음이 기본이며 필요할 때만 오디오 장치에 접근한다.
            # Third party imports
            from PySide6.QtMultimedia import QMediaDevices, QSoundEffect

            if not QMediaDevices.audioOutputs():
                self._unavailable = True
                self._pressure_timer.stop()
                return
            self._playing = {
                name: voice
                for name, voice in self._playing.items()
                if self._effects[name].isPlaying()
            }
            # 박동은 성공의 파편·잔향을 덮거나 끊지 않는다.
            if priority == 0 and any(voice[0] >= 2 for voice in self._playing.values()):
                return
            effect = self._effects.get(resource)
            if effect is None:
                effect = QSoundEffect(self)
                effect.setSource(
                    QUrl.fromLocalFile(game_resource_path(resource + ".wav"))
                )
                effect.setLoopCount(1)
                self._effects[resource] = effect
            if effect.status() == QSoundEffect.Status.Error:
                return
            if priority == 4:
                self._stop_voices()
            elif resource not in self._playing and len(self._playing) >= _MAX_VOICES:
                victim = min(self._playing, key=lambda name: self._playing[name])
                if self._playing[victim][0] > priority:
                    return
                self._effects[victim].stop()
                del self._playing[victim]
            # 같은 음원만 재시작하고 다른 음원의 잔향은 상한 안에서 보존한다.
            if resource in self._playing:
                effect.stop()
            effect.setVolume(
                float(self.settings.volume) * (0.65 if priority == 0 else 1)
            )
            effect.play()
            self._playing[resource] = priority, now
            self._last_started[priority] = now
        except (ImportError, OSError, ValueError, RuntimeError):
            self._unavailable = True
            self._pressure_timer.stop()

    def _stop_pressure(self) -> None:
        self._pressure_timer.stop()
        for resource in tuple(self._playing):
            if resource.startswith("pressure-"):
                self._effects[resource].stop()
                del self._playing[resource]

    def _stop_voices(self) -> None:
        for effect in self._effects.values():
            effect.stop()
        self._playing.clear()

    def stop(self) -> None:
        self._pressure_timer.stop()
        self._stop_voices()
        self._last_started.clear()
