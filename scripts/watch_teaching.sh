#!/bin/bash
# Watch a teaching run live: its own output, what its store now holds, and errors. Ctrl+C stops the view, not the
# run; the view closes by itself once the run has ended.
# Usage: scripts/watch_teaching.sh [run log] [database]   (default: logs/wordnet_production_run.log lyric_db)
cd "$(dirname "$0")/.." || exit 1
RUN_LOG="${1:-logs/wordnet_production_run.log}"
STORE="${2:-lyric_db}"
PSQL=/opt/homebrew/opt/postgresql@16/bin/psql
DB="-h localhost -p 5433 -U stefan -d $STORE -Atc"
while true; do
  clear
  date
  PID=$(pgrep -f "[Pp]ython3? scripts/teach\.py" | head -1)
  ENDED=$([ -z "$PID" ] && echo yes)
  if [ -n "$PID" ]; then
    echo "teaching: RUNNING (process $PID, running for $(ps -o etime= -p "$PID" | tr -d ' '))"
  elif grep -q "Traceback" "$RUN_LOG"; then
    echo "teaching: STOPPED WITH AN ERROR at $(date -r "$RUN_LOG" '+%H:%M'):"
    grep -E "^[A-Za-z]+Error|^[A-Za-z]+Exception" "$RUN_LOG" | tail -n 1
  elif grep -q "session:" "$RUN_LOG"; then
    echo "teaching: FINISHED at $(date -r "$RUN_LOG" '+%H:%M')"
  else
    echo "teaching: NOT RUNNING"
  fi
  echo
  echo "--- the run's own output ---"
  grep -v "Batches\|relation surface\|BertModel\|^Key\|^---\|embeddings\|Notes\|UNEXPECTED\|^$" "$RUN_LOG" | tail -n 6
  echo
  echo "--- what $STORE holds ---"
  $PSQL $DB "select 'word classes: ' || count(*) filter (where tags @> '[\"word_class\"]') || '   language patterns: ' || count(*) filter (where tags @> '[\"language_pattern\"]') || '   memories: ' || count(*) from memory_hot.memory_hot"
  $PSQL $DB "select 'concepts: ' || (select count(*) from unified.concepts) || '   links: ' || (select count(*) from unified.concept_relations) || '   beliefs: ' || (select count(*) from unified.beliefs)"
  echo
  echo "errors in the last 5000 system log lines: $(tail -n 5000 logs/lyric_main.log | grep -c ' - ERROR - ')"
  echo "--- latest activity ---"
  tail -n 3 logs/lyric_main.log | cut -c1-170
  [ -n "$ENDED" ] && break
  sleep 5
done
