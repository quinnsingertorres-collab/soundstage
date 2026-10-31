from PySide6.QtGui import QColor

BG = "#121417"
PANEL = "#1A1D22"
PANEL_2 = "#22262C"
LINE = "#2E333A"
TEXT = "#E8EAED"
MUTED = "#9AA0A8"
DIM = "#646B74"
ACCENT = "#3DDC97"      # custom / signal
PRO = "#F5B342"         # professional mode
DANGER = "#FF5D5D"
SOLO = "#5DA9FF"

C_BG, C_PANEL, C_PANEL_2, C_LINE = map(QColor, (BG, PANEL, PANEL_2, LINE))
C_TEXT, C_MUTED, C_DIM = map(QColor, (TEXT, MUTED, DIM))
C_ACCENT, C_PRO, C_DANGER, C_SOLO = map(QColor, (ACCENT, PRO, DANGER, SOLO))

STYLESHEET = f"""
* {{ font-family: "Segoe UI Variable", "Segoe UI", "Inter", sans-serif; font-size: 13px; color: {TEXT}; }}
QMainWindow, QDialog, #root {{ background: {BG}; }}
QLabel#title {{ font-size: 18px; font-weight: 600; }}
QLabel#subtle {{ color: {MUTED}; }}
QLabel#section {{ color: {MUTED}; font-size: 11px; font-weight: 600; letter-spacing: 1px; }}
QFrame#panel {{ background: {PANEL}; border: 1px solid {LINE}; border-radius: 12px; }}
QFrame#strip {{ background: {PANEL}; border: 1px solid {LINE}; border-radius: 10px; }}
QFrame#strip[master="true"] {{ background: {PANEL_2}; border-color: {ACCENT}; }}
QFrame#banner {{ background: #2A2416; border: 1px solid #5A4A22; border-radius: 10px; }}
QFrame#propanel {{ background: #211C12; border: 1px solid #5A4A22; border-radius: 12px; }}
QPushButton {{ background: {PANEL_2}; border: 1px solid {LINE}; border-radius: 8px; padding: 6px 12px; }}
QPushButton:hover {{ border-color: {DIM}; }}
QPushButton:pressed {{ background: {LINE}; }}
QPushButton:checked {{ background: #17382B; border-color: {ACCENT}; color: {ACCENT}; }}
QPushButton#seg {{ border-radius: 0; padding: 7px 16px; }}
QPushButton#segL {{ border-top-right-radius: 0; border-bottom-right-radius: 0; padding: 7px 16px; }}
QPushButton#segR {{ border-top-left-radius: 0; border-bottom-left-radius: 0; padding: 7px 16px; }}
QPushButton#segR:checked {{ background: #3A2D12; border-color: {PRO}; color: {PRO}; }}
QPushButton#venue:checked {{ background: #3A2D12; border-color: {PRO}; color: {PRO}; }}
QPushButton#mute {{ padding: 3px 0; min-width: 28px; font-weight: 600; }}
QPushButton#mute:checked {{ background: #3A1717; border-color: {DANGER}; color: {DANGER}; }}
QPushButton#solo {{ padding: 3px 0; min-width: 28px; font-weight: 600; }}
QPushButton#solo:checked {{ background: #16283D; border-color: {SOLO}; color: {SOLO}; }}
QPushButton#bypass:checked {{ background: #3A1717; border-color: {DANGER}; color: {DANGER}; }}
QPushButton#primary {{ background: {PRO}; color: #1A1406; border: none; font-weight: 600; }}
QPushButton#toggle {{ padding: 2px 10px; font-size: 11px; }}
QComboBox {{ background: {PANEL_2}; border: 1px solid {LINE}; border-radius: 8px; padding: 5px 10px; min-width: 120px; }}
QComboBox QAbstractItemView {{ background: {PANEL_2}; border: 1px solid {LINE}; selection-background-color: {LINE}; }}
QTabWidget::pane {{ border: none; }}
QTabBar::tab {{ background: transparent; color: {MUTED}; padding: 8px 16px; border-bottom: 2px solid transparent; font-weight: 600; }}
QTabBar::tab:selected {{ color: {TEXT}; border-bottom-color: {ACCENT}; }}
QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:horizontal {{ height: 8px; background: transparent; }}
QScrollBar::handle:horizontal {{ background: {LINE}; border-radius: 4px; min-width: 30px; }}
QScrollBar:vertical {{ width: 8px; background: transparent; }}
QScrollBar::handle:vertical {{ background: {LINE}; border-radius: 4px; min-height: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QSlider::groove:vertical {{ background: {BG}; width: 6px; border-radius: 3px; }}
QSlider::sub-page:vertical {{ background: {BG}; border-radius: 3px; }}
QSlider::add-page:vertical {{ background: {ACCENT}; width: 6px; border-radius: 3px; }}
QSlider::handle:vertical {{ background: {TEXT}; height: 14px; width: 30px; margin: 0 -12px; border-radius: 4px; }}
QSlider::groove:horizontal {{ background: {BG}; height: 6px; border-radius: 3px; }}
QSlider::sub-page:horizontal {{ background: {PRO}; height: 6px; border-radius: 3px; }}
QSlider::handle:horizontal {{ background: {TEXT}; width: 18px; height: 18px; margin: -6px 0; border-radius: 9px; }}
QToolTip {{ background: {PANEL_2}; color: {TEXT}; border: 1px solid {LINE}; padding: 4px; }}
QMenu {{ background: {PANEL_2}; border: 1px solid {LINE}; }}
QMenu::item:selected {{ background: {LINE}; }}
QLineEdit {{ background: {PANEL_2}; border: 1px solid {LINE}; border-radius: 8px; padding: 5px 8px; }}
"""
