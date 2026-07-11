# CivicMirror-API — Hybrid Extraction Architecture (Handoff Brief)

**Purpose of this doc:** design brief for implementing a tiered, hybrid election-data
extraction system. Drop into Claude Code as the spec, then work against the actual
codebase. This captures a design decision, not finished code — treat the file layout
and names below as proposals to reconcile with what already exists.

---

## Goal

Aggregate election **results** (contests + candidates + vote totals) from local
jurisdictions across many states into one normalized, trustworthy dataset. The
problem is source heterogeneity: some jurisdictions expose clean ENR feeds, others
publish only certified PDFs, others nothing but ad-hoc county HTML.

## Core idea: route per jurisdiction, normalize everything

For each jurisdiction (keyed by **OCD-ID**), pick the best available extraction
strategy for whatever the source actually is, then funnel all strategies into one
normalized schema and one validation gate. **The LLM is the fallback, not the default.**

## Source tiers (best → worst)

| Tier | Source type | Strategy | Trust |
|------|-------------|----------|-------|
| 1 | Structured API (ENR XML/JSON) | Deterministic adapter | Exact, fast |
| 2 | Structured docs (certified PDF, CSV) | Deterministic parser (e.g. pdfplumber) | Exact, more brittle |
| 3 | Semi-structured HTML (county results tables) | Parser if layout stable; templated extraction if predictable | Medium |
| 4 | Unstructured / no feed (decentralized long tail) | LLM discovery + extraction pipeline | Low — must be gated |

Already reverse-engineered and belonging in Tiers 1–2 (keep deterministic, do **not**
replace with LLM): AZ AZSOS XML feed, AR TotalResults API, NY Flateau API + cert PDFs,
CT KNOWiNK TotalVote. Tier 4 targets the known-hard cases (WI decentralized structure,
IA county CMS sprawl, and similar per-county messes).

## Components

### 1. Registry (the router's config)
A mapping keyed by OCD-ID → which source(s) exist and which strategy/adapter to run.
Analogous in spirit to a `state_configs`-style table. The router reads this and
dispatches. Optionally: try Tier 1 first and fall down the tiers when a source is
absent or fails.

### 2. Router / dispatcher
`resolve OCD-ID → registry lookup → run selected adapter`. Adapters are swappable and
share a common interface so tiers plug in uniformly.

### 3. Common normalized output
Every tier emits the same shape: **Race/Contest → Candidate → votes**, regardless of
how it was obtained. This is the convergence point. The existing Race
normalization/deduplication management command (provenance-aware field merging) is the
canonical-landing step all tiers feed into.

### 4. Validation & trust layer (the part that makes hybrid *safe*)
Sits between extraction and the database. Treats tiers differently:
- **Deterministic tiers (1–3):** light sanity checks — votes sum to reported turnout,
  candidate count matches the contest, totals reconcile.
- **LLM tier (4):** same arithmetic checks **plus** a confidence score **plus**
  cross-check against any other available source for that jurisdiction. Below
  threshold → **human review queue**, never straight to trusted.

### 5. Provenance + confidence on every datum
Tag which tier/source produced each value (extends existing provenance-aware merging).
Lets the merge step prefer the structured value when tiers disagree, and supports audit.

### 6. Review queue
Low-confidence / failed-validation extractions land here for human accept/reject before
promotion to trusted. (Reference pattern: CivicPatch gates all scraped officials through
GitHub PR review before merge — same idea, applied to results.)

## Per-jurisdiction run flow

```
resolve OCD-ID
  → registry: which source / strategy
  → extract (deterministic adapter | parser | LLM pipeline)
  → normalize to Race → Candidate → votes
  → validate (strict gate for LLM output)
  → tag provenance + confidence
  → high confidence? auto-accept : enqueue for review
  → merge into canonical races (existing dedup command)
```

## Why hybrid (the tradeoff being bought)

Exactness + speed where clean feeds exist; coverage where they don't; one schema and
one validation gate over both — **without letting LLM guesses near a vote total
unchecked.** Election-night cadence is bursty/high-volume/latency-sensitive, so
structured feeds stay the workhorse; the LLM pipeline is reserved for the slow-changing
long tail where no feed exists.

## Stack notes

- Django + DRF backend; PostgreSQL.
- Reuse the existing Race normalization/dedup management command as the canonical merge.
- OCD-IDs as the jurisdiction key throughout (consistent with prior per-state research).
- If/when LLM extraction is added: keep a **prompt-eval harness** that runs on every
  prompt change so numeric extraction can't silently regress (reference pattern borrowed
  from CivicPatch's pipeline evals).

## Reference: CivicPatch pipeline pattern (optional, for the Tier-4 fallback)

Their `people_collector` is an LLM pipeline of typed steps, one directory per step,
each a single function taking a typed context and returning a typed result, wired into
an orchestrator: research (LLM + web search) → find links → render (Playwright) →
clean/chunk → LLM-extract structured records → dedup within pass → reconcile across
passes → resolve IDs → format/save. A results-oriented `results_collector` could mirror
this skeleton; their Playwright rendering + chunking utilities are largely liftable.

## Suggested first implementation steps

1. Define the adapter interface + the normalized Race/Candidate result type.
2. Stand up the OCD-ID registry and the router that dispatches to adapters.
3. Wrap one existing deterministic source (e.g. AR TotalResults) as the first adapter
   behind the interface — proves the router + normalize + validate path end to end.
4. Add the validation layer with reconciliation checks + provenance/confidence tags.
5. Add the review-queue model + a minimal accept/reject surface.
6. Only then prototype the Tier-4 LLM `results_collector` for one no-feed jurisdiction.