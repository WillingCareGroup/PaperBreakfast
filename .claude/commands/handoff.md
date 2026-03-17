Update `HANDOFF.md` to reflect the current state of the session.

Read through the conversation and all files touched this session, then rewrite HANDOFF.md with:

```markdown
# Session Handoff

**Last updated:** YYYY-MM-DD
**Session:** <one-line description of what this session was about>

---

## What happened this session
<bullet list of meaningful changes — files created/modified, decisions made, bugs fixed>

---

## Current state
<table or list of components with status: working / written-untested / broken / in-progress>

**What's missing before next step:**
<concrete blockers>

---

## Open questions / things to verify
<numbered list — be specific, include how to verify each>

---

## Recommended next steps
<ordered list of concrete commands or actions>

---

## Known issues / pitfalls
<brief list — link to devlog entries if relevant>
```

Use today's actual date. Be honest about what's tested vs untested.
After writing, confirm with a one-line summary of what changed in the handoff.
