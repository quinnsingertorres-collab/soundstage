"""Per-app volume, mute and level meters via the Windows audio session API.

Apps play into the default device (CABLE Input once routing is set up), so
their sessions live there and these faders act before Soundstage's mix.
Off Windows, a demo set of apps is returned so the UI can still be previewed.
"""
from __future__ import annotations

import math
import random
import sys
import time
from dataclasses import dataclass, field

IS_WINDOWS = sys.platform == "win32"

if IS_WINDOWS:
    try:
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume, IAudioMeterInformation
    except Exception:  # pragma: no cover
        AudioUtilities = None
else:
    AudioUtilities = None

FRIENDLY = {
    "chrome": "Chrome", "msedge": "Edge", "firefox": "Firefox", "spotify": "Spotify",
    "discord": "Discord", "steam": "Steam", "steamwebhelper": "Steam", "vlc": "VLC",
    "teams": "Teams", "ms-teams": "Teams", "zoom": "Zoom", "obs64": "OBS",
    "applemusic": "Apple Music", "itunes": "iTunes", "music.ui": "Media Player",
    "slack": "Slack", "brave": "Brave", "opera": "Opera",
}


def friendly_name(exe: str) -> str:
    base = exe.rsplit("\\", 1)[-1]
    if base.lower().endswith(".exe"):
        base = base[:-4]
    return FRIENDLY.get(base.lower(), base[:1].upper() + base[1:])


@dataclass
class AppGroup:
    """All audio sessions of one program (Chrome alone can have dozens)."""
    key: str
    name: str
    exe_path: str | None = None
    sessions: list = field(default_factory=list)
    meters: list = field(default_factory=list)

    # ---- volume ----------------------------------------------------------
    @property
    def volume(self) -> float:
        for s in self.sessions:
            try:
                return float(s.SimpleAudioVolume.GetMasterVolume())
            except Exception:
                continue
        return 1.0

    def set_volume(self, v: float):
        v = max(0.0, min(1.0, v))
        for s in self.sessions:
            try:
                s.SimpleAudioVolume.SetMasterVolume(v, None)
            except Exception:
                pass

    @property
    def muted(self) -> bool:
        for s in self.sessions:
            try:
                return bool(s.SimpleAudioVolume.GetMute())
            except Exception:
                continue
        return False

    def set_muted(self, m: bool):
        for s in self.sessions:
            try:
                s.SimpleAudioVolume.SetMute(1 if m else 0, None)
            except Exception:
                pass

    @property
    def peak(self) -> float:
        best = 0.0
        for m in self.meters:
            try:
                best = max(best, float(m.GetPeakValue()))
            except Exception:
                pass
        return best


class SessionManager:
    def __init__(self):
        self.available = IS_WINDOWS and AudioUtilities is not None

    def groups(self) -> list[AppGroup]:
        if not self.available:
            return _demo_groups()
        groups: dict[str, AppGroup] = {}
        try:
            sessions = AudioUtilities.GetAllSessions()
        except Exception:
            return []
        for s in sessions:
            try:
                proc = s.Process
                if proc is None:
                    key, name, path = "system", "System sounds", None
                else:
                    exe = proc.name()
                    key, name = exe.lower(), friendly_name(exe)
                    try:
                        path = proc.exe()
                    except Exception:
                        path = None
                    if key == "soundstage.exe":
                        continue
                g = groups.setdefault(key, AppGroup(key, name, path))
                g.sessions.append(s)
                try:
                    g.meters.append(s._ctl.QueryInterface(IAudioMeterInformation))
                except Exception:
                    pass
            except Exception:
                continue
        order = sorted(groups.values(), key=lambda g: (g.key == "system", g.name.lower()))
        return order


# ---------------------------------------------------------------------------
# Windows master volume (what the keyboard volume keys change)
# ---------------------------------------------------------------------------

ENDPOINT_HARDWARE_SUPPORT_VOLUME = 0x1


class SystemVolume:
    """Reads and sets the default output device's volume and mute.

    Once routing is set up the default device is CABLE Input, so this is
    exactly what the volume keys and the Windows volume flyout control.
    """

    def __init__(self):
        self.available = IS_WINDOWS and AudioUtilities is not None
        self._ep = None
        self.hardware_volume = False
        self._demo = [0.6, False]

    def reset(self):
        """Forget the cached device (call after the default device changes)."""
        self._ep = None

    def _endpoint(self):
        if not self.available:
            return None
        if self._ep is None:
            try:
                dev = AudioUtilities.GetSpeakers()
                ep = getattr(dev, "EndpointVolume", None)       # newer pycaw
                if ep is None:                                   # older pycaw
                    from ctypes import POINTER, cast
                    from comtypes import CLSCTX_ALL
                    iface = dev.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
                    ep = cast(iface, POINTER(IAudioEndpointVolume))
                try:
                    self.hardware_volume = bool(ep.QueryHardwareSupport() & ENDPOINT_HARDWARE_SUPPORT_VOLUME)
                except Exception:
                    self.hardware_volume = False
                self._ep = ep
            except Exception:
                self._ep = None
        return self._ep

    def read(self):
        """(scalar 0..1, level dB, muted) or None if unavailable."""
        if not self.available:
            v, m = self._demo
            return v, (20 * math.log10(v) if v > 0 else -96.0), m
        ep = self._endpoint()
        if ep is None:
            return None
        try:
            return (float(ep.GetMasterVolumeLevelScalar()), float(ep.GetMasterVolumeLevel()),
                    bool(ep.GetMute()))
        except Exception:
            self._ep = None
            return None

    def set_scalar(self, v: float):
        v = max(0.0, min(1.0, v))
        if not self.available:
            self._demo[0] = v
            return
        ep = self._endpoint()
        if ep is not None:
            try:
                ep.SetMasterVolumeLevelScalar(v, None)
            except Exception:
                self._ep = None

    def set_mute(self, m: bool):
        if not self.available:
            self._demo[1] = bool(m)
            return
        ep = self._endpoint()
        if ep is not None:
            try:
                ep.SetMute(1 if m else 0, None)
            except Exception:
                self._ep = None


# ---------------------------------------------------------------------------
# Demo mode (non-Windows previews and tests)
# ---------------------------------------------------------------------------

class _DemoVolume:
    def __init__(self, v):
        self.v, self.m = v, 0

    def GetMasterVolume(self): return self.v
    def SetMasterVolume(self, v, _): self.v = v
    def GetMute(self): return self.m
    def SetMute(self, m, _): self.m = m


class _DemoSession:
    def __init__(self, v):
        self.SimpleAudioVolume = _DemoVolume(v)


class _DemoMeter:
    def __init__(self, speed, vol):
        self.speed, self.vol, self.phase = speed, vol, random.random() * 6

    def GetPeakValue(self):
        t = time.time() * self.speed + self.phase
        if self.vol.m:
            return 0.0
        return self.vol.v * (0.45 + 0.35 * abs(math.sin(t)) + 0.15 * random.random())


_DEMO: list[AppGroup] | None = None


def _demo_groups() -> list[AppGroup]:
    global _DEMO
    if _DEMO is None:
        _DEMO = []
        for key, name, v, speed in [("spotify.exe", "Spotify", 0.8, 2.1),
                                    ("chrome.exe", "Chrome", 0.6, 1.3),
                                    ("game.exe", "Game", 0.7, 3.0),
                                    ("discord.exe", "Discord", 0.9, 4.2),
                                    ("system", "System sounds", 0.5, 0.7)]:
            s = _DemoSession(v)
            _DEMO.append(AppGroup(key, name, None, [s], [_DemoMeter(speed, s.SimpleAudioVolume)]))
    return _DEMO
