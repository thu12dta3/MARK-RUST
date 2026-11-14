#!/usr/bin/env bash
set -euo pipefail
BIN="${MARK_BIN:-$HOME/.local/bin/mark}"
[ -x "$BIN" ] || BIN="$HOME/MARK-RUST/target/release/mark-app"
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
if [ -n "${WAYLAND_DISPLAY:-}" ]; then
  exec "$BIN" "$@"
fi
if [ -S "$XDG_RUNTIME_DIR/wayland-1" ]; then
  WAYLAND_DISPLAY=wayland-1 exec "$BIN" "$@"
fi
if [ -n "${DISPLAY:-}" ]; then
  exec env -u WAYLAND_DISPLAY "$BIN" "$@"
fi
DISPLAY=:0 exec env -u WAYLAND_DISPLAY "$BIN" "$@"
