"""Settings and user presets, stored as JSON in %APPDATA%\\Soundstage."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from .dsp import DEFAULT_PARAMS


def config_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    d = base / "Soundstage"
    d.mkdir(parents=True, exist_ok=True)
    return d


DEFAULT_SETTINGS = {
    "mode": "pro",              # "custom" or "pro"
    "venue": "Theater",
    "live_feel": 0.5,
    "params": dict(DEFAULT_PARAMS),
    "preset": "Flat",
    "user_presets": {},
    "output_device": None,      # saved by name; indices change between boots
    "input_device": None,
    "blocksize": 512,
    "close_to_tray": True,
    "geometry": None,
}


class Settings(dict):
    def __init__(self, path: Path | None = None):
        super().__init__(json.loads(json.dumps(DEFAULT_SETTINGS)))
        self.path = path or config_dir() / "settings.json"
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self.update({k: v for k, v in data.items() if k in DEFAULT_SETTINGS})
            params = dict(DEFAULT_PARAMS)
            params.update({k: v for k, v in data.get("params", {}).items() if k in DEFAULT_PARAMS})
            self["params"] = params
        except Exception:
            pass

    def save(self):
        try:
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self, indent=2), encoding="utf-8")
            tmp.replace(self.path)
        except Exception:
            pass
