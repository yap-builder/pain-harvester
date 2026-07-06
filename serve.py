#!/usr/bin/env python3
"""Живой сервер reddit-pain на :8772 — чистый список + кнопка прогона.

Без JS: интерактив через ссылки + <meta refresh> (смотрелка не исполняет скрипты).
Тонкий слой поверх reddit_ai_score (вся логика/рендер — там, под тестами).
Маршруты:
  GET /                 → чистый AI-список (боль-заголовком) + полоска + история
  GET /run              → фоновый прогон (если не идёт), редирект на /
  GET /<file>           → статика из out/ (слой 1: reddit-pain.html и т.д.)
"""
import datetime
import http.server
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")
AI_JSON = os.path.join(OUT, "reddit-pain-ai.json")
RUNS_JSON = os.path.join(OUT, "ai-runs.json")
LOCK = os.path.join(OUT, ".ai-run.lock")
SCRIPT = os.path.join(HERE, "reddit_ai_score.py")

sys.path.insert(0, HERE)
import reddit_ai_score as scorer  # noqa: E402


def _load(path, default):
    try:
        return json.load(open(path, encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _meta():
    import glob
    items = _load(AI_JSON, [])
    runs = _load(RUNS_JSON, [])
    updated = "?"
    try:
        updated = datetime.datetime.fromtimestamp(os.path.getmtime(AI_JSON)).strftime("%d.%m %H:%M")
    except OSError:
        pass
    digests = sorted(glob.glob(os.path.join(OUT, "*pain-core20.html")))  # последний по дате
    return items, {"updated": updated, "n": len(items),
                   "running": os.path.exists(LOCK), "runs": runs,
                   "digest": os.path.basename(digests[-1]) if digests else ""}


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=OUT, **k)

    def _send_html(self, body, code=200):
        data = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/":
            items, meta = _meta()
            self._send_html(scorer.view_page(items, meta))
            return
        if path == "/run":
            if not os.path.exists(LOCK):       # замок занят → не плодим прогоны
                logf = open(os.path.join(OUT, "ai-run.log"), "a")
                subprocess.Popen([sys.executable, SCRIPT, "--trigger", "manual"],
                                 cwd=HERE, stdout=logf, stderr=logf, start_new_session=True)
                logf.close()                   # ребёнок держит свою копию; без close текла ручка на каждый /run
            self.send_response(302)
            self.send_header("Location", "/")
            self.end_headers()
            return
        return super().do_GET()                # статика из out/

    def log_message(self, *a):                 # тихий лог
        pass


def main():
    port = int(os.environ.get("PORT") or (sys.argv[1] if len(sys.argv) > 1 else 8772))
    httpd = http.server.ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print("reddit-pain serve on :%d  (dir %s)" % (port, OUT))
    httpd.serve_forever()


if __name__ == "__main__":
    main()
