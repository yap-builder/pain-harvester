#!/usr/bin/env python3
"""«Собиратель» — недельный внешний выпуск pain-harvester (P0 #4).

Читает out/reddit-pain-ai.json (боли, прошедшие гейт дословной цитаты), группирует
в темы (Haiku один проход; --no-ai или сбой → каждая боль сама себе тема) и пишет:
  out/weekly/issue-<YYYY>-W<WW>.json  — данные выпуска (источник правды)
  out/weekly/issue-<YYYY>-W<WW>.txt   — выжимка для DM (цитаты + ссылки, без имитации голоса)
  out/weekly/issue-<YYYY>-W<WW>.html  — статичная страница (без JS)
  out/weekly/latest.html              — копия свежего
Рамка текста: «с чем бьётся dev-сообщество на неделе» — сервис другим, без первого лица.
"""
import argparse
import datetime
import html
import json
import os
import shutil

def safe_url(u):
    """Ссылка из чужого поста идёт в href только с http(s)-схемой — иначе '#' (анти-XSS)."""
    return u if isinstance(u, str) and u.startswith(("http://", "https://")) else "#"

from reddit_ai_score import source_label, run_claude, parse_batch

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")
WEEKLY = os.path.join(OUT, "weekly")
TOP_N = 5


# --- чистая логика (тесты в test_weekly_issue.py) ---------------------------

def identity_themes(pains):
    """Фолбэк и v0: каждая боль — своя тема; ярлык = формулировка боли."""
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
    """Чистим ответ модели: только целые id в [0,n), без повторов между темами,
    группы без ярлыка/членов выбрасываются. Возвращает (темы, непокрытые id)."""
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
        # id помечаем покрытыми ТОЛЬКО если группа сохранена: члены выброшенной
        # (безымянной) группы должны уйти в identity-фолбэк, а не пропасть из выпуска.
        if label and ms:
            seen.update(ms)
            out.append({"label": label, "members": ms})
    uncovered = [i for i in range(n) if i not in seen]
    return out, uncovered


def build_themes(pains, use_ai=True, runner=run_claude):
    """Один Haiku-проход (КАП: без embeddings). Любой сбой → identity-фолбэк."""
    if not use_ai:
        return identity_themes(pains)
    try:
        raw = parse_batch(runner(build_theme_prompt(pains)))
        themes, uncovered = validate_themes(raw, len(pains))
        ident = identity_themes(pains)
        return themes + [ident[i] for i in uncovered]
    except Exception as ex:
        print("темы: фолбэк identity (%s)" % str(ex)[:120])
        return identity_themes(pains)


def representative(theme, pains):
    """Сильнейший член темы: max (ai_score, эвристический score)."""
    best = max(theme["members"],
               key=lambda i: ((pains[i].get("ai_score") or 0), pains[i].get("score", 0)))
    return pains[best]


def issue_data(pains, themes, top_n=TOP_N, week=""):
    """Топ-N тем: больше людей → выше; при равенстве — острее боль."""
    ordered = sorted(themes, key=lambda t: (
        -len(t["members"]),
        -max((pains[i].get("ai_score") or 0) for i in t["members"])))
    out = []
    for t in ordered[:top_n]:
        rep = representative(t, pains)
        out.append({"label": t["label"], "count": len(t["members"]),
                    "quote": rep.get("evidence_quote", ""), "url": rep.get("url", ""),
                    "source": source_label(rep), "ai_score": rep.get("ai_score"),
                    # пруф счётчика: «N×» проверяемо только если члены группы названы (URL каждого)
                    "members": [{"url": pains[i].get("url", ""),
                                 "source": source_label(pains[i])} for i in t["members"]]})
    return {"week": week, "pains_total": len(pains), "themes": out}


def render_txt(issue):
    """Выжимка для DM: голые факты, цитаты, ссылки. Ни слова от первого лица."""
    lines = ["What the dev community is struggling with, week %s — top-%d pains, each with a verbatim quote:"
             % (issue["week"], len(issue["themes"])), ""]
    for i, t in enumerate(issue["themes"], 1):
        cnt = (" (%d people reported this)" % t["count"]) if t["count"] > 1 else ""
        lines.append("%d. %s%s" % (i, t["label"], cnt))
        lines.append('   "%s"' % t["quote"])
        lines.append("   %s" % t["url"])
        lines.append("")
    return "\n".join(lines)


WORDMARK = "PAINWEEKLY"   # плейсхолдер названия — заменить на финальное имя (см. отчёт)

# Скин N1×N2 «тёплый минимал + брутал-характер» (свап 07-04, его «свайпай» после
# фидбэка «шумно»): светлая воздушная база, моно только в акцентах, красный сдержанный.
# Без JS, самодостаточно. Прежний N2-брутализм — в design/ и .bak, вернуть легко.
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
    """Снять ведущий цветной кружок (🔴/🟠) из тега источника — в N2-скине чистый текст."""
    s = source or ""
    return s.split(" ", 1)[1] if s[:1] in ("\U0001F534", "\U0001F7E0") else s


def render_html(issue):
    """Статичная страница выпуска, скин N1×N2 (свап 07-04). Без JS,
    самодостаточно. Цитаты и ссылки — только из источника, всё экранируется."""
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


# --- оркестрация -------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(description="собиратель: недельный выпуск болей")
    ap.add_argument("--in", dest="inp", default=os.path.join(OUT, "reddit-pain-ai.json"))
    ap.add_argument("--top", type=int, default=TOP_N)
    ap.add_argument("--no-ai", action="store_true", help="без Haiku-группировки (identity-темы)")
    args = ap.parse_args(argv)

    pains = json.load(open(args.inp, encoding="utf-8"))
    if not pains:
        raise SystemExit("нет болей в %s — сперва прогони reddit_ai_score.py" % args.inp)
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
    print("OK выпуск %s: болей %d → тем %d → топ-%d · файлы %s.{json,txt,html}"
          % (week, len(pains), len(themes), len(issue["themes"]), base))


if __name__ == "__main__":
    main()
