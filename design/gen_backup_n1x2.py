#!/usr/bin/env python3
"""N1xN2 hybrid: clean airy base (N1) + raw brutalist character (N2).
demo-issue.json → out/weekly/mockup-n1x2-demo.html. No JS, self-contained."""
import html
import json
import os
import sys

WEEKLY = "/Users/me/pain-harvester/out/weekly"
issue = json.load(open(sys.argv[1], encoding="utf-8"))
e = html.escape
W = e(issue["week"])
N = str(len(issue["themes"]))
MARK = "PAINWEEKLY"


def src(t):
    s = t["source"]
    return s.split(" ", 1)[1] if s[:1] in "\U0001F534\U0001F7E0" else s


CSS = """
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
.hr{border-top:3px solid var(--ink);margin:28px 0 0}
.item{padding:30px 0;border-bottom:1px solid var(--line);display:grid;grid-template-columns:46px 1fr;gap:10px 14px}
.num{grid-row:1/5;font:800 17px/1 ui-monospace,monospace;color:var(--acc);padding-top:5px}
.kick{display:flex;gap:8px;flex-wrap:wrap;font:700 10.5px/1 ui-monospace,monospace;letter-spacing:.8px;text-transform:uppercase}
.chip{border:1.5px solid var(--ink);padding:4px 8px;color:var(--ink)}
.chip.cnt{background:var(--acc);border-color:var(--acc);color:#fff}
h2{font-size:22px;font-weight:750;line-height:1.26;letter-spacing:-.2px}
blockquote{font-size:16.5px;line-height:1.55;color:var(--soft);border-left:4px solid var(--acc);padding-left:14px}
blockquote::before{content:"\\201C"}blockquote::after{content:"\\201D"}
.go{display:inline-block;color:var(--ink);text-decoration:none;
 font:700 12px/1 ui-monospace,monospace;letter-spacing:.5px;text-transform:uppercase;
 border-bottom:2px solid var(--acc);padding-bottom:2px}
.foot{margin-top:34px;font-size:13px;line-height:1.7;color:var(--faint)}
.foot .cta{color:var(--ink);font-size:16px;font-weight:700;margin-bottom:8px}
.foot .cta b{color:var(--acc)}
"""


def rows():
    out = []
    for i, t in enumerate(issue["themes"], 1):
        c = ('<span class="chip cnt">%d&times; reported</span>' % t["count"]) if t.get("count", 1) > 1 else ""
        out.append(
            '<article class="item"><div class="num">%02d</div>'
            '<div class="kick"><span class="chip">%s</span>%s</div>'
            '<h2>%s</h2><blockquote>%s</blockquote>'
            '<a class="go" href="%s">Source &#8599;</a></article>'
            % (i, e(src(t)), c, e(t["label"]), e(t["quote"]), e(t["url"])))
    return "\n".join(out)


inner = ('<div class="brand"><span class="m">&#9670; ' + MARK + '</span>'
         '<span class="e">week ' + W + '</span></div>'
         '<h1>What the dev community<br>is struggling with</h1>'
         '<p class="promise">Top-' + N + ' pains of the week from Reddit and Hacker News. Each one is '
         'a <b>verbatim quote</b> from the post. No paraphrase, no promo.</p>'
         '<div class="hr"></div>' + rows() +
         '<footer class="foot"><div class="cta">Useful? Comes out <b>every week</b>.</div>'
         'Method: verbatim quote from the post body, promo filtered out, similar pains grouped into themes.</footer>')

s = ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
     '<meta name="viewport" content="width=device-width,initial-scale=1">'
     '<title>' + MARK + ' · ' + W + '</title><style>' + CSS + '</style></head>'
     '<body><div class="wrap">' + inner + '</div></body></html>')
p = os.path.join(WEEKLY, "mockup-n1x2-demo.html")
open(p, "w", encoding="utf-8").write(s)
print("wrote", p)
