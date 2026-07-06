# Verbatim-evidence gate: don't trust an LLM verdict blindly

~70 lines of pure-stdlib Python + its unit tests. Read it, run the tests, and you can
verify the whole idea in two minutes.

## The problem

**The LLM-grades-LLM problem is real** — you ask a judge model to grade another model's
output, the judge says `PASS`, and the output is actually bad. The judge hallucinates
approval the same way a generator hallucinates content. See this writeup:
<https://www.reddit.com/r/PromptEngineering/comments/1udrem8/the_llm_grades_llm_problem_is_real_heres_the/>

If you build any "LLM-as-a-judge" step, its verdict is just more model output — equally
capable of being confidently wrong.

## The mechanism

This gate refuses to take the judge's word for it. Two deterministic layers wrap every
verdict (`gate.py`):

1. **Verbatim-quote gate (`quote_in_source`).** Every `keep: true` verdict must attach an
   `evidence_quote` — an exact span the model claims proves its decision. The gate checks
   that the quote is *literally present* in the source text (after normalizing whitespace
   and case). No verbatim match → the verdict is dropped, no matter how high the model's
   confidence score. A model can assert; it cannot fabricate evidence that survives a
   substring check against the real text.

2. **Source-owned URL (`merge_verdicts`).** The output link is copied from the *source
   record*, never from the model's reply. Even a "kept" item cannot carry a hallucinated
   URL — the model never gets to write that field.

Everything here is pure functions over `re` and `json`: no network, no model call, no file
I/O. That is the point — the trust boundary is small, deterministic, and testable.

## The result

From one real run of the pipeline this was extracted from (run-log counts, verbatim):

- **160** candidates graded by the judge model
- **47** passed the gate (`kept = 47`)
- **12** were dropped *purely* for lacking a verbatim quote (`dropped_no_quote = 12`) —
  the model wanted to keep them, the evidence check said no
- (101 the model itself rejected, `dropped_ai_no = 101`)

So of the 59 items the judge marked "keep", the evidence gate caught **12 (~20%)** that
could not prove their claim with a real quote — caught deterministically, with zero extra
model calls.

## Run the tests

Pure standard library — no dependencies to install:

```bash
python -m unittest test_gate -v
```

Or with pytest, if you prefer:

```bash
pytest test_gate.py -v
```

Expected: **13 passed** — covering the quote gate (verbatim / whitespace-insensitive /
fabricated / empty), lenient JSON parsing of messy model replies, the merge that enforces
keep + quote + source-owned URL, and candidate selection.
