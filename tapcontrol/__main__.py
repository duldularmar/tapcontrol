"""Entry point: python -m tapcontrol (GUI) or python -m tapcontrol <cmd>."""
from __future__ import annotations

import sys
from typing import List

CLI_COMMANDS = ("mute", "unmute", "volup", "voldown", "devices", "status",
                "selftest")


def _run_cli(cmd: str) -> int:
    from .actions import win_actions
    if cmd == "mute":
        ok = win_actions.execute_action("toggle_mute")
        print("toggled mute" if ok else "failed")
        return 0 if ok else 1
    if cmd == "unmute":
        ok = win_actions.execute_action("toggle_mute")
        print("toggled mute" if ok else "failed")
        return 0 if ok else 1
    if cmd == "volup":
        ok = win_actions.execute_action("volume_up")
        print("volume +2" if ok else "failed")
        return 0 if ok else 1
    if cmd == "voldown":
        ok = win_actions.execute_action("volume_down")
        print("volume -2" if ok else "failed")
        return 0 if ok else 1
    if cmd == "devices":
        from .audio.capture import MicrophoneCapture
        for d in MicrophoneCapture().list_input_devices():
            star = "*" if d["default"] else " "
            print(f"{star} {d['index']:>3}  {d['name']} ({d['channels']} ch)")
        return 0
    if cmd == "status":
        from .config.settings import Settings
        s = Settings.load()
        print(f"theme={s.theme} sensitivity={s.sensitivity} "
              f"calibrated={s.calibration.calibrated} "
              f"threshold={s.threshold_dbfs():.1f} dBFS")
        return 0
    if cmd == "selftest":
        return _selftest()
    print(__doc__)
    print("commands:", ", ".join(CLI_COMMANDS))
    return 0


def _selftest() -> int:
    # 3 s microphone level check, no GUI
    import time
    import numpy as np
    from .audio.capture import MicrophoneCapture, rms_to_dbfs
    mic = MicrophoneCapture()
    if not mic.start():
        print("FAIL: microphone did not start:", mic.last_error())
        return 1
    print("Recording 3 s from microphone... make some noise!")
    peak = 0.0
    t0 = time.time()
    while time.time() - t0 < 3.0:
        b = mic.read_block(timeout=0.3)
        if b is not None:
            r = float(np.sqrt(np.mean(np.square(b))) + 1e-12)
            peak = max(peak, r)
    mic.stop()
    ok = peak > 1e-4
    print(f"peak RMS {rms_to_dbfs(peak):.1f} dBFS -> "
          + ("OK" if ok else "WARNING: mic may be muted"))
    return 0 if ok else 1


def main() -> int:
    argv = sys.argv[1:]
    cmd = next((a for a in argv if a in CLI_COMMANDS), None)
    if cmd:
        return _run_cli(cmd)
    if any(a in ("-h", "--help") for a in argv):
        print(__doc__)
        print("commands:", ", ".join(CLI_COMMANDS))
        return 0
    # GUI
    from PySide6.QtWidgets import QApplication
    from .config.settings import Settings
    from .gui.window import MainWindow
    from .gui import theme

    app = QApplication(sys.argv)
    app.setApplicationName("TapControl")
    app.setQuitOnLastWindowClosed(False)
    settings = Settings.load()
    theme.apply_theme(app, settings.theme == "dark")
    win = MainWindow(settings)
    if settings.start_minimized:
        win.hide()
    else:
        win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
