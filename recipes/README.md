# Custom recipe queue

Drop `.json` files into `recipes/queue/` and the daily run uses them
**before** falling back to TheMealDB — oldest filename first, one per day.
The consumed file is deleted automatically (committed by the workflow).

## Schema (`recipes/queue/2026-07-05-biryani.json`)

```json
{
  "name": "Hyderabadi Veg Biryani",
  "category": "Rice",
  "area": "Telugu",
  "image_url": "https://example.com/photo-of-the-dish.jpg",
  "ingredients": [
    {"name": "Basmati rice", "measure": "2 cups"},
    {"name": "Mixed vegetables", "measure": "300g"},
    {"name": "Biryani masala", "measure": "2 tbsp"}
  ],
  "steps": [
    "Soak the rice for 30 minutes and cook until 70 percent done.",
    "Fry the vegetables with masala until soft.",
    "Layer rice and vegetables, cover and cook on low heat."
  ],
  "youtube": "",
  "tags": "biryani,telugu"
}
```

Required: `name`, `image_url` (public URL of a real photo of the dish —
it becomes the carousel cover AND the visual reference every AI video
shot is anchored to), `ingredients`, `steps`. Everything else optional.
