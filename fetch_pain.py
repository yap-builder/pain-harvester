#!/usr/bin/env python3
"""
fetch_pain.py — pain harvester for Hacker News + StackExchange.

Why: stage 1 of pain-mining (Reddit API is closed to solo devs → pivot to open sources).
Pulls posts/comments matching pain phrases and builds a markdown digest of "pain cards"
for review via /raw in 00-raw.

Principles:
- stdlib only (no pip) — runs on any python3, including on Hermes.
- No API keys needed. StackExchange: 300 requests/day/IP without a key (key optional, raises quota).
- No LLM — pure extraction (judgment happens separately, in /raw).
- DATA LAW: a card = verbatim quote + URL, or it is NOT written. Nothing is invented.

Examples:
  python3 fetch_pain.py --queries "is there a tool for,how do you deal with" --limit 10
  python3 fetch_pain.py --queries @pain-queries.txt --sources hn,se \
        --se-sites stackoverflow --min-points 5 --out ./out --label agents
"""
import argparse
import gzip
import html
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from urllib.parse import urlencode
from urllib.error import URLError, HTTPError

# Etiquette: StackExchange asks for an identifiable User-Agent. Put your own contact here.
USER_AGENT = "pain-harvester/0.1 (personal pain-mining research)"

HN_API = "https://hn.algolia.com/api/v1/search"
SE_API = "https://api.stackexchange.com/2.3/search/advanced"


def _get(url, timeout=25):
    """GET → JSON. Decompresses gzip (SE always compresses; sniff magic bytes just in case)."""
    req = Request(url, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "gzip"})
    with urlopen(req, timeout=timeout) as r:
        raw = r.read()
        enc = r.headers.get("Content-Encoding", "") or ""
    if "gzip" in enc.lower() or raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    return json.loads(raw.decode("utf-8", "replace"))


def clean(text):
    """HTML → flat text, collapse whitespace. Verbatim (no paraphrasing), only markup is stripped."""
    if not text:
        return ""
    text = html.unescape(text)
    text = re.sub(r"(?is)<\s*(script|style)[^>]*>.*?<\s*/\s*\1\s*>", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def epoch_to_date(ts):
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m-%d")
    except (TypeError, ValueError):
        return ""


# ---------- Hacker News (Algolia HN Search API, no key) ----------
def hn_item_url(hit):
    """Card link. Comment → story page with a #comment_id anchor:
    HN aggressively rate-limits direct comment permalinks (HTTP 429, "Sorry."
    page, verified 2026-07-02), while story pages are served fine, and the reader
    gets thread context. The anchor works as long as the comment is on page one."""
    oid = hit.get("objectID")
    story = hit.get("story_id")
    if hit.get("comment_text") and story:
        return f"https://news.ycombinator.com/item?id={story}#{oid}"
    return f"https://news.ycombinator.com/item?id={oid}"


def fetch_hn(query, limit=20, min_points=0, kind="(story,comment)", days=0):
    params = {"query": query, "tags": kind, "hitsPerPage": min(int(limit), 50)}
    nf = []
    if min_points:
        nf.append(f"points>={int(min_points)}")
    if days:
        # freshness: without this filter the "weekly issue" pulled posts from 2023 (caught in review 07-05)
        since = int(datetime.now(timezone.utc).timestamp()) - int(days) * 86400
        nf.append(f"created_at_i>={since}")
    if nf:
        params["numericFilters"] = ",".join(nf)
    data = _get(HN_API + "?" + urlencode(params))
    cards = []
    for h in data.get("hits", []):
        quote = clean(h.get("comment_text") or h.get("story_text") or h.get("title"))
        oid = h.get("objectID")
        if not quote or not oid:
            continue  # no text or no id → no card
        cards.append({
            "source": "HN",
            "title": clean(h.get("story_title") or h.get("title") or ""),
            "quote": quote,
            "url": hn_item_url(h),
            "score": h.get("points"),
            "author": h.get("author"),
            "date": (h.get("created_at") or "")[:10],
            "query": query,
        })
    return cards


# ---------- StackExchange (API 2.3, no key) ----------
def fetch_se(query, site="stackoverflow", limit=20, min_score=0, key=None, days=0):
    params = {
        "order": "desc", "sort": "relevance", "q": query,
        "site": site, "pagesize": min(int(limit), 100), "filter": "withbody",
    }
    if days:
        params["fromdate"] = int(datetime.now(timezone.utc).timestamp()) - int(days) * 86400
    if key:
        params["key"] = key
    data = _get(SE_API + "?" + urlencode(params))
    if data.get("error_message"):
        raise RuntimeError(f"SE error: {data.get('error_message')}")
    cards = []
    for it in data.get("items", []):
        if (it.get("score") or 0) < int(min_score):
            continue
        title = clean(it.get("title"))
        link = it.get("link")
        if not title or not link:
            continue  # no question/URL → no card
        body = clean(it.get("body"))
        cards.append({
            "source": f"SE/{site}",
            "title": title,
            "quote": title,                      # the question itself = verbatim pain signal
            "body_excerpt": body[:400] + ("…" if len(body) > 400 else ""),
            "url": link,
            "score": it.get("score"),
            "author": (it.get("owner") or {}).get("display_name"),
            "date": epoch_to_date(it.get("creation_date")),
            "query": query,
        })
    # politeness towards the SE quota
    if data.get("backoff"):
        time.sleep(int(data["backoff"]) + 1)
    return cards, data.get("quota_remaining")


# ---------- digest ----------
def write_digest(cards, out_dir, label):
    os.makedirs(out_dir, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    safe = re.sub(r"[^a-z0-9_-]+", "-", (label or "pain").lower()).strip("-") or "pain"
    path = os.path.join(out_dir, f"{ts}-pain-{safe}.md")
    out = [
        f"# pain-harvest {ts} — {label or 'all'}",
        f"_autogenerated by `fetch_pain.py` · sources HN+SE · cards: {len(cards)}_",
        "",
        "> rule: every card carries a verbatim quote and a URL. If not — it is not written.",
        "",
    ]
    written = 0
    for c in cards:
        q = (c.get("quote") or "").strip()
        url = c.get("url")
        if not q or not url:
            continue  # double safeguard for the data law
        if len(q) > 600:
            q = q[:600].rstrip() + "…"
        out.append(f"## [{c['source']}] {c.get('title') or '(no title)'}")
        out.append(f"> {q}")
        if c.get("body_excerpt"):
            out.append(f"> ")
            out.append(f"> _body:_ {c['body_excerpt']}")
        meta = f"— score {c.get('score')} · {c.get('date')} · matched `{c.get('query')}`"
        if c.get("author"):
            meta += f" · @{c['author']}"
        out.append(meta)
        out.append(f"{url}")
        out.append("")
        written += 1
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(out))
    return path, written


def load_queries(arg):
    if not arg:
        return []
    if arg.startswith("@"):
        with open(arg[1:], encoding="utf-8") as f:
            return [ln.strip() for ln in f if ln.strip() and not ln.startswith("#")]
    return [q.strip() for q in arg.split(",") if q.strip()]


def main():
    ap = argparse.ArgumentParser(description="Pain-mining fetcher: HN + StackExchange")
    ap.add_argument("--queries", required=True,
                    help="comma-separated phrases OR @file (one phrase per line)")
    ap.add_argument("--sources", default="hn,se", help="hn,se (comma-separated)")
    ap.add_argument("--se-sites", default="stackoverflow",
                    help="comma-separated StackExchange sites (stackoverflow,serverfault,...)")
    ap.add_argument("--limit", type=int, default=20, help="cards per query/source")
    ap.add_argument("--min-points", type=int, default=0, help="HN: minimum points")
    ap.add_argument("--min-score", type=int, default=0, help="SE: minimum score")
    ap.add_argument("--se-key", default=os.environ.get("SE_KEY"),
                    help="StackExchange key (optional, raises quota; otherwise 300/day/IP)")
    ap.add_argument("--out", default="./out", help="digest folder")
    ap.add_argument("--label", default="", help="topic label in the filename")
    ap.add_argument("--sleep", type=float, default=0.5, help="pause between requests, seconds")
    ap.add_argument("--days", type=int, default=14,
                    help="freshness: only posts from the last N days (0 = no filter)")
    args = ap.parse_args()

    queries = load_queries(args.queries)
    if not queries:
        sys.exit("no queries")
    sources = {s.strip() for s in args.sources.split(",") if s.strip()}
    se_sites = [s.strip() for s in args.se_sites.split(",") if s.strip()]

    all_cards, seen = [], set()
    for q in queries:
        if "hn" in sources:
            try:
                for c in fetch_hn(q, args.limit, args.min_points, days=args.days):
                    if c["url"] not in seen:
                        seen.add(c["url"]); all_cards.append(c)
            except (URLError, HTTPError, ValueError, RuntimeError) as e:
                print(f"[warn] HN '{q}': {e}", file=sys.stderr)
            time.sleep(args.sleep)
        if "se" in sources:
            for site in se_sites:
                try:
                    cards, quota = fetch_se(q, site, args.limit, args.min_score, args.se_key, days=args.days)
                    for c in cards:
                        if c["url"] not in seen:
                            seen.add(c["url"]); all_cards.append(c)
                    if quota is not None and quota < 20:
                        print(f"[warn] SE quota low: {quota}", file=sys.stderr)
                except (URLError, HTTPError, ValueError, RuntimeError) as e:
                    print(f"[warn] SE '{q}'@{site}: {e}", file=sys.stderr)
                time.sleep(args.sleep)

    path, written = write_digest(all_cards, args.out, args.label)
    print(f"OK: {written} cards → {path}")


if __name__ == "__main__":
    main()
