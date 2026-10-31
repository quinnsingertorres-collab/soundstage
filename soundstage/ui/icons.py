"""The Soundstage app icon, drawn in code so no image assets are needed at runtime."""
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap


def icon_pixmap(size: int = 256) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    s = size / 256
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("#16191D"))
    p.drawRoundedRect(QRectF(8 * s, 8 * s, 240 * s, 240 * s), 56 * s, 56 * s)
    # three fader slots with caps at different heights
    caps = [(70, 150, "#3DDC97"), (128, 90, "#F5B342"), (186, 125, "#3DDC97")]
    for x, cap_y, color in caps:
        p.setBrush(QColor("#2E333A"))
        p.drawRoundedRect(QRectF((x - 7) * s, 52 * s, 14 * s, 152 * s), 7 * s, 7 * s)
        p.setBrush(QColor(color))
        p.drawRoundedRect(QRectF((x - 7) * s, cap_y * s, 14 * s, (204 - cap_y) * s), 7 * s, 7 * s)
        p.setBrush(QColor("#E8EAED"))
        p.drawRoundedRect(QRectF((x - 22) * s, (cap_y - 11) * s, 44 * s, 22 * s), 8 * s, 8 * s)
    p.end()
    return pm


def app_icon() -> QIcon:
    icon = QIcon()
    for sz in (16, 24, 32, 48, 64, 128, 256):
        icon.addPixmap(icon_pixmap(sz))
    return icon
