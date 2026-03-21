"""
Anthropic Message Batches backend — 50% cost vs real-time API.

Submits all unevaluated papers as a single batch, polls until complete,
then returns parsed results. Typical turnaround: 1–15 minutes for
hundreds of papers.

The Batch API has a custom_id limit of 64 chars. We use list index
as the id and maintain a mapping back to paper GUIDs.
"""
import logging
import time

import anthropic

from paperbreakfast.evaluators.base import BackendError, EvaluationResult

logger = logging.getLogger(__name__)

_POLL_INTERVAL = 30       # seconds between status checks
_TIMEOUT       = 7200     # 2 hours max wait
_MAX_BATCH     = 10_000   # Anthropic hard limit per batch


def evaluate_batch(
    api_key: str,
    model: str,
    temperature: float,
    max_tokens: int,
    strategy,                        # EvaluationStrategy — builds prompts + parses
    papers: list,
    interest_profile: str,
) -> tuple[dict, int, int]:          # ({guid: EvaluationResult}, evaluated, errors)
    """
    Submit papers as an Anthropic batch, poll to completion, return results.
    Never raises — errors are captured per-paper and in the summary counts.
    """
    if not api_key:
        raise BackendError("ANTHROPIC_API_KEY is not set.")

    client = anthropic.Anthropic(api_key=api_key)
    evaluator_name = f"claude-batch:{model}"

    # ── Build requests ────────────────────────────────────────────────────────
    # custom_id = str(index) — Anthropic limits to 64 chars, GUIDs can be longer
    index_to_guid: dict[str, str] = {}
    requests = []

    for i, paper in enumerate(papers[:_MAX_BATCH]):
        custom_id = str(i)
        index_to_guid[custom_id] = paper.guid
        sys_prompt, usr_prompt = strategy.build_prompts(paper, interest_profile)
        requests.append({
            "custom_id": custom_id,
            "params": {
                "model": model,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "system": sys_prompt,
                "messages": [{"role": "user", "content": usr_prompt}],
            },
        })

    logger.info(f"Submitting batch of {len(requests)} papers to Anthropic...")

    # ── Submit ────────────────────────────────────────────────────────────────
    try:
        batch = client.messages.batches.create(requests=requests)
    except anthropic.AuthenticationError as e:
        raise BackendError(f"Claude authentication failed: {e}") from e
    except anthropic.APIError as e:
        raise BackendError(f"Batch submission failed: {e}") from e

    batch_id = batch.id
    logger.info(f"Batch submitted — id: {batch_id}  Polling every {_POLL_INTERVAL}s...")

    # ── Poll ──────────────────────────────────────────────────────────────────
    elapsed = 0
    while elapsed < _TIMEOUT:
        time.sleep(_POLL_INTERVAL)
        elapsed += _POLL_INTERVAL

        try:
            batch = client.messages.batches.retrieve(batch_id)
        except Exception as e:
            logger.warning(f"Poll error (will retry): {e}")
            continue

        counts = batch.request_counts
        logger.info(
            f"  [{elapsed}s] status={batch.processing_status}  "
            f"done={counts.succeeded + counts.errored}/"
            f"{len(requests)}  succeeded={counts.succeeded}"
        )

        if batch.processing_status == "ended":
            break
    else:
        raise BackendError(f"Batch {batch_id} did not complete within {_TIMEOUT}s.")

    # ── Collect results ───────────────────────────────────────────────────────
    results: dict[str, EvaluationResult] = {}
    errors = 0

    for item in client.messages.batches.results(batch_id):
        guid = index_to_guid.get(item.custom_id)
        if guid is None:
            continue

        if item.result.type == "succeeded":
            raw = item.result.message.content[0].text
            ev = strategy.parse_response(raw)
            ev.evaluator_name = evaluator_name
            ev.raw_response = raw
            results[guid] = ev
        else:
            # errored / canceled / expired
            logger.warning(f"Batch item {item.custom_id} — {item.result.type}")
            results[guid] = EvaluationResult(
                triage="skip",
                evaluator_name=evaluator_name,
                parse_error=True,
            )
            errors += 1

    evaluated = len(results) - errors
    logger.info(f"Batch complete — {evaluated} evaluated, {errors} errors")
    return results, evaluated, errors
