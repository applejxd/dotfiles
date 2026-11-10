#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps


def parse_size(value: str) -> tuple[int, int]:
    try:
        width, height = value.lower().split("x", maxsplit=1)
        result = int(width), int(height)
    except (TypeError, ValueError) as exc:
        raise argparse.ArgumentTypeError("Size must look like 1600x1000") from exc
    if min(result) <= 0:
        raise argparse.ArgumentTypeError("Size values must be positive")
    return result


def font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    )
    for candidate in candidates:
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size=size)
    return ImageFont.load_default()


def trim_uniform_edges(image: Image.Image, tolerance: int = 12) -> Image.Image:
    rgb = image.convert("RGB")
    background = Image.new("RGB", rgb.size, rgb.getpixel((0, 0)))
    diff = ImageOps.difference(rgb, background).convert("L")
    diff = diff.point(lambda value: 255 if value > tolerance else 0)
    bbox = diff.getbbox()
    return image.crop(bbox) if bbox else image


def rounded_mask(size: tuple[int, int], radius: int) -> Image.Image:
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, *size), radius=radius, fill=255)
    return mask


def load_callouts(path: Path | None) -> list[dict[str, Any]]:
    if not path:
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("Callouts must be a JSON array.")
    return [item for item in data if isinstance(item, dict)]


def compose(
    source: Path,
    output: Path,
    canvas: tuple[int, int],
    caption: str,
    callouts: list[dict[str, Any]],
    do_trim: bool,
) -> None:
    image = Image.open(source).convert("RGBA")
    if do_trim:
        image = trim_uniform_edges(image).convert("RGBA")

    width, height = canvas
    padding = round(min(width, height) * 0.065)
    caption_height = round(height * 0.09) if caption else 0
    available = (width - 2 * padding, height - 2 * padding - caption_height)
    scale = min(available[0] / image.width, available[1] / image.height)
    resized = image.resize(
        (max(1, round(image.width * scale)), max(1, round(image.height * scale))),
        Image.Resampling.LANCZOS,
    )

    background = Image.new("RGBA", canvas, "#E9EDF3")
    gradient = Image.new("RGBA", canvas)
    gradient_draw = ImageDraw.Draw(gradient)
    for y in range(height):
        mix = y / max(1, height - 1)
        color = (
            round(244 - 18 * mix),
            round(247 - 15 * mix),
            round(251 - 8 * mix),
            255,
        )
        gradient_draw.line((0, y, width, y), fill=color)
    background.alpha_composite(gradient)

    x = (width - resized.width) // 2
    y = padding + max(0, (available[1] - resized.height) // 2)
    radius = max(8, round(min(resized.size) * 0.02))

    shadow = Image.new("RGBA", canvas, (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow)
    shadow_draw.rounded_rectangle(
        (x + 8, y + 12, x + resized.width + 8, y + resized.height + 12),
        radius=radius,
        fill=(15, 23, 42, 70),
    )
    shadow = shadow.filter(ImageFilter.GaussianBlur(radius=18))
    background.alpha_composite(shadow)

    mask = rounded_mask(resized.size, radius)
    background.paste(resized, (x, y), mask)
    draw = ImageDraw.Draw(background)
    draw.rounded_rectangle(
        (x, y, x + resized.width, y + resized.height),
        radius=radius,
        outline=(255, 255, 255, 210),
        width=max(2, width // 800),
    )

    label_font = font(max(18, round(height * 0.027)))
    for index, item in enumerate(callouts, start=1):
        raw_box = item.get("box")
        if not isinstance(raw_box, list) or len(raw_box) != 4:
            continue
        bx, by, bw, bh = (float(value) for value in raw_box)
        rect = (
            round(x + bx * resized.width),
            round(y + by * resized.height),
            round(x + (bx + bw) * resized.width),
            round(y + (by + bh) * resized.height),
        )
        color = item.get("color", "#FF5A36")
        draw.rounded_rectangle(rect, radius=10, outline=color, width=max(4, width // 350))
        label = str(item.get("label", index))
        label_bbox = draw.textbbox((0, 0), label, font=label_font)
        label_w = label_bbox[2] - label_bbox[0] + 22
        label_h = label_bbox[3] - label_bbox[1] + 14
        label_x = max(x, min(rect[0], x + resized.width - label_w))
        label_y = max(y, rect[1] - label_h - 8)
        draw.rounded_rectangle(
            (label_x, label_y, label_x + label_w, label_y + label_h),
            radius=label_h // 2,
            fill=color,
        )
        draw.text(
            (label_x + 11, label_y + 5),
            label,
            font=label_font,
            fill="white",
        )

    if caption:
        caption_font = font(max(22, round(height * 0.032)))
        caption_box = draw.textbbox((0, 0), caption, font=caption_font)
        caption_w = caption_box[2] - caption_box[0]
        draw.text(
            ((width - caption_w) // 2, height - padding - caption_height // 2),
            caption,
            font=caption_font,
            fill="#273449",
            anchor="lm",
        )

    output.parent.mkdir(parents=True, exist_ok=True)
    background.convert("RGB").save(output, quality=95)


def main() -> int:
    parser = argparse.ArgumentParser(description="Frame and annotate a screenshot.")
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--canvas", type=parse_size, default=(1600, 1000))
    parser.add_argument("--caption", default="")
    parser.add_argument("--callouts", type=Path)
    parser.add_argument("--no-trim", action="store_true")
    args = parser.parse_args()
    compose(
        args.input,
        args.output,
        args.canvas,
        args.caption,
        load_callouts(args.callouts),
        not args.no_trim,
    )
    print(f"Wrote framed screenshot: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
