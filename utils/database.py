"""
SQLite persistence layer.
Stores every pipeline decision with full audit trail.
Uses stdlib only — no extra dependencies.
"""

import sqlite3
import uuid
from datetime import datetime, timezone
from config.settings import config
from utils.logger import logger


def _connect() -> sqlite3.Connection:
    config.DB_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Create tables and indexes. Safe to call on every startup."""
    with _connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS pipeline_results (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                lead_id           TEXT NOT NULL,
                run_id            TEXT NOT NULL,
                raw_text          TEXT,
                received_at       TEXT,
                category          TEXT,
                confidence        REAL,
                reason            TEXT,
                validation_passed INTEGER,
                fallback_action   TEXT,
                final_decision    TEXT,
                processing_ms     REAL,
                notes             TEXT,
                created_at        TEXT NOT NULL
            )
        """)
        for idx, col in [
            ("idx_lead_id",       "lead_id"),
            ("idx_run_id",        "run_id"),
            ("idx_final_decision","final_decision"),
        ]:
            conn.execute(f"CREATE INDEX IF NOT EXISTS {idx} ON pipeline_results({col})")
    logger.debug("Database initialised")


def save_result(result: dict, run_id: str):
    ai  = result.get("ai_output") or {}
    val = result.get("validation") or {}
    inp = result.get("input") or {}

    with _connect() as conn:
        conn.execute("""
            INSERT INTO pipeline_results
              (lead_id, run_id, raw_text, received_at, category, confidence, reason,
               validation_passed, fallback_action, final_decision, processing_ms, notes, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            inp.get("id"),
            run_id,
            inp.get("raw_text"),
            inp.get("received_at"),
            ai.get("category"),
            ai.get("confidence"),
            ai.get("reason"),
            1 if val.get("valid") else 0,
            result.get("fallback_action"),
            result.get("final_decision"),
            result.get("processing_ms"),
            result.get("notes"),
            datetime.now(timezone.utc).isoformat()
        ))


def get_recent_decisions(limit: int = 20) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute("""
            SELECT lead_id, run_id, category, confidence, final_decision,
                   fallback_action, validation_passed, processing_ms, created_at
            FROM pipeline_results ORDER BY created_at DESC LIMIT ?
        """, (limit,)).fetchall()
    return [dict(r) for r in rows]


def get_lead_history(lead_id: str) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute("""
            SELECT lead_id, run_id, category, confidence, final_decision,
                   fallback_action, validation_passed, notes, created_at
            FROM pipeline_results WHERE lead_id = ? ORDER BY created_at DESC
        """, (lead_id,)).fetchall()
    return [dict(r) for r in rows]


def get_stats() -> dict:
    with _connect() as conn:
        total = conn.execute("SELECT COUNT(*) FROM pipeline_results").fetchone()[0]
        by_decision = conn.execute("""
            SELECT final_decision, COUNT(*) as count
            FROM pipeline_results GROUP BY final_decision
        """).fetchall()
        fallbacks = conn.execute("""
            SELECT COUNT(*) FROM pipeline_results WHERE fallback_action != 'none'
        """).fetchone()[0]
        avg_ms = conn.execute(
            "SELECT AVG(processing_ms) FROM pipeline_results WHERE processing_ms IS NOT NULL"
        ).fetchone()[0]
        runs = conn.execute(
            "SELECT COUNT(DISTINCT run_id) FROM pipeline_results"
        ).fetchone()[0]

    return {
        "total_processed": total,
        "total_runs": runs,
        "decisions": {row["final_decision"]: row["count"] for row in by_decision},
        "fallbacks_triggered": fallbacks,
        "avg_processing_ms": round(avg_ms, 2) if avg_ms else 0,
        "manual_review_rate": round(
            next((r["count"] for r in by_decision if r["final_decision"] == "manual_review"), 0)
            / total * 100, 1
        ) if total else 0
    }


def test_connection() -> bool:
    """Test DB is reachable and readable. Used by health check."""
    try:
        with _connect() as conn:
            conn.execute("SELECT 1")
        return True
    except Exception:
        return False


def generate_run_id() -> str:
    return f"run_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
