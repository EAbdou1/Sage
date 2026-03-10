# Pipeline:
#   SagePipeline (SequentialAgent)
#     ├── ContentAgent  → PDF → slide text
#     └── ImageAgent    → image per slide
#
# ExplainerAgent runs separately, triggered by SageAgent during voice sessions.

import asyncio
import logging
import os

from google.adk.agents import LlmAgent, SequentialAgent
from google.genai import types
from dotenv import load_dotenv

from tools.firestore_tools import (
    get_session,
    update_status,
    write_slides,
    update_slide_image,
    update_slide_content,
    mark_ready,
    log_event,
    Status,
)
from tools.pdf_tools import download_and_extract
from tools.slide_tools import generate_slides
from tools.image_tools import fetch_images_for_all_slides

load_dotenv()
logger = logging.getLogger(__name__)

MODEL = "gemini-2.5-flash"

# ---------------------------------------------------------------------------
# Tool functions — plain Python functions the agents can call
# Each has a clear docstring because that's what the LLM reads to understand
# what the tool does and when to call it.
# ---------------------------------------------------------------------------

def process_pdf_to_slides(session_id: str) -> dict:
    """
    Download the PDF for this session, extract its text, and generate
    a structured slide deck using Gemini. Writes the slides to Firestore.
    Returns a summary of what was generated.
    """
    try:
        log_event(session_id, "📄 Starting PDF extraction...")
        update_status(session_id, Status.EXTRACTING_PDF)

        # Get the session to find the PDF URL
        session = get_session(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")

        pdf_url = session.get("pdfUrl")
        if not pdf_url:
            raise ValueError(f"Session {session_id} has no pdfUrl")

        # Download + extract text
        extracted = download_and_extract(pdf_url)

        if extracted.get("warning"):
            log_event(session_id, f"⚠️ {extracted['warning']}")

        log_event(
            session_id,
            f"✅ Extracted {extracted['char_count']:,} characters "
            f"from {extracted['pages_processed']} pages"
        )

        # Generate slides with Gemini
        update_status(session_id, Status.GENERATING_SLIDES)
        log_event(session_id, "🧠 Generating slide structure with Gemini...")

        deck = generate_slides(extracted["text"], extracted["char_count"])

        # Write slides to Firestore (status → fetching_images)
        write_slides(
            session_id=session_id,
            deck_title=deck["deckTitle"],
            subject=deck["subject"],
            slides=deck["slides"]
        )

        log_event(
            session_id,
            f"✅ Generated {deck['raw_slide_count']} slides: \"{deck['deckTitle']}\""
        )

        return {
            "success": True,
            "session_id": session_id,
            "deck_title": deck["deckTitle"],
            "subject": deck["subject"],
            "slide_count": deck["raw_slide_count"],
            "slides": deck["slides"]
        }

    except Exception as e:
        error_msg = str(e)
        logger.error(f"ContentAgent failed for {session_id}: {error_msg}")
        log_event(session_id, f"❌ PDF processing failed: {error_msg}")
        update_status(session_id, Status.ERROR, error_msg)
        return {"success": False, "error": error_msg, "session_id": session_id}


def process_images_for_session(session_id: str) -> dict:
    """
    Fetch or generate images for all slides in this session.
    Runs all image fetches in parallel for speed.
    Updates each slide in Firestore as images are found.
    Marks the session as ready when complete.
    """
    try:
        log_event(session_id, "🖼️ Starting image fetching...")
        update_status(session_id, Status.FETCHING_IMAGES)

        # Get current session state (slides were written by ContentAgent)
        session = get_session(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")

        slides = session.get("slides", [])
        subject = session.get("subject", "Medicine")

        if not slides:
            raise ValueError("No slides found — ContentAgent may have failed")

        content_slides = [s for s in slides if s.get("type") not in {"mcq", "summary"}]
        log_event(
            session_id,
            f"🔍 Finding images for {len(content_slides)} slides "
            f"(skipping MCQ + summary slides)..."
        )

        # Run all image fetches in parallel
        updated_slides = asyncio.run(
            fetch_images_for_all_slides(session_id, slides, subject)
        )

        # Write each slide's image back to Firestore
        images_found = 0
        for slide in updated_slides:
            if slide.get("imageUrl"):
                update_slide_image(
                    session_id=session_id,
                    slide_id=slide["id"],
                    image_url=slide["imageUrl"],
                    image_alt=slide["imageAlt"],
                    image_source=slide["imageSource"]
                )
                images_found += 1

        log_event(
            session_id,
            f"✅ Images complete: {images_found}/{len(content_slides)} slides have images"
        )

        # 🎉 Final step — fires frontend onSnapshot → UI shows the deck
        mark_ready(session_id)
        log_event(session_id, "🎉 Sage is ready! Your lecture deck is live.")

        return {
            "success": True,
            "session_id": session_id,
            "images_found": images_found,
            "total_slides": len(slides)
        }

    except Exception as e:
        error_msg = str(e)
        logger.error(f"ImageAgent failed for {session_id}: {error_msg}")
        log_event(session_id, f"❌ Image fetching failed: {error_msg}")
        # Don't set ERROR status here — slides exist, just no images
        # Mark ready anyway so the frontend still shows the deck
        mark_ready(session_id)
        return {"success": False, "error": error_msg, "session_id": session_id}


def rewrite_slide(session_id: str, slide_id: int, reason: str = "student did not understand") -> dict:
    """
    Rewrite a slide's content with a simpler explanation.
    If the slide's image was AI-generated, regenerate it too.
    Called by ExplainerAgent during voice sessions when student says they don't understand.
    Returns the updated slide content.
    """
    try:
        session = get_session(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")

        slides = session.get("slides", [])
        slide = next((s for s in slides if s["id"] == slide_id), None)

        if not slide:
            raise ValueError(f"Slide {slide_id} not found in session {session_id}")

        # Enforce rewrite limit
        rewrite_count = slide.get("rewriteCount", 0)
        if rewrite_count >= 3:
            return {
                "success": False,
                "message": "This slide has been rewritten 3 times. Let's move on.",
                "at_limit": True
            }

        subject = session.get("subject", "Medicine")
        log_event(session_id, f"🔄 Rewriting slide {slide_id}: \"{slide['title']}\"...")

        # Ask Gemini to rewrite with a different approach
        from tools.slide_tools import client, MODEL as SLIDE_MODEL
        from google.genai import types as gtypes

        rewrite_prompt = f"""A medical student did not understand this slide. 
Rewrite the content using a completely different explanation approach.

Slide title: {slide['title']}
Original content: {slide['content']}
Subject: {subject}
Reason student is confused: {reason}
This is rewrite attempt #{rewrite_count + 1} of 3.

Rules:
- Use simpler language and a fresh analogy or clinical example
- Keep it 2-3 sentences maximum  
- Make it clearer than the original
- Return ONLY the new content text, nothing else"""

        response = client.models.generate_content(
            model=SLIDE_MODEL,
            contents=rewrite_prompt,
            config=gtypes.GenerateContentConfig(temperature=0.7, max_output_tokens=300)
        )
        new_content = response.text.strip()

        # Regenerate image only if original was AI-generated
        new_image_url = None
        new_image_source = None

        if slide.get("imageSource") == "generated":
            log_event(session_id, f"🖼️ Regenerating image for rewritten slide...")
            from tools.image_tools import _generate_with_imagen, _upload_to_firebase
            image_bytes = asyncio.run(
                _generate_with_imagen(slide["title"], new_content, subject)
            )
            if image_bytes:
                new_image_url = _upload_to_firebase(
                    image_bytes, session_id, slide_id, "image/png"
                )
                new_image_source = "generated"

        # Write updated content to Firestore
        update_slide_content(
            session_id=session_id,
            slide_id=slide_id,
            new_content=new_content,
            new_image_url=new_image_url,
            new_image_source=new_image_source
        )

        log_event(session_id, f"✅ Slide {slide_id} rewritten (attempt {rewrite_count + 1}/3)")

        return {
            "success": True,
            "slide_id": slide_id,
            "new_content": new_content,
            "image_regenerated": new_image_url is not None,
            "rewrite_count": rewrite_count + 1
        }

    except Exception as e:
        error_msg = str(e)
        logger.error(f"ExplainerAgent failed: {error_msg}")
        log_event(session_id, f"❌ Slide rewrite failed: {error_msg}")
        return {"success": False, "error": error_msg}


# ---------------------------------------------------------------------------
# ADK Agent definitions
# ---------------------------------------------------------------------------

# ContentAgent — PDF extraction + slide generation
content_agent = LlmAgent(
    name="ContentAgent",
    model=MODEL,
    description="Downloads a PDF from Firebase Storage, extracts its text, and generates a structured slide deck using Gemini. Call this first with the session_id.",
    instruction="""You are ContentAgent, the first step in the Sage teaching pipeline.

Your one job: call process_pdf_to_slides with the session_id you receive.

- Call the tool immediately — do not ask questions
- If it returns success=True, report the deck title and slide count
- If it returns success=False, report the error clearly
- Do not modify or interpret the slides — just process and report""",
    tools=[process_pdf_to_slides]
)

# ImageAgent — parallel image fetching for all slides
image_agent = LlmAgent(
    name="ImageAgent",
    model=MODEL,
    description="Fetches or generates images for all slides in a session. Runs after ContentAgent. Call with the same session_id.",
    instruction="""You are ImageAgent, the second step in the Sage teaching pipeline.

Your one job: call process_images_for_session with the session_id you receive.

- Call the tool immediately — do not ask questions
- If ContentAgent reported success=False, still attempt image fetching
- Report how many images were found out of total slides
- When done, the session will be marked ready and the frontend will update automatically""",
    tools=[process_images_for_session]
)

# ExplainerAgent — rewrites slides during voice sessions
explainer_agent = LlmAgent(
    name="ExplainerAgent",
    model=MODEL,
    description="Rewrites a slide with a simpler explanation when a student says they don't understand. Regenerates the image if it was AI-generated.",
    instruction="""You are ExplainerAgent, activated during live teaching sessions.

Your job: when a student doesn't understand a slide, call rewrite_slide with:
- session_id: the current session
- slide_id: the slide they're confused about  
- reason: what specifically confused them (from their words)

After rewriting:
- If at_limit=True: tell the student "I've explained this a few different ways. Let's move on and revisit it later."
- If success=True: read the new_content naturally to the student, don't mention it was rewritten
- If image_regenerated=True: mention "I've also updated the visual for you" """,
    tools=[rewrite_slide]
)

# SagePipeline — runs ContentAgent then ImageAgent sequentially
# This is what listener.py triggers for each new session
sage_pipeline = SequentialAgent(
    name="SagePipeline",
    description="Full pipeline: processes a PDF into a complete slide deck with images. Takes a session_id and runs ContentAgent then ImageAgent in order.",
    agents=[content_agent, image_agent]
)

# Root agent — exposed to ADK (required for adk web / adk run)
root_agent = sage_pipeline