"""Image analysis with real pixels, not metadata.

There is no OCR in this deployment (Sarvam's vision endpoint is beta-gated), so
the image path is honest about what it can measure: dimensions, the actual
palette from pixels, the dominant text/background pair and the WCAG contrast
between them, plus edge density as a rough "is this a text-heavy poster" signal.
Copy baked into a picture still has to be pasted to be reviewed for claims.
"""
from __future__ import annotations

import io
from collections import Counter

from PIL import Image, ImageFilter

MAX_SIDE = 900
PALETTE_SIZE = 5


def _rgb(hex_code: str) -> tuple[int, int, int]:
    h = hex_code.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def _hex(rgb: tuple[int, int, int]) -> str:
    return "#{:02X}{:02X}{:02X}".format(*rgb)


def contrast_ratio(fg: tuple[int, int, int], bg: tuple[int, int, int]) -> float:
    def lum(c: tuple[int, int, int]) -> float:
        def chan(v: int) -> float:
            s = v / 255
            return s / 12.92 if s <= 0.03928 else ((s + 0.055) / 1.055) ** 2.4

        r, g, b = c
        return 0.2126 * chan(r) + 0.7152 * chan(g) + 0.0722 * chan(b)

    l1, l2 = lum(fg), lum(bg)
    hi, lo = max(l1, l2), min(l1, l2)
    return round((hi + 0.05) / (lo + 0.05), 2)


def analyze(data: bytes) -> dict:
    """Return measurable facts about an image. Never guesses."""
    image = Image.open(io.BytesIO(data))
    width, height = image.size
    image = image.convert("RGB")
    if max(width, height) > MAX_SIDE:
        scale = MAX_SIDE / max(width, height)
        image = image.resize((max(1, int(width * scale)), max(1, int(height * scale))))

    quantised = image.quantize(colors=PALETTE_SIZE)
    palette = quantised.getpalette() or []
    counts = Counter(quantised.getdata())
    colours = []
    for index, count in counts.most_common(PALETTE_SIZE):
        rgb = tuple(palette[index * 3 : index * 3 + 3])
        if len(rgb) != 3:
            continue
        share = round(100 * count / max(1, sum(counts.values())), 1)
        colours.append({"hex": _hex(rgb), "share": share})

    background = _rgb(colours[0]["hex"]) if colours else (255, 255, 255)
    # the most common colour that is far enough from the background to be text
    text = None
    for item in colours[1:]:
        candidate = _rgb(item["hex"])
        if contrast_ratio(candidate, background) >= 1.6:
            text = candidate
            break
    ratio = contrast_ratio(text, background) if text else None

    grey = image.convert("L")
    edges = grey.filter(ImageFilter.FIND_EDGES)
    histogram = edges.histogram()
    total = max(1, sum(histogram))
    edge_density = round(sum(histogram[40:]) / total, 4)

    return {
        "width": width,
        "height": height,
        "aspect": round(width / height, 3) if height else None,
        "palette": [c["hex"] for c in colours],
        "palette_share": colours,
        "background": _hex(background),
        "text_colour": _hex(text) if text else None,
        "contrast_ratio": ratio,
        "edge_density": edge_density,
        "likely_text_heavy": edge_density > 0.06,
        "ocr_available": False,
        "note": (
            "Measured from pixels: palette, dominant text/background contrast and layout density. "
            "Text baked into the image is not read automatically — paste the on-screen copy to have "
            "it reviewed for claims and legal triggers."
        ),
    }


def palette_delta(asset_palette: list[str], brand_palette: list[str]) -> list[str]:
    """Colours in the image that are not in the approved brand palette."""
    allowed = {c.upper().lstrip("#") for c in brand_palette}
    return [c for c in asset_palette if c.upper().lstrip("#") not in allowed]
