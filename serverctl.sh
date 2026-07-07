#!/bin/bash
# reddit-pain server control (launchd): server on :8772 + smart-daily cron
HERE="/Users/me/pain-harvester"
LA="$HOME/Library/LaunchAgents"
SRV=com.me.reddit-ai
NIGHT=com.me.reddit-ai-nightly

case "$1" in
  install)
    # take down an old manual http.server on :8772, if hanging around
    lsof -ti TCP:8772 -sTCP:LISTEN 2>/dev/null | xargs kill 2>/dev/null || true
    cp "$HERE/$SRV.plist"   "$LA/$SRV.plist"
    cp "$HERE/$NIGHT.plist" "$LA/$NIGHT.plist"
    launchctl unload "$LA/$SRV.plist"   2>/dev/null || true
    launchctl unload "$LA/$NIGHT.plist" 2>/dev/null || true
    launchctl load   "$LA/$SRV.plist"
    launchctl load   "$LA/$NIGHT.plist"
    echo "installed: server :8772 (KeepAlive) + nightly 05:15 (--if-changed)"
    ;;
  uninstall)
    launchctl unload "$LA/$SRV.plist"   2>/dev/null || true
    launchctl unload "$LA/$NIGHT.plist" 2>/dev/null || true
    rm -f "$LA/$SRV.plist" "$LA/$NIGHT.plist"
    echo "removed (plists deleted, server stopped)"
    ;;
  restart)
    launchctl unload "$LA/$SRV.plist" 2>/dev/null || true
    launchctl load   "$LA/$SRV.plist"
    echo "server restarted"
    ;;
  status)
    launchctl list | grep -E "reddit-ai" || echo "launchd: not loaded"
    lsof -nP -iTCP:8772 -sTCP:LISTEN 2>/dev/null || echo ":8772 — nothing listening"
    ;;
  run)
    cd "$HERE" && python3 reddit_ai_score.py --trigger manual
    ;;
  *)
    echo "usage: $0 {install|uninstall|restart|status|run}"
    ;;
esac
