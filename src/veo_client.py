"""Veo 3.1 client via the Gemini API (google-genai SDK).

Mirrors kie_client's start-all-then-poll flow so ai_reel can drive either
backend. Veo caps a generation at 8s (vs Seedance's 12s), always renders
audio, and takes the dish photo as an "asset" reference image instead of
Seedance's @image1 URL syntax.
"""

import os
import time

import requests

VEO_MODEL = os.environ.get("VEO_MODEL") or "veo-3.1-fast-generate-preview"
# Veo allows different person_generation values per mode (text-to-video only
# takes allow_all, image modes only allow_adult) — omit unless overridden so
# the API applies the right per-mode default
PERSON_GENERATION = os.environ.get("VEO_PERSON_GENERATION")


def make_client():
    from google import genai

    return genai.Client(
        http_options={"api_version": "v1beta"},
        api_key=os.environ["GEMINI_API_KEY"],
    )


def build_reference(url: str):
    """Fetch the dish photo once; reusable across all generations."""
    from google.genai import types

    resp = requests.get(url, timeout=120)
    resp.raise_for_status()
    clean = url.lower().split("?")[0]
    mime = "image/png" if clean.endswith(".png") else "image/jpeg"
    return types.VideoGenerationReferenceImage(
        image=types.Image(image_bytes=resp.content, mime_type=mime),
        reference_type="asset",
    )


def start_generation(client, prompt: str, reference, duration_s: int):
    """Create one generation; retries 429s — Tier 1 Veo allows only a couple
    of requests per minute, so back-to-back creates trip the rate limiter."""
    from google.genai import types

    config = types.GenerateVideosConfig(
        aspect_ratio="9:16",  # vertical reels render at 720p on Veo
        resolution="720p",
        duration_seconds=duration_s,
        number_of_videos=1,
    )
    if PERSON_GENERATION:
        config.person_generation = PERSON_GENERATION
    if reference is not None:
        config.reference_images = [reference]

    attempts = 5
    for attempt in range(attempts):
        try:
            return client.models.generate_videos(
                model=VEO_MODEL, prompt=prompt, config=config
            )
        except Exception as exc:
            rate_limited = "429" in str(exc) or "RESOURCE_EXHAUSTED" in str(exc)
            if not rate_limited or attempt == attempts - 1:
                raise
            print(f"  Veo rate limit; retrying in 70s ({attempt + 1}/{attempts - 1})", flush=True)
            time.sleep(70)


def wait_and_save(client, operation, path, timeout_s: int = 1200) -> None:
    deadline = time.time() + timeout_s
    while not operation.done:
        if time.time() > deadline:
            raise RuntimeError(f"Veo generation timed out after {timeout_s}s")
        time.sleep(10)
        operation = client.operations.get(operation)
    if operation.error:
        raise RuntimeError(f"Veo generation failed: {operation.error}")
    result = operation.result
    videos = (result.generated_videos or []) if result else []
    if not videos:
        # Safety-filtered outputs come back as filter counts, not videos
        reasons = getattr(result, "rai_media_filtered_reasons", None)
        raise RuntimeError(f"Veo returned no video (filtered: {reasons})")
    video = videos[0].video
    client.files.download(file=video)
    video.save(str(path))
