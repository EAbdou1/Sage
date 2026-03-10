
# Entry point for the Sage backend.
# Watches Firestore for sessions with status "pending" and triggers
# the SagePipeline for each one in a separate thread.

import logging
import threading
import time
import os
import sys

import firebase_admin
from firebase_admin import credentials, firestore
from dotenv import load_dotenv

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

load_dotenv()

# ---------------------------------------------------------------------------
# Logging setup — shows timestamps + log level
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("sage.listener")

# ---------------------------------------------------------------------------
# Firebase init
# ---------------------------------------------------------------------------

def _init_firebase():
    if not firebase_admin._apps:
        cred_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "./serviceAccount.json")
        cred = credentials.Certificate(cred_path)
        firebase_admin.initialize_app(cred, {
            "storageBucket": os.getenv("FIREBASE_STORAGE_BUCKET")
        })

_init_firebase()
db = firestore.client()

# ---------------------------------------------------------------------------
# ADK Runner setup
# ---------------------------------------------------------------------------

# Import root_agent after firebase is initialized
from agent import sage_pipeline

session_service = InMemorySessionService()
runner = Runner(
    agent=sage_pipeline,
    app_name="sage",
    session_service=session_service
)

# ---------------------------------------------------------------------------
# Session processor — runs in its own thread per session
# ---------------------------------------------------------------------------

def process_session(session_id: str):
    """
    Run the full SagePipeline for a single session.
    Executed in a background thread so the listener never blocks.
    """
    logger.info(f"▶️  Processing session: {session_id}")

    try:
        # Import here to avoid circular import issues
        from tools.firestore_tools import claim_session, update_status, log_event, Status

        # Atomically claim the session — prevents duplicate processing on restart
        claimed = claim_session(session_id)
        if not claimed:
            logger.info(f"Session {session_id} already claimed — skipping")
            return

        log_event(session_id, "🚀 Sage pipeline started")

        # Create an ADK session for this run
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        adk_session = loop.run_until_complete(
            session_service.create_session(
                app_name="sage",
                user_id=session_id,   # use session_id as user_id for simplicity
                state={"session_id": session_id}
            )
        )

        # Run the pipeline — pass the session_id as the message
        message = types.Content(
            role="user",
            parts=[types.Part(text=f"Process session_id: {session_id}")]
        )

        final_response = None
        async def run_pipeline():
            nonlocal final_response
            async for event in runner.run_async(
                user_id=session_id,
                session_id=adk_session.id,
                new_message=message
            ):
                if event.is_final_response():
                    if event.content and event.content.parts:
                        final_response = event.content.parts[0].text

        loop.run_until_complete(run_pipeline())
        loop.close()

        logger.info(f"✅ Session {session_id} complete. Response: {final_response}")

    except Exception as e:
        logger.error(f"❌ Pipeline failed for {session_id}: {e}", exc_info=True)
        try:
            from tools.firestore_tools import update_status, log_event, Status
            update_status(session_id, Status.ERROR, str(e))
            log_event(session_id, f"❌ Pipeline crashed: {str(e)}")
        except Exception:
            pass  # Don't crash the listener over a logging failure


def safe_process(session_id: str):
    """Wrapper that catches any uncaught exception in the thread."""
    try:
        process_session(session_id)
    except Exception as e:
        logger.error(f"Unhandled error in thread for {session_id}: {e}", exc_info=True)


# ---------------------------------------------------------------------------
# Firestore listener — watches for new "pending" sessions
# ---------------------------------------------------------------------------

def on_snapshot(col_snapshot, changes, read_time):
    """
    Called by Firestore whenever the sessions collection changes.
    Spawns a new thread for each new "pending" session.
    """
    for change in changes:
        # Only react to newly ADDED documents or documents that changed to "pending"
        if change.type.name in ("ADDED", "MODIFIED"):
            doc = change.document
            data = doc.to_dict()

            if data.get("status") == "pending":
                session_id = doc.id
                logger.info(f"🆕 New pending session detected: {session_id}")

                # Spawn a background thread — listener never blocks
                thread = threading.Thread(
                    target=safe_process,
                    args=(session_id,),
                    daemon=True  # thread dies if main process exits
                )
                thread.start()


# ---------------------------------------------------------------------------
# Main — start the listener
# ---------------------------------------------------------------------------

def main():
    logger.info("=" * 50)
    logger.info("🌿 Sage backend starting...")
    logger.info(f"   Project: {os.getenv('GOOGLE_CLOUD_PROJECT')}")
    logger.info(f"   Bucket:  {os.getenv('FIREBASE_STORAGE_BUCKET')}")
    logger.info("=" * 50)

    # Attach Firestore listener to the sessions collection
    col_ref = db.collection("sessions")
    col_watch = col_ref.on_snapshot(on_snapshot)

    logger.info("👂 Listening for new sessions... (Ctrl+C to stop)")

    # Keep the main thread alive — listener runs in background
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("\n🛑 Sage backend stopped.")
        col_watch.unsubscribe()
        sys.exit(0)


if __name__ == "__main__":
    main()