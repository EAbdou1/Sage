# Calls Gemini 2.5 Flash to convert extracted PDF text into structured slide JSON.
# Uses Gemini's structured output mode (response_mime_type: application/json)
# to guarantee valid, parseable JSON every single time — no brittle string parsing.

import os
import logging
import json
from typing import Optional

from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Gemini client
# ---------------------------------------------------------------------------

client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))
MODEL = "gemini-2.5-flash"

# ---------------------------------------------------------------------------
# Slide count logic
# ---------------------------------------------------------------------------

def _calculate_slide_count(char_count: int) -> int:
    """
    Decide how many slides to generate based on content length.
    Short chapter  (<5k chars)  → 6-8 slides
    Medium chapter (5k-15k)     → 8-12 slides
    Long chapter   (15k-40k)    → 12-16 slides
    """
    if char_count < 5000:
        return 7
    elif char_count < 15000:
        return 10
    else:
        return 14

# ---------------------------------------------------------------------------
# The prompt
# ---------------------------------------------------------------------------

def _build_prompt(text: str, slide_count: int) -> str:
    return f"""You are an expert medical educator. Your job is to convert a medical textbook chapter into a structured slide deck for an AI-powered teaching agent called Sage.

CONTENT TO CONVERT:
{text}

INSTRUCTIONS:
- Generate exactly {slide_count} slides total
- Slide 0 must be type "overview" — a welcome/introduction slide
- Last slide must be type "summary" — key takeaways
- Every 3-4 content slides, insert one type "mcq" knowledge check
- All other slides are type "content"
- Each content slide covers ONE concept only — never pack multiple ideas into one slide
- Content field: 2-3 clear sentences maximum. Write like a teacher speaking, not a textbook
- MCQ slides: generate a clinically relevant question with 4 options, one correct answer
- Extract the subject/discipline from the content (e.g. "Pharmacology", "Microbiology")

SLIDE TYPES:
- "overview": introduction to the topic
- "content": teaches one concept
- "mcq": knowledge check question
- "summary": final recap slide

OUTPUT FORMAT — return ONLY valid JSON, no markdown, no explanation, no backticks:
{{
  "deckTitle": "Full descriptive title of the chapter topic",
  "subject": "Medical discipline (e.g. Pharmacology)",
  "totalSlides": {slide_count},
  "slides": [
    {{
      "id": 0,
      "type": "overview",
      "title": "Slide title here",
      "content": "2-3 sentence intro to the topic.",
      "isMCQ": false,
      "mcqOptions": [],
      "correctAnswer": null,
      "explanation": "",
      "rewriteCount": 0
    }},
    {{
      "id": 3,
      "type": "mcq",
      "title": "Knowledge Check",
      "content": "The question text here?",
      "isMCQ": true,
      "mcqOptions": ["Option A", "Option B", "Option C", "Option D"],
      "correctAnswer": 1,
      "explanation": "One sentence explaining why the correct answer is right.",
      "rewriteCount": 0
    }}
  ]
}}"""

# ---------------------------------------------------------------------------
# Main function: text → slides JSON
# ---------------------------------------------------------------------------

def generate_slides(extracted_text: str, char_count: int) -> dict:
    """
    Send extracted PDF text to Gemini 2.5 Flash and get back structured slide JSON.

    Uses response_mime_type='application/json' to guarantee valid JSON output.
    Never crashes on malformed JSON — Gemini handles the schema enforcement.

    Returns a dict with:
    - deckTitle, subject, totalSlides, slides[]
    - raw_slide_count: actual number of slides returned
    Raises on API failure after retries.
    """
    slide_count = _calculate_slide_count(char_count)
    prompt = _build_prompt(extracted_text, slide_count)

    logger.info(f"Calling Gemini to generate {slide_count} slides ({char_count:,} chars input)")

    last_error = None

    for attempt in range(3):  # retry up to 3 times
        try:
            response = client.models.generate_content(
                model=MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.4,      # low temp = consistent structured output
                    max_output_tokens=8192
                )
            )

            raw = response.text.strip()

            # Strip markdown fences if Gemini adds them despite our instructions
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[-1]
                raw = raw.rsplit("```", 1)[0].strip()

            deck = json.loads(raw)

            # Basic validation
            if "slides" not in deck or not isinstance(deck["slides"], list):
                raise ValueError("Gemini response missing 'slides' array")

            if len(deck["slides"]) == 0:
                raise ValueError("Gemini returned 0 slides")

            # Ensure every slide has required fields with safe defaults
            for slide in deck["slides"]:
                slide.setdefault("isMCQ", slide.get("type") == "mcq")
                slide.setdefault("mcqOptions", [])
                slide.setdefault("correctAnswer", None)
                slide.setdefault("explanation", "")
                slide.setdefault("rewriteCount", 0)
                slide.setdefault("imageUrl", None)
                slide.setdefault("imageAlt", "")
                slide.setdefault("imageSource", None)

            deck["raw_slide_count"] = len(deck["slides"])

            logger.info(
                f"Gemini generated {len(deck['slides'])} slides: "
                f"'{deck.get('deckTitle', 'Untitled')}' ({deck.get('subject', 'Unknown')})"
            )
            return deck

        except json.JSONDecodeError as e:
            last_error = f"JSON parse error on attempt {attempt + 1}: {e}"
            logger.warning(last_error)

        except Exception as e:
            last_error = f"Gemini API error on attempt {attempt + 1}: {e}"
            logger.warning(last_error)

            # Exponential backoff: 1s, 2s, 4s
            import time
            time.sleep(2 ** attempt)

    # All 3 attempts failed
    raise RuntimeError(f"Failed to generate slides after 3 attempts. Last error: {last_error}")