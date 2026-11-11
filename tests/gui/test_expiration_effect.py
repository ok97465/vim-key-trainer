"""시간 종료의 전체 창 알림이 입력과 본문 가독성을 보존하는지 검증한다."""

# Third party imports
from PySide6.QtCore import QAbstractAnimation, QRect, Qt
from PySide6.QtWidgets import (
    QApplication,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from pytestqt.qtbot import QtBot

# Local imports
from vim_key_trainer.domain.preferences import PresentationSettings
from vim_key_trainer.ui.widgets.expiration_effect import ExpirationEffect


def _surface(
    qtbot: QtBot,
) -> tuple[QWidget, QLineEdit, QPushButton, ExpirationEffect]:
    host = QWidget()
    qtbot.addWidget(host)
    host.setStyleSheet("background: #17222c; color: #e8edf3;")
    outer = QVBoxLayout(host)
    panel = QWidget()
    layout = QVBoxLayout(panel)
    editor = QLineEdit()
    editor.setText("before")
    layout.addWidget(editor)
    button = QPushButton("계속 연습")
    layout.addWidget(button)
    outer.addWidget(panel)
    outer.addStretch()
    host.resize(800, 600)
    host.show()
    host.activateWindow()
    editor.setFocus()
    qtbot.waitUntil(editor.hasFocus)
    effect = ExpirationEffect(panel)
    return host, editor, button, effect


def test_expiration_covers_the_whole_window_without_intercepting_input(
    qtbot: QtBot,
) -> None:
    host, editor, button, effect = _surface(qtbot)
    panel = effect.parentWidget()
    assert panel is not None and panel.height() < host.height()
    effect.trigger(host)
    assert effect.isVisible()
    assert effect.parentWidget() is host
    assert effect.geometry() == host.rect()
    assert editor.hasFocus()
    qtbot.keyClicks(editor, " after")
    assert editor.text() == "before after"
    assert editor.hasFocus()
    assert QApplication.widgetAt(button.mapToGlobal(button.rect().center())) is button
    with qtbot.waitSignal(button.clicked):
        qtbot.mouseClick(button, Qt.MouseButton.LeftButton)
    host.resize(960, 640)
    qtbot.waitUntil(lambda: effect.geometry() == host.rect())
    effect.stop_effects()
    assert effect.isHidden()
    assert effect.animation.state() == QAbstractAnimation.State.Stopped
    assert not effect.static_timer.isActive()


def test_single_edge_glow_leaves_the_document_center_unchanged(qtbot: QtBot) -> None:
    host, _, _, effect = _surface(qtbot)
    before = host.grab().toImage()
    effect.trigger(host)
    effect.animation.pause()
    effect.animation.setCurrentTime(300)
    after = host.grab().toImage()
    scale = after.devicePixelRatio()
    center = QRect(
        round(host.width() * 0.35 * scale),
        round(host.height() * 0.4 * scale),
        round(host.width() * 0.3 * scale),
        round(host.height() * 0.3 * scale),
    )
    edge = QRect(0, round(host.height() * 0.35 * scale), round(18 * scale), 100)
    assert before.copy(center) == after.copy(center)
    assert before.copy(edge) != after.copy(edge)
    effect.animation.setCurrentTime(effect.animation.duration())
    assert effect.isHidden()
    assert effect.animation.state() == QAbstractAnimation.State.Stopped


def test_reduced_motion_keeps_a_static_notice_and_clears_it_once(qtbot: QtBot) -> None:
    host, editor, _, effect = _surface(qtbot)
    effect.configure_effects(PresentationSettings(reduced_motion=True))
    effect.trigger(host)
    assert effect.isVisible()
    assert effect.animation.state() == QAbstractAnimation.State.Stopped
    assert effect.static_timer.isActive()
    before = effect.grab().toImage()
    qtbot.wait(50)
    assert effect.grab().toImage() == before
    assert editor.hasFocus()
    qtbot.waitUntil(effect.isHidden, timeout=1700)
    assert not effect.static_timer.isActive()
    assert effect.animation.state() == QAbstractAnimation.State.Stopped


def test_disabled_and_hidden_effects_release_replay_resources(qtbot: QtBot) -> None:
    host, editor, _, effect = _surface(qtbot)
    effect.configure_effects(PresentationSettings(effects=False))
    effect.trigger(host)
    assert effect.isHidden()
    assert effect.animation.state() == QAbstractAnimation.State.Stopped
    assert not effect.static_timer.isActive()
    effect.configure_effects(PresentationSettings())
    assert effect.isHidden()
    effect.trigger(host)
    assert effect.animation.state() == QAbstractAnimation.State.Running
    effect.hide()
    assert effect.animation.state() == QAbstractAnimation.State.Stopped
    effect.configure_effects(PresentationSettings(reduced_motion=True))
    effect.trigger(host)
    assert effect.static_timer.isActive()
    effect.configure_effects(PresentationSettings(effects=False))
    assert effect.isHidden()
    assert not effect.static_timer.isActive()
    assert editor.hasFocus()
