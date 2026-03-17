# PaperBreakfast

Polls RSS feeds from scientific journals, evaluates paper abstracts against your research interest profile using an LLM, and delivers a daily HTML email digest — same day papers go online.

---

## Architecture

```
RSS feeds (feedparser)
    ↓  every 2 hours
SQLite (peewee) — dedup by GUID
    ↓
Evaluator — modular backend × strategy
    │  Backends:  Claude API | LM Studio | Ollama | Keyword (no LLM)
    │  Strategies: relevance_json | chain_of_thought
    ↓
Daily HTML email digest (Jinja2 + smtplib)
```

Backends and strategies are independent — swap either in `config.yaml` with no code changes.

---

## Setup

### 1. Prerequisites

Python 3.10+ required.

```bash
python --version
```

### 2. Install

```bash
git clone https://github.com/WillingCareGroup/PaperBreakfast.git
cd PaperBreakfast

python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # Mac/Linux

pip install -e .
```

### 3. Config files

```bash
cp config.example.yaml config.yaml
cp .env.example .env
```

Edit `config.yaml` — fill in the email section at minimum:

```yaml
email:
  smtp_host: smtp.gmail.com
  smtp_port: 587
  smtp_user: youraddress@gmail.com
  from_addr: youraddress@gmail.com
  to_addrs:
    - digest@wherever.you.want.it
```

**Start with the keyword evaluator** (no API key required):

```yaml
evaluator:
  backend:
    type: keyword
  strategy:
    type: relevance_json
```

### 4. Gmail App Password

Gmail requires an App Password for SMTP — your account password will not work.

1. [myaccount.google.com](https://myaccount.google.com) → **Security**
2. **2-Step Verification** must be ON
3. Search **"App passwords"** → create one → name it "PaperBreakfast"
4. Add the 16-character password to `.env`:

```
SMTP_PASSWORD=abcd efgh ijkl mnop
```

### 5. First test run

```bash
# Verify config loads and feeds are listed
python main.py feeds

# Poll all feeds and store new papers
python main.py fetch --verbose

# Check what came in
python main.py status
```

Expect a few feed errors on first run — publishers occasionally change RSS URLs.
Note which ones fail and update `feeds.yaml` as needed.

### 6. Benchmark the keyword evaluator

```bash
python main.py eval
```

Runs 15 hand-labeled papers through the evaluator and reports MAE, precision, recall, F1.
Expect MAE ~0.25–0.35 with the keyword backend. This is your baseline.

### 7. Test email delivery

```bash
python main.py digest
```

Check your inbox (and spam folder the first time).

### 8. Switch to Claude API (recommended)

Get an API key at [console.anthropic.com](https://console.anthropic.com). Add to `.env`:

```
ANTHROPIC_API_KEY=sk-ant-...
```

Update `config.yaml`:

```yaml
evaluator:
  backend:
    type: claude
    model: claude-haiku-4-5-20251001    # fast and cheap (~$1-3/month for this workload)
  strategy:
    type: relevance_json
```

Re-run the benchmark to see the improvement:

```bash
python main.py eval
```

Expect MAE ~0.10–0.15 and recall 85%+.

### 9. Local LLM (LM Studio or Ollama)

Start your local server, then set in `config.yaml`:

```yaml
evaluator:
  backend:
    type: openai_compat
    model: your-model-name        # e.g. llama-3.3-70b
    base_url: http://localhost:1234/v1   # LM Studio default
    # base_url: http://localhost:11434/v1  # Ollama default
```

### 10. Start the daemon

```bash
python main.py run
```

Polls feeds every 2 hours, sends digest daily at 8:00 UTC (adjust `send_hour` in `config.yaml`).

---

## CLI reference

| Command | Description |
|---|---|
| `python main.py run` | Start the scheduler daemon |
| `python main.py fetch` | Run one poll + evaluate cycle now |
| `python main.py digest` | Send digest immediately |
| `python main.py status` | Show database statistics |
| `python main.py feeds` | List configured feeds |
| `python main.py eval` | Benchmark evaluator against ground truth |
| `python main.py feedback list` | Show recent papers by score |
| `python main.py feedback <guid> good\|noise\|missed` | Record relevance feedback |

All commands accept `--verbose` / `-v` for debug logging.

---

## Tuning

### Interest profile

Edit `profile.md`. This is the primary lever for relevance quality.
The LLM evaluates every abstract against it verbatim — be specific about what you want
and explicit about what you don't.

### Score threshold

In `config.yaml`, `score_threshold: 0.6` controls the cutoff for the digest.
After the first week, use feedback to label papers and re-run `eval` to calibrate.

### Adding feeds

Add entries to `feeds.yaml`:

```yaml
- url: https://www.cell.com/cell-stem-cell/inpress.rss
  name: Cell Stem Cell
  group: cell-press
  enabled: true
```

Set `enabled: false` to temporarily pause a feed without deleting it.

### Switching evaluators

Change `evaluator.backend.type` and `evaluator.strategy.type` in `config.yaml`.
Run `python main.py eval` to benchmark before committing to a change.

---

## Evaluator backends and strategies

| Backend | Requires | Notes |
|---|---|---|
| `claude` | `ANTHROPIC_API_KEY` | Best quality, ~$1-3/month |
| `openai_compat` | Local server running | LM Studio, Ollama, vLLM |
| `keyword` | Nothing | Useful for testing; no LLM |

| Strategy | Output format | Best for |
|---|---|---|
| `relevance_json` | `{"score": 0.8, "reasoning": "..."}` | Fast, structured, default |
| `chain_of_thought` | Step-by-step → `SCORE: 0.8` | Diagnosing why papers are/aren't recommended |

---

## Dev docs

- `docs/devlog.md` — full decision log with rationale, trade-offs, pitfalls
- `docs/invariants.md` — architectural constraints that must not be broken
- `HANDOFF.md` — current project state, open questions, next steps
- `eval/ground_truth.jsonl` — 15 hand-labeled papers for evaluator benchmarking

### Slash commands (Claude Code)

| Command | Action |
|---|---|
| `/adr <decision>` | Append a structured Architecture Decision Record to devlog |
| `/log <note>` | Append a quick entry (pitfall, fix, discovery) to devlog |
| `/handoff` | Rewrite HANDOFF.md to reflect the current session state |
