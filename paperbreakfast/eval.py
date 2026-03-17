"""
Evaluator benchmarking against the ground truth dataset.

Usage:
    python main.py eval
    python main.py eval --gt eval/ground_truth.jsonl

Metrics reported:
    MAE        — mean absolute error between human and model scores
    Precision  — of papers the model recommends, fraction that are truly relevant
    Recall     — of truly relevant papers, fraction the model catches
    F1         — harmonic mean of precision and recall

The ground truth file is a JSONL where each line has:
    id, title, abstract, journal, authors, human_score (0.0–1.0), notes
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
    # Attributes present on DB Paper that strategies may reference
    score: Optional[float] = None
    url: str = ""


@dataclass
class EvalResult:
    paper: EvalPaper
    model_score: Optional[float]
    reasoning: str
    error: Optional[str] = None

    @property
    def diff(self) -> Optional[float]:
        if self.model_score is None:
            return None
        return abs(self.model_score - self.paper.human_score)


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

    console.print(
        f"\n[bold]Evaluator benchmark[/] — {evaluator.name} — {len(papers)} papers\n"
    )

    results: list[EvalResult] = []
    for i, paper in enumerate(papers, 1):
        console.print(f"  [{i:02d}/{len(papers)}] {paper.title[:65]}...", end="\r")
        try:
            outcome = evaluator.evaluate(paper, config.interest_profile)
            results.append(EvalResult(
                paper=paper,
                model_score=outcome.score,
                reasoning=outcome.reasoning,
            ))
        except Exception as exc:
            logger.error(f"Eval failed for {paper.guid}: {exc}")
            results.append(EvalResult(
                paper=paper,
                model_score=None,
                reasoning="",
                error=str(exc),
            ))

    console.print(" " * 80, end="\r")  # clear progress line

    # ── Results table ────────────────────────────────────────────────────────
    t = Table(title=f"Results — {evaluator.name}", show_lines=False)
    t.add_column("ID", style="dim", width=6)
    t.add_column("Title", max_width=38)
    t.add_column("Human", justify="right", width=6)
    t.add_column("Model", justify="right", width=6)
    t.add_column("Diff", justify="right", width=5)
    t.add_column("Reasoning", max_width=38, style="dim")

    for r in results:
        human_str = f"{r.paper.human_score:.2f}"
        if r.model_score is None:
            t.add_row(r.paper.guid, r.paper.title[:38], human_str, "[red]ERR[/]", "-", r.error or "")
            continue

        model_str = f"{r.model_score:.2f}"
        diff_val = r.diff
        diff_str = f"{diff_val:.2f}" if diff_val is not None else "-"
        if diff_val is None:
            diff_color = "white"
        elif diff_val < 0.15:
            diff_color = "green"
        elif diff_val < 0.30:
            diff_color = "yellow"
        else:
            diff_color = "red"

        t.add_row(
            r.paper.guid,
            r.paper.title[:38],
            human_str,
            model_str,
            f"[{diff_color}]{diff_str}[/]",
            r.reasoning[:38] if r.reasoning else "",
        )

    console.print(t)

    # ── Metrics ──────────────────────────────────────────────────────────────
    valid = [r for r in results if r.model_score is not None]
    if not valid:
        console.print("[red]No valid results — cannot compute metrics.[/]")
        return {}

    mae = sum(r.diff for r in valid) / len(valid)  # type: ignore[arg-type]

    threshold = config.evaluator.score_threshold
    tp = sum(1 for r in valid if r.paper.human_score >= threshold and r.model_score >= threshold)
    fp = sum(1 for r in valid if r.paper.human_score < threshold and r.model_score >= threshold)
    fn = sum(1 for r in valid if r.paper.human_score >= threshold and r.model_score < threshold)
    tn = sum(1 for r in valid if r.paper.human_score < threshold and r.model_score < threshold)

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

    console.print(f"\n[bold]Metrics[/] at threshold [cyan]{threshold:.0%}[/]:")
    console.print(f"  Papers evaluated : {len(valid)} / {len(papers)}")
    console.print(f"  MAE              : [cyan]{mae:.3f}[/]  (lower is better)")
    console.print(f"  Precision        : [cyan]{precision:.1%}[/]  (recommended papers that are truly relevant)")
    console.print(f"  Recall           : [cyan]{recall:.1%}[/]  (relevant papers that get recommended)")
    console.print(f"  F1               : [cyan]{f1:.1%}[/]")
    console.print(f"  TP/FP/FN/TN      : {tp}/{fp}/{fn}/{tn}\n")

    return {
        "evaluator": evaluator.name,
        "n": len(valid),
        "mae": mae,
        "precision": precision,
        "recall": recall,
        "f1": f1,
    }
