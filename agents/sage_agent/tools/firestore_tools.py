# All Firestore read/write operations for Sage.
# Every other tool calls these functions — nothing else touches Firestore directly.

import os
import logging
from datetime import datetime, timezone
from typing import Optional

import firebase_admin
from firebase_admin import credentials, firestore
from dotenv import load_dotenv
from google.cloud.firestore_v1 import Transaction

load_dotenv()

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Firebase initialization (safe to call multiple times)
# ---------------------------------------------------------------------------

def _init_firebase():
    """Initialize Firebase app if not already initialized."""
    if not firebase_admin._apps:
        cred_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "./serviceAccount.json")
        cred = credentials.Certificate(cred_path)
        firebase_admin.initialize_app(cred, {
            "storageBucket": os.getenv("FIREBASE_STORAGE_BUCKET")
        })

_init_firebase()
db = firestore.client()

# ---------------------------------------------------------------------------
# Status constants — single source of truth, used everywhere
# ---------------------------------------------------------------------------

class Status:
    PENDING           = "pending"
    EXTRACTING_PDF    = "extracting_pdf"
    GENERATING_SLIDES = "generating_slides"
    FETCHING_IMAGES   = "fetching_images"
    READY             = "ready"
    ERROR             = "error"

# ---------------------------------------------------------------------------
# Core session operations
# ---------------------------------------------------------------------------

def get_session(session_id: str) -> Optional[dict]:
    """
    Fetch a session document from Firestore by session ID.
    Returns the session data as a dict, or None if not found.
    """
    try:
        doc = db.collection("sessions").document(session_id).get()
        if not doc.exists:
            logger.warning(f"Session {session_id} not found")
            return None
        return {"id": doc.id, **doc.to_dict()}
    except Exception as e:
        logger.error(f"Failed to get session {session_id}: {e}")
        raise


def update_status(session_id: str, status: str, error_message: str = None):
    """
    Update the status field of a session.
    Optionally attach an error message when status is 'error'.
    """
    try:
        data = {
            "status": status,
            "updatedAt": datetime.now(timezone.utc)
        }
        if error_message:
            data["errorMessage"] = error_message

        db.collection("sessions").document(session_id).update(data)
        logger.info(f"Session {session_id} → status: {status}")
    except Exception as e:
        logger.error(f"Failed to update status for {session_id}: {e}")
        raise


def write_slides(session_id: str, deck_title: str, subject: str, slides: list):
    """
    Write the generated slides array to Firestore.
    Also sets deckTitle, subject, and transitions status to fetching_images.
    Called by ContentAgent after Gemini returns the slide JSON.
    """
    try:
        db.collection("sessions").document(session_id).update({
            "deckTitle": deck_title,
            "subject": subject,
            "slides": slides,
            "currentSlide": 0,
            "status": Status.FETCHING_IMAGES,
            "updatedAt": datetime.now(timezone.utc)
        })
        logger.info(f"Session {session_id}: wrote {len(slides)} slides")
    except Exception as e:
        logger.error(f"Failed to write slides for {session_id}: {e}")
        raise


def update_slide_image(session_id: str, slide_id: int, image_url: str,
                       image_alt: str, image_source: str):
    """
    Update a single slide's image fields using Firestore array operations.
    Uses ArrayUnion pattern via direct index update for efficiency.
    Called by ImageAgent for each slide after image is found/generated.
    """
    try:
        session_ref = db.collection("sessions").document(session_id)
        doc = session_ref.get()

        if not doc.exists:
            raise ValueError(f"Session {session_id} not found")

        slides = doc.to_dict().get("slides", [])

        # Find and update the matching slide
        updated = False
        for i, slide in enumerate(slides):
            if slide.get("id") == slide_id:
                slides[i]["imageUrl"] = image_url
                slides[i]["imageAlt"] = image_alt
                slides[i]["imageSource"] = image_source
                updated = True
                break

        if not updated:
            logger.warning(f"Slide {slide_id} not found in session {session_id}")
            return

        session_ref.update({
            "slides": slides,
            "updatedAt": datetime.now(timezone.utc)
        })
        logger.info(f"Session {session_id}: updated image for slide {slide_id} ({image_source})")
    except Exception as e:
        logger.error(f"Failed to update slide image: {e}")
        raise


def update_slide_content(session_id: str, slide_id: int, new_content: str,
                          new_image_url: str = None, new_image_source: str = None):
    """
    Rewrite a slide's content (and optionally its image).
    Called by ExplainerAgent when student says 'I don't understand'.
    Also increments rewriteCount — capped at 3 by ExplainerAgent.
    """
    try:
        session_ref = db.collection("sessions").document(session_id)
        doc = session_ref.get()

        if not doc.exists:
            raise ValueError(f"Session {session_id} not found")

        slides = doc.to_dict().get("slides", [])

        for i, slide in enumerate(slides):
            if slide.get("id") == slide_id:
                slides[i]["content"] = new_content
                slides[i]["rewriteCount"] = slide.get("rewriteCount", 0) + 1

                # Only update image if a new one was generated
                if new_image_url:
                    slides[i]["imageUrl"] = new_image_url
                    slides[i]["imageSource"] = new_image_source or "generated"
                break

        session_ref.update({
            "slides": slides,
            "updatedAt": datetime.now(timezone.utc)
        })
        logger.info(f"Session {session_id}: rewrote slide {slide_id}")
    except Exception as e:
        logger.error(f"Failed to update slide content: {e}")
        raise


def mark_ready(session_id: str):
    """
    Final status transition: marks the session as ready for presentation.
    This fires the frontend onSnapshot → UI transitions to the slide deck view.
    """
    try:
        db.collection("sessions").document(session_id).update({
            "status": Status.READY,
            "updatedAt": datetime.now(timezone.utc)
        })
        logger.info(f"Session {session_id} is READY!")
    except Exception as e:
        logger.error(f"Failed to mark session ready: {e}")
        raise


# ---------------------------------------------------------------------------
# Logging — streams to frontend LoggerPanel via onSnapshot
# ---------------------------------------------------------------------------

def log_event(session_id: str, message: str, source: str = "agent"):
    """
    Append a log entry to the session's logs array.
    The frontend LoggerPanel streams these in real time via onSnapshot.

    source: "agent" | "frontend"
    """
    try:
        session_ref = db.collection("sessions").document(session_id)
        session_ref.update({
            "logs": firestore.ArrayUnion([{
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "source": source,
                "message": message
            }])
        })
    except Exception as e:
        # Log failures are non-fatal — never crash the pipeline over a log entry
        logger.warning(f"Failed to write log event: {e}")


# ---------------------------------------------------------------------------
# Idempotency — atomic session claim (prevents duplicate processing)
# ---------------------------------------------------------------------------

@firestore.transactional
def _claim_session_transaction(transaction: Transaction, session_ref):
    """
    Atomically checks if session is still 'pending' and claims it.
    If another worker already claimed it, returns False.
    This is a Firestore transaction — runs atomically, retries on conflict.
    """
    doc = session_ref.get(transaction=transaction)

    if not doc.exists:
        return False

    if doc.to_dict().get("status") != Status.PENDING:
        return False  # Already claimed by another worker

    transaction.update(session_ref, {
        "status": Status.EXTRACTING_PDF,
        "claimedAt": datetime.now(timezone.utc)
    })
    return True


def claim_session(session_id: str) -> bool:
    """
    Try to atomically claim a pending session for processing.
    Returns True if successfully claimed, False if already taken.

    Always call this before processing — prevents duplicate work on restart.
    """
    try:
        session_ref = db.collection("sessions").document(session_id)
        transaction = db.transaction()
        return _claim_session_transaction(transaction, session_ref)
    except Exception as e:
        logger.error(f"Failed to claim session {session_id}: {e}")
        return False