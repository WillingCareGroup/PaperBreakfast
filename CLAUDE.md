# PaperBreakfast — Claude Standing Instructions

## Read at the start of every session
1. `HANDOFF.md` — current state, open questions, recommended next steps
2. `docs/invariants.md` — constraints that must never be violated
3. Last 10 entries of `docs/devlog.md` — recent decisions and context

---

## Dev log protocol

When making a significant decision (architecture, trade-off, tech debt accepted,
approach rejected, pitfall discovered), append an entry to `docs/devlog.md`:

```
### YYYY-MM-DD — <short title>
**Type:** Decision | ADR | Pitfall | Tech-debt | Discovery
**Context:** what situation led to this
**Decision:** what was decided
**Why:** driving reason (constraint, perf, simplicity, etc.)
**Alternatives considered:** what was rejected and why
**Trade-offs / tech debt:** what this sacrifices or defers
**Pitfalls to watch:** known risks or future gotchas
```

Mark uncertain facts with `[ASSUMED]` and verified facts with `[VERIFIED]` so future
sessions can distinguish between the two.

---

## Scope guard

Stop and summarize a plan before writing any code if the task requires:
- Creating more than 3 new files, **OR**
- Modifying more than 5 existing files, **OR**
- Changing the evaluator base interfaces (`evaluators/base.py`), **OR**
- Adding new `pyproject.toml` dependencies

Exception: user has explicitly said "proceed autonomously" for this session.

---

## Requires explicit user approval
- Schema changes to `paperbreakfast/models/db.py`
- Interface changes to `paperbreakfast/evaluators/base.py`
- Breaking changes to `config.example.yaml` schema
- New entries in `pyproject.toml` dependencies

## Claude decides autonomously
- Implementation details within a file
- Variable naming and code style
- Error message wording
- Test implementation details
- Comment and docstring content

---

## Architecture reminders

**Evaluator system** (most important to preserve):
- `LLMBackend` and `EvaluationStrategy` vary independently — never couple them
- `factory.py` is the only file that knows the full backend × strategy matrix
- `Evaluator.evaluate()` must never write to the DB — pipeline owns all persistence
- Adding a backend or strategy = one new file + one line in `factory.py`

**Pipeline stages are independent**:
- `run_poll()` → `run_evaluation()` → `run_digest()` can each be called standalone
- The scheduler calls them at different cadences — don't couple them

---

## Regression notes — do not re-introduce

- `IntegerField` must be imported at top of `db.py` with other peewee imports
  (was accidentally placed at bottom as a late import hack)
- `feedparser` `bozo_exception` is not always a real error — log as warning, never raise
- `Evaluator.evaluate()` must never write to the DB
- `EvaluationStrategy.parse_response()` must never raise — return parse_error result instead

---

## End of session

Update `HANDOFF.md` with:
- What was done this session
- Current project state (what works, what doesn't)
- Open questions
- Recommended next steps
