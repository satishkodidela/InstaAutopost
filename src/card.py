"""Render the daily news-highlights card as a 1080x1350 JPEG."""

from PIL import Image, ImageDraw, ImageFont

WIDTH, HEIGHT = 1080, 1350
MARGIN = 70

BG_TOP = (13, 22, 38)
BG_BOTTOM = (24, 42, 72)
ACCENT_SAFFRON = (255, 153, 51)
ACCENT_GREEN = (19, 136, 8)
TEXT_WHITE = (245, 247, 250)
TEXT_MUTED = (150, 165, 185)

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


def make_card(headlines: list[dict], date_label: str, out_path: str) -> None:
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

    title_font = _font(FONT_CANDIDATES_BOLD, 66)
    date_font = _font(FONT_CANDIDATES_REGULAR, 34)
    num_font = _font(FONT_CANDIDATES_BOLD, 44)
    head_font = _font(FONT_CANDIDATES_BOLD, 40)
    src_font = _font(FONT_CANDIDATES_REGULAR, 28)
    footer_font = _font(FONT_CANDIDATES_REGULAR, 28)

    y = 80
    draw.text((MARGIN, y), "INDIA DAILY NEWS", font=title_font, fill=TEXT_WHITE)
    y += 84
    draw.text((MARGIN, y), date_label, font=date_font, fill=ACCENT_SAFFRON)
    y += 60
    draw.line([(MARGIN, y), (WIDTH - MARGIN, y)], fill=(60, 78, 105), width=2)
    y += 44

    text_x = MARGIN + 78
    max_text_width = WIDTH - text_x - MARGIN

    for i, item in enumerate(headlines, start=1):
        lines = _wrap(draw, item["title"], head_font, max_text_width)[:3]
        draw.text((MARGIN, y), f"{i:02d}", font=num_font, fill=ACCENT_SAFFRON)
        for line in lines:
            draw.text((text_x, y), line, font=head_font, fill=TEXT_WHITE)
            y += 52
        draw.text((text_x, y + 2), item["source"], font=src_font, fill=TEXT_MUTED)
        y += 66

    footer = "Sources: TOI, The Hindu, NDTV, Indian Express"
    fw = draw.textlength(footer, font=footer_font)
    draw.text(((WIDTH - fw) / 2, HEIGHT - 70), footer, font=footer_font, fill=TEXT_MUTED)

    img.save(out_path, "JPEG", quality=90)
