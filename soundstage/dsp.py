"""Real-time stereo DSP for Soundstage.

Every processor works on float32 blocks shaped (frames, 2) and keeps its own
state between blocks, so the chain can run inside an audio callback. All of
it is vectorised with numpy/scipy; the only Python loops run per sub-block
(32-64 samples) or per delay-line chunk, never per sample.
"""
from __future__ import annotations

import math
import threading

import numpy as np
from scipy.signal import lfilter, sosfilt

# ---------------------------------------------------------------------------
# Parameters
# ---------------------------------------------------------------------------

DEFAULT_PARAMS: dict = {
    "bypass": False,
    "input_gain": 0.0,          # dB
    # EQ
    "hpf_on": False, "hpf_freq": 30.0,
    "low_gain": 0.0, "low_freq": 100.0,                          # low shelf
    "lowmid_gain": 0.0, "lowmid_freq": 300.0, "lowmid_q": 1.0,   # peaking
    "mid_gain": 0.0, "mid_freq": 1000.0, "mid_q": 1.0,
    "highmid_gain": 0.0, "highmid_freq": 4000.0, "highmid_q": 1.0,
    "high_gain": 0.0, "high_freq": 10000.0,                      # high shelf
    # Dynamics
    "comp_on": False, "comp_threshold": -18.0, "comp_ratio": 2.0,
    "comp_attack": 20.0, "comp_release": 200.0, "comp_makeup": 0.0,
    # Colour
    "warmth": 0.0,              # 0..1 console-style saturation
    "width": 1.0,               # 0 = mono, 1 = unchanged, 2 = extra wide
    # Space
    "reverb_on": False, "reverb_size": 0.7, "reverb_damp": 0.5,
    "reverb_mix": 0.0, "reverb_predelay": 20.0,   # mix 0..1, predelay ms
    # Output
    "balance": 0.0,             # -1 left .. +1 right
    "limiter_on": True, "limiter_ceiling": -1.0,  # dBFS
    "output_gain": 0.0,         # dB
}


def db_to_lin(db):
    return np.power(10.0, np.asarray(db) / 20.0)


def lin_to_db(x, floor: float = -120.0):
    return np.maximum(20.0 * np.log10(np.maximum(np.asarray(x), 1e-12)), floor)


# ---------------------------------------------------------------------------
# EQ (RBJ cookbook biquads)
# ---------------------------------------------------------------------------

def biquad(kind: str, freq: float, fs: float, gain_db: float = 0.0, q: float = 0.707):
    freq = float(np.clip(freq, 10.0, fs * 0.45))
    w = 2 * math.pi * freq / fs
    cw, sw = math.cos(w), math.sin(w)
    A = 10 ** (gain_db / 40.0)
    if kind == "peak":
        alpha = sw / (2 * q)
        b = [1 + alpha * A, -2 * cw, 1 - alpha * A]
        a = [1 + alpha / A, -2 * cw, 1 - alpha / A]
    elif kind in ("lowshelf", "highshelf"):
        sq = math.sqrt(A)
        alpha = sw / math.sqrt(2)  # shelf slope S = 1
        if kind == "lowshelf":
            b = [A * ((A + 1) - (A - 1) * cw + 2 * sq * alpha),
                 2 * A * ((A - 1) - (A + 1) * cw),
                 A * ((A + 1) - (A - 1) * cw - 2 * sq * alpha)]
            a = [(A + 1) + (A - 1) * cw + 2 * sq * alpha,
                 -2 * ((A - 1) + (A + 1) * cw),
                 (A + 1) + (A - 1) * cw - 2 * sq * alpha]
        else:
            b = [A * ((A + 1) + (A - 1) * cw + 2 * sq * alpha),
                 -2 * A * ((A - 1) + (A + 1) * cw),
                 A * ((A + 1) + (A - 1) * cw - 2 * sq * alpha)]
            a = [(A + 1) - (A - 1) * cw + 2 * sq * alpha,
                 2 * ((A - 1) - (A + 1) * cw),
                 (A + 1) - (A - 1) * cw - 2 * sq * alpha]
    elif kind == "highpass":
        alpha = sw / (2 * q)
        b = [(1 + cw) / 2, -(1 + cw), (1 + cw) / 2]
        a = [1 + alpha, -2 * cw, 1 - alpha]
    elif kind == "lowpass":
        alpha = sw / (2 * q)
        b = [(1 - cw) / 2, 1 - cw, (1 - cw) / 2]
        a = [1 + alpha, -2 * cw, 1 - alpha]
    else:
        raise ValueError(kind)
    a0 = a[0]
    return np.array([b[0] / a0, b[1] / a0, b[2] / a0, 1.0, a[1] / a0, a[2] / a0])


class FilterBank:
    """A cascade of biquads applied to both channels, state kept across blocks."""

    def __init__(self):
        self.sos = None
        self.zi = None

    def set_sections(self, sections: list[np.ndarray]):
        if not sections:
            self.sos, self.zi = None, None
            return
        sos = np.vstack(sections)
        if self.zi is None or self.zi.shape[0] != sos.shape[0]:
            self.zi = np.zeros((sos.shape[0], 2, 2))
        self.sos = sos

    def process(self, x: np.ndarray) -> np.ndarray:
        if self.sos is None:
            return x
        y, self.zi = sosfilt(self.sos, x, axis=0, zi=self.zi)
        return y


class Equalizer(FilterBank):
    def configure(self, p: dict, fs: float):
        sections = []
        if p["hpf_on"]:
            sections.append(biquad("highpass", p["hpf_freq"], fs, q=0.707))
        if abs(p["low_gain"]) > 0.01:
            sections.append(biquad("lowshelf", p["low_freq"], fs, p["low_gain"]))
        for band in ("lowmid", "mid", "highmid"):
            if abs(p[f"{band}_gain"]) > 0.01:
                sections.append(biquad("peak", p[f"{band}_freq"], fs, p[f"{band}_gain"],
                                       max(0.1, p[f"{band}_q"])))
        if abs(p["high_gain"]) > 0.01:
            sections.append(biquad("highshelf", p["high_freq"], fs, p["high_gain"]))
        # Keep the state array the same size so toggling bands doesn't click badly.
        self.set_sections(sections)


# ---------------------------------------------------------------------------
# Dynamics
# ---------------------------------------------------------------------------

class Compressor:
    """Feed-forward RMS compressor with soft knee, computed per 32-sample sub-block."""

    SUB = 32

    def __init__(self, fs: float):
        self.fs = fs
        self.env_db = 0.0     # current gain reduction (positive dB)
        self.prev_gain = 1.0
        self.gain_reduction = 0.0
        self.set(-18.0, 2.0, 20.0, 200.0, 0.0)

    def set(self, threshold, ratio, attack_ms, release_ms, makeup_db, knee_db=6.0):
        self.threshold = float(threshold)
        self.ratio = max(1.0, float(ratio))
        sub_t = self.SUB / self.fs
        self.a_att = 1 - math.exp(-sub_t / max(attack_ms, 0.1) * 1000)
        self.a_rel = 1 - math.exp(-sub_t / max(release_ms, 1.0) * 1000)
        self.makeup = float(db_to_lin(makeup_db))
        self.knee = knee_db

    def _target_gr(self, level_db):
        over = level_db - self.threshold
        slope = 1 - 1 / self.ratio
        k = self.knee / 2
        gr = np.where(over <= -k, 0.0,
                      np.where(over >= k, over * slope, slope * (over + k) ** 2 / (2 * self.knee)))
        return gr

    def process(self, x: np.ndarray) -> np.ndarray:
        n = len(x)
        sub = self.SUB
        nseg = -(-n // sub)
        pad = nseg * sub - n
        sq = np.max(x * x, axis=1)
        if pad:
            sq = np.concatenate([sq, np.repeat(sq[-1:], pad)])
        rms = np.sqrt(sq.reshape(nseg, sub).mean(axis=1))
        targets = self._target_gr(lin_to_db(rms))
        gains = np.empty(nseg)
        env = self.env_db
        for i, t in enumerate(targets):
            env += (t - env) * (self.a_att if t > env else self.a_rel)
            gains[i] = env
        self.env_db = env
        self.gain_reduction = env
        lin = db_to_lin(-gains)
        # linear ramp from the previous sub-block's gain to each new one
        ramp = np.empty(nseg * sub)
        starts = np.concatenate([[self.prev_gain], lin[:-1]])
        frac = (np.arange(1, sub + 1) / sub)[None, :]
        ramp[:] = (starts[:, None] + (lin - starts)[:, None] * frac).ravel()
        self.prev_gain = lin[-1]
        return x * (ramp[:n, None] * self.makeup)


class Limiter:
    """Brickwall-style peak limiter: instant attack per 16-sample sub-block, smooth release."""

    SUB = 16

    def __init__(self, fs: float):
        self.fs = fs
        self.gain = 1.0
        self.ceiling = float(db_to_lin(-1.0))
        self.a_rel = 1 - math.exp(-(self.SUB / fs) / 0.08)
        self.gain_reduction = 0.0

    def set(self, ceiling_db: float):
        self.ceiling = float(db_to_lin(min(0.0, ceiling_db)))

    def process(self, x: np.ndarray) -> np.ndarray:
        n = len(x)
        sub = self.SUB
        nseg = -(-n // sub)
        pad = nseg * sub - n
        pk = np.max(np.abs(x), axis=1)
        if pad:
            pk = np.concatenate([pk, np.zeros(pad)])
        peaks = pk.reshape(nseg, sub).max(axis=1)
        needed = np.minimum(1.0, self.ceiling / np.maximum(peaks, 1e-12))
        g = self.gain
        out_g = np.empty(nseg * sub)
        idx = np.arange(1, sub + 1) / sub
        for i, target in enumerate(needed):
            if target < g:            # attack instantly for this sub-block
                out_g[i * sub:(i + 1) * sub] = target
                g = target
            else:                     # release smoothly toward unity / target
                new = g + (target - g) * self.a_rel
                out_g[i * sub:(i + 1) * sub] = g + (new - g) * idx
                g = new
        self.gain = g
        self.gain_reduction = float(-lin_to_db(g))
        y = x * out_g[:n, None]
        # safety net for inter-sample overs
        return np.clip(y, -self.ceiling, self.ceiling)


# ---------------------------------------------------------------------------
# Colour & stereo
# ---------------------------------------------------------------------------

def saturate(x: np.ndarray, amount: float) -> np.ndarray:
    """Gentle console-style saturation, level-matched, blended by amount (0..1)."""
    if amount <= 0.001:
        return x
    drive = 1.0 + 4.0 * amount
    wet = np.tanh(x * drive) / math.tanh(drive)
    return x + (wet - x) * min(1.0, amount * 1.2)


def stereo_width(x: np.ndarray, width: float) -> np.ndarray:
    if abs(width - 1.0) < 1e-3:
        return x
    mid = (x[:, 0] + x[:, 1]) * 0.5
    side = (x[:, 0] - x[:, 1]) * 0.5 * width
    # keep perceived loudness roughly constant when widening
    comp = 1.0 / math.sqrt(0.5 * (1 + width * width)) if width > 1 else 1.0
    return np.stack([(mid + side) * comp, (mid - side) * comp], axis=1)


def balance(x: np.ndarray, bal: float) -> np.ndarray:
    if abs(bal) < 1e-3:
        return x
    gl = 1.0 if bal <= 0 else 1.0 - bal
    gr = 1.0 if bal >= 0 else 1.0 + bal
    return x * np.array([gl, gr])


# ---------------------------------------------------------------------------
# Reverb (Freeverb topology, vectorised by delay-line chunks)
# ---------------------------------------------------------------------------

_COMB_TUNING = [1116, 1188, 1277, 1356, 1422, 1491, 1557, 1617]
_ALLPASS_TUNING = [556, 441, 341, 225]
_SPREAD = 23


class _Comb:
    def __init__(self, size):
        self.buf = np.zeros(size)
        self.idx = 0
        self.zi = np.zeros(1)
        self.feedback = 0.84
        self.damp = 0.2

    def process(self, x):
        out = np.empty_like(x)
        size = len(self.buf)
        pos, n = 0, len(x)
        d = self.damp
        while pos < n:
            m = min(n - pos, size - self.idx)
            seg = self.buf[self.idx:self.idx + m].copy()
            out[pos:pos + m] = seg
            filt, self.zi = lfilter([1 - d], [1, -d], seg, zi=self.zi)
            self.buf[self.idx:self.idx + m] = x[pos:pos + m] + filt * self.feedback
            self.idx = (self.idx + m) % size
            pos += m
        return out


class _Allpass:
    def __init__(self, size):
        self.buf = np.zeros(size)
        self.idx = 0
        self.g = 0.5

    def process(self, x):
        out = np.empty_like(x)
        size = len(self.buf)
        pos, n = 0, len(x)
        while pos < n:
            m = min(n - pos, size - self.idx)
            bufout = self.buf[self.idx:self.idx + m].copy()
            xin = x[pos:pos + m]
            out[pos:pos + m] = bufout - xin
            self.buf[self.idx:self.idx + m] = xin + bufout * self.g
            self.idx = (self.idx + m) % size
            pos += m
        return out


class _Delay:
    def __init__(self, max_samples):
        self.buf = np.zeros(max_samples + 1)
        self.w = 0
        self.delay = 0

    def process(self, x):
        if self.delay <= 0:
            return x
        size = len(self.buf)
        n = len(x)
        widx = (self.w + np.arange(n)) % size
        self.buf[widx] = x
        out = self.buf[(widx - self.delay) % size]
        self.w = (self.w + n) % size
        return out


class Reverb:
    """Stereo room reverb used as a parallel send ("venue" sound)."""

    def __init__(self, fs: float):
        scale = fs / 44100.0
        self.fs = fs
        self.combs = [[_Comb(int((t + s) * scale)) for t in _COMB_TUNING] for s in (0, _SPREAD)]
        self.allpasses = [[_Allpass(int((t + s) * scale)) for t in _ALLPASS_TUNING] for s in (0, _SPREAD)]
        self.predelay = _Delay(int(fs * 0.25))
        self.tone = FilterBank()
        # keep low rumble and fizz out of the room so it sits behind the mix
        self.tone.set_sections([biquad("highpass", 180, fs), biquad("lowpass", 9000, fs)])
        self.set(0.7, 0.5, 20.0)

    def set(self, size: float, damp: float, predelay_ms: float):
        fb = 0.7 + 0.28 * float(np.clip(size, 0, 1))
        d = 0.05 + 0.6 * float(np.clip(damp, 0, 1))
        for ch in self.combs:
            for c in ch:
                c.feedback, c.damp = fb, d
        self.predelay.delay = int(self.fs * np.clip(predelay_ms, 0, 200) / 1000)

    def process(self, x: np.ndarray) -> np.ndarray:
        mono = (x[:, 0] + x[:, 1]) * 0.015   # Freeverb fixed input gain
        mono = self.predelay.process(mono)
        outs = []
        for ch in range(2):
            acc = np.zeros_like(mono)
            for c in self.combs[ch]:
                acc += c.process(mono)
            for a in self.allpasses[ch]:
                acc = a.process(acc)
            outs.append(acc)
        wet = np.stack(outs, axis=1)
        return self.tone.process(wet)


# ---------------------------------------------------------------------------
# The full chain
# ---------------------------------------------------------------------------

class MixChain:
    """input gain → EQ → compressor → warmth → width → reverb send → balance → limiter → output."""

    def __init__(self, fs: float = 48000.0):
        self.fs = float(fs)
        self._lock = threading.Lock()
        self._pending: dict | None = dict(DEFAULT_PARAMS)
        self.p = dict(DEFAULT_PARAMS)
        self.eq = Equalizer()
        self.comp = Compressor(self.fs)
        self.reverb = Reverb(self.fs)
        self.limiter = Limiter(self.fs)
        # meters (read by the UI)
        self.in_peak = np.zeros(2)
        self.out_peak = np.zeros(2)
        # Windows master volume: (input compensation, output volume) as linear gains
        self._sys_target = (1.0, 1.0)
        self._sys_prev = (1.0, 1.0)
        self._apply_pending()

    def set_system_volume(self, db: float, muted: bool, compensate: bool = True):
        """Follow the Windows master volume (the volume keys).

        Windows applies that volume to CABLE Input *before* Soundstage hears it.
        With compensate=True the attenuation is undone on the way in, so the EQ,
        compressor and limiter always work on full-level audio, and the volume
        is applied at the very end instead. Loudness is unchanged; the mix
        sounds the same at every volume.
        """
        db = float(min(0.0, db))
        vol = 0.0 if muted else float(db_to_lin(db))
        comp = float(db_to_lin(min(-db, 60.0))) if compensate else 1.0
        self._sys_target = (comp, vol)

    # Called from the UI thread
    def set_params(self, params: dict):
        merged = dict(DEFAULT_PARAMS)
        merged.update({k: v for k, v in params.items() if k in DEFAULT_PARAMS})
        with self._lock:
            self._pending = merged

    def _apply_pending(self):
        with self._lock:
            pending, self._pending = self._pending, None
        if pending is None:
            return
        p = self.p = pending
        self.eq.configure(p, self.fs)
        self.comp.set(p["comp_threshold"], p["comp_ratio"], p["comp_attack"],
                      p["comp_release"], p["comp_makeup"])
        self.reverb.set(p["reverb_size"], p["reverb_damp"], p["reverb_predelay"])
        self.limiter.set(p["limiter_ceiling"])
        self._in_gain = float(db_to_lin(p["input_gain"]))
        self._out_gain = float(db_to_lin(p["output_gain"]))

    @property
    def comp_gr(self) -> float:
        return self.comp.gain_reduction if self.p["comp_on"] else 0.0

    @property
    def limiter_gr(self) -> float:
        return self.limiter.gain_reduction if self.p["limiter_on"] else 0.0

    # Called from the audio thread
    def process(self, block: np.ndarray) -> np.ndarray:
        if self._pending is not None:
            self._apply_pending()
        x = np.asarray(block, dtype=np.float64)
        if x.ndim == 1:
            x = np.stack([x, x], axis=1)
        elif x.shape[1] == 1:
            x = np.repeat(x, 2, axis=1)
        elif x.shape[1] > 2:
            x = x[:, :2]
        p = self.p
        if p["bypass"] or len(x) == 0:
            # Windows has already applied its volume; pass through untouched.
            self.in_peak = self.out_peak = np.max(np.abs(x), axis=0) if len(x) else np.zeros(2)
            self._sys_prev = self._sys_target
            return x.astype(np.float32)

        # Smoothly ramp volume changes across the block (no zipper noise).
        (c0, v0), (c1, v1) = self._sys_prev, self._sys_target
        self._sys_prev = (c1, v1)
        ramp = np.linspace(0.0, 1.0, len(x), endpoint=False)[:, None]
        x = x * (c0 + (c1 - c0) * ramp)
        self.in_peak = np.max(np.abs(x), axis=0)

        x = x * self._in_gain
        x = self.eq.process(x)
        if p["comp_on"]:
            x = self.comp.process(x)
        x = saturate(x, p["warmth"])
        x = stereo_width(x, p["width"])
        if p["reverb_on"] and p["reverb_mix"] > 0:
            wet = self.reverb.process(x)
            mix = float(np.clip(p["reverb_mix"], 0, 1))
            # equal-ish power: keep the dry signal strong, the room behind it
            x = x * (1 - 0.5 * mix) + wet * (mix * 2.5)
        x = balance(x, p["balance"])
        x = x * self._out_gain
        if p["limiter_on"]:
            x = self.limiter.process(x)
        else:
            x = np.clip(x, -1.0, 1.0)
        x = x * (v0 + (v1 - v0) * ramp)
        self.out_peak = np.max(np.abs(x), axis=0)
        return x.astype(np.float32)
