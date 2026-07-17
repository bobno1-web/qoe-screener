#!/usr/bin/env bash
# ============================================================
#  QoE Normalizer local web app launcher (macOS / Linux) - execution shell.
#  What it does: (1) check Python/deps (2) start web server (3) open browser.
#  Does NOT reimplement the pipeline/web logic - only calls python -m src.web.app.
#  The 2 API keys are entered in the web screen (do NOT put keys in this script).
#
#  Run: in a terminal  ./start_qoe.sh   (first time:  chmod +x start_qoe.sh)
#       On macOS, copy this file to start_qoe.command to enable double-click.
#  Note: on-screen messages are ASCII-only for consistency with the Windows launcher.
# ============================================================
cd "$(dirname "$0")" || exit 1

open_browser() {
  if command -v open >/dev/null 2>&1; then open "http://127.0.0.1:5000"
  elif command -v xdg-open >/dev/null 2>&1; then xdg-open "http://127.0.0.1:5000"
  else echo "  (Could not open the browser automatically. Please open http://127.0.0.1:5000 yourself.)"; fi
}

# --- 1) Python check ---
if command -v python3 >/dev/null 2>&1; then PY=python3
elif command -v python >/dev/null 2>&1; then PY=python
else
  echo "[ERROR] Python 3 not found. Install it from https://www.python.org and run again."
  read -r -p "Press Enter to exit..." _
  exit 1
fi

# --- 2) Dependency check (install once if missing) ---
if ! "$PY" -c "import flask" >/dev/null 2>&1; then
  echo "[INFO] Required libraries are missing. Installing them once..."
  if ! "$PY" -m pip install -r requirements.txt; then
    echo "[ERROR] Failed to install libraries. Run manually: pip install -r requirements.txt"
    read -r -p "Press Enter to exit..." _
    exit 1
  fi
fi

# --- 3) Port 5000 check (if already in use, just open the browser instead) ---
if command -v lsof >/dev/null 2>&1 && lsof -iTCP:5000 -sTCP:LISTEN >/dev/null 2>&1; then
  echo "[INFO] Port 5000 is already in use. The web app may already be running."
  echo "       Opening browser to the existing server: http://127.0.0.1:5000"
  open_browser
  exit 0
fi

# --- 4) Auto-open browser (after server is ready, ~3s) + run server in foreground ---
echo
echo "============================================================"
echo "  QoE Normalizer is running. Keep this window OPEN while using the app."
echo
echo "  Open in browser:  http://127.0.0.1:5000"
echo "  (Your browser will open automatically in a few seconds.)"
echo
echo "  To STOP: close this window (or press Ctrl+C)."
echo
echo "  Enter the 2 keys (OpenDART / Anthropic) in the web screen."
echo "============================================================"
echo
( sleep 3; open_browser ) &
exec "$PY" -m src.web.app
