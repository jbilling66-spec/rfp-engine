#!/bin/bash
# P12 battery guard (2026-08-16) — protects the benchmark queue on a laptop
# whose charger cannot outpace the load. Observed failure mode: macOS enters
# a battery-safety state ("AC attached; not charging") under sustained CPU
# load and the battery drains toward hard shutdown, which would kill the run
# mid-chunk and risk Docker VM state corruption.
#
# Policy (sawtooth): pause every rfp-extraction-gate container when the
# battery is <= FLOOR%, unconditionally on state text; unpause when recovered
# (>= RESUME%, or macOS reports charged, or >= 75% while in an
# optimized-charging / "not charging" hold). docker pause freezes processes
# in place — no progress is lost and the queue's `docker wait` blocks
# straight through it.
#
# 2026-08-16 fix (the guard was caught not firing at 24%): the original
# pause condition also required the word "discharging", but in the exact
# failure mode this guard exists for the machine drains on AC and pmset
# reads "AC attached; not charging" — "discharging" never appears while
# plugged in. Gate on the measured percent, never the narrative label.
#
# Launch (host, survives the session):
#   nohup docker/battery-guard.sh >> benchmarks/logs/battery-guard.log 2>&1 &
#
# Exits on its own when the queue script is gone and no gate containers
# remain (queue complete or halted). Manual override at any time:
#   docker unpause <name>   # and kill this guard if you want it gone

set -u

IMG="rfp-extraction-gate"
FLOOR=25
RESUME=90
POLL_S=120

note() { echo "[guard $(date '+%F %T')] $*"; }

heartbeat=0

note "started (floor=${FLOOR}%, resume=${RESUME}%, poll=${POLL_S}s)"

while :; do
  batt_line=$(pmset -g batt | grep InternalBattery || true)
  pct=$(echo "$batt_line" | grep -o '[0-9]*%' | head -1 | tr -d '%')
  pct=${pct:-0}

  paused=$(docker ps --filter "ancestor=$IMG" --filter status=paused --format '{{.Names}}')
  running=$(docker ps --filter "ancestor=$IMG" --filter status=running --format '{{.Names}}')

  if [ -n "$paused" ]; then
    if [ "$pct" -ge "$RESUME" ] \
       || echo "$batt_line" | grep -qw 'charged' \
       || { [ "$pct" -ge 75 ] && echo "$batt_line" | grep -q 'not charging'; }; then
      for c in $paused; do docker unpause "$c" && note "UNPAUSED $c at ${pct}%"; done
    else
      note "holding paused at ${pct}% (${batt_line#*)})"
    fi
  elif [ -n "$running" ]; then
    if [ "$pct" -le "$FLOOR" ]; then
      for c in $running; do docker pause "$c" && note "PAUSED $c at ${pct}% (${batt_line})"; done
    else
      heartbeat=$((heartbeat + 1))
      if [ $((heartbeat % 30)) -eq 0 ]; then note "running at ${pct}% (${batt_line})"; fi
    fi
  else
    if ! pgrep -f benchmark-queue.sh > /dev/null 2>&1; then
      note "queue script gone and no gate containers — exiting"
      break
    fi
  fi

  sleep "$POLL_S"
done
