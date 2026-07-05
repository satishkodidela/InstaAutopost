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
# Cooking shots show hands, which Veo treats as person content
PERSON_GENERATION = os.environ.get("VEO_PERSON_GENERATION") or "allow_adult"


def make_client():
    from google import genai

    return genai.Client(
        http_options={"api_version": "v1beta"},
        api_key=os.environ["GEMINI_API_KEY"],
    )


def _reference_image(url: str):
    from google.genai import types

    resp = requests.get(url, timeout=120)
    resp.raise_for_status()
    clean = url.lower().split("?")[0]
    mime = "image/png" if clean.endswith(".png") else "image/jpeg"
    return types.VideoGenerationReferenceImage(
        image=types.Image(image_bytes=resp.content, mime_type=mime),
        reference_type="asset",
    )


def start_generation(client, prompt: str, ref_image_url: str | None, duration_s: int):
    from google.genai import types

    config = types.GenerateVideosConfig(
        aspect_ratio="9:16",  # vertical reels render at 720p on Veo
        resolution="720p",
        duration_seconds=duration_s,
        number_of_videos=1,
        person_generation=PERSON_GENERATION,
    )
    if ref_image_url:
        config.reference_images = [_reference_image(ref_image_url)]
    return client.models.generate_videos(model=VEO_MODEL, prompt=prompt, config=config)


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
