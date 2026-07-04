# Owner feedback log

Standing rules from the account owner. Every content change must respect
these; add new entries at the top when feedback comes in.

## 2026-07-04 — first AI reel review ("very bad")
- ❌ Voiceover read "180C/gas 4" as digits → ✅ fixed: temperatures/units/
  times are converted to everyday words (high/medium/low heat, "a few
  minutes", "some") before TTS (`voiceover._humanize`).
- ❌ Shots showed a different-looking dish in hook vs cooking vs reveal →
  ✅ fixed: every Seedance shot now passes the real dish photo via
  `reference_image_urls` + prompts demand consistency with the reference.
- ❌ Hook claimed "N ingredients" but they were never shown → ✅ fixed:
  shot 2 overlays the key ingredient list on screen.
- Standing: reels must be full AI video (no card stills), < 45–60s.
- Standing: Telugu voiceover must be conversational/code-mixed, never
  formal or number-heavy.

## Earlier
- No card-slideshow reels (rejected 2026-07-04).
- Research before building new features; ask clarifying questions first.
