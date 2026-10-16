#!/bin/bash
# Teach Lyric and watch it, in one command: production (lyric_db, the main model) or the sandbox (lyric_dev).
# Usage: scripts/teach_and_watch.sh production|sandbox [teach.py arguments]   (default: --source wordnet --domain english)
# A run already going is shown, not started again. Ctrl+C closes the view; the run keeps going, and the same
# command shows it again. To stop a run: kill -INT <its pid>, which cancels it where it next gives way.
cd "$(dirname "$0")/.." || exit 1
case "$1" in
  production) STORE=lyric_db ;;
  sandbox) STORE=lyric_dev ;;
  *) echo "usage: scripts/teach_and_watch.sh production|sandbox [teach.py arguments]" >&2; exit 1 ;;
esac
WHERE=$1
shift
ARGS=("$@")
[ ${#ARGS[@]} -eq 0 ] && ARGS=(--source wordnet --domain english)
SOURCE=$(printf '%s\n' "${ARGS[@]}" | grep -A1 -x -- "--source" | tail -n 1)
RUN_LOG="logs/${SOURCE:-teaching}_${WHERE}_run.log"
if pgrep -f "[Pp]ython3? scripts/teach\.py" >/dev/null; then
  echo "a teaching run is already going; showing it"
  sleep 2
else
  # A JOB OF ITS OWN: without job control a script's background command ignores SIGINT, and Python then sets no
  # handler for it, so kill -INT never stopped a run (2026-10-12). Its own process group keeps Ctrl+C in the view
  # from reaching it.
  set -m
  POSTGRES_DATABASE=$STORE PYTHONPATH="$PWD" nohup ./venv_lyric/bin/python3 scripts/teach.py "${ARGS[@]}" \
    > "$RUN_LOG" 2>&1 &
  disown
  echo "teaching started on $WHERE ($STORE): ${ARGS[*]}"
  sleep 2
fi
exec scripts/watch_teaching.sh "$RUN_LOG" "$STORE"
