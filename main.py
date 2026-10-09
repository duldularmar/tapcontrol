#!/usr/bin/env python
"""TapControl launcher: python main.py (same as python -m tapcontrol)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tapcontrol.__main__ import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
