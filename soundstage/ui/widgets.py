"""Custom controls: knobs, meters, gain-reduction bars and the EQ curve."""
from __future__ import annotations

import math

import numpy as np
from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget
from scipy.signal import sosfreqz

from ..dsp import Equalizer
from . import theme


class Knob(QWidget):
    """A rotary control. Drag up/down (Shift for fine), scroll, double-click to reset."""

    valueChanged = Signal(float)

    def __init__(self, label: str, minimum: float, maximum: float, value: float,
                 default: float | None = None, fmt: str = "{:.1f}", unit: str = "",
                 log: bool = False, step: float | None = None, color: QColor | None = None,
                 size: int = 46, parent=None):
        super().__init__(parent)
        self.label, self.min, self.max = label, float(minimum), float(maximum)
        self.default = float(value if default is None else default)
        self.fmt, self.unit, self.log = fmt, unit, log
        self.step = step
        self.color = color or theme.C_ACCENT
        self.dial = size
        self._value = float(value)
        self._drag = None
        self.setFixedSize(max(size + 22, 70), size + 42)
        self.setCursor(Qt.SizeVerCursor)
        self.setToolTip(f"{label} — drag, scroll, or double-click to reset")

    # mapping between value and 0..1 knob position
    def _to_norm(self, v):
        if self.log:
            return math.log(v / self.min) / math.log(self.max / self.min)
        return (v - self.min) / (self.max - self.min)

    def _from_norm(self, n):
        n = min(1.0, max(0.0, n))
        v = self.min * (self.max / self.min) ** n if self.log else self.min + n * (self.max - self.min)
        if self.step:
            v = round(v / self.step) * self.step
        return min(self.max, max(self.min, v))

    def value(self) -> float:
        return self._value

    def setValue(self, v: float, emit: bool = False):
        v = min(self.max, max(self.min, float(v)))
        if abs(v - self._value) < 1e-9:
            return
        self._value = v
        self.update()
        if emit:
            self.valueChanged.emit(v)

    def text(self) -> str:
        v = self._value
        if self.unit == "Hz" and v >= 1000:
            return f"{v / 1000:.1f}k"
        s = self.fmt.format(v)
        if self.unit in ("dB",) and v > 0.05:
            s = "+" + s
        return f"{s}{(' ' + self.unit) if self.unit and self.unit != 'Hz' else ''}"

    # interaction
    def mousePressEvent(self, e):
        self._drag = (e.position().y(), self._to_norm(self._value))

    def mouseMoveEvent(self, e):
        if self._drag is None:
            return
        y0, n0 = self._drag
        scale = 600 if e.modifiers() & Qt.ShiftModifier else 180
        self.setValue(self._from_norm(n0 + (y0 - e.position().y()) / scale), emit=True)

    def mouseReleaseEvent(self, e):
        self._drag = None

    def mouseDoubleClickEvent(self, e):
        self.setValue(self.default, emit=True)

    def wheelEvent(self, e):
        steps = e.angleDelta().y() / 120
        self.setValue(self._from_norm(self._to_norm(self._value) + steps * 0.02), emit=True)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w = self.width()
        d = self.dial
        r = QRectF((w - d) / 2, 4, d, d)
        start, span = 225, -270
        # track
        p.setPen(QPen(theme.C_LINE, 4, Qt.SolidLine, Qt.RoundCap))
        p.drawArc(r.adjusted(3, 3, -3, -3), start * 16, span * 16)
        # value arc (from centre for bipolar controls)
        n = self._to_norm(self._value)
        if self.min < 0 < self.max and not self.log:
            zero = self._to_norm(0.0)
            a0 = start + span * zero
            a1 = start + span * n
        else:
            a0, a1 = start, start + span * n
        p.setPen(QPen(self.color if self.isEnabled() else theme.C_DIM, 4, Qt.SolidLine, Qt.RoundCap))
        p.drawArc(r.adjusted(3, 3, -3, -3), int(a0 * 16), int((a1 - a0) * 16))
        # cap + pointer
        inner = r.adjusted(9, 9, -9, -9)
        p.setPen(Qt.NoPen)
        p.setBrush(theme.C_PANEL_2)
        p.drawEllipse(inner)
        ang = math.radians(start + span * n)
        c = inner.center()
        rad = inner.width() / 2 - 3
        p.setPen(QPen(theme.C_TEXT, 2, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(QPointF(c.x() + math.cos(ang) * rad * 0.35, c.y() - math.sin(ang) * rad * 0.35),
                   QPointF(c.x() + math.cos(ang) * rad, c.y() - math.sin(ang) * rad))
        # text
        f = QFont(self.font())
        f.setPixelSize(12)
        p.setFont(f)
        p.setPen(theme.C_TEXT)
        p.drawText(QRectF(0, d + 6, w, 16), Qt.AlignCenter, self.text())
        f.setPixelSize(11)
        p.setFont(f)
        p.setPen(theme.C_MUTED)
        p.drawText(QRectF(0, d + 22, w, 16), Qt.AlignCenter, self.label)


class Meter(QWidget):
    """Vertical peak meter (1 or 2 channels) with peak hold, -60..+3 dBFS."""

    def __init__(self, channels: int = 2, width: int = 18, parent=None):
        super().__init__(parent)
        self.channels = channels
        self.levels = [0.0] * channels
        self.holds = [-60.0] * channels
        self._display = [-60.0] * channels
        self.setFixedWidth(width)
        self.setMinimumHeight(120)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)

    def set_levels(self, *lin):
        for i in range(self.channels):
            v = lin[i] if i < len(lin) else lin[0]
            db = 20 * math.log10(max(float(v), 1e-6))
            # fast attack, smooth fall
            self._display[i] = db if db > self._display[i] else max(db, self._display[i] - 1.2)
            self.holds[i] = db if db > self.holds[i] else self.holds[i] - 0.25
        self.update()

    @staticmethod
    def _pos(db):
        return min(1.0, max(0.0, (db + 60) / 63))

    def paintEvent(self, _):
        p = QPainter(self)
        h = self.height()
        gap = 2
        bw = (self.width() - gap * (self.channels - 1)) / self.channels
        grad = QLinearGradient(0, h, 0, 0)
        grad.setColorAt(0.0, theme.C_ACCENT)
        grad.setColorAt(self._pos(-12), theme.C_ACCENT)
        grad.setColorAt(self._pos(-6), theme.C_PRO)
        grad.setColorAt(self._pos(-1), theme.C_DANGER)
        grad.setColorAt(1.0, theme.C_DANGER)
        for i in range(self.channels):
            x = i * (bw + gap)
            p.fillRect(QRectF(x, 0, bw, h), theme.C_BG)
            lvl = self._pos(self._display[i]) * h
            p.fillRect(QRectF(x, h - lvl, bw, lvl), QBrush(grad))
            hy = h - self._pos(self.holds[i]) * h
            if self.holds[i] > -59:
                p.fillRect(QRectF(x, hy, bw, 2), theme.C_TEXT)
        # scale ticks
        p.setPen(QColor(0, 0, 0, 120))
        for db in (-6, -12, -24, -48):
            y = h - self._pos(db) * h
            p.drawLine(0, int(y), self.width(), int(y))


class GRMeter(QWidget):
    """Horizontal gain-reduction bar, 0..max dB, drawn from the left."""

    def __init__(self, label="GR", max_db=20.0, color=None, parent=None):
        super().__init__(parent)
        self.label, self.max_db = label, max_db
        self.color = color or theme.C_PRO
        self.value = 0.0
        self.setFixedHeight(22)
        self.setMinimumWidth(120)

    def set_value(self, db):
        self.value = self.value * 0.6 + float(db) * 0.4
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        p.setPen(Qt.NoPen)
        p.setBrush(theme.C_BG)
        p.drawRoundedRect(QRectF(0, 4, w, h - 8), 4, 4)
        fill = min(1.0, self.value / self.max_db) * w
        p.setBrush(self.color)
        p.drawRoundedRect(QRectF(0, 4, fill, h - 8), 4, 4)
        p.setPen(theme.C_TEXT)
        f = QFont(self.font())
        f.setPixelSize(11)
        p.setFont(f)
        p.drawText(QRectF(6, 0, w - 12, h), Qt.AlignVCenter | Qt.AlignLeft, self.label)
        p.drawText(QRectF(6, 0, w - 12, h), Qt.AlignVCenter | Qt.AlignRight, f"-{self.value:.1f} dB")


class EqCurve(QWidget):
    """Live frequency-response plot of the current EQ settings."""

    FS = 48000

    def __init__(self, parent=None):
        super().__init__(parent)
        self.freqs = np.geomspace(20, 20000, 240)
        self.resp = np.zeros_like(self.freqs)
        self.color = theme.C_ACCENT
        self.setMinimumHeight(130)

    def set_params(self, params: dict, color: QColor | None = None):
        eq = Equalizer()
        eq.configure(params, self.FS)
        if eq.sos is None:
            self.resp = np.zeros_like(self.freqs)
        else:
            _, h = sosfreqz(eq.sos, worN=self.freqs, fs=self.FS)
            self.resp = 20 * np.log10(np.maximum(np.abs(h), 1e-6))
        if color is not None:
            self.color = color
        self.update()

    def _x(self, f):
        return (math.log10(f) - math.log10(20)) / (math.log10(20000) - math.log10(20)) * self.width()

    def _y(self, db, rng=15.0):
        h = self.height()
        return h / 2 - (max(-rng, min(rng, db)) / rng) * (h / 2 - 8)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        p.setPen(Qt.NoPen)
        p.setBrush(theme.C_BG)
        p.drawRoundedRect(QRectF(0, 0, w, h), 8, 8)
        f = QFont(self.font())
        f.setPixelSize(10)
        p.setFont(f)
        grid = QPen(theme.C_LINE, 1)
        for fr, lab in ((50, "50"), (100, "100"), (500, "500"), (1000, "1k"), (5000, "5k"), (10000, "10k")):
            x = self._x(fr)
            p.setPen(grid)
            p.drawLine(QPointF(x, 0), QPointF(x, h))
            p.setPen(theme.C_DIM)
            p.drawText(QPointF(x + 3, h - 4), lab)
        for db in (-12, -6, 0, 6, 12):
            y = self._y(db)
            p.setPen(QPen(theme.C_DIM if db == 0 else theme.C_LINE, 1))
            p.drawLine(QPointF(0, y), QPointF(w, y))
            p.setPen(theme.C_DIM)
            p.drawText(QPointF(4, y - 2), f"{db:+d}" if db else "0")
        path = QPainterPath()
        pts = [QPointF(self._x(fr), self._y(db)) for fr, db in zip(self.freqs, self.resp)]
        path.moveTo(pts[0])
        for pt in pts[1:]:
            path.lineTo(pt)
        fillp = QPainterPath(path)
        fillp.lineTo(QPointF(w, self._y(0)))
        fillp.lineTo(QPointF(0, self._y(0)))
        fillp.closeSubpath()
        c = QColor(self.color)
        c.setAlpha(45)
        p.fillPath(fillp, c)
        p.setPen(QPen(self.color, 2))
        p.drawPath(path)


class Section(QFrame):
    """A titled panel with an optional on/off toggle in the header."""

    toggled = Signal(bool)

    def __init__(self, title: str, toggle: bool = False, parent=None):
        super().__init__(parent)
        self.setObjectName("panel")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 10, 14, 12)
        outer.setSpacing(8)
        head = QHBoxLayout()
        lab = QLabel(title.upper())
        lab.setObjectName("section")
        head.addWidget(lab)
        head.addStretch(1)
        self.switch = None
        if toggle:
            self.switch = QPushButton("On")
            self.switch.setObjectName("toggle")
            self.switch.setCheckable(True)
            self.switch.toggled.connect(self._on_toggle)
            head.addWidget(self.switch)
        outer.addLayout(head)
        self.body = QHBoxLayout()
        self.body.setSpacing(4)
        outer.addLayout(self.body)

    def _on_toggle(self, on):
        self.switch.setText("On" if on else "Off")
        self.toggled.emit(on)

    def set_on(self, on: bool):
        if self.switch:
            self.switch.blockSignals(True)
            self.switch.setChecked(on)
            self.switch.setText("On" if on else "Off")
            self.switch.blockSignals(False)
