#!/usr/bin/env bash
# Keep Agla Station up on this laptop for testing and demos: bot + web + tunnel, restarted if it ever exits.
#
#   scripts/run.sh            # run in a Terminal window (not VS Code), leave it open; Ctrl-C stops everything
#
# - caffeinate keeps the Mac awake while this runs (plugged in: no idle or system sleep). Closing the lid still
#   sleeps it unless an external display is attached. Your power settings are not changed.
# - If the app exits or crashes it restarts after a short pause; the tunnel watchdog inside the app already
#   replaces a dead tunnel. A restart gets a new tunnel URL: the bot's Dashboard button follows it, old share
#   links stop working.
# - Output goes to logs/agla.log (gitignored) as well as the terminal.

set -u
cd "$(dirname "$0")/.."
mkdir -p logs
LOG=logs/agla.log
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
