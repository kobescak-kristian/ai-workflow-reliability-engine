"""
AI Workflow Reliability Engine — v2.0
======================================
Pipeline: Input → Sanitise → AI → Validate → Fallback → Route → Notify → Sheets → Persist → Output
"""

import json
import time
import argparse
from pathlib import Path

from pipeline.input_handler import load_inputs
from pipeline import ai_processor, validator, fallback, router
from models.schemas import PipelineResult, FallbackAction, FinalDecision
from config.settings import config
from utils.logger import logger
from utils.database import init_db, save_result, generate_run_id
from utils.notifier import notify_manual_review
from utils.sheets import write_result, ensure_tabs


def run_pipeline(input_path: str, output_path: str | None = None) -> list[dict]:
    logger.section("AI WORKFLOW RELIABILITY ENGINE v2.0 — START")

    for k, v in config.summary().items():
        logger.info(f"  {k}: {v}")

    init_db()
    run_id = generate_run_id()
    logger.info(f"Run ID: {run_id}")

    # Ensure all four Google Sheets tabs exist
    if config.sheets_enabled():
        ensure_tabs()

    records = load_inputs(input_path)
    results = []

    for record in records:
        logger.section(f"Processing: {record.id}")
        t_start = time.time()

        ai_output         = ai_processor.process_record(record)
        validation_result = validator.validate(ai_output, record.id)

        fallback_action = FallbackAction.NONE
        if not validation_result.valid:
            logger.warning(f"[{record.id}] Validation failed — triggering fallback")
            ai_output, fallback_action = fallback.handle_fallback(record, validation_result)
            validation_result = validator.validate(ai_output, record.id)

        final_decision = router.route(ai_output, fallback_action, record.id)
        processing_ms  = round((time.time() - t_start) * 1000, 2)
        notes          = _build_notes(fallback_action, validation_result)
        alert_reason   = _alert_reason(fallback_action, validation_result, ai_output)

        result = PipelineResult(
            input=record,
            ai_output=ai_output,
            validation=validation_result,
            fallback_action=fallback_action,
            final_decision=final_decision,
            notes=notes,
            processing_ms=processing_ms
        )

        result_dict = result.model_dump()
        results.append(result_dict)

        # Persist to DB
        save_result(result_dict, run_id)

        # Notify if manual review
        if final_decision == FinalDecision.MANUAL_REVIEW:
            notify_manual_review(
                lead_id=record.id,
                reason=alert_reason,
                fallback_action=fallback_action.value,
                run_id=run_id,
                validation_errors=validation_result.errors if not validation_result.valid else []
            )

        # Write to Google Sheets (all decisions, all tabs)
        if config.sheets_enabled():
            write_result(result_dict, run_id, alert_reason)

        logger.info(
            f"[{record.id}] Done — {final_decision.value} | "
            f"fallback: {fallback_action.value} | {processing_ms}ms"
        )

    _print_summary(results, run_id)

    if output_path:
        _write_output(results, output_path)

    return results


def _build_notes(fallback_action, validation) -> str | None:
    if fallback_action == FallbackAction.MANUAL_REVIEW_FLAGGED:
        return f"Fallback triggered. Errors: {'; '.join(validation.errors)}"
    if fallback_action == FallbackAction.RETRY:
        return "Retry succeeded after initial validation failure."
    return None


def _alert_reason(fallback_action, validation_result, ai_output) -> str:
    if fallback_action == FallbackAction.MANUAL_REVIEW_FLAGGED:
        return "Validation failed after retry — safe default assigned"
    if ai_output and ai_output.category == "unknown":
        return f"AI classified as unknown (confidence={ai_output.confidence:.2f})"
    if ai_output and ai_output.confidence < config.CONFIDENCE_THRESHOLD:
        return f"High-value lead below confidence threshold ({ai_output.confidence:.2f} < {config.CONFIDENCE_THRESHOLD})"
    return ""


def _print_summary(results: list[dict], run_id: str):
    logger.section("PIPELINE SUMMARY")
    decisions = {}
    fallbacks = 0
    alerts    = 0
    total_ms  = 0

    for r in results:
        d = r["final_decision"]
        decisions[d] = decisions.get(d, 0) + 1
        if r["fallback_action"] != "none":
            fallbacks += 1
        if d == "manual_review":
            alerts += 1
        if r.get("processing_ms"):
            total_ms += r["processing_ms"]

    avg_ms = round(total_ms / len(results), 2) if results else 0

    logger.info(f"Run ID          : {run_id}")
    logger.info(f"Total records   : {len(results)}")
    for decision, count in sorted(decisions.items()):
        logger.info(f"  {decision}: {count}")
    logger.warning(f"Fallbacks       : {fallbacks}")
    logger.warning(f"Alerts sent     : {alerts}")
    logger.info(f"Avg time        : {avg_ms}ms per record")
    logger.success(f"Persisted       → {config.DB_PATH}")
    logger.success(f"Alerts queue    → {config.ALERTS_PATH}")
    logger.success(f"Sheets updated  → all 4 tabs")


def _write_output(results: list[dict], output_path: str):
    path = Path(output_path)
    path.parent.mkdir(exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, default=str)
    logger.success(f"Results written → {output_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AI Workflow Reliability Engine")
    parser.add_argument("--input",  default="data/sample_input.json")
    parser.add_argument("--output", default="data/results.json")
    args = parser.parse_args()
    run_pipeline(args.input, args.output)
