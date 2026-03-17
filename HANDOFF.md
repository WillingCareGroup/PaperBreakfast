# Session Handoff

**Last updated:** 2026-03-16
**Session:** Initial build + dev practices + bug fixes + README + first push to GitHub

---

## What happened this session

### Phase 1 — Core system
Full PaperBreakfast codebase built from scratch:
- RSS ingestion, SQLite storage, modular evaluator (backend × strategy), email digest, CLI, APScheduler daemon

### Phase 2 — Dev practices layer
- `CLAUDE.md` — standing instructions, scope guard, regression notes
- `docs/devlog.md` — all decisions documented retroactively
- `docs/invariants.md` — 11 hard constraints
- `.claude/commands/` — `/adr`, `/log`, `/handoff` slash commands
- `eval/ground_truth.jsonl` — 15 labeled papers for benchmarking
- `paperbreakfast/eval.py` — eval runner with MAE / precision / recall / F1
- `user_feedback` field on Paper model

### Phase 3 — Code review + bug fixes
Six bugs fixed before first run:
1. GUID dedup used unstable `hash()` → replaced with `hashlib.sha256`
2. CLI `feedback` argparse conflict → simplified to positional args
3. Regex `self.renewal` matched any char → fixed to `self-renewal`
4. SMTP socket leaked on exception → added `try/finally`
5. Parse errors were silent → added WARNING log in pipeline
6. Empty interest profile was silent → added runtime warning in config loader

### Phase 4 — Wrap-up
- `README.md` written with full setup guide and CLI reference
- All changes committed and pushed to GitHub

---

## Current state

| Component | Status |
|---|---|
| RSS ingestion (feedparser) | Written, untested end-to-end |
| Evaluator — keyword | Written, can test immediately (no API key) |
| Evaluator — Claude API | Written, needs `ANTHROPIC_API_KEY` |
| Evaluator — LM Studio / Ollama | Written, needs local server |
| Email digest | Written, needs SMTP config + Gmail app password |
| Eval benchmark | Written, untested |
| Feedback system | Written, untested |
| Scheduler daemon | Written, untested |

**Nothing has been run yet.** The first real test is Step 5 of the README.

---

## What's needed before first run

1. `config.yaml` — copy from `config.example.yaml`, fill in email section
2. `.env` — copy from `.env.example`, fill in `SMTP_PASSWORD` (and optionally `ANTHROPIC_API_KEY`)
3. Dependencies installed — `pip install -e .` in a venv

---

## Open questions to resolve on first run

1. **Which RSS feeds are live?** — Cell Press `inpress.rss`, Science.org URLs are most likely to need adjustment. Run `python main.py fetch --verbose` and note which feeds return 0 entries or errors.

2. **Gmail app password** — must be an App Password, not account password. See README Step 4.

3. **Score threshold calibration** — 0.6 is a starting guess. After first week, label papers with `feedback` and re-run `eval` to find the right cutoff.

4. **APScheduler timezone** — daemon uses UTC. `send_hour: 8` = 8 AM UTC. Adjust in `config.yaml` for your timezone (UTC+1 → set 7, UTC-5 → set 13, etc.).

5. **DB migration** — if `paperbreakfast.db` was created in an earlier test before `user_feedback` field was added, delete it and let it recreate on next run.

---

## Recommended next steps

```bash
# 1. Install
cd PaperBreakfast
python -m venv .venv && .venv\Scripts\activate
pip install -e .

# 2. Configure
cp config.example.yaml config.yaml   # fill in email + start with backend: keyword
cp .env.example .env                  # fill in SMTP_PASSWORD

# 3. Test ingestion
python main.py fetch --verbose
python main.py status

# 4. Benchmark keyword evaluator
python main.py eval

# 5. Test email
python main.py digest

# 6. Switch to Claude, re-benchmark
# (add ANTHROPIC_API_KEY to .env, change backend.type in config.yaml)
python main.py eval

# 7. Start daemon
python main.py run
```

---

## Known issues to watch
- See `docs/devlog.md` entry "2026-03-16 — Code review + bug fixes" for full list
- GUID fallback (sha256 of title) still theoretically allows collision for identical paper titles — monitor if duplicates appear
- Keyword evaluator terms are hardcoded — cannot be customized without editing `keyword.py`
