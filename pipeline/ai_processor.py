"""
AI Processor.
Calls OpenAI API to classify leads. Falls back to simulation mode if no API key.

Simulation mode covers all 51 records with realistic responses,
including deliberate failures to demonstrate the validation layer.
"""

import json
from models.schemas import AIOutput, InputRecord
from config.settings import config
from utils.logger import logger
from utils.sanitiser import sanitise

SYSTEM_PROMPT = """You are a lead qualification engine for a B2B SaaS company.

Analyse the lead text and return ONLY a valid JSON object with exactly these fields:
{
  "category": "high_value" | "low_value" | "unknown",
  "confidence": <float between 0.0 and 1.0>,
  "reason": "<one sentence explanation, max 20 words>"
}

Rules:
- high_value: clear business need, budget signals, decision-maker involvement, urgency
- low_value: student, vague, no budget, no urgency, general curiosity, no company
- unknown: ambiguous, insufficient info, gibberish, or cannot determine intent

Return ONLY the JSON object. No markdown. No explanation. No extra text."""

STRICT_SYSTEM_PROMPT = """You are a lead qualification engine. Return ONLY valid JSON.

Exact structure required — no other output:
{"category": "high_value" or "low_value" or "unknown", "confidence": 0.0 to 1.0, "reason": "one sentence max 20 words"}"""

# ── Simulation responses ──────────────────────────────────────────────────

SIMULATED = {
    # Clean high value
    "lead_001": {"category":"high_value","confidence":0.95,"reason":"Enterprise demo with confirmed 50k EUR annual budget and C-suite attendance."},
    "lead_002": {"category":"high_value","confidence":0.97,"reason":"200-staff logistics company, urgent 6-week go-live, direct CTO outreach."},
    "lead_003": {"category":"high_value","confidence":0.98,"reason":"Fortune 500 with active RFP, legal and procurement engaged, 120k EUR budget."},
    "lead_004": {"category":"high_value","confidence":0.91,"reason":"Existing paying client expanding contract, proven ROI, clear upgrade scope."},
    "lead_005": {"category":"high_value","confidence":0.89,"reason":"Healthcare group, COO decision maker, compliance team involved, 12 clinics."},
    "lead_006": {"category":"high_value","confidence":0.88,"reason":"Series B startup, 15M EUR raised, CTO-led initiative, Q2 budget approved."},
    "lead_007": {"category":"high_value","confidence":0.87,"reason":"Global manufacturer shortlisted us, VP Operations meeting scheduled."},
    "lead_008": {"category":"high_value","confidence":0.94,"reason":"PE firm with partner sign-off, immediate start, 80k EUR budget confirmed."},
    "lead_009": {"category":"high_value","confidence":0.92,"reason":"Regional bank with compliance sign-off and 40k EUR pilot budget approved."},
    "lead_010": {"category":"high_value","confidence":0.90,"reason":"E-commerce at 10k orders/day, technical team ready, clear integration need."},
    "lead_011": {"category":"high_value","confidence":0.86,"reason":"Insurance company actively switching from competitor, 30-day decision timeline."},
    "lead_012": {"category":"high_value","confidence":0.88,"reason":"Telecoms operator with mapped integration points and confirmed 25k EUR pilot."},
    "lead_013": {"category":"high_value","confidence":0.83,"reason":"200-lawyer firm, managing partner involved, RFP issued, 3-month timeline."},
    "lead_014": {"category":"high_value","confidence":0.91,"reason":"Well-funded logistics startup with board mandate for automation, CEO contact."},
    "lead_015": {"category":"high_value","confidence":0.96,"reason":"Pharma company, CIO and compliance officer on call, six-figure budget approved."},

    # Clean low value
    "lead_016": {"category":"low_value","confidence":0.93,"reason":"Student dissertation research, no commercial intent or business context."},
    "lead_017": {"category":"low_value","confidence":0.88,"reason":"Anonymous pricing query, no contact info, no company, no stated need."},
    "lead_018": {"category":"low_value","confidence":0.85,"reason":"3-person startup, sub-500 EUR budget, no timeline, no defined use case."},
    "lead_019": {"category":"low_value","confidence":0.90,"reason":"Solo freelancer, no company, no team, no budget, not the target customer."},
    "lead_020": {"category":"low_value","confidence":0.87,"reason":"Blog visitor asking definitional questions, no purchase signal."},
    "lead_021": {"category":"low_value","confidence":0.95,"reason":"High school teacher, not a business inquiry, no commercial context."},
    "lead_022": {"category":"low_value","confidence":0.92,"reason":"Retired individual exploring tech, no business context or budget."},
    "lead_023": {"category":"low_value","confidence":0.89,"reason":"Asking only about free tier, no company, no use case, not a buyer."},
    "lead_024": {"category":"low_value","confidence":0.82,"reason":"NGO volunteer, no decision maker, no budget, exploratory only."},
    "lead_025": {"category":"low_value","confidence":0.86,"reason":"Intern doing competitive research, no purchasing authority."},

    # Ambiguous / unknown
    "lead_026": {"category":"unknown","confidence":0.45,"reason":"Real decision maker but budget frozen until Q3, unclear conversion timeline."},
    "lead_027": {"category":"unknown","confidence":0.40,"reason":"Partner reseller inquiry, indirect revenue potential, no end-user budget."},
    "lead_028": {"category":"unknown","confidence":0.30,"reason":"Technical questions with no business need stated, possible competitor research."},
    "lead_029": {"category":"unknown","confidence":0.25,"reason":"Press inquiry for editorial purposes, no purchase intent."},
    "lead_030": {"category":"unknown","confidence":0.42,"reason":"Consultant won't disclose client, budget and timeline completely unknown."},

    # High value but low confidence — triggers manual review via threshold
    "lead_031": {"category":"high_value","confidence":0.52,"reason":"Mid-size company manager interested but vague on budget and timeline."},
    "lead_032": {"category":"high_value","confidence":0.55,"reason":"500-employee company IT contact, unclear if they have purchasing authority."},
    "lead_033": {"category":"high_value","confidence":0.48,"reason":"Operations director expressed interest but engagement has gone cold."},
    "lead_034": {"category":"high_value","confidence":0.57,"reason":"Enterprise demo booked but minimal use case info, unclear contact seniority."},
    "lead_035": {"category":"high_value","confidence":0.53,"reason":"Senior title at large retailer but personal email and slow follow-up."},

    # Gibberish — unknown
    "lead_036": {"category":"unknown","confidence":0.05,"reason":"Input is gibberish with no discernible business intent or meaning."},

    # Borderline confidence
    "lead_043": {"category":"high_value","confidence":0.60,"reason":"Genuine need and budget signals present but decision maker not confirmed."},
    "lead_044": {"category":"high_value","confidence":0.62,"reason":"Clear use case and budget but no urgency and no executive sponsor."},
    "lead_045": {"category":"high_value","confidence":0.58,"reason":"Good technical fit but budget approval still pending."},

    # Repeat lead — both submissions
    "lead_046": {"category":"high_value","confidence":0.94,"reason":"CFO with board approval and confirmed 60k-75k EUR budget, ready to start."},

    # Long input — truncated but still high value
    "lead_047": {"category":"high_value","confidence":0.99,"reason":"Global 25k-employee enterprise, 2.5M EUR budget, CIO/CFO sponsors, RFP shortlist."},

    # HTML injection — sanitised to plain text, then classified
    "lead_048": {"category":"high_value","confidence":0.72,"reason":"Company interested in enterprise plan with budget available after sanitisation."},

    # German language
    "lead_049": {"category":"high_value","confidence":0.84,"reason":"German consultancy, 150 staff, budget confirmed, CEO is decision maker."},

    # Too short
    "lead_050": {"category":"unknown","confidence":0.05,"reason":"Single word greeting, no business context or intent detectable."},
}

# ── Deliberate failures for validation demo ───────────────────────────────
# These override the above for specific leads

FORCED_FAILURES = {
    "lead_037": {
        "bad_category":            {"category":"maybe_value","confidence":0.78,"reason":"Small startup with limited budget."},
        "confidence_out_of_range": {"category":"low_value","confidence":1.85,"reason":"Small startup exploring options."},
        "empty_reason":            {"category":"low_value","confidence":0.78,"reason":""},
    },
    "lead_038": {
        "bad_category":            {"category":"medium_value","confidence":0.65,"reason":"Mid-size company, reasonable budget."},
        "confidence_out_of_range": {"category":"high_value","confidence":-0.3,"reason":"Mid-size company with some urgency."},
        "empty_reason":            {"category":"high_value","confidence":0.65,"reason":""},
    },
    "lead_039": {
        "bad_category":            {"category":"","confidence":0.90,"reason":"Enterprise client with confirmed budget."},
        "confidence_out_of_range": {"category":"high_value","confidence":2.0,"reason":"Enterprise client, urgent timeline."},
        "empty_reason":            {"category":"high_value","confidence":0.90,"reason":""},
    },
}


def call_openai(record: InputRecord, clean_text: str, strict: bool = False) -> dict | None:
    if not config.OPENAI_API_KEY:
        logger.debug(f"Simulation mode for {record.id}")
        return _simulate(record)

    try:
        import openai
        client = openai.OpenAI(api_key=config.OPENAI_API_KEY)
        system = STRICT_SYSTEM_PROMPT if strict else SYSTEM_PROMPT

        response = client.chat.completions.create(
            model=config.OPENAI_MODEL,
            messages=[
                {"role":"system","content":system},
                {"role":"user","content":f"Classify this lead:\n\n{clean_text}"}
            ],
            temperature=0.1,
            max_tokens=150
        )
        raw = response.choices[0].message.content.strip()
        logger.debug(f"OpenAI response for {record.id}: {raw}")
        return json.loads(raw)

    except json.JSONDecodeError as e:
        logger.error(f"Non-JSON response for {record.id}: {e}")
        return None
    except Exception as e:
        logger.error(f"OpenAI call failed for {record.id}: {e}")
        return None


def process_record(record: InputRecord, strict: bool = False) -> AIOutput | None:
    # Sanitise first
    clean = sanitise(record.raw_text, record.id)
    if clean is None:
        logger.warning(f"[{record.id}] Input rejected by sanitiser")
        return None

    raw = call_openai(record, clean, strict=strict)
    if raw is None:
        return None

    try:
        return AIOutput(**raw)
    except Exception as e:
        logger.error(f"Could not parse AI output for {record.id}: {e}")
        return None


def _simulate(record: InputRecord) -> dict | None:
    meta = record.metadata or {}
    force = meta.get("_force_invalid")

    if force and record.id in FORCED_FAILURES:
        result = FORCED_FAILURES[record.id].get(force)
        if result:
            logger.debug(f"Forcing invalid response for {record.id}: {force}")
            return result

    return SIMULATED.get(record.id)
