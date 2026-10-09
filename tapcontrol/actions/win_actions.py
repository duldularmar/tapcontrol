"""Windows system actions using native Windows APIs (SendInput).

- Media keys (play/pause, next/prev track) are sent via the SendInput API with
  VK_MEDIA_* virtual key codes.
- Volume / mute use the VK_VOLUME_* multimedia virtual keys, which act on the
  actual Windows master volume (same as the keyboard volume keys) - no window
  focus is needed and no mouse is touched.
- Only fixed action identifiers from settings.KNOWN_ACTIONS are accepted;
  audio events can never trigger arbitrary shell commands.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes

import win32con

# --- SendInput structures -------------------------------------------------
class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG),
                ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.POINTER(wintypes.ULONG))]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
                ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.POINTER(wintypes.ULONG))]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wintypes.DWORD),
                ("wParamL", wintypes.WORD),
                ("wParamH", wintypes.WORD)]


class _INPUTunion(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT),
                ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("union", _INPUTunion)]


KEYEVENTF_KEYUP = 0x0002

# Virtual key codes (winmm / kbd.h)
VK_VOLUME_MUTE = 0xAD
VK_VOLUME_DOWN = 0xAE
VK_VOLUME_UP = 0xAF
VK_MEDIA_PLAY_PAUSE = 0xB3
VK_MEDIA_NEXT_TRACK = 0xB5
VK_MEDIA_PREV_TRACK = 0xB6

MEDIA_KEYS = {
    "play_pause": VK_MEDIA_PLAY_PAUSE,
    "next_track": VK_MEDIA_NEXT_TRACK,
    "prev_track": VK_MEDIA_PREV_TRACK,
}

VOLUME_KEYS = {
    "toggle_mute": VK_VOLUME_MUTE,
    "volume_up": VK_VOLUME_UP,
    "volume_down": VK_VOLUME_DOWN,
}

ACTION_DESCRIPTIONS = {
    "play_pause": "Play / Pause media",
    "next_track": "Next track",
    "prev_track": "Previous track",
    "toggle_mute": "Toggle system mute",
    "volume_up": "Volume up",
    "volume_down": "Volume down",
}


def send_virtual_key(vk: int, repeat: int = 1) -> bool:
    """Press and release a virtual key once (or `repeat` times)."""
    try:
        n = max(1, int(repeat))
        arr = (INPUT * (2 * n))()
        for i in range(n):
            arr[2 * i].type = 1          # INPUT_KEYBOARD
            arr[2 * i].union.ki.wVk = vk
            arr[2 * i + 1].type = 1
            arr[2 * i + 1].union.ki.wVk = vk
            arr[2 * i + 1].union.ki.dwFlags = KEYEVENTF_KEYUP
        sent = ctypes.windll.user32.SendInput(2 * n, arr, ctypes.sizeof(INPUT))
        return sent == 2 * n
    except Exception:
        return False


def send_media_key(action: str) -> bool:
    vk = MEDIA_KEYS.get(action)
    return send_virtual_key(vk) if vk is not None else False


def volume_action(action: str, steps: int = 1) -> bool:
    """volume_up / volume_down / toggle_mute via system volume keys."""
    vk = VOLUME_KEYS.get(action)
    return send_virtual_key(vk, repeat=steps) if vk is not None else False


def execute_action(action: str) -> bool:
    """Execute one fixed logical action. Unrecognized ids are ignored."""
    if action in MEDIA_KEYS:
        return send_media_key(action)
    if action in VOLUME_KEYS:
        return volume_action(action)
    return False


def describe(action: str) -> str:
    return ACTION_DESCRIPTIONS.get(action, action)
