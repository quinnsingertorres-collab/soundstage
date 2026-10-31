# Soundstage

A system-wide output mixer for Windows. Everything your PC plays — music, games,
browser, Discord — runs through Soundstage before it reaches your speakers.

- **Apps** — a fader, meter, mute and solo for every program making sound.
- **Mixer** — a full console: 6-band EQ with live curve, compressor, warmth,
  stereo width, room reverb, balance and a brickwall limiter.
- **Professional** — one tap for a mix that sounds mastered and live: tone-matched
  EQ, glue compression, console warmth, a wider stage and a real venue around it
  (Studio, Club, Theater, Arena), with a *Live feel* slider. Hit **Fine-tune in
  mixer** to take it from there.
- Presets (built-in and your own), bypass, tray icon, settings remembered.

## Download

Grab `Soundstage.exe` from the latest release on the Releases page. It's a single
file — no installer. (Windows SmartScreen may warn because the app isn't
code-signed; choose **More info → Run anyway**.)

## One-time setup

1. Install the free [VB-CABLE](https://vb-audio.com/Cable/) driver and restart.
2. Windows **Settings → System → Sound → Output**: choose **CABLE Input**.
3. Open Soundstage. It captures CABLE Output, mixes it, and plays the result on
   your real speakers/headphones (change which in **Settings**).

> While your output is set to CABLE Input, you only hear audio while Soundstage is
> running. Closing the window keeps it mixing in the tray; to stop using it, set
> your Windows output back to your speakers.

## Run from source

```powershell
py -3.12 -m pip install -r requirements.txt
py -3.12 app.py
```

Build the exe yourself:

```powershell
py -3.12 -m pip install pyinstaller
py -3.12 -m PyInstaller --noconfirm --onefile --windowed --name Soundstage --icon assets/soundstage.ico --collect-submodules pycaw --collect-submodules comtypes --collect-data sounddevice app.py
```

Pushing a tag like `v1.0.0` makes GitHub Actions build `Soundstage.exe` and attach
it to a release automatically.

## How it works

`soundstage/dsp.py` is the processing chain (input → EQ → compressor → warmth →
width → reverb send → balance → limiter), vectorised with numpy/scipy so it uses
well under 10% of the audio time budget. `engine.py` moves audio from the virtual
cable to your speakers; `sessions.py` drives per-app volume through the Windows
audio session API.
