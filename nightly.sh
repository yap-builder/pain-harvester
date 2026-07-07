#!/bin/bash
# Nightly END-TO-END pain-harvester (tier B).
# Previously the nightly job ran ONLY the AI scoring → the input froze, --if-changed skipped forever.
# Now the chain is complete: reddit fetch (headless webkit) + HN/SE → build → AI-score.
# Invoked by com.me.reddit-ai-nightly.plist at 05:15.
set -u
HERE="/Users/me/pain-harvester"
cd "$HERE" || exit 1
PY="$HERE/venv/bin/python"   # playwright (only for reddit_fetch)
SYS=python3                  # stdlib + calls `claude` on the subscription

echo "=== $(date '+%F %T') nightly start ==="

# 0. hang guard: on 03.07 reddit_fetch hung for 2 days and blocked every following night.
#    Previous instances of this script (except ourselves) are killed before starting.
for pid in $(pgrep -f "bash .*pain-harvester/nightly.sh" 2>/dev/null); do
  [ "$pid" != "$$" ] && kill "$pid" 2>/dev/null && echo "[guard] killed a hanging previous run (pid $pid)"
done
pkill -f "pain-harvester.*reddit_fetch.py" 2>/dev/null && echo "[guard] killed a hanging reddit_fetch"

# 1. reddit — headless WEBKIT (chromium hits the bot block; an empty collection does NOT touch latest → exit 2)
#    perl-alarm = hard 40-min ceiling so a hung browser does not eat the night (no timeout on macOS)
perl -e 'alarm 2400; exec @ARGV' "$PY" reddit_fetch.py || echo "[warn] reddit_fetch did not update latest (proceeding with the previous one)"

# 2. HN/SE digest (urllib, no venv) → out/<date>-pain-core20.md
"$SYS" fetch_pain.py --queries @pain-queries.txt --label core20 --out ./out \
  || echo "[warn] fetch_pain (HN/SE) did not update"
# keep 3 fresh digests, move older ones out of the glob (.bak)
ls -1t out/*-pain-core20.md 2>/dev/null | tail -n +4 | while read -r f; do mv "$f" "$f.bak"; done

# 3. heuristic reddit triage → reddit-pain.json
"$SYS" reddit_build.py || { echo "[err] reddit_build failed"; exit 1; }

# 4. AI scoring: smart daily (runs only if the input changed since the last run)
"$SYS" reddit_ai_score.py --if-changed --trigger cron

echo "=== $(date '+%F %T') nightly done ==="
