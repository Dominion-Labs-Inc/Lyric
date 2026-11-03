#!/bin/bash
# Watch a long run live: its own output, what its store now holds, and errors. Ctrl+C stops the view, not the
# run; the view closes by itself once the run has ended.
#
# Serves a teaching pass (`scripts/teach.py`) and a record build (`experiments/TRAIN-FORMAT-03/build.py`) alike:
# what differs between them is only which process to look for and which line says it finished, so both are
# arguments. A build writes a file and never a store, so the store lines simply do not move while one runs --
# that is the view being honest, not the build being stuck.
#
# Usage: scripts/watch_teaching.sh [run log] [database] [process pattern]
#   default: logs/wordnet_production_run.log lyric_db 'scripts/teach\.py'
#   a build:  scripts/watch_teaching.sh logs/ewt_words_build_*.log lyric_db 'TRAIN-FORMAT-03/build\.py'
cd "$(dirname "$0")/.." || exit 1
RUN_LOG="${1:-logs/wordnet_production_run.log}"
STORE="${2:-lyric_db}"
WATCH="${3:-scripts/teach\.py}"
PSQL=/opt/homebrew/opt/postgresql@16/bin/psql
DB="-h localhost -p 5433 -U stefan -d $STORE -Atc"
# The line each kind of run prints when it has finished its work: a teaching pass writes its session file, a build
# says what it wrote. Either means ended well; a Traceback means ended badly.
DONE='session:|^wrote '
while true; do
  clear
  date
  PID=$(pgrep -f "[Pp]ython3? .*$WATCH" | head -1)
  ENDED=$([ -z "$PID" ] && echo yes)
  if [ -n "$PID" ]; then
    echo "running: process $PID, up $(ps -o etime= -p "$PID" | tr -d ' '), $(ps -o %cpu= -p "$PID" | tr -d ' ')% cpu, $(ps -o rss= -p "$PID" | awk '{printf "%.1f GB", $1/1048576}') held"
  elif grep -q "Traceback" "$RUN_LOG"; then
    echo "STOPPED WITH AN ERROR at $(date -r "$RUN_LOG" '+%H:%M'):"
    grep -E "^[A-Za-z]+Error|^[A-Za-z]+Exception" "$RUN_LOG" | tail -n 1
  elif grep -qE "$DONE" "$RUN_LOG"; then
    echo "FINISHED at $(date -r "$RUN_LOG" '+%H:%M')"
  else
    echo "NOT RUNNING"
  fi
  echo
  echo "--- the run's own output ---"
  grep -v "Batches\|relation surface\|BertModel\|^Key\|^---\|embeddings\|Notes\|UNEXPECTED\|^$" "$RUN_LOG" | tail -n 6
  echo
  echo "--- what $STORE holds ---"
  $PSQL $DB "select 'word records: ' || count(*) filter (where tags @> '[\"word_record\"]') || '   sentence records: ' || count(*) filter (where tags @> '[\"sentence_record\"]') || '   word classes: ' || count(*) filter (where tags @> '[\"word_class\"]') || '   memories: ' || count(*) from memory_hot.memory_hot"
  $PSQL $DB "select 'concepts: ' || (select count(*) from unified.concepts) || '   links: ' || (select count(*) from unified.concept_relations) || '   beliefs: ' || (select count(*) from unified.beliefs)"
  echo
  # A build runs with no substrate of its own, so there is no system log to read; a teaching pass has one.
  if [ -f logs/lyric_main.log ]; then
    echo "errors in the last 5000 system log lines: $(tail -n 5000 logs/lyric_main.log | grep -c ' - ERROR - ')"
    echo "--- latest activity ---"
    tail -n 3 logs/lyric_main.log | cut -c1-170
  fi
  [ -n "$ENDED" ] && break
  sleep 5
done
