#!/usr/bin/env python3
"""The "Collector" — weekly public issue of pain-harvester (P0 #4).

Reads out/reddit-pain-ai.json (pains that passed the verbatim-quote gate), groups
them into themes (one Haiku pass; --no-ai or failure → every pain is its own theme) and writes:
  out/weekly/issue-<YYYY>-W<WW>.json  — issue data (source of truth)
  out/weekly/issue-<YYYY>-W<WW>.txt   — digest for DM (quotes + links, no voice imitation)
  out/weekly/issue-<YYYY>-W<WW>.html  — static page (no JS)
  out/weekly/latest.html              — copy of the latest
Framing: "what the dev community is struggling with this week" — a service to others, no first person.
"""
import argparse
import datetime
import html
import json
import os
import shutil

def safe_url(u):
    """A link from someone else's post goes into href only with an http(s) scheme — otherwise '#' (anti-XSS)."""
    return u if isinstance(u, str) and u.startswith(("http://", "https://")) else "#"

from reddit_ai_score import source_label, run_claude, parse_batch

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")
WEEKLY = os.path.join(OUT, "weekly")
TOP_N = 5


# --- pure logic (tests in test_weekly_issue.py) -----------------------------

def identity_themes(pains):
    """Fallback and v0: every pain is its own theme; label = the pain wording."""
    return [{"label": (p.get("ai_reason") or "").strip() or (p.get("evidence_quote") or "")[:60],
             "members": [i]} for i, p in enumerate(pains)]


THEME_PROMPT = """You group developer pain points into themes.
Below are numbered pains (a short label + a verbatim proof quote). Group pains that
describe THE SAME underlying problem. Return ONLY a JSON array:
[{"theme": "<short label in English, 3-7 words>", "members": [<ids>]}]
Rules: every id appears in AT MOST one group; a pain with no sibling = its own group;
do not invent ids; do not merge unrelated pains.

PAINS:
"""


def build_theme_prompt(pains):
    parts = [THEME_PROMPT]
    for i, p in enumerate(pains):
        parts.append("### PAIN %d\n%s\n%s\n"
                     % (i, (p.get("ai_reason") or "")[:200], (p.get("evidence_quote") or "")[:300]))
    return "\n".join(parts)


def validate_themes(raw, n):
    """Clean the model's answer: only integer ids in [0,n), no repeats across themes,
    groups without a label/members are dropped. Returns (themes, uncovered ids)."""
    seen, out = set(), []
    for t in (raw if isinstance(raw, list) else []):
        if not isinstance(t, dict):
            continue
        label = str(t.get("theme") or "").strip()
        ms = []
        for m in t.get("members") or []:
            if (isinstance(m, int) and not isinstance(m, bool)
                    and 0 <= m < n and m not in seen and m not in ms):
                ms.append(m)
        # ids are marked covered ONLY if the group is kept: members of a dropped
        # (unnamed) group must go to the identity fallback, not vanish from the issue.
        if label and ms:
            seen.update(ms)
            out.append({"label": label, "members": ms})
    uncovered = [i for i in range(n) if i not in seen]
    return out, uncovered


def build_themes(pains, use_ai=True, runner=run_claude):
    """One Haiku pass (CAP: no embeddings). Any failure → identity fallback."""
    if not use_ai:
        return identity_themes(pains)
    try:
        raw = parse_batch(runner(build_theme_prompt(pains)))
        themes, uncovered = validate_themes(raw, len(pains))
        ident = identity_themes(pains)
        return themes + [ident[i] for i in uncovered]
    except Exception as ex:
        print("themes: identity fallback (%s)" % str(ex)[:120])
        return identity_themes(pains)


def representative(theme, pains):
    """Strongest member of the theme: max (ai_score, heuristic score)."""
    best = max(theme["members"],
               key=lambda i: ((pains[i].get("ai_score") or 0), pains[i].get("score", 0)))
    return pains[best]


def issue_data(pains, themes, top_n=TOP_N, week=""):
    """Top-N themes: more people → higher; on a tie — the sharper pain wins."""
    ordered = sorted(themes, key=lambda t: (
        -len(t["members"]),
        -max((pains[i].get("ai_score") or 0) for i in t["members"])))
    out = []
    for t in ordered[:top_n]:
        rep = representative(t, pains)
        out.append({"label": t["label"], "count": len(t["members"]),
                    "quote": rep.get("evidence_quote", ""), "url": rep.get("url", ""),
                    "source": source_label(rep), "ai_score": rep.get("ai_score"),
                    # proof for the counter: "N×" is verifiable only if group members are named (URL of each)
                    "members": [{"url": pains[i].get("url", ""),
                                 "source": source_label(pains[i])} for i in t["members"]]})
    return {"week": week, "pains_total": len(pains), "themes": out}


def render_txt(issue):
    """Digest for DM: bare facts, quotes, links. Not a word in the first person."""
    lines = ["What the dev community is struggling with, week %s — top-%d pains, each with a verbatim quote:"
             % (issue["week"], len(issue["themes"])), ""]
    for i, t in enumerate(issue["themes"], 1):
        cnt = (" (%d people reported this)" % t["count"]) if t["count"] > 1 else ""
        lines.append("%d. %s%s" % (i, t["label"], cnt))
        lines.append('   "%s"' % t["quote"])
        lines.append("   %s" % t["url"])
        lines.append("")
    return "\n".join(lines)


WORDMARK = "PAINWEEKLY"   # placeholder name — replace with the final name (see report)

# N1×N2 skin "warm minimal + brutalist character" (swapped 07-04, his "swipe it" after
# the "noisy" feedback): light airy base, mono only in accents, restrained red.
# No JS, self-contained. The previous N2 brutalism lives in design/ and .bak, easy to bring back.
_BRUTAL_CSS = """
:root{--bg:#fbfbf9;--ink:#0b0b0b;--soft:#54524d;--faint:#9a978e;--line:#e7e5df;--acc:#e8402f}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--ink);
 font:16px/1.58 -apple-system,BlinkMacSystemFont,'Helvetica Neue',system-ui,sans-serif;-webkit-font-smoothing:antialiased}
.wrap{max-width:620px;margin:0 auto;padding:30px 22px 80px}
.brand{display:flex;justify-content:space-between;align-items:center;
 font:700 11px/1 ui-monospace,SFMono-Regular,Menlo,monospace;letter-spacing:2px;text-transform:uppercase}
.brand .m{color:var(--acc)}.brand .e{color:var(--faint)}
h1{font-size:39px;font-weight:800;letter-spacing:-.8px;line-height:1.05;margin:20px 0 16px}
.promise{font-size:16px;line-height:1.5;color:var(--soft);max-width:40ch}
.promise b{color:var(--ink);font-weight:700;box-shadow:inset 0 -8px 0 rgba(232,64,47,.16)}
.hr{border-top:2px solid var(--ink);margin:28px 0 0}
.item{padding:28px 0;border-bottom:1px solid var(--line)}
.kick{font:700 11px/1 ui-monospace,monospace;letter-spacing:.8px;text-transform:uppercase;color:var(--faint);margin-bottom:10px}
.kick .n{color:var(--acc)}
.kick .cnt{color:var(--acc)}
h2{font-size:21px;font-weight:750;line-height:1.3;letter-spacing:-.2px;margin-bottom:10px}
blockquote{font-size:16px;line-height:1.6;color:var(--soft);margin-bottom:12px}
blockquote::before{content:"\\201C"}blockquote::after{content:"\\201D"}
.go{display:inline-block;color:var(--ink);text-decoration:none;
 font:700 12px/1 ui-monospace,monospace;letter-spacing:.5px;text-transform:uppercase;
 border-bottom:2px solid var(--acc);padding-bottom:2px}
.foot{margin-top:34px;font-size:13px;line-height:1.7;color:var(--faint)}
.foot .cta{color:var(--ink);font-size:16px;font-weight:700;margin-bottom:8px}
.foot .cta b{color:var(--acc)}
.foot details.leg{margin-top:14px;border:1.5px solid var(--line);background:#fff}
.foot details.leg summary{cursor:pointer;padding:8px 12px;color:var(--soft);
 font:700 11px/1 ui-monospace,monospace;letter-spacing:.8px;text-transform:uppercase;list-style:none}
.foot details.leg summary::-webkit-details-marker{display:none}
.foot details.leg summary::before{content:"▸ ";color:var(--acc)}
.foot details.leg[open] summary::before{content:"▾ "}
.foot details.leg[open] summary{border-bottom:1.5px solid var(--line)}
.foot details.leg ul{margin:0;padding:10px 12px 12px 28px;line-height:1.8;color:var(--soft)}
.foot details.leg b{color:var(--ink)}
"""


def strip_src_emoji(source):
    """Strip the leading colored dot (🔴/🟠) from the source tag — the N2 skin uses plain text."""
    s = source or ""
    return s.split(" ", 1)[1] if s[:1] in ("\U0001F534", "\U0001F7E0") else s


def render_html(issue):
    """Static issue page, N1×N2 skin (swapped 07-04). No JS,
    self-contained. Quotes and links come only from the source, everything is escaped."""
    e = html.escape
    week = e(issue["week"])
    n = len(issue["themes"])
    items = []
    for i, t in enumerate(issue["themes"], 1):
        cnt = (' &middot; <span class="cnt">%d&times; reported</span>' % t["count"]) if t.get("count", 1) > 1 else ""
        items.append(
            '<article class="item">'
            '<div class="kick"><span class="n">%02d</span> &middot; %s%s</div>'
            '<h2>%s</h2><blockquote>%s</blockquote>'
            '<a class="go" href="%s">Source &#8599;</a></article>'
            % (i, e(strip_src_emoji(t.get("source", ""))), cnt,
               e(t["label"]), e(t.get("quote", "")), e(safe_url(t.get("url", "")))))
    head = ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>%s · week %s</title><style>%s</style></head><body><div class="wrap">'
            % (WORDMARK, week, _BRUTAL_CSS))
    top = ('<div class="brand"><span class="m">&#9670; %s</span>'
           '<span class="e">week %s</span></div>'
           '<h1>What the dev community<br>is struggling with</h1>'
           '<p class="promise">Top-%d pains of the week from Reddit and Hacker News. Each one is '
           'a <b>verbatim quote</b> from the post. No paraphrase, no promo.</p>'
           '<div class="hr"></div>'
           % (WORDMARK, week, n))
    foot = ('<footer class="foot"><div class="cta">Useful? Comes out <b>every week</b>.</div>'
            'Method: verbatim quote from the post body, promo filtered out, similar pains grouped into themes.'
            '<details class="leg"><summary>how to read this page</summary><ul>'
            '<li><b>theme title</b> — a label, grouped by AI</li>'
            '<li><b>quote</b> — word-for-word from the post body, not a paraphrase</li>'
            '<li><b>N&times; reported</b> — how many people wrote about the same thing</li>'
            '<li><b>Source</b> — link to the real post</li>'
            '</ul></details></footer>')
    return head + top + "\n".join(items) + foot + "</div></body></html>"


# --- orchestration -----------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(description="collector: weekly issue of pains")
    ap.add_argument("--in", dest="inp", default=os.path.join(OUT, "reddit-pain-ai.json"))
    ap.add_argument("--top", type=int, default=TOP_N)
    ap.add_argument("--no-ai", action="store_true", help="skip Haiku grouping (identity themes)")
    args = ap.parse_args(argv)

    pains = json.load(open(args.inp, encoding="utf-8"))
    if not pains:
        raise SystemExit("no pains in %s — run reddit_ai_score.py first" % args.inp)
    iso = datetime.date.today().isocalendar()
    week = "%d-W%02d" % (iso[0], iso[1])
    themes = build_themes(pains, use_ai=not args.no_ai)
    issue = issue_data(pains, themes, top_n=args.top, week=week)

    os.makedirs(WEEKLY, exist_ok=True)
    base = os.path.join(WEEKLY, "issue-%s" % week)
    json.dump(issue, open(base + ".json", "w"), ensure_ascii=False, indent=1)
    open(base + ".txt", "w", encoding="utf-8").write(render_txt(issue))
    page = render_html(issue)
    open(base + ".html", "w", encoding="utf-8").write(page)
    shutil.copyfile(base + ".html", os.path.join(WEEKLY, "latest.html"))
    print("OK issue %s: pains %d → themes %d → top-%d · files %s.{json,txt,html}"
          % (week, len(pains), len(themes), len(issue["themes"]), base))


if __name__ == "__main__":
    main()
