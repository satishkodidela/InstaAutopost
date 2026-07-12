"""Boundary keyframe chain for reel clips (first/last-frame conditioning).

Clip i is generated with first_frame=K[i] and last_frame=K[i+1]; adjacent
clips share their boundary image exactly, so clip-to-clip cuts are
continuous. K0 recomposes the hero photo as the opening close-up, middle
keyframes advance the cooking state by editing the previous keyframe
(same kitchen, props and lighting each hop), and the final keyframe
mirrors K0 so the reel loops seamlessly.
"""

import os

from kie_client import create_task, poll_task

EDIT_MODEL = os.environ.get("KIE_IMAGE_EDIT_MODEL") or "google/nano-banana-edit"
IMAGE_EXTS = "jpg|jpeg|png|webp"


def _edit(prompt: str, image_urls: list[str], key: str) -> str:
    task_id = create_task(
        EDIT_MODEL,
        {
            "prompt": prompt,
            "image_urls": image_urls,
            "aspect_ratio": "9:16",
            "output_format": "png",
        },
        key,
    )
    return poll_task(task_id, key, exts=IMAGE_EXTS)


def state_text(beat: str) -> str:
    """Beat text minus the camera direction, which is meaningless in a still."""
    return beat.split("Camera:")[0].strip().rstrip(".,;: ")


def generate_keyframes(
    recipe: dict,
    beats: list[str],
    beats_per_gen: int,
    n_gens: int,
    style: str,
    hero_url: str,
    key: str,
) -> list[str]:
    """n_gens + 1 Kie-hosted 9:16 keyframe URLs, K0..Kn."""
    name = recipe["name"]
    scene_lock = (
        "Keep the exact same kitchen, counter, utensils, props and lighting "
        "as the input image."
    )
    k0 = _edit(
        f"Using this photo of {name} for the dish's exact appearance, create "
        f"a vertical 9:16 cinematic food-film frame showing: "
        f"{state_text(beats[0])}. {style}",
        [hero_url],
        key,
    )
    frames = [k0]
    # One boundary keyframe per clip cut, depicting the cooking state where
    # the next clip picks up (the first beat of that clip's chunk)
    for g in range(1, n_gens):
        beat = state_text(beats[g * beats_per_gen])
        frames.append(
            _edit(
                f"{scene_lock} Now show this stage of cooking {name}: {beat}. "
                f"Vertical 9:16 cinematic food-film frame. {style}",
                [frames[-1], hero_url],
                key,
            )
        )
    # The final keyframe returns to K0's framing so the reel loops seamlessly
    frames.append(
        _edit(
            f"Match the framing and composition of the first input image "
            f"exactly: the finished {name}, garnished, steam rising, glossy. "
            f"Keep the kitchen, props and lighting of the second input image. "
            f"Vertical 9:16 cinematic food-film frame. {style}",
            [k0, frames[-1]],
            key,
        )
    )
    return frames
