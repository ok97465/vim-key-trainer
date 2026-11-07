"""고해상도 PNG를 Windows 배율별 이미지를 담은 ICO로 내보낸다."""

# Standard library imports
import struct
from pathlib import Path

# Third party imports
from PySide6.QtCore import QBuffer, QIODevice, Qt
from PySide6.QtGui import QImage

ICON_DIRECTORY = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "vim_key_trainer"
    / "resources"
    / "icons"
)
ICON_SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def export_icon(source: Path) -> None:
    image = QImage(str(source))
    if image.isNull() or image.width() != image.height():
        raise ValueError(f"정사각형 PNG를 읽을 수 없습니다: {source}")
    entries = bytearray()
    payloads = bytearray()
    offset = 6 + 16 * len(ICON_SIZES)
    for size in ICON_SIZES:
        frame = image.scaled(
            size,
            size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        buffer = QBuffer()
        if not buffer.open(QIODevice.OpenModeFlag.WriteOnly) or not frame.save(
            buffer, "PNG"
        ):
            raise ValueError(f"ICO 이미지를 변환할 수 없습니다: {source}")
        payload = bytes(buffer.data())
        buffer.close()
        dimension = size if size < 256 else 0
        entries.extend(
            struct.pack(
                "<BBBBHHII", dimension, dimension, 0, 0, 1, 32, len(payload), offset
            )
        )
        payloads.extend(payload)
        offset += len(payload)
    destination = source.with_suffix(".ico")
    destination.write_bytes(
        struct.pack("<HHH", 0, 1, len(ICON_SIZES)) + entries + payloads
    )
    print(destination)


if __name__ == "__main__":
    for name in ("ok97465", "vim-key-trainer"):
        export_icon(ICON_DIRECTORY / f"{name}.png")
