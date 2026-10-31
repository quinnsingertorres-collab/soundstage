import time

import numpy as np

from soundstage.dsp import DEFAULT_PARAMS, MixChain, biquad
from soundstage.presets import BUILTIN_PRESETS, professional
from scipy.signal import sosfreqz

FS = 48000
BLOCK = 512


def music(seconds=2.0, seed=0):
    rng = np.random.default_rng(seed)
    t = np.arange(int(FS * seconds)) / FS
    tone = 0.3 * np.sin(2 * np.pi * 110 * t) + 0.2 * np.sin(2 * np.pi * 880 * t)
    hits = (np.sin(2 * np.pi * 2 * t) > 0.95) * rng.normal(0, 0.6, t.size)
    left = tone + hits + rng.normal(0, 0.02, t.size)
    right = 0.8 * tone + hits + rng.normal(0, 0.02, t.size)
    return np.stack([left, right], axis=1).astype(np.float32)


def run(chain, x):
    return np.concatenate([chain.process(x[i:i + BLOCK]) for i in range(0, len(x), BLOCK)])


def test_flat_is_transparent():
    chain = MixChain(FS)
    chain.set_params({**DEFAULT_PARAMS, "limiter_on": False})
    x = music() * 0.5
    y = run(chain, x)
    assert np.allclose(np.clip(x, -1, 1), y, atol=1e-5)


def test_bypass():
    chain = MixChain(FS)
    chain.set_params({"bypass": True})
    x = music()
    assert np.allclose(run(chain, x), np.clip(x, -10, 10), atol=1e-6)


def test_eq_gain_at_center():
    sos = biquad("peak", 1000, FS, 6.0, 1.0)[None, :]
    w, h = sosfreqz(sos, worN=[1000], fs=FS)
    assert abs(20 * np.log10(abs(h[0])) - 6.0) < 0.05
    sos = biquad("lowshelf", 100, FS, -4.0)[None, :]
    w, h = sosfreqz(sos, worN=[10], fs=FS)
    assert abs(20 * np.log10(abs(h[0])) + 4.0) < 0.1


def test_every_preset_is_stable_and_under_ceiling():
    x = music(3.0) * 1.5   # hot input on purpose
    for name, p in {**BUILTIN_PRESETS, "pro0": professional(0), "pro1": professional(1, "Arena")}.items():
        chain = MixChain(FS)
        chain.set_params(p)
        y = run(chain, x)
        assert np.isfinite(y).all(), name
        ceiling = 10 ** (p["limiter_ceiling"] / 20) if p["limiter_on"] else 1.0
        assert np.max(np.abs(y)) <= ceiling + 1e-6, name
        assert np.sqrt(np.mean(y ** 2)) > 0.02, name   # still audible


def test_compressor_reduces_dynamics():
    chain = MixChain(FS)
    chain.set_params({"comp_on": True, "comp_threshold": -30, "comp_ratio": 6, "limiter_on": False})
    loud = np.full((FS, 2), 0.5, np.float32)
    y = run(chain, loud)
    assert chain.comp_gr > 5
    assert np.abs(y[-1000:]).mean() < 0.3


def test_reverb_tail_decays():
    chain = MixChain(FS)
    chain.set_params(professional(1.0, "Arena"))
    impulse = np.zeros((FS * 6, 2), np.float32)
    impulse[0] = 0.8
    y = run(chain, impulse)
    early = np.abs(y[FS // 10: FS // 2]).max()
    late = np.abs(y[-FS:]).max()
    assert early > 1e-3          # there is a room
    assert late < early * 0.05   # and it dies away


def test_realtime_speed():
    chain = MixChain(FS)
    chain.set_params(professional(1.0, "Arena"))
    x = music(5.0)
    start = time.perf_counter()
    run(chain, x)
    elapsed = time.perf_counter() - start
    # must run well faster than real time (5 s of audio)
    assert elapsed < 5.0 * 0.35, elapsed
