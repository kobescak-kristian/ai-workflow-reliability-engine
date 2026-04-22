from models.schemas import AIOutput, ValidationResult
from utils.logger import logger

ALLOWED_CATEGORIES = {"high_value", "low_value", "unknown"}


def validate(ai_output: AIOutput | None, record_id: str) -> ValidationResult:
    errors = []

    if ai_output is None:
        logger.warning(f"[{record_id}] Validation failed: no AI output")
        return ValidationResult(valid=False, errors=["AI returned no output"])

    if not ai_output.category:
        errors.append("Missing field: category")
    elif ai_output.category not in ALLOWED_CATEGORIES:
        errors.append(f"Invalid category '{ai_output.category}' — must be one of {ALLOWED_CATEGORIES}")

    try:
        conf = float(ai_output.confidence)
        if not (0.0 <= conf <= 1.0):
            errors.append(f"Confidence out of range: {conf} — must be 0.0–1.0")
    except (TypeError, ValueError):
        errors.append(f"Confidence not numeric: '{ai_output.confidence}'")

    if not ai_output.reason or not str(ai_output.reason).strip():
        errors.append("Missing or empty field: reason")

    if errors:
        for e in errors:
            logger.warning(f"[{record_id}] Validation error: {e}")
        return ValidationResult(valid=False, errors=errors)

    logger.success(f"[{record_id}] Validation passed")
    return ValidationResult(valid=True, errors=[])
