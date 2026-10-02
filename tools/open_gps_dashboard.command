#!/bin/zsh
# Double-click (or a Desktop link to it) to open the GPS dashboard.
# Close this Terminal window, or press Ctrl+C, to stop the dashboard.

# A dedicated port, not Streamlit's default 8501: other dashboards (e.g. the
# finance one) use that, and "already running" would then open the wrong app.
PORT=8520
URL="http://localhost:$PORT"

# Resolve the real location even when launched through a Desktop symlink, and
# run from the repo root — that's where Streamlit finds the .streamlit/ theme.
REPO="$(cd "$(dirname "$(realpath "$0")")/.." && pwd)"
cd "$REPO" || exit 1

is_up() { [[ "$(curl -s --max-time 1 "$URL/_stcore/health")" == "ok" ]]; }

if is_up; then
  echo "GPS dashboard is already running — opening $URL"
  open "$URL"
  exit 0
fi

if [[ ! -x .venv/bin/streamlit ]]; then
  echo "No virtual environment at $REPO/.venv — see Setup in README.md."
  read -k 1 "?Press any key to close."
  exit 1
fi

# Open the browser once the server answers, instead of guessing a delay.
(
  for _ in {1..60}; do
    is_up && { open "$URL"; exit 0; }
    sleep 0.5
  done
  echo "Dashboard did not start within 30 s — see the messages above."
) &

echo "Starting GPS dashboard at $URL (close this window to stop it)…"
exec .venv/bin/streamlit run dashboards/gps_dashboard.py --server.port "$PORT" --server.headless true
