"""실제 장치 없이 잔향 보존·음성 상한·박동의 독립적인 수명을 검증한다."""

# Standard library imports
import sys
from time import monotonic_ns
from types import SimpleNamespace

# Third party imports
import pytest
from PySide6.QtCore import QTimer, QUrl
from PySide6.QtWidgets import QWidget
from pytestqt.qtbot import QtBot

# Local imports
from vim_key_trainer.domain.preferences import PresentationSettings
from vim_key_trainer.ui.challenge_audio import ChallengeAudio


class FakeSoundEffect:
    Status = SimpleNamespace(Error="error")

    def __init__(self, parent: object) -> None:
        self.source = ""
        self.playing = False
        self.play_count = 0
        self.stop_count = 0
        self.volume = 0.0

    def setSource(self, source: QUrl) -> None:
        self.source = source.toLocalFile()

    def setLoopCount(self, count: int) -> None:
        assert count == 1

    def setVolume(self, volume: float) -> None:
        self.volume = volume

    def status(self) -> str:
        return "ready"

    def isPlaying(self) -> bool:
        return self.playing

    def play(self) -> None:
        self.playing = True
        self.play_count += 1

    def stop(self) -> None:
        self.playing = False
        self.stop_count += 1


@pytest.fixture
def backend(monkeypatch: pytest.MonkeyPatch) -> list[FakeSoundEffect]:
    effects: list[FakeSoundEffect] = []

    def create(parent: object) -> FakeSoundEffect:
        effect = FakeSoundEffect(parent)
        effects.append(effect)
        return effect

    # 생성자에도 실제 QSoundEffect와 같은 상태 상수를 제공한다.
    create.Status = FakeSoundEffect.Status  # type: ignore[attr-defined]
    monkeypatch.setitem(
        sys.modules,
        "PySide6.QtMultimedia",
        SimpleNamespace(
            QMediaDevices=SimpleNamespace(audioOutputs=lambda: [object()]),
            QSoundEffect=create,
        ),
    )
    return effects


def test_success_tails_overlap_with_bounded_voices(
    qtbot: QtBot, backend: list[FakeSoundEffect]
) -> None:
    host = QWidget()
    qtbot.addWidget(host)
    now = 0
    audio = ChallengeAudio(host, clock_ns=lambda: now)
    audio.configure(PresentationSettings(success_sound=True, volume=0.4))
    for index in range(3):
        now = index * 100_000_000
        audio.play("success", technique="delete", chain=5)
    assert len(backend) == 3
    assert all(effect.playing and effect.stop_count == 0 for effect in backend)
    assert all(effect.volume == 0.4 for effect in backend)
    assert len({effect.source for effect in backend}) == 3
    assert all("success-heavy-2-" in effect.source for effect in backend)

    now += 100_000_000
    audio.play("success", technique="word", chain=10)
    assert sum(effect.playing for effect in backend) == 3
    assert backend[0].stop_count == 1
    assert backend[1].stop_count == backend[2].stop_count == 0
    assert "success-soft-3-" in backend[-1].source


def test_countdown_cannot_interrupt_or_suppress_success_and_finale(
    qtbot: QtBot, backend: list[FakeSoundEffect]
) -> None:
    host = QWidget()
    qtbot.addWidget(host)
    now = 0
    audio = ChallengeAudio(host, clock_ns=lambda: now)
    audio.configure(PresentationSettings(success_sound=True, countdown_sound=True))
    audio.set_pressure(2.8, 0.08, True)
    assert audio._pressure_timer.isActive()
    now += 1_000_000
    audio.play("success", close_call=True)
    assert backend[-1].playing
    assert "success-precise-1-" in backend[-1].source
    now += 100_000_000
    audio.play("countdown")
    assert len(backend) == 2
    assert backend[-1].stop_count == 0
    audio.play("finale")
    assert not audio._pressure_timer.isActive()
    assert backend[-1].source.endswith("finale.wav")
    assert sum(effect.playing for effect in backend) == 1
    audio.stop()
    assert not any(effect.playing for effect in backend)


def test_repeated_view_refresh_does_not_postpone_heartbeat(
    qtbot: QtBot, backend: list[FakeSoundEffect]
) -> None:
    host = QWidget()
    qtbot.addWidget(host)
    audio = ChallengeAudio(host, clock_ns=monotonic_ns)
    audio.configure(PresentationSettings(countdown_sound=True))
    audio.set_pressure(2.5, 0.08, True)
    refresh = QTimer(host)
    refresh.setInterval(10)
    refresh.timeout.connect(lambda: audio.set_pressure(2.5, 0.08, True))
    refresh.start()
    qtbot.waitUntil(
        lambda: sum(effect.play_count for effect in backend) >= 2, timeout=700
    )
    refresh.stop()
    audio.set_pressure(None, 1.0, False)
    assert not audio._pressure_timer.isActive()
    assert not any(effect.playing for effect in backend)


def test_silent_settings_never_open_backend_and_pause_cleans_pressure(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    host = QWidget()
    qtbot.addWidget(host)
    monkeypatch.setitem(sys.modules, "PySide6.QtMultimedia", None)
    audio = ChallengeAudio(host)
    audio.set_pressure(1, 0.05, True)
    audio.play("success")
    audio.play("finale")
    assert not audio._unavailable
    assert not audio._pressure_timer.isActive()
    assert not audio._effects


def test_gentle_free_timeout_uses_failure_sound_setting(
    qtbot: QtBot, backend: list[FakeSoundEffect]
) -> None:
    host = QWidget()
    qtbot.addWidget(host)
    audio = ChallengeAudio(host)
    audio.configure(PresentationSettings(success_sound=True))
    audio.play("expired")
    assert not backend
    audio.configure(PresentationSettings(failure_sound=True, volume=0.3))
    audio.play("expired")
    assert len(backend) == 1
    assert backend[0].source.endswith("expired.wav")
    assert backend[0].volume == 0.3
    audio.stop()
    assert not backend[0].playing
