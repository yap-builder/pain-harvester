#!/usr/bin/env python3
"""Headless reddit fetch for pain-harvester (tier B: fetch automation).

WHY: previously reddit was collected ONLY manually via the MCP browser in a session — so
the scorer's input (`reddit-pain.json`) froze, and the nightly `--if-changed` honestly skipped.
This script makes collection a background job: headless playwright-WEBKIT (chromium hits
reddit's "network security" bot block — webkit passes the js-challenge) walks /new/ of each
sub, pulls posts and writes a SINGLE `out/reddit-raw-batch-latest.json` in reddit_build.py format:
    [{sub, count, posts:[{url, title, comments}]}]
`title` = headline + body preview (used for scoring and the quote gate). Anonymous, with pauses.

Run: venv/bin/python reddit_fetch.py   (see nightly.sh — the first tier of the nightly job).
"""
import json
import os
import sys
import time

from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")
LATEST = os.path.join(OUT, "reddit-raw-batch-latest.json")

# same subs as in the manual collection (AI agents / dev-tools / founder / crypto)
SUBS = [
    "SaaS", "SideProject", "indiehackers", "Agent_AI", "ClaudeAI",
    "PromptEngineering", "Appstore", "ArtificialInteligence",
    "buildinpublic", "founder", "languagehub",
]

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
      "(KHTML, like Gecko) Version/17.0 Safari/605.1.15")

# feed extractor: full title + body preview from the card (not the truncated attribute)
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
    """Open the sub's /new/, wait for the feed, load more by scrolling, return posts."""
    url = "https://www.reddit.com/r/%s/new/" % sub
    for attempt in range(1, tries + 1):
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
            page.wait_for_selector("shreddit-post", timeout=20000)
            # lazily-loading feed: a couple of scrolls to gather ~25 posts
            for _ in range(3):
                page.mouse.wheel(0, 4000)
                page.wait_for_timeout(1200)
            posts = page.evaluate(EXTRACT)
            if posts:
                return posts
        except Exception as e:
            print("  [warn] r/%s attempt %d: %s" % (sub, attempt, str(e)[:110]), file=sys.stderr)
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
            print("  r/%-22s %3d posts" % (sub, len(posts)))
            if i + 1 < len(SUBS):
                time.sleep(2.5)  # polite pause between subs
        br.close()

    ok_subs = sum(1 for g in groups if g["count"] > 0)
    # safeguard: an empty collection does NOT overwrite a good latest (otherwise build would zero the input)
    if total == 0:
        print("EMPTY: 0 posts from all subs — leaving latest untouched (bot block? network?)", file=sys.stderr)
        sys.exit(2)
    json.dump(groups, open(LATEST, "w"), ensure_ascii=False, indent=1)
    print("OK: %d posts from %d/%d subs → %s" % (total, ok_subs, len(SUBS), os.path.relpath(LATEST, HERE)))


if __name__ == "__main__":
    main()
