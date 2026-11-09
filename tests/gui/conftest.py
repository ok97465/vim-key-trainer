"""연습 창의 공통 생성·활성화·정리를 관리한다."""

# Standard library imports
from collections.abc import Iterator

# Third party imports
import pytest
from pytestqt.qtbot import QtBot

# Local imports
from vim_key_trainer.ui.main_window import MainWindow


@pytest.fixture
def window(qtbot: QtBot) -> Iterator[MainWindow]:
    widget = MainWindow()
    qtbot.addWidget(widget)
    widget.show()
    widget.activateWindow()
    qtbot.waitUntil(widget.isActiveWindow)
    yield widget
    widget.close()
