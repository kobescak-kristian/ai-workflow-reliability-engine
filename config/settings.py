"""
Central configuration loader.
Reads from .env file if present, falls back to environment variables,
falls back to safe defaults.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


class Config:
    # ── OpenAI ────────────────────────────────────────────────────────────
    OPENAI_API_KEY: str  = os.getenv("OPENAI_API_KEY", "")
    OPENAI_MODEL: str    = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    # ── Slack ─────────────────────────────────────────────────────────────
    SLACK_WEBHOOK_URL: str = os.getenv("SLACK_WEBHOOK_URL", "")
    SLACK_ENABLED: bool    = os.getenv("SLACK_ENABLED", "false").lower() == "true"

    # ── Email ─────────────────────────────────────────────────────────────
    EMAIL_ENABLED: bool     = os.getenv("EMAIL_ENABLED", "false").lower() == "true"
    EMAIL_SENDER: str       = os.getenv("EMAIL_SENDER", "")
    EMAIL_APP_PASSWORD: str = os.getenv("EMAIL_APP_PASSWORD", "")
    EMAIL_RECIPIENT: str    = os.getenv("EMAIL_RECIPIENT", "")
    EMAIL_SMTP_HOST: str    = os.getenv("EMAIL_SMTP_HOST", "smtp.gmail.com")
    EMAIL_SMTP_PORT: int    = int(os.getenv("EMAIL_SMTP_PORT", "587"))

    # ── Google Sheets ─────────────────────────────────────────────────────
    GOOGLE_SHEETS_ID: str         = os.getenv("GOOGLE_SHEETS_ID", "")
    GOOGLE_CREDENTIALS_FILE: str  = os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json")

    # ── Pipeline ──────────────────────────────────────────────────────────
    CONFIDENCE_THRESHOLD: float = float(os.getenv("CONFIDENCE_THRESHOLD", "0.60"))

    # ── Paths ─────────────────────────────────────────────────────────────
    DB_PATH: Path    = Path(os.getenv("DB_PATH", "data/pipeline.db"))
    ALERTS_PATH: Path = Path(os.getenv("ALERTS_PATH", "data/alerts.json"))

    @classmethod
    def simulation_mode(cls) -> bool:
        return not bool(cls.OPENAI_API_KEY)

    @classmethod
    def sheets_enabled(cls) -> bool:
        return bool(cls.GOOGLE_SHEETS_ID and cls.GOOGLE_CREDENTIALS_FILE)

    @classmethod
    def summary(cls) -> dict:
        return {
            "openai_model":          cls.OPENAI_MODEL,
            "simulation_mode":       cls.simulation_mode(),
            "slack_enabled":         cls.SLACK_ENABLED,
            "email_enabled":         cls.EMAIL_ENABLED,
            "sheets_enabled":        cls.sheets_enabled(),
            "confidence_threshold":  cls.CONFIDENCE_THRESHOLD,
            "db_path":               str(cls.DB_PATH),
        }


config = Config()
