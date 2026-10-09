# TapControl

Control your Windows 11 laptop by **tapping the desk**. TapControl listens
through your laptop's built-in microphone, recognizes tap patterns in real
time, and executes real system actions (media keys, volume, mute). No
external hardware, no cloud services, no paid APIs.

- 1 tap → Play / Pause media
- 2 quick taps → Next track
- 3 quick taps → Toggle system mute
- 4 quick taps → Volume down (hold-free, single step per gesture)
- 5 quick taps → Volume up

All gestures, tap counts, and timings are configurable in the GUI; settings
are saved to `%APPDATA%\TapControl\config.json`.

---

## Quick start (easiest)

Double-click **`launch.bat`** to start the app, or **`test.bat`** to run the
test suite. Both auto-set the working directory and show errors if Python
or dependencies are missing.

## Requirements

- Windows 10/11 (64-bit)
- Python 3.11 or newer — tested on Python 3.13
- A working microphone (built-in laptop mic is fine)
- Speaker/audio playback app (Spotify, Media Player, etc.) for media gestures

## Installation (PowerShell)

```powershell
# 1. Go to the project folder
cd C:\Users\<you>\Desktop\tapDesk\tapcontrol

# 2. (Optional but recommended) create a virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 3. Install dependencies
pip install -r requirements.txt

# 4. Run the app
python main.py
```

If `Activate.ps1` is blocked by execution policy, run first:
`Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned`

If `pip` lacks Python in PATH, use `python -m pip install -r requirements.txt`.

## Usage

1. Launch: `python main.py` (or `python -m tapcontrol`).
2. Click **Start Listening**.
3. **Calibrate** (recommended): click *Calibrate…*, stay quiet for 2.5 s, then
   tap the desk 4–5 times firmly, roughly once per second.
4. Tap the desk near the laptop:
   - 1 tap → play/pause, 2 quick taps → next track, 3 → mute toggle,
     4 → volume down, 5 → volume up.
5. To close: the × button minimizes to the system tray (taps keep working);
   use tray → **Quit** to exit fully.
6. Global toggle hotkey: **Ctrl+Alt+T** toggles listening on/off.

### CLI (no GUI)

```powershell
python -m tapcontrol devices    # list input devices
python -m tapcontrol selftest   # 3 s mic level check
python -m tapcontrol status     # current settings summary
python -m tapcontrol volup      # send volume +2 once (sanity check)
python -m tapcontrol mute       # toggle system mute once
```

### Settings file

`%APPDATA%\TapControl\config.json` — sample rate, sensitivity, tap intervals,
gesture map, theme, calibration values. Delete it to reset to defaults; the
app never writes outside that folder (plus a startup shortcut you opt into).

## How detection works

1. **Capture** — `sounddevice` runs a non-blocking PortAudio callback that
   only copies 10 ms blocks into a drop-oldest queue (overflow-safe, no locks
   touched).
2. **Signal processing** — a worker thread bandpasses each block
   (150 Hz–4.5 kHz Butterworth, state continuous across block boundaries so
   closely spaced taps are not swallowed), then extracts a fast-attack /
   slow-release energy envelope in dBFS.
3. **Tap detection** — adaptive noise floor (EMA updated only while quiet),
   per-microphone threshold (refined by calibration), rise-time validation
   (taps rise <15 ms; speech/ HVAC do not), a fresh-onset arming flag and a
   refractory/debounce interval stop one physical impact from producing
   several detections.
4. **Gesture grouping** — taps within `max_interval` count together; a
   gesture executes only after the grouping window expires, so 1 tap never
   fires before a possible 2nd tap arrives.
5. **Actions** — fixed identifiers only (`play_pause`, `next_track`,
   `toggle_mute`, `volume_up/down`) executed via the Windows SendInput API
   with VK_MEDIA_* and VK_VOLUME_* virtual keys. Arbitrary shell commands can
   never be triggered by audio events.

## Project layout

```
tapcontrol/
├── main.py                     # launcher (python main.py)
├── requirements.txt
├── tapcontrol.spec             # PyInstaller build for a standalone .exe
└── tapcontrol/
    ├── audio/capture.py        # microphone stream, queue, level, restart
    ├── dsp/signal.py           # bandpass (stateful), envelope helpers
    ├── dsp/detector.py         # noise floor, threshold, peaks, transients
    ├── gestures/recognizer.py  # tap grouping + execute scheduling
    ├── actions/win_actions.py  # SendInput media/volume keys
    ├── actions/dispatcher.py   # optional off-thread action runner
    ├── config/settings.py      # JSON-backed settings dataclasses
    ├── core/pipeline.py        # capture→detect→recognize→execute thread
    ├── core/calibration.py     # wizard state machine
    ├── gui/theme.py            # Win11-style dark/light stylesheets
    ├── gui/panels.py           # level scope widget (meter + threshold)
    ├── gui/window.py           # main window, tabs, tray, hotkey
    └── tests/                  # unittest suite (gesture timing, detection)
```

## Tests

```powershell
python -m unittest discover -s tapcontrol/tests -v
```

Covers gesture grouping/timing (gaps, execute delay, cooldown, disabled and
unknown counts), settings persistence/corruption recovery, and end-to-end
synthetic audio (double tap → one gesture, noise rejection, tap separation).

## Packaging a standalone .exe (optional)

```powershell
pip install pyinstaller
pyinstaller tapcontrol.spec
# → dist\TapControl.exe
```

Note:.first run on another PC still needs mic access allowed in
**Settings → Privacy & security → Microphone** (Windows asks automatically).

## Troubleshooting

| Problem | Fix |
| --- | --- |
| "Could not start microphone" | Check **Settings → Privacy → Microphone → Let desktop apps access your microphone**; pick the right device in the GUI combo; run `python -m tapcontrol devices`. |
| Mic works but no taps detected | Run calibration; raise *Sensitivity*; check the level meter moves when you tap — if not, see next row. |
| Level meter frozen at -80 dBFS | The selected device may be muted in Windows sound settings (input level slider at 0). |
| Volume/mute do nothing, media keys work | Some laptops route volume via a special driver; test manually with `python -m tapcontrol volup`. If that fails, check that the target device is not the HDMI output (Windows mixes per-device). |
| Actions fire while typing/using mouse | Keyboard clatter rejection is on by default; if it still happens, lower *Sensitivity* or raise *Min interval between taps*. |
| Single taps sometimes trigger as "no action" | A count with no configured gesture is ignored by design; configure it in the **Gestures** tab. |
| Double media key presses occur | Cooldown exists; if you still see it (e.g. two mics picking the same tap), increase *Cooldown after gesture*. |
| App does not appear after closing | It minimized to the tray (by design). Use the tray icon → Show window, or uncheck "Minimize to system tray on close". |

## What was not testable on the development machine

- **System tray icon rendering**: the validation runs had no custom icon set
  (`QSystemTrayIcon::setVisible: No Icon set` warning); default Qt icon is
  used. Functionality (menu, minimize) was exercised programmatically.
- **Real media playback response** (Spotify etc. actually pausing): the
  SendInput calls succeed and Windows generates the events, but no media
  player was verified on this machine — please confirm with your player.
- **Launch-on-startup toggle** is stored in settings; wiring to the Windows
  `HKCU\...\Run` key is a stub in this build (documented limitation).
- **Microphone disconnection mid-run** recovery is implemented (restart with
  back-off) but was not physically tested by unplugging a device.

## Windows permission note

Windows shows a microphone permission prompt the first time the app opens an
input stream. If you declined it, re-enable at
**Settings → Privacy & security → Microphone**.
