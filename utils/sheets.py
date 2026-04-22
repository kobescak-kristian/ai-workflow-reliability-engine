"""
Google Sheets integration — 4-tab operational model.

Tabs:
  1. Action Queue   — live CRM working list, newest on top
  2. Sales History  — append-only, send_to_sales decisions
  3. Review History — append-only, manual_review decisions
  4. Archive        — append-only, archive decisions

Action Queue rules:
  - New leads inserted at row 2 (newest always on top)
  - Repeat leads: new row inserted at top, marked YES, old row untouched
  - Pipeline writes: all AI fields, Status=new, Decision, Date Added
  - Pipeline NEVER touches: Assigned To, Notes, Last Updated
"""

import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime, timezone
from pathlib import Path

from config.settings import config
from utils.logger import logger

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

# Status map — pipeline sets initial value, rep updates
DECISION_LABEL = {
    "send_to_sales": "call",
    "manual_review": "review",
    "archive":       "reject"
}


def _get_client():
    creds_path = Path(config.GOOGLE_CREDENTIALS_FILE)
    if not creds_path.exists():
        creds_path = Path.cwd() / config.GOOGLE_CREDENTIALS_FILE
    creds = Credentials.from_service_account_file(str(creds_path), scopes=SCOPES)
    return gspread.authorize(creds)


def _get_spreadsheet():
    return _get_client().open_by_key(config.GOOGLE_SHEETS_ID)


def ensure_tabs():
    """Verify all four tabs exist. Log result. Does not overwrite existing data."""
    try:
        ss = _get_spreadsheet()
        existing = [ws.title for ws in ss.worksheets()]
        needed = ["Action Queue", "Sales History", "Review History", "Archive"]
        for tab in needed:
            if tab not in existing:
                logger.warning(f"Tab '{tab}' not found in sheet — please create it manually with correct headers")
            else:
                logger.debug(f"Tab verified: {tab}")
        logger.success("Google Sheets tabs verified")
    except Exception as e:
        logger.error(f"Could not verify tabs: {e}")


def _get_lead_rows(ws, lead_id: str) -> list[int]:
    """Return all row numbers where lead_id appears in column A."""
    values = ws.col_values(1)
    return [i+1 for i, v in enumerate(values) if v == lead_id]


def write_to_action_queue(result: dict, run_id: str, alert_reason: str = ""):
    """
    Insert lead at row 2 (newest on top).
    Marks as repeat if lead ID already exists in the queue.
    Never touches Assigned To, Notes, Last Updated columns.
    """
    try:
        ss  = _get_spreadsheet()
        ws  = ss.worksheet("Action Queue")

        inp      = result.get("input") or {}
        ai       = result.get("ai_output") or {}
        meta     = inp.get("metadata") or {}
        decision = result.get("final_decision", "")
        now      = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

        existing_rows = _get_lead_rows(ws, inp.get("id", ""))
        is_repeat     = len(existing_rows) > 0

        row = [
            inp.get("id", ""),                      # Lead ID
            now,                                     # Date Added
            "new",                                   # Status
            DECISION_LABEL.get(decision, "review"),  # Decision
            ai.get("category", ""),                  # Category
            ai.get("confidence", ""),                # Confidence
            ai.get("reason", ""),                    # Reason
            alert_reason,                            # Alert Reason
            meta.get("region", ""),                  # Region
            meta.get("source", ""),                  # Source
            meta.get("company_size", ""),            # Company Size
            "YES" if is_repeat else "NO",            # Repeat Lead
            run_id,                                  # Run ID
            "",                                      # Assigned To (rep fills)
            "",                                      # Notes (rep fills)
            ""                                       # Last Updated (rep fills)
        ]

        # Insert at row 2 — pushes everything down, header stays at row 1
        ws.insert_row(row, index=2, value_input_option="USER_ENTERED")

        if is_repeat:
            logger.info(f"[{inp.get('id')}] Action Queue — repeat lead inserted at top")
        else:
            logger.success(f"[{inp.get('id')}] Action Queue → {DECISION_LABEL.get(decision, 'review')}")

    except Exception as e:
        logger.error(f"Action Queue write failed for {result.get('input', {}).get('id')}: {e}")


def append_to_history(result: dict, run_id: str, alert_reason: str = ""):
    """
    Append to the correct history tab based on final decision.
    Always appends — never modifies existing rows.
    """
    decision = result.get("final_decision", "")
    inp  = result.get("input") or {}
    ai   = result.get("ai_output") or {}
    meta = inp.get("metadata") or {}
    now  = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    ts   = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    try:
        ss = _get_spreadsheet()

        if decision == "send_to_sales":
            ws  = ss.worksheet("Sales History")
            row = [
                inp.get("id", ""),
                now,
                inp.get("raw_text", "")[:200],
                ai.get("category", ""),
                ai.get("confidence", ""),
                ai.get("reason", ""),
                meta.get("region", ""),
                meta.get("source", ""),
                meta.get("company_size", ""),
                run_id,
                ts
            ]

        elif decision == "manual_review":
            ws  = ss.worksheet("Review History")
            row = [
                inp.get("id", ""),
                now,
                inp.get("raw_text", "")[:200],
                ai.get("category", ""),
                ai.get("confidence", ""),
                ai.get("reason", ""),
                alert_reason,
                result.get("fallback_action", ""),
                meta.get("region", ""),
                meta.get("source", ""),
                meta.get("company_size", ""),
                run_id,
                ts
            ]

        elif decision == "archive":
            ws  = ss.worksheet("Archive")
            row = [
                inp.get("id", ""),
                now,
                inp.get("raw_text", "")[:200],
                ai.get("category", ""),
                ai.get("confidence", ""),
                ai.get("reason", ""),
                meta.get("region", ""),
                meta.get("source", ""),
                meta.get("company_size", ""),
                run_id,
                ts
            ]
        else:
            return

        ws.append_row(row, value_input_option="USER_ENTERED")
        logger.debug(f"[{inp.get('id')}] History → {decision}")

    except Exception as e:
        logger.error(f"History append failed for {inp.get('id')}: {e}")


def write_result(result: dict, run_id: str, alert_reason: str = ""):
    """
    Single entry point from main pipeline.
    Writes to Action Queue + appropriate history tab.
    """
    write_to_action_queue(result, run_id, alert_reason)
    append_to_history(result, run_id, alert_reason)
