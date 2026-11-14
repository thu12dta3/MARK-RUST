#!/usr/bin/env bash
# Launches the MARK desktop application: PyQt6 interface + compiled Rust engine.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO="${MARK_RUST_ROOT:-$HERE}"
PY_UI="$REPO/py_ui"
PYTHON="${MARK_PYTHON:-$HOME/MARK/.venv/bin/python}"
[ -x "$PYTHON" ] || PYTHON="$(command -v python3)"
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"

# Build the Rust engine binaries once, so the desktop entry never needs a manual build.
need_build=0
for bin in mark-server mark-vault mark-engineer; do
  [ -x "$REPO/target/release/$bin" ] || need_build=1
done
if [ "$need_build" -eq 1 ] && command -v cargo >/dev/null 2>&1; then
  (cd "$REPO" && cargo build --release --bin mark-server --bin mark-vault --bin mark-engineer >/dev/null 2>&1) || true
fi

export PYTHONPATH="$PY_UI${PYTHONPATH:+:$PYTHONPATH}"
export QT_AUTO_SCREEN_SCALE_FACTOR="${QT_AUTO_SCREEN_SCALE_FACTOR:-1}"

if [ -n "${WAYLAND_DISPLAY:-}" ]; then
  exec "$PYTHON" "$PY_UI/run_mark.py" "$@"
fi
if [ -S "$XDG_RUNTIME_DIR/wayland-1" ]; then
  WAYLAND_DISPLAY=wayland-1 exec "$PYTHON" "$PY_UI/run_mark.py" "$@"
fi
if [ -n "${DISPLAY:-}" ]; then
  exec env -u WAYLAND_DISPLAY "$PYTHON" "$PY_UI/run_mark.py" "$@"
fi
DISPLAY=:0 exec env -u WAYLAND_DISPLAY "$PYTHON" "$PY_UI/run_mark.py" "$@"
