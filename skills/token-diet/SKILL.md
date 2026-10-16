---
name: token-diet
description: >-
  Cut token usage across the whole session without losing correctness or
  substance — concise user replies, lean tests/docs/plans/comments, tight code,
  disciplined context and tool use, and cheap sub-agent delegation. Load when the
  user wants less verbosity, lower cost, fewer tokens, or a "token diet" / "lean
  mode"; also triggered by /token-diet or "token diet on".
---

# Token Diet

Reduce tokens by cutting **wasted words, not substance**. Preserve every bit of
correctness, specificity, and required detail — remove filler, repetition,
preamble, and dead exploration. If a cut would lower quality, don't make it.

Input tokens recur: the transcript and every tool output are re-sent each turn.
So keeping junk **out of context** (buckets E & F) outweighs shortening what you
type — prioritize accordingly.

## Levels

- **on** (default) — every rule below.
- **lite** — communication + artifacts only (buckets A, B); leave tooling as-is.
- **ultra** — everything in `on`, plus telegraphic output on low-stakes surfaces
  (see below). Opt-in.
- **off** — pause. Triggered by "normal mode" / "verbose mode" / `/token-diet off`.

Toggle: `/token-diet [on|lite|ultra|off]` or say "token diet on/ultra/off".

### Ultra mode (surface-scoped)

- **Low-stakes → telegraphic.** User chat replies and progress/status notes.
  Lead with the answer; drop articles, auxiliaries, and pronouns where meaning
  survives; fragments over full sentences; arrow chains (`A → B → fails`) and
  common abbreviations OK; no headers/bold on a short reply; no preamble,
  postamble, hedging, or emoji. Anchor on this target style:
  > VERBOSE: "The function parses the string and then returns the number of
  > cents, and it throws an error on invalid input."
  > ULTRA: "parses string → cents (int); throws on invalid input."
- **High-stakes → never telegraph.** Code, commands, file paths, identifiers,
  error strings, **tests, docs / memory / hand-off files, and sub-agent
  instructions** stay complete and precise (normal `on` rules, not fragments). A
  sub-agent prompt or migration doc in shorthand loses the precision that makes
  it actionable.

Rule of thumb: if a human reads it and moves on, telegraph it; if a human or
agent must *act on it exactly*, keep it whole. Guardrails bind in every level.

---

## The rules

### A. Talking to the user
- Lead with the answer. **No preamble** ("Sure! Here's…") and **no postamble**
  ("Let me know if…") unless it carries information.
- **Don't restate the request** back to the user.
- Report **deltas, not narration**: "done: X; tests green; Y still failing".
- Short sentences, dense, skimmable. Drop filler.

### B. Artifacts you write (docs, memory, hand-offs, plans, comments)
- **Docs / memory / hand-off / skill files**: minimum words that still convey
  everything the next reader needs. No restating the obvious.
- **Plans**: the steps and the decisions, nothing else.
- **Code comments**: comment the non-obvious *why*; skip comments that re-say the
  code.

### C. Tests
- Cover **key behavior and critical/edge paths only**; group related cases into
  compact tests. No exhaustive one-assert-per-test matrices, no redundant cases.
- **≤ 10 tests per session** ceiling.
- Guardrail G1 still binds: never drop coverage on money / auth / data-loss.

### D. Code as an artifact  *(re-enters context on every read)*
- **YAGNI**: build only what's asked. No speculative abstractions, flags, config,
  or error handling for cases that can't happen.
- **Concise but idiomatic** — match surrounding code, no redundant boilerplate.
  **Never cryptic.**
- No dead / commented-out code left behind.

### E. Context & search  *(highest leverage — cache read+write dominate the bill)*
- **grep before you read.** Never open a file blind — locate with `grep -rn`
  first, then read only that range (`sed -n 'a,bp'` or offset+limit). **Never
  read a whole file.** Prefer grep/sed (tiny outputs) over pulling files in.
- **Batch every independent grep/read into one turn** — one round of many calls,
  not one call per turn (each turn re-sends the whole accumulated context).
- **Minimize total turns.** Scout once, plan the whole change, then apply every
  edit and verify in a single pass. Never ping-pong read→edit→read across turns:
  each extra turn re-sends *and* re-caches the entire prefix — the single biggest
  line on the bill (cache_read + cache_write scale directly with turn count).
- **Reuse what's already in context** — never re-read or re-grep it; never
  re-read a file you just edited "to verify" (the edit fails loudly on mismatch).
- **Stop the instant you can act** — don't re-read to verify or explore adjacent
  code "for completeness".
- **Delegate broad, well-bounded search / exploration to a sub-agent on a
  cheaper, weaker model** — it returns only the conclusion; raw dumps and
  dead-ends stay out of your context, at a lower per-token rate. But **don't hand
  correctness-sensitive verification (call-site safety, cross-file impact) to a
  weaker model** — it over-explores and costs *more* than doing it inline. Keep
  those on your own model.

### F. Tools & flow
- **Batch independent tool calls** into one turn.
- **Stop when you have enough to act.** No speculative rabbit-holes.
- **Targeted test/build runs while iterating** (single file/pattern); full suite
  once, at the end.

### G. Sub-agent instructions
- Write them **detailed enough that quality and coverage are not lost** — state
  the goal, the exact targets, and the required output shape — in **as few words
  as possible.** It's an artifact you write *and* context the sub-agent re-reads.

---

## Guardrails (never trade these for tokens)

1. **Never below critical test coverage.** Always verify money, auth, and
   data-loss paths.
2. **Concision applies to communication and artifacts — never to the reasoning
   needed for correctness.** Think as hard as the problem needs; only the output
   gets shorter.
3. **Keep code, commands, identifiers, and error strings verbatim.**
4. **Never cryptic.** Readable-and-short beats short-and-obscure.

---

## Style anchors (before → after)

**User reply**
> ~~Great question! Let me walk you through how this works. Essentially…~~
> **Missing raw-body read: `constructEvent` needs `req.text()`, not `req.json()`.
> Fix at `webhook/route.ts:22`.**

**Sub-agent instruction**
> ~~Here is the instruction prompt I would give… Context: this is a Next.js +
> TypeScript monorepo with three packages… (5 paragraphs)~~
> **Find every call site of `legacyCharge()` in this TS monorepo (apps/web,
> apps/worker-node, packages/*). Read-only inventory for a migration — don't
> edit. `grep -rn "legacyCharge" --include=*.ts`; also catch re-exports/aliases
> and bare-string refs. Report per call site: `path:line` + 2 lines context,
> grouped by file; end with total count + distinct files + the definition and
> alias sites.**
