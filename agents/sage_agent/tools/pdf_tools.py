# Handles everything PDF-related:
# 1. Download the PDF from Firebase Storage to a local temp file
# 2. Extract all readable text using PyMuPDF
# 3. Validate the content is usable before sending to Gemini

import os
import logging
import tempfile

import fitz  # PyMuPDF
import firebase_admin
from firebase_admin import storage, credentials
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_PAGES = 30       # Never process more than 30 pages
MAX_CHARS = 40000    # Safe limit for Gemini 2.5 Flash context window
MIN_CHARS = 200      # If less than this, PDF is probably image-only (scanned)

# ---------------------------------------------------------------------------
# Firebase initialization (safe to call multiple times)
# ---------------------------------------------------------------------------

def _init_firebase():
    if not firebase_admin._apps:
        cred_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "./serviceAccount.json")
        cred = credentials.Certificate(cred_path)
        firebase_admin.initialize_app(cred, {
            "storageBucket": os.getenv("FIREBASE_STORAGE_BUCKET")
        })

_init_firebase()

# ---------------------------------------------------------------------------
# Download PDF from Firebase Storage
# ---------------------------------------------------------------------------

def download_pdf(pdf_url: str) -> str:
    """
    Download a PDF from Firebase Storage to a local temp file.

    pdf_url: the Firebase Storage path stored in Firestore, e.g.
             "sessions/abc123/chapter.pdf"
             OR a full gs:// URL like "gs://bucket/sessions/abc123/chapter.pdf"

    Returns the local file path of the downloaded PDF.
    Raises an exception if download fails.
    """
    try:
        # Strip gs://bucket-name/ prefix if present — we just need the blob path
        bucket_name = os.getenv("FIREBASE_STORAGE_BUCKET")
        if pdf_url.startswith("gs://"):
            # "gs://sage-ai-1bd20.firebasestorage.app/sessions/abc/file.pdf"
            # → "sessions/abc/file.pdf"
            prefix = f"gs://{bucket_name}/"
            blob_path = pdf_url.replace(prefix, "")
        else:
            blob_path = pdf_url

        logger.info(f"Downloading PDF from: {blob_path}")

        bucket = storage.bucket()
        blob = bucket.blob(blob_path)

        if not blob.exists():
            raise FileNotFoundError(f"PDF not found in Firebase Storage: {blob_path}")

        # Write to a temp file — automatically cleaned up when we're done
        suffix = ".pdf"
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        blob.download_to_filename(tmp.name)

        logger.info(f"PDF downloaded to temp file: {tmp.name}")
        return tmp.name

    except Exception as e:
        logger.error(f"Failed to download PDF: {e}")
        raise


# ---------------------------------------------------------------------------
# Extract text from PDF
# ---------------------------------------------------------------------------

def extract_text(pdf_path: str) -> dict:
    """
    Extract all readable text from a PDF file using PyMuPDF.

    Returns a dict with:
    - text: the extracted text string (truncated if too long)
    - page_count: total pages in the PDF
    - pages_processed: how many pages we actually read
    - was_truncated: True if we hit the MAX_CHARS limit
    - warning: optional warning message (e.g. scanned PDF detected)

    Raises ValueError if the PDF has no extractable text (scanned/image-only).
    """
    doc = None
    try:
        doc = fitz.open(pdf_path)
        total_pages = len(doc)
        pages_to_read = min(total_pages, MAX_PAGES)

        logger.info(f"PDF has {total_pages} pages — processing first {pages_to_read}")

        full_text = []
        char_count = 0
        was_truncated = False

        for page_num in range(pages_to_read):
            page = doc[page_num]
            page_text = page.get_text("text")  # "text" mode = plain text, no formatting

            # Check if adding this page would exceed our limit
            if char_count + len(page_text) > MAX_CHARS:
                # Add as much of this page as fits
                remaining = MAX_CHARS - char_count
                full_text.append(page_text[:remaining])
                was_truncated = True
                logger.warning(f"Text truncated at page {page_num + 1} ({MAX_CHARS} char limit)")
                break

            full_text.append(page_text)
            char_count += len(page_text)

        combined_text = "\n\n".join(full_text).strip()

        # Validate we actually got something useful
        if len(combined_text) < MIN_CHARS:
            raise ValueError(
                f"PDF contains less than {MIN_CHARS} characters of text. "
                "This PDF may be scanned or image-only. "
                "Please upload a text-based PDF."
            )

        warning = None
        if was_truncated:
            warning = f"PDF was large — only processed first {MAX_CHARS:,} characters ({pages_to_read} pages)."
        if total_pages > MAX_PAGES:
            warning = f"PDF has {total_pages} pages — only processed first {MAX_PAGES}."

        result = {
            "text": combined_text,
            "page_count": total_pages,
            "pages_processed": pages_to_read,
            "char_count": len(combined_text),
            "was_truncated": was_truncated,
            "warning": warning
        }

        logger.info(
            f"Extracted {len(combined_text):,} chars from {pages_to_read}/{total_pages} pages"
        )
        return result

    except ValueError:
        raise  # Re-raise our validation errors as-is
    except Exception as e:
        logger.error(f"Failed to extract text from PDF: {e}")
        raise
    finally:
        # Always close the PDF file handle
        if doc:
            doc.close()


# ---------------------------------------------------------------------------
# Cleanup temp file after processing
# ---------------------------------------------------------------------------

def cleanup_temp_file(file_path: str):
    """
    Delete the temp PDF file after we're done with it.
    Non-fatal — logs a warning if deletion fails but doesn't crash.
    """
    try:
        if file_path and os.path.exists(file_path):
            os.unlink(file_path)
            logger.info(f"Cleaned up temp file: {file_path}")
    except Exception as e:
        logger.warning(f"Could not delete temp file {file_path}: {e}")


# ---------------------------------------------------------------------------
# Combined helper: download + extract in one call
# ---------------------------------------------------------------------------

def download_and_extract(pdf_url: str) -> dict:
    """
    Convenience function: downloads the PDF from Firebase Storage,
    extracts its text, cleans up the temp file, and returns the result.

    This is what ContentAgent calls — one function, full pipeline.

    Returns the same dict as extract_text(), plus:
    - pdf_url: the original URL (for logging)
    """
    tmp_path = None
    try:
        tmp_path = download_pdf(pdf_url)
        result = extract_text(tmp_path)
        result["pdf_url"] = pdf_url
        return result
    finally:
        # Always clean up, even if extraction failed
        if tmp_path:
            cleanup_temp_file(tmp_path)