# PaperBreakfast — Development Log

---

### 2026-03-16 — Code review + bug fixes (pre-first-run)

**Type:** Fix
**Context:** Full retrospective review before first run. Several bugs found that would silently break correctness.

**Bugs fixed:**
1. **GUID hash instability** (`poller.py`) — Python's `hash()` changes every interpreter run due to hash randomization. Replaced with `hashlib.sha256` which is stable. Without this fix, the same paper would be inserted multiple times, violating the dedup invariant (I-1).
2. **CLI argparse conflict** (`cli.py`) — `feedback` command had both subparsers and positional args at the same level, which argparse rejects at runtime. Replaced with simple positional args + mode detection.
3. **Regex dot bug** (`keyword.py`) — `self.renewal` matched any character between "self" and "renewal". Changed to `self-renewal`.
4. **SMTP socket leak** (`mailer.py`) — socket left open on exception. Wrapped in try/finally to always call `smtp.quit()`.
5. **Silent parse errors** (`pipeline.py`) — `parse_error=True` results were stored as score=0.0 with no log message. Added WARNING log so bad LLM responses are visible.
6. **Silent empty profile** (`config.py`) — empty interest profile causes LLM evaluations to score everything ~0.5 with no explanation. Added runtime warning.

**Pitfalls to watch:** The GUID fallback (sha256 of title) is still not ideal — two papers with identical titles would collide. In practice this is very rare for scientific papers, but worth monitoring if duplicates appear in the DB.



Chronological record of decisions, trade-offs, pitfalls, and tech debt.
Maintained by Claude. Use `/adr`, `/log` to append entries.

---

### 2026-03-16 — RSS chosen over email TOC subscriptions

**Type:** ADR
**Context:** Need to ingest new papers from scientific journals same-day.
Two options: RSS feeds or email Table-of-Contents subscriptions.
**Decision:** RSS only.
**Why:** RSS is machine-readable, standardized, works with feedparser out of the box.
TOC emails require HTML parsing + anti-bot workarounds + email account polling — fragile.
**Alternatives considered:** Email TOC (too brittle), journal API scraping (no public APIs
for most publishers, rate limiting, legal grey area).
**Trade-offs:** A few journals have poor RSS coverage (e.g. some Elsevier titles).
Those will be added manually when discovered. [ASSUMED: all 15 starting feeds have valid RSS]
**Pitfalls to watch:** Publishers occasionally restructure RSS URLs without redirects.
Need to verify URLs on first run.

---

### 2026-03-16 — Modular evaluator: backend × strategy separation

**Type:** ADR
**Context:** User expects to trial multiple LLM backends (Claude API, LM Studio, Ollama)
and multiple evaluation approaches. Naive design would couple them.
**Decision:** Two independent ABCs: `LLMBackend` (where/how LLM is called) and
`EvaluationStrategy` (what is asked and how response is parsed). A `CompositeEvaluator`
combines them. `factory.py` is the only file that knows the matrix.
**Why:** Swapping backend should never require touching strategy code and vice versa.
New backend = one file + one line in factory.py.
**Alternatives considered:** Single `Evaluator` class with backend+strategy baked in (rejected:
combinatorial explosion of subclasses). Config-driven prompt templates without code abstraction
(rejected: can't handle structurally different response formats like JSON vs CoT).
**Trade-offs:** Slightly more files up front. Worth it given the explicit goal of experimentation.
**Pitfalls to watch:** If a strategy needs backend-specific behavior (e.g. special tokens),
this abstraction leaks. Cross that bridge when we hit it.

---

### 2026-03-16 — KeywordEvaluator as standalone (not using strategy layer)

**Type:** Decision
**Context:** Keyword matching doesn't need an LLM call at all, making `LLMBackend` irrelevant.
**Decision:** `KeywordEvaluator` implements `Evaluator` directly, bypassing both `LLMBackend`
and `EvaluationStrategy`. Registered under `backend.type: keyword` in factory.
**Why:** Forcing it through the strategy layer would require `KeywordBackend.complete()` to
return a fake LLM response that the strategy then parses — pure theatre.
**Trade-offs:** Slight inconsistency: keyword is listed as a "backend" in config but doesn't
use a strategy. The factory handles this as a special case. Acceptable.

---

### 2026-03-16 — peewee + SQLite over heavier options

**Type:** ADR
**Context:** Need persistent storage for papers, evaluation results, digest history.
**Decision:** peewee ORM with SQLite.
**Why:** No server to manage. `Paper.get_or_create(guid=...)` is the natural expression
of the deduplication requirement. peewee is thin enough to not hide behavior.
**Alternatives considered:** SQLAlchemy (overkill for this use case), raw sqlite3 module
(lose get_or_create convenience), PostgreSQL (requires a running server — too much ops overhead
for a personal tool), TinyDB (no good dedup primitive).
**Trade-offs:** Schema migrations require manual SQL or DB recreation (no Alembic).
Acceptable for a personal tool with few schema changes expected.
**Tech debt:** If this ever needs to run across multiple machines or users, the DB layer
would need to be swapped out. [ASSUMED: single-user, single-machine use]

---

### 2026-03-16 — APScheduler embedded vs external cron

**Type:** ADR
**Context:** Need to schedule RSS polling (every 2h) and digest sending (daily).
**Decision:** APScheduler embedded in the Python process.
**Why:** Cross-platform (Windows + Mac). No external dependencies. One command to start.
**Alternatives considered:** OS cron / Task Scheduler (platform-specific, harder to package),
Celery (requires Redis/broker — massive overkill), simple `while True: sleep()` loop
(no missed-job handling, no cron-style scheduling).
**Trade-offs:** If the process dies, scheduled jobs don't run. No built-in job persistence
across restarts (in-memory job store). Acceptable: the tool is designed to run continuously.
**Pitfalls to watch:** APScheduler silently swallows job exceptions by default. Added
`max_instances=1` and `coalesce=True` to prevent job pile-up. Always check APScheduler
logs if jobs seem to stop running.

---

### 2026-03-16 — Pipeline stages are independently callable

**Type:** Decision
**Context:** Poll and digest run at different cadences. Also needed for CLI testing.
**Decision:** `pipeline.run_poll()`, `pipeline.run_evaluation()`, `pipeline.run_digest()`
are each standalone public methods. `run_full()` is a convenience wrapper.
**Why:** Allows `python main.py fetch` (poll only), `python main.py digest` (digest only),
and scheduled runs at different intervals without coupling.
**Trade-offs:** Slightly more surface area in Pipeline. Worth it.

---

### 2026-03-16 — score stored as float 0.0–1.0, threshold in DigestBuilder

**Type:** Decision
**Context:** LLM evaluators return a score. Need to decide range and where threshold lives.
**Decision:** Score is always [0.0, 1.0]. Threshold check lives in `DigestBuilder`,
not in the evaluator.
**Why:** The evaluator's job is to score. The digest stage's job is to decide what's
"good enough." Keeping them separate lets you change the threshold and retroactively
re-digest from existing scored data without re-running evaluation.
**Pitfalls to watch:** All strategies must clamp their score to [0.0, 1.0]. Currently done
in each strategy's parse_response — if a new strategy is added, this must be maintained.

---

### 2026-03-16 — eval/ground_truth.jsonl for evaluator benchmarking

**Type:** Decision
**Context:** No way to know if changing a prompt, model, or strategy actually improved
paper selection without a reference dataset.
**Decision:** 15 hand-labeled papers in `eval/ground_truth.jsonl` covering the full
relevance spectrum. `python main.py eval` runs the configured evaluator against them
and reports MAE, precision, recall.
**Why:** Prevents "feels better" prompt tuning with no actual measurement.
Also serves as regression test when switching backends.
**Tech debt:** 15 papers is enough to start but too small for statistical significance.
Should grow to 50+ over the first month as real papers come in and get labeled.
**Pitfalls to watch:** Ground truth can become stale if research interests shift.
Review and update `eval/ground_truth.jsonl` every few months.

---

### 2026-03-16 — user_feedback field for organic ground truth collection

**Type:** Decision
**Context:** As real papers flow through the system, the user can mark them as
good/noise/missed. This builds ground truth organically without manual curation.
**Decision:** Added `user_feedback` nullable CharField to Paper model.
CLI: `python main.py feedback <guid> good|noise|missed`.
**Why:** Organic feedback is higher quality than synthetic examples because it reflects
real papers from real feeds evaluated by real research interests.
**Tech debt:** Feedback is stored but not yet used to auto-tune threshold or prompts.
Future work: use feedback to periodically recalibrate threshold, fine-tune prompts.
**Pitfalls to watch:** DB schema change. Users with an existing DB need to delete and
recreate it (no migration tooling in place yet).

---

### 2026-03-16 — Inter-call delay of 0.4s between LLM evaluations

**Type:** Decision
**Context:** When evaluating a batch of papers, rapid back-to-back API calls can hit
rate limits on Claude API or overwhelm a local LLM server.
**Decision:** `_EVAL_INTER_CALL_DELAY = 0.4` seconds between calls in pipeline.py.
**Why:** Claude Haiku has generous rate limits but a small delay is courteous.
For local servers (LM Studio, Ollama), rapid calls can cause queue buildup.
**Trade-offs:** Evaluating 100 papers takes ~40s extra. Acceptable.
**Pitfalls to watch:** If using Claude API for large backlogs (hundreds of papers),
0.4s may not be enough. Monitor for 429 errors and increase if needed.
