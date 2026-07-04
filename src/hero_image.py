"""Generate a hero photo of a dish (for recipe-bank entries without one).

The returned Kie-hosted URL doubles as the carousel cover source and the
@image1 visual anchor for every video shot in the same run.
"""

import os

from kie_client import create_task, poll_task

MODEL = os.environ.get("KIE_IMAGE_MODEL") or "seedream/5-lite-text-to-image"


def hero_prompt(recipe: dict) -> str:
    name = recipe["name"]
    area = recipe.get("area") or "South Indian"
    key_ing = ", ".join(i["name"] for i in recipe["ingredients"][:4])
    return (
        f"Professional food photography of {name}, traditional {area} dish "
        f"made with {key_ing}, served in authentic brass or steel ware on a "
        f"dark wood table with banana leaf accents, backlit steam rising, "
        f"garnished with fresh coriander and curry leaves, glossy appetizing "
        f"texture, warm golden 45-degree side lighting, shallow depth of "
        f"field, photorealistic, overhead three-quarter angle"
    )


def generate_hero(recipe: dict, key: str) -> str:
    task_id = create_task(
        MODEL,
        {"prompt": hero_prompt(recipe), "aspect_ratio": "3:4", "quality": "basic"},
        key,
    )
    return poll_task(task_id, key, exts="jpg|jpeg|png|webp")
