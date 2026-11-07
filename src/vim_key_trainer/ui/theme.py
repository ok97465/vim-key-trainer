"""Qt Widgets 공통 색상과 스타일."""

STYLESHEET = """
QWidget {
    background: #10151d; color: #e8edf3;
    font-family: "Apple SD Gothic Neo", "Malgun Gothic", sans-serif;
    font-size: 14px;
}
QMainWindow { background: #10151d; }
QLabel { background: transparent; }
QFrame#sidebar { background: #151c26; border-right: 1px solid #293342; }
QFrame#card { background: #19212d; border: 1px solid #2c3747; border-radius: 12px; }
QFrame#card QLabel { background: transparent; }
QLabel#brand { color: #c3ef85; font-size: 22px; font-weight: bold; }
QLabel#eyebrow { color: #b7e980; font-size: 12px; font-weight: bold; }
QLabel#title { font-size: 30px; font-weight: bold; }
QLabel#sectionTitle { font-size: 19px; font-weight: bold; }
QLabel#muted { color: #a2afbf; }
QLabel#metric { font-size: 26px; font-weight: bold; }
QLabel#stars { font-size: 36px; color: #c3ef85; }
QPushButton {
    background: #243041; border: 1px solid #354458; border-radius: 7px;
    padding: 10px 18px; font-weight: bold;
}
QPushButton:hover { background: #304157; border-color: #7a8da6; }
QPushButton:focus { border: 2px solid #c3ef85; }
QPushButton:pressed { background: #172231; }
QPushButton:disabled { color: #748193; background: #1b2430; border-color: #293342; }
QPushButton#primary, QPushButton[emphasized="true"] {
    background: #c3ef85; color: #17220e; border-color: #c3ef85;
}
QPushButton#primary:hover, QPushButton[emphasized="true"]:hover { background: #d5ffa1; }
QPushButton#primary:disabled, QPushButton[emphasized="true"]:disabled {
    color: #748193; background: #1b2430; border-color: #293342;
}
QPushButton#nav {
    text-align: left; background: transparent; border-color: transparent;
}
QPushButton#nav:hover { background: #243041; }
QPushButton#nav:checked {
    background: #25382c; border-color: #60764a; color: #c3ef85;
}
QPushButton#nav:focus { border-color: #c3ef85; }
QComboBox, QSpinBox {
    background: #19212d; border: 1px solid #425268; border-radius: 6px;
    padding: 7px 10px; min-height: 24px;
}
QComboBox:focus, QSpinBox:focus { border-color: #c3ef85; }
QComboBox QAbstractItemView {
    background: #243041; selection-background-color: #425268;
}
QProgressBar {
    background: #253040; border: none; border-radius: 3px;
    min-height: 6px; max-height: 6px;
}
QProgressBar::chunk { background: #c3ef85; border-radius: 3px; }
QScrollArea { border: none; }
QScrollBar:vertical { background: #151c26; width: 9px; }
QScrollBar::handle:vertical {
    background: #425268; border-radius: 4px; min-height: 30px;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal { background: #151c26; height: 9px; }
QScrollBar::handle:horizontal {
    background: #425268; border-radius: 4px; min-width: 30px;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
"""
