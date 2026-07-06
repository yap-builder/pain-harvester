# pain-harvester

Scrapes dev communities (Reddit, Hacker News) for posts where people describe real
problems, filters out promo and hallucinated "pain", and compiles a weekly top-5
digest — every pain backed by a verbatim quote from the original post.

I built this because I kept catching LLMs inventing market "pain" that sounded
convincing but didn't exist in the source. This pipeline is my answer: no quote,
no pain.

## How it works

```
reddit_fetch.py   -> anonymous Playwright (WebKit) crawl of 8 subreddits
fetch_pain.py     -> Hacker News (Algolia) + StackExchange, stdlib only, no keys
reddit_build.py   -> deterministic triage: dedup, anti-promo, heuristic pain score
reddit_ai_score.py-> LLM scoring with an evidence gate (see below)
weekly_issue.py   -> weekly issue: dedup into themes, top-5, static HTML/txt
serve.py          -> tiny local server for the live page (no JS on the page)
```

### The three guards (the actual point of this repo)

1. **Verbatim-quote gate.** Every pain must carry a quote copied word-for-word from
   the post *body*. The quote is verified by normalized substring match against the
   source; no match — the pain is discarded. Title echoes are rejected too: quoting
   the headline back is a summary, not evidence.
2. **Deterministic promo pre-filter.** Launch posts ("Show HN", "I built…",
   "Roast my…") are cut by regex *before* any LLM sees them, so self-promo can't
   masquerade as someone's pain.
3. **Validated LLM dedup, no embeddings.** One LLM pass groups pains describing the
   same problem. The response is strictly validated (ids in range, no cross-theme
   duplicates); unnamed groups fall back to singleton themes so nothing is silently
   lost.

Real run (2026-07-02): 157 posts -> 11 promo cut -> 39 pains with verified quotes
-> 17 themes -> top-5.

## Honest status

- Works: the full weekly pipeline end-to-end (fetch -> triage -> score -> issue),
  78 unit tests, runs on a schedule via launchd on my Mac.
- Rough edges: subreddit list and pain queries are hardcoded to my domains
  (AI agents / dev tools / indie SaaS); Reddit crawling needs Playwright WebKit
  (Chromium gets bot-blocked); the LLM steps assume a local `claude` CLI.
- Not included: my scraped data (`out/` is gitignored) — run it yourself.
- Terms of service: Reddit is crawled with a headless browser, which their ToS
  does not welcome — this is a personal research tool, run it accordingly (low
  volume, anonymous read-only, no republishing of full posts). HN is fetched via
  the public Algolia API. StackExchange content is CC BY-SA; it stays in the
  local digest and is excluded from the published issue by default.

## Run

```bash
python3 -m venv venv && venv/bin/pip install playwright pytest && venv/bin/playwright install webkit
python3 reddit_fetch.py            # crawl
python3 reddit_build.py            # triage
python3 reddit_ai_score.py         # LLM scoring (needs `claude` CLI)
python3 weekly_issue.py            # build the weekly issue -> out/weekly/
```

MIT license.
