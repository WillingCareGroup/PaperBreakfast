# Session Handoff

> **For contributors:** This file is automatically maintained by Claude Code at the end of each development session. It reflects the current project state, open questions, and recommended next steps. It is intentionally included in the repository to give contributors full context on where the project stands.

---

**Last updated:** 2026-04-16
**Session:** Diagnosed and resolved missed scheduled runs (April 15–16) due to interactive logon requirement

---

## What happened this session

- **Investigation: missed runs April 15–16** — `logs/scheduler.log` last modified April 14 at 10:04 AM confirmed two days of missed digests. Task Scheduler `LastTaskResult: 0x800710E0` (requires interactive window station) and `LogonType: Interactive` confirmed the root cause: the task silently skips when the user's screen is locked or session is inactive.
- **Fix applied by user** — Task Scheduler config changed from "Run only when user is logged on" to "Run whether user is logged on or not". No code changes this session.
- **Confirmed previous fixes are live** — `scheduler.log` shows 14 successful runs since March 21, with `N/48` feeds stat (not `?`) and `run-once` working correctly. Both March 25 bug fixes (`run-once` CLI, HTML attachment) are confirmed working in production.

---

## Current state

| Component | Status |
|---|---|
| RSS ingestion — 48 feeds | Working |
| Evaluator — chunked Sonnet 4.6, v6 prompt | Working |
| `evaluator_model` field | Working |
| Triage system — 4 labels | Working |
| Crossref/PubMed enrichment (PubMed-first) | Working |
| Email digest — HTML body + attachment | Working (confirmed live) |
| `run-once` CLI command | Working (confirmed live) |
| Windows scheduled task | Working — fixed to run without interactive logon |
| Eval benchmark | Working |
| Feedback system | Working |

**Active config:** `backend: claude`, model `claude-sonnet-4-6`, `chunk_size: 10`, `temperature: 0.0`, `use_batch: false`

**DB state:** 3848 papers total, 3845 evaluated, 227 recommended/unsent, 624 sent across 30 digest runs.

**What's missing before next step:**
- Confirm task fires correctly at 10 AM April 17 without user being logged on

---

## Open questions / things to verify

1. **Scheduled task fix** — Confirm April 17 run fires at 10 AM even if screen is locked. Check `logs/scheduler.log` for new entry after 10 AM.
2. **Recurring chunk parse errors** — Both recent runs showed 3 errors (`list index out of range` in chunk 1 fallback). Same 3 papers failing consistently: "Structural basis for the assembly and translocation of the V", "Complete biosynthesis of nicotine", "Preclinical evaluation of an mRNA vaccine". Investigate whether these are parse failures or papers with unusual content that causes issues.
3. **HTML attachment** — Confirmed arriving, but verify it opens correctly in browser when email body is clipped (only verifiable on a large digest day).
4. **`multipart/mixed` compatibility** — Some older email clients may render `mixed` differently than `alternative`. Watch for any formatting regression.
5. **Haiku papers still in DB** — 763 papers evaluated with haiku 4.5 remain tagged `evaluator_model = claude-haiku-4-5-20251001`. Consider re-evaluating with sonnet (~$0.50).
6. **Horizon rate with sonnet** — 196 horizon papers in DB (of ~810 read/skim/horizon) ≈ 24%. Monitor whether this feels right over live digests.

---

## Recommended next steps

```bash
# After 10 AM April 17 — verify the task fired without interactive logon:
tail -50 logs/scheduler.log

# If chunk parse errors are recurring, investigate the 3 failing papers:
python main.py status

# Label papers to grow ground truth (target 50+)
python main.py feedback
python main.py feedback <guid> good|noise|missed
```

**Longer term:**
- Decide whether to re-evaluate the 763 haiku papers with sonnet (costs ~$0.50, cleans up the split DB)
- Grow ground truth to 50+ papers for statistically meaningful eval
- Investigate recurring chunk parse errors on the 3 consistently failing papers
- Consider article type detection once a reliable signal is found
- Consider `focus` as a dedicated prompt field for skim — requires prompt approval

---

## Known issues / pitfalls

- **Prompt/profile are frozen** — any changes to `relevance_json.py` (prompt) or `profile.md` require explicit user approval before editing.
- **763 haiku papers in DB** — triage distribution differs from sonnet. Mixed DB until re-evaluated or aged out.
- **Recurring chunk parse errors** — 3 papers consistently fail with `list index out of range` in the chunk 1 fallback path. Not blocking (they're skipped), but worth investigating.
- **PubMed RSS lags ~24h** — Blood, Blood Advances, Cancer Discovery, CCR, JAMA Oncology via PubMed mirrors.
- **`included_in_digest` is permanent** — re-sending requires direct DB unmark.
- **pi_name format inconsistent** — "Last F" vs "Last First" depending on source. Not normalised.
- See `docs/devlog.md` for full historical context.
