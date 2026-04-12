"""
core_extraction.py — Arkiveit prediction extraction engine
Uses Grok-4 via xAI API to extract structured predictions from tweets.
"""

import os
import json
from typing import Optional
from pydantic import BaseModel
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

LLM_CLIENT = OpenAI(
    api_key=os.getenv("GROK_API_KEY"),
    base_url="https://api.x.ai/v1"
)

# ---------------------------------------------------------------------------
# Extraction prompt — deliberately strict to avoid false positives
# ---------------------------------------------------------------------------
# The #1 failure mode is extracting non-predictions (opinions, analysis,
# commentary) as predictions. We lose credibility if we track vague claims.
# The prompt is tuned to require specificity.

SYSTEM_PROMPT = """You are Arkiveit's prediction extraction engine. Your job is to identify ONLY genuine, verifiable, forward-looking predictions from social media posts.

STRICT DEFINITION — a prediction MUST have ALL of:
1. A specific, falsifiable claim about a future state of the world
2. A measurable outcome (price level, election winner, event happening/not happening)
3. An implied or explicit timeframe
4. Genuine uncertainty — the outcome must be genuinely unknown at the time of posting, not a scheduled or confirmed event being reported

DO NOT extract:
- General opinions ("I think markets are overvalued")
- Vague directional statements ("stocks will go up eventually")
- Analysis or commentary without a specific future claim
- Warnings or risks without a predicted outcome ("recession risk is rising")
- Historical statements or explanations
- Predictions with no way to verify true/false
- Scheduled events or confirmed plans being reported as news (e.g. "meeting will be held tonight", "vote will take place tomorrow")

TIERS:
- Tier 1: Highly verifiable — specific number, date, named outcome (e.g. "SPX hits 6000 by Dec 2025")
- Tier 2: Moderately verifiable — clear direction + timeframe (e.g. "Fed will cut rates before June")
- Tier 3: Hard to verify — qualitative but time-bound (e.g. "China will escalate Taiwan tensions in 2025")
- Tier 4: Not a prediction — set is_prediction to false

Return ONLY valid JSON, no preamble, no explanation outside the JSON:

{
  "is_prediction": boolean,
  "tier": 1|2|3|4,
  "claim_text": "the exact claim as a clean sentence, or empty string if not a prediction",
  "normalized": {
    "category": "finance|politics|geopolitics|technology|other" or null,
    "asset": "specific asset or entity being predicted about, e.g. SPX, BTC, Joe Biden" or null,
    "metric": "what is being measured, e.g. price, election result, GDP growth" or null,
    "direction": "above|below|equals|wins|loses|happens|does_not_happen" or null,
    "threshold": number or null,
    "deadline": "YYYY-MM-DD" or null,
    "conditions": "any conditions or caveats stated" or null
  },
  "verifiability_score": 0.0-1.0,
  "implied_confidence": "high|medium|low" or null,
  "reasoning": "one sentence explaining why this is or is not a prediction"
}"""


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

class NormalizedPrediction(BaseModel):
    category: Optional[str] = None
    asset: Optional[str] = None
    metric: Optional[str] = None
    direction: Optional[str] = None
    threshold: Optional[float] = None
    deadline: Optional[str] = None
    conditions: Optional[str] = None


class ExtractedPrediction(BaseModel):
    is_prediction: bool
    tier: int
    claim_text: str
    normalized: NormalizedPrediction
    verifiability_score: float
    implied_confidence: Optional[str]
    reasoning: str


# ---------------------------------------------------------------------------
# Main extraction function
# ---------------------------------------------------------------------------

def extract_prediction(post_text: str, context: str = "") -> ExtractedPrediction:
    """
    Extract a structured prediction from a tweet.

    Args:
        post_text: The tweet text to analyse
        context:   Optional additional context (quoted tweet, thread, etc.)

    Returns:
        ExtractedPrediction — always returns something, never raises
    """
    user_content = f"POST: {post_text}"
    if context:
        user_content += f"\n\nCONTEXT: {context}"

    try:
        response = LLM_CLIENT.chat.completions.create(
            model="grok-4",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_content}
            ],
            temperature=0.0,
            response_format={"type": "json_object"},
            timeout=30,
        )

        raw = response.choices[0].message.content
        data = json.loads(raw)

        # Validate tier is int
        if "tier" in data:
            data["tier"] = int(data["tier"])

        return ExtractedPrediction(**data)

    except json.JSONDecodeError as e:
        print(f"⚠️  LLM returned invalid JSON: {e}")
    except Exception as e:
        print(f"⚠️  Extraction error: {e}")

    # Safe fallback — never crash the calling code
    return ExtractedPrediction(
        is_prediction=False,
        tier=4,
        claim_text="",
        normalized=NormalizedPrediction(),
        verifiability_score=0.0,
        implied_confidence=None,
        reasoning="Extraction failed — treated as non-prediction"
    )


# ---------------------------------------------------------------------------
# Reply text composer — lives here so it can be tested independently
# ---------------------------------------------------------------------------

def compose_reply(prediction: ExtractedPrediction, author_username: str, dashboard_url: str) -> str:
    """
    Compose a public reply tweet confirming a prediction has been archived.
    Kept under 280 characters.
    """
    claim = prediction.claim_text
    category = (prediction.normalized.category or "General").capitalize()
    deadline = prediction.normalized.deadline or "unspecified timeframe"

    # Build reply, truncate claim if needed
    max_claim = 120
    if len(claim) > max_claim:
        claim = claim[:max_claim - 1] + "…"

    reply = (
        f"📌 Prediction archived!\n\n"
        f"@{author_username}: {claim}\n"
        f"📅 By: {deadline} | 🏷 {category}\n\n"
        f"Track accuracy: {dashboard_url}"
    )

    # Hard fallback if still over 280
    if len(reply) > 280:
        reply = (
            f"📌 Archived @{author_username}'s prediction.\n"
            f"{claim[:80]}…\n"
            f"Track: {dashboard_url}"
        )

    return reply
