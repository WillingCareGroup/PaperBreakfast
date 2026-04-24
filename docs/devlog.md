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

---

### 2026-03-18 — pyproject.toml build fixes (Python 3.14 + setuptools)

**Type:** Pitfall
**Context:** First `pip install -e .` failed on Python 3.14.
**Bugs fixed:**
1. `build-backend = "setuptools.backends.legacy:build"` — this path doesn't exist in bundled setuptools. Changed to `"setuptools.build_meta"`. [VERIFIED]
2. Setuptools flat-layout discovery found both `paperbreakfast/` and `eval/` as top-level packages and refused to build. Fixed with `[tool.setuptools.packages.find] include = ["paperbreakfast*"]`. [VERIFIED]
**Pitfalls to watch:** If new top-level directories are added (e.g. `scripts/`), setuptools will error again unless they are excluded or not Python packages (no `__init__.py`).

---

### 2026-03-18 — Windows cp1252 encoding fix in CLI

**Type:** Pitfall
**Context:** `python main.py feeds` crashed on Windows with `UnicodeEncodeError` for the `✓`/`✗` characters in the feeds table.
**Decision:** Replaced with ASCII `Y`/`N`.
**Why:** Windows terminal defaults to cp1252 which cannot encode those Unicode characters. Rich's legacy Windows renderer hits this before the terminal can handle it.
**Pitfalls to watch:** Any future Rich table additions should use ASCII-safe characters unless `PYTHONUTF8=1` is set in the environment.

---

### 2026-03-18 — First successful end-to-end run

**Type:** Discovery
**Context:** First real test of the full system.
**Results:** 242 papers ingested across 15 feeds (all feeds live [VERIFIED]). Keyword evaluator benchmarked: Precision 100%, Recall 22%, F1 36% — correct baseline behaviour (conservative, no false positives). All RSS URLs valid as of this date.
**Pitfalls to watch:** Cell Press and Science.org RSS URLs may restructure without redirects — verify if feeds start returning 0 entries.

---

### 2026-03-18 — Email digest configured and tested

**Type:** Decision
**Context:** First live email send.
**Decision:** Gmail SMTP (smtp.gmail.com:587 STARTTLS) with App Password stored in `.env`. Sender: `youraddress@gmail.com`, receiver: `recipient@example.com`.
**Why:** Gmail App Passwords are the only supported SMTP auth method when 2FA is enabled on a Google account. Regular account password is rejected.
**Pitfalls to watch:** App Passwords are silently revoked if 2FA is disabled or the Google account security settings change. If SMTP auth starts failing, regenerate the App Password.

---

### 2026-03-18 — Schema addition: institution + pi_name on Paper model

**Type:** Decision
**Context:** User wanted PI lab name and institution displayed on each digest card.
**Decision:** Added `institution = CharField(max_length=256, null=True)` and `pi_name = CharField(max_length=256, null=True)` to `Paper` model. Added matching optional fields to `EvaluationResult` in `base.py`. Updated `pipeline.py` to write them when non-null. Updated `relevance_json.py` strategy (v2) to request these fields in JSON output with explicit "null if unknown, do not guess" instruction.
**Why:** RSS feeds do not carry affiliation data. LLM extraction from training knowledge + abstract scanning is the only viable approach without a separate web fetch step.
**Trade-offs / tech debt:** Coverage is partial — Haiku 4.5 populated pi_name for 16/25 papers and institution for only 1/25 in initial run. Institution fill rate will improve as the prompt also scans abstract text for affiliation mentions.
**Pitfalls to watch:** DB was deleted and recreated to add the new columns. Any future schema changes will require the same (no migration tooling). pi_name values from the LLM are in "Last, First" format (pulled from author list convention) — not always the true corresponding author.

---

### 2026-03-18 — Digest template redesign

**Type:** Decision
**Context:** First email had alignment bug (score badge floating randomly), no topic tags, no PI/institution, no explicit read link, and journal grouping was too heavy for low-volume daily use.
**Decision:** Full template rewrite:
- Score badge: replaced CSS flex with HTML table layout for reliable email client alignment [VERIFIED fix]
- Layout: removed journal section grouping — flat list sorted by score, journal name as small label on each card
- Added topic tags (10 categories + Milestone) inferred at render time in builder.py from title+abstract regex — no extra LLM cost
- PI + institution meta line below tags; falls back to last author (senior author convention) when pi_name is null
- Replaced two ambiguous grey text blocks with labelled sections: "WHY RECOMMENDED" (Claude's reasoning only; abstract snippet removed)
- Added explicit "Read paper →" link
- Banner: date moved to top-right corner via table layout; stats use inline-block with margin-right instead of flex gap for email client compatibility
**Pitfalls to watch:** flex/gap is unreliable in some email clients — always use table or inline-block for layout-critical elements in the HTML template.

---

### 2026-03-18 — Model comparison: Haiku 4.5 vs Claude 3 Haiku

**Type:** ADR
**Context:** User asked whether a cheaper model could be used. Claude 3 Haiku costs ~3x less ($0.25/$1.25 vs $0.80/$4 per MTok).
**Decision:** Keep claude-haiku-4-5-20251001. [VERIFIED against ground truth benchmark]
**Results on 15-paper eval set:**

| Metric | Haiku 4.5 | Claude 3 Haiku |
|---|---|---|
| MAE | 0.088 | 0.129 |
| Precision | 81.8% | 75.0% |
| Recall | 100% | 100% |
| F1 | 90.0% | 85.7% |

**Why:** Claude 3 Haiku has a systematic overscoring bias — it scores nearly everything 0.80–0.90 regardless of true relevance, and its reasoning is generic ("The paper is highly relevant to the researcher's profile"). This produces 3 extra false positives per digest. At ~$0.30/month cost difference, the quality trade-off is not worth it.
**Pitfalls to watch:** Re-run this benchmark if Anthropic releases a new Haiku model or changes pricing significantly.

---

### 2026-03-18 — RSS feed expansion: all 48 feeds verified working

**Type:** Fix | Discovery
**Context:** Expanded feed list from 15 to 48 journals; direct RSS URLs for ASH, AACR, JAMA, and BioMed Central all returned 403/404.
**Detail:** ASH (Blood, Blood Advances), AACR (Cancer Discovery, Clinical Cancer Research), and JAMA Oncology block direct RSS scraping — resolved via PubMed mirror RSS (`pubmed.ncbi.nlm.nih.gov/rss/journals/{slug}`). [VERIFIED: 20 entries each] JHO BioMed Central direct RSS 404 — resolved via Springer search RSS (`link.springer.com/search.rss?facet-journal-id=13045`). Mol Therapy sub-journals absent from cell.com — resolved via ScienceDirect ISSN-based feeds. Nature CDN journals (Blood Cancer Journal, BMT, npj Regen Med) resolved via `feeds.nature.com` CDN instead of `www.nature.com`. Windows scheduled task created via `schtasks` running `run_digest.bat` weekdays at 10:00 AM.
**Impact:** All 48/48 feeds return entries [VERIFIED]. PubMed mirror lags by ~24h vs direct publisher feeds — acceptable for daily digest cadence. Scheduled task uses Interactive logon; will not run if user is logged out.

---

### 2026-03-19 — Session 2: enrichment, chunked eval, error surfacing

**Type:** Decision
**Context:** Full pipeline buildout session — reliability, cost efficiency, and data quality all addressed in one pass.
**Detail:** Added Crossref+PubMed enrichment stage (new `doi` field + migration, `run_enrichment()` after scoring) — [VERIFIED: 58/61 recommended papers got real PI/institution data]. Replaced per-paper LLM calls with chunked evaluation (25 papers/call): 34 calls for 833 papers vs 833, `max_tokens` raised to 4096, markdown fence stripping added to parser. ClaudeBackend now retries transient errors with exponential backoff (2s→4s→8s); auth errors still fail immediately. Feed/eval errors now surface in digest email (red box + N/48 feeds OK stat in header). Batch API infrastructure built (`use_batch` flag) but disabled — chunked mode is strictly better for synchronous use. Live end-to-end run: 48/48 feeds, 288 papers, 0 errors, 148-paper digest sent. [VERIFIED]
**Impact:** Token cost reduced ~96% on evaluation overhead. Watch: chunk parse failures fall back to individual calls silently — monitor logs if scores look off. Enrichment skips papers without a DOI (Cell/Nature links don't carry DOI in URL, only in `dc_identifier` which is now stored).

---

### 2026-03-20 — Pipeline v2: triage classification, Sonnet 4.6, prompt caching, structured summary

**Type:** Decision
**Context:** First week of live digests revealed two problems: too many false positives (numeric score compression around 0.6–0.7) and a one-sentence reasoning field too thin to be actionable.
**Detail:** Replaced float score with categorical triage (read/skim/skip) + independent milestone boolean — eliminates false precision and forces the model to make a discrete commitment. Switched model to claude-sonnet-4-6 [ASSUMED: higher triage accuracy vs Haiku], temperature 0.0, chunk_size 10. Profile embedded in system prompt for prompt caching (cache_control ephemeral) — all chunk calls after the first pay ~10% for the system prompt. Replaced one-sentence reasoning with four-field structured summary: Problem / Model / Finding / Impact; Model field uses N/A if not stated in abstract to prevent hallucination. DB schema extended with triage/milestone/summary columns (ALTER TABLE migration, old score/reasoning columns kept as legacy). Enrichment threshold changed from score≥0.6 to triage∈{read,skim}. Banner stats updated to x/y recommended/total-today + feeds-online with ⚠ on error. Prompt content is v5 placeholder — full decision-tree prompt (v6) to be written before DB re-evaluation. [VERIFIED: smoke tests pass, 1590 papers marked unevaluated and awaiting re-evaluation with new prompt]
**Impact:** Full DB re-evaluation required before next digest. Batch API intentionally kept disabled — batch and chunked are mutually exclusive in current architecture; $1.27/month Sonnet cost difference does not justify restructuring.

---

### 2026-03-20 — v6 prompt integration: horizon label, new profile, full code wiring

**Type:** Decision
**Context:** v5 was a placeholder. v6 prompt designed in a separate agent session (see `prompt research/`), ready for integration.
**Detail:** Added fourth triage label `horizon` (Type A: broad breakthrough; Type B: cross-domain transfer) across all code paths — `relevance_json.py` parser, chunked eval in `pipeline.py`, `db.py` digest query, enrichment query, `builder.py` sort order. `parse_response()` now handles JSON array format (v6 spec) with backward-compat fallback to bare object. Template redesigned with three named sections (Read / On the Horizon / Skim) using a Jinja2 macro; horizon cards render in indigo with a `Transfer` summary field. `profile.md` replaced with v6 profile (factual bio only; instructional sentences moved into system prompt as "Baseline Knowledge adjustment" rule). `SYSTEM_TEMPLATE` exported from `relevance_json.py` and imported by `pipeline.py` — single source of truth for prompt text. [VERIFIED: files updated, pending first live run]
**Impact:** 1590 papers awaiting re-evaluation with v6 prompt. Run `python main.py evaluate` then `python main.py digest` to confirm. Watch: horizon label rate — if consistently >10-15% of daily output, profile may be too broad.

---

### 2026-03-21 — Post-v6 bug sweep and cleanup

**Type:** Fix
**Context:** Full project review after v6 integration revealed legacy code paths still referencing removed `score`/`reasoning` fields on `EvaluationResult`.
**Detail:** Fixed five crash bugs: `keyword.py` and `chain_of_thought.py` were returning `EvaluationResult(score=..., reasoning=...)` (fields removed in v2); `cli.py` `cmd_status`/`cmd_feedback` queried `Paper.score` (never written); `eval.py` accessed `outcome.score` and computed MAE (metric removed). Deleted `prompt research/` directory (content fully integrated). Updated README: removed MAE references, corrected model to `claude-sonnet-4-6`, updated output format description, fixed score_threshold description, fixed feedback command syntax. [VERIFIED: all imports and functional tests pass]
**Impact:** keyword and chain_of_thought backends were silently broken since v2 migration — now restored. CLI status/feedback and eval benchmark are now correct.

---

### 2026-04-16 — Fix: ClaudeBackend empty content crash (stop_reason=refusal)

**Type:** Fix / Discovery
**Context:** Three papers consistently failed with `list index out of range` across every evaluation run; two were stuck at `triage=None` indefinitely.
**Detail:** Root cause: `message.content[0].text` in `claude.py` raises IndexError when the API returns an empty content list. Fixed by guarding with `if not message.content: return ""` and logging `stop_reason`. [VERIFIED: stop_reason=refusal] — Claude's safety system refuses papers containing insecticidal toxin (Vip1-Vip2 / Bacillus thuringiensis) and H5N1 content outright. Returning `""` routes through `parse_response` → `triage=skip, parse_error=True`, which saves the papers and clears them from the unevaluated queue permanently.
**Impact:** Unevaluated queue now 0. `parse_error=True` is not persisted to DB so refused papers are indistinguishable from normal skips — the `stop_reason=refusal` WARNING log is the only signal. Watch logs if unexpected papers go missing from future digests.
