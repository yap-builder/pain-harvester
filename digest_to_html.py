#!/usr/bin/env python3
"""Конвертер pain-дайджеста (.md от fetch_pain.py) → самодостаточный .html.

Использование:
  python3 digest_to_html.py out/2026-06-23-pain-core20.md
  python3 digest_to_html.py out/2026-06-23-pain-core20.md --out custom.html

Пишет рядом одноимённый .html. Зависимостей нет. Фразы (заготовленные, matched) идут
кнопками-чипами со счётчиком — кликаешь, не печатаешь. Доп.поиск по тексту — опционально.
"""
import argparse
import html
import json
import os
import re
import sys

CARD_RE = re.compile(r"^##\s+\[([^\]]+)\]\s+(.*)$")
META_RE = re.compile(r"^—\s+(.*)$")
MATCHED_RE = re.compile(r"matched\s+`([^`]+)`")


def parse(md_text):
    """Грубый, но устойчивый парс формата fetch_pain.py."""
    cards = []
    cur = None
    for line in md_text.splitlines():
        m = CARD_RE.match(line)
        if m:
            if cur:
                cards.append(cur)
            src = m.group(1)
            cur = {
                "source": src.split("/")[0],          # HN / SE
                "site": src,                            # HN / SE/stackoverflow
                "title": m.group(2).strip(),
                "quote": "", "url": "", "matched": "", "meta": "",
            }
            continue
        if cur is None:
            continue
        if line.startswith(">"):
            cur["quote"] += (" " if cur["quote"] else "") + line.lstrip("> ").rstrip()
        elif META_RE.match(line):
            cur["meta"] = META_RE.match(line).group(1).strip()
            mm = MATCHED_RE.search(line)
            if mm:
                cur["matched"] = mm.group(1)
        elif line.strip().startswith("http"):
            cur["url"] = line.strip()
    if cur:
        cards.append(cur)
    return cards


def _card_html(c):
    e = html.escape
    quote = f'<blockquote class="quote">{e(c["quote"])}</blockquote>' if c["quote"] else ""
    return (
        f'<article class="card">'
        f'<a class="t" href="{e(c["url"])}" target="_blank" rel="noopener">{e(c["title"])}</a>'
        f'<div class="badges"><span class="badge src">{e(c["site"])}</span></div>'
        f'{quote}'
        f'<div class="meta">{e(c["meta"])}</div>'
        f'</article>'
    )


def render(cards, title):
    """Полностью статичный HTML, без JavaScript. Карточки сгруппированы по matched-фразе
    в нативные <details> — разворачиваются кликом, работают в любой смотрелке."""
    e = html.escape
    groups = {}
    for c in cards:
        groups.setdefault(c["matched"] or "(без фразы)", []).append(c)
    # фразы по убыванию числа карточек
    order = sorted(groups, key=lambda k: -len(groups[k]))

    sections = []
    for i, phr in enumerate(order):
        cs = groups[phr]
        hn = sum(1 for c in cs if c["source"] == "HN")
        se = sum(1 for c in cs if c["source"] == "SE")
        bits = []
        if hn:
            bits.append(f"HN&nbsp;{hn}")
        if se:
            bits.append(f"SE&nbsp;{se}")
        sub = " · ".join(bits)
        body = "".join(_card_html(c) for c in cs)
        op = " open" if i == 0 else ""
        sections.append(
            f'<details{op}><summary><span class="ph">{e(phr)}</span>'
            f'<span class="n">{sub}</span></summary>{body}</details>'
        )
    body = "\n".join(sections)

    return f"""<!doctype html><html lang="ru"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(title)}</title>
<style>
:root{{color-scheme:dark}}
*{{box-sizing:border-box}}
body{{margin:0;font:15px/1.5 -apple-system,system-ui,sans-serif;background:#0d1117;color:#e6edf3}}
header{{background:#161b22;border-bottom:1px solid #30363d;padding:14px 16px}}
h1{{font-size:16px;margin:0}}
.sub{{font-size:12px;color:#8b949e;margin-top:5px}}
main{{padding:10px 14px;max-width:820px;margin:0 auto}}
details{{background:#161b22;border:1px solid #30363d;border-radius:10px;margin:0 0 9px;overflow:hidden}}
summary{{cursor:pointer;padding:12px 14px;font-weight:600;display:flex;justify-content:space-between;align-items:center;gap:10px;list-style:none}}
summary::-webkit-details-marker{{display:none}}
summary::before{{content:"▸";color:#8b949e;margin-right:8px;font-weight:400}}
details[open] summary::before{{content:"▾"}}
.ph{{flex:1}}
.n{{font-size:11px;color:#7ee787;font-weight:600;white-space:nowrap}}
.card{{border-top:1px solid #21262d;padding:12px 14px}}
.card a.t{{color:#58a6ff;text-decoration:none;font-weight:600;font-size:14.5px}}
.badges{{margin:6px 0}}
.badge{{font-size:11px;padding:2px 7px;border-radius:20px;background:#21262d;color:#d2a8ff;border:1px solid #553098}}
.quote{{color:#adbac7;font-size:13px;margin:6px 0 0;border-left:2px solid #30363d;padding:0 0 0 10px}}
.meta{{color:#6e7681;font-size:11px;margin-top:6px}}
</style></head><body>
<header><h1>{e(title)}</h1>
<div class="sub">{len(cards)} карточек · сгруппировано по фразам · тапни фразу, чтобы раскрыть · без скриптов</div>
</header>
<main>
{body}
</main>
</body></html>"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("md")
    ap.add_argument("--out", default="")
    args = ap.parse_args()
    if not os.path.isfile(args.md):
        sys.exit(f"нет файла: {args.md}")
    with open(args.md, encoding="utf-8") as f:
        text = f.read()
    cards = parse(text)
    if not cards:
        sys.exit("карточки не распознаны — формат дайджеста другой?")
    title = text.splitlines()[0].lstrip("# ").strip() or "pain digest"
    out = args.out or os.path.splitext(args.md)[0] + ".html"
    with open(out, "w", encoding="utf-8") as f:
        f.write(render(cards, title))
    print(f"OK: {len(cards)} карточек → {out}")


if __name__ == "__main__":
    main()
