#!/usr/bin/env python3
"""Deferred AI scorer for the reddit branch of pain-harvester.

Second pass on top of the deterministic `reddit_build.py`: Haiku judges the top
heuristic candidates and keeps only real, specific pains — EACH one must be
confirmed by a verbatim quote from the post text. Quote not found in the
source → the pain is dropped (gate against fabrication).

Runs on the subscription: `claude -p --model claude-haiku-4-5` (no API key, no
SDK). reddit_build.py is left untouched.
"""
import re

# --- pure core (tested without calling claude) ------------------------------


def normalize(text):
    """lower + collapse any whitespace into one space, trim edges."""
    return re.sub(r"\s+", " ", text or "").strip().lower()


def quote_in_source(quote, source):
    """Authenticity gate: a non-empty quote is present verbatim (after normalization) in the text."""
    nq = normalize(quote)
    return bool(nq) and nq in normalize(source)


def split_headline_body(text):
    """cand['title'] = headline + '\n\n' + body (as built by reddit_build and parse_hnse).
    Returns (headline, body); no separator → (text, '')."""
    parts = (text or "").split("\n\n", 1)
    return parts[0], (parts[1] if len(parts) > 1 else "")


def is_title_echo(quote, headline):
    """Quote ≈ headline (substring match in either direction) = not proof, but an echo."""
    nq, nh = normalize(quote), normalize(headline)
    return bool(nq) and bool(nh) and (nq in nh or nh in nq)


PROMO_RE = re.compile(
    r"(?i)^\s*(show hn:|roast my|i (built|made|created|launched)|we (built|made|launched)|"
    r"just launched|launching\b|feedback on my|check out my)")


def looks_promo(headline):
    """Deterministic filter for promos/launches BEFORE spending on scoring (P0 #2).
    Catches prefixes; disguised promo is finished off by the hardened prompt (second line of defense)."""
    return bool(PROMO_RE.search(headline or ""))


def parse_batch(raw):
    """Extract the JSON array from the model's reply (tolerating prose/code fences around it).

    Raises ValueError if there is no array in the text (model refusal / garbage).
    """
    import json

    candidates = []
    s = (raw or "").strip()
    candidates.append(s)
    # contents of ```...``` code fences
    for m in re.finditer(r"```(?:json)?\s*(.*?)```", s, re.S):
        candidates.append(m.group(1).strip())
    # rough slice from the first [ to the last ]
    i, j = s.find("["), s.rfind("]")
    if i != -1 and j != -1 and j > i:
        candidates.append(s[i:j + 1])

    for c in candidates:
        try:
            data = json.loads(c)
        except (ValueError, TypeError):
            continue
        if isinstance(data, list):
            return data
    raise ValueError("no JSON array in the model reply")


def merge_verdicts(candidates, verdicts):
    """Stitch Haiku verdicts to the source by id, apply keep + the quote gate.

    Returns (kept, counts). `url` always comes from the source, never from the model.
    """
    counts = {"kept": 0, "dropped_ai_no": 0, "dropped_no_quote": 0, "dropped_title_echo": 0, "malformed": 0}
    kept = []
    for v in verdicts:
        if not isinstance(v, dict):
            counts["malformed"] += 1
            continue
        idx = v.get("id")
        if not isinstance(idx, int) or isinstance(idx, bool) or not (0 <= idx < len(candidates)):
            counts["malformed"] += 1
            continue
        cand = candidates[idx]
        if not bool(v.get("keep")):
            counts["dropped_ai_no"] += 1
            continue
        quote = v.get("evidence_quote", "")
        headline, body = split_headline_body(cand.get("title", ""))
        if is_title_echo(quote, headline):
            counts["dropped_title_echo"] += 1
            continue
        if not quote_in_source(quote, body):
            counts["dropped_no_quote"] += 1
            continue
        item = dict(cand)
        item["ai_score"] = v.get("ai_score")
        item["ai_reason"] = v.get("reason", "")
        item["evidence_quote"] = quote
        item["url"] = cand.get("url")  # from the source, guaranteed real
        kept.append(item)
        counts["kept"] += 1
    return kept, counts


def select_candidates(items, top):
    """Only bucket=='cand', sorted by heuristic score ↓, sliced to top (None = all)."""
    cands = [x for x in items if x.get("bucket") == "cand"]
    cands.sort(key=lambda x: -x.get("score", 0))
    return cands if top is None else cands[:top]


def parse_hnse(md_text):
    """Adapter: HN/SE digest (.md from fetch_pain.py) → the scorer's shape.

    Text for the AI and for the quote gate = title + quote (merge_verdicts validates
    against the title field). `score` from meta for ranking, origin/sources for the
    source tag, bucket='cand' so select_candidates picks it up.
    """
    import digest_to_html

    items = []
    for c in digest_to_html.parse(md_text):
        text = c.get("title", "")
        if c.get("quote"):
            text += "\n\n" + c["quote"]
        m = re.search(r"score\s+(\d+)", c.get("meta", ""))
        items.append({
            "bucket": "cand",
            "score": int(m.group(1)) if m else 0,
            "title": text,
            "url": c.get("url", ""),
            "sources": [c.get("site", "")],
            "origin": (c.get("source", "") or "").lower(),  # 'hn' / 'se'
        })
    return items


def select_hnse(items, top, include_se=False):
    """Select HN/SE candidates. By default HN ONLY (live pains); SE is parked —
    its only ranking signal (SO votes) pulls up canonical solved questions, not
    pains. include_se=True brings SE back into the shared ranking (once there is a pain signal).
    """
    pool = items if include_se else [x for x in items if x.get("origin") == "hn"]
    return select_candidates(pool, top)


def source_label(item):
    """Source tag: 🔴 r/<sub> for reddit (default), 🟠 <site> for HN/SE."""
    origin = item.get("origin") or "reddit"
    srcs = item.get("sources") or []
    if origin == "reddit":
        tag, body = "🔴", ", ".join("r/" + s for s in srcs)
    else:
        tag, body = "🟠", ", ".join(srcs)
    return (tag + " " + body) if body else tag


# --- prompt + Haiku call -----------------------------------------------------

MODEL = "claude-haiku-4-5"          # claude-api skill; Haiku does NOT support effort
BATCH_SIZE = 8
POST_CAP = 1000                     # trim post text in the prompt (validation uses the full title)

PROMPT_HEADER = """\
You judge posts from developer forums (Reddit, Hacker News, StackExchange) for GENUINE, SPECIFIC pain that someone would pay to solve.

For EACH numbered post below, return one JSON object:
{"id": <post number>, "keep": <true|false>, "ai_score": <1-5>,
 "reason": "<one short clause, why>",
 "evidence_quote": "<an EXACT span copied verbatim from that post's text>"}

Rules:
- keep=true ONLY for a real, specific, currently-felt pain (not a vague wish, not a
  promo/launch, not a generic question).
- A post PROMOTING the author's own product/launch (Show HN, "I built…", "roast my…",
  a feature list with emojis) is a promo -> keep=false, even if it mentions a pain.
- evidence_quote MUST be copied character-for-character from the post — the literal
  words that prove the pain. Do NOT paraphrase. If you cannot find such a span, set
  keep=false and evidence_quote="".
- ai_score: 5 = sharp, urgent, monetizable pain; 1 = barely a pain.

Output ONLY a JSON array of these objects, one per post, nothing else.

POSTS:
"""


def build_prompt(batch):
    """Prompt with numbered posts (text trimmed) + strict JSON requirement."""
    parts = [PROMPT_HEADER]
    for i, p in enumerate(batch):
        text = (p.get("title", "") or "")[:POST_CAP]
        parts.append("### POST %d\n%s\n" % (i, text))
    return "\n".join(parts)


def run_claude(prompt, model=MODEL):
    """Call Haiku on the subscription: claude -p (no API key, no tools). Returns text."""
    import subprocess

    proc = subprocess.run(
        ["claude", "-p", "--model", model, "--allowedTools", ""],
        input=prompt, capture_output=True, text=True, timeout=180,
    )
    if proc.returncode != 0:
        raise RuntimeError("claude exit %d: %s" % (proc.returncode, proc.stderr.strip()[:300]))
    return proc.stdout


def score_batch(batch, runner=run_claude, model=MODEL):
    """Build the prompt → call the model → parse the JSON verdicts."""
    return parse_batch(runner(build_prompt(batch), model))


# --- static page rendering ---------------------------------------------------

_STYLE = """:root{color-scheme:dark}*{box-sizing:border-box}
body{margin:0;font:15px/1.5 -apple-system,system-ui,sans-serif;background:#0d1117;color:#e6edf3}
header{background:#161b22;border-bottom:1px solid #30363d;padding:14px 16px}
h1{font-size:16px;margin:0}.sub{font-size:12px;color:#8b949e;margin-top:5px}
main{padding:10px 14px;max-width:820px;margin:0 auto}
details{background:#161b22;border:1px solid #30363d;border-radius:10px;margin:0 0 9px;overflow:hidden}
summary{cursor:pointer;padding:12px 14px;font-weight:600;display:flex;justify-content:space-between;align-items:center;gap:10px;list-style:none}
summary::-webkit-details-marker{display:none}
summary::before{content:"▸";color:#8b949e;margin-right:8px;font-weight:400}
details[open] summary::before{content:"▾"}
.n{font-size:12px;color:#7ee787;font-weight:600}
.card{border-top:1px solid #21262d;padding:12px 14px}
.card a.t{color:#58a6ff;text-decoration:none;font-weight:600;font-size:14.5px}
.card a.t mark{background:#ffd33d;color:#0d1117;padding:0 2px;border-radius:3px;font-weight:600}
.meta{color:#8b949e;font-size:11.5px;margin-top:7px}
.proof{font-size:12.5px;color:#c9d1d9;margin-top:5px;border-left:2px solid #30363d;padding-left:8px}
.strip{padding:10px 14px;background:#161b22;border-bottom:1px solid #30363d;font-size:13px}
.strip a{color:#58a6ff;text-decoration:none;margin-right:16px;font-weight:600}
.run{color:#f0a04b;font-weight:600}
.more{margin-top:14px}.more summary{font-size:12px;color:#8b949e;font-weight:400}"""


def cards_html(items):
    """Cards by ai_score (5→1). HEADLINE = the pain itself (reason); quote = proof beneath it."""
    import html
    try:
        import reddit_build
        highlight = reddit_build.highlight_sentence
    except Exception:
        highlight = lambda _t: None
    e = html.escape

    def card(it):
        quote = it.get("evidence_quote", "")
        hl = highlight(quote)
        proof = hl if hl else e(quote[:240])
        pain = e(it.get("ai_reason") or "(no wording)")
        url = e(it.get("url") or "")
        src = source_label(it)
        return ('<article class="card">'
                '<a class="t" href="%s" target="_blank" rel="noopener">★%s %s</a>'
                '<div class="proof">%s</div>'
                '<div class="meta">%s · → open post</div></article>'
                % (url, e(str(it.get("ai_score"))), pain, proof, e(src)))

    groups, secs = {}, []
    for it in sorted(items, key=lambda x: -(x.get("ai_score") or 0)):
        groups.setdefault(it.get("ai_score") or 0, []).append(it)
    for k, (sc, xs) in enumerate(sorted(groups.items(), key=lambda kv: -kv[0])):
        opn = " open" if k == 0 else ""
        body = "".join(card(x) for x in xs)
        secs.append('<details%s><summary><span>★%s pain</span>'
                    '<span class="n">%d</span></summary>%s</details>'
                    % (opn, e(str(sc)), len(xs), body))
    return "\n".join(secs)


def render(items, title):
    """Static reddit-pain-ai.html file (direct open / backup)."""
    import html
    e = html.escape
    return ("""<!doctype html><html lang="ru"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>%s</title><style>%s</style></head><body>
<header><h1>%s</h1><div class="sub">%d pains · confirmed by quote · Haiku AI pass · no scripts</div></header>
<main>%s</main></body></html>""" % (e(title), _STYLE, e(title), len(items), cards_html(items)))


def view_page(items, meta):
    """Live page: run status bar + list (pain as headline) + collapsed history."""
    import html
    e = html.escape
    running = bool(meta.get("running"))
    refresh = '<meta http-equiv="refresh" content="5">' if running else ""
    if running:
        status = '<span class="run">⏳ run in progress…</span>'
    else:
        status = "updated %s · %s pains" % (e(str(meta.get("updated", "?"))), e(str(meta.get("n", 0))))

    rows = []
    for rn in (meta.get("runs") or [])[::-1][:5]:
        c = rn.get("counts") or {}
        rows.append("<div>%s · %s · ✅%s 🗑%s ❌%s</div>" % (
            e(str(rn.get("started_at", "?"))), e(str(rn.get("status", "?"))),
            e(str(c.get("kept", "–"))), e(str(c.get("dropped_no_quote", "–"))),
            e(str(c.get("dropped_ai_no", "–")))))
    history = ('<details class="more"><summary>recent runs</summary>'
               '<div class="meta">%s</div></details>' % ("".join(rows) or "empty so far"))

    digest = meta.get("digest")
    digest_link = ('<a href="%s">HN+SE digest →</a>' % e(digest)) if digest else ""
    body = cards_html(items) or '<div class="card">empty — press "run now"</div>'
    return ("""<!doctype html><html lang="ru"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">%s
<title>pains · reddit + HN/SE</title><style>%s</style></head><body>
<header><h1>pains · reddit + HN/SE</h1><div class="sub">%s</div></header>
<div class="strip"><a href="/run">▶ run now</a><a href="reddit-pain.html">reddit triage →</a>%s</div>
<main>%s
%s</main></body></html>""" % (refresh, _STYLE, status, digest_link, body, history))


# --- run log + smart daily ----------------------------------------------------

def source_hash(path):
    """sha256 of the source file; no file → ''."""
    import hashlib
    try:
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except OSError:
        return ""


def sources_hash(paths):
    """Combined sha256 of several sources; missing file → a stable marker.

    Separator between files → order and boundaries matter (one source changed —
    the combined hash changes).
    """
    import hashlib

    h = hashlib.sha256()
    for p in paths:
        try:
            with open(p, "rb") as f:
                h.update(f.read())
        except OSError:
            h.update(b"\0")
        h.update(b"\x1e")
    return h.hexdigest()


def should_run(current_hash, last_hash):
    """Run if the source has changed since the last completed run."""
    return current_hash != last_hash


def new_run(run_id, trigger, src_hash, now):
    return {"id": run_id, "trigger": trigger, "source_hash": src_hash,
            "started_at": now, "status": "running"}


def finish_run(runs, run_id, status, now, counts=None, error=None):
    for rn in runs:
        if rn.get("id") == run_id:
            rn["status"] = status
            rn["finished_at"] = now
            if counts is not None:
                rn["counts"] = counts
            if error is not None:
                rn["error"] = error
            break
    return runs


def trim_runs(runs, n):
    return runs[-n:]


def last_run_hash(runs):
    """Source hash at the time of the last completed (done/skipped) run."""
    for rn in reversed(runs):
        if rn.get("status") in ("done", "skipped") and rn.get("source_hash"):
            return rn["source_hash"]
    return ""


# --- orchestration ------------------------------------------------------------

def main(argv=None):
    import argparse
    import datetime
    import json
    import os

    here = os.path.dirname(os.path.abspath(__file__))
    out = os.path.join(here, "out")
    runs_path = os.path.join(out, "ai-runs.json")
    lock_path = os.path.join(out, ".ai-run.lock")

    ap = argparse.ArgumentParser(description="AI scorer for reddit candidates (Haiku, on subscription)")
    ap.add_argument("--in", dest="inp", default=os.path.join(out, "reddit-pain.json"))
    ap.add_argument("--top", type=int, default=None, help="how many top reddit candidates (default — all)")
    ap.add_argument("--hn-se", dest="hnse", default=None,
                    help="HN/SE digest .md (default — the latest out/*pain-core20.md)")
    ap.add_argument("--hnse-top", type=int, default=40, help="how many top HN cards by score")
    ap.add_argument("--include-se", action="store_true",
                    help="bring SE back into the pass (HN only by default — SO votes ≠ pain)")
    ap.add_argument("--batch", type=int, default=BATCH_SIZE)
    ap.add_argument("--model", default=MODEL)
    ap.add_argument("--if-changed", action="store_true",
                    help="run only if reddit-pain.json changed since the last run")
    ap.add_argument("--trigger", default="cli", help="launch trigger (manual/cron/cli)")
    args = ap.parse_args(argv)

    def now():
        return datetime.datetime.now().isoformat(timespec="seconds")

    def load_runs():
        try:
            return json.load(open(runs_path, encoding="utf-8"))
        except (OSError, ValueError):
            return []

    def save_runs(runs):
        json.dump(trim_runs(runs, 20), open(runs_path, "w"), ensure_ascii=False, indent=1)

    import glob

    hnse_path = args.hnse
    if hnse_path is None:
        found = sorted(glob.glob(os.path.join(out, "*pain-core20.md")))
        hnse_path = found[-1] if found else ""

    runs = load_runs()
    cur_hash = sources_hash([args.inp, hnse_path or ""])

    # smart daily: no source changed → skip, do not burn tokens
    if args.if_changed and not should_run(cur_hash, last_run_hash(runs)):
        rec = new_run(now(), args.trigger, cur_hash, now())
        rec["status"], rec["finished_at"] = "skipped", now()
        runs.append(rec)
        save_runs(runs)
        print("skip: sources (reddit + HN/SE) unchanged since the last run")
        return

    # lock against overlap (double tap / button+cron)
    try:
        os.close(os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
    except FileExistsError:
        raise SystemExit("a run is already in progress (lock %s)" % lock_path)

    run_id = now()
    runs.append(new_run(run_id, args.trigger, cur_hash, now()))
    save_runs(runs)

    try:
        items = json.load(open(args.inp, encoding="utf-8"))
        reddit_cands = select_candidates(items, args.top)
        hnse_cands = []
        if hnse_path and os.path.isfile(hnse_path):
            hnse_cands = select_hnse(parse_hnse(open(hnse_path, encoding="utf-8").read()),
                                     args.hnse_top, include_se=args.include_se)
        cands = reddit_cands + hnse_cands
        pre = len(cands)
        cands = [c for c in cands if not looks_promo(split_headline_body(c.get("title", ""))[0])]
        dropped_promo = pre - len(cands)
        print("promo pre-filter: −%d" % dropped_promo)
        if not cands:
            raise RuntimeError("no candidates: reddit %s + HN/SE %s" % (args.inp, hnse_path or "—"))
        hn_lbl = "HN+SE" if args.include_se else "HN"
        print("input: reddit %d + %s %d = %d candidates" % (len(reddit_cands), hn_lbl, len(hnse_cands), len(cands)))

        kept_all = []
        total = {"kept": 0, "dropped_ai_no": 0, "dropped_no_quote": 0, "dropped_title_echo": 0, "malformed": 0, "batch_errors": 0}
        for i in range(0, len(cands), args.batch):
            batch = cands[i:i + args.batch]
            try:
                verdicts = score_batch(batch, model=args.model)
            except Exception as ex:       # claude unavailable / non-JSON / timeout
                total["batch_errors"] += 1
                print("  batch %d-%d: skipped (%s)" % (i, i + len(batch) - 1, str(ex)[:120]))
                continue
            kept, counts = merge_verdicts(batch, verdicts)
            kept_all.extend(kept)
            for key in ("kept", "dropped_ai_no", "dropped_no_quote", "dropped_title_echo", "malformed"):
                total[key] += counts[key]

        kept_all.sort(key=lambda x: (-(x.get("ai_score") or 0), -x.get("score", 0)))
        json.dump(kept_all, open(os.path.join(out, "reddit-pain-ai.json"), "w"),
                  ensure_ascii=False, indent=1)
        open(os.path.join(out, "reddit-pain-ai.html"), "w", encoding="utf-8").write(
            render(kept_all, "AI pains (reddit + HN/SE) — confirmed by quote"))

        finish_run(runs, run_id, "done", now(), counts=total)
        print("OK: input %d → ✅%d (with quote) · ❌%d AI-no · 🗑%d no quote · "
              "🪞%d title echo · ⚠️%d malformed · 💥%d errors"
              % (len(cands), total["kept"], total["dropped_ai_no"],
                 total["dropped_no_quote"], total["dropped_title_echo"],
                 total["malformed"], total["batch_errors"]))
        print("files: out/reddit-pain-ai.json + out/reddit-pain-ai.html")
    except Exception as ex:
        finish_run(runs, run_id, "error", now(), error=str(ex)[:200])
        raise
    finally:
        save_runs(runs)
        try:
            os.remove(lock_path)
        except OSError:
            pass


if __name__ == "__main__":
    main()
