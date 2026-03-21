"""
Evaluator benchmarking against the ground truth dataset.

Usage:
    python main.py eval
    python main.py eval --gt eval/ground_truth.jsonl

Metrics reported:
    Precision  — of papers the model recommends (read/skim), fraction truly relevant
    Recall     — of truly relevant papers, fraction the model catches
    F1         — harmonic mean of precision and recall

The ground truth file is a JSONL where each line has:
    id, title, abstract, journal, authors, human_score (0.0–1.0), notes

human_score >= score_threshold is treated as "relevant".
Model triage of read or skim is treated as "recommended".
"""
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.table import Table

logger = logging.getLogger(__name__)
console = Console()

# Triage values the model can return
_RECOMMENDED = frozenset(["read", "skim"])

# Rich color per triage value
_TRIAGE_COLOR = {
    "read": "green",
    "skim": "yellow",
    "horizon": "magenta",
    "skip": "dim",
}


@dataclass
class EvalPaper:
    """
    Lightweight stand-in for the DB Paper model used during eval runs.
    Has the same attributes that EvaluationStrategy.build_prompts() accesses.
    NOT stored in the database.
    """
    guid: str
    title: str
    abstract: str
    journal: str
    authors: str
    human_score: float
    notes: str = ""
    url: str = ""


@dataclass
class EvalResult:
    paper: EvalPaper
    triage: Optional[str]       # model output: read / skim / horizon / skip
    summary: Optional[dict]     # structured summary from model
    error: Optional[str] = None

    @property
    def recommended(self) -> Optional[bool]:
        """True if model recommends this paper (read or skim)."""
        if self.triage is None:
            return None
        return self.triage in _RECOMMENDED


def load_ground_truth(path: str = "eval/ground_truth.jsonl") -> list[EvalPaper]:
    gt_file = Path(path)
    if not gt_file.exists():
        raise FileNotFoundError(
            f"Ground truth file not found: {path}\n"
            "Expected: eval/ground_truth.jsonl"
        )

    papers = []
    with open(gt_file, encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                d = json.loads(line)
                papers.append(EvalPaper(
                    guid=d["id"],
                    title=d["title"],
                    abstract=d["abstract"],
                    journal=d.get("journal", ""),
                    authors=d.get("authors", ""),
                    human_score=float(d["human_score"]),
                    notes=d.get("notes", ""),
                ))
            except (json.JSONDecodeError, KeyError) as e:
                logger.warning(f"Skipping malformed line {lineno} in {path}: {e}")

    return papers


def run_eval(config, gt_path: str = "eval/ground_truth.jsonl") -> dict:
    from paperbreakfast.evaluators.factory import build_evaluator

    papers = load_ground_truth(gt_path)
    evaluator = build_evaluator(config)
    threshold = config.evaluator.score_threshold

    console.print(
        f"\n[bold]Evaluator benchmark[/] — {evaluator.name} — {len(papers)} papers\n"
        f"  Relevant threshold: human_score >= [cyan]{threshold:.0%}[/]\n"
        f"  Recommended = model triage ∈ {{read, skim}}\n"
    )

    results: list[EvalResult] = []
    for i, paper in enumerate(papers, 1):
        console.print(f"  [{i:02d}/{len(papers)}] {paper.title[:65]}...", end="\r")
        try:
            outcome = evaluator.evaluate(paper, config.interest_profile)
            results.append(EvalResult(
                paper=paper,
                triage=outcome.triage,
                summary=outcome.summary,
            ))
        except Exception as exc:
            logger.error(f"Eval failed for {paper.guid}: {exc}")
            results.append(EvalResult(
                paper=paper,
                triage=None,
                summary=None,
                error=str(exc),
            ))

    console.print(" " * 80, end="\r")  # clear progress line

    # ── Results table ─────────────────────────────────────────────────────────
    t = Table(title=f"Results — {evaluator.name}", show_lines=False)
    t.add_column("ID", style="dim", width=6)
    t.add_column("Title", max_width=40)
    t.add_column("Human", justify="right", width=6)
    t.add_column("Triage", width=8)
    t.add_column("OK?", width=4)
    t.add_column("Notes / Error", max_width=32, style="dim")

    for r in results:
        human_str = f"{r.paper.human_score:.2f}"
        human_relevant = r.paper.human_score >= threshold

        if r.triage is None:
            t.add_row(r.paper.guid[:6], r.paper.title[:40], human_str,
                      "[red]ERR[/]", "[red]x[/]", r.error or "")
            continue

        color = _TRIAGE_COLOR.get(r.triage, "white")
        triage_str = f"[{color}]{r.triage}[/]"

        correct = (human_relevant == r.recommended)
        ok_str = "[green]Y[/]" if correct else "[red]N[/]"

        notes = r.paper.notes[:32] if r.paper.notes else ""
        t.add_row(r.paper.guid[:6], r.paper.title[:40], human_str,
                  triage_str, ok_str, notes)

    console.print(t)

    # ── Metrics ───────────────────────────────────────────────────────────────
    valid = [r for r in results if r.triage is not None]
    if not valid:
        console.print("[red]No valid results — cannot compute metrics.[/]")
        return {}

    tp = sum(1 for r in valid if r.paper.human_score >= threshold and r.recommended)
    fp = sum(1 for r in valid if r.paper.human_score <  threshold and r.recommended)
    fn = sum(1 for r in valid if r.paper.human_score >= threshold and not r.recommended)
    tn = sum(1 for r in valid if r.paper.human_score <  threshold and not r.recommended)

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall    = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1        = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

    # Triage distribution
    dist = {}
    for r in valid:
        dist[r.triage] = dist.get(r.triage, 0) + 1

    console.print(f"\n[bold]Metrics[/] (threshold [cyan]{threshold:.0%}[/] for relevant):")
    console.print(f"  Papers evaluated : {len(valid)} / {len(papers)}")
    console.print(f"  Precision        : [cyan]{precision:.1%}[/]  (recommended that are truly relevant)")
    console.print(f"  Recall           : [cyan]{recall:.1%}[/]  (relevant papers caught)")
    console.print(f"  F1               : [cyan]{f1:.1%}[/]")
    console.print(f"  TP/FP/FN/TN      : {tp}/{fp}/{fn}/{tn}")

    dist_parts = "  ".join(
        f"[{_TRIAGE_COLOR.get(k,'white')}]{k}[/]: {v}"
        for k, v in sorted(dist.items())
    )
    console.print(f"  Triage dist      : {dist_parts}\n")

    return {
        "evaluator": evaluator.name,
        "n": len(valid),
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "distribution": dist,
    }
