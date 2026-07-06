#!/bin/bash
# управление reddit-pain сервером (launchd): сервер на :8772 + умный-ежедневный крон
HERE="/Users/me/pain-harvester"
LA="$HOME/Library/LaunchAgents"
SRV=com.me.reddit-ai
NIGHT=com.me.reddit-ai-nightly

case "$1" in
  install)
    # снять старый ручной http.server с :8772, если висит
    lsof -ti TCP:8772 -sTCP:LISTEN 2>/dev/null | xargs kill 2>/dev/null || true
    cp "$HERE/$SRV.plist"   "$LA/$SRV.plist"
    cp "$HERE/$NIGHT.plist" "$LA/$NIGHT.plist"
    launchctl unload "$LA/$SRV.plist"   2>/dev/null || true
    launchctl unload "$LA/$NIGHT.plist" 2>/dev/null || true
    launchctl load   "$LA/$SRV.plist"
    launchctl load   "$LA/$NIGHT.plist"
    echo "установлено: сервер :8772 (KeepAlive) + nightly 05:15 (--if-changed)"
    ;;
  uninstall)
    launchctl unload "$LA/$SRV.plist"   2>/dev/null || true
    launchctl unload "$LA/$NIGHT.plist" 2>/dev/null || true
    rm -f "$LA/$SRV.plist" "$LA/$NIGHT.plist"
    echo "снято (плисты удалены, сервер остановлен)"
    ;;
  restart)
    launchctl unload "$LA/$SRV.plist" 2>/dev/null || true
    launchctl load   "$LA/$SRV.plist"
    echo "сервер перезапущен"
    ;;
  status)
    launchctl list | grep -E "reddit-ai" || echo "launchd: не загружен"
    lsof -nP -iTCP:8772 -sTCP:LISTEN 2>/dev/null || echo ":8772 — ничего не слушает"
    ;;
  run)
    cd "$HERE" && python3 reddit_ai_score.py --trigger manual
    ;;
  *)
    echo "usage: $0 {install|uninstall|restart|status|run}"
    ;;
esac
