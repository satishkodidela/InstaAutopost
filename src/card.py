"""Render the daily recipe carousel cards as 1080x1350 JPEGs."""

import io

from PIL import Image, ImageDraw, ImageFont

WIDTH, HEIGHT = 1080, 1350
MARGIN = 80

CREAM = (251, 243, 231)
DARK = (46, 31, 20)
ACCENT = (232, 93, 38)
MUTED = (138, 117, 99)
BAND = (36, 24, 16)

FONT_CANDIDATES_BOLD = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",  # GitHub Actions (ubuntu)
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",  # macOS
    "/System/Library/Fonts/Helvetica.ttc",
]
FONT_CANDIDATES_REGULAR = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
]


def _font(candidates: list[str], size: int) -> ImageFont.FreeTypeFont:
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default(size)


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> list[str]:
    words = text.split()
    lines, current = [], ""
    for word in words:
        trial = f"{current} {word}".strip()
        if draw.textlength(trial, font=font) <= max_width:
            current = trial
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _text_card_canvas(header: str) -> tuple[Image.Image, ImageDraw.ImageDraw, int]:
    """Cream card with the accent strip and a section header. Returns start y."""
    img = Image.new("RGB", (WIDTH, HEIGHT), CREAM)
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, WIDTH, 14], fill=ACCENT)

    brand_font = _font(FONT_CANDIDATES_BOLD, 34)
    header_font = _font(FONT_CANDIDATES_BOLD, 58)

    y = 70
    draw.text((MARGIN, y), "DAILY RECIPE", font=brand_font, fill=ACCENT)
    y += 62
    draw.text((MARGIN, y), header, font=header_font, fill=DARK)
    y += 78
    draw.line([(MARGIN, y), (WIDTH - MARGIN, y)], fill=(216, 198, 178), width=3)
    return img, draw, y + 50


def _footer(
    draw: ImageDraw.ImageDraw,
    page: int,
    total: int,
    dark_bg: bool = False,
    y: int = HEIGHT - 60,
) -> None:
    dot_r, gap = 7, 30
    x0 = (WIDTH - (total - 1) * gap) / 2
    inactive = (90, 70, 55) if dark_bg else (216, 198, 178)
    for i in range(total):
        cx = x0 + i * gap
        draw.ellipse(
            [cx - dot_r, y - dot_r, cx + dot_r, y + dot_r],
            fill=ACCENT if i == page else inactive,
        )


def make_cover(photo: bytes, recipe: dict, total_pages: int, out_path: str) -> None:
    img = Image.new("RGB", (WIDTH, HEIGHT), BAND)
    draw = ImageDraw.Draw(img)

    # Dish photo: square, full width, top of the card
    dish = Image.open(io.BytesIO(photo)).convert("RGB")
    side = min(dish.size)
    left = (dish.width - side) // 2
    top = (dish.height - side) // 2
    dish = dish.crop((left, top, left + side, top + side)).resize(
        (WIDTH, WIDTH), Image.LANCZOS
    )
    img.paste(dish, (0, 0))

    name_font = _font(FONT_CANDIDATES_BOLD, 54)
    meta_font = _font(FONT_CANDIDATES_BOLD, 30)

    # Bottom band with dish name + cuisine
    name_lines = _wrap(draw, recipe["name"], name_font, WIDTH - 2 * MARGIN)[:2]
    y = WIDTH + (96 if len(name_lines) == 1 else 26)
    for line in name_lines:
        lw = draw.textlength(line, font=name_font)
        draw.text(((WIDTH - lw) / 2, y), line, font=name_font, fill=CREAM)
        y += 64

    meta = " • ".join(filter(None, [recipe["area"], recipe["category"]]))
    if meta:
        mw = draw.textlength(meta, font=meta_font)
        draw.text(((WIDTH - mw) / 2, y + 8), meta, font=meta_font, fill=ACCENT)

    _footer(draw, 0, total_pages, dark_bg=True, y=HEIGHT - 42)
    img.save(out_path, "JPEG", quality=90)


def make_ingredients_card(recipe: dict, page: int, total_pages: int, out_path: str) -> None:
    img, draw, y = _text_card_canvas("Ingredients")

    item_font = _font(FONT_CANDIDATES_REGULAR, 36)
    measure_font = _font(FONT_CANDIDATES_BOLD, 36)

    items = recipe["ingredients"]
    two_columns = len(items) > 12
    col_width = (WIDTH - 2 * MARGIN - 60) // 2 if two_columns else WIDTH - 2 * MARGIN
    line_h = 64
    col_x = [MARGIN, MARGIN + col_width + 60]
    per_col = (len(items) + 1) // 2 if two_columns else len(items)

    for i, item in enumerate(items):
        col = i // per_col if two_columns else 0
        row = i % per_col if two_columns else i
        x = col_x[col]
        yy = y + row * line_h
        draw.ellipse([x, yy + 16, x + 10, yy + 26], fill=ACCENT)
        text = f"{item['measure']} {item['name']}".strip()
        line = _wrap(draw, text, item_font, col_width - 30)[0]
        if line != text:
            line = line.rstrip(",. ") + "…"
        draw.text((x + 28, yy), line, font=item_font, fill=DARK)

    _footer(draw, page, total_pages)
    img.save(out_path, "JPEG", quality=90)


def make_steps_cards(
    recipe: dict, first_page: int, out_paths: list[str]
) -> int:
    """Render instruction cards, filling as many of `out_paths` as needed.

    Returns the number of cards written. Steps that don't fit on the
    last card are dropped with a "full recipe in caption" note.
    """
    step_font = _font(FONT_CANDIDATES_REGULAR, 34)
    num_font = _font(FONT_CANDIDATES_BOLD, 38)
    note_font = _font(FONT_CANDIDATES_REGULAR, 28)

    line_h = 48
    step_gap = 30
    bottom_limit = HEIGHT - 140
    text_x = MARGIN + 66
    max_text_width = WIDTH - text_x - MARGIN

    # Pre-measure wrapping with a scratch canvas
    scratch = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    wrapped = [
        _wrap(scratch, step, step_font, max_text_width) for step in recipe["steps"]
    ]

    cards: list[list[int]] = [[]]  # step indices per card
    y = 260  # matches _text_card_canvas start
    for i, lines in enumerate(wrapped):
        height = len(lines) * line_h + step_gap
        if y + height > bottom_limit and cards[-1]:
            if len(cards) == len(out_paths):
                break
            cards.append([])
            y = 260
        cards[-1].append(i)
        y += height

    shown = sum(len(c) for c in cards)
    total_pages = first_page + len(cards)

    for card_idx, step_indices in enumerate(cards):
        header = "Method" if len(cards) == 1 else f"Method ({card_idx + 1}/{len(cards)})"
        img, draw, y = _text_card_canvas(header)
        for i in step_indices:
            draw.text((MARGIN, y), f"{i + 1:02d}", font=num_font, fill=ACCENT)
            for line in wrapped[i]:
                draw.text((text_x, y), line, font=step_font, fill=DARK)
                y += line_h
            y += step_gap
        if card_idx == len(cards) - 1 and shown < len(recipe["steps"]):
            note = "Continued in caption — full recipe there!"
            nw = draw.textlength(note, font=note_font)
            draw.text(((WIDTH - nw) / 2, HEIGHT - 110), note, font=note_font, fill=MUTED)
        _footer(draw, first_page + card_idx, total_pages)
        img.save(out_paths[card_idx], "JPEG", quality=90)

    return len(cards)
