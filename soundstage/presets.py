"""Built-in presets and the Professional mode macro."""
from __future__ import annotations

from .dsp import DEFAULT_PARAMS

# Venues shape the "space" part of Professional mode.
VENUES = {
    "Studio": dict(reverb_size=0.35, reverb_damp=0.7, reverb_predelay=8.0, room=0.45, width=1.10),
    "Club": dict(reverb_size=0.55, reverb_damp=0.55, reverb_predelay=15.0, room=0.8, width=1.18),
    "Theater": dict(reverb_size=0.72, reverb_damp=0.45, reverb_predelay=24.0, room=1.0, width=1.25),
    "Arena": dict(reverb_size=0.9, reverb_damp=0.35, reverb_predelay=38.0, room=1.2, width=1.35),
}


def professional(live_feel: float = 0.5, venue: str = "Theater") -> dict:
    """A mastered, front-of-house style mix.

    live_feel 0..1 scales how much of the venue and console character comes
    through: 0 is a clean studio master, 1 is a big live room.
    """
    lf = max(0.0, min(1.0, float(live_feel)))
    v = VENUES.get(venue, VENUES["Theater"])
    p = dict(DEFAULT_PARAMS)
    p.update(
        # Tone match: clear the rumble and mud, tame harshness, add air.
        hpf_on=True, hpf_freq=28.0,
        low_gain=1.5 + 1.0 * lf, low_freq=90.0,
        lowmid_gain=-1.5 - 1.0 * lf, lowmid_freq=280.0, lowmid_q=0.9,
        mid_gain=0.0, mid_freq=1000.0, mid_q=0.8,
        highmid_gain=-1.0, highmid_freq=3500.0, highmid_q=1.4,
        high_gain=2.0 + 1.0 * lf, high_freq=11000.0,
        # Glue compression like a mix-bus comp on a live desk.
        comp_on=True, comp_threshold=-20.0 - 4.0 * lf, comp_ratio=2.0 + 1.0 * lf,
        comp_attack=25.0, comp_release=180.0, comp_makeup=2.0 + 1.5 * lf,
        warmth=0.15 + 0.25 * lf,
        width=1.0 + (v["width"] - 1.0) * (0.5 + lf),
        # The room.
        reverb_on=True, reverb_size=v["reverb_size"], reverb_damp=v["reverb_damp"],
        reverb_predelay=v["reverb_predelay"],
        reverb_mix=round((0.03 + 0.14 * lf) * v["room"], 3),
        limiter_on=True, limiter_ceiling=-1.0,
    )
    return p


def _with(**kw) -> dict:
    p = dict(DEFAULT_PARAMS)
    p.update(kw)
    return p


BUILTIN_PRESETS: dict[str, dict] = {
    "Flat": _with(),
    "Bass boost": _with(low_gain=6.0, low_freq=80.0, lowmid_gain=-1.5, lowmid_freq=300.0,
                        comp_on=True, comp_threshold=-16.0, comp_ratio=2.0, comp_makeup=1.0),
    "Vocal clarity": _with(hpf_on=True, hpf_freq=80.0, lowmid_gain=-3.0, lowmid_freq=250.0,
                           highmid_gain=3.0, highmid_freq=3000.0, highmid_q=0.9, high_gain=1.5),
    "Late night": _with(comp_on=True, comp_threshold=-30.0, comp_ratio=4.0, comp_attack=10.0,
                        comp_release=250.0, comp_makeup=8.0, low_gain=-3.0, limiter_ceiling=-3.0),
    "Gaming": _with(low_gain=3.0, lowmid_gain=-2.0, highmid_gain=2.5, highmid_freq=3200.0,
                    width=1.3, comp_on=True, comp_threshold=-22.0, comp_ratio=2.5, comp_makeup=3.0),
    "Concert hall": professional(0.85, "Arena"),
}
