"""Render the daily news carousel cards as 1080x1350 JPEGs."""

from PIL import Image, ImageDraw, ImageFont

WIDTH, HEIGHT = 1080, 1350
MARGIN = 70

BG_TOP = (13, 22, 38)
BG_BOTTOM = (24, 42, 72)
ACCENT_SAFFRON = (255, 153, 51)
ACCENT_GREEN = (19, 136, 8)
TEXT_WHITE = (245, 247, 250)
TEXT_MUTED = (150, 165, 185)
TEXT_SUMMARY = (196, 207, 222)

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


def _wrap_ellipsis(draw, text, font, max_width, max_lines):
    lines = _wrap(draw, text, font, max_width)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1].rstrip(".,;: ") + "…"
    return lines


def _new_canvas() -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("RGB", (WIDTH, HEIGHT))
    draw = ImageDraw.Draw(img)

    # Vertical gradient background
    for y in range(HEIGHT):
        t = y / HEIGHT
        color = tuple(int(a + (b - a) * t) for a, b in zip(BG_TOP, BG_BOTTOM))
        draw.line([(0, y), (WIDTH, y)], fill=color)

    # Tricolor top strip
    strip_h = 14
    draw.rectangle([0, 0, WIDTH // 3, strip_h], fill=ACCENT_SAFFRON)
    draw.rectangle([WIDTH // 3, 0, 2 * WIDTH // 3, strip_h], fill=TEXT_WHITE)
    draw.rectangle([2 * WIDTH // 3, 0, WIDTH, strip_h], fill=ACCENT_GREEN)
    return img, draw


def _footer(draw: ImageDraw.ImageDraw, page: int, total: int) -> None:
    font = _font(FONT_CANDIDATES_REGULAR, 28)
    text = "Sources: TOI, The Hindu, NDTV, Indian Express"
    fw = draw.textlength(text, font=font)
    draw.text(((WIDTH - fw) / 2, HEIGHT - 70), text, font=font, fill=TEXT_MUTED)

    # Page dots
    dot_r, gap = 7, 30
    total_w = (total - 1) * gap
    x0 = (WIDTH - total_w) / 2
    for i in range(total):
        cx = x0 + i * gap
        color = ACCENT_SAFFRON if i == page else (70, 88, 115)
        draw.ellipse([cx - dot_r, HEIGHT - 120 - dot_r, cx + dot_r, HEIGHT - 120 + dot_r], fill=color)


def make_cover(headlines: list[dict], date_label: str, total_pages: int, out_path: str) -> None:
    img, draw = _new_canvas()

    title_font = _font(FONT_CANDIDATES_BOLD, 96)
    date_font = _font(FONT_CANDIDATES_REGULAR, 40)
    teaser_font = _font(FONT_CANDIDATES_BOLD, 38)
    swipe_font = _font(FONT_CANDIDATES_BOLD, 36)

    y = 190
    for word in ("INDIA", "DAILY", "NEWS"):
        draw.text((MARGIN, y), word, font=title_font, fill=TEXT_WHITE)
        y += 110
    draw.rectangle([MARGIN, y + 10, MARGIN + 260, y + 18], fill=ACCENT_SAFFRON)
    y += 60
    draw.text((MARGIN, y), date_label, font=date_font, fill=ACCENT_SAFFRON)
    y += 110

    # Teaser: top three headlines, one line each
    max_text_width = WIDTH - MARGIN * 2 - 40
    for item in headlines[:3]:
        line = _wrap_ellipsis(draw, item["title"], teaser_font, max_text_width, 1)[0]
        draw.text((MARGIN, y), "•", font=teaser_font, fill=ACCENT_SAFFRON)
        draw.text((MARGIN + 40, y), line, font=teaser_font, fill=TEXT_SUMMARY)
        y += 64

    swipe = "Swipe for today's top stories  →"
    sw = draw.textlength(swipe, font=swipe_font)
    draw.text(((WIDTH - sw) / 2, HEIGHT - 210), swipe, font=swipe_font, fill=ACCENT_SAFFRON)

    _footer(draw, 0, total_pages)
    img.save(out_path, "JPEG", quality=90)


def make_story_card(
    items: list[dict],
    start_number: int,
    date_label: str,
    page: int,
    total_pages: int,
    out_path: str,
) -> None:
    img, draw = _new_canvas()

    header_font = _font(FONT_CANDIDATES_BOLD, 48)
    date_font = _font(FONT_CANDIDATES_REGULAR, 30)
    num_font = _font(FONT_CANDIDATES_BOLD, 44)
    head_font = _font(FONT_CANDIDATES_BOLD, 40)
    sum_font = _font(FONT_CANDIDATES_REGULAR, 30)
    src_font = _font(FONT_CANDIDATES_REGULAR, 26)

    y = 70
    draw.text((MARGIN, y), "INDIA DAILY NEWS", font=header_font, fill=TEXT_WHITE)
    dw = draw.textlength(date_label, font=date_font)
    draw.text((WIDTH - MARGIN - dw, y + 16), date_label, font=date_font, fill=ACCENT_SAFFRON)
    y += 78
    draw.line([(MARGIN, y), (WIDTH - MARGIN, y)], fill=(60, 78, 105), width=2)
    y += 48

    text_x = MARGIN + 82
    max_text_width = WIDTH - text_x - MARGIN

    for i, item in enumerate(items):
        draw.text((MARGIN, y), f"{start_number + i:02d}", font=num_font, fill=ACCENT_SAFFRON)
        for line in _wrap_ellipsis(draw, item["title"], head_font, max_text_width, 3):
            draw.text((text_x, y), line, font=head_font, fill=TEXT_WHITE)
            y += 52
        y += 6
        if item.get("summary"):
            for line in _wrap_ellipsis(draw, item["summary"], sum_font, max_text_width, 3):
                draw.text((text_x, y), line, font=sum_font, fill=TEXT_SUMMARY)
                y += 42
        draw.text((text_x, y + 4), item["source"], font=src_font, fill=TEXT_MUTED)
        y += 76

    _footer(draw, page, total_pages)
    img.save(out_path, "JPEG", quality=90)
