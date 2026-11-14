#!/usr/bin/env python3
"""Process entry for the MARK desktop app.

Runs the PyQt6 interface from the py_ui tree against the compiled Rust engine.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import faulthandler  # noqa: E402

_FAULT_LOG = Path.home() / ".local" / "state" / "mark" / "crash_fault.log"
_FAULT_LOG.parent.mkdir(parents=True, exist_ok=True)
_fault_handle = open(_FAULT_LOG, "a", buffering=1)
faulthandler.enable(file=_fault_handle, all_threads=True)

from mark.app_entry import main

if __name__ == "__main__":
    raise SystemExit(main())
