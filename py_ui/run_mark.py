#!/usr/bin/env python3
"""Process entry for the MARK desktop app.

Runs the PyQt6 interface from the py_ui tree against the compiled Rust engine.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mark.app_entry import main

if __name__ == "__main__":
    raise SystemExit(main())
