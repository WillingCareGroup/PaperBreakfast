# Session Handoff

**Last updated:** 2026-03-21
**Session:** Haiku→Sonnet migration, evaluator_model tracking, digest header redesign, enrichment improvements

---

## What happened this session

- **Cleanup from previous session** — deleted `prompt research/` directory (3 files, all content integrated); updated README.md: removed MAE references, updated model to `claude-sonnet-4-6`, fixed output format description, score_threshold description, feedback command syntax, architecture diagram.
- **Smoke tests** — all 6 functional tests passed (imports, keyword, chain_of_thought, relevance_json, DigestBuilder, EvalResult).
- **Re-evaluation run** — 1590 papers were pending. Started accidentally with haiku 4.5 (old config), killed at 1525 evaluated. Updated `config.yaml` to sonnet 4.6 (`temperature: 0.0`, `chunk_size: 10`).
- **`evaluator_model` field added** — new `CharField(null=True)` on `Paper` model with ALTER TABLE migration. `_save_evaluation()` in `pipeline.py` now writes `config.evaluator.backend.model` for every paper. Backfilled 1525 haiku papers with `claude-haiku-4-5-20251001`.
- **Haiku vs Sonnet comparison** — reset 762 haiku papers for sonnet re-evaluation (random seed 42). Sonnet evaluated all 762 + ~120 new polled papers (883 total). Results: haiku 31.3% recommended (7.1% read, 12.5% skim, 11.8% horizon) vs sonnet 18.1% (2.7% read, 13.5% skim, 1.9% horizon). Haiku over-inflated horizon and read. Sonnet confirmed as correct model.
- **Enrichment: PubMed-first** — swapped order: PubMed now runs first, Crossref as fallback. PubMed corresponding author detection: authors with `@` in affiliation are corresponding authors; first one wins. Falls back to last author if none marked. Previous code always used last author.
- **Enrichment run** — 0 new papers enriched; all 17 unenriched papers are recent 2026 publications not yet indexed by PubMed. Will self-resolve.
- **Feeds stat in standalone digest** — fixed: `feeds_total` now shows configured feed count (`len(config.feeds)`) even when no poll ran. Shows `?/48` in grey when poll data unavailable.
- **Digest header redesign** — Read/Horizon/Skim counts (big, colored) on left; PaperBreakfast title + date top-right; status corner (small) bottom-left shows `recommended/total` and `feeds`. Removed journals stat.
- **Skim "Focus" label** — skim cards now show `Impact` field labelled "Focus" in amber. Read/horizon cards keep "Impact" label. Template-only change, no prompt change.
- **Prompt/profile approval rule established** — rolled back a v7 prompt attempt (article_type + focus fields). Rule: `relevance_json.py` and `profile.md` must not be edited without explicit user approval.
- **Digest sent** — 24 papers to zhengpri@gmail.com. [VERIFIED]

---

## Current state

| Component | Status |
|---|---|
| RSS ingestion — 48 feeds | Working |
| Evaluator — chunked Sonnet 4.6, v6 prompt | Working — confirmed on 883 papers |
| `evaluator_model` field | Working — all papers labelled, new evals auto-tagged |
| Triage system — 4 labels | Working |
| Crossref/PubMed enrichment (PubMed-first) | Working — corresponding author detection active |
| Email digest — 3-section template | Working — header redesigned, Focus label for skim |
| Windows scheduled task | Running — weekdays 10AM |
| Eval benchmark | Working — triage-based P/R/F1 |
| Feedback system | Working |
| keyword / chain_of_thought backends | Working |

**Active config:** `backend: claude`, model `claude-sonnet-4-6`, `chunk_size: 10`, `temperature: 0.0`, `use_batch: false`

**Nothing blocking** — system is live and running.

---

## Open questions / things to verify

1. **Haiku papers still in DB** — 763 papers evaluated with haiku 4.5 remain tagged `evaluator_model = claude-haiku-4-5-20251001`. These will appear in future digests if they're within the 24h window and haven't been sent. Consider whether to re-evaluate them with sonnet. Query: `SELECT count(*) FROM papers WHERE evaluator_model='claude-haiku-4-5-20251001' AND triage IN ('read','skim','horizon') AND included_in_digest=0`.
2. **2026 unenriched papers** — 17 papers lack institution (very recent, PubMed not indexed yet). Will self-resolve; run `python main.py fetch` in a week to pick them up.
3. **Horizon rate with sonnet** — 1.9% vs haiku's 11.8%. Watch over the next week of live digests to confirm this feels right. May need prompt tuning if it seems too low.
4. **Corresponding author coverage** — new PubMed-first enrichment with email detection untested on a large batch. Verify PI names look more accurate in the next digest.
5. **Focus label for skim** — confirm it renders correctly in email client (amber "Focus" label).

---

## Recommended next steps

```bash
# Normal daily operation — scheduled task handles this automatically
# Manual run if needed:
python main.py fetch        # poll + evaluate + enrich
python main.py digest       # send

# Check haiku papers still pending digest
python main.py status

# Label papers to grow ground truth (target 50+)
python main.py feedback
python main.py feedback <guid> good|noise|missed

# Re-benchmark with sonnet
python main.py eval
```

**Longer term:**
- Decide whether to re-evaluate the 763 haiku papers with sonnet (costs ~$0.50, cleans up the split DB)
- Grow ground truth to 50+ papers for statistically meaningful eval
- Consider article type detection once a reliable signal is found (RSS metadata, DOI prefix patterns)
- Consider `focus` as a dedicated prompt field for skim (currently embedded in `impact`) — requires prompt approval

---

## Known issues / pitfalls

- **Prompt/profile are frozen** — any changes to `relevance_json.py` (prompt) or `profile.md` require explicit user approval before editing.
- **763 haiku papers in DB** — triage distribution differs from sonnet. Mixed DB until re-evaluated or aged out.
- **Interactive logon only** — scheduled task won't fire if screen is locked. Fix: Task Scheduler → PaperBreakfast → "Run whether user is logged on or not".
- **PubMed RSS lags ~24h** — Blood, Blood Advances, Cancer Discovery, CCR, JAMA Oncology via PubMed mirrors.
- **`included_in_digest` is permanent** — re-sending requires direct DB unmark.
- **pi_name format inconsistent** — "Last F" vs "Last First" depending on source. Not normalised.
- See `docs/devlog.md` 2026-03-21 entry for full context.
