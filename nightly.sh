#!/bin/bash
# Ночной END-TO-END pain-harvester (ярус B).
# Раньше ночная джоба гоняла ТОЛЬКО AI-скоринг → вход замерзал, --if-changed вечно скипал.
# Теперь цепочка полная: фетч reddit (headless webkit) + HN/SE → build → AI-score.
# Вызывается из com.me.reddit-ai-nightly.plist в 05:15.
set -u
HERE="/Users/me/pain-harvester"
cd "$HERE" || exit 1
PY="$HERE/venv/bin/python"   # playwright (только для reddit_fetch)
SYS=python3                  # stdlib + вызывает `claude` по подписке

echo "=== $(date '+%F %T') nightly start ==="

# 0. страж висяка: 03.07 reddit_fetch завис на 2 суток и блокировал все следующие ночи.
#    Прошлые экземпляры этого скрипта (кроме себя) добиваем перед стартом.
for pid in $(pgrep -f "bash .*pain-harvester/nightly.sh" 2>/dev/null); do
  [ "$pid" != "$$" ] && kill "$pid" 2>/dev/null && echo "[guard] добил висящий прошлый прогон (pid $pid)"
done
pkill -f "pain-harvester.*reddit_fetch.py" 2>/dev/null && echo "[guard] добил висящий reddit_fetch"

# 1. reddit — headless WEBKIT (chromium ловит бот-блок; пустой сбор НЕ трогает latest → exit 2)
#    perl-alarm = жёсткий потолок 40 мин, чтобы зависший браузер не съедал ночь (timeout на маке нет)
perl -e 'alarm 2400; exec @ARGV' "$PY" reddit_fetch.py || echo "[warn] reddit_fetch не обновил latest (иду на прошлом)"

# 2. HN/SE дайджест (urllib, без venv) → out/<дата>-pain-core20.md
"$SYS" fetch_pain.py --queries @pain-queries.txt --label core20 --out ./out \
  || echo "[warn] fetch_pain (HN/SE) не обновил"
# держим 3 свежих дайджеста, старые уводим из glob (.bak)
ls -1t out/*-pain-core20.md 2>/dev/null | tail -n +4 | while read -r f; do mv "$f" "$f.bak"; done

# 3. эвристический триаж reddit → reddit-pain.json
"$SYS" reddit_build.py || { echo "[err] reddit_build упал"; exit 1; }

# 4. AI-скоринг: умный ежедневный (гонит только если вход изменился с прошлого прогона)
"$SYS" reddit_ai_score.py --if-changed --trigger cron

echo "=== $(date '+%F %T') nightly done ==="
