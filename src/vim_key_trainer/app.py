"""데스크톱 앱 실행 진입점."""

# Standard library imports
import sys

# Third party imports
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

# Local imports
from vim_key_trainer.ui.main_window import MainWindow
from vim_key_trainer.ui.theme import STYLESHEET


def main() -> int:
    # Qt 기본 macOS modifier 매핑을 어댑터에서 명시적으로 정규화한다.
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_DontUseNativeMenuBar)
    app = QApplication(sys.argv)
    app.setApplicationName("vim-key-trainer")
    app.setStyle("Fusion")
    app.setStyleSheet(STYLESHEET)
    window = MainWindow()
    window.show()
    return app.exec()
