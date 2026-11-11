"""외부 샘플 없이 칼질·파편·박동을 합성한다. 표준 라이브러리만 사용한다."""

# Standard library imports
import math
import random
import struct
import wave
from pathlib import Path

OUTPUT = Path(__file__).resolve().parents[1] / "src/vim_key_trainer/resources/game"
SAMPLE_RATE = 44_100
SUCCESS_STYLES = ("precise", "heavy", "soft")


def _tone(frequency: float, time: float) -> float:
    return math.sin(math.tau * frequency * time)


def _strike(time: float, noise: float, style: str, level: int, variation: int) -> float:
    """공기 절단, 날의 접촉, 낮은 충격, 잔향을 서로 다른 포락선으로 잇는다."""
    pitch = (1.0, 1.07, 1.16, 1.27)[level] * (0.98, 1.01, 1.035, 0.995)[variation]
    weight = {"precise": 0.65, "heavy": 1.0, "soft": 0.42}[style]
    value = 0.0
    if 0 <= time < 0.095:
        value += noise * math.sin(math.pi * time / 0.095) ** 2 * 0.24
    contact = time - 0.068
    if contact >= 0:
        value += noise * math.exp(-62 * contact) * 0.48
        value += _tone(2600 * pitch, contact) * math.exp(-72 * contact) * 0.19
    impact = time - 0.082
    if impact >= 0:
        value += (
            math.sin(math.tau * (125 * impact - 55 * impact * impact))
            * math.exp(-20 * impact)
            * weight
        )
    tail = time - 0.105
    if tail >= 0:
        # 높은 파편음 뒤에도 따뜻한 낮은 공명을 남긴다.
        value += sum(
            _tone(frequency * pitch, tail) * amplitude * math.exp(-decay * tail)
            for frequency, amplitude, decay in (
                (523.25, 0.12, 5.5),
                (783.99, 0.09, 6.5),
                (1567.98, 0.045, 8),
            )
        )
    for delay in (0.15, 0.225, 0.32, 0.43, 0.55):
        piece = time - delay - variation * 0.003
        if piece >= 0:
            value += (
                noise * 0.07 + _tone((1850 + delay * 1300) * pitch, piece) * 0.035
            ) * math.exp(-38 * piece)
    return value


def _sample(name: str, time: float, noise: float) -> float:
    if name == "success" or name.startswith("success-"):
        if name == "success":
            return _strike(time, noise, "precise", 0, 0)
        _, style, level, variation = name.split("-")
        return _strike(time, noise, style, int(level), int(variation))
    if name == "finale":
        value = _strike(time, noise, "heavy", 3, 1)
        for frequency, delay in (
            (523.25, 0.13),
            (659.25, 0.25),
            (783.99, 0.38),
            (1046.5, 0.56),
            (1318.5, 0.76),
        ):
            note = time - delay
            if note >= 0:
                value += (
                    (_tone(frequency, note) + 0.22 * _tone(frequency * 2, note))
                    * min(1.0, note / 0.012)
                    * math.exp(-4.5 * note)
                    * 0.2
                )
        return value
    if name == "timeout":
        value = 0.0
        for delay in (0.0, 0.095):
            impact = time - delay
            if impact >= 0:
                value += sum(
                    amplitude * _tone(frequency, impact) * math.exp(-decay * impact)
                    for frequency, amplitude, decay in (
                        (146, 0.5, 12),
                        (1174.7, 0.28, 18),
                        (1861, 0.15, 25),
                        (2866, 0.08, 34),
                    )
                )
                value += noise * math.exp(-40 * impact) * 0.22
        return value
    if name == "expired":
        # 작은 한숨처럼 내려가는 공명과 부드러운 세 음. 금속 타격은 넣지 않는다.
        value = (
            math.sin(math.tau * (235 * time - 44 * time * time))
            * min(1.0, time / 0.035)
            * math.exp(-4.8 * time)
            * 0.38
        )
        for frequency, delay in ((392.0, 0.0), (329.63, 0.17), (261.63, 0.36)):
            note = time - delay
            if note >= 0:
                value += (
                    (_tone(frequency, note) + _tone(frequency * 2, note) * 0.08)
                    * min(1.0, note / 0.025)
                    * math.exp(-7 * note)
                    * 0.17
                )
        return value + noise * math.sin(math.pi * min(1.0, time / 0.8)) ** 2 * 0.012
    if name == "countdown":
        return _tone(1046.5, time) * math.exp(-58 * time) * 0.35
    level = int(name.rsplit("-", 1)[1])
    value = 0.0
    for delay, amplitude in ((0.0, 0.48), (0.09, 0.3)):
        beat = time - delay
        if beat >= 0:
            value += _tone(67 + level * 13, beat) * math.exp(-36 * beat) * amplitude
    # 심지의 지직거림은 박동 뒤까지 이어지되 성공음을 덮지 않는다.
    value += noise * math.exp(-12 * time) * (0.035 + level * 0.015)
    return value


def generate_audio(output: Path = OUTPUT) -> None:
    output.mkdir(parents=True, exist_ok=True)
    durations = {
        "success": 0.78,
        "timeout": 0.65,
        "expired": 0.92,
        "countdown": 0.09,
        "finale": 1.55,
        **{f"pressure-{level}": 0.27 for level in range(3)},
        **{
            f"success-{style}-{level}-{variation}": 0.78
            for style in SUCCESS_STYLES
            for level in range(4)
            for variation in range(4)
        },
    }
    for name, duration in durations.items():
        source = random.Random(413)
        samples: list[int] = []
        previous_noise = 0.0
        for index in range(int(SAMPLE_RATE * duration)):
            time = index / SAMPLE_RATE
            raw_noise = source.uniform(-1.0, 1.0)
            noise = (raw_noise - previous_noise) / 2
            previous_noise = raw_noise
            # 모든 큐의 양 끝을 부드럽게 닫아 음원 경계의 클릭을 막는다.
            envelope = min(1.0, time / 0.003, (duration - time) / 0.025)
            value = math.tanh(_sample(name, time, noise)) * envelope
            samples.append(round(24_000 * value))
        with wave.open(str(output / f"{name}.wav"), "wb") as stream:
            stream.setnchannels(1)
            stream.setsampwidth(2)
            stream.setframerate(SAMPLE_RATE)
            stream.writeframes(struct.pack(f"<{len(samples)}h", *samples))


if __name__ == "__main__":
    generate_audio()
