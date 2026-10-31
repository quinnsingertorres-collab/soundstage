"""Audio routing: capture everything Windows plays, mix it, send it to real speakers.

Windows plays into the free VB-Audio "CABLE Input" virtual device. Soundstage
records the other end ("CABLE Output"), runs it through the MixChain and plays
the result on the speakers/headphones you pick. Using a virtual cable (instead
of loopback-recording the speakers) is what keeps you from hearing the
original and the mixed audio on top of each other.
"""
from __future__ import annotations

import queue
import threading
from dataclasses import dataclass

import numpy as np

from .dsp import MixChain

try:
    import sounddevice as sd
except Exception:  # pragma: no cover - PortAudio missing
    sd = None


CABLE_KEYWORDS = ("cable output", "vb-audio")
CABLE_PLAYBACK_KEYWORDS = ("cable input",)


@dataclass
class Device:
    index: int
    name: str
    channels: int
    samplerate: float

    def __str__(self):
        return self.name


def _hostapi_index():
    """Prefer WASAPI on Windows; fall back to PortAudio's default host API."""
    if sd is None:
        return None
    for i, api in enumerate(sd.query_hostapis()):
        if "WASAPI" in api["name"]:
            return i
    return sd.default.hostapi


def list_devices(kind: str) -> list[Device]:
    """kind = 'input' or 'output'."""
    if sd is None:
        return []
    api = _hostapi_index()
    key = "max_input_channels" if kind == "input" else "max_output_channels"
    out = []
    for i, d in enumerate(sd.query_devices()):
        if d["hostapi"] == api and d[key] > 0:
            out.append(Device(i, d["name"], d[key], d["default_samplerate"]))
    return out


def refresh_devices():
    """PortAudio caches the device list; re-initialise to see new/changed devices."""
    if sd is None:
        return
    try:
        sd._terminate()
        sd._initialize()
    except Exception:
        pass


def find_cable_capture() -> Device | None:
    for d in list_devices("input"):
        if any(k in d.name.lower() for k in CABLE_KEYWORDS):
            return d
    return None


def is_cable(name: str) -> bool:
    n = name.lower()
    return "cable" in n and ("vb-audio" in n or "input" in n or "output" in n)


def real_outputs() -> list[Device]:
    return [d for d in list_devices("output") if not is_cable(d.name)]


def windows_default_output_name() -> str | None:
    if sd is None:
        return None
    try:
        api = sd.query_hostapis(_hostapi_index())
        idx = api["default_output_device"]
        return sd.query_devices(idx)["name"] if idx >= 0 else None
    except Exception:
        return None


def routing_status() -> str:
    """'no-cable', 'not-default' or 'ok'."""
    if find_cable_capture() is None:
        return "no-cable"
    default = windows_default_output_name() or ""
    if not any(k in default.lower() for k in CABLE_PLAYBACK_KEYWORDS):
        return "not-default"
    return "ok"


def _wasapi_settings():
    if sd is None or not hasattr(sd, "WasapiSettings"):
        return None
    try:
        return sd.WasapiSettings(exclusive=False, auto_convert=True)
    except TypeError:  # older sounddevice without auto_convert
        return None


class AudioEngine:
    """Two streams (capture + playback) joined by a small jitter buffer."""

    def __init__(self, chain: MixChain | None = None):
        self.chain = chain or MixChain(48000)
        self.blocksize = 512
        self.input_device: int | None = None
        self.output_device: int | None = None
        self._in_stream = None
        self._out_stream = None
        self._q: queue.Queue = queue.Queue(maxsize=8)
        self._primed = False
        self._lock = threading.Lock()
        self.running = False
        self.error: str | None = None
        self.underruns = 0

    # ---- callbacks (audio threads) -------------------------------------
    def _on_input(self, indata, frames, time_info, status):
        try:
            out = self.chain.process(indata)
        except Exception as e:  # never let DSP kill the stream
            self.error = f"DSP error: {e}"
            out = np.zeros((frames, 2), np.float32)
        try:
            self._q.put_nowait(out)
        except queue.Full:
            try:
                self._q.get_nowait()      # drop the oldest block to cap latency
            except queue.Empty:
                pass
            self._q.put_nowait(out)

    def _on_output(self, outdata, frames, time_info, status):
        if not self._primed:
            if self._q.qsize() < 2:
                outdata.fill(0)
                return
            self._primed = True
        # keep latency low if the capture clock runs a little fast
        while self._q.qsize() > 4:
            try:
                self._q.get_nowait()
            except queue.Empty:
                break
        try:
            block = self._q.get_nowait()
        except queue.Empty:
            self.underruns += 1
            self._primed = False
            outdata.fill(0)
            return
        n = min(len(block), frames)
        outdata[:n, :2] = block[:n]
        if n < frames:
            outdata[n:] = 0
        if outdata.shape[1] > 2:
            outdata[:, 2:] = 0

    # ---- control (UI thread) --------------------------------------------
    def start(self) -> bool:
        if sd is None:
            self.error = "Audio support (PortAudio) isn't available on this system."
            return False
        self.stop()
        self.error = None
        cable = find_cable_capture()
        in_dev = self.input_device if self.input_device is not None else (cable.index if cable else None)
        if in_dev is None:
            self.error = "VB-CABLE isn't installed, so there's nothing to capture yet."
            return False
        outs = real_outputs()
        out_dev = self.output_device if self.output_device is not None else (outs[0].index if outs else None)
        if out_dev is None:
            self.error = "No speakers or headphones were found."
            return False
        info = sd.query_devices(in_dev)
        fs = float(info["default_samplerate"]) or 48000.0
        if abs(fs - self.chain.fs) > 1:
            params = dict(self.chain.p)
            self.chain = MixChain(fs)
            self.chain.set_params(params)
        extra = _wasapi_settings()
        try:
            self._q = queue.Queue(maxsize=8)
            self._primed = False
            self._in_stream = sd.InputStream(
                device=in_dev, channels=min(2, max(1, info["max_input_channels"])),
                samplerate=fs, blocksize=self.blocksize, dtype="float32",
                latency="low", callback=self._on_input, extra_settings=extra)
            self._out_stream = sd.OutputStream(
                device=out_dev, channels=2, samplerate=fs, blocksize=self.blocksize,
                dtype="float32", latency="low", callback=self._on_output, extra_settings=extra)
            self._out_stream.start()
            self._in_stream.start()
        except Exception as e:
            self.error = f"Couldn't open audio devices: {e}"
            self.stop()
            return False
        self.input_device, self.output_device = in_dev, out_dev
        self.running = True
        return True

    def stop(self):
        for s in (self._in_stream, self._out_stream):
            if s is not None:
                try:
                    s.stop()
                    s.close()
                except Exception:
                    pass
        self._in_stream = self._out_stream = None
        self.running = False

    @property
    def latency_ms(self) -> float:
        if not self.running:
            return 0.0
        try:
            base = (self._in_stream.latency + self._out_stream.latency) * 1000
        except Exception:
            base = 0.0
        return base + self._q.qsize() * self.blocksize / self.chain.fs * 1000
