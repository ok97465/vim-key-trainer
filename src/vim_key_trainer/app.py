"""데스크톱 앱 실행 진입점."""

# Standard library imports
import sys

# Third party imports
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

# Local imports
from vim_key_trainer.services.application_storage import open_application_repository
from vim_key_trainer.services.settings_repository import (
    SettingsRepository,
    default_settings_path,
)
from vim_key_trainer.services.sqlite_repository import SqliteResultRepository
from vim_key_trainer.ui.branding import (
    APP_NAME,
    AUTHOR,
    load_icon,
    set_windows_app_id,
)
from vim_key_trainer.ui.main_window import MainWindow
from vim_key_trainer.ui.theme import STYLESHEET


def main() -> int:
    set_windows_app_id()
    # Qt 기본 macOS modifier 매핑을 어댑터에서 명시적으로 정규화한다.
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_DontUseNativeMenuBar)
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setOrganizationName(AUTHOR)
    app.setWindowIcon(load_icon("vim-key-trainer"))
    app.setStyle("Fusion")
    app.setStyleSheet(STYLESHEET)
    repository, warning = open_application_repository()
    window = MainWindow(
        repository, settings_repository=SettingsRepository(default_settings_path())
    )
    if warning:
        window.show_storage_warning(warning)
    window.show()
    try:
        return app.exec()
    finally:
        if isinstance(repository, SqliteResultRepository):
            repository.retry_pending()
            repository.close()
