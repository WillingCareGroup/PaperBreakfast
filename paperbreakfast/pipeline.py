"""
Pipeline — orchestrates one full run of the system.

Each stage is independently callable so the scheduler can run them
at different cadences (poll every 2h, digest once daily).
"""
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from paperbreakfast.config import AppConfig
from paperbreakfast.digest.builder import DigestBuilder
from paperbreakfast.digest.mailer import Mailer
from paperbreakfast.evaluators.base import BackendError
from paperbreakfast.evaluators.factory import build_evaluator
from paperbreakfast.evaluators.strategies.relevance_json import SYSTEM_TEMPLATE as _EVAL_SYSTEM_TEMPLATE
from paperbreakfast.feeds.poller import FeedPoller, PollResult
from paperbreakfast.models.db import (
    Paper,
    get_papers_for_digest,
    get_papers_fetched_today,
    get_unevaluated_papers,
)

logger = logging.getLogger(__name__)

# Delay between LLM calls to avoid hammering the API
_EVAL_INTER_CALL_DELAY = 0.4  # seconds


@dataclass
class EvaluationSummary:
    evaluated: int = 0
    errors: int = 0
    error_messages: list = field(default_factory=list)


@dataclass
class DigestResult:
    paper_count: int = 0
    sent: bool = False
    error: str = ""


class Pipeline:

    def __init__(self, config: AppConfig):
        self.config = config
        self._poller = FeedPoller(config.feeds)
        self._evaluator = build_evaluator(config)
        self._builder = DigestBuilder(
            proxy_base_url=config.proxy_base_url,
        )
        self._mailer = Mailer(config.email, config.smtp_password or "")
        logger.info(f"Pipeline ready — evaluator: {self._evaluator.name}")

    # ── Public stages ────────────────────────────────────────────────────────

    def run_poll(self) -> PollResult:
        logger.info("Polling RSS feeds...")
        result = self._poller.poll_all()
        logger.info(
            f"Poll done: {result.total_new} new papers across {result.feeds_polled} feeds"
            + (f" ({len(result.errors)} errors)" if result.errors else "")
        )
        return result

    def run_evaluation(self) -> EvaluationSummary:
        """Evaluate unevaluated papers — dispatch based on config."""
        if self.config.evaluator.use_batch:
            return self._run_batch_evaluation()
        chunk = self.config.evaluator.chunk_size
        if chunk > 1:
            return self._run_chunked_evaluation(chunk)
        return self._run_sequential_evaluation()

    def _run_sequential_evaluation(self) -> EvaluationSummary:
        papers = get_unevaluated_papers()
        if not papers:
            logger.info("No papers to evaluate.")
            return EvaluationSummary()

        logger.info(f"Evaluating {len(papers)} papers with {self._evaluator.name}...")
        summary = EvaluationSummary()

        for paper in papers:
            try:
                result = self._evaluator.evaluate(paper, self.config.interest_profile)
                self._save_evaluation(paper.guid, result)
                summary.evaluated += 1
                if result.parse_error:
                    logger.warning(
                        f"Parse error evaluating '{paper.title[:60]}' — "
                        f"raw: {result.raw_response[:80]!r}"
                    )
                else:
                    flag = "**" if result.triage == "read" else "  "
                    logger.debug(f"{flag} [{result.triage}] {paper.title[:80]}")

                if _EVAL_INTER_CALL_DELAY > 0:
                    time.sleep(_EVAL_INTER_CALL_DELAY)

            except BackendError as exc:
                msg = f"[{paper.journal}] {paper.title[:60]}: {exc}"
                logger.error(f"Backend error on '{paper.title[:60]}': {exc}")
                summary.errors += 1
                summary.error_messages.append(msg)
            except Exception as exc:
                msg = f"[{paper.journal}] {paper.title[:60]}: {exc}"
                logger.error(f"Unexpected error on '{paper.title[:60]}': {exc}")
                summary.errors += 1
                summary.error_messages.append(msg)

        logger.info(
            f"Evaluation done: {summary.evaluated} evaluated, {summary.errors} errors"
        )
        return summary

    def _run_chunked_evaluation(self, chunk_size: int) -> EvaluationSummary:
        """
        Score multiple papers per LLM call — interest profile sent once per chunk.
        chunk_size=25 means ~34 calls for 833 papers vs 833 sequential calls.
        Falls back to individual evaluation for any chunk that fails to parse.
        """
        import json
        import re as _re

        papers = get_unevaluated_papers()
        if not papers:
            logger.info("No papers to evaluate.")
            return EvaluationSummary()

        backend = getattr(self._evaluator, "backend", None)
        if backend is None:
            logger.warning("Chunked evaluation requires a CompositeEvaluator — falling back to sequential.")
            return self._run_sequential_evaluation()

        ev_name = f"{backend.name}/chunked_relevance_json"
        profile = self.config.interest_profile
        summary = EvaluationSummary()

        # v6 prompt — imported from relevance_json.py to avoid duplication.
        # Profile is embedded in the system prompt for prompt caching.
        system_prompt = _EVAL_SYSTEM_TEMPLATE.format(profile=profile)

        chunks = [papers[i:i + chunk_size] for i in range(0, len(papers), chunk_size)]
        logger.info(
            f"Evaluating {len(papers)} papers in {len(chunks)} chunks "
            f"of up to {chunk_size} (evaluator: {ev_name})"
        )

        for chunk_idx, chunk in enumerate(chunks):
            # Build JSON array input matching v6 prompt spec: id / title / abstract
            papers_input = [
                {
                    "id": i + 1,
                    "title": paper.title or "Unknown",
                    "abstract": paper.abstract if paper.abstract else None,
                }
                for i, paper in enumerate(chunk)
            ]
            user_prompt = json.dumps(papers_input)

            try:
                raw = backend.complete(system_prompt, user_prompt)

                # Parse: strip markdown fences, then try direct, then regex fallback
                data = None
                cleaned = _re.sub(r'^```[a-z]*\s*', '', raw.strip(), flags=_re.MULTILINE)
                cleaned = _re.sub(r'```\s*$', '', cleaned.strip())
                try:
                    data = json.loads(cleaned.strip())
                except json.JSONDecodeError:
                    m = _re.search(r'\[.*\]', cleaned, _re.DOTALL)
                    if m:
                        try:
                            data = json.loads(m.group())
                        except json.JSONDecodeError:
                            pass

                if not isinstance(data, list) or len(data) != len(chunk):
                    raise ValueError(
                        f"Expected array of {len(chunk)}, got "
                        f"{'non-array' if not isinstance(data, list) else len(data)}"
                    )

                for paper, item in zip(chunk, data):
                    from paperbreakfast.evaluators.base import EvaluationResult
                    raw_triage = str(item.get("triage", "skip")).lower().strip()
                    triage = raw_triage if raw_triage in ("read", "skim", "horizon", "skip") else "skip"
                    milestone = bool(item.get("milestone", False))
                    raw_summary = item.get("summary")
                    item_summary = raw_summary if isinstance(raw_summary, dict) else None

                    result = EvaluationResult(
                        triage=triage,
                        milestone=milestone,
                        summary=item_summary,
                        evaluator_name=ev_name,
                        raw_response=raw,
                    )
                    self._save_evaluation(paper.guid, result)
                    summary.evaluated += 1
                    flag = "**" if triage == "read" else "  "
                    logger.debug(f"{flag} [{triage}] {paper.title[:80]}")

                logger.info(
                    f"  Chunk {chunk_idx + 1}/{len(chunks)} — "
                    f"{len(chunk)} papers scored"
                )

            except Exception as exc:
                logger.warning(
                    f"Chunk {chunk_idx + 1} parse/API error ({exc}) — "
                    f"falling back to individual calls for {len(chunk)} papers"
                )
                # Per-paper fallback for failed chunk
                for paper in chunk:
                    try:
                        result = self._evaluator.evaluate(paper, profile)
                        self._save_evaluation(paper.guid, result)
                        summary.evaluated += 1
                        if _EVAL_INTER_CALL_DELAY > 0:
                            time.sleep(_EVAL_INTER_CALL_DELAY)
                    except BackendError as e:
                        msg = f"[{paper.journal}] {paper.title[:60]}: {e}"
                        logger.error(msg)
                        summary.errors += 1
                        summary.error_messages.append(msg)
                    except Exception as e:
                        msg = f"[{paper.journal}] {paper.title[:60]}: {e}"
                        logger.error(f"Unexpected error on '{paper.title[:60]}': {e}")
                        summary.errors += 1
                        summary.error_messages.append(msg)

        logger.info(f"Chunked evaluation done: {summary.evaluated} evaluated, {summary.errors} errors")
        return summary

    def _run_batch_evaluation(self) -> EvaluationSummary:
        papers = get_unevaluated_papers()
        if not papers:
            logger.info("No papers to evaluate.")
            return EvaluationSummary()

        from paperbreakfast.evaluators.backends.claude_batch import evaluate_batch
        ev_cfg = self.config.evaluator

        # strategy is needed to build prompts and parse responses
        strategy = getattr(self._evaluator, "strategy", None)
        if strategy is None:
            logger.error("Batch evaluation requires a CompositeEvaluator — falling back to sequential.")
            return self._run_sequential_evaluation()

        try:
            results, evaluated, errors = evaluate_batch(
                api_key=self.config.anthropic_api_key or "",
                model=ev_cfg.backend.model,
                temperature=ev_cfg.backend.temperature,
                max_tokens=ev_cfg.backend.max_tokens,
                strategy=strategy,
                papers=papers,
                interest_profile=self.config.interest_profile,
            )
        except BackendError as exc:
            logger.error(f"Batch evaluation failed: {exc}")
            return EvaluationSummary(errors=len(papers), error_messages=[str(exc)])

        summary = EvaluationSummary()
        for guid, result in results.items():
            self._save_evaluation(guid, result)
            if result.parse_error:
                summary.errors += 1
                summary.error_messages.append(f"Parse error for guid {guid[:40]}")
            else:
                summary.evaluated += 1

        logger.info(
            f"Batch evaluation done: {summary.evaluated} evaluated, {summary.errors} errors"
        )
        return summary

    def _save_evaluation(self, guid: str, result) -> None:
        """Persist an EvaluationResult to the DB. Called by both eval paths."""
        import json as _json
        Paper.update(
            triage=result.triage,
            milestone=result.milestone,
            summary=_json.dumps(result.summary) if result.summary else None,
            evaluator_name=result.evaluator_name,
            evaluator_model=getattr(self.config.evaluator.backend, "model", None),
            evaluated_at=datetime.utcnow(),
        ).where(Paper.guid == guid).execute()

    def run_enrichment(self) -> int:
        """
        Enrich scored papers with PI/institution from Crossref + PubMed.
        Only runs on papers above threshold that have a DOI and are missing institution.
        """
        from paperbreakfast.enrichment.enricher import enrich_paper

        papers = list(
            Paper.select().where(
                (Paper.triage.in_(["read", "skim", "horizon"]))
                & (Paper.doi.is_null(False))
                & (Paper.institution.is_null())
            )
        )

        if not papers:
            logger.debug("No papers need enrichment.")
            return 0

        logger.info(f"Enriching {len(papers)} papers via Crossref/PubMed...")
        enriched = 0

        for paper in papers:
            pi_name, institution = enrich_paper(paper.doi)
            if pi_name or institution:
                update = {}
                if pi_name and not paper.pi_name:
                    update["pi_name"] = pi_name
                if institution:
                    update["institution"] = institution
                if update:
                    Paper.update(update).where(Paper.guid == paper.guid).execute()
                    enriched += 1
                    logger.debug(
                        f"  Enriched: {paper.title[:60]} → {pi_name} / {institution}"
                    )
            time.sleep(0.2)  # be polite to public APIs

        logger.info(f"Enrichment done: {enriched}/{len(papers)} papers enriched")
        return enriched

    def run_digest(
        self,
        poll_result: "PollResult | None" = None,
        eval_summary: "EvaluationSummary | None" = None,
    ) -> DigestResult:
        since = datetime.utcnow() - timedelta(days=1)
        papers = get_papers_for_digest(since)
        total_today = get_papers_fetched_today()

        if not papers and not (
            (poll_result and poll_result.errors)
            or (eval_summary and eval_summary.errors)
        ):
            logger.info("No new recommended papers for digest.")
            return DigestResult(paper_count=0, sent=False)

        logger.info(f"Building digest with {len(papers)} papers...")
        payload = self._builder.build(
            papers,
            poll_result=poll_result,
            eval_summary=eval_summary,
            total_papers_today=total_today,
            feeds_configured=len(self.config.feeds),
        )
        sent = self._mailer.send(payload)

        if sent:
            (
                Paper.update(
                    included_in_digest=True,
                    digest_sent_at=datetime.utcnow(),
                )
                .where(Paper.guid.in_([p.guid for p in papers]))
                .execute()
            )

        return DigestResult(paper_count=len(papers), sent=sent)

    def run_full(self):
        """Convenience: poll + evaluate + enrich + digest in sequence."""
        poll = self.run_poll()
        ev = self.run_evaluation()
        self.run_enrichment()
        digest = self.run_digest(poll_result=poll, eval_summary=ev)
        return poll, ev, digest
