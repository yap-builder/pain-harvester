#!/bin/bash
# pain-harvester · недельный «собиратель»: свежий AI-проход (с гейтами) → выпуск → пинок.
# Анти-заморозка: дедлайн стоит на ОТПРАВКЕ, не на сборке — уведомление это и говорит.
set -u
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR" || exit 1
echo "================= $(date '+%Y-%m-%d %H:%M:%S') WEEKLY START ================="
python3 reddit_ai_score.py --trigger weekly 2>&1
echo "--- score rc=$? ---"
python3 weekly_issue.py 2>&1
echo "--- issue rc=$? ---"
osascript -e 'display notification "Выпуск болей готов (out/weekly/latest.html + txt). Отправь до вечера воскресенья." with title "pain-harvester · собиратель"' 2>/dev/null
echo "================= $(date '+%H:%M:%S') WEEKLY DONE ================="
