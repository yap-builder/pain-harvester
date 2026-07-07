#!/bin/bash
# pain-harvester · weekly "collector": fresh AI pass (with gates) → issue → nudge.
# Anti-freeze: the deadline sits on SENDING, not on assembling — the notification says exactly that.
set -u
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR" || exit 1
echo "================= $(date '+%Y-%m-%d %H:%M:%S') WEEKLY START ================="
python3 reddit_ai_score.py --trigger weekly 2>&1
echo "--- score rc=$? ---"
python3 weekly_issue.py 2>&1
echo "--- issue rc=$? ---"
osascript -e 'display notification "The pain issue is ready (out/weekly/latest.html + txt). Send it before Sunday evening." with title "pain-harvester · collector"' 2>/dev/null
echo "================= $(date '+%H:%M:%S') WEEKLY DONE ================="
