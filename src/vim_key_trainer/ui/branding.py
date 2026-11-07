"""앱 이름·작성자와 패키지에 포함된 브랜딩 이미지."""

# Standard library imports
import ctypes
import sys
from importlib.resources import files
from typing import Literal

# Third party imports
from PySide6.QtGui import QIcon, QPixmap

APP_NAME = "vim-key-trainer"
AUTHOR = "ok97465"
WINDOW_TITLE = f"매일 조금씩, 손에 익는 Vim key 연습기 by {AUTHOR}"
WINDOWS_APP_ID = f"{AUTHOR}.{APP_NAME}"


def load_icon(name: Literal["ok97465", "vim-key-trainer"]) -> QIcon:
    """설치 위치나 현재 작업 폴더와 무관하게 PNG를 메모리로 읽는다."""
    data = (
        files("vim_key_trainer")
        .joinpath("resources", "icons", f"{name}.png")
        .read_bytes()
    )
    pixmap = QPixmap()
    if not pixmap.loadFromData(data, "PNG"):
        raise ValueError(f"아이콘 이미지를 읽을 수 없습니다: {name}")
    return QIcon(pixmap)


def set_windows_app_id() -> None:
    """Windows 작업 표시줄에서 Python 대신 앱 고유 ID로 묶는다."""
    if sys.platform == "win32":
        set_app_id = ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID
        set_app_id.argtypes = [ctypes.c_wchar_p]
        set_app_id.restype = ctypes.c_long
        set_app_id(WINDOWS_APP_ID)
