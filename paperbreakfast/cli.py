"""
Command-line interface.

Commands:
  run      Start the scheduler daemon (poll + evaluate + digest on schedule)
  fetch    Run one poll + evaluate cycle immediately
  digest   Send digest immediately (of whatever is already scored in DB)
  status   Show database statistics
  feeds    List configured feeds
"""
import argparse
import logging
import sys

from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table

console = Console()


def _setup_logging(verbose: bool = False):
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(rich_tracebacks=True, show_path=False)],
    )


def _load(config_path: str, feeds_path: str):
    from paperbreakfast.config import load_config
    from paperbreakfast.models.db import init_db

    config = load_config(config_path, feeds_path)
    init_db(config.db_path)
    return config


# ── Commands ──────────────────────────────────────────────────────────────────

def cmd_run(args, config):
    from paperbreakfast.scheduler import Scheduler
    console.print("[bold green]Starting PaperBreakfast scheduler...[/]")
    console.print(
        f"  Polling every [cyan]{config.scheduler.poll_interval_hours}h[/], "
        f"digest at [cyan]{config.email.send_hour:02d}:00 UTC[/]\n"
        f"  Evaluator: [cyan]{_evaluator_name(config)}[/]\n"
        "  Press Ctrl+C to stop."
    )
    Scheduler(config).start()


def cmd_fetch(args, config):
    from paperbreakfast.pipeline import Pipeline
    console.print("[bold]Running fetch + evaluate cycle...[/]")
    p = Pipeline(config)
    poll = p.run_poll()
    console.print(
        f"  Polled [green]{poll.feeds_ok}/{poll.feeds_total}[/] feeds OK — "
        f"[green]{poll.total_new}[/] new papers"
    )
    for err in poll.errors:
        console.print(f"  [red]Feed error:[/] {err}")

    ev = p.run_evaluation()
    console.print(
        f"  Evaluated [green]{ev.evaluated}[/] papers"
        + (f", [red]{ev.errors} errors[/]" if ev.errors else "")
    )

    enriched = p.run_enrichment()
    if enriched:
        console.print(f"  Enriched [green]{enriched}[/] papers with PI/institution")


def cmd_digest(args, config):
    from paperbreakfast.pipeline import Pipeline
    console.print("[bold]Sending digest now...[/]")
    result = Pipeline(config).run_digest()
    if result.sent:
        console.print(f"  [green]Sent[/] — {result.paper_count} papers")
    elif result.paper_count == 0:
        console.print("  [yellow]Nothing to send[/] — no new recommended papers")
    else:
        console.print(f"  [red]Send failed[/] — check logs. Papers: {result.paper_count}")


def cmd_run_once(args, config):
    from paperbreakfast.pipeline import Pipeline
    console.print("[bold]Running full pipeline (fetch + evaluate + enrich + digest)...[/]")
    p = Pipeline(config)
    poll, ev, digest = p.run_full()
    console.print(
        f"  Poll: [green]{poll.feeds_ok}/{poll.feeds_total}[/] feeds OK — "
        f"[green]{poll.total_new}[/] new papers"
    )
    for err in poll.errors:
        console.print(f"  [red]Feed error:[/] {err}")
    console.print(
        f"  Eval: [green]{ev.evaluated}[/] papers"
        + (f", [red]{ev.errors} errors[/]" if ev.errors else "")
    )
    if digest.sent:
        console.print(f"  Digest: [green]Sent[/] — {digest.paper_count} papers")
    elif digest.paper_count == 0:
        console.print("  Digest: [yellow]Nothing to send[/]")
    else:
        console.print(f"  Digest: [red]Send failed[/] — {digest.paper_count} papers")


def cmd_status(args, config):
    from paperbreakfast.models.db import DigestRun, Paper

    total = Paper.select().count()
    evaluated = Paper.select().where(Paper.triage.is_null(False)).count()
    read_count   = Paper.select().where(Paper.triage == "read").count()
    skim_count   = Paper.select().where(Paper.triage == "skim").count()
    horizon_count = Paper.select().where(Paper.triage == "horizon").count()
    recommended_unsent = (
        Paper.select()
        .where(
            Paper.triage.in_(["read", "skim", "horizon"]),
            Paper.included_in_digest == False,  # noqa: E712
        )
        .count()
    )
    sent = Paper.select().where(Paper.included_in_digest == True).count()  # noqa: E712
    digests = DigestRun.select().count()

    t = Table(title="PaperBreakfast Status", show_header=True)
    t.add_column("Metric", style="cyan")
    t.add_column("Value", style="green", justify="right")
    t.add_row("Total papers in DB", str(total))
    t.add_row("Evaluated", str(evaluated))
    t.add_row("Pending evaluation", str(total - evaluated))
    t.add_row("  — read", str(read_count))
    t.add_row("  — skim", str(skim_count))
    t.add_row("  — horizon", str(horizon_count))
    t.add_row("Recommended (read/skim/horizon), unsent", str(recommended_unsent))
    t.add_row("Sent in past digests", str(sent))
    t.add_row("Digest runs recorded", str(digests))
    t.add_row("Active evaluator", _evaluator_name(config))
    console.print(t)


def cmd_feeds(args, config):
    t = Table(title="Configured Feeds")
    t.add_column("Name", style="cyan")
    t.add_column("Group")
    t.add_column("On", justify="center")
    t.add_column("URL", style="dim")
    for feed in config.feeds:
        t.add_row(feed.name, feed.group, "[green]Y[/]" if feed.enabled else "[red]N[/]", feed.url)
    console.print(t)


def cmd_eval(args, config):
    from paperbreakfast.eval import run_eval
    gt_path = getattr(args, "gt", "eval/ground_truth.jsonl")
    run_eval(config, gt_path=gt_path)


def cmd_feedback(args, config):
    from paperbreakfast.models.db import Paper

    VALID = {"good", "noise", "missed"}

    if args.guid is None:
        # Show recent evaluated papers awaiting feedback
        limit = getattr(args, "limit", 20)
        papers = (
            Paper.select()
            .where(Paper.triage.is_null(False))
            .order_by(Paper.evaluated_at.desc())
            .limit(limit)
        )
        t = Table(title=f"Recent evaluated papers (latest {limit})")
        t.add_column("Triage", width=8)
        t.add_column("Feedback", width=8)
        t.add_column("Journal", width=20)
        t.add_column("Title", max_width=50)
        t.add_column("GUID", style="dim", max_width=20)
        for p in papers:
            fb = p.user_feedback or "-"
            fb_color = {"good": "green", "noise": "red", "missed": "yellow"}.get(fb, "dim")
            triage_color = {
                "read": "green", "skim": "yellow",
                "horizon": "magenta", "skip": "dim",
            }.get(p.triage or "", "dim")
            t.add_row(
                f"[{triage_color}]{p.triage or '-'}[/]",
                f"[{fb_color}]{fb}[/]",
                p.journal,
                p.title[:50],
                p.guid[-20:],
            )
        console.print(t)
        console.print(
            "\nUsage: [cyan]paperbreakfast feedback <guid> good|noise|missed[/]"
        )
        return

    # Record feedback for a specific paper
    guid_fragment = args.guid
    feedback_value = args.value
    if feedback_value is None:
        console.print("[red]Missing value. Use: good | noise | missed[/]")
        return

    if feedback_value not in VALID:
        console.print(f"[red]Invalid feedback value '{feedback_value}'. Use: {VALID}[/]")
        return

    # Allow partial GUID match (last N chars)
    matches = list(Paper.select().where(Paper.guid.contains(guid_fragment)))
    if not matches:
        console.print(f"[red]No paper found matching GUID fragment: {guid_fragment}[/]")
        return
    if len(matches) > 1:
        console.print(f"[yellow]Ambiguous GUID — {len(matches)} matches. Be more specific.[/]")
        for m in matches[:5]:
            console.print(f"  {m.guid[-30:]}  {m.title[:50]}")
        return

    paper = matches[0]
    Paper.update(user_feedback=feedback_value).where(Paper.guid == paper.guid).execute()
    console.print(
        f"[green]Recorded[/] [bold]{feedback_value}[/] for: {paper.title[:70]}"
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _evaluator_name(config) -> str:
    ev = config.evaluator
    return f"{ev.backend.type} / {ev.strategy.type}"


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        prog="paperbreakfast",
        description="Scientific paper curation via RSS + LLM",
    )
    parser.add_argument("--config", default="config.yaml", metavar="FILE")
    parser.add_argument("--feeds", default="feeds.yaml", metavar="FILE")
    parser.add_argument("--verbose", "-v", action="store_true")

    sub = parser.add_subparsers(dest="command", metavar="COMMAND")
    sub.add_parser("run", help="Start the scheduler daemon")
    sub.add_parser("fetch", help="Run one fetch + evaluate cycle now")
    sub.add_parser("digest", help="Send digest now")
    sub.add_parser("run-once", help="Run full pipeline once (fetch + evaluate + enrich + digest)")
    sub.add_parser("status", help="Show database statistics")
    sub.add_parser("feeds", help="List configured feeds")

    p_eval = sub.add_parser("eval", help="Benchmark evaluator against ground truth")
    p_eval.add_argument("--gt", default="eval/ground_truth.jsonl", metavar="FILE",
                        help="Ground truth JSONL file")

    p_feedback = sub.add_parser(
        "feedback",
        help="Record or view paper relevance feedback",
        description=(
            "Without arguments: list recent papers.\n"
            "With <guid> <value>: record feedback.\n"
            "Values: good | noise | missed"
        ),
    )
    p_feedback.add_argument("guid", nargs="?", default=None, help="GUID fragment")
    p_feedback.add_argument(
        "value", nargs="?", default=None, choices=["good", "noise", "missed"]
    )
    p_feedback.add_argument("--limit", type=int, default=20, help="Rows to show in list mode")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    _setup_logging(args.verbose)

    try:
        config = _load(args.config, args.feeds)
    except FileNotFoundError as exc:
        console.print(f"[red]Config error:[/] {exc}")
        sys.exit(1)
    except Exception as exc:
        console.print(f"[red]Startup error:[/] {exc}")
        sys.exit(1)

    {
        "run": cmd_run,
        "fetch": cmd_fetch,
        "digest": cmd_digest,
        "run-once": cmd_run_once,
        "status": cmd_status,
        "feeds": cmd_feeds,
        "eval": cmd_eval,
        "feedback": cmd_feedback,
    }[args.command](args, config)


if __name__ == "__main__":
    main()
