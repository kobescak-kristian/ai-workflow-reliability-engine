from models.schemas import AIOutput, ValidationResult, FallbackAction, InputRecord
from pipeline import ai_processor, validator
from utils.logger import logger

DEFAULT_SAFE_OUTPUT = AIOutput(
    category="unknown",
    confidence=0.0,
    reason="System default — AI output failed validation after retry."
)

MAX_RETRIES = 1


def handle_fallback(
    record: InputRecord,
    validation: ValidationResult,
    attempt: int = 0
) -> tuple[AIOutput, FallbackAction]:

    if attempt < MAX_RETRIES:
        logger.warning(f"[{record.id}] Fallback Stage 1: retrying with strict prompt")
        retried = ai_processor.process_record(record, strict=True)
        retried_val = validator.validate(retried, record.id)

        if retried_val.valid and retried is not None:
            logger.success(f"[{record.id}] Retry succeeded")
            return retried, FallbackAction.RETRY

        logger.warning(f"[{record.id}] Retry failed — assigning safe default")

    logger.warning(f"[{record.id}] Fallback Stage 2: safe default assigned, flagged for manual review")
    return DEFAULT_SAFE_OUTPUT, FallbackAction.MANUAL_REVIEW_FLAGGED
