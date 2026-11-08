"""외부 샘플 없이 짧은 게임 효과음을 재현한다. Python 표준 라이브러리만 사용."""

# Standard library imports
import math
import struct
import wave
from pathlib import Path

OUTPUT = Path(__file__).resolve().parents[1] / "src/vim_key_trainer/resources/game"
SAMPLE_RATE = 44_100


def _tone(frequency: float, time: float) -> float:
    return math.sin(2 * math.pi * frequency * time)


def generate_audio(output: Path = OUTPUT) -> None:
    output.mkdir(parents=True, exist_ok=True)
    for name, duration in (("success", 0.32), ("timeout", 0.34), ("countdown", 0.055)):
        samples: list[int] = []
        for index in range(int(SAMPLE_RATE * duration)):
            time = index / SAMPLE_RATE
            envelope = min(1.0, time / 0.004) * (1 - time / duration) ** 2
            if name == "success":
                value = (
                    sum(
                        _tone(frequency, time - delay) * math.exp(-14 * (time - delay))
                        for frequency, delay in (
                            (659.25, 0.0),
                            (880.0, 0.06),
                            (1318.5, 0.12),
                        )
                        if time >= delay
                    )
                    / 2
                )
            elif name == "timeout":
                # 서로 다른 비정수 배음과 두 번의 타격으로 짧은 금속성 '챙챙'.
                value = sum(
                    sum(
                        amplitude
                        * _tone(frequency, time - delay)
                        * math.exp(-decay * (time - delay))
                        for frequency, amplitude, decay in (
                            (1174.7, 0.6, 19),
                            (1861.0, 0.36, 26),
                            (2866.0, 0.2, 34),
                            (4112.0, 0.1, 48),
                        )
                    )
                    for delay in (0.0, 0.09)
                    if time >= delay
                )
            else:
                value = _tone(1046.5, time) * math.exp(-65 * time)
            samples.append(round(14_000 * max(-1.0, min(1.0, value * envelope))))
        with wave.open(str(output / f"{name}.wav"), "wb") as stream:
            stream.setnchannels(1)
            stream.setsampwidth(2)
            stream.setframerate(SAMPLE_RATE)
            stream.writeframes(struct.pack(f"<{len(samples)}h", *samples))


if __name__ == "__main__":
    generate_audio()
