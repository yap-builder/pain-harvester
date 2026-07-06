"""Verbatim-evidence gate: don't trust an LLM verdict blindly.

When one LLM grades another's output, the judge often says "PASS" on work that is
actually bad. This module is the deterministic core that refuses to take the judge's
word for it: every "keep" verdict must attach an EXACT quote copied from the source
text. If that quote is not literally present in the source, the verdict is dropped —
no matter how confidently the model asserted it.

Pure standard library (re, json). No network, no model call, no I/O — so it is fully
unit-testable and every decision is explainable in plain words.
"""
import json
import re


def normalize(text):
    """Lowercase, collapse any run of whitespace to one space, trim the edges."""
    return re.sub(r"\s+", " ", text or "").strip().lower()


def quote_in_source(quote, source):
    """Authenticity gate: a non-empty quote appears verbatim (after normalization) in the source."""
    nq = normalize(quote)
    return bool(nq) and nq in normalize(source)


def parse_batch(raw):
    """Extract a JSON array from the model's reply (tolerating prose / code fences around it).

    Raises ValueError if there is no array in the text (model refusal / garbage).
    """
    candidates = []
    s = (raw or "").strip()
    candidates.append(s)
    # contents of ```...``` code fences
    for m in re.finditer(r"```(?:json)?\s*(.*?)```", s, re.S):
        candidates.append(m.group(1).strip())
    # crude slice from the first [ to the last ]
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
    """Join the model's verdicts back to the source by id, apply keep + the quote gate.

    Returns (kept, counts). `url` is always taken from the source, never from the model —
    a second anti-fabrication layer, so the model cannot invent a link.
    """
    counts = {"kept": 0, "dropped_ai_no": 0, "dropped_no_quote": 0, "malformed": 0}
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
        if not quote_in_source(quote, cand.get("title", "")):
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
    """Only bucket == 'cand', sorted by heuristic score desc, sliced to top (None = all)."""
    cands = [x for x in items if x.get("bucket") == "cand"]
    cands.sort(key=lambda x: -x.get("score", 0))
    return cands if top is None else cands[:top]
