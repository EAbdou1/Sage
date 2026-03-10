# Finds or generates an image for each slide:
# Strategy: Google Custom Search first → fallback to Imagen 3
# Uploads the winning image to Firebase Storage and returns the public URL.

import os
import io
import logging
import asyncio
import tempfile
import mimetypes
from typing import Optional

import httpx
import firebase_admin
from firebase_admin import storage, credentials
from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SEARCH_API_KEY   = os.getenv("GOOGLE_SEARCH_API_KEY")   # Google Custom Search API key
SEARCH_ENGINE_ID = os.getenv("GOOGLE_SEARCH_ENGINE_ID") # Custom Search Engine ID (cx)
SEARCH_ENDPOINT  = "https://www.googleapis.com/customsearch/v1"

IMAGE_TIMEOUT_SECONDS = 8    # Max wait per image fetch before falling back to Imagen
MAX_IMAGE_SIZE_MB     = 5    # Skip images larger than this
SKIP_IMAGE_TYPES      = {"mcq", "summary"}  # These slide types don't need images

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

# ---------------------------------------------------------------------------
# Gemini client (for Imagen 3)
# ---------------------------------------------------------------------------

client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))

# ---------------------------------------------------------------------------
# Search query builder
# ---------------------------------------------------------------------------

def _build_search_query(slide_title: str, subject: str) -> str:
    """
    Build a targeted medical image search query.
    Generic queries return junk — we need specific, educational results.

    Examples:
      "Cardiac Action Potential" + "Cardiology"
      → "cardiac action potential diagram medical illustration site:edu OR site:nih.gov"
    """
    # Clean up the title
    title = slide_title.strip().lower()

    # Build a query that biases toward educational/medical diagrams
    query = f"{title} {subject.lower()} diagram medical illustration"

    return query


# ---------------------------------------------------------------------------
# Google Custom Search
# ---------------------------------------------------------------------------

async def _search_for_image(query: str) -> Optional[str]:
    """
    Search Google Images for a relevant medical diagram.
    Returns the image URL if a good result is found, None otherwise.

    Requires GOOGLE_SEARCH_API_KEY and GOOGLE_SEARCH_ENGINE_ID in .env
    """
    if not SEARCH_API_KEY or not SEARCH_ENGINE_ID:
        logger.warning("Google Search API key or Engine ID not set — skipping search")
        return None

    params = {
        "key": SEARCH_API_KEY,
        "cx": SEARCH_ENGINE_ID,
        "q": query,
        "searchType": "image",
        "num": 5,                    # Get top 5 results to pick the best
        "imgType": "clipart",        # Prefers diagrams over photos
        "safe": "active",
        "fileType": "jpg,png",
    }

    try:
        async with httpx.AsyncClient(timeout=10) as http:
            response = await http.get(SEARCH_ENDPOINT, params=params)
            response.raise_for_status()
            data = response.json()

        items = data.get("items", [])
        if not items:
            logger.info(f"No search results for: {query}")
            return None

        # Pick the first result that passes validation
        for item in items:
            url = item.get("link", "")
            if url and await _validate_image_url(url):
                logger.info(f"Found image via search: {url[:80]}...")
                return url

        logger.info("No valid images found in search results")
        return None

    except Exception as e:
        logger.warning(f"Google Search failed: {e}")
        return None


async def _validate_image_url(url: str) -> bool:
    """
    Check that an image URL is actually reachable and returns an image.
    Avoids dead links and non-image URLs silently breaking the frontend.
    """
    try:
        async with httpx.AsyncClient(timeout=5) as http:
            # HEAD request only — don't download the whole image just to check
            response = await http.head(url, follow_redirects=True)

        if response.status_code != 200:
            return False

        content_type = response.headers.get("content-type", "")
        if not content_type.startswith("image/"):
            return False

        # Check file size if Content-Length is available
        content_length = response.headers.get("content-length")
        if content_length:
            size_mb = int(content_length) / (1024 * 1024)
            if size_mb > MAX_IMAGE_SIZE_MB:
                logger.info(f"Image too large ({size_mb:.1f}MB): {url[:60]}")
                return False

        return True

    except Exception:
        return False


# ---------------------------------------------------------------------------
# Download image bytes from URL
# ---------------------------------------------------------------------------

async def _download_image(url: str) -> Optional[bytes]:
    """Download image bytes from a validated URL."""
    try:
        async with httpx.AsyncClient(timeout=IMAGE_TIMEOUT_SECONDS) as http:
            response = await http.get(url, follow_redirects=True)
            response.raise_for_status()
            return response.content
    except Exception as e:
        logger.warning(f"Failed to download image from {url[:60]}: {e}")
        return None


# ---------------------------------------------------------------------------
# Imagen 3 generation
# ---------------------------------------------------------------------------

async def _generate_with_imagen(slide_title: str, slide_content: str, subject: str) -> Optional[bytes]:
    """
    Generate a medical illustration using Imagen 3.
    Falls back when Google Search finds nothing usable.

    Returns raw image bytes, or None if generation fails.
    """
    prompt = (
        f"A clean, professional medical illustration for a teaching slide about: "
        f"'{slide_title}'. Subject: {subject}. "
        f"Context: {slide_content[:200]}. "
        f"Style: medical textbook diagram, labeled, white background, "
        f"educational, no text overlays, clear and accurate anatomy."
    )

    try:
        # Run the synchronous Gemini call in a thread so we don't block the event loop
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: client.models.generate_images(
                model="imagen-3.0-generate-002",
                prompt=prompt,
                config=types.GenerateImagesConfig(
                    number_of_images=1,
                    aspect_ratio="16:9",
                    safety_filter_level="block_low_and_above",
                )
            )
        )

        if response.generated_images:
            image_bytes = response.generated_images[0].image.image_bytes
            logger.info(f"Imagen 3 generated image for: {slide_title}")
            return image_bytes

        logger.warning(f"Imagen 3 returned no images for: {slide_title}")
        return None

    except Exception as e:
        logger.warning(f"Imagen 3 failed for '{slide_title}': {e}")
        return None


# ---------------------------------------------------------------------------
# Upload image to Firebase Storage
# ---------------------------------------------------------------------------

def _upload_to_firebase(image_bytes: bytes, session_id: str,
                         slide_id: int, content_type: str = "image/jpeg") -> str:
    """
    Upload image bytes to Firebase Storage.
    Returns the public download URL.

    Path pattern: sessions/{sessionId}/slides/{slideId}.jpg
    """
    ext = mimetypes.guess_extension(content_type) or ".jpg"
    blob_path = f"sessions/{session_id}/slides/{slide_id}{ext}"

    bucket = storage.bucket()
    blob = bucket.blob(blob_path)
    blob.upload_from_string(image_bytes, content_type=content_type)

    # Make it publicly readable
    blob.make_public()

    logger.info(f"Uploaded image to Firebase: {blob_path}")
    return blob.public_url


# ---------------------------------------------------------------------------
# Main entry point: get image for one slide
# ---------------------------------------------------------------------------

async def get_image_for_slide(
    session_id: str,
    slide_id: int,
    slide_title: str,
    slide_content: str,
    subject: str
) -> dict:
    """
    Full image pipeline for a single slide:
    1. Try Google Image Search
    2. If nothing found → generate with Imagen 3
    3. Upload result to Firebase Storage
    4. Return { imageUrl, imageAlt, imageSource }

    Returns a dict with imageUrl=None if everything fails (non-fatal).
    """
    query = _build_search_query(slide_title, subject)
    image_bytes = None
    image_source = None
    content_type = "image/jpeg"

    # --- Strategy 1: Google Image Search ---
    try:
        async with asyncio.timeout(IMAGE_TIMEOUT_SECONDS):
            search_url = await _search_for_image(query)

            if search_url:
                image_bytes = await _download_image(search_url)
                if image_bytes:
                    image_source = "search"
                    # Guess content type from URL
                    if search_url.lower().endswith(".png"):
                        content_type = "image/png"

    except asyncio.TimeoutError:
        logger.warning(f"Image search timed out for slide {slide_id} — falling back to Imagen 3")
    except Exception as e:
        logger.warning(f"Image search error for slide {slide_id}: {e}")

    # --- Strategy 2: Imagen 3 fallback ---
    if not image_bytes:
        try:
            async with asyncio.timeout(30):  # Imagen can be slow
                image_bytes = await _generate_with_imagen(slide_title, slide_content, subject)
                if image_bytes:
                    image_source = "generated"
                    content_type = "image/png"
        except asyncio.TimeoutError:
            logger.warning(f"Imagen 3 timed out for slide {slide_id}")
        except Exception as e:
            logger.warning(f"Imagen 3 error for slide {slide_id}: {e}")

    # --- Upload if we got anything ---
    if image_bytes:
        try:
            image_url = _upload_to_firebase(image_bytes, session_id, slide_id, content_type)
            return {
                "imageUrl": image_url,
                "imageAlt": f"Illustration: {slide_title}",
                "imageSource": image_source
            }
        except Exception as e:
            logger.error(f"Failed to upload image for slide {slide_id}: {e}")

    # Non-fatal — slide renders without an image
    logger.warning(f"No image obtained for slide {slide_id}: {slide_title}")
    return {
        "imageUrl": None,
        "imageAlt": "",
        "imageSource": None
    }


# ---------------------------------------------------------------------------
# Process all slides in parallel
# ---------------------------------------------------------------------------

async def fetch_images_for_all_slides(session_id: str, slides: list, subject: str) -> list:
    """
    Fetch images for all slides concurrently using asyncio.gather.
    Skips MCQ and summary slides — they don't need images.

    Returns the slides list with imageUrl/imageAlt/imageSource filled in.
    All failures are non-fatal — a slide without an image is fine.
    """
    tasks = []
    skip_indices = []

    for i, slide in enumerate(slides):
        if slide.get("type") in SKIP_IMAGE_TYPES:
            skip_indices.append(i)
            tasks.append(asyncio.sleep(0))  # placeholder coroutine
        else:
            tasks.append(get_image_for_slide(
                session_id=session_id,
                slide_id=slide["id"],
                slide_title=slide["title"],
                slide_content=slide.get("content", ""),
                subject=subject
            ))

    logger.info(
        f"Fetching images for {len(tasks) - len(skip_indices)} slides "
        f"(skipping {len(skip_indices)} MCQ/summary slides)"
    )

    # Run all image fetches in parallel — return_exceptions prevents one failure
    # from cancelling the rest
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Merge results back into slides
    for i, result in enumerate(results):
        if i in skip_indices:
            continue
        if isinstance(result, Exception):
            logger.warning(f"Image fetch exception for slide {i}: {result}")
            continue
        if isinstance(result, dict) and result.get("imageUrl"):
            slides[i]["imageUrl"]    = result["imageUrl"]
            slides[i]["imageAlt"]    = result["imageAlt"]
            slides[i]["imageSource"] = result["imageSource"]

    return slides