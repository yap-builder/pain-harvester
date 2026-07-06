#!/usr/bin/env python3
"""Headless-фетч reddit для pain-harvester (ярус B: автоматизация фетча).

ЗАЧЕМ: раньше reddit собирался ТОЛЬКО вручную через MCP-браузер в сессии — поэтому
вход скорера (`reddit-pain.json`) замерзал, а ночной `--if-changed` честно скипал. Этот
скрипт делает сбор фоновым: headless playwright-WEBKIT (chromium ловит бот-блок reddit
«network security» — webkit проходит js-challenge) обходит /new/ каждого саба, тянет
посты и пишет ЕДИНЫЙ `out/reddit-raw-batch-latest.json` в формате reddit_build.py:
    [{sub, count, posts:[{url, title, comments}]}]
`title` = заголовок + превью тела (по нему скоринг и гейт цитаты). Анонимно, паузами.

Запуск: venv/bin/python reddit_fetch.py   (см. nightly.sh — первый ярус ночной джобы).
"""
import json
import os
import sys
import time

from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")
LATEST = os.path.join(OUT, "reddit-raw-batch-latest.json")

# те же сабы, что и в ручном сборе (AI-агенты / dev-tools / founder / крипта)
SUBS = [
    "SaaS", "SideProject", "indiehackers", "Agent_AI", "ClaudeAI",
    "PromptEngineering", "Appstore", "ArtificialInteligence",
    "buildinpublic", "founder", "languagehub",
]

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
      "(KHTML, like Gecko) Version/17.0 Safari/605.1.15")

# извлекатель ленты: полный заголовок + превью тела из карточки (не обрезанный атрибут)
EXTRACT = r"""() => {
  const posts = [];
  const seen = new Set();
  document.querySelectorAll('shreddit-post').forEach(el => {
    const path = el.getAttribute('permalink') || '';
    if (!path) return;
    const url = (path.startsWith('http') ? path : 'https://www.reddit.com' + path).split('?')[0];
    if (seen.has(url)) return;
    const titleEl = el.querySelector('[slot="title"]');
    let title = (titleEl ? titleEl.textContent : el.getAttribute('post-title') || '').trim();
    const bodyEl = el.querySelector('[slot="text-body"]');
    const body = bodyEl ? bodyEl.textContent.trim().replace(/\s+/g, ' ') : '';
    if (body) title = (title + '\n\n' + body).trim();
    if (title) { seen.add(url); posts.push({ url, title, comments: '' }); }
  });
  return posts;
}"""


def fetch_sub(page, sub, tries=2):
    """Открыть /new/ саба, дождаться ленты, подгрузить скроллом, вернуть посты."""
    url = "https://www.reddit.com/r/%s/new/" % sub
    for attempt in range(1, tries + 1):
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
            page.wait_for_selector("shreddit-post", timeout=20000)
            # лениво-грузящаяся лента: пара скроллов, чтобы набрать ~25 постов
            for _ in range(3):
                page.mouse.wheel(0, 4000)
                page.wait_for_timeout(1200)
            posts = page.evaluate(EXTRACT)
            if posts:
                return posts
        except Exception as e:
            print("  [warn] r/%s попытка %d: %s" % (sub, attempt, str(e)[:110]), file=sys.stderr)
        time.sleep(3)
    return []


def main():
    os.makedirs(OUT, exist_ok=True)
    groups, total = [], 0
    with sync_playwright() as p:
        br = p.webkit.launch(headless=True)
        ctx = br.new_context(user_agent=UA, viewport={"width": 1280, "height": 900}, locale="en-US")
        page = ctx.new_page()
        for i, sub in enumerate(SUBS):
            posts = fetch_sub(page, sub)
            groups.append({"sub": sub, "count": len(posts), "posts": posts})
            total += len(posts)
            print("  r/%-22s %3d постов" % (sub, len(posts)))
            if i + 1 < len(SUBS):
                time.sleep(2.5)  # вежливая пауза между сабами
        br.close()

    ok_subs = sum(1 for g in groups if g["count"] > 0)
    # страховка: пустой сбор НЕ перезаписывает хороший latest (иначе build обнулит вход)
    if total == 0:
        print("ПУСТО: 0 постов со всех сабов — latest не трогаю (бот-блок? сеть?)", file=sys.stderr)
        sys.exit(2)
    json.dump(groups, open(LATEST, "w"), ensure_ascii=False, indent=1)
    print("OK: %d постов из %d/%d сабов → %s" % (total, ok_subs, len(SUBS), os.path.relpath(LATEST, HERE)))


if __name__ == "__main__":
    main()
