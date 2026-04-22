"""
FastAPI wrapper — AI Workflow Reliability Engine v2.0

Endpoints:
  POST /qualify                      — Single lead, full pipeline
  POST /qualify/batch                — Up to 50 leads, shared run_id
  GET  /health                       — Health check (DB + config)
  GET  /stats                        — Aggregate pipeline metrics
  GET  /audit                        — Recent decisions from DB
  GET  /audit/{lead_id}              — Full history for a specific lead
  GET  /alerts                       — Pending manual review alerts
  PATCH /alerts/{lead_id}/acknowledge — Mark alert as acknowledged

Run: uvicorn api:app --reload --port 8000
"""

import time
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel
from typing import Optional

from models.schemas import InputRecord, FallbackAction, FinalDecision
from pipeline import ai_processor, validator, fallback, router
from config.settings import config
from utils.logger import logger
from utils.database import (
    init_db, save_result, get_recent_decisions,
    get_lead_history, get_stats, test_connection, generate_run_id
)
from utils.notifier import (
    notify_manual_review, get_pending_alerts,
    get_all_alerts, acknowledge_alert
)

init_db()

app = FastAPI(
    title="AI Workflow Reliability Engine",
    description="Production-style validation, fallback and routing layer for AI-classified leads.",
    version="2.0.0"
)


# ── Request / Response models ─────────────────────────────────────────────

class LeadRequest(BaseModel):
    id: str
    raw_text: str
    metadata: Optional[dict] = None

    model_config = {
        "json_schema_extra": {
            "example": {
                "id": "lead_demo_01",
                "raw_text": "CFO confirmed 40k EUR budget. CTO and procurement involved. Go-live in 8 weeks.",
                "metadata": {"source": "web_form", "region": "EU"}
            }
        }
    }


class LeadResponse(BaseModel):
    id: str
    category: str
    confidence: float
    reason: str
    validation_passed: bool
    fallback_action: str
    final_decision: str
    notes: Optional[str]
    processing_ms: float


class BatchRequest(BaseModel):
    leads: list[LeadRequest]


class BatchResponse(BaseModel):
    total: int
    processed: int
    failed: int
    run_id: str
    results: list[LeadResponse]
    failed_ids: list[str]
    summary: dict


# ── Core processing ───────────────────────────────────────────────────────

def process_lead(lead: LeadRequest, run_id: str) -> LeadResponse:
    t_start = time.time()

    record = InputRecord(id=lead.id, raw_text=lead.raw_text, metadata=lead.metadata)

    ai_output        = ai_processor.process_record(record)
    validation_result = validator.validate(ai_output, record.id)

    fallback_action = FallbackAction.NONE
    if not validation_result.valid:
        ai_output, fallback_action = fallback.handle_fallback(record, validation_result)
        validation_result = validator.validate(ai_output, record.id)

    final_decision = router.route(ai_output, fallback_action, record.id)
    processing_ms  = round((time.time() - t_start) * 1000, 2)

    notes = None
    if fallback_action == FallbackAction.MANUAL_REVIEW_FLAGGED:
        notes = f"Fallback triggered. Errors: {'; '.join(validation_result.errors)}"
    elif fallback_action == FallbackAction.RETRY:
        notes = "Retry succeeded after initial validation failure."

    result_dict = {
        "input": {"id": record.id, "raw_text": record.raw_text,
                  "metadata": record.metadata, "received_at": record.received_at},
        "ai_output": {
            "category":   ai_output.category   if ai_output else "unknown",
            "confidence": ai_output.confidence if ai_output else 0.0,
            "reason":     ai_output.reason     if ai_output else "No output"
        },
        "validation":     {"valid": validation_result.valid, "errors": validation_result.errors},
        "fallback_action": fallback_action.value,
        "final_decision":  final_decision.value,
        "notes":           notes,
        "processing_ms":   processing_ms
    }

    save_result(result_dict, run_id)

    if final_decision == FinalDecision.MANUAL_REVIEW:
        reason = "Validation failed after retry" if fallback_action == FallbackAction.MANUAL_REVIEW_FLAGGED \
            else f"category={result_dict['ai_output']['category']}, confidence={result_dict['ai_output']['confidence']:.2f}"
        notify_manual_review(
            lead_id=record.id,
            reason=reason,
            fallback_action=fallback_action.value,
            run_id=run_id,
            validation_errors=validation_result.errors if not validation_result.valid else []
        )

    return LeadResponse(
        id=record.id,
        category=result_dict["ai_output"]["category"],
        confidence=result_dict["ai_output"]["confidence"],
        reason=result_dict["ai_output"]["reason"],
        validation_passed=validation_result.valid,
        fallback_action=fallback_action.value,
        final_decision=final_decision.value,
        notes=notes,
        processing_ms=processing_ms
    )


# ── Endpoints ─────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    """Health check — tests DB connection and returns config state."""
    db_ok = test_connection()
    return {
        "status": "ok" if db_ok else "degraded",
        "database": "connected" if db_ok else "unreachable",
        "simulation_mode": config.simulation_mode(),
        "slack_enabled": config.SLACK_ENABLED,
        "email_enabled": config.EMAIL_ENABLED,
        "confidence_threshold": config.CONFIDENCE_THRESHOLD,
        "version": "2.0.0"
    }


@app.post("/qualify", response_model=LeadResponse)
def qualify_lead(lead: LeadRequest):
    """Process a single lead through the full pipeline."""
    try:
        run_id = generate_run_id()
        logger.info(f"API /qualify — {lead.id} (run={run_id})")
        result = process_lead(lead, run_id)
        logger.success(f"API /qualify — {lead.id} → {result.final_decision}")
        return result
    except Exception as e:
        logger.error(f"API /qualify error for {lead.id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/qualify/batch", response_model=BatchResponse)
def qualify_batch(batch: BatchRequest):
    """
    Process a batch of leads under a shared run_id.
    Returns per-record results plus which records failed and why.
    """
    if not batch.leads:
        raise HTTPException(status_code=400, detail="Batch cannot be empty.")
    if len(batch.leads) > 50:
        raise HTTPException(status_code=400, detail="Batch limit is 50 leads per request.")

    run_id = generate_run_id()
    logger.info(f"API /qualify/batch — {len(batch.leads)} leads (run={run_id})")

    results    = []
    failed_ids = []

    for lead in batch.leads:
        try:
            results.append(process_lead(lead, run_id))
        except Exception as e:
            logger.error(f"Batch error — {lead.id}: {e}")
            failed_ids.append(lead.id)

    decisions = {}
    fallbacks = 0
    for r in results:
        decisions[r.final_decision] = decisions.get(r.final_decision, 0) + 1
        if r.fallback_action != "none":
            fallbacks += 1

    summary = {
        "decisions":        decisions,
        "fallbacks":        fallbacks,
        "errors":           len(failed_ids),
        "avg_processing_ms": round(
            sum(r.processing_ms for r in results) / len(results), 2
        ) if results else 0
    }

    logger.success(f"API /qualify/batch — {len(results)} processed, {len(failed_ids)} failed (run={run_id})")

    return BatchResponse(
        total=len(batch.leads),
        processed=len(results),
        failed=len(failed_ids),
        run_id=run_id,
        results=results,
        failed_ids=failed_ids,
        summary=summary
    )


@app.get("/stats")
def stats():
    """Aggregate pipeline metrics across all runs."""
    return get_stats()


@app.get("/audit")
def audit_recent(limit: int = Query(default=20, le=100)):
    """Return the most recent pipeline decisions from the database."""
    records = get_recent_decisions(limit=limit)
    return {"count": len(records), "records": records}


@app.get("/audit/{lead_id}")
def audit_lead(lead_id: str):
    """Full decision history for a specific lead across all runs."""
    history = get_lead_history(lead_id)
    if not history:
        raise HTTPException(status_code=404, detail=f"No records found for: {lead_id}")
    return {"lead_id": lead_id, "total_runs": len(history), "history": history}


@app.get("/alerts")
def get_alerts(status: str = Query(default="pending", pattern="^(pending|all)$")):
    """
    Return manual review alerts.
    ?status=pending (default) — unacknowledged only
    ?status=all               — full alert history
    """
    alerts = get_pending_alerts() if status == "pending" else get_all_alerts()
    return {"count": len(alerts), "status_filter": status, "alerts": alerts}


@app.patch("/alerts/{lead_id}/acknowledge")
def ack_alert(lead_id: str):
    """Mark the most recent pending alert for a lead as acknowledged."""
    updated = acknowledge_alert(lead_id)
    if not updated:
        raise HTTPException(status_code=404, detail=f"No pending alert found for: {lead_id}")
    return {"acknowledged": True, "lead_id": lead_id}
