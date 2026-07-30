#!/usr/bin/env python3
"""Create a single-page A4 print PDF from an agenda PNG."""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image


def main() -> None:
    parser = argparse.ArgumentParser(description="Create A4 portrait print PDF from PNG.")
    parser.add_argument("input_png", type=Path)
    parser.add_argument("output_pdf", type=Path)
    parser.add_argument("--preview-png", type=Path, default=None)
    parser.add_argument("--dpi", type=int, default=300)
    parser.add_argument("--margin-mm", type=float, default=5.0)
    args = parser.parse_args()

    # A4 portrait at the requested DPI.
    width = round(args.dpi * 210 / 25.4)
    height = round(args.dpi * 297 / 25.4)
    margin = round(args.dpi * args.margin_mm / 25.4)

    source = Image.open(args.input_png).convert("RGB")
    canvas = Image.new("RGB", (width, height), "white")
    box_width = width - 2 * margin
    box_height = height - 2 * margin
    scale = min(box_width / source.width, box_height / source.height)
    new_size = (round(source.width * scale), round(source.height * scale))
    resample = getattr(Image.Resampling, "LANCZOS", Image.LANCZOS)
    source = source.resize(new_size, resample)
    x = (width - new_size[0]) // 2
    y = (height - new_size[1]) // 2
    canvas.paste(source, (x, y))

    args.output_pdf.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(args.output_pdf, "PDF", resolution=args.dpi)
    if args.preview_png:
        args.preview_png.parent.mkdir(parents=True, exist_ok=True)
        canvas.save(args.preview_png, dpi=(args.dpi, args.dpi))


if __name__ == "__main__":
    main()
