"""앱에 포함된 그림·음원의 패키지 경로를 제공한다."""

# Standard library imports
from importlib.resources import files

_ALLOWED_ASSETS = frozenset(
    {
        "bomb-mascot.png",
        "cat-mascot.png",
        "library-workshop.png",
        "success.wav",
        "timeout.wav",
        "expired.wav",
        "countdown.wav",
        "finale.wav",
        *(f"pressure-{level}.wav" for level in range(3)),
        *(
            f"success-{style}-{level}-{variation}.wav"
            for style in ("precise", "heavy", "soft")
            for level in range(4)
            for variation in range(4)
        ),
    }
)


def game_resource_path(name: str) -> str:
    if name not in _ALLOWED_ASSETS:
        raise ValueError("등록되지 않은 게임 리소스입니다.")
    return str(files("vim_key_trainer").joinpath("resources", "game", name))
