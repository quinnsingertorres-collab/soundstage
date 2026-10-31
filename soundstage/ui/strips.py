"""Channel strips for the Apps tab."""
from __future__ import annotations

import sys

from PySide6.QtCore import QFileInfo, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (QFileIconProvider, QFrame, QHBoxLayout, QLabel, QPushButton,
                               QSlider, QVBoxLayout)

from . import theme
from .widgets import Meter

_icon_provider = None
_PALETTE = ["#3DDC97", "#5DA9FF", "#F5B342", "#E86FA8", "#9C8CFF", "#4FD1E0"]


def letter_icon(name: str, size: int = 32) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    c = QColor(_PALETTE[sum(map(ord, name)) % len(_PALETTE)])
    bg = QColor(c)
    bg.setAlpha(50)
    p.setPen(Qt.NoPen)
    p.setBrush(bg)
    p.drawRoundedRect(QRectF(0, 0, size, size), 8, 8)
    p.setPen(c)
    f = QFont()
    f.setPixelSize(int(size * 0.5))
    f.setBold(True)
    p.setFont(f)
    p.drawText(QRectF(0, 0, size, size), Qt.AlignCenter, name[:1].upper())
    p.end()
    return pm


def app_icon(name: str, exe_path: str | None, size: int = 32) -> QPixmap:
    global _icon_provider
    if exe_path and sys.platform == "win32":
        try:
            if _icon_provider is None:
                _icon_provider = QFileIconProvider()
            icon = _icon_provider.icon(QFileInfo(exe_path))
            pm = icon.pixmap(QSize(size, size))
            if not pm.isNull():
                return pm
        except Exception:
            pass
    return letter_icon(name, size)


class ChannelStrip(QFrame):
    """Icon, name, meter, fader, value readout, mute/solo."""

    volumeChanged = Signal(float)     # 0..1
    muteToggled = Signal(bool)
    soloToggled = Signal(bool)

    def __init__(self, name: str, icon: QPixmap, volume: float = 1.0, muted: bool = False,
                 show_solo: bool = True, parent=None):
        super().__init__(parent)
        self.setObjectName("strip")
        self.setFixedWidth(96)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 10, 8, 10)
        lay.setSpacing(6)

        ic = QLabel()
        ic.setPixmap(icon)
        ic.setAlignment(Qt.AlignCenter)
        lay.addWidget(ic)
        self.name = QLabel(name)
        self.name.setAlignment(Qt.AlignCenter)
        self.name.setToolTip(name)
        fm = self.name.fontMetrics()
        self.name.setText(fm.elidedText(name, Qt.ElideRight, 80))
        lay.addWidget(self.name)

        mid = QHBoxLayout()
        mid.setSpacing(6)
        mid.addStretch(1)
        self.fader = QSlider(Qt.Vertical)
        self.fader.setRange(0, 100)
        self.fader.setValue(round(volume * 100))
        self.fader.setMinimumHeight(170)
        self.fader.valueChanged.connect(self._on_fader)
        mid.addWidget(self.fader)
        self.meter = Meter(channels=1, width=8)
        mid.addWidget(self.meter)
        mid.addStretch(1)
        lay.addLayout(mid, 1)

        self.readout = QLabel()
        self.readout.setAlignment(Qt.AlignCenter)
        self.readout.setObjectName("subtle")
        lay.addWidget(self.readout)

        btns = QHBoxLayout()
        btns.setSpacing(4)
        self.mute = QPushButton("M")
        self.mute.setObjectName("mute")
        self.mute.setCheckable(True)
        self.mute.setChecked(muted)
        self.mute.setToolTip("Mute")
        self.mute.toggled.connect(self.muteToggled)
        btns.addWidget(self.mute)
        self.solo = QPushButton("S")
        self.solo.setObjectName("solo")
        self.solo.setCheckable(True)
        self.solo.setToolTip("Solo — hear only this app")
        self.solo.toggled.connect(self.soloToggled)
        self.solo.setVisible(show_solo)
        btns.addWidget(self.solo)
        lay.addLayout(btns)
        self._update_readout()

    def _on_fader(self, v):
        self._update_readout()
        self.volumeChanged.emit(v / 100.0)

    def _update_readout(self):
        self.readout.setText(f"{self.fader.value()}%")

    def set_volume(self, v: float):
        self.fader.blockSignals(True)
        self.fader.setValue(round(v * 100))
        self.fader.blockSignals(False)
        self._update_readout()

    def set_muted(self, m: bool):
        self.mute.blockSignals(True)
        self.mute.setChecked(m)
        self.mute.blockSignals(False)


class MasterStrip(QFrame):
    """Output level (dB) with a stereo meter."""

    gainChanged = Signal(float)   # dB

    def __init__(self, gain_db: float = 0.0, parent=None):
        super().__init__(parent)
        self.setObjectName("strip")
        self.setProperty("master", True)
        self.setFixedWidth(120)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(6)
        t = QLabel("Master")
        t.setAlignment(Qt.AlignCenter)
        t.setStyleSheet(f"color:{theme.ACCENT}; font-weight:600;")
        lay.addWidget(t)
        sub = QLabel("after the mix")
        sub.setObjectName("subtle")
        sub.setAlignment(Qt.AlignCenter)
        lay.addWidget(sub)
        mid = QHBoxLayout()
        mid.addStretch(1)
        self.fader = QSlider(Qt.Vertical)
        self.fader.setRange(-240, 120)   # tenths of a dB
        self.fader.setValue(round(gain_db * 10))
        self.fader.setMinimumHeight(170)
        self.fader.valueChanged.connect(self._changed)
        mid.addWidget(self.fader)
        self.meter = Meter(channels=2, width=18)
        mid.addWidget(self.meter)
        mid.addStretch(1)
        lay.addLayout(mid, 1)
        self.readout = QLabel()
        self.readout.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.readout)
        reset = QPushButton("0 dB")
        reset.clicked.connect(lambda: self.fader.setValue(0))
        lay.addWidget(reset)
        self._changed(self.fader.value(), emit=False)

    def _changed(self, v, emit=True):
        db = v / 10
        self.readout.setText(f"{db:+.1f} dB" if abs(db) > 0.04 else "0.0 dB")
        if emit:
            self.gainChanged.emit(db)

    def set_gain(self, db: float):
        self.fader.blockSignals(True)
        self.fader.setValue(round(db * 10))
        self.fader.blockSignals(False)
        self._changed(self.fader.value(), emit=False)
