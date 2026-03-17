# PaperBreakfast — Invariants

These constraints must hold at all times. Violating them breaks correctness or modularity
in ways that may not surface immediately. Review before any refactor.

---

## Data integrity

**I-1: `Paper.guid` is the deduplication key.**
A GUID must uniquely identify a paper across all feeds and all time. Always use
`Paper.get_or_create(guid=guid, defaults={...})` — never `Paper.create()` for ingested papers.
If two feeds publish the same paper, only the first-seen version is stored.

**I-2: `score` is always in [0.0, 1.0] or NULL.**
NULL means not yet evaluated. Every `EvaluationStrategy.parse_response()` must clamp its
output to this range. A score outside [0.0, 1.0] will silently corrupt threshold comparisons.

**I-3: `included_in_digest` is only set True after a successful send.**
The mailer sets this flag only on `send() == True`. If the send fails, papers remain
eligible for the next digest attempt. Never set this flag speculatively.

---

## Architecture

**I-4: `Evaluator.evaluate()` must never write to the database.**
The pipeline owns all persistence. Evaluators are pure transforms: Paper + profile → result.
This keeps evaluators testable without a DB fixture and prevents hidden side effects.

**I-5: `EvaluationStrategy.parse_response()` must never raise.**
Strategies must return `EvaluationResult(score=0.0, parse_error=True)` on any parse failure.
The pipeline evaluates papers in a loop — one bad response must not abort the whole batch.

**I-6: `factory.py` is the only file that imports from both backends/ and strategies/.**
No strategy should import a backend. No backend should import a strategy.
This keeps the two axes genuinely independent.

**I-7: Pipeline stages (`run_poll`, `run_evaluation`, `run_digest`) must remain independently callable.**
The scheduler calls them at different cadences. If you merge them, the system loses the
ability to test/run individual stages.

---

## Configuration

**I-8: Secrets never appear in config.yaml or feeds.yaml.**
API keys and passwords come exclusively from environment variables (via `.env`).
config.yaml is safe to commit; `.env` is gitignored.

**I-9: `config.example.yaml` must stay in sync with `config.py`.**
If you add a field to `AppConfig`, add the corresponding commented example to
`config.example.yaml`. Users copy the example to configure the system.

---

## Evaluator contracts

**I-10: `LLMBackend.complete()` is stateless per call.**
Each call to `complete()` is independent. Backends must not accumulate conversation
history between calls. Paper evaluation is always a fresh context.

**I-11: Score threshold check happens only in `DigestBuilder`, nowhere else.**
The evaluator scores; the digest builder filters. Don't add threshold checks in the
pipeline, poller, or anywhere else. This lets you change the threshold and retroactively
re-filter without re-evaluating.
