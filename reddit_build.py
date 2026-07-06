#!/usr/bin/env python3
"""Сборка + ЭВРИСТИЧЕСКИЙ триаж собранных reddit-постов.

Вход:  out/reddit-raw-batch*.json  (группы [{sub,count,posts:[{url,title,comments}]}])
Выход: out/reddit-pain.json  (обогащённый score+why+sources)
       out/reddit-pain.html  (статичная no-JS телефонная страница: 🔥Кандидаты/Посмотреть/Шум)

Скоринг детерминированный и прозрачный — каждый балл объясним словами (никакого AI-вайба).
AI-скорер НЕ используется (решение субагента: эвристики закрывают ~80%; AI — опционально
вторым проходом по верхушке, если эта планка после боевого прогона окажется мала).
"""
import glob
import html
import json
import os
import re
import sys

def safe_url(u):
    """Ссылка из чужого поста идёт в href только с http(s)-схемой — иначе '#' (анти-XSS)."""
    return u if isinstance(u, str) and u.startswith(("http://", "https://")) else "#"

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")

PAIN = re.compile(r"\b(keep|can'?t|cannot|struggl|tired of|wish (there|i)|how (do|to)|"
                  r"is there a (tool|way|better)|spent (days|hours|weeks|months)|fail|broke|"
                  r"hate|frustrat|stuck|no idea|need (help|advice)|anyone else|why (is|does)|"
                  r"problem|annoying|painful|impossible|nightmare|workaround|drowning)", re.I)
DOMAIN = re.compile(r"\b(agent|llm|claude|gpt|prompt|context window|\bmodel\b|automat|\bapi\b|"
                    r"saas|\busers?\b|customer|churn|\bmrr\b|leads?|sign[ -]?up|onboard|"
                    r"integrat|workflow|\bbot\b|trading|crypto|\bmcp\b|\brag\b|scrap|dataset|"
                    r"fine[ -]?tun|deploy|cofounder|founder)", re.I)
PROMO = re.compile(r"^(show hn|launching|introducing|i built|i made|i just (built|launch|made|ship)|"
                   r"i'?ve (built|made|launch)|day \d+ of|first app|\[promo)", re.I)
PROMO_BODY = re.compile(r"(check (it|us) out|try it (out|now)|i run a (site|tool)|"
                        r"https?://[^\s]+\.(vercel|app|co|io|dev|xyz|space)|feedback on (my|new))", re.I)
# раскрытый спрос: человек УЖЕ платит / купил / уходит с инструмента — не «вот бы такое»
PAY = re.compile(r"(\$\s?\d|\b\d+\s?(usd|/mo|/month|/yr|per month|per year|a month|a year)\b|"
                 r"\bpaid\b|\bpaying\b|\bpay(s|ing)? for\b|\bi pay\b|\bwe pay\b|subscri|"
                 r"\bbought\b|purchas|switch(ing|ed)? from|migrat(e|ed|ing) (from|off)|"
                 r"currently (use|using|on|pay)|cancel(led|ling|s)?|too expensive|"
                 r"overpriced|pricing|retainer)", re.I)


def norm(t):
    return re.sub(r"[^a-z0-9 ]", "", t.lower()).strip()[:80]


def load_all():
    by_url, dupes = {}, {}
    for f in sorted(glob.glob(os.path.join(OUT, "reddit-raw-batch*.json"))):
        for g in json.load(open(f, encoding="utf-8")):
            sub = g.get("sub", "?")
            for p in g.get("posts", []):
                url = (p.get("url") or "").split("?")[0]
                title = (p.get("title") or "").strip()
                if not url or not title:
                    continue
                if url not in by_url:
                    by_url[url] = {"sub": sub, "title": title, "url": url,
                                   "comments": p.get("comments", ""), "sources": {sub}}
                else:
                    by_url[url]["sources"].add(sub)
    # схлопнуть кросс-посты по нормализованному заголовку
    by_norm = {}
    for it in by_url.values():
        k = norm(it["title"])
        if k in by_norm:
            by_norm[k]["sources"] |= it["sources"]
        else:
            by_norm[k] = it
    return list(by_norm.values())


def score(it):
    t = it["title"]
    why, s = [], 0
    has_pay = bool(PAY.search(t))
    if has_pay:
        s += 3; why.append("уже платят +3")
    has_pain = bool(PAIN.search(t))
    if has_pain:
        s += 2; why.append("боль-маркер +2")
    has_dom = bool(DOMAIN.search(t))
    if has_dom:
        s += 2; why.append("домен +2")
    extra = min(len(it["sources"]) - 1, 3)
    if extra > 0:
        s += extra; why.append(f"×{len(it['sources'])} кросспост +{extra}")
    try:
        c = float(re.sub(r"[^\d.]", "", it["comments"]) or 0)
        if "k" in it["comments"].lower():
            c *= 1000
        if c >= 5:
            s += 1; why.append(f"💬{it['comments']} +1")
    except ValueError:
        pass
    promo = bool(PROMO.search(t) or PROMO_BODY.search(t))
    # раскрытый платёж перебивает «похоже на рекламу»: это сигнал спроса, не питч
    if promo and not has_pay:
        s -= 3; why.append("реклама −3")
    if not has_dom:
        s -= 2; why.append("вне домена −2")
    it["pay"] = has_pay
    it["pain"] = has_pain
    it["dom"] = has_dom
    it["score"] = s
    it["why"] = " · ".join(why) or "нет сигналов"
    if (promo and not has_pay) or s <= 0:
        it["bucket"] = "noise"
    elif s >= 3:
        it["bucket"] = "cand"
    else:
        it["bucket"] = "look"
    return it


# тематические кластеры кандидатов — ПОРЯДОК ВАЖЕН (первое совпадение выигрывает):
# специфичные темы идут раньше широкого «маркетинга», иначе он всё поглощает.
# тема = поверхностные слова, тут regex надёжен (в отличие от «голоса автора»).
THEMES = [
    ("Агенты / LLM",         re.compile(r"\b(agent|llm|claude|gpt|prompt|rag|mcp|fine[- ]?tun|context window|ai model|language model)", re.I)),
    ("Деплой / инфра / API", re.compile(r"\b(deploy|infra|api|integrat|workflow|scrap|dataset|hosting|server|database)", re.I)),
    ("Отток / удержание",    re.compile(r"\b(churn|reten|cancel|retain|onboard|activation)", re.I)),
    ("Деньги / прайсинг",    re.compile(r"\b(mrr|pricing|revenue|subscri|monetiz|too expensive|overpriced|\$\s?\d)", re.I)),
    ("Кофаундер / команда",  re.compile(r"\b(cofounder|co-founder|hire|hiring|team|partner)", re.I)),
    ("Запуск / валидация",   re.compile(r"\b(launch|validat|product hunt|first (user|customer|sale)|mvp)", re.I)),
    ("Лиды / маркетинг",     re.compile(r"\b(lead|signup|sign[- ]?up|marketing|seo|ads?|traffic|growth|audience|outreach|cold email)", re.I)),
]


def theme_of(title):
    """Возвращает имя темы кандидата по первому совпавшему словарю, иначе 'Прочее'."""
    for name, rx in THEMES:
        if rx.search(title):
            return name
    return "Прочее"


def highlight_sentence(text):
    """Возвращает HTML: контекстное ОКНО вокруг первого PAIN/PAY маркера, маркер в <mark>.

    Алгоритм:
    1. Ищем ПЕРВОЕ совпадение (по позиции) среди PAIN и PAY, расширяем до целого слова.
    2. Берём ~95 симв контекста с каждой стороны, втягивая СОСЕДНИЕ предложения —
       чтобы короткий маркер вроде «Yet, I'm stuck.» не остался без сути.
    3. Края режем по границам предложений/слов, ставим «…» если обрезали.
    4. Делим сырой текст на (before/match/after), экранируем по отдельности, вставляем <mark>.
    5. Если совпадений нет — возвращаем None (вызывающий делает fallback).
    """
    # ищем первое совпадение из PAIN и PAY по позиции в тексте
    m_pain = PAIN.search(text)
    m_pay  = PAY.search(text)
    if m_pain and m_pay:
        m = m_pain if m_pain.start() <= m_pay.start() else m_pay
    elif m_pain:
        m = m_pain
    elif m_pay:
        m = m_pay
    else:
        return None

    ms, me = m.start(), m.end()

    # расширяем маркер до границ цельного слова (регэкспы ловят основы:
    # struggl→struggling, subscri→subscription) — иначе подсветка рвёт слово
    while ms > 0 and (text[ms - 1].isalnum() or text[ms - 1] == "'"):
        ms -= 1
    while me < len(text) and (text[me].isalnum() or text[me] == "'"):
        me += 1

    # --- контекстное окно вокруг маркера (соседние предложения, не голое предложение) ---
    CTX = 95          # симв контекста с каждой стороны
    MINSIDE = 35      # если граница предложения оставляет меньше — тянем жёстким окном
    sent_delim = re.compile(r'[.!?\n]')

    # левая граница: входим в окно [ms-CTX, ms) и стартуем с ПЕРВОГО целого
    # предложения внутри него — так тянем контекст, а не обрезаем у маркера
    seg_start = max(0, ms - CTX)
    dm = sent_delim.search(text, seg_start, ms)
    if dm:
        left = dm.end()
    else:
        left = seg_start
        if left > 0:  # нет границы — не рвём слово, сдвигаемся к началу следующего
            sp = text.find(" ", left, ms)
            left = sp + 1 if sp != -1 else left
    while left < ms and text[left] in " \t\r\n":
        left += 1

    # правая граница: в окне (me, me+CTX] берём ПО ПОСЛЕДНЕЕ целое предложение
    seg_end = min(len(text), me + CTX)
    last = None
    for dm in sent_delim.finditer(text, me, seg_end):
        last = dm
    if last and (last.end() - me) >= MINSIDE:
        right = last.end()
    else:
        # граница даёт пустой хвост (маркер в конце короткого предложения) —
        # берём жёсткое окно, чтобы было видно, В ЧЁМ боль
        right = seg_end
        if right < len(text):
            sp = text.rfind(" ", me, right)
            right = sp if sp != -1 else right

    prefix = "…" if left > 0 else ""
    suffix = "…" if right < len(text) else ""

    raw_before = text[left:ms]
    raw_match  = text[ms:me]
    raw_after  = text[me:right].rstrip()
    return (prefix
            + html.escape(raw_before)
            + "<mark>" + html.escape(raw_match) + "</mark>"
            + html.escape(raw_after)
            + suffix)


def render(items, title):
    e = html.escape
    buckets = {"cand": [], "look": [], "noise": []}
    for it in items:
        buckets[it["bucket"]].append(it)
    for b in buckets.values():
        b.sort(key=lambda x: -x["score"])
    labels = {"cand": ("🔥 Кандидаты", True), "look": ("👀 Посмотреть", False),
              "noise": ("🗑 Шум / реклама / оффтоп", False)}

    def card(it):
        src = ", ".join("r/" + s for s in sorted(it["sources"]))
        c = f' · 💬{e(it["comments"])}' if it.get("comments") else ""

        # --- первая строка: подсвеченное предложение или fallback ---
        headline_html = highlight_sentence(it["title"])
        if headline_html is None:
            # fallback: первые 240 символов без <mark>
            fb = it["title"]
            if len(fb) > 240:
                fb = fb[:240] + "…"
            headline_html = e(fb)

        # --- полоска значков: ИЗ ЧЕГО собран сигнал (описывает, не ранжирует) ---
        sig = []
        if it.get("pay"):  sig.append("💰")
        if it.get("pain"): sig.append("🔔")
        if it.get("dom"):  sig.append("🏷")
        n = len(it["sources"])
        if n > 1:          sig.append(f"🔁×{n}")
        sig_html = " ".join(sig) or "·"

        # --- спойлер: полный текст + разбор (число балла прячем сюда) ---
        full = it["title"]
        if len(full) > 240:
            full = full[:240] + "…"
        details_inner = (f'<div class="more-full">{e(full)}</div>'
                         f'<div class="more-why">🔥{it["score"]} · {e(it["why"])}</div>')

        return (f'<article class="card">'
                f'<a class="t" href="{e(safe_url(it["url"]))}" target="_blank" rel="noopener">{headline_html}</a>'
                f'<div class="meta"><span class="sig">{sig_html}</span> · {e(src)}{c}</div>'
                f'<details class="more"><summary>полный текст · почему</summary>{details_inner}</details>'
                f'</article>')

    secs = []
    for key in ("cand", "look", "noise"):
        cs = buckets[key]

        # === КАНДИДАТЫ: группируем по ТЕМЕ боли (теплокарта — где боль гуще) ===
        if key == "cand":
            groups = {}
            for x in cs:
                groups.setdefault(theme_of(x["title"]), []).append(x)
            # темы по убыванию размера; самая горячая — открыта, остальные свёрнуты
            ordered = sorted(groups.items(), key=lambda kv: -len(kv[1]))
            for i, (tname, xs) in enumerate(ordered):
                opn = " open" if i == 0 else ""
                body = "".join(card(x) for x in xs)
                secs.append(f'<details{opn}><summary><span class="ph">🔥 {e(tname)}</span>'
                            f'<span class="n">{len(xs)}</span></summary>{body}</details>')
        else:
            lab, op = labels[key]
            opn = " open" if op else ""
            body = "".join(card(x) for x in cs) or '<div class="card" style="color:#6e7681">пусто</div>'
            secs.append(f'<details{opn}><summary><span class="ph">{lab}</span>'
                        f'<span class="n">{len(cs)}</span></summary>{body}</details>')

    body = "\n".join(secs)
    nc, nl, nn = len(buckets["cand"]), len(buckets["look"]), len(buckets["noise"])

    return f"""<!doctype html><html lang="ru"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(title)}</title>
<style>
:root{{color-scheme:dark}}*{{box-sizing:border-box}}
body{{margin:0;font:15px/1.5 -apple-system,system-ui,sans-serif;background:#0d1117;color:#e6edf3}}
header{{background:#161b22;border-bottom:1px solid #30363d;padding:14px 16px}}
h1{{font-size:16px;margin:0}}.sub{{font-size:12px;color:#8b949e;margin-top:5px}}
main{{padding:10px 14px;max-width:820px;margin:0 auto}}
details{{background:#161b22;border:1px solid #30363d;border-radius:10px;margin:0 0 9px;overflow:hidden}}
summary{{cursor:pointer;padding:12px 14px;font-weight:600;display:flex;justify-content:space-between;align-items:center;gap:10px;list-style:none}}
summary::-webkit-details-marker{{display:none}}
summary::before{{content:"▸";color:#8b949e;margin-right:8px;font-weight:400}}
details[open] summary::before{{content:"▾"}}
.ph{{flex:1}}.n{{font-size:12px;color:#7ee787;font-weight:600}}
.card{{border-top:1px solid #21262d;padding:12px 14px}}
.card a.t{{color:#58a6ff;text-decoration:none;font-weight:600;font-size:14.5px}}
.card a.t mark{{background:#ffd33d;color:#0d1117;padding:0 2px;border-radius:3px;font-weight:600}}
.meta{{color:#8b949e;font-size:11.5px;margin-top:7px}}
.sig{{font-size:13px;letter-spacing:1px}}
.src{{color:#6e7681;font-size:11px;margin-top:3px}}
.more{{border:none;background:none;margin-top:5px}}
.more summary{{cursor:pointer;font-size:11px;color:#8b949e;padding:0;font-weight:400;list-style:none;display:inline}}
.more summary::-webkit-details-marker{{display:none}}
.more summary::before{{content:"▸ ";font-size:10px;color:#6e7681}}
.more[open] summary::before{{content:"▾ "}}
.more-full{{font-size:12px;color:#c9d1d9;margin-top:4px;line-height:1.4}}
.more-why{{font-size:11px;color:#8b949e;margin-top:3px}}
</style></head><body>
<header><h1>{e(title)}</h1>
<div class="sub">{len(items)} уникальных · 🔥{nc} кандидатов · 👀{nl} посмотреть · 🗑{nn} отсеяно · без скриптов<br>значки: 💰 платит · 🔔 боль · 🏷 домен · 🔁 кросспост · (детали и балл — тапни «почему»)</div>
</header>
<main>
{body}
</main></body></html>"""


def main():
    items = [score(it) for it in load_all()]
    if not items:
        sys.exit("нет данных: out/reddit-raw-batch*.json пуст")
    for it in items:
        it["sources"] = sorted(it["sources"])
    items.sort(key=lambda x: -x["score"])
    json.dump(items, open(os.path.join(OUT, "reddit-pain.json"), "w"),
              ensure_ascii=False, indent=1)
    html_path = os.path.join(OUT, "reddit-pain.html")
    open(html_path, "w", encoding="utf-8").write(
        render(items, "reddit-pain — триаж по боли"))
    nc = sum(1 for it in items if it["bucket"] == "cand")
    nl = sum(1 for it in items if it["bucket"] == "look")
    nn = sum(1 for it in items if it["bucket"] == "noise")
    print(f"OK: {len(items)} уникальных → 🔥{nc} кандидатов · 👀{nl} посмотреть · 🗑{nn} шум")
    print("файлы: out/reddit-pain.json + out/reddit-pain.html")


if __name__ == "__main__":
    main()
