"""Soundstage main window."""
from __future__ import annotations

from PySide6.QtCore import QByteArray, Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QDesktopServices
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                               QFormLayout, QFrame, QHBoxLayout, QInputDialog, QLabel,
                               QMainWindow, QMenu, QMessageBox, QPushButton, QScrollArea,
                               QSizePolicy, QSlider, QSystemTrayIcon, QTabWidget, QVBoxLayout,
                               QWidget)

from .. import APP_NAME, __version__, engine as eng
from ..config import Settings
from ..dsp import DEFAULT_PARAMS
from ..engine import AudioEngine
from ..presets import BUILTIN_PRESETS, VENUES, professional
from ..sessions import SessionManager
from . import theme
from .icons import app_icon, icon_pixmap
from .strips import ChannelStrip, MasterStrip, app_icon as program_icon
from .widgets import EqCurve, GRMeter, Knob, Meter, Section

# Controls that belong to you in every mode (they never kick you out of Professional).
MASTER_KEYS = ("output_gain", "balance")

VBCABLE_URL = "https://vb-audio.com/Cable/"


def feel_caption(lf: float) -> str:
    if lf < 0.2:
        return "Clean, polished studio master"
    if lf < 0.45:
        return "Mastered, with a hint of the room"
    if lf < 0.7:
        return "Front-of-house energy — like the sound desk at a show"
    if lf < 0.9:
        return "Big live show: wide, warm and roomy"
    return "Front row at the arena"


class MainWindow(QMainWindow):
    def __init__(self, settings: Settings, engine: AudioEngine, sessions: SessionManager):
        super().__init__()
        self.settings, self.engine, self.sessions = settings, engine, sessions
        self.mode = settings["mode"]
        self.venue = settings["venue"] if settings["venue"] in VENUES else "Theater"
        self.live_feel = float(settings["live_feel"])
        self.custom_params = dict(DEFAULT_PARAMS, **settings["params"])
        self.custom_params["bypass"] = False
        self.bypassed = False
        self.knobs: dict[str, Knob] = {}
        self.groups = {}
        self.strips: dict[str, ChannelStrip] = {}
        self._strip_keys: list[str] = []
        self.user_mutes: dict[str, bool] = {}
        self.solos: set[str] = set()
        self._tray_hint_shown = False
        self._quitting = False

        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(app_icon())
        self.resize(1180, 820)
        self.setMinimumSize(900, 620)
        if settings.get("geometry"):
            try:
                self.restoreGeometry(QByteArray.fromBase64(settings["geometry"].encode()))
            except Exception:
                pass

        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        self.vbox = QVBoxLayout(root)
        self.vbox.setContentsMargins(18, 14, 18, 14)
        self.vbox.setSpacing(12)

        self._build_header()
        self._build_banner()
        self._build_pro_panel()
        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_apps_tab(), "Apps")
        self.tabs.addTab(self._build_mixer_tab(), "Mixer")
        self.vbox.addWidget(self.tabs, 1)
        self._build_tray()

        self._save_timer = QTimer(self, singleShot=True, interval=800, timeout=self._save)
        self._meter_timer = QTimer(self, interval=33, timeout=self._tick_meters)
        self._meter_timer.start()
        self._session_timer = QTimer(self, interval=1500, timeout=self.refresh_sessions)
        self._session_timer.start()
        self._routing_timer = QTimer(self, interval=5000, timeout=self._auto_recheck)
        self._routing_timer.start()

        self.set_mode(self.mode, push=False)
        self.refresh_sessions()
        self.push_params()
        self._update_routing(eng.routing_status())

    # ------------------------------------------------------------------ header
    def _build_header(self):
        row = QHBoxLayout()
        row.setSpacing(10)
        logo = QLabel()
        logo.setPixmap(icon_pixmap(30))
        row.addWidget(logo)
        title = QLabel(APP_NAME)
        title.setObjectName("title")
        row.addWidget(title)
        row.addSpacing(14)

        seg = QHBoxLayout()
        seg.setSpacing(0)
        self.btn_custom = QPushButton("Custom")
        self.btn_custom.setObjectName("segL")
        self.btn_pro = QPushButton("Professional")
        self.btn_pro.setObjectName("segR")
        grp = QButtonGroup(self)
        for b in (self.btn_custom, self.btn_pro):
            b.setCheckable(True)
            grp.addButton(b)
            seg.addWidget(b)
        self.btn_custom.clicked.connect(lambda: self.set_mode("custom"))
        self.btn_pro.clicked.connect(lambda: self.set_mode("pro"))
        row.addLayout(seg)
        row.addSpacing(10)

        self.preset_combo = QComboBox()
        self.preset_combo.setPlaceholderText("Unsaved mix")
        self.preset_combo.setMinimumWidth(170)
        self._fill_presets()
        self.preset_combo.activated.connect(self._on_preset)
        row.addWidget(self.preset_combo)
        self.btn_save_preset = QPushButton("Save as…")
        self.btn_save_preset.clicked.connect(self._save_preset)
        row.addWidget(self.btn_save_preset)
        self.btn_del_preset = QPushButton("Delete")
        self.btn_del_preset.clicked.connect(self._delete_preset)
        row.addWidget(self.btn_del_preset)

        row.addStretch(1)
        self.status = QLabel()
        row.addWidget(self.status)
        self.btn_bypass = QPushButton("Bypass")
        self.btn_bypass.setObjectName("bypass")
        self.btn_bypass.setCheckable(True)
        self.btn_bypass.setToolTip("Hear your audio without any processing")
        self.btn_bypass.toggled.connect(self.set_bypass)
        row.addWidget(self.btn_bypass)
        settings_btn = QPushButton("Settings")
        settings_btn.clicked.connect(self.open_settings)
        row.addWidget(settings_btn)
        self.vbox.addLayout(row)

    def _fill_presets(self):
        self.preset_combo.blockSignals(True)
        self.preset_combo.clear()
        for name in BUILTIN_PRESETS:
            self.preset_combo.addItem(name, ("builtin", name))
        users = self.settings["user_presets"]
        if users:
            self.preset_combo.insertSeparator(self.preset_combo.count())
            for name in sorted(users):
                self.preset_combo.addItem(name, ("user", name))
        self._select_preset(self.settings.get("preset"))
        self.preset_combo.blockSignals(False)

    def _select_preset(self, name):
        for i in range(self.preset_combo.count()):
            d = self.preset_combo.itemData(i)
            if d and d[1] == name:
                self.preset_combo.setCurrentIndex(i)
                self._sync_delete_button()
                return
        self.preset_combo.setCurrentIndex(-1)
        self._sync_delete_button()

    def _sync_delete_button(self):
        if not hasattr(self, "btn_del_preset"):
            return
        d = self.preset_combo.currentData()
        self.btn_del_preset.setVisible(self.mode == "custom" and bool(d) and d[0] == "user")

    # ------------------------------------------------------------------ banner
    def _build_banner(self):
        self.banner = QFrame()
        self.banner.setObjectName("banner")
        lay = QHBoxLayout(self.banner)
        lay.setContentsMargins(14, 10, 14, 10)
        self.banner_text = QLabel()
        self.banner_text.setWordWrap(True)
        lay.addWidget(self.banner_text, 1)
        self.banner_btn = QPushButton()
        self.banner_btn.clicked.connect(self._banner_action)
        lay.addWidget(self.banner_btn)
        again = QPushButton("Check again")
        again.clicked.connect(self.recheck_routing)
        lay.addWidget(again)
        self.vbox.addWidget(self.banner)
        self.banner.hide()
        self._banner_kind = None

    def _banner_action(self):
        if self._banner_kind == "no-cable":
            QDesktopServices.openUrl(QUrl(VBCABLE_URL))
        elif self._banner_kind == "not-default":
            QDesktopServices.openUrl(QUrl("ms-settings:sound"))
        else:
            self.open_settings()

    def _update_routing(self, status: str):
        self._routing = status
        if self.engine.error and status == "ok":
            self._banner_kind = "error"
            self.banner_text.setText(self.engine.error)
            self.banner_btn.setText("Audio settings")
            self.banner.show()
        elif status == "no-cable":
            self._banner_kind = "no-cable"
            self.banner_text.setText(
                "One-time setup: install the free VB-CABLE driver. It gives Soundstage a way "
                "to hear everything Windows plays so it can mix it before it reaches your speakers.")
            self.banner_btn.setText("Get VB-CABLE")
            self.banner.show()
        elif status == "not-default":
            self._banner_kind = "not-default"
            self.banner_text.setText(
                "Almost there: in Windows Sound settings, set your Output device to "
                "“CABLE Input”. Soundstage will play the mixed result on your speakers.")
            self.banner_btn.setText("Open sound settings")
            self.banner.show()
        else:
            self.banner.hide()
        self._update_status()

    def recheck_routing(self):
        was_running = self.engine.running
        self.engine.stop()
        eng.refresh_devices()
        status = eng.routing_status()
        if status != "no-cable" or was_running:
            self.start_engine(update_banner=False)
        self._update_routing(status)

    def _auto_recheck(self):
        # Re-scanning devices restarts audio, so only poll while setup is unfinished.
        if self._routing != "ok" and self.isVisible():
            self.recheck_routing()

    # ------------------------------------------------------------------ pro panel
    def _build_pro_panel(self):
        self.pro_panel = QFrame()
        self.pro_panel.setObjectName("propanel")
        lay = QHBoxLayout(self.pro_panel)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.setSpacing(24)

        left = QVBoxLayout()
        t = QLabel("Professional mix")
        t.setStyleSheet(f"color:{theme.PRO}; font-size:16px; font-weight:600;")
        left.addWidget(t)
        d = QLabel("Tone-matched EQ, glue compression, console warmth, a wider stage, "
                   "a real venue around it, and a limiter so nothing ever clips.")
        d.setObjectName("subtle")
        d.setWordWrap(True)
        d.setMaximumWidth(360)
        left.addWidget(d)
        left.addStretch(1)
        lay.addLayout(left, 2)

        mid = QVBoxLayout()
        vl = QLabel("VENUE")
        vl.setObjectName("section")
        mid.addWidget(vl)
        vrow = QHBoxLayout()
        vrow.setSpacing(6)
        self.venue_group = QButtonGroup(self)
        self.venue_buttons = {}
        for name in VENUES:
            b = QPushButton(name)
            b.setObjectName("venue")
            b.setCheckable(True)
            b.clicked.connect(lambda _=False, n=name: self.set_venue(n))
            self.venue_group.addButton(b)
            self.venue_buttons[name] = b
            vrow.addWidget(b)
        mid.addLayout(vrow)
        fl = QHBoxLayout()
        lab = QLabel("LIVE FEEL")
        lab.setObjectName("section")
        fl.addWidget(lab)
        fl.addStretch(1)
        self.feel_value = QLabel()
        fl.addWidget(self.feel_value)
        mid.addSpacing(6)
        mid.addLayout(fl)
        self.feel = QSlider(Qt.Horizontal)
        self.feel.setRange(0, 100)
        self.feel.setValue(round(self.live_feel * 100))
        self.feel.valueChanged.connect(self._on_feel)
        mid.addWidget(self.feel)
        self.feel_caption = QLabel()
        self.feel_caption.setObjectName("subtle")
        mid.addWidget(self.feel_caption)
        lay.addLayout(mid, 3)

        right = QVBoxLayout()
        right.addStretch(1)
        tune = QPushButton("Fine-tune in mixer")
        tune.setObjectName("primary")
        tune.setToolTip("Switch to Custom, starting from this professional mix")
        tune.clicked.connect(self.fine_tune)
        right.addWidget(tune)
        right.addStretch(1)
        lay.addLayout(right)
        self.vbox.addWidget(self.pro_panel)
        self.venue_buttons[self.venue].setChecked(True)
        self._on_feel(self.feel.value(), push=False)

    def set_venue(self, name):
        self.venue = name
        self.venue_buttons[name].setChecked(True)
        self.settings["venue"] = name
        self.refresh_controls()
        self.push_params()

    def _on_feel(self, v, push=True):
        self.live_feel = v / 100
        self.settings["live_feel"] = self.live_feel
        self.feel_value.setText(f"{v}%")
        self.feel_caption.setText(feel_caption(self.live_feel))
        if push:
            self.refresh_controls()
            self.push_params()

    def fine_tune(self):
        keep = {k: self.custom_params[k] for k in MASTER_KEYS}
        self.custom_params = dict(professional(self.live_feel, self.venue), **keep)
        self.settings["preset"] = None
        self.set_mode("custom")
        self._select_preset(None)
        self.tabs.setCurrentIndex(1)

    # ------------------------------------------------------------------ apps tab
    def _build_apps_tab(self):
        page = QWidget()
        lay = QHBoxLayout(page)
        lay.setContentsMargins(0, 12, 0, 0)
        lay.setSpacing(12)
        self.apps_scroll = QScrollArea()
        self.apps_scroll.setWidgetResizable(True)
        self.apps_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        holder = QWidget()
        self.apps_row = QHBoxLayout(holder)
        self.apps_row.setContentsMargins(0, 0, 0, 0)
        self.apps_row.setSpacing(10)
        self.apps_empty = QLabel("Nothing is playing yet. Start some music or a video and its "
                                 "app shows up here with its own fader.")
        self.apps_empty.setObjectName("subtle")
        self.apps_empty.setWordWrap(True)
        self.apps_row.addWidget(self.apps_empty)
        self.apps_row.addStretch(1)
        self.apps_scroll.setWidget(holder)
        lay.addWidget(self.apps_scroll, 1)
        self.master = MasterStrip(self.custom_params["output_gain"])
        self.master.gainChanged.connect(lambda db: self.on_param("output_gain", db))
        lay.addWidget(self.master)
        return page

    def refresh_sessions(self):
        groups = self.sessions.groups()
        self.groups = {g.key: g for g in groups}
        keys = [g.key for g in groups]
        if keys != self._strip_keys:
            self._rebuild_strips(groups)
        else:
            for g in groups:
                s = self.strips[g.key]
                if not s.fader.isSliderDown():
                    s.set_volume(g.volume)
                if not self.solos:
                    s.set_muted(g.muted)
                    self.user_mutes[g.key] = g.muted

    def _rebuild_strips(self, groups):
        for s in self.strips.values():
            self.apps_row.removeWidget(s)
            s.deleteLater()
        self.strips = {}
        self.solos &= {g.key for g in groups}
        insert_at = 0
        for g in groups:
            strip = ChannelStrip(g.name, program_icon(g.name, g.exe_path), g.volume, g.muted,
                                 show_solo=len(groups) > 1)
            strip.volumeChanged.connect(lambda v, k=g.key: self._app_volume(k, v))
            strip.muteToggled.connect(lambda m, k=g.key: self._app_mute(k, m))
            strip.soloToggled.connect(lambda on, k=g.key: self._app_solo(k, on))
            strip.solo.setChecked(g.key in self.solos)
            self.user_mutes.setdefault(g.key, g.muted)
            self.apps_row.insertWidget(insert_at, strip)
            insert_at += 1
            self.strips[g.key] = strip
        self._strip_keys = [g.key for g in groups]
        self.apps_empty.setVisible(not groups)
        self._apply_solo()

    def _app_volume(self, key, v):
        g = self.groups.get(key)
        if g:
            g.set_volume(v)

    def _app_mute(self, key, m):
        self.user_mutes[key] = m
        self._apply_solo()

    def _app_solo(self, key, on):
        (self.solos.add if on else self.solos.discard)(key)
        self._apply_solo()

    def _apply_solo(self):
        for key, g in self.groups.items():
            muted = self.user_mutes.get(key, False) or (bool(self.solos) and key not in self.solos)
            g.set_muted(muted)
            if key in self.strips:
                self.strips[key].set_muted(muted)

    # ------------------------------------------------------------------ mixer tab
    def _knob(self, key, label, lo, hi, **kw):
        k = Knob(label, lo, hi, self.custom_params[key], default=DEFAULT_PARAMS[key], **kw)
        k.valueChanged.connect(lambda v, key=key: self.on_param(key, v))
        self.knobs[key] = k
        return k

    def _build_mixer_tab(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        page = QWidget()
        col = QVBoxLayout(page)
        col.setContentsMargins(0, 12, 6, 0)
        col.setSpacing(12)

        # --- Equalizer ---------------------------------------------------
        eq = Section("Equalizer")
        eqw = QWidget()
        eqv = QVBoxLayout(eqw)
        eqv.setContentsMargins(0, 0, 0, 0)
        self.eq_curve = EqCurve()
        eqv.addWidget(self.eq_curve)
        bands = QHBoxLayout()
        bands.setSpacing(2)

        def band(title, widgets):
            box = QVBoxLayout()
            box.setSpacing(0)
            lab = QLabel(title)
            lab.setObjectName("subtle")
            lab.setAlignment(Qt.AlignCenter)
            box.addWidget(lab)
            r = QHBoxLayout()
            r.setSpacing(0)
            for w in widgets:
                r.addWidget(w)
            box.addLayout(r)
            bands.addLayout(box)

        def divider():
            line = QFrame()
            line.setFixedWidth(1)
            line.setStyleSheet(f"background:{theme.LINE};")
            bands.addWidget(line)

        self.hpf_btn = QPushButton("Low cut")
        self.hpf_btn.setObjectName("toggle")
        self.hpf_btn.setCheckable(True)
        self.hpf_btn.toggled.connect(lambda on: self.on_param("hpf_on", on))
        hp = QVBoxLayout()
        hp.setSpacing(4)
        hp.addWidget(self.hpf_btn, 0, Qt.AlignCenter)
        hp.addWidget(self._knob("hpf_freq", "Freq", 20, 300, unit="Hz", fmt="{:.0f}", log=True))
        bands.addLayout(hp)
        divider()
        band("Low shelf", [self._knob("low_gain", "Gain", -12, 12, unit="dB", step=0.1),
                           self._knob("low_freq", "Freq", 40, 400, unit="Hz", fmt="{:.0f}", log=True)])
        divider()
        for key, title, lo, hi in (("lowmid", "Low-mid", 100, 1000), ("mid", "Mid", 300, 4000),
                                   ("highmid", "High-mid", 1500, 10000)):
            band(title, [self._knob(f"{key}_gain", "Gain", -12, 12, unit="dB", step=0.1),
                         self._knob(f"{key}_freq", "Freq", lo, hi, unit="Hz", fmt="{:.0f}", log=True),
                         self._knob(f"{key}_q", "Width Q", 0.3, 4.0, fmt="{:.2f}", log=True)])
            divider()
        band("High shelf", [self._knob("high_gain", "Gain", -12, 12, unit="dB", step=0.1),
                            self._knob("high_freq", "Freq", 3000, 16000, unit="Hz", fmt="{:.0f}", log=True)])
        bands.addStretch(1)
        reset = QPushButton("Flat")
        reset.setToolTip("Reset the EQ")
        reset.clicked.connect(self._reset_eq)
        bands.addWidget(reset, 0, Qt.AlignBottom)
        eqv.addLayout(bands)
        eq.body.addWidget(eqw)
        col.addWidget(eq)

        # --- Input / Dynamics / Colour -------------------------------------
        row1 = QHBoxLayout()
        row1.setSpacing(12)
        inp = Section("Input")
        inp.body.addWidget(self._knob("input_gain", "Gain", -24, 24, unit="dB", step=0.1))
        self.in_meter = Meter(2, 14)
        self.in_meter.setMinimumHeight(80)
        inp.body.addWidget(self.in_meter)
        row1.addWidget(inp)

        self.dyn = Section("Compressor", toggle=True)
        self.dyn.toggled.connect(lambda on: self.on_param("comp_on", on))
        dynw = QWidget()
        dv = QVBoxLayout(dynw)
        dv.setContentsMargins(0, 0, 0, 0)
        dk = QHBoxLayout()
        dk.setSpacing(0)
        dk.addWidget(self._knob("comp_threshold", "Threshold", -50, 0, unit="dB", step=0.5))
        dk.addWidget(self._knob("comp_ratio", "Ratio", 1, 10, fmt="{:.1f}:1", log=True))
        dk.addWidget(self._knob("comp_attack", "Attack", 0.5, 100, unit="ms", fmt="{:.0f}", log=True))
        dk.addWidget(self._knob("comp_release", "Release", 20, 1000, unit="ms", fmt="{:.0f}", log=True))
        dk.addWidget(self._knob("comp_makeup", "Makeup", 0, 18, unit="dB", step=0.1))
        dv.addLayout(dk)
        self.comp_gr = GRMeter("Gain reduction")
        dv.addWidget(self.comp_gr)
        self.dyn.body.addWidget(dynw)
        row1.addWidget(self.dyn, 1)

        colour = Section("Colour and stage")
        colour.body.addWidget(self._knob("warmth", "Warmth", 0, 1, fmt="{:.0%}"))
        colour.body.addWidget(self._knob("width", "Width", 0, 2, fmt="{:.0%}"))
        row1.addWidget(colour)
        col.addLayout(row1)

        # --- Space / Output ----------------------------------------------
        row2 = QHBoxLayout()
        row2.setSpacing(12)
        self.space = Section("Room reverb", toggle=True)
        self.space.toggled.connect(lambda on: self.on_param("reverb_on", on))
        self.space.body.addWidget(self._knob("reverb_size", "Size", 0, 1, fmt="{:.0%}"))
        self.space.body.addWidget(self._knob("reverb_damp", "Damping", 0, 1, fmt="{:.0%}"))
        self.space.body.addWidget(self._knob("reverb_predelay", "Pre-delay", 0, 120, unit="ms", fmt="{:.0f}"))
        self.space.body.addWidget(self._knob("reverb_mix", "Amount", 0, 0.5, fmt="{:.0%}"))
        self.space.body.addStretch(1)
        row2.addWidget(self.space, 1)

        out = Section("Output")
        outw = QWidget()
        ov = QVBoxLayout(outw)
        ov.setContentsMargins(0, 0, 0, 0)
        ok = QHBoxLayout()
        ok.setSpacing(0)
        ok.addWidget(self._knob("balance", "Balance", -1, 1, fmt="{:+.2f}"))
        ok.addWidget(self._knob("limiter_ceiling", "Ceiling", -12, 0, unit="dB", step=0.1))
        ok.addWidget(self._knob("output_gain", "Level", -24, 12, unit="dB", step=0.1))
        ov.addLayout(ok)
        lr = QHBoxLayout()
        self.lim_btn = QPushButton("Limiter")
        self.lim_btn.setObjectName("toggle")
        self.lim_btn.setCheckable(True)
        self.lim_btn.toggled.connect(lambda on: self.on_param("limiter_on", on))
        lr.addWidget(self.lim_btn)
        self.lim_gr = GRMeter("Limiting", max_db=12, color=theme.C_DANGER)
        lr.addWidget(self.lim_gr, 1)
        ov.addLayout(lr)
        out.body.addWidget(outw)
        self.out_meter = Meter(2, 14)
        self.out_meter.setMinimumHeight(80)
        out.body.addWidget(self.out_meter)
        row2.addWidget(out, 1)
        col.addLayout(row2)
        col.addStretch(1)
        scroll.setWidget(page)
        return scroll

    def _reset_eq(self):
        for k in DEFAULT_PARAMS:
            if k.startswith(("low", "mid", "highmid", "high_", "hpf")):
                self.on_param(k, DEFAULT_PARAMS[k], refresh=False)
        self.refresh_controls()

    # ------------------------------------------------------------------ params
    def current_params(self) -> dict:
        if self.mode == "pro":
            p = professional(self.live_feel, self.venue)
            for k in MASTER_KEYS:
                p[k] = self.custom_params[k]
        else:
            p = dict(self.custom_params)
        p["bypass"] = self.bypassed
        return p

    def on_param(self, key, value, refresh=True):
        if key not in MASTER_KEYS and self.mode == "pro":
            # Touching any mixer control turns the pro mix into your own starting point.
            keep = {k: self.custom_params[k] for k in MASTER_KEYS}
            self.custom_params = dict(professional(self.live_feel, self.venue), **keep)
            self.set_mode("custom", push=False)
        if key not in MASTER_KEYS and self.settings.get("preset") is not None:
            self.settings["preset"] = None
            self._select_preset(None)
        self.custom_params[key] = value
        if key == "output_gain":
            self.master.set_gain(value)
            self.knobs["output_gain"].setValue(value)
        if refresh and key not in ("output_gain",):
            self._refresh_toggles(self.current_params())
        self.push_params()

    def push_params(self):
        p = self.current_params()
        self.engine.chain.set_params(p)
        self.eq_curve.set_params(p, theme.C_PRO if self.mode == "pro" else theme.C_ACCENT)
        self.settings["params"] = {k: v for k, v in self.custom_params.items() if k != "bypass"}
        self.settings["mode"] = self.mode
        self._save_timer.start()

    def _refresh_toggles(self, p):
        self.hpf_btn.blockSignals(True)
        self.hpf_btn.setChecked(bool(p["hpf_on"]))
        self.hpf_btn.blockSignals(False)
        self.lim_btn.blockSignals(True)
        self.lim_btn.setChecked(bool(p["limiter_on"]))
        self.lim_btn.blockSignals(False)
        self.dyn.set_on(bool(p["comp_on"]))
        self.space.set_on(bool(p["reverb_on"]))

    def refresh_controls(self):
        p = self.current_params()
        color = theme.C_PRO if self.mode == "pro" else theme.C_ACCENT
        for key, k in self.knobs.items():
            k.color = theme.C_ACCENT if key in MASTER_KEYS else color
            k.setValue(p[key])
            k.update()
        self._refresh_toggles(p)
        self.master.set_gain(p["output_gain"])
        self.eq_curve.set_params(p, color)

    def set_mode(self, mode, push=True):
        self.mode = mode
        self.btn_custom.setChecked(mode == "custom")
        self.btn_pro.setChecked(mode == "pro")
        self.pro_panel.setVisible(mode == "pro")
        for w in (self.preset_combo, self.btn_save_preset):
            w.setVisible(mode == "custom")
        self._sync_delete_button()
        self.refresh_controls()
        if hasattr(self, "tray_pro"):
            self.tray_pro.setChecked(mode == "pro")
        if push:
            self.push_params()
        self._update_status()

    def set_bypass(self, on):
        self.bypassed = on
        if self.btn_bypass.isChecked() != on:
            self.btn_bypass.setChecked(on)
        if hasattr(self, "tray_bypass"):
            self.tray_bypass.setChecked(on)
        self.push_params()
        self._update_status()

    # ------------------------------------------------------------------ presets
    def _on_preset(self, index):
        data = self.preset_combo.itemData(index)
        if not data:
            return
        kind, name = data
        src = BUILTIN_PRESETS[name] if kind == "builtin" else self.settings["user_presets"].get(name, {})
        keep = {k: self.custom_params[k] for k in MASTER_KEYS}
        self.custom_params = dict(DEFAULT_PARAMS, **src)
        self.custom_params.update(keep)
        self.settings["preset"] = name
        self._sync_delete_button()
        self.refresh_controls()
        self.push_params()

    def _save_preset(self):
        name, ok = QInputDialog.getText(self, "Save preset", "Name this mix:")
        name = (name or "").strip()
        if not ok or not name:
            return
        if name in BUILTIN_PRESETS:
            QMessageBox.information(self, APP_NAME, "That name belongs to a built-in preset. Try another.")
            return
        self.settings["user_presets"][name] = {k: v for k, v in self.custom_params.items()
                                               if k not in MASTER_KEYS and k != "bypass"}
        self.settings["preset"] = name
        self._fill_presets()
        self._save()

    def _delete_preset(self):
        d = self.preset_combo.currentData()
        if not d or d[0] != "user":
            return
        if QMessageBox.question(self, APP_NAME, f"Delete the preset “{d[1]}”?") != QMessageBox.Yes:
            return
        self.settings["user_presets"].pop(d[1], None)
        self.settings["preset"] = None
        self._fill_presets()
        self._save()

    # ------------------------------------------------------------------ meters & status
    def _tick_meters(self):
        chain = self.engine.chain
        if self.engine.running:
            self.master.meter.set_levels(*chain.out_peak)
            self.out_meter.set_levels(*chain.out_peak)
            self.in_meter.set_levels(*chain.in_peak)
            self.comp_gr.set_value(chain.comp_gr)
            self.lim_gr.set_value(chain.limiter_gr)
        else:
            for m in (self.master.meter, self.out_meter, self.in_meter):
                m.set_levels(0, 0)
            self.comp_gr.set_value(0)
            self.lim_gr.set_value(0)
        for key, strip in self.strips.items():
            g = self.groups.get(key)
            strip.meter.set_levels(g.peak if g else 0.0)

    def _update_status(self):
        if self.bypassed:
            text, color = "● Bypassed", theme.DANGER
        elif self.engine.running and getattr(self, "_routing", "ok") == "ok":
            ms = self.engine.latency_ms
            label = "Professional" if self.mode == "pro" else "Mixing"
            text, color = f"● {label} · {ms:.0f} ms", theme.PRO if self.mode == "pro" else theme.ACCENT
        elif self.engine.running:
            text, color = "● Waiting for audio", theme.MUTED
        else:
            text, color = "● Stopped", theme.DIM
        self.status.setText(text)
        self.status.setStyleSheet(f"color:{color}; font-weight:600; padding: 0 6px;")

    # ------------------------------------------------------------------ engine & settings
    def _device_index(self, name, kind):
        if not name:
            return None
        for d in eng.list_devices(kind):
            if d.name == name:
                return d.index
        return None

    def start_engine(self, update_banner=True):
        self.engine.blocksize = int(self.settings.get("blocksize", 512))
        self.engine.input_device = self._device_index(self.settings.get("input_device"), "input")
        self.engine.output_device = self._device_index(self.settings.get("output_device"), "output")
        self.engine.start()
        self.push_params()   # the chain may have been rebuilt for a new sample rate
        if update_banner:
            self._update_routing(eng.routing_status())
        self._update_status()

    def open_settings(self):
        dlg = SettingsDialog(self.settings, self)
        if dlg.exec() == QDialog.Accepted:
            dlg.apply()
            self._save()
            self.recheck_routing()

    # ------------------------------------------------------------------ tray & lifetime
    def _build_tray(self):
        self.tray = None
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self.tray = QSystemTrayIcon(app_icon(), self)
        self.tray.setToolTip(APP_NAME)
        menu = QMenu()
        show = QAction("Show Soundstage", self, triggered=self.show_normal)
        self.tray_pro = QAction("Professional mode", self, checkable=True)
        self.tray_pro.triggered.connect(lambda on: self.set_mode("pro" if on else "custom"))
        self.tray_bypass = QAction("Bypass", self, checkable=True)
        self.tray_bypass.triggered.connect(self.set_bypass)
        quit_ = QAction("Quit", self, triggered=self.quit)
        for a in (show, self.tray_pro, self.tray_bypass):
            menu.addAction(a)
        menu.addSeparator()
        menu.addAction(quit_)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(lambda r: self.show_normal() if r == QSystemTrayIcon.Trigger else None)
        self.tray.show()

    def show_normal(self):
        self.show()
        self.setWindowState(self.windowState() & ~Qt.WindowMinimized)
        self.raise_()
        self.activateWindow()

    def closeEvent(self, e):
        if not self._quitting and self.tray and self.settings.get("close_to_tray", True):
            e.ignore()
            self.hide()
            if not self._tray_hint_shown:
                self.tray.showMessage(APP_NAME, "Still mixing in the background. "
                                      "Right-click the tray icon to quit.", app_icon(), 4000)
                self._tray_hint_shown = True
            return
        self._shutdown()
        e.accept()

    def quit(self):
        self._quitting = True
        self.close()

    def _shutdown(self):
        self._save()
        self.engine.stop()
        if self.tray:
            self.tray.hide()
        from PySide6.QtWidgets import QApplication
        QApplication.quit()

    def _save(self):
        self.settings["geometry"] = bytes(self.saveGeometry().toBase64()).decode()
        self.settings.save()


class SettingsDialog(QDialog):
    def __init__(self, settings: Settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("Audio settings")
        self.setMinimumWidth(460)
        form = QFormLayout(self)
        form.setSpacing(10)

        self.out = QComboBox()
        self.out.addItem("Automatic (first speakers found)", None)
        for d in eng.real_outputs():
            self.out.addItem(d.name, d.name)
        self._select(self.out, settings.get("output_device"))
        form.addRow("Play the mix on", self.out)

        self.inp = QComboBox()
        self.inp.addItem("Automatic (CABLE Output)", None)
        for d in eng.list_devices("input"):
            self.inp.addItem(d.name, d.name)
        self._select(self.inp, settings.get("input_device"))
        form.addRow("Capture from", self.inp)

        self.block = QComboBox()
        for n, hint in ((256, "lowest latency"), (512, "balanced"), (1024, "most stable")):
            self.block.addItem(f"{n} samples — {hint}", n)
        self._select(self.block, settings.get("blocksize", 512))
        form.addRow("Buffer size", self.block)

        self.tray = QCheckBox("Keep mixing in the tray when the window is closed")
        self.tray.setChecked(settings.get("close_to_tray", True))
        form.addRow("", self.tray)

        note = QLabel("Your Windows output should be set to “CABLE Input”. Pick your real "
                      "speakers or headphones above.")
        note.setObjectName("subtle")
        note.setWordWrap(True)
        form.addRow(note)
        ver = QLabel(f"{APP_NAME} {__version__}")
        ver.setObjectName("subtle")
        form.addRow(ver)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    @staticmethod
    def _select(combo, value):
        for i in range(combo.count()):
            if combo.itemData(i) == value:
                combo.setCurrentIndex(i)
                return

    def apply(self):
        self.settings["output_device"] = self.out.currentData()
        self.settings["input_device"] = self.inp.currentData()
        self.settings["blocksize"] = self.block.currentData()
        self.settings["close_to_tray"] = self.tray.isChecked()
