#!/usr/bin/env bash
# Keep Agla Station up on this laptop for testing and demos: bot + web + tunnel, restarted if it ever exits.
#
#   scripts/run.sh               # in a Terminal window; Ctrl-C stops everything (closing the window stops it too)
#   scripts/run.sh --background  # detached: keeps running after you close the Terminal (survives window close)
#   scripts/run.sh --stop        # stop a background run cleanly
#   scripts/run.sh --status      # is it running? prints the latest log line
#
# - caffeinate keeps the Mac awake while this runs (plugged in: no idle or system sleep). Closing the lid still
#   sleeps it unless an external display is attached. Your power settings are not changed.
# - If the app exits or crashes it restarts after a short pause; the tunnel watchdog inside the app already
#   replaces a dead tunnel. A restart gets a new tunnel URL: the bot's Dashboard button follows it, old share
#   links stop working.
# - Output goes to logs/agla.log (gitignored), and to the terminal unless running with --background.

set -u
cd "$(dirname "$0")/.."
mkdir -p logs
LOG=logs/agla.log

running() { pgrep -f "scripts/run\.sh$" | grep -v "^$$\$" || true; }  # runners have no arguments
app_pids() {  # the Python process itself, not its `uv run` wrapper (which would forward a second interrupt)
  for p in $(pgrep -f -- "-m agla --tunnel"); do ps -p "$p" -o command= | grep -q "^uv " || echo "$p"; done
}
case "${1:-}" in
  --background)
    if [ -n "$(running)" ]; then echo "Already running (pid $(running | tr '\n' ' ')). scripts/run.sh --stop first."; exit 1; fi
    nohup bash scripts/run.sh >/dev/null 2>&1 &
    echo "Started in the background (pid $!). Log: $LOG  Stop: scripts/run.sh --stop"
    exit 0 ;;
  --stop)
    pids=$(running)
    if [ -z "$pids" ]; then echo "Not running."; exit 0; fi
    kill -TERM $pids                                   # the runner won't restart the app again...
    for p in $(app_pids); do kill -INT "$p"; done     # ...and the app shuts down the bot and tunnel cleanly
    echo "Stopping (pid $pids)."; exit 0 ;;
  --status)
    if [ -n "$(running)" ]; then echo "Running (pid $(running | tr '\n' ' '))."; else echo "Not running."; fi
    grep -E "^20[0-9]{2}-" "$LOG" 2>/dev/null | tail -1; exit 0 ;;
esac
stopping=0
trap 'stopping=1' INT TERM

# keep the Mac awake for as long as this script runs (-i idle, -m disk, -s system sleep on AC power)
caffeinate -ims -w $$ &

delay=5
while [ "$stopping" -eq 0 ]; do
  started=$(date +%s)
  echo "$(date '+%F %T') starting Agla Station" | tee -a "$LOG"
  uv run python -m agla --tunnel 2>&1 | tee -a "$LOG"
  [ "$stopping" -eq 1 ] && break
  # back off if it keeps failing fast (bad .env, no network), reset once it has run for a while
  if [ $(( $(date +%s) - started )) -gt 300 ]; then delay=5; else delay=$(( delay < 300 ? delay * 2 : 300 )); fi
  echo "$(date '+%F %T') Agla Station stopped; restarting in ${delay}s (Ctrl-C to quit)" | tee -a "$LOG"
  sleep "$delay" || break
done
echo "$(date '+%F %T') stopped" | tee -a "$LOG"
